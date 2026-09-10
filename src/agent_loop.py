"""
SiliconDreams — Custom Agent Loop (v0.6.0)
===========================================
Replaces the old LangChain ReAct agent (agent.py) with a custom
tool-calling loop using DeepSeek's native Function Calling API.

Key features:
- Generator-based: yields SSE events for streaming progress
- 5 tools: web_search, search_reports, lookup_terms, get_company_data,
  financial_calculator
- Citation tracking integrated into every tool call
- Graceful degradation: all tool errors become LLM-readable results
"""

from __future__ import annotations

import json
import logging
import time
from typing import Generator, Optional

from src.citation import CitationTracker

logger = logging.getLogger(__name__)

# ── Agent Limits ──────────────────────────────────────────
MAX_ITERATIONS = 6
WEB_SEARCH_TIMEOUT = 8  # seconds


# ═══════════════════════════════════════════════════════════
# Tool Definitions (OpenAI Function Calling format)
# ═══════════════════════════════════════════════════════════

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "搜索互联网获取实时信息、最新新闻和当前动态。"
                "当用户询问最新进展、当前事件、新闻报道、或本地知识库中没有覆盖的"
                "信息时使用此工具。英文搜索效果最好。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询词，建议使用英文关键词",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_reports",
            "description": (
                "在已上传的PDF财报和研究报告中检索相关数据。"
                "当用户询问具体的财务数字、公司业绩、或需要从财报中查找信息时使用。"
                "如果没有上传任何PDF文档，此工具将返回空结果。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "自然语言查询，如'台积电2025年毛利率同比变化'",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_terms",
            "description": (
                "查询半导体行业专业术语的定义和商业影响。"
                "当用户询问术语含义、技术概念、或需要理解半导体专业知识时使用。"
                "知识库包含100+条常用半导体术语。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "需要查询的术语或概念，如'先进制程'、'HBM'、'EUV光刻'",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_data",
            "description": (
                "获取晶圆代工企业的结构化财务数据，包括营收、毛利率、净利率、"
                "CAPEX、产能利用率、制程结构等关键指标。"
                "目前支持：台积电（TSMC）、中芯国际（SMIC）。"
                "数据来源：公司最新年报（FY2025）。"
                "注意：仅包含年度汇总数据，不包含季度或月度明细。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "公司名称，如'台积电'、'TSMC'、'中芯国际'、'SMIC'",
                    }
                },
                "required": ["company"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "financial_calculator",
            "description": (
                "执行精确的财务计算。支持：同比/环比增长率、毛利率、净利率、"
                "ROE、资产负债率、流动比率、市盈率、人均营收、研发投入比。"
                "任何涉及数字比较、比率计算、增长率的问题都必须使用此工具，严禁心算。"
                "输入格式：'计算类型:数值1,数值2'（如'yoy_growth:120,100'）"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": (
                            "计算表达式。支持格式："
                            "'yoy_growth:120,100'（同比增长率）"
                            "'gross_margin:56.2,100'（毛利率，利润/营收）"
                            "'net_margin:45.3,100'（净利率）"
                            "'difference:60,21'（差值）"
                        ),
                    }
                },
                "required": ["expression"],
            },
        },
    },
]

# ── Tool name → category mapping (for frontend icons/labels) ──
TOOL_CATEGORY = {
    "web_search": "web",
    "search_reports": "rag",
    "lookup_terms": "term",
    "get_company_data": "financial",
    "financial_calculator": "calculator",
}

# ── Chinese labels for tool progress display ──
TOOL_LABELS_ZH = {
    "web_search": "搜索网络中...",
    "search_reports": "检索本地报告中...",
    "lookup_terms": "查询术语库中...",
    "get_company_data": "获取财务数据中...",
    "financial_calculator": "计算中...",
}

TOOL_DONE_LABELS_ZH = {
    "web_search": "网络搜索完成",
    "search_reports": "报告检索完成",
    "lookup_terms": "术语查询完成",
    "get_company_data": "财务数据获取完成",
    "financial_calculator": "计算完成",
}

