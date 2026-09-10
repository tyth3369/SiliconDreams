"""
SiliconDreams — 财务精确计算器
===============================
核心理念: RAG 捞数 → Python 精确计算 → LLM 润色叙事
LLM 不碰数字计算，只负责语言生成。

支持 10 种财务比率 + 同比/环比增长率。
使用 Python decimal 保证金融级精度。
本模块是项目中所有财务计算的唯一实现。
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# 核心计算函数
# ═══════════════════════════════════════════════════


class FinancialCalculator:
    """财务计算器（所有计算 100% Python 执行，零 LLM 依赖）"""

    @staticmethod
    def _to_decimal(value) -> Decimal:
        """安全转 Decimal"""
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def _fmt(value, precision: int = 2) -> str:
        """格式化输出"""
        return str(round(value, precision))

    # ── 增长率 ──────────────────────────────────────

    @staticmethod
    def yoy_growth(current: float, prior: float) -> dict:
        """
        同比增长率 = (当期 - 去年同期) / 去年同期 × 100

        Args:
            current: 当期值
            prior: 去年同期值
        """
        c, p = Decimal(str(current)), Decimal(str(prior))
        if p == 0:
            return {
                "result": None,
                "formula": "N/A (基数为零)",
                "interpretation": "无法计算：去年同期值为零",
            }

        result = float((c - p) / p * 100)
        direction = "上升" if result > 0 else ("下降" if result < 0 else "持平")
        return {
            "result": round(result, 2),
            "formula": f"({current} - {prior}) / {prior} × 100",
            "interpretation": f"{direction}{abs(result):.2f}%",
            "raw": {"current": current, "prior": prior, "change": abs(current - prior)},
        }

    @staticmethod
    def qoq_growth(current: float, previous: float) -> dict:
        """
        环比增长率 = (当期 - 上期) / 上期 × 100
        """
        return FinancialCalculator.yoy_growth(current, previous)

    # ── 盈利能力 ────────────────────────────────────

    @staticmethod
    def gross_margin(revenue: float, cost: float) -> dict:
        """
        毛利率 = (营收 - 营业成本) / 营收 × 100
        """
        r, c = Decimal(str(revenue)), Decimal(str(cost))
        if r == 0:
            return {"result": None, "formula": "N/A", "interpretation": "无法计算：营收为零"}

        result = float((r - c) / r * 100)
        return {
            "result": round(result, 2),
            "formula": f"({revenue} - {cost}) / {revenue} × 100",
            "interpretation": f"毛利率为 {result:.2f}%",
            "raw": {"revenue": revenue, "cost": cost, "gross_profit": revenue - cost},
        }

    @staticmethod
    def net_margin(net_profit: float, revenue: float) -> dict:
        """
        净利率 = 净利润 / 营收 × 100
        """
        n, r = Decimal(str(net_profit)), Decimal(str(revenue))
        if r == 0:
            return {"result": None, "formula": "N/A", "interpretation": "无法计算：营收为零"}

        result = float(n / r * 100)
        return {
            "result": round(result, 2),
            "formula": f"{net_profit} / {revenue} × 100",
            "interpretation": f"净利率为 {result:.2f}%",
        }

    # ── 回报率 ──────────────────────────────────────

    @staticmethod
    def roe(net_profit: float, equity: float) -> dict:
        """
        净资产收益率 (ROE) = 净利润 / 股东权益 × 100
        """
        n, e = Decimal(str(net_profit)), Decimal(str(equity))
        if e == 0:
            return {"result": None, "formula": "N/A", "interpretation": "无法计算：股东权益为零"}

        result = float(n / e * 100)
        return {
            "result": round(result, 2),
            "formula": f"{net_profit} / {equity} × 100",
            "interpretation": f"ROE 为 {result:.2f}%",
        }

    @staticmethod
    def roa(net_profit: float, total_assets: float) -> dict:
        """
        总资产收益率 (ROA) = 净利润 / 总资产 × 100
        """
        return FinancialCalculator.roe(net_profit, total_assets)

    # ── 偿债能力 ────────────────────────────────────

    @staticmethod
    def debt_ratio(total_liabilities: float, total_assets: float) -> dict:
        """
        资产负债率 = 总负债 / 总资产 × 100
        """
        liabilities = Decimal(str(total_liabilities))
        assets = Decimal(str(total_assets))
        if assets == 0:
            return {"result": None, "formula": "N/A", "interpretation": "无法计算：总资产为零"}

        result = float(liabilities / assets * 100)
        return {
            "result": round(result, 2),
            "formula": f"{total_liabilities} / {total_assets} × 100",
            "interpretation": f"资产负债率为 {result:.2f}%",
        }

    @staticmethod
    def current_ratio(current_assets: float, current_liabilities: float) -> dict:
        """
        流动比率 = 流动资产 / 流动负债
        """
        ca = Decimal(str(current_assets))
        cl = Decimal(str(current_liabilities))
        if cl == 0:
            return {"result": None, "formula": "N/A", "interpretation": "无法计算：流动负债为零"}

        result = float(ca / cl)
        health = "健康" if result >= 1.5 else ("一般" if result >= 1.0 else "偏紧")
        return {
            "result": round(result, 2),
            "formula": f"{current_assets} / {current_liabilities}",
            "interpretation": f"流动比率为 {result:.2f}（{health}）",
        }

    # ── 估值 ────────────────────────────────────────

    @staticmethod
    def pe_ratio(stock_price: float, eps: float) -> dict:
        """
        市盈率 (P/E) = 股价 / 每股收益
        """
        p, e = Decimal(str(stock_price)), Decimal(str(eps))
        if e == 0:
            return {"result": None, "formula": "N/A", "interpretation": "无法计算：EPS为零"}

        result = float(p / e)
        valuation = "高估值" if result > 30 else ("合理" if result > 15 else "低估值")
        return {
            "result": round(result, 2),
            "formula": f"{stock_price} / {eps}",
            "interpretation": f"P/E 为 {result:.2f} 倍（{valuation}，需结合行业平均水平判断）",
        }

    # ── 效率指标 ────────────────────────────────────

    @staticmethod
    def revenue_per_employee(revenue: float, employees: int) -> dict:
        """
        人均创收 = 营收 / 员工数
        """
        r = Decimal(str(revenue))
        if employees == 0:
            return {"result": None, "formula": "N/A", "interpretation": "无法计算：员工数为零"}

        result = float(r / Decimal(str(employees)))
        return {
            "result": round(result, 2),
            "formula": f"{revenue} / {employees}",
            "interpretation": f"人均创收 {result:,.0f} 元/人",
        }

    @staticmethod
    def rd_ratio(rd_expense: float, revenue: float) -> dict:
        """
        研发投入比 = 研发费用 / 营收 × 100
        （半导体行业最核心的创新投入指标）
        """
        r, rev = Decimal(str(rd_expense)), Decimal(str(revenue))
        if rev == 0:
            return {"result": None, "formula": "N/A", "interpretation": "无法计算：营收为零"}

        result = float(r / rev * 100)
        intensity = "超高投入" if result > 20 else ("高投入" if result > 10 else "适中")
        return {
            "result": round(result, 2),
            "formula": f"{rd_expense} / {revenue} × 100",
            "interpretation": f"研发投入比为 {result:.2f}%（{intensity}，半导体行业通常 10-25%）",
        }

    @staticmethod
    def difference(current: float, prior: float) -> dict:
        """绝对差值及相对变化幅度。"""
        c, p = Decimal(str(current)), Decimal(str(prior))
        diff = c - p
        relative = None if p == 0 else diff / p * 100
        return {
            "result": float(diff),
            "relative_change_pct": None if relative is None else round(float(relative), 2),
            "formula": f"{current} - {prior}",
            "interpretation": f"差值为 {float(diff):.2f}",
        }

    @staticmethod
    def ratio(numerator: float, denominator: float) -> dict:
        """通用比率 = 分子 / 分母。"""
        n, d = Decimal(str(numerator)), Decimal(str(denominator))
        if d == 0:
            return {"result": None, "formula": "N/A", "interpretation": "无法计算：分母为零"}
        result = n / d
        return {
            "result": round(float(result), 4),
            "formula": f"{numerator} / {denominator}",
            "interpretation": f"比率为 {float(result):.4f}",
        }

    # ── 批量计算 ────────────────────────────────────

    @staticmethod
    def batch_compare(metrics: dict) -> list[dict]:
        """
        批量财务对比。

        Args:
            metrics = {
                "台积电": {"revenue": 100, "net_profit": 40, "equity": 200, ...},
                "中芯国际": {"revenue": 50, "net_profit": 10, "equity": 100, ...},
            }

        Returns:
            [{company, gross_margin, net_margin, roe, rd_ratio, ...}, ...]
        """
        results = []
        for company, data in metrics.items():
            row = {"company": company}
            if "revenue" in data and "cost" in data:
                row["gross_margin"] = FinancialCalculator.gross_margin(
                    data["revenue"], data["cost"]
                )["result"]
            if "net_profit" in data and "revenue" in data:
                row["net_margin"] = FinancialCalculator.net_margin(
                    data["net_profit"], data["revenue"]
                )["result"]
            if "net_profit" in data and "equity" in data:
                row["roe"] = FinancialCalculator.roe(data["net_profit"], data["equity"])["result"]
            if "rd_expense" in data and "revenue" in data:
                row["rd_ratio"] = FinancialCalculator.rd_ratio(data["rd_expense"], data["revenue"])[
                    "result"
                ]
            if "total_liabilities" in data and "total_assets" in data:
                row["debt_ratio"] = FinancialCalculator.debt_ratio(
                    data["total_liabilities"], data["total_assets"]
                )["result"]
            results.append(row)
        return results


CalculationOperation = Literal[
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
]


class CalculationRequest(BaseModel):
    """Validated, structured input accepted by the Agent calculator tool."""

    model_config = ConfigDict(extra="forbid")

    operation: CalculationOperation
    operands: dict[str, float] = Field(min_length=2)


_REQUIRED_OPERANDS: dict[str, tuple[str, ...]] = {
    "yoy_growth": ("current", "prior"),
    "qoq_growth": ("current", "previous"),
    "gross_margin": ("revenue", "cost"),
    "net_margin": ("net_profit", "revenue"),
    "roe": ("net_profit", "equity"),
    "roa": ("net_profit", "total_assets"),
    "debt_ratio": ("total_liabilities", "total_assets"),
    "current_ratio": ("current_assets", "current_liabilities"),
    "pe_ratio": ("stock_price", "eps"),
    "revenue_per_employee": ("revenue", "employees"),
    "rd_ratio": ("rd_expense", "revenue"),
    "difference": ("current", "prior"),
    "ratio": ("numerator", "denominator"),
}


def calculate_financial(request: CalculationRequest | dict) -> dict:
    """Validate and execute one financial calculation through the canonical calculator."""
    parsed = (
        request
        if isinstance(request, CalculationRequest)
        else CalculationRequest.model_validate(request)
    )
    required = _REQUIRED_OPERANDS[parsed.operation]
    missing = [name for name in required if name not in parsed.operands]
    if missing:
        return {
            "error": "missing_operands",
            "message": f"缺少参数: {', '.join(missing)}",
            "required": list(required),
        }

    func = getattr(FinancialCalculator, parsed.operation)
    params = {name: parsed.operands[name] for name in required}
    result = func(**params)
    return {"operation": parsed.operation, "operands": params, **result}


# ── 便捷函数 ──────────────────────────────────────────
def get_calculator() -> FinancialCalculator:
    return FinancialCalculator()
