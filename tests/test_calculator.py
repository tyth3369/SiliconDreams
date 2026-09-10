import pytest
from pydantic import ValidationError

from src.tools.calculator import CalculationRequest, FinancialCalculator, calculate_financial


@pytest.mark.parametrize(
    ("input_data", "expected"),
    [
        ({"operation": "yoy_growth", "operands": {"current": 120, "prior": 100}}, 20.0),
        ({"operation": "qoq_growth", "operands": {"current": 33.73, "previous": 33.1}}, 1.9),
        ({"operation": "gross_margin", "operands": {"revenue": 100, "cost": 43.8}}, 56.2),
        ({"operation": "net_margin", "operands": {"net_profit": 45.3, "revenue": 100}}, 45.3),
        ({"operation": "roe", "operands": {"net_profit": 20, "equity": 100}}, 20.0),
        ({"operation": "roa", "operands": {"net_profit": 10, "total_assets": 200}}, 5.0),
        (
            {"operation": "debt_ratio", "operands": {"total_liabilities": 40, "total_assets": 100}},
            40.0,
        ),
        (
            {
                "operation": "current_ratio",
                "operands": {"current_assets": 150, "current_liabilities": 100},
            },
            1.5,
        ),
        ({"operation": "pe_ratio", "operands": {"stock_price": 120, "eps": 6}}, 20.0),
        (
            {"operation": "revenue_per_employee", "operands": {"revenue": 1000, "employees": 10}},
            100.0,
        ),
        ({"operation": "rd_ratio", "operands": {"rd_expense": 15, "revenue": 100}}, 15.0),
        ({"operation": "difference", "operands": {"current": 62.3, "prior": 59.5}}, 2.8),
        ({"operation": "ratio", "operands": {"numerator": 25, "denominator": 100}}, 0.25),
    ],
)
def test_calculation_dispatch(input_data, expected):
    assert calculate_financial(input_data)["result"] == pytest.approx(expected)


@pytest.mark.parametrize(
    ("operation", "operands"),
    [
        ("yoy_growth", {"current": 10, "prior": 0}),
        ("qoq_growth", {"current": 10, "previous": 0}),
        ("gross_margin", {"revenue": 0, "cost": 0}),
        ("net_margin", {"net_profit": 1, "revenue": 0}),
        ("current_ratio", {"current_assets": 1, "current_liabilities": 0}),
        ("ratio", {"numerator": 1, "denominator": 0}),
    ],
)
def test_zero_denominator_returns_none(operation, operands):
    assert calculate_financial({"operation": operation, "operands": operands})["result"] is None


def test_missing_operand_is_reported():
    result = calculate_financial(
        {"operation": "qoq_growth", "operands": {"current": 10, "other": 2}}
    )
    assert result["error"] == "missing_operands"
    assert result["required"] == ["current", "previous"]


def test_unknown_operation_is_rejected():
    with pytest.raises(ValidationError):
        CalculationRequest.model_validate(
            {"operation": "growth_rate", "operands": {"a": 1, "b": 2}}
        )


def test_extra_top_level_field_is_rejected():
    with pytest.raises(ValidationError):
        CalculationRequest.model_validate(
            {"operation": "ratio", "operands": {"numerator": 1, "denominator": 2}, "extra": True}
        )


def test_decimal_input_is_not_binary_float_math():
    result = FinancialCalculator.qoq_growth(0.3, 0.1)
    assert result["result"] == 200.0
