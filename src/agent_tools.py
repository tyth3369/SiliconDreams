"""Validated evidence and calculation tools for the deterministic agent."""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.citation import CitationTracker

logger = logging.getLogger(__name__)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "通过 Tavily 搜索实时信息和最新新闻。仅在问题具有时效性或本地证据不足时使用。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_reports",
            "description": "在用户上传的 PDF 财报和研究报告中进行混合检索，返回精确页码证据。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_terms",
            "description": "查询半导体术语的定义、商业影响、相关公司和技术。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_data",
            "description": "获取台积电或中芯国际的官方结构化财务数据。两家公司均支持 FY2025 及 2024 Q1 至 2026 Q2；查询季度时必须在 periods 中列出所需期间。共同直接披露口径为美元营收和毛利率；营业利润口径存在差异。",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "periods": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 12,
                        "description": "例如 ['2025 Q3', '2025 Q4']；年度使用 ['FY2025']。",
                    },
                },
                "required": ["company"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "financial_calculator",
            "description": "用 Python Decimal 执行精确财务计算。所有增长率、比率和差额必须使用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": [
                            "yoy_growth",
                            "qoq_growth",
                            "gross_margin",
                            "net_margin",
                            "roe",
                            "roa",
                            "debt_ratio",
                            "current_ratio",
                            "pe_ratio",
                            "revenue_per_employee",
                            "rd_ratio",
                            "difference",
                            "ratio",
                        ],
                    },
                    "operands": {
                        "type": "object",
                        "additionalProperties": {"type": "number"},
                    },
                },
                "required": ["operation", "operands"],
                "additionalProperties": False,
            },
        },
    },
]

RETRIEVAL_TOOLS = [tool for tool in TOOLS if tool["function"]["name"] != "financial_calculator"]
CALCULATOR_TOOLS = [tool for tool in TOOLS if tool["function"]["name"] == "financial_calculator"]

TOOL_LABELS = {
    "zh": {
        "web_search": ("搜索网络中...", "网络搜索完成"),
        "search_reports": ("检索本地报告中...", "报告检索完成"),
        "lookup_terms": ("查询术语库中...", "术语查询完成"),
        "get_company_data": ("获取财务数据中...", "财务数据获取完成"),
        "financial_calculator": ("计算中...", "计算完成"),
    },
    "en": {
        "web_search": ("Searching the web...", "Web search complete"),
        "search_reports": ("Searching local reports...", "Report search complete"),
        "lookup_terms": ("Looking up terminology...", "Terminology lookup complete"),
        "get_company_data": ("Fetching financial data...", "Financial data fetched"),
        "financial_calculator": ("Computing...", "Calculation complete"),
    },
}


class QueryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)


class CompanyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str = Field(min_length=1, max_length=100)
    periods: list[str] = Field(default_factory=list, max_length=12)


def validate_arguments(name: str, arguments: dict) -> dict:
    if name in {"web_search", "search_reports", "lookup_terms"}:
        return QueryArguments.model_validate(arguments).model_dump()
    if name == "get_company_data":
        return CompanyArguments.model_validate(arguments).model_dump()
    if name == "financial_calculator":
        from src.tools.calculator import CalculationRequest

        return CalculationRequest.model_validate(arguments).model_dump()
    raise ValueError(f"unknown tool: {name}")


def execute_tool(name: str, arguments: dict, tracker: CitationTracker) -> str:
    """Execute a locally validated tool call and return LLM-readable evidence."""
    try:
        if name == "web_search":
            return _web_search(arguments, tracker)
        if name == "search_reports":
            return _search_reports(arguments, tracker)
        if name == "lookup_terms":
            return _lookup_terms(arguments, tracker)
        if name == "get_company_data":
            return _get_company_data(arguments, tracker)
        if name == "financial_calculator":
            return _calculate(arguments)
        return json.dumps({"error": "unknown_tool", "tool": name}, ensure_ascii=False)
    except Exception as error:
        logger.error("Tool execution failed [%s]: %s", name, error, exc_info=True)
        return json.dumps(
            {"error": "tool_execution_failed", "tool": name, "message": str(error)},
            ensure_ascii=False,
        )