TOOL_LABELS_EN = {
    "web_search": "Searching the web...",
    "search_reports": "Searching local reports...",
    "lookup_terms": "Looking up terminology...",
    "get_company_data": "Fetching financial data...",
    "financial_calculator": "Computing...",
}

TOOL_DONE_LABELS_EN = {
    "web_search": "Web search complete",
    "search_reports": "Report search complete",
    "lookup_terms": "Terminology lookup complete",
    "get_company_data": "Financial data fetched",
    "financial_calculator": "Calculation complete",
}


# ═══════════════════════════════════════════════════════════
# Tool Executor
# ═══════════════════════════════════════════════════════════

def _execute_tool(name: str, arguments: dict, tracker: CitationTracker) -> str:
    """
    Execute a tool by name and return the result string.
    Also populates the CitationTracker for source attribution.

    All errors are caught and returned as strings so the LLM can
    gracefully handle them.
    """
    try:
        if name == "web_search":
            return _tool_web_search(arguments, tracker)

        elif name == "search_reports":
            return _tool_search_reports(arguments, tracker)

        elif name == "lookup_terms":
            return _tool_lookup_terms(arguments, tracker)

        elif name == "get_company_data":
            return _tool_get_company_data(arguments, tracker)

        elif name == "financial_calculator":
            return _tool_financial_calculator(arguments)

        else:
            return f"未知工具: {name}"

    except Exception as e:
        logger.error(f"工具执行失败 [{name}]: {e}")
        return f"工具执行出错: {e}。请尝试其他方式获取所需信息。"


# ── Individual Tool Implementations ────────────────────────


def _tool_web_search(arguments: dict, tracker: CitationTracker) -> str:
    """DuckDuckGo web search."""
    query = arguments.get("query", "")
    if not query:
        return "搜索查询为空，请提供具体的搜索关键词。"

    from src.tools.web_search import _do_search, MAX_RESULTS

    # Single HTTP request → both structured + formatted
    results, text = _do_search(query, MAX_RESULTS)

    # Track citations from structured results
    for r in results:
        tracker.add_web(
            title=r["title"],
            url=r["url"],
            snippet=r.get("snippet", "")[:200],
        )

    if results:
        text += f"\n（共找到 {len(results)} 条结果）"
    return text


def _tool_search_reports(arguments: dict, tracker: CitationTracker) -> str:
    """Local RAG search over uploaded PDFs."""
    query = arguments.get("query", "")
    if not query:
        return "检索查询为空，请提供具体的检索关键词。"

    from src.retriever import get_retriever

    retriever = get_retriever()
    results = retriever.retrieve(query, top_k=5)

    if not results:
        return "未在已上传的报告中找到相关信息。可能的原因：没有上传PDF文档，或查询关键词与文档内容不匹配。"

    lines = [f"## 本地报告检索: \"{query}\"\n"]
    for i, r in enumerate(results, 1):
        source = r["metadata"].get("source", "unknown")
        page = r["metadata"].get("page", 0) or 0
        text = r["text"]
        if len(text) > 800:
            text = text[:800] + "..."

        lines.append(f"### 结果 {i}: {source}, p{page} (相关度: {r['score']:.2f})")
        lines.append(text)
        lines.append("")

        # Track citation
        tracker.add_rag(
            source=source,
            page=page if page > 0 else None,
            snippet=text[:200],
            score=r["score"],
        )

    return "\n".join(lines)


def _tool_lookup_terms(arguments: dict, tracker: CitationTracker) -> str:
    """Semiconductor terminology lookup."""
    query = arguments.get("query", "")
    if not query:
        return "术语查询为空，请提供需要查询的术语。"

    from src.terminology import TerminologyManager

    tm = TerminologyManager()
    context, refs = tm.build_context(query, max_terms=5, return_refs=True)

    if not context:
        return f"未在术语库中找到与 '{query}' 匹配的术语。"

    # Track citations
    for ref in refs:
        tracker.add_term(ref["name"])

    return context


