"""
SiliconDreams — RAG 检索工具 (Agent Tool)
==========================================
供 LangChain Agent 调用的搜索函数。
"""

import json
import logging

from langchain.tools import Tool

logger = logging.getLogger(__name__)


def create_search_tool():
    """创建 RAG 检索 Tool"""

    def search(query: str) -> str:
        """
        在已上传的财报/研报知识库中检索相关内容。

        Args:
            query: 自然语言查询（如"台积电2024毛利率"）

        Returns:
            JSON 格式的检索结果
        """
        try:
            from src.retriever import get_retriever
            retriever = get_retriever()
            results = retriever.retrieve(query, top_k=5)

            if not results:
                return json.dumps(
                    {"count": 0, "message": "未找到相关信息"},
                    ensure_ascii=False,
                )

            formatted = []
            for r in results:
                formatted.append({
                    "source": r["metadata"].get("source", "未知"),
                    "page": r["metadata"].get("page", "?"),
                    "type": r["metadata"].get("type", "text"),
                    "score": r["score"],
                    "text": r["text"][:800],  # 截断，Agent 不需要完整长文本
                })

            return json.dumps(
                {"count": len(formatted), "results": formatted},
                ensure_ascii=False,
            )

        except Exception as e:
            logger.error(f"检索失败: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    tool = Tool(
        name="search_reports",
        func=search,
        description=(
            "Search the uploaded financial reports and research knowledge base. "
            "Input a natural language query, returns relevant document excerpts. "
            "Use this tool when the user asks about specific data or financial metrics in reports."
        ),
    )

    return tool
