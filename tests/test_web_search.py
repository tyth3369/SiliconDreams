from src.evidence_policy import WebEvidenceAssessment
from src.tools.web_search import (
    _do_search,
    _format_results,
    preferred_official_domains,
    source_trust_tier,
)


def test_official_subdomains_are_tier_one():
    assert source_trust_tier("https://investor.tsmc.com/english/quarterly-results") == 1
    assert source_trust_tier("https://www.sec.gov/Archives/report.htm") == 1


def test_reputable_reporting_is_tier_two():
    assert source_trust_tier("https://www.reuters.com/technology/chips/") == 2
    assert source_trust_tier("https://www.bbc.com/news/articles/example") == 2
    assert source_trust_tier("https://www.trendforce.com/news/example") == 2


def test_unknown_and_deceptive_domains_are_not_promoted():
    assert source_trust_tier("https://example.com/post") == 3
    assert source_trust_tier("https://tsmc.com.attacker.example/post") == 3


def test_formatted_results_expose_date_trust_and_policy():
    text = _format_results(
        "最新进展",
        "Tavily",
        [
            {
                "title": "Official update",
                "url": "https://tsmc.com/update",
                "publisher": "tsmc.com",
                "published_at": "2026-09-01",
                "trust_tier": 1,
                "date_status": "dated",
                "snippet": "Update",
            }
        ],
        WebEvidenceAssessment(True, 0, 0, 0),
    )
    assert "发布日期: 2026-09-01" in text
    assert "来源等级: Tier 1" in text
    assert "Tier 1 官方披露" in text


def test_explicit_company_filing_queries_prefer_official_domains():
    assert preferred_official_domains("台积电 2026 Q2 官方季报") == ["tsmc.com"]
    assert preferred_official_domains("SMIC annual report") == ["smic.com", "hkexnews.hk"]
    assert preferred_official_domains("台积电亚利桑那近况") == []


def test_search_cache_avoids_repeated_backend_calls(tmp_path, monkeypatch):
    from src.storage import Database

    database = Database(tmp_path / "cache.db")
    calls = []

    def fake_search(query, max_results):
        calls.append((query, max_results))
        return [
            {
                "title": "Official update",
                "url": "https://tsmc.com/update",
                "snippet": "Evidence",
                "score": 0.9,
                "publisher": "tsmc.com",
                "published_at": "2026-09-01",
                "trust_tier": 1,
            }
        ], "Tavily"

    monkeypatch.setattr("src.tools.web_search._cache_database", lambda: database)
    monkeypatch.setattr("src.tools.web_search._search_tavily", fake_search)
    monkeypatch.setattr("src.tools.web_search.SearchConfig.api_key", "tvly-test")
    first, _ = _do_search("TSMC latest", 5)
    second, formatted = _do_search("TSMC latest", 5)
    assert first == second
    assert len(calls) == 1
    assert "Tavily cache" in formatted
    assert database.count("web_snapshots") == 1
