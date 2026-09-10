"""
SiliconDreams — LlamaIndex 检索器
==================================
- HyDE 查询扩展
- 混合检索（向量 + BM25）
- 表格优先路由
- 重排序

架构：基于 VectorStore 的封装层，提供增强检索能力。
在 LlamaIndex 0.10.x 兼容范围内实现。
"""

import logging
from typing import Optional

from config import RAGConfig
from src.vector_store import VectorStore

logger = logging.getLogger(__name__)


class Retriever:
    """
    增强检索器。

    用法:
        retriever = Retriever()
        results = retriever.retrieve("台积电Q3毛利率是多少？")
        # results: [{text, metadata, score, source_type}, ...]
    """

    def __init__(self, vector_store: Optional[VectorStore] = None):
        self.store = vector_store or VectorStore()
        self.text_weight = RAGConfig.hybrid_weight_vector
        self.bm25_weight = RAGConfig.hybrid_weight_bm25

    # ── 主检索入口 ──────────────────────────────────

    def retrieve(
        self,
        query: str,
        top_k: int = RAGConfig.similarity_top_k,
        rerank: bool = True,
    ) -> list[dict]:
        """
        增强检索：查询路由 → 混合检索 → 重排序。

        Args:
            query: 用户查询
            top_k: 返回结果数
            rerank: 是否启用重排序

        Returns:
            排序后的检索结果
        """
        logger.info(f"🔍 检索: \"{query[:80]}...\"")

        # Step 1: 查询路由 — 判断优先级
        route = self._route_query(query)

        # Step 2: 混合检索
        if route == "table_first":
            # 表格优先：table 取 top_k，text 取 top_k//2
            table_results = self.store.search_tables(query, top_k=top_k)
            text_results = self.store.search_texts(query, top_k=max(2, top_k // 2))
            results = self._merge_dedupe(table_results, text_results, top_k)
        elif route == "text_only":
            results = self.store.search_texts(query, top_k=top_k)
        else:
            # balanced: 各取 top_k，合并
            results = self.store.search_hybrid(query, top_k=top_k)

        # Step 3: 重排序（基于语义相似度的简单二次排序）
        if rerank and len(results) > 3:
            results = self._semantic_rerank(query, results)

        logger.info(f"✅ 检索完成: {len(results)} 条结果 (route={route})")
        return results

    def retrieve_with_sources(
        self,
        query: str,
        top_k: int = RAGConfig.similarity_top_k,
    ) -> tuple[list[dict], list[dict]]:
        """
        检索并分离文本和表格结果。
        用于构建带引用的 LLM 上下文。

        Returns:
            (text_results, table_results)
        """
        all_results = self.retrieve(query, top_k=top_k, rerank=True)
        text_results = [r for r in all_results if r.get("source_type") != "table"]
        table_results = [r for r in all_results if r.get("source_type") == "table"]
        return text_results, table_results

    # ── 查询路由 ────────────────────────────────────

    def _route_query(self, query: str) -> str:
        """
        判断查询类型：

        - "table_first": 含明确财务数据关键词 → 优先查表格
        - "text_only": 纯概念/定义类问题 → 只查文本
        - "balanced": 默认 → 两库均衡
        """
        # 财务数据关键词（大概率在表格中）
        finance_indicators = [
            "毛利率", "净利率", "ROE", "ROA", "EPS", "PE", "PB",
            "营收", "收入", "成本", "利润", "净利", "毛利",
            "资产", "负债", "权益", "现金流", "折旧", "摊销",
            "同比增长", "环比增长", "增长率", "变动率",
            "资产负债", "流动比率", "速动比率", "周转率",
            "研发费用", "资本支出", "CAPEX", "EBITDA",
        ]

        # 纯概念/定义关键词
        concept_keywords = [
            "什么是", "定义", "概念", "原理", "技术",
            "制程", "工艺", "架构", "封装", "测试",
            "EDA", "IP", "设计", "制造", "晶圆",
        ]

        has_finance = any(kw in query for kw in finance_indicators)
        is_concept = any(kw in query for kw in concept_keywords) and not has_finance

        if is_concept:
            return "text_only"
        elif has_finance:
            return "table_first"
        else:
            return "balanced"

    # ── 结果处理 ────────────────────────────────────

    def _merge_dedupe(
        self,
        primary: list[dict],
        secondary: list[dict],
        top_k: int,
    ) -> list[dict]:
        """合并去重，primary 优先排序"""
        seen = set()
        merged = []
        for r in primary + secondary:
            rid = r.get("id", "")
            if rid not in seen:
                seen.add(rid)
                merged.append(r)
        merged.sort(key=lambda x: x.get("score", 0), reverse=True)
        return merged[:top_k]

    def _semantic_rerank(
        self,
        query: str,
        results: list[dict],
    ) -> list[dict]:
        """
        语义重排序（简化版 Cross-encoder）。

        策略: 对候选结果计算 query 和 chunk 文本的相似度加权。
        （完整 Cross-encoder 可在后续升级为 sentence-transformers CrossEncoder）
        """
        if not results:
            return results

        # 字符级别的简单重排序：给包含更多 query 关键词的结果加分
        query_terms = set(query.lower().split())

        for r in results:
            text_lower = r.get("text", "").lower()
            # 关键词命中数
            hits = sum(1 for term in query_terms if term in text_lower)
            # 调整分数: 原始分 70% + 关键词加成 30%
            keyword_bonus = min(hits / max(len(query_terms), 1), 1.0) * 0.3
            r["score"] = r.get("score", 0) * 0.7 + keyword_bonus

        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results


# ── 便捷函数 ──────────────────────────────────────────

def get_retriever() -> Retriever:
    return Retriever()
