"""Evidence-backed chart payloads for the research workbench.

Only reported values already stored in ``foundry_financials.json`` are exposed
here. Financial ratios are never derived in this module.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from config import DATA_DIR

FINANCIALS_FILE = DATA_DIR / "foundry_financials.json"
COMPANY_KEYS = ("台积电", "中芯国际")
QUARTERLY_METRICS = ("revenue_usd_billion", "gross_margin_pct")


def _safe_url(value: str) -> str:
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.netloc else ""


def _percent(value: object) -> float:
    """Parse stored percentage strings without deriving a financial metric."""
    cleaned = str(value).strip().replace("~", "").replace("%", "")
    return float(cleaned)


@lru_cache(maxsize=1)
def load_analytics_payload(path: Path = FINANCIALS_FILE) -> dict:
    """Build a serializable, source-rich dashboard payload."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    companies = raw["companies"]
    periods = sorted(set.intersection(*(set(companies[key]["quarterly"]) for key in COMPANY_KEYS)))

    quarterly: dict[str, list[dict]] = {metric: [] for metric in QUARTERLY_METRICS}
    process_mix: list[dict] = []
    capex_intensity: list[dict] = []
    annual_sources: list[dict] = []

    for key in COMPANY_KEYS:
        company = companies[key]
        for metric in QUARTERLY_METRICS:
            points = []
            for period in periods:
                quarter = company["quarterly"][period]
                points.append(
                    {
                        "period": period,
                        "value": quarter["metrics"][metric],
                        "source_title": quarter["source_title"],
                        "source_url": _safe_url(quarter["source_url"]),
                        "published_at": quarter["source_published_at"],
                    }
                )
            quarterly[metric].append(
                {"company": key, "company_en": company["name_en"], "points": points}
            )

        segments = [
            {"label": label, "value": _percent(value), "approximate": "~" in str(value)}
            for label, value in company["capacity"]["process_mix"].items()
        ]
        process_mix.append({"company": key, "company_en": company["name_en"], "segments": segments})
        capex_intensity.append(
            {
                "company": key,
                "company_en": company["name_en"],
                "value": company["capex"]["intensity_pct"],
            }
        )
        annual_sources.append(
            {
                "company": key,
                "title": company["source_title"],
                "publisher": company["source_publisher"],
                "published_at": company["source_published_at"],
                "url": _safe_url(company["source_url"]),
            }
        )

    return {
        "as_of": raw["_meta"]["last_updated"],
        "periods": periods,
        "quarterly": quarterly,
        "process_mix": process_mix,
        "capex_intensity": capex_intensity,
        "annual_sources": annual_sources,
        "disclaimer": raw["_meta"]["disclaimer"],
    }


def build_watchlist_timeline(watched: list[str], lang: str = "zh", limit: int = 12) -> dict:
    """Build a recent official-disclosure timeline for watched companies."""
    payload = load_analytics_payload()
    selected = [key for key in COMPANY_KEYS if key in watched]
    company_names = {
        series["company"]: series["company_en"]
        for series in payload["quarterly"]["revenue_usd_billion"]
    }
    events: list[dict] = []
    revenue_series = {
        series["company"]: series["points"]
        for series in payload["quarterly"]["revenue_usd_billion"]
    }
    margin_series = {
        series["company"]: series["points"] for series in payload["quarterly"]["gross_margin_pct"]
    }

    for company in selected:
        margins = {point["period"]: point for point in margin_series[company]}
        for revenue in revenue_series[company]:
            margin = margins[revenue["period"]]
            if lang == "en":
                summary = (
                    f"Revenue USD {revenue['value']:.2f}bn · gross margin {margin['value']:.1f}%"
                )
                title = f"{company_names[company]} {revenue['period']} results"
            else:
                summary = f"营收 {revenue['value']:.2f} 十亿美元 · 毛利率 {margin['value']:.1f}%"
                title = f"{company} {revenue['period']} 业绩"
            events.append(
                {
                    "company": company,
                    "company_en": company_names[company],
                    "period": revenue["period"],
                    "date": revenue["published_at"],
                    "title": title,
                    "summary": summary,
                    "source_title": revenue["source_title"],
                    "source_url": revenue["source_url"],
                }
            )

    events.sort(key=lambda event: (event["date"], event["company"]), reverse=True)
    return {"watched": selected, "events": events[:limit], "supported": list(COMPANY_KEYS)}
