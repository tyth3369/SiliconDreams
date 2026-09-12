#!/usr/bin/env python3
"""Print and enforce terminology graph closure invariants."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.knowledge_graph import get_knowledge_graph  # noqa: E402


def main() -> int:
    report = get_knowledge_graph().audit()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["missing_endpoints"] or report["missing_inverse_edges"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
