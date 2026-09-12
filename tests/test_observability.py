from config import ObservabilityConfig
from src.observability import RunTelemetry, is_tool_error
from src.tools.calculator import calculate_llm_usage_cost, summarize_numeric_values


def test_usage_cost_uses_decimal_rates():
    assert (
        calculate_llm_usage_cost(
            cache_hit_tokens=1_000_000,
            cache_miss_tokens=2_000_000,
            completion_tokens=500_000,
            cache_hit_usd_per_million="0.10",
            cache_miss_usd_per_million="0.40",
            output_usd_per_million="1.00",
        )
        == "1.40000000"
    )


def test_numeric_summary_uses_nearest_rank_p95():
    assert summarize_numeric_values([10, 20, 30, 40])["p95"] == 40.0
    assert summarize_numeric_values([]) == {"count": 0, "average": None, "p95": None}


def test_run_telemetry_contains_aggregates_but_no_research_content(monkeypatch):
    monkeypatch.setattr(ObservabilityConfig, "input_cache_hit_usd_per_million", "0.1")
    monkeypatch.setattr(ObservabilityConfig, "input_cache_miss_usd_per_million", "0.4")
    monkeypatch.setattr(ObservabilityConfig, "output_usd_per_million", "1.0")
    telemetry = RunTelemetry(
        request_id="request-1",
        conversation_id="conversation-1",
        provider="deepseek",
        model="model",
    )
    telemetry.model_call_started()
    telemetry.add_usage(
        {
            "prompt_tokens": 30,
            "completion_tokens": 10,
            "prompt_cache_hit_tokens": 20,
            "prompt_cache_miss_tokens": 10,
        }
    )
    telemetry.record_tool("web_search", 0.125)
    telemetry.first_token()
    run = telemetry.finish([{"source_type": "web"}, {"source_type": "financial"}])

    assert run["status"] == "success"
    assert run["tool_calls"] == 1
    assert run["source_types"] == {"financial": 1, "web": 1}
    assert run["estimated_cost_usd"] == "0.00001600"
    assert "query" not in run
    assert "answer" not in run
    serialized = str(run).lower()
    assert "secret research question" not in serialized
    assert "secret answer" not in serialized
    assert "https://" not in serialized


def test_structured_tool_errors_are_detected():
    assert is_tool_error('{"error":"failed"}') is True
    assert is_tool_error("ordinary evidence") is False


def test_final_response_failure_is_an_error_not_a_degraded_success():
    telemetry = RunTelemetry("request", "conversation", "deepseek", "model")
    telemetry.model_call_started()
    telemetry.model_call_failed("final_response_failed")
    telemetry.fail("final_response_failed")
    assert telemetry.finish([])["status"] == "error"


def test_malformed_usage_metadata_cannot_break_the_request():
    telemetry = RunTelemetry("request", "conversation", "deepseek", "model")
    telemetry.add_usage(
        {
            "prompt_tokens": "not-a-number",
            "completion_tokens": None,
            "prompt_cache_hit_tokens": object(),
        }
    )
    run = telemetry.finish([])
    assert run["prompt_tokens"] == 0
    assert run["completion_tokens"] == 0
    assert run["cache_hit_tokens"] == 0
