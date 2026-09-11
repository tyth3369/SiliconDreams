#!/usr/bin/env python3
"""Download the multilingual cross-encoder using system curl with resume support."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

MODEL_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
LOCAL_PATH = Path.home() / ".cache" / "silicondreams" / "models" / "mmarco-reranker"

FILES = (
    "config.json",
    "model.safetensors",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    command = [
        "curl",
        "-fL",
        "--retry",
        "5",
        "--retry-all-errors",
        "--retry-delay",
        "3",
        "-C",
        "-",
        "-o",
        str(partial),
        url,
    ]
    subprocess.run(command, check=True, timeout=1800)
    partial.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mirror", default="https://hf-mirror.com")
    args = parser.parse_args()
    base = f"{args.mirror.rstrip('/')}/{MODEL_NAME}/resolve/main"
    destination = LOCAL_PATH

    for filename in FILES:
        target = destination / filename
        if target.exists() and target.stat().st_size > 0:
            print(f"skip {filename} ({target.stat().st_size / 1_000_000:.1f} MB)")
            continue
        print(f"download {filename}")
        download_file(f"{base}/{filename}", target)
    print(f"ready: {destination}")


if __name__ == "__main__":
    main()
