"""
SiliconDreams — 技术趋势分析工具 (Agent Tool)
==============================================
结合术语库进行技术联想+财报检索。
"""

import json
import logging

from langchain.tools import Tool

logger = logging.getLogger(__name__)


def create_analyze_tool():
    """创建技术趋势分析 Tool"""

    def analyze_technology(query: str) -> str:
        """
        分析半导体技术趋势及商业影响。

        Args:
            query: 技术关键词或问题（如"分析3nm制程的商业影响"）

        Returns:
            JSON: 术语定义 + 相关知识库内容
        """
        try:
            # 1. 查术语库
            from src.terminology import get_terminology
            tm = get_terminology()
            terms = tm.find_terms(query)

            term_info = []
            for t in terms[:5]:  # 最多5条
                term_info.append({
                    "term": t["name"],
                    "definition": t.get("definition", ""),
                    "business_impact": t.get("business_impact", ""),
                    "related_terms": t.get("related_terms", []),
                    "related_companies": t.get("related_companies", []),
                })

            # 2. 如果有知识库，同步检索相关财报段落
            try:
                from src.retriever import get_retriever
                retriever = get_retriever()
                results = retriever.retrieve(query, top_k=3)

                report_context = []
                for r in results:
                    report_context.append({
                        "source": r["metadata"].get("source", ""),
                        "page": r["metadata"].get("page", "?"),
                        "text": r["text"][:500],
                    })
            except Exception:
                report_context = []

            return json.dumps(
                {
                    "query": query,
                    "terminology": term_info,
                    "related_reports": report_context,
                    "suggestion": (
                        "请基于术语定义和财报数据，"
                        "分析该技术对相关公司的财务影响和战略意义。"
                    ),
                },
                ensure_ascii=False,
            )

        except Exception as e:
            logger.error(f"技术分析失败: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    tool = Tool(
        name="analyze_technology",
        func=analyze_technology,
        description=(
            "Analyze semiconductor technology trends and their business impact. "
            "Input a technology keyword or question, returns the technology's definition, "
            "business impact analysis, related companies and technologies, "
            "and quantitative data from relevant financial reports. "
            "Use this tool when the user asks about technology trends, process analysis, "
            "or technology competitive landscape."
        ),
    )

    return tool
