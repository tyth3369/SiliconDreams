#!/usr/bin/env python3
"""Verify a public SiliconDreams deployment without sending credentials."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.deployment_verifier import verify_deployment  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://sillycon.xyz")
    parser.add_argument("--alias-url", default="", help="Optional www/alias URL to verify")
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-ip", default="", help="Expected ECS public IP address")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = verify_deployment(
            args.base_url,
            args.expected_version,
            expected_ip=args.expected_ip,
            alias_url=args.alias_url,
            timeout=args.timeout,
        )
    except ValueError as exc:
        print(f"Invalid configuration: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(report.to_json())
    else:
        print(f"SiliconDreams deployment verification: {report.base_url}")
        for check in report.checks:
            marker = "PASS" if check.passed else "FAIL"
            print(f"[{marker}] {check.name}: {check.detail}")
        print("PASS" if report.passed else "FAIL")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
