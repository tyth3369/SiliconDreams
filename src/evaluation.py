"""Small, dependency-free retrieval evaluation utilities."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

INLINE_CITATION_PATTERN = re.compile(r"\[(\d+)\]")


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
    normalized_expected = re.sub(r"\s+", " ", str(contains)).strip().lower()
    normalized_text = re.sub(r"\s+", " ", str(result.get("text", ""))).strip().lower()
    if contains and normalized_expected not in normalized_text:
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


def citation_integrity(answer: str, citations: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure whether inline citation markers resolve to the supplied source list."""
    markers = [int(value) for value in INLINE_CITATION_PATTERN.findall(answer)]
    valid = [marker for marker in markers if 1 <= marker <= len(citations)]
    invalid = [marker for marker in markers if marker < 1 or marker > len(citations)]
    return {
        "markers": len(markers),
        "valid_markers": len(valid),
        "invalid_markers": invalid,
        "marker_validity": len(valid) / len(markers) if markers else 0.0,
        "cited_sources": len(set(valid)),
        "available_sources": len(citations),
    }


def evaluate_citations(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate manually annotated claim-to-source citation precision and coverage."""
    if not cases:
        return {
            "cases": 0,
            "citation_precision": 0.0,
            "claim_coverage": 0.0,
            "marker_validity": 0.0,
            "details": [],
        }

    total_markers = 0
    valid_markers = 0
    supported_markers = 0
    required_claims = 0
    covered_claims = 0
    details = []
    for case in cases:
        answer = str(case.get("answer", ""))
        citations = list(case.get("citations") or [])
        integrity = citation_integrity(answer, citations)
        case_supported = 0
        case_covered = 0
        case_required = 0
        annotated_marker_count = 0
        claim_details = []
        for claim in case.get("claims") or []:
            claim_text = str(claim.get("text", ""))
            present = bool(claim_text and claim_text in answer)
            markers = (
                [int(value) for value in INLINE_CITATION_PATTERN.findall(claim_text)]
                if present
                else []
            )
            supported_by = {int(value) for value in claim.get("supported_by") or []}
            supported = [marker for marker in markers if marker in supported_by]
            annotated_marker_count += len(markers)
            case_supported += len(supported)
            if claim.get("required", True):
                case_required += 1
                required_claims += 1
                if supported:
                    covered_claims += 1
                    case_covered += 1
            claim_details.append(
                {
                    "text": claim_text,
                    "present": present,
                    "markers": markers,
                    "supported_by": sorted(supported_by),
                    "supported": bool(supported),
                }
            )

        # Markers outside an annotated claim cannot be counted as grounded.
        case_total = integrity["markers"]
        total_markers += case_total
        valid_markers += integrity["valid_markers"]
        bounded_supported = min(case_supported, annotated_marker_count, case_total)
        supported_markers += bounded_supported
        details.append(
            {
                "id": case.get("id", ""),
                "citation_precision": bounded_supported / case_total if case_total else 0.0,
                "claim_coverage": case_covered / case_required if case_required else 0.0,
                "marker_validity": integrity["marker_validity"],
                "invalid_markers": integrity["invalid_markers"],
                "claims": claim_details,
            }
        )

    return {
        "cases": len(cases),
        "citation_precision": supported_markers / total_markers if total_markers else 0.0,
        "claim_coverage": covered_claims / required_claims if required_claims else 0.0,
        "marker_validity": valid_markers / total_markers if total_markers else 0.0,
        "details": details,
    }
