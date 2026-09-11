"""Evidence-first hybrid retrieval: BGE-M3 dense search + BM25 + RRF."""

from __future__ import annotations

import logging
import re
from typing import Any

from config import RAGConfig
from src.reranker import RerankerManager
from src.storage import Database
from src.vector_store import VectorStore

logger = logging.getLogger(__name__)


_COMPANY_ALIASES: dict[str, tuple[str, ...]] = {
    "tsmc": ("台积电", "tsmc", "taiwan semiconductor manufacturing"),
    "smic": ("中芯国际", "smic", "semiconductor manufacturing international"),
}

_QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "营收": ("revenue",),
    "同比": ("year-on-year", "YoY"),
    "毛利率": ("gross margin",),
    "营业利润率": ("operating profit margin",),
    "产能利用率": ("utilisation rate", "utilization rate"),
    "研发费用": ("research and development expenses", "R&D expenses"),
    "出货": ("shipments",),
    "产能": ("manufacturing capacity",),
    "晶圆营收": ("wafer revenue",),
    "先进制程": ("advanced technologies", "advanced process nodes"),
}


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
        expanded_query = self._expand_query(query)
        source_filters = self._matching_sources(query)
        candidate_count = max(top_k * 12, 64)
        dense = self.store.search_hybrid(query, top_k=candidate_count, sources=source_filters)
        lexical_original = self.database.search_chunks_bm25(
            query, limit=candidate_count, sources=source_filters
        )
        lexical_expanded = (
            self.database.search_chunks_bm25(
                expanded_query, limit=candidate_count, sources=source_filters
            )
            if expanded_query != query
            else []
        )
        lexical = self._merge_rankings(lexical_original, lexical_expanded, candidate_count)
        results = self._reciprocal_rank_fusion(dense, lexical, route)
        results = self._scope_to_named_companies(query, results)
        if rerank and len(results) > 1:
            selected = RerankerManager.get_instance().rerank(
                query,
                results[:candidate_count],
                top_n=candidate_count,
            )
            selected = self._prioritize_answer_evidence(query, selected)[:top_k]
        else:
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

    @staticmethod
    def _merge_rankings(
        primary: list[dict[str, Any]], secondary: list[dict[str, Any]], limit: int
    ) -> list[dict[str, Any]]:
        """Fuse original and expanded lexical queries without letting either dominate."""
        if not secondary:
            return primary[:limit]
        scores: dict[str, float] = {}
        items: dict[str, dict[str, Any]] = {}
        for ranking in (primary, secondary):
            for rank, item in enumerate(ranking, 1):
                key = str(item.get("vector_id") or item.get("id") or "")
                if not key:
                    continue
                items[key] = item
                scores[key] = max(scores.get(key, 0.0), 1.0 / (60 + rank))
        ordered = sorted(items, key=lambda key: scores[key], reverse=True)
        return [items[key] for key in ordered[:limit]]

    @staticmethod
    def _prioritize_answer_evidence(
        query: str, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Prefer passages containing the metric concepts explicitly asked for."""
        query_normalized = " ".join(query.lower().split())
        concept_groups = (
            (("营收", "revenue"), ("revenue", "营收")),
            (("同比", "year-on-year", "yoy"), ("year-on-year", "yoy", "同比")),
            (("毛利率", "gross margin"), ("gross margin", "毛利率")),
            (
                ("营业利润率", "operating profit margin"),
                ("operating profit margin", "营业利润率"),
            ),
            (
                ("产能利用率", "utilisation rate", "utilization rate"),
                ("utilisation rate", "utilization rate", "产能利用率"),
            ),
            (
                ("研发费用", "research and development expenses", "r&d expenses"),
                ("research and development expenses", "r&d expenses", "研发费用"),
            ),
            (("出货", "shipments"), ("shipments", "wafer shipment", "出货")),
            (
                ("产能", "manufacturing capacity"),
                ("annual capacity", "manufacturing capacity", "monthly capacity", "产能"),
            ),
            (
                ("先进制程", "advanced technologies", "advanced process"),
                ("advanced technologies", "advanced process", "7nm and more advanced", "先进制程"),
            ),
        )
        active_groups = [
            evidence
            for triggers, evidence in concept_groups
            if any(trigger in query_normalized for trigger in triggers)
        ]
        node_tokens = set(re.findall(r"\b\d+(?:\.\d+)?\s*nm\b", query_normalized))

        ranked = []
        for original_rank, candidate in enumerate(candidates, 1):
            text = " ".join(str(candidate.get("text", "")).lower().split())
            coverage = sum(any(term in text for term in group) for group in active_groups)
            coverage += sum(
                token.replace(" ", "") in text.replace(" ", "") for token in node_tokens
            )
            item = dict(candidate)
            item["evidence_coverage"] = coverage
            ranked.append((coverage, original_rank, item))
        ranked.sort(key=lambda entry: (-entry[0], entry[1]))
        return [entry[2] for entry in ranked]

    def _matching_sources(self, query: str) -> list[str] | None:
        """Resolve explicit company mentions to exact indexed report filenames."""
        targets = self._named_companies(query)
        if not targets or not hasattr(self.database, "list_documents"):
            return None
        matches = []
        for document in self.database.list_documents(limit=10_000):
            haystack = " ".join(
                str(document.get(field) or "") for field in ("original_filename", "source_title")
            ).lower()
            if any(
                any(alias.lower() in haystack for alias in _COMPANY_ALIASES[target])
                for target in targets
            ):
                matches.append(str(document["original_filename"]))
        return list(dict.fromkeys(matches)) or None

    @staticmethod
    def _expand_query(query: str) -> str:
        """Append deterministic bilingual aliases without rewriting user intent."""
        additions: list[str] = []
        query_lower = query.lower()
        for trigger, aliases in _QUERY_EXPANSIONS.items():
            if trigger.lower() in query_lower:
                additions.extend(alias for alias in aliases if alias.lower() not in query_lower)
        return " ".join([query, *dict.fromkeys(additions)])

    @staticmethod
    def _named_companies(query: str) -> set[str]:
        query_lower = query.lower()
        return {
            company
            for company, aliases in _COMPANY_ALIASES.items()
            if any(alias.lower() in query_lower for alias in aliases)
        }

    @classmethod
    def _scope_to_named_companies(
        cls, query: str, results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Prefer only explicitly named companies when matching reports are available."""
        targets = cls._named_companies(query)
        if not targets:
            return results

        scoped = []
        for item in results:
            metadata = item.get("metadata") or {}
            haystack = " ".join(
                str(metadata.get(field) or "") for field in ("source", "publisher", "source_title")
            ).lower()
            if any(
                any(alias.lower() in haystack for alias in _COMPANY_ALIASES[target])
                for target in targets
            ):
                scoped.append(item)
        return scoped or results

    def retrieve_with_sources(
        self, query: str, top_k: int = RAGConfig.similarity_top_k
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        results = self.retrieve(query, top_k=top_k)
        text_results = [item for item in results if item.get("source_type") != "table"]
        table_results = [item for item in results if item.get("source_type") == "table"]
        return text_results, table_results

    @staticmethod
    def _route_query(query: str) -> str:
        normalized_query = query.lower()
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
            "产能",
            "研发",
            "出货",
            "同比",
            "环比",
            "CAPEX",
            "EBITDA",
            "revenue",
            "gross margin",
            "operating profit margin",
            "utilisation",
            "utilization",
            "capacity",
            "shipments",
            "research and development",
            "r&d",
        )
        concept_indicators = ("什么是", "定义", "概念", "原理", "技术", "制程", "工艺", "架构")
        if any(term.lower() in normalized_query for term in finance_indicators):
            return "table_first"
        if any(term.lower() in normalized_query for term in concept_indicators):
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
        if route == "table_first":
            dense_weight, lexical_weight = 0.4, 0.6
        else:
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
