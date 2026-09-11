import pytest
from pydantic import ValidationError

from src.analysis_templates import (
    CompanyComparisonRequest,
    build_company_comparison_prompt,
    default_foundry_comparison_prompt,
    load_metric_definitions,
)


def test_metric_registry_contains_comparable_and_derived_scopes():
    metrics = load_metric_definitions()

    assert metrics["revenue"]["comparability"] == "direct"
    assert metrics["gross_margin"]["comparability"] == "direct"
    assert metrics["operating_margin"]["calculator_operation"] == "ratio"


def test_comparison_request_requires_at_least_two_companies():
    with pytest.raises(ValidationError):
        CompanyComparisonRequest(companies=["台积电"], periods=["2026 Q2"], metrics=["revenue"])


def test_chinese_comparison_prompt_preserves_disclosure_and_calculator_rules():
    prompt = default_foundry_comparison_prompt("zh")

    assert "台积电、中芯国际" in prompt
    assert "2026 Q2" in prompt
    assert "直接披露" in prompt
    assert "中芯国际数值标为派生值" in prompt
    assert "financial_calculator" in prompt


def test_english_comparison_prompt_is_bilingual():
    prompt = default_foundry_comparison_prompt("en")

    assert "Revenue" in prompt
    assert "Gross margin" in prompt
    assert "SMIC must be labelled as derived" in prompt


def test_unknown_metric_is_rejected():
    request = CompanyComparisonRequest(
        companies=["TSMC", "SMIC"], periods=["2026 Q2"], metrics=["invented_metric"]
    )

    with pytest.raises(ValueError, match="unknown comparison metrics"):
        build_company_comparison_prompt(request)
