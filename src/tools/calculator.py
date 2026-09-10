"""
SiliconDreams — 财务精确计算器
===============================
核心理念: RAG 捞数 → Python 精确计算 → LLM 润色叙事
LLM 不碰数字计算，只负责语言生成。

支持 10 种财务比率 + 同比/环比增长率。
使用 Python decimal 保证金融级精度，pandas 处理批量对比。

LangChain Tool 接口: 供 Agent 调用
"""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

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
            return {"result": None, "formula": "N/A (基数为零)", "interpretation": "无法计算：去年同期值为零"}

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
        l, a = Decimal(str(total_liabilities)), Decimal(str(total_assets))
        if a == 0:
            return {"result": None, "formula": "N/A", "interpretation": "无法计算：总资产为零"}

        result = float(l / a * 100)
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

        result = float(r / employees)
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
                row["roe"] = FinancialCalculator.roe(
                    data["net_profit"], data["equity"]
                )["result"]
            if "rd_expense" in data and "revenue" in data:
                row["rd_ratio"] = FinancialCalculator.rd_ratio(
                    data["rd_expense"], data["revenue"]
                )["result"]
            if "total_liabilities" in data and "total_assets" in data:
                row["debt_ratio"] = FinancialCalculator.debt_ratio(
                    data["total_liabilities"], data["total_assets"]
                )["result"]
            results.append(row)
        return results


# ═══════════════════════════════════════════════════
# LangChain Tool 封装
# ═══════════════════════════════════════════════════

def create_calculator_tool():
    """
    创建 LangChain Tool 供 Agent 调用。

    Agent 在涉及数字计算时必须优先调用此 Tool，
    严禁 LLM 自行心算。
    """
    from langchain.tools import Tool

    calc = FinancialCalculator()

    def calculate(expression: str) -> str:
        """
        执行财务计算。

        输入格式（JSON 字符串）:
        {
            "method": "yoy_growth" | "qoq_growth" | "gross_margin" | "net_margin"
                     | "roe" | "debt_ratio" | "current_ratio" | "pe_ratio"
                     | "revenue_per_employee" | "rd_ratio",
            "params": { ... 各方法的参数 ... }
        }

        示例:
        {"method": "yoy_growth", "params": {"current": 57.8, "prior": 54.3}}
        {"method": "gross_margin", "params": {"revenue": 1000, "cost": 430}}
        """
        import json

        try:
            req = json.loads(expression)
            method = req.get("method", "")
            params = req.get("params", {})

            func = getattr(calc, method, None)
            if func is None:
                return json.dumps({"error": f"未知计算方法: {method}"}, ensure_ascii=False)

            result = func(**params)
            return json.dumps(result, ensure_ascii=False, default=str)

        except Exception as e:
            logger.error(f"财务计算失败: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    tool = Tool(
        name="financial_calculator",
        func=calculate,
        description=(
            "[MANDATORY] Execute precise financial ratio and growth rate calculations. "
            "When dealing with numerical comparisons, ratio calculations, or YoY/QoQ analysis, "
            "you MUST call this tool for accurate results — NEVER calculate manually. "
            "Supports: yoy_growth, qoq_growth, gross_margin, net_margin, roe, "
            "debt_ratio, current_ratio, pe_ratio, revenue_per_employee, rd_ratio."
        ),
    )

    return tool


# ── 便捷函数 ──────────────────────────────────────────
def get_calculator() -> FinancialCalculator:
    return FinancialCalculator()
