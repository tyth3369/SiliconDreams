"""Small, dependency-free retrieval evaluation utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class RetrievalBackend(Protocol):
    def retrieve(self, query: str, top_k: int = 5, rerank: bool = True) -> list[dict[str, Any]]: ...


def _matches(result: dict[str, Any], expected: dict[str, Any]) -> bool:
    metadata = result.get("metadata") or {}
    if expected.get("id") and str(result.get("id")) != str(expected["id"]):
        return False
    if expected.get("source") and str(metadata.get("source")) != str(expected["source"]):
        return False
    if expected.get("page") is not None and int(metadata.get("page") or 0) != int(expected["page"]):
        return False
    contains = expected.get("contains")
    if contains and str(contains).lower() not in str(result.get("text", "")).lower():
        return False
    return any(key in expected for key in ("id", "source", "page", "contains"))


def evaluate_retrieval(
    backend: RetrievalBackend,
    cases: list[dict[str, Any]],
    *,
    top_k: int = 5,
    rerank: bool = True,
) -> dict[str, Any]:
    """Compute Recall@K and MRR from source/page/content expectations."""
    if not cases:
        return {"cases": 0, "recall_at_k": 0.0, "mrr": 0.0, "details": []}

    recalls = []
    reciprocal_ranks = []
    details = []
    for case in cases:
        results = backend.retrieve(str(case["query"]), top_k=top_k, rerank=rerank)
        expected = list(case.get("expected") or [])
        hit_ranks = []
        matched_expectations = 0
        for target in expected:
            ranks = [rank for rank, result in enumerate(results, 1) if _matches(result, target)]
            if ranks:
                matched_expectations += 1
                hit_ranks.append(min(ranks))
        recall = matched_expectations / len(expected) if expected else 0.0
        reciprocal_rank = 1.0 / min(hit_ranks) if hit_ranks else 0.0
        recalls.append(recall)
        reciprocal_ranks.append(reciprocal_rank)
        details.append(
            {
                "query": case["query"],
                "recall_at_k": recall,
                "reciprocal_rank": reciprocal_rank,
                "returned": len(results),
            }
        )
    return {
        "cases": len(cases),
        "top_k": top_k,
        "recall_at_k": sum(recalls) / len(recalls),
        "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks),
        "details": details,
    }


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("evaluation file must contain a 'cases' list")
    return cases
