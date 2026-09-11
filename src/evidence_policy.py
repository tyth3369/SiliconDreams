"""Deterministic source-quality, recency, and evidence-conflict policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any

TIME_SENSITIVE_MARKERS = (
    "最新",
    "近况",
    "近期",
    "进展",
    "现在",
    "当前",
    "截至",
    "latest",
    "recent",
    "current",
    "progress",
    "as of",
)


def parse_source_date(value: str | None) -> date | None:
    """Parse conservative ISO-like source dates; unknown prose remains undated."""
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError, OverflowError):
        pass
    match = re.search(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b", text)
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def is_time_sensitive_query(query: str) -> bool:
    lowered = query.casefold()
    return any(marker.casefold() in lowered for marker in TIME_SENSITIVE_MARKERS)


@dataclass(frozen=True)
class WebEvidenceAssessment:
    time_sensitive: bool
    excluded_future: int
    stale: int
    undated: int

    def instruction(self, lang: str = "zh") -> str:
        if lang == "en":
            parts = [
                "Prefer Tier 1 official disclosures over Tier 2 reporting and Tier 3 web sources.",
                "Publication date is metadata, not necessarily the event date.",
            ]
            if self.excluded_future:
                parts.append(f"{self.excluded_future} future-dated result(s) were excluded.")
            if self.time_sensitive and self.stale:
                parts.append(
                    f"{self.stale} older result(s) are background only, not latest-state proof."
                )
            if self.undated:
                parts.append(
                    f"{self.undated} result(s) have unknown publication dates; qualify recency claims."
                )
            return " ".join(parts)

        parts = [
            "来源优先级为 Tier 1 官方披露 > Tier 2 权威报道 > Tier 3 普通网页。",
            "发布日期只是来源元数据，不一定等于事件发生日期。",
        ]
        if self.excluded_future:
            parts.append(f"已排除 {self.excluded_future} 条发布日期晚于当前日期的结果。")
        if self.time_sensitive and self.stale:
            parts.append(f"其中 {self.stale} 条较旧结果只能作为背景，不能单独证明最新状态。")
        if self.undated:
            parts.append(f"其中 {self.undated} 条结果发布日期未知，涉及时效性的结论必须保留限定。")
        return "".join(parts)


def assess_web_results(
    query: str,
    results: list[dict[str, Any]],
    *,
    as_of: date | None = None,
    stale_after_days: int = 550,
) -> tuple[list[dict[str, Any]], WebEvidenceAssessment]:
    """Reject future-dated results and annotate freshness without inventing dates."""
    today = as_of or datetime.now(UTC).date()
    time_sensitive = is_time_sensitive_query(query)
    accepted: list[dict[str, Any]] = []
    excluded_future = stale = undated = 0

    for original in results:
        item = dict(original)
        published = parse_source_date(item.get("published_at"))
        if published and published > today:
            excluded_future += 1
            continue
        if published is None:
            item["date_status"] = "undated"
            undated += 1
        elif time_sensitive and (today - published).days > stale_after_days:
            item["date_status"] = "stale"
            stale += 1
        else:
            item["date_status"] = "dated"
        accepted.append(item)

    freshness_bonus = {"dated": 0.08, "undated": 0.0, "stale": -0.10}
    tier_bonus = {1: 0.20, 2: 0.08, 3: 0.0, 4: -0.05}
    accepted.sort(
        key=lambda item: (
            float(item.get("score", 0.0))
            + tier_bonus.get(int(item.get("trust_tier", 3)), 0.0)
            + freshness_bonus.get(str(item.get("date_status", "undated")), 0.0)
        ),
        reverse=True,
    )
    return accepted, WebEvidenceAssessment(time_sensitive, excluded_future, stale, undated)


def canonical_fact_value(value: object) -> str:
    """Normalize numeric strings so 33.10 and 33.1 compare as the same fact."""
    try:
        normalized = Decimal(str(value)).normalize()
    except (InvalidOperation, ValueError):
        return str(value).strip().casefold()
    return format(normalized, "f")


def build_answer_evidence_instruction(query: str, citations: list[dict], lang: str) -> str:
    """Build an answer-time policy from the sources that were actually retrieved."""
    web = [citation for citation in citations if citation.get("source_type") == "web"]
    if not web:
        return ""
    tier_counts = {
        tier: sum(int(item.get("trust_tier", 3)) == tier for item in web) for tier in (1, 2, 3)
    }
    undated = sum(item.get("date_status") == "undated" for item in web)
    stale = sum(item.get("date_status") == "stale" for item in web)
    temporal = is_time_sensitive_query(query)
    if lang == "en":
        instruction = (
            f"Web evidence mix: Tier 1={tier_counts[1]}, Tier 2={tier_counts[2]}, "
            f"Tier 3={tier_counts[3]}, undated={undated}, stale={stale}. "
            "Prefer official sources; lower-tier sources may add context but must not silently overrule them. "
            "If sources disagree, state the disagreement and cite both."
        )
        if temporal:
            instruction += (
                " For latest-state claims, do not rely solely on stale or undated sources."
            )
        return instruction
    instruction = (
        f"本次网页证据构成：Tier 1={tier_counts[1]}、Tier 2={tier_counts[2]}、"
        f"Tier 3={tier_counts[3]}、日期未知={undated}、较旧={stale}。"
        "优先采用官方来源；低等级来源只能补充背景，不能无说明地覆盖高等级来源。"
        "若来源说法不一致，必须明确列出分歧并同时引用双方。"
    )
    if temporal:
        instruction += "回答最新状态时，不得仅依赖较旧或日期未知的来源。"
    return instruction
