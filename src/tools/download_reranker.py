#!/usr/bin/env python3
"""Download and verify the pinned multilingual cross-encoder reranker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.model_artifacts import RERANKER_MANIFEST  # noqa: E402
from src.tools.model_download import download_model  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror", default="https://hf-mirror.com")
    args = parser.parse_args()
    download_model(RERANKER_MANIFEST, mirror=args.mirror)


if __name__ == "__main__":
    main()
