from datetime import date

from src.evidence_policy import (
    assess_web_results,
    build_answer_evidence_instruction,
    canonical_fact_value,
    is_time_sensitive_query,
    parse_source_date,
)


def _result(title, published_at, tier=3, score=0.5):
    return {
        "title": title,
        "url": f"https://example.com/{title}",
        "snippet": title,
        "published_at": published_at,
        "trust_tier": tier,
        "score": score,
    }


def test_source_date_parses_iso_and_rfc_2822():
    assert parse_source_date("2026-08-30") == date(2026, 8, 30)
    assert parse_source_date("Tue, 11 Mar 2025 17:00:00 GMT") == date(2025, 3, 11)
    assert parse_source_date("unknown") is None


def test_latest_query_rejects_future_and_marks_stale_or_undated():
    results, assessment = assess_web_results(
        "TSMC Arizona latest progress",
        [
            _result("future", "2026-09-12", tier=1),
            _result("current", "2026-09-01", tier=2),
            _result("old", "2024-01-01", tier=1),
            _result("unknown", "", tier=3),
        ],
        as_of=date(2026, 9, 11),
    )
    assert [item["title"] for item in results] == ["current", "old", "unknown"]
    assert {item["title"]: item["date_status"] for item in results} == {
        "current": "dated",
        "old": "stale",
        "unknown": "undated",
    }
    assert assessment.excluded_future == 1
    assert assessment.stale == 1
    assert assessment.undated == 1


def test_non_temporal_query_does_not_call_old_sources_stale():
    results, assessment = assess_web_results(
        "what is a foundry",
        [_result("definition", "2020-01-01")],
        as_of=date(2026, 9, 11),
    )
    assert results[0]["date_status"] == "dated"
    assert assessment.stale == 0


def test_answer_policy_exposes_source_mix_and_disagreement_rule():
    instruction = build_answer_evidence_instruction(
        "最新进展",
        [
            {"source_type": "web", "trust_tier": 1, "date_status": "dated"},
            {"source_type": "web", "trust_tier": 3, "date_status": "undated"},
        ],
        "zh",
    )
    assert "Tier 1=1" in instruction
    assert "日期未知=1" in instruction
    assert "必须明确列出分歧" in instruction


def test_time_sensitive_query_detection_is_bilingual():
    assert is_time_sensitive_query("台积电亚利桑那工厂近况")
    assert is_time_sensitive_query("TSMC latest progress")
    assert not is_time_sensitive_query("什么是先进制程")


def test_fact_values_are_canonicalized_before_conflict_detection():
    assert canonical_fact_value("33.10") == canonical_fact_value(33.1)