def _tool_get_company_data(arguments: dict, tracker: CitationTracker) -> str:
    """Structured financial data for foundry companies."""
    company = arguments.get("company", "")
    if not company:
        return "公司名称为空，请提供具体的公司名称（如'台积电'、'中芯国际'）。"

    from src.financial_data import FinancialDataManager

    fdm = FinancialDataManager()
    # Try the build_context approach first
    context, refs = fdm.build_context(company, max_companies=1)

    if not context:
        # Try direct lookup
        found = fdm.find_companies(company)
        if not found:
            return (
                f"未找到 '{company}' 的财务数据。目前支持的公司：台积电（TSMC）、"
                f"中芯国际（SMIC）。"
            )
        # Rebuild with the found key
        context, refs = fdm.build_context(" ".join(found), max_companies=1)

    if not context:
        return f"无法获取 '{company}' 的财务数据。"

    # Track citations
    for ref in refs:
        tracker.add_financial(ref["name"], name_en=ref.get("name_en", ""), year=str(ref.get("year", "")))

    return context


def _tool_financial_calculator(arguments: dict) -> str:
    """Precise financial calculation using Python decimal."""
    expression = arguments.get("expression", "")
    if not expression:
        return "计算表达式为空。请提供格式如 'yoy_growth:120,100' 的计算表达式。"

    from decimal import Decimal, InvalidOperation, DivisionByZero
    from typing import Tuple

    def _parse_two(value_str: str) -> Tuple[Decimal, Decimal]:
        """Parse 'a,b' into (Decimal(a), Decimal(b))."""
        parts = value_str.strip().split(",")
        if len(parts) < 2:
            parts = [value_str.strip(), "1"]
        a = Decimal(parts[0].strip())
        b = Decimal(parts[1].strip())
        return a, b

    try:
        expr = expression.strip()
        lower = expr.lower()

        if lower.startswith("yoy_growth:") or lower.startswith("yoy:"):
            current, prior = _parse_two(expr.split(":", 1)[1])
            if prior == 0:
                return "计算错误：上期值为零，无法计算同比增长率。"
            result = (current - prior) / prior * 100
            return (
                f"同比增长率: {float(result):.2f}%\n"
                f"（当期={float(current):.2f}, 上期={float(prior):.2f}, "
                f"变动={(float(current) - float(prior)):.2f}）"
            )

        elif lower.startswith("qoq_growth:") or lower.startswith("qoq:"):
            current, prior = _parse_two(expr.split(":", 1)[1])
            if prior == 0:
                return "计算错误：上季值为零，无法计算环比增长率。"
            result = (current - prior) / prior * 100
            return (
                f"环比增长率: {float(result):.2f}%\n"
                f"（本季={float(current):.2f}, 上季={float(prior):.2f}）"
            )

        elif lower.startswith("gross_margin:") or lower.startswith("gm:"):
            profit, revenue = _parse_two(expr.split(":", 1)[1])
            if revenue == 0:
                return "计算错误：营收为零，无法计算毛利率。"
            result = profit / revenue * 100
            return f"毛利率: {float(result):.2f}%"

        elif lower.startswith("net_margin:") or lower.startswith("nm:"):
            profit, revenue = _parse_two(expr.split(":", 1)[1])
            if revenue == 0:
                return "计算错误：营收为零，无法计算净利率。"
            result = profit / revenue * 100
            return f"净利率: {float(result):.2f}%"

        elif lower.startswith("difference:") or lower.startswith("diff:"):
            a, b = _parse_two(expr.split(":", 1)[1])
            diff = a - b
            if b != 0:
                pct = diff / b * 100
                return (
                    f"差值: {float(diff):.2f}\n"
                    f"（{float(a):.2f} - {float(b):.2f} = {float(diff):.2f}, "
                    f"变化幅度: {float(pct):.2f}%）"
                )
            return f"差值: {float(diff):.2f}（{float(a):.2f} - {float(b):.2f}）"

        elif lower.startswith("roe:"):
            net_income, equity = _parse_two(expr.split(":", 1)[1])
            if equity == 0:
                return "计算错误：权益为零，无法计算ROE。"
            result = net_income / equity * 100
            return f"ROE（净资产收益率）: {float(result):.2f}%"

        elif lower.startswith("ratio:") or lower.startswith("divide:"):
            a, b = _parse_two(expr.split(":", 1)[1])
            if b == 0:
                return "计算错误：除数为零。"
            result = a / b
            return f"比率: {float(result):.4f}（{float(a):.2f} / {float(b):.2f}）"

        else:
            return (
                f"不支持的计算类型: '{expression}'。"
                f"支持的类型: yoy_growth（同比增长率）, qoq_growth（环比增长率）, "
                f"gross_margin（毛利率）, net_margin（净利率）, difference（差值）, "
                f"roe（净资产收益率）, ratio（比率）。"
            )

    except (InvalidOperation, ValueError) as e:
        return f"计算表达式格式错误: {e}。请使用数字格式，如 'yoy_growth:120,100'。"
    except DivisionByZero:
        return "计算错误：除数为零。"
    except Exception as e:
        logger.error(f"计算器异常: {e}")
        return f"计算出错: {e}。请检查输入格式。"


