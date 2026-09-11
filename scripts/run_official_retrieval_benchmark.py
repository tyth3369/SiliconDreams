#!/usr/bin/env python3
"""Download, index and evaluate the reviewed official annual-report benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from curl_cffi import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chunker import chunk_document  # noqa: E402
from src.evaluation import evaluate_retrieval, load_cases  # noqa: E402
from src.pdf_parser import parse_pdf  # noqa: E402
from src.retriever import Retriever  # noqa: E402
from src.storage import Database  # noqa: E402
from src.vector_store import VectorStore  # noqa: E402

DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "retrieval_golden.json"
DEFAULT_WORKSPACE = ROOT / "tmp" / "official-retrieval-benchmark"
DEFAULT_MIN_RECALL = 0.90
DEFAULT_MIN_MRR = 0.70


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("documents"), list) or not isinstance(payload.get("cases"), list):
        raise ValueError("benchmark fixture requires documents and cases lists")
    return payload


def _download(document: dict[str, Any], directory: Path) -> Path:
    target = directory / document["source"]
    expected_hash = document["sha256"]
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected_hash:
        return target
    response = requests.get(document["url"], impersonate="chrome", timeout=180)
    response.raise_for_status()
    content = bytes(response.content)
    if not content.startswith(b"%PDF-"):
        raise RuntimeError(f"official source did not return a PDF: {document['url']}")
    actual_hash = hashlib.sha256(content).hexdigest()
    if actual_hash != expected_hash:
        raise RuntimeError(
            f"official PDF hash changed for {document['source']}: {actual_hash}; "
            "review the new document before updating the benchmark"
        )
    target.write_bytes(content)
    return target


def _index_document(
    document: dict[str, Any], path: Path, database: Database, vector_store: VectorStore
) -> None:
    content_hash = document["sha256"]
    existing = database.get_document_by_sha256(content_hash)
    if existing and existing["parse_status"] == "ready":
        return
    source_id = database.upsert_source(
        source_type="official",
        title=document["source"],
        url=document["url"],
        publisher=document["publisher"],
        published_at="2026-04-08" if document["publisher"] == "SMIC" else "2026-03-12",
        trust_tier=1,
        content_hash=content_hash,
        metadata={"benchmark": True, "reviewed_on": "2026-09-11"},
    )
    document_id = database.upsert_document(
        source_id=source_id,
        original_filename=document["source"],
        stored_path=str(path),
        sha256=content_hash,
        page_count=document["pages"],
        report_period="FY2025",
        parse_status="parsing",
    )
    parsed = parse_pdf(path, original_filename=document["source"])
    chunks = chunk_document(parsed)
    for chunk in chunks:
        chunk_id = database.add_chunk(
            document_id=document_id,
            source_id=source_id,
            page=chunk.page,
            chunk_type=chunk.chunk_type,
            text=chunk.text,
            section=chunk.section,
            metadata=chunk.metadata,
        )
        chunk.chunk_id = chunk_id
        chunk.metadata.update(
            {"document_id": document_id, "source_id": source_id, "vector_id": chunk_id}
        )
    existing_text = set(vector_store.text_collection.get(include=[])["ids"])
    existing_tables = set(vector_store.table_collection.get(include=[])["ids"])
    pending = [
        chunk
        for chunk in chunks
        if chunk.chunk_id not in (existing_tables if chunk.chunk_type == "table" else existing_text)
    ]
    vector_store.add_chunks(pending)
    database.set_document_status(document_id, "ready", page_count=parsed.total_pages)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--min-recall", type=float, default=DEFAULT_MIN_RECALL)
    parser.add_argument("--min-mrr", type=float, default=DEFAULT_MIN_MRR)
    args = parser.parse_args()

    manifest = _load_manifest(args.fixture)
    documents_dir = args.workspace / "documents"
    documents_dir.mkdir(parents=True, exist_ok=True)
    database = Database(args.workspace / "benchmark.db")
    vector_store = VectorStore(args.workspace / "chroma")
    for document in manifest["documents"]:
        path = _download(document, documents_dir)
        _index_document(document, path, database, vector_store)

    report = evaluate_retrieval(
        Retriever(vector_store=vector_store, database=database),
        load_cases(args.fixture),
        top_k=args.top_k,
        rerank=not args.no_rerank,
    )
    report["dataset"] = manifest["dataset"]
    report["reviewed_on"] = manifest["reviewed_on"]
    report["thresholds"] = {"recall_at_k": args.min_recall, "mrr": args.min_mrr}
    report["passed"] = report["recall_at_k"] >= args.min_recall and report["mrr"] >= args.min_mrr
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
