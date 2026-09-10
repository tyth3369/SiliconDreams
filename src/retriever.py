"""Evidence-first hybrid retrieval: BGE-M3 dense search + BM25 + RRF."""

from __future__ import annotations

import logging
from typing import Any

from config import RAGConfig
from src.storage import Database
from src.vector_store import VectorStore

logger = logging.getLogger(__name__)


class Retriever:
    """Fuse dense and lexical rankings while preserving exact source provenance."""

    def __init__(
        self,
        vector_store: VectorStore | None = None,
        database: Database | None = None,
    ) -> None:
        self.store = vector_store or VectorStore()
        self.database = database or Database()

    def retrieve(
        self,
        query: str,
        top_k: int = RAGConfig.similarity_top_k,
        rerank: bool = True,
    ) -> list[dict[str, Any]]:
        if not query.strip() or top_k <= 0:
            return []

        route = self._route_query(query)
        candidate_count = max(top_k * 4, 20)
        dense = self.store.search_hybrid(query, top_k=candidate_count)
        lexical = self.database.search_chunks_bm25(query, limit=candidate_count)
        results = self._reciprocal_rank_fusion(dense, lexical, route)
        # `rerank` remains in the public API for compatibility. A model-backed
        # reranker can consume this candidate list without changing callers.
        selected = results[:top_k]
        logger.info(
            "Hybrid retrieval: query=%r route=%s dense=%d bm25=%d selected=%d",
            query[:80],
            route,
            len(dense),
            len(lexical),
            len(selected),
        )
        return selected

    def retrieve_with_sources(
        self, query: str, top_k: int = RAGConfig.similarity_top_k
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        results = self.retrieve(query, top_k=top_k)
        text_results = [item for item in results if item.get("source_type") != "table"]
        table_results = [item for item in results if item.get("source_type") == "table"]
        return text_results, table_results

    @staticmethod
    def _route_query(query: str) -> str:
        finance_indicators = (
            "毛利率",
            "净利率",
            "ROE",
            "ROA",
            "EPS",
            "PE",
            "PB",
            "营收",
            "收入",
            "成本",
            "利润",
            "资产",
            "负债",
            "现金流",
            "同比",
            "环比",
            "CAPEX",
            "EBITDA",
        )
        concept_indicators = ("什么是", "定义", "概念", "原理", "技术", "制程", "工艺", "架构")
        if any(term in query for term in finance_indicators):
            return "table_first"
        if any(term in query for term in concept_indicators):
            return "text_first"
        return "balanced"

    @staticmethod
    def _dense_key(item: dict[str, Any]) -> str:
        metadata = item.get("metadata") or {}
        return str(metadata.get("vector_id") or item.get("id") or "")

    @staticmethod
    def _lexical_key(item: dict[str, Any]) -> str:
        return str(item.get("vector_id") or item.get("id") or "")

    def _reciprocal_rank_fusion(
        self,
        dense: list[dict[str, Any]],
        lexical: list[dict[str, Any]],
        route: str,
        rrf_k: int = 60,
    ) -> list[dict[str, Any]]:
        """Fuse rank positions rather than incomparable raw similarity scores."""
        fused: dict[str, dict[str, Any]] = {}
        dense_weight = RAGConfig.hybrid_weight_vector
        lexical_weight = RAGConfig.hybrid_weight_bm25

        for rank, item in enumerate(dense, 1):
            key = self._dense_key(item)
            if not key:
                continue
            normalized = dict(item)
            normalized["source_type"] = (item.get("metadata") or {}).get("chunk_type", "text")
            normalized["dense_score"] = item.get("score", 0.0)
            normalized["rrf_score"] = dense_weight / (rrf_k + rank)
            fused[key] = normalized

        for rank, row in enumerate(lexical, 1):
            key = self._lexical_key(row)
            if not key:
                continue
            metadata = {
                "source": row.get("original_filename") or row.get("source_title") or "unknown",
                "page": row.get("page"),
                "section": row.get("section", ""),
                "chunk_type": row.get("chunk_type", "text"),
                "document_id": row.get("document_id"),
                "source_id": row.get("source_id"),
                "vector_id": key,
                "source_url": row.get("source_url"),
                "publisher": row.get("publisher"),
                "published_at": row.get("published_at"),
                "trust_tier": row.get("trust_tier"),
            }
            if key not in fused:
                fused[key] = {
                    "id": key,
                    "text": row.get("text", ""),
                    "metadata": metadata,
                    "source_type": row.get("chunk_type", "text"),
                    "dense_score": 0.0,
                    "rrf_score": 0.0,
                }
            else:
                fused[key]["metadata"] = {**metadata, **(fused[key].get("metadata") or {})}
            fused[key]["bm25_score"] = row.get("bm25_score", 0.0)
            fused[key]["rrf_score"] += lexical_weight / (rrf_k + rank)

        for item in fused.values():
            if route == "table_first" and item.get("source_type") == "table":
                item["rrf_score"] *= 1.15
            elif route == "text_first" and item.get("source_type") == "text":
                item["rrf_score"] *= 1.10
            item["score"] = item["rrf_score"]

        return sorted(fused.values(), key=lambda item: item["rrf_score"], reverse=True)


def get_retriever() -> Retriever:
    return Retriever()