# ═══════════════════════════════════════════════════════════
# Agent Loop (Generator)
# ═══════════════════════════════════════════════════════════

def run_agent_loop(
    client,  # DeepSeekClient
    messages: list[dict],
    tracker: CitationTracker,
    lang: str = "zh",
    model: Optional[str] = None,
    max_iterations: int = MAX_ITERATIONS,
) -> Generator[str, None, None]:
    """
    Run the tool-calling agent loop, yielding SSE event strings.

    The generator yields SSE-formatted strings:
        data: {"status": "thinking"}\\n\\n
        data: {"status": "tool_start", "tool": "...", "label": "..."}\\n\\n
        data: {"status": "tool_done", "tool": "...", "label": "...", "summary": "..."}\\n\\n
        data: {"token": "..."}\\n\\n
        data: {"done": true}\\n\\n
        data: {"citations": [...], "panel_html": "..."}\\n\\n

    Args:
        client: DeepSeekClient instance
        messages: Conversation messages (system + user + history)
        tracker: CitationTracker instance for this message
        lang: UI language ('zh' or 'en')
        model: Model override (default: deepseek-chat)
        max_iterations: Max tool-calling iterations

    Yields:
        SSE-formatted event strings
    """
    tool_labels = TOOL_LABELS_ZH if lang == "zh" else TOOL_LABELS_EN
    tool_done_labels = TOOL_DONE_LABELS_ZH if lang == "zh" else TOOL_DONE_LABELS_EN

    # ── Phase 1: Tool-calling loop ────────────────────

    called_tools: set[tuple] = set()  # (tool_name, args_json) for duplicate detection
    consecutive_same_tool = 0          # track consecutive calls to the same tool
    last_tool_name: str | None = None
    total_web_searches = 0             # total web_search calls across all iterations

    for iteration in range(max_iterations):
        try:
            response = client.chat_with_tools(
                messages=messages,
                tools=TOOLS,
                model=model,
            )
        except Exception as e:
            logger.error(f"Agent Loop 第 {iteration + 1} 轮失败: {e}")
            yield f"data: {json.dumps({'error': f'AI 调用失败: {e}'})}\n\n"
            return

        # Tool calls returned → execute them
        if response["tool_calls"]:
            force_break = False
            for tc in response["tool_calls"]:
                tool_name = tc["name"]
                args_str = json.dumps(tc["arguments"], ensure_ascii=False, sort_keys=True)
                sig = (tool_name, args_str)

                # Duplicate detection: same tool + same args → LLM is looping
                if sig in called_tools:
                    logger.warning(
                        f"Agent Loop 检测到重复调用 {tool_name}({args_str[:80]})，强制退出工具循环"
                    )
                    yield (
                        f"data: {json.dumps({'status': 'info', 'label': '检测到重复工具调用，综合分析中...'})}\n\n"
                    )
                    force_break = True
                    break

                called_tools.add(sig)

                # Consecutive same-tool detection: same tool N times in a row = loop
                if tool_name == last_tool_name:
                    consecutive_same_tool += 1
                else:
                    consecutive_same_tool = 1
                    last_tool_name = tool_name

                # Per-tool consecutive threshold: web_search needs more calls
                _consec_limit = 4 if tool_name == "web_search" else 3
                if consecutive_same_tool >= _consec_limit:
                    logger.warning(
                        f"Agent Loop 连续 {consecutive_same_tool} 次调用 {tool_name}，强制退出"
                    )
                    yield (
                        f"data: {json.dumps({'status': 'info', 'label': '连续调用同一工具，综合分析中...'})}\n\n"
                    )
                    force_break = True
                    break

                # Total web_search cap: prevent excessive searching
                if tool_name == "web_search":
                    total_web_searches += 1
                    if total_web_searches >= 5:
                        logger.warning(
                            f"Agent Loop 累计 {total_web_searches} 次 web_search，强制退出"
                        )
                        yield (
                            f"data: {json.dumps({'status': 'info', 'label': '已搜索足够信息，综合分析中...'})}\n\n"
                        )
                        force_break = True
                        break

                label = tool_labels.get(tool_name, f"🔧 调用工具: {tool_name}")

                # Emit tool start event
                yield (
                    f"data: {json.dumps({'status': 'tool_start', 'tool': tool_name, 'label': label})}\n\n"
                )

                # Execute the tool
                t0 = time.perf_counter()
                result = _execute_tool(tool_name, tc["arguments"], tracker)
                elapsed = time.perf_counter() - t0

                done_label = tool_done_labels.get(
                    tool_name, f"✅ {tool_name} 完成"
                )
                # Format elapsed time: ms for fast ops, seconds for slow ops
                if elapsed < 0.1:
                    time_str = f"{elapsed*1000:.0f}ms"
                else:
                    time_str = f"{elapsed:.1f}s"

                # Build a short summary for the frontend
                summary = result[:120].replace("\n", " ") + "..." if len(result) > 120 else result.replace("\n", " ")

                # Emit tool done event
                done_data = {
                    "status": "tool_done",
                    "tool": tool_name,
                    "label": f"{done_label} ({time_str})",
                    "summary": summary,
                }
                yield f"data: {json.dumps(done_data)}\n\n"

                # Add the tool interaction to messages
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                        },
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

            # Continue to next iteration (LLM may call more tools)
            if force_break:
                break
            continue

        # No tool calls → LLM is ready to answer.
        # DO NOT append response["content"] to messages here — that would
        # cause Phase 2's chat_stream to see an existing assistant answer
        # and generate a short "follow-up" instead of the full answer.
        # Phase 2 will stream the final answer fresh from tool results.
        break

    else:
        # Loop exhausted without convergence → force final answer
        logger.warning(f"Agent Loop 达到最大迭代次数 {max_iterations}，强制生成回答")
        yield (
            f"data: {json.dumps({'status': 'tool_done', 'tool': '_force', 'label': '⚠️ 达到最大搜索步数，综合分析中...'})}\n\n"
        )

    # ── Phase 2: Stream final answer ──────────────────

    # Build inline citation index so LLM can use [1], [2] markers
    # This must happen BEFORE chat_stream so the LLM knows which number = which source
    if not tracker.is_empty():
        citations = tracker.to_list()
        idx_lines = []
        for i, c in enumerate(citations, 1):
            idx_lines.append(f"[{i}] {c['icon']}: {c['display_source']}")
        idx_text = "\n".join(idx_lines)
        if lang == "zh":
            instruction = (
                f"请基于以上信息回答用户的问题。在回答中使用 [1]、[2] 等数字上标"
                f"在句末标注引用来源。\n\n可用来源索引：\n{idx_text}"
            )
        else:
            instruction = (
                f"Answer the user's question based on the information above. "
                f"Use [1], [2] numeric superscript markers to cite sources.\n\n"
                f"Available source index:\n{idx_text}"
            )
        messages.append({"role": "user", "content": instruction})

    # Signal that we're generating the answer (before first token arrives)
    yield (
        f"data: {json.dumps({'status': 'info', 'label': '正在生成回答...' if lang == 'zh' else 'Generating answer...'})}\n\n"
    )

    try:
        for token in client.chat_stream(messages=messages, model=model):
            yield f"data: {json.dumps({'token': token})}\n\n"
    except Exception as e:
        logger.error(f"最终回答流式输出失败: {e}")
        yield f"data: {json.dumps({'error': f'回答生成失败: {e}'})}\n\n"
        return

    # ── Phase 3: Citations + Done ─────────────────────
    # IMPORTANT: citations MUST come before done — the client
    # closes the EventSource on 'done', discarding any pending events.

    if not tracker.is_empty():
        citations = tracker.to_list()
        panel_html = CitationTracker.format_panel(citations, lang=lang)
        yield (
            f"data: {json.dumps({'citations': citations, 'panel_html': panel_html})}\n\n"
        )

    yield f"data: {json.dumps({'done': True})}\n\n"


