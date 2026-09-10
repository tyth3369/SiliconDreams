"""
SiliconDreams — 公司对比工具 (Agent Tool)
==========================================
多公司财务指标对比，必须调用 Calculator 保证计算准确。
"""

import json
import logging

from langchain.tools import Tool

logger = logging.getLogger(__name__)


def create_compare_tool():
    """创建公司对比 Tool"""

    def compare_companies(query: str) -> str:
        """
        对比多家公司的关键财务指标。

        工作流程:
        1. RAG 检索各公司的财务数据
        2. 调用 FinancialCalculator 精确计算
        3. 返回结构化对比结果

        Args:
            query: 对比请求（如"对比台积电和中芯国际的毛利率和ROE"）

        Returns:
            JSON 对比结果
        """
        try:
            # 1. 检索相关公司数据
            from src.retriever import get_retriever
            retriever = get_retriever()

            # 尝试提取公司名
            import re
            companies = re.findall(r'[一-鿿]{2,6}(?:公司|科技|半导体|电子|光电)?', query)
            companies = list(set(companies))[:3]  # 去重，最多3家

            if not companies:
                companies = ["台积电", "中芯国际"]  # 默认对比

            # 2. 检索各公司数据
            company_data = {}
            for company in companies:
                results = retriever.retrieve(f"{company} 营收 毛利率 净利润 ROE", top_k=5)
                snippets = [r["text"][:300] for r in results[:3]]
                company_data[company] = {
                    "snippets": snippets,
                    "source_count": len(results),
                }

            return json.dumps(
                {
                    "companies": list(company_data.keys()),
                    "data": company_data,
                    "instruction": (
                        "请基于检索到的数据，调用 financial_calculator 计算各公司的"
                        "毛利率、净利率、ROE、研发投入比，生成对比表格和分析。"
                    ),
                },
                ensure_ascii=False,
            )

        except Exception as e:
            logger.error(f"对比分析失败: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    tool = Tool(
        name="compare_companies",
        func=compare_companies,
        description=(
            "Compare key financial metrics across multiple semiconductor companies. "
            "Automatically retrieves financial data for each company. "
            "Must be used together with financial_calculator for accurate computations. "
            "Use this tool when the user asks to compare different companies."
        ),
    )

    return tool
