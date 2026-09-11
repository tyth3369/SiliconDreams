#!/usr/bin/env python3
"""Evaluate the current local PDF index against a human-reviewed golden set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation import evaluate_retrieval, load_cases  # noqa: E402
from src.retriever import Retriever  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", help="JSON file containing query/evidence expectations")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--no-rerank", action="store_true")
    args = parser.parse_args()
    report = evaluate_retrieval(
        Retriever(),
        load_cases(args.cases),
        top_k=args.top_k,
        rerank=not args.no_rerank,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