# ═══════════════════════════════════════════════════════════
# Fallback: Simple context injection (for R1 or error recovery)
# ═══════════════════════════════════════════════════════════

def build_simple_context(
    query: str,
    lang: str,
    tracker: CitationTracker,
) -> list[dict]:
    """
    Build system messages using the old manual context injection method.
    Used as fallback when R1 model is selected (no Function Calling support).
    """
    from config import AppConfig

    extra_messages = [
        {"role": "system", "content": AppConfig.get_system_prompt(lang)}
    ]

    # Terminology
    try:
        from src.terminology import TerminologyManager
        tm = TerminologyManager()
        ctx, refs = tm.build_context(query, return_refs=True)
        if ctx:
            extra_messages.append({"role": "system", "content": ctx})
            for ref in refs:
                tracker.add_term(ref["name"])
    except Exception as e:
        logger.warning(f"术语注入失败: {e}")

    # Financial data
    try:
        from src.financial_data import FinancialDataManager
        fdm = FinancialDataManager()
        ctx, refs = fdm.build_context(query)
        if ctx:
            extra_messages.append({"role": "system", "content": ctx})
            for ref in refs:
                tracker.add_financial(ref["name"], name_en=ref.get("name_en", ""), year=str(ref.get("year", "")))
    except Exception as e:
        logger.warning(f"财务数据注入失败: {e}")

    # RAG (only if documents uploaded)
    try:
        from src.vector_store import VectorStore
        store = VectorStore()
        stats = store.get_stats()
        if stats.get("doc_count", 0) > 0:
            from src.retriever import get_retriever
            retriever = get_retriever()
            results = retriever.retrieve(query, top_k=4)
            if results:
                parts = []
                for i, r in enumerate(results):
                    source = r["metadata"].get("source", "unknown")
                    page = r["metadata"].get("page", 0) or 0
                    text = r["text"]
                    if len(text) > 1500:
                        text = text[:1500] + "..."
                    parts.append(
                        f"--- [Doc {i+1}] {source}, p{page} (relevance: {r['score']:.2f}) ---\n{text}"
                    )
                    tracker.add_rag(
                        source=source,
                        page=page if page > 0 else None,
                        snippet=text[:200],
                        score=r["score"],
                    )
                extra_messages.append({
                    "role": "system",
                    "content": f"以下是从已上传财报中检索到的相关信息：\n\n" + "\n\n".join(parts),
                })
    except Exception as e:
        logger.warning(f"RAG 注入失败: {e}")

    return extra_messages
