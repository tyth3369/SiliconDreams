#!/usr/bin/env python3
"""Measure deterministic local workbench routes without external APIs."""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from httpx import ASGITransport, AsyncClient  # noqa: E402

import server  # noqa: E402


async def measure(path: str, samples: int) -> dict:
    transport = ASGITransport(app=server.app)
    timings = []
    async with AsyncClient(transport=transport, base_url="http://benchmark") as client:
        await client.get(path)
        for _ in range(samples):
            started = time.perf_counter()
            response = await client.get(path)
            response.raise_for_status()
            timings.append((time.perf_counter() - started) * 1000)
    ordered = sorted(timings)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return {
        "path": path,
        "samples": samples,
        "median_ms": round(statistics.median(timings), 2),
        "p95_ms": round(p95, 2),
        "max_ms": round(max(timings), 2),
    }


async def main(samples: int) -> None:
    for path in ("/healthz", "/analytics?lang=en", "/watchlist?lang=en"):
        result = await measure(path, samples)
        print(
            f"{result['path']}: median={result['median_ms']}ms "
            f"p95={result['p95_ms']}ms max={result['max_ms']}ms "
            f"n={result['samples']}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(main(max(1, args.samples)))
