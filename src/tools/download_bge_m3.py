#!/usr/bin/env python3
"""
Download BGE-M3 model using macOS system curl (SecureTransport) + hf-mirror.com.
No Python SSL needed — bypasses LibreSSL entirely.

Usage:
    python src/tools/download_bge_m3.py
    python src/tools/download_bge_m3.py --mirror https://hf-mirror.com
"""

import argparse
import os
import subprocess
import sys

MODEL_ID = "BAAI/bge-m3"
CACHE_DIR = os.path.expanduser("~/.cache/silicondreams/models/bge-m3")

# Files needed for SentenceTransformer to load BGE-M3
FILES = [
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "sentence_bert_config.json",
    "modules.json",
    "1_Pooling/config.json",
    "pytorch_model.bin",  # ~2.27 GB
    "special_tokens_map.json",
    "sentencepiece.bpe.model",
]

MAX_RETRIES = 5


def download_file(url: str, filepath: str, label: str) -> bool:
    """Download a single file with curl + retry + resume. Returns True on success."""
    for attempt in range(MAX_RETRIES):
        print(f"  ↓ {label}...", end=" ", flush=True)
        try:
            args = [
                "curl",
                "-fLsS",  # fail on HTTP errors, follow redirects, silent but show errors
                "-o",
                filepath,
                "--retry",
                "3",
                "--retry-delay",
                "5",
            ]
            # Resume partial download if file exists
            if os.path.exists(filepath):
                args.extend(["-C", "-"])

            args.append(url)
            subprocess.run(args, check=True, timeout=1200, capture_output=True)

            size_mb = os.path.getsize(filepath) / 1e6
            print(f"Done ({size_mb:.1f} MB)")
            return True

        except subprocess.TimeoutExpired:
            print(f"TIMEOUT (attempt {attempt + 1}/{MAX_RETRIES})")
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode("utf-8", errors="replace")[:200] if e.stderr else str(e)
            print(f"FAILED (attempt {attempt + 1}/{MAX_RETRIES}): {err}")
        except Exception as e:
            print(f"FAILED (attempt {attempt + 1}/{MAX_RETRIES}): {e}")

        if attempt < MAX_RETRIES - 1:
            import time

            wait = 5 * (2**attempt)
            print(f"    Retrying in {wait}s...")
            time.sleep(wait)

    return False


def main():
    parser = argparse.ArgumentParser(description="Download BGE-M3 model")
    parser.add_argument(
        "--mirror", default="https://hf-mirror.com", help="HuggingFace mirror base URL"
    )
    args = parser.parse_args()

    mirror = args.mirror.rstrip("/")
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(os.path.join(CACHE_DIR, "1_Pooling"), exist_ok=True)

    print(f"📥 Downloading BGE-M3 from {mirror}")
    print(f"   Target: {CACHE_DIR}\n")

    success = True
    for filename in FILES:
        url = f"{mirror}/{MODEL_ID}/resolve/main/{filename}"
        filepath = os.path.join(CACHE_DIR, filename)

        if os.path.exists(filepath):
            size_mb = os.path.getsize(filepath) / 1e6
            print(f"  ✓ {filename} ({size_mb:.1f} MB) — already cached, skipping")
            continue

        if not download_file(url, filepath, filename):
            print(f"\n❌ Failed to download: {filename}")
            success = False
            break

    if not success:
        print("\n💡 Re-run this script to resume. Already-cached files will be skipped.")
        sys.exit(1)

    total = 0
    for f in os.listdir(CACHE_DIR):
        fp = os.path.join(CACHE_DIR, f)
        if os.path.isfile(fp):
            total += os.path.getsize(fp)

    print(f"\n✅ BGE-M3 model ready at {CACHE_DIR}")
    print(f"   Total size: {total / 1e9:.1f} GB")


if __name__ == "__main__":
    main()
