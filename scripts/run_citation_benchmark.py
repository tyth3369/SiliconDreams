#!/usr/bin/env python3
"""Run the reviewed claim-to-source citation benchmark and enforce its gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation import evaluate_citations  # noqa: E402

DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "citation_golden.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--min-precision", type=float)
    parser.add_argument("--min-coverage", type=float)
    parser.add_argument("--min-validity", type=float)
    args = parser.parse_args()

    manifest = json.loads(args.fixture.read_text(encoding="utf-8"))
    thresholds = dict(manifest.get("thresholds") or {})
    required = {
        "citation_precision": (
            args.min_precision
            if args.min_precision is not None
            else float(thresholds.get("citation_precision", 0.95))
        ),
        "claim_coverage": (
            args.min_coverage
            if args.min_coverage is not None
            else float(thresholds.get("claim_coverage", 0.90))
        ),
        "marker_validity": (
            args.min_validity
            if args.min_validity is not None
            else float(thresholds.get("marker_validity", 1.0))
        ),
    }
    report = evaluate_citations(list(manifest.get("cases") or []))
    report.update(
        {
            "dataset": manifest.get("dataset", ""),
            "captured_on": manifest.get("captured_on", ""),
            "capture_model": manifest.get("capture_model", ""),
            "reviewed_on": manifest.get("reviewed_on", ""),
            "thresholds": required,
        }
    )
    report["passed"] = all(report[metric] >= threshold for metric, threshold in required.items())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
