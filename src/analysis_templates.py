"""Reusable, evidence-aware research templates and metric definitions."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from config import DATA_DIR

METRIC_DEFINITIONS_FILE = DATA_DIR / "metric_definitions.json"


class CompanyComparisonRequest(BaseModel):
    """Validated inputs for a reusable peer-comparison research prompt."""

    model_config = ConfigDict(extra="forbid")
    companies: list[str] = Field(min_length=2, max_length=4)
    periods: list[str] = Field(min_length=1, max_length=8)
    metrics: list[str] = Field(min_length=1, max_length=8)


@lru_cache(maxsize=1)
def load_metric_definitions(path: Path = METRIC_DEFINITIONS_FILE) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("metric definition file requires a non-empty 'metrics' object")
    return metrics


def build_company_comparison_prompt(
    request: CompanyComparisonRequest,
    *,
    lang: str = "zh",
    definitions: dict[str, dict] | None = None,
) -> str:
    """Build a bounded comparison request that preserves metric disclosure scope."""
    registry = definitions or load_metric_definitions()
    unknown = [metric for metric in request.metrics if metric not in registry]
    if unknown:
        raise ValueError(f"unknown comparison metrics: {', '.join(unknown)}")

    companies = "、".join(request.companies) if lang == "zh" else ", ".join(request.companies)
    periods = "、".join(request.periods) if lang == "zh" else ", ".join(request.periods)
    metric_lines = []
    for key in request.metrics:
        item = registry[key]
        label = item["label_zh" if lang == "zh" else "label_en"]
        note = item["comparison_note_zh" if lang == "zh" else "comparison_note_en"]
        metric_lines.append(f"- {label} (`{key}`): {note}")

    if lang == "zh":
        return (
            f"请使用公司对比模板分析 {companies} 在 {periods} 的表现。\n"
            "只使用官方结构化数据或已上传报告中的可追溯证据；不要用网页摘要替代已有官方数据。\n"
            "先输出一张清晰的 Markdown 对比表，每一行都标注来源；随后解释差异、趋势、口径限制与投资含义。\n"
            "任何增长率、利润率派生值、差额或比例必须调用 financial_calculator，严禁心算。\n"
            "指标口径：\n" + "\n".join(metric_lines)
        )
    return (
        f"Use the company-comparison template to analyze {companies} for {periods}.\n"
        "Use only traceable official structured data or uploaded-report evidence; do not replace available official data with web summaries.\n"
        "Start with a clear Markdown comparison table and cite every row, then explain differences, trends, scope limitations and investment implications.\n"
        "Every derived growth rate, margin, difference or ratio must use financial_calculator; never calculate mentally.\n"
        "Metric scope:\n" + "\n".join(metric_lines)
    )


def default_foundry_comparison_prompt(lang: str = "zh") -> str:
    """Return the current official-data peer comparison used by the quick action."""
    return build_company_comparison_prompt(
        CompanyComparisonRequest(
            companies=["台积电", "中芯国际"],
            periods=["2026 Q2"],
            metrics=["revenue", "gross_margin", "operating_margin"],
        ),
        lang=lang,
    )
