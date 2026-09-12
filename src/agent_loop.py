"""Bounded deterministic agent pipeline with stable SSE events."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydantic import ValidationError

from src.agent_tools import (
    CALCULATOR_TOOLS,
    RETRIEVAL_TOOLS,
    TOOL_LABELS,
    execute_tool,
    validate_arguments,
)
from src.citation import CitationTracker
from src.evidence_policy import build_answer_evidence_instruction

logger = logging.getLogger(__name__)
MAX_PLANNED_TOOLS = 6


def _normalize_planned_calls(tool_calls: list[dict] | None) -> list[dict]:
    """Validate, deduplicate, and enforce hard per-request tool budgets."""
    limits = {
        "web_search": 2,
        "search_reports": 1,
        "lookup_terms": 1,
        "get_company_data": 2,
        "financial_calculator": 4,
    }
    counts: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    normalized = []
    for call in tool_calls or []:
        name = str(call.get("name", ""))
        if name not in limits or counts.get(name, 0) >= limits[name]:
            continue
        try:
            arguments = validate_arguments(name, call.get("arguments") or {})
        except (ValidationError, ValueError, TypeError) as error:
            logger.warning("Rejected invalid tool call %s: %s", name, error)
            continue
        signature = (name, json.dumps(arguments, ensure_ascii=False, sort_keys=True))
        if signature in seen:
            continue
        seen.add(signature)
        counts[name] = counts.get(name, 0) + 1
        normalized.append(
            {
                "id": str(call.get("id") or f"planned-{len(normalized)}"),
                "name": name,
                "arguments": arguments,
            }
        )
        if len(normalized) >= MAX_PLANNED_TOOLS:
            break
    return normalized


def _tool_message(calls: list[dict]) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                },
            }
            for call in calls
        ],
    }


def _needs_calculation(query: str) -> bool:
    indicators = (
        "同比",
        "环比",
        "增长率",
        "增长",
        "毛利率",
        "净利率",
        "ROE",
        "ROA",
        "比例",
        "比率",
        "差额",
        "相差",
        "占比",
        "compare",
        "growth",
        "margin",
        "ratio",
    )
    lowered = query.lower()
    return any(indicator.lower() in lowered for indicator in indicators)


def _status_event(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _format_duration(elapsed: float) -> str:
    if elapsed < 0.001:
        return "<1ms"
    if elapsed < 0.1:
        return f"{elapsed * 1000:.0f}ms"
    return f"{elapsed:.1f}s"


def _fallback_retrieval_calls(query: str, planner_tools: list[dict]) -> list[dict]:
    """Recover deterministic local lookups when a provider emits no valid tool call."""
    available = {tool["function"]["name"] for tool in planner_tools}
    calls = []
    if "get_company_data" in available:
        from src.financial_data import FinancialDataManager

        for company in FinancialDataManager().find_companies(query)[:2]:
            calls.append(
                {
                    "id": f"fallback-company-{len(calls)}",
                    "name": "get_company_data",
                    "arguments": {"company": company, "periods": []},
                }
            )
    if not calls and "lookup_terms" in available:
        from src.terminology import TerminologyManager

        if TerminologyManager().find_terms(query):
            calls.append(
                {
                    "id": "fallback-terms-0",
                    "name": "lookup_terms",
                    "arguments": {"query": query},
                }
            )
    return calls


def _execute_retrieval_plan(
    calls: list[dict], tracker: CitationTracker, messages: list[dict], lang: str
) -> Generator[str, None, None]:
    labels = TOOL_LABELS.get(lang, TOOL_LABELS["zh"])
    for call in calls:
        yield _status_event(
            {"status": "tool_start", "tool": call["name"], "label": labels[call["name"]][0]}
        )

    outcomes: dict[int, tuple[str, CitationTracker, float]] = {}

    def execute(index: int, call: dict) -> tuple[int, str, CitationTracker, float]:
        local_tracker = CitationTracker()
        started = time.perf_counter()
        result = execute_tool(call["name"], call["arguments"], local_tracker)
        return index, result, local_tracker, time.perf_counter() - started

    with ThreadPoolExecutor(max_workers=min(4, len(calls))) as executor:
        futures = [executor.submit(execute, index, call) for index, call in enumerate(calls)]
        for future in as_completed(futures):
            index, result, local_tracker, elapsed = future.result()
            outcomes[index] = (result, local_tracker, elapsed)
            call = calls[index]
            duration = _format_duration(elapsed)
            yield _status_event(
                {
                    "status": "tool_done",
                    "tool": call["name"],
                    "label": f"{labels[call['name']][1]} ({duration})",
                    "summary": result.replace("\n", " ")[:120],
                }
            )

    messages.append(_tool_message(calls))
    for index, call in enumerate(calls):
        result, local_tracker, _elapsed = outcomes[index]
        tracker.merge(local_tracker)
        messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})


def run_agent_loop(
    client,
    messages: list[dict],
    tracker: CitationTracker,
    lang: str = "zh",
    model: str | None = None,
    available_retrieval_tools: set[str] | None = None,
) -> Generator[str, None, None]:
    """Plan once, run retrieval concurrently, optionally calculate once, then answer."""
    working_messages = [dict(message) for message in messages]
    user_query = next(
        (
            str(message.get("content", ""))
            for message in reversed(working_messages)
            if message.get("role") == "user"
        ),
        "",
    )
    planning_instruction = (
        "你是证据检索规划器。只规划当前问题必需的检索工具，并在一次响应中给出所有调用。"
        "最多两次网络搜索、一次报告检索、一次术语查询和两次公司数据查询。"
        "公司季度问题必须在 get_company_data.periods 中一次列出全部所需季度；环比应同时取当前季度和上一季度。"
        "不要计算，不要重复近义搜索，不要回答问题。"
        if lang == "zh"
        else "You are an evidence planner. Select all necessary retrieval tools in one response: at most two web searches, one report search, one terminology lookup, and two company lookups. For quarterly questions, include every required quarter in get_company_data.periods; QoQ needs both current and preceding quarters. Do not calculate, repeat equivalent searches, or answer."
    )
    planner_tools = RETRIEVAL_TOOLS
    if available_retrieval_tools is not None:
        planner_tools = [
            tool
            for tool in RETRIEVAL_TOOLS
            if tool["function"]["name"] in available_retrieval_tools
        ]
    try:
        plan = client.chat_with_tools(
            messages=[{"role": "system", "content": planning_instruction}, *working_messages],
            tools=planner_tools,
            model=model,
            tool_choice="auto",
        )
        retrieval_calls = _normalize_planned_calls(plan.get("tool_calls"))
        if not retrieval_calls:
            retrieval_calls = _fallback_retrieval_calls(user_query, planner_tools)
    except Exception as error:
        logger.error("Evidence planning failed: %s", error, exc_info=True)
        retrieval_calls = []
        label = (
            "检索规划失败，使用已有证据生成回答"
            if lang == "zh"
            else "Planning failed; using available evidence"
        )
        yield _status_event({"status": "info", "label": label})

    if retrieval_calls:
        yield from _execute_retrieval_plan(retrieval_calls, tracker, working_messages, lang)

    if _needs_calculation(user_query):
        calculation_instruction = (
            "只检查现有证据中的数字。若能完成用户要求的精确计算，请在一次响应中调用全部必要计算器。"
            "不得心算、搜索、猜测缺失数字或回答。"
            if lang == "zh"
            else "Use only numbers already present in evidence. In one response call every calculator operation needed. Do not estimate, search, or answer."
        )
        try:
            plan = client.chat_with_tools(
                messages=[
                    {"role": "system", "content": calculation_instruction},
                    *working_messages,
                ],
                tools=CALCULATOR_TOOLS,
                model=model,
                tool_choice="auto",
            )
            calculation_calls = _normalize_planned_calls(plan.get("tool_calls"))
        except Exception as error:
            logger.error("Calculation planning failed: %s", error, exc_info=True)
            calculation_calls = []

        if calculation_calls:
            labels = TOOL_LABELS.get(lang, TOOL_LABELS["zh"])
            working_messages.append(_tool_message(calculation_calls))
            for call in calculation_calls:
                yield _status_event(
                    {
                        "status": "tool_start",
                        "tool": call["name"],
                        "label": labels[call["name"]][0],
                    }
                )
                started = time.perf_counter()
                result = execute_tool(call["name"], call["arguments"], tracker)
                elapsed = time.perf_counter() - started
                duration = _format_duration(elapsed)
                yield _status_event(
                    {
                        "status": "tool_done",
                        "tool": call["name"],
                        "label": f"{labels[call['name']][1]} ({duration})",
                        "summary": result[:120],
                    }
                )
                working_messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": result}
                )

    if not tracker.is_empty():
        citations = tracker.to_list()
        source_lines = []
        for index, citation in enumerate(citations, 1):
            quality = ""
            if citation.get("source_type") == "web":
                quality = f" · Tier {citation.get('trust_tier', 3)}"
            elif citation.get("source_type") == "financial":
                quality = f" · Tier {citation.get('trust_tier', 1)}"
            if citation.get("published_at"):
                quality += f" · {citation['published_at']}"
            source_lines.append(
                f"[{index}] {citation['icon']}: {citation['display_source']}{quality}"
            )
        source_index = "\n".join(source_lines)
        citation_instruction = (
            "只依据已提供证据回答。每个可核验事实的句末必须用 [1]、[2] 等编号，且对应以下来源。"
            "保持证据中的数值单位；除非已有计算器结果，否则不得自行换算单位。"
            if lang == "zh"
            else "Answer only from supplied evidence. Cite every verifiable claim with [1], [2], etc., matching this source index. Preserve evidence units unless a calculator result explicitly converts them."
        )
        evidence_instruction = build_answer_evidence_instruction(user_query, citations, lang)
        if evidence_instruction:
            citation_instruction = f"{citation_instruction}\n{evidence_instruction}"
        working_messages.append(
            {"role": "user", "content": f"{citation_instruction}\n\n{source_index}"}
        )

    label = "正在生成回答..." if lang == "zh" else "Generating answer..."
    yield _status_event({"status": "info", "label": label})
    try:
        for token in client.chat_stream(messages=working_messages, model=model):
            yield _status_event({"token": token})
    except Exception as error:
        logger.error("Final response stream failed: %s", error, exc_info=True)
        yield _status_event({"error": f"回答生成失败: {error}"})
        return

    if not tracker.is_empty():
        citations = tracker.to_list()
        yield _status_event(
            {
                "citations": citations,
                "panel_html": CitationTracker.format_panel(citations, lang=lang),
            }
        )
    yield _status_event({"done": True})


__all__ = ["run_agent_loop"]
