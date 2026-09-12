#!/usr/bin/env python3
"""Inspect, verify, back up, or restore the SiliconDreams SQLite database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DATABASE_FILE  # noqa: E402
from src.database_admin import (  # noqa: E402
    backup_database,
    inspect_database,
    restore_database,
    verify_database,
)
from src.storage import Database  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DATABASE_FILE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show schema, migration, and integrity status")
    subparsers.add_parser("verify", help="Verify integrity and the current schema")
    audit = subparsers.add_parser("audit", help="Read recent append-only audit events")
    audit.add_argument("--limit", type=int, default=100)
    metrics = subparsers.add_parser(
        "metrics", help="Summarize privacy-safe AI cost, latency, errors, and source coverage"
    )
    metrics.add_argument("--hours", type=int, default=24)

    backup = subparsers.add_parser("backup", help="Create and verify an online SQLite backup")
    backup.add_argument("destination", type=Path)

    restore = subparsers.add_parser("restore", help="Verify and atomically restore a backup")
    restore.add_argument("source", type=Path)
    restore.add_argument(
        "--force", action="store_true", help="Replace an existing destination database"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "status":
        result = inspect_database(args.database)
    elif args.command == "verify":
        result = verify_database(args.database)
    elif args.command == "backup":
        result = {"backup": str(backup_database(args.database, args.destination))}
    elif args.command == "audit":
        result = {"events": Database(args.database).list_audit_events(limit=args.limit)}
    elif args.command == "metrics":
        result = Database(args.database).observability_summary(hours=args.hours)
    else:
        result = {
            "restored": str(
                restore_database(args.source, args.database, overwrite=bool(args.force))
            )
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