def _web_search(arguments: dict, tracker: CitationTracker) -> str:
    from src.tools.web_search import MAX_RESULTS, _do_search

    results, text = _do_search(arguments["query"], MAX_RESULTS)
    for result in results:
        tracker.add_web(
            title=result["title"],
            url=result["url"],
            snippet=result.get("snippet", "")[:200],
            publisher=result.get("publisher", ""),
            published_at=result.get("published_at", ""),
            trust_tier=int(result.get("trust_tier", 3)),
            date_status=result.get("date_status", ""),
        )
    return f"{text}\n（共找到 {len(results)} 条结果）" if results else text


def _search_reports(arguments: dict, tracker: CitationTracker) -> str:
    from src.retriever import get_retriever

    results = get_retriever().retrieve(arguments["query"], top_k=5)
    if not results:
        return "未在已上传的报告中找到相关信息。"
    sections = [f'## 本地报告检索: "{arguments["query"]}"']
    for index, result in enumerate(results, 1):
        metadata = result.get("metadata") or {}
        source = metadata.get("source", "unknown")
        page = int(metadata.get("page") or 0)
        text = str(result.get("text", ""))[:800]
        sections.extend([f"### 结果 {index}: {source}, p{page}", text])
        tracker.add_rag(
            source=source,
            page=page or None,
            snippet=text[:200],
            score=float(result.get("score", 0)),
        )
    return "\n\n".join(sections)


def _lookup_terms(arguments: dict, tracker: CitationTracker) -> str:
    from src.terminology import TerminologyManager

    context, references = TerminologyManager().build_context(
        arguments["query"], max_terms=5, return_refs=True
    )
    for reference in references:
        tracker.add_term(reference["name"])
    return context or "未在术语库中找到匹配术语。"


def _get_company_data(arguments: dict, tracker: CitationTracker) -> str:
    from src.financial_data import FinancialDataManager
    from src.storage import Database

    manager = FinancialDataManager()
    context, references = manager.build_context(
        arguments["company"], max_companies=1, periods=arguments.get("periods")
    )
    for reference in references:
        tracker.add_financial(
            reference["name"],
            name_en=reference.get("name_en", ""),
            year=str(reference.get("period") or reference.get("year", "")),
            reference_title=reference.get("source_title", ""),
            url=reference.get("source_url", ""),
            publisher=reference.get("source_publisher", ""),
            published_at=reference.get("source_published_at", ""),
            trust_tier=1,
        )

    conflict_lines = []
    database = Database()
    seen_conflicts = set()
    for reference in references:
        period = str(reference.get("period") or reference.get("year") or "")
        if period and not period.startswith("FY") and " Q" not in period:
            period = f"FY{period}"
        for conflict in database.find_fact_conflicts(
            company=reference.get("name_en") or None,
            period=period or None,
        ):
            key = (conflict["company"], conflict["metric"], conflict["period"])
            if key in seen_conflicts:
                continue
            seen_conflicts.add(key)
            variants = "; ".join(
                f"{fact['value']} {fact['unit']} ({fact['source_title']}, Tier {fact['trust_tier']})"
                for fact in conflict["facts"]
            )
            conflict_lines.append(
                f"- CONFLICT {conflict['company']} {conflict['metric']} {conflict['period']}: {variants}"
            )
            for fact in conflict["facts"]:
                tracker.add_financial(
                    reference.get("name") or conflict["company"],
                    name_en=conflict["company"],
                    year=conflict["period"],
                    reference_title=fact["source_title"],
                    url=fact.get("source_url") or "",
                    publisher=fact.get("source_publisher") or "",
                    published_at=fact.get("published_at") or "",
                    trust_tier=int(fact.get("trust_tier", 3)),
                )
    if conflict_lines:
        context = (
            f"{context}\n\n## 结构化事实冲突警告\n"
            "以下同口径事实存在不同数值。回答时不得静默选取，必须说明分歧并引用来源：\n"
            + "\n".join(conflict_lines)
        )
    return context or f"未找到 {arguments['company']} 的结构化财务数据。"


def _calculate(arguments: dict) -> str:
    from src.tools.calculator import calculate_financial

    try:
        return json.dumps(calculate_financial(arguments), ensure_ascii=False)
    except ValidationError as error:
        return json.dumps(
            {"error": "invalid_calculation_request", "details": error.errors(include_url=False)},
            ensure_ascii=False,
        )
