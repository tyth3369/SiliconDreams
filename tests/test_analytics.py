import asyncio
import json
import re

from httpx import ASGITransport, AsyncClient

import server
from src.analytics import build_watchlist_timeline, load_analytics_payload


def test_payload_uses_reported_values_and_exact_sources():
    payload = load_analytics_payload()
    assert payload["periods"] == [
        "2024 Q1",
        "2024 Q2",
        "2024 Q3",
        "2024 Q4",
        "2025 Q1",
        "2025 Q2",
        "2025 Q3",
        "2025 Q4",
        "2026 Q1",
        "2026 Q2",
    ]
    tsmc_revenue = payload["quarterly"]["revenue_usd_billion"][0]["points"]
    assert tsmc_revenue[-1]["value"] == 40.2
    assert tsmc_revenue[-1]["source_title"] == "TSMC 2Q26 Quarterly Results"
    assert tsmc_revenue[-1]["source_url"].startswith("https://investor.tsmc.com/")
    assert payload["capex_intensity"][1]["value"] == 86.8


def test_process_mix_preserves_approximation_flag():
    payload = load_analytics_payload()
    smic = payload["process_mix"][1]
    assert all(segment["approximate"] for segment in smic["segments"])
    assert sum(segment["value"] for segment in smic["segments"]) == 100


def test_watchlist_timeline_is_recent_source_backed_and_localized():
    timeline = build_watchlist_timeline(["台积电", "中芯国际"], lang="en", limit=3)
    assert len(timeline["events"]) == 3
    assert timeline["events"][0]["date"] >= timeline["events"][1]["date"]
    assert "gross margin" in timeline["events"][0]["summary"]
    assert timeline["events"][0]["source_url"].startswith("https://")
    assert build_watchlist_timeline([], lang="zh")["events"] == []


def test_analytics_fragment_contains_safe_json_and_local_renderer():
    async def request():
        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/analytics?lang=en")

    response = asyncio.run(request())
    assert response.status_code == 200
    assert "Financial Analytics" in response.text
    assert "analytics-data" in response.text
    assert "onclick=" not in response.text
    match = re.search(
        r'<div id="analytics-data" hidden>(.*?)</div>',
        response.text,
        re.DOTALL,
    )
    assert match
    payload = json.loads(match.group(1))
    assert payload["quarterly"]["gross_margin_pct"][1]["company_en"] == "SMIC"
