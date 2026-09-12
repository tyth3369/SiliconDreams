"""Safe SQLite inspection, backup, verification, and restore helpers."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from src.migrations import SCHEMA_VERSION, validate_schema


class DatabaseAdminError(RuntimeError):
    """Raised when a database administration operation is unsafe or invalid."""


def inspect_database(path: str | Path) -> dict[str, Any]:
    """Inspect a database without migrating or otherwise mutating it."""
    database_path = Path(path).expanduser().resolve()
    if not database_path.is_file():
        raise DatabaseAdminError(f"Database does not exist: {database_path}")

    uri = f"file:{database_path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_issues = connection.execute("PRAGMA foreign_key_check").fetchall()
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        version = None
        history: list[dict[str, Any]] = []
        if "schema_meta" in tables:
            row = connection.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
            version = int(row[0]) if row else None
        if "schema_migrations" in tables:
            history = [
                {
                    "version": row[0],
                    "name": row[1],
                    "checksum": row[2],
                    "applied_at": row[3],
                    "baseline": bool(row[4]),
                }
                for row in connection.execute(
                    """
                    SELECT version, name, checksum, applied_at, baseline
                    FROM schema_migrations ORDER BY version
                    """
                ).fetchall()
            ]
    return {
        "path": str(database_path),
        "size_bytes": database_path.stat().st_size,
        "schema_version": version,
        "supported_schema_version": SCHEMA_VERSION,
        "integrity": integrity,
        "foreign_key_issues": len(foreign_key_issues),
        "tables": tables,
        "migrations": history,
    }


def verify_database(path: str | Path, *, require_current_schema: bool = True) -> dict[str, Any]:
    """Verify SQLite integrity, foreign keys, and optionally the full current schema."""
    status = inspect_database(path)
    if status["integrity"] != "ok":
        raise DatabaseAdminError(f"Integrity check failed: {status['integrity']}")
    if status["foreign_key_issues"]:
        raise DatabaseAdminError(f"Foreign-key check found {status['foreign_key_issues']} issue(s)")
    version = status["schema_version"]
    if version is None or not 1 <= version <= SCHEMA_VERSION:
        raise DatabaseAdminError(f"Unsupported schema version: {version}")
    if require_current_schema and version != SCHEMA_VERSION:
        raise DatabaseAdminError(f"Expected schema v{SCHEMA_VERSION}, found v{version}")
    database_path = Path(path).expanduser().resolve()
    uri = f"file:{database_path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        validate_schema(connection, version=version)
    return status


def backup_database(source: str | Path, destination: str | Path) -> Path:
    """Create a consistent backup of any supported schema and verify it."""
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if not source_path.is_file():
        raise DatabaseAdminError(f"Source database does not exist: {source_path}")
    if source_path == destination_path:
        raise DatabaseAdminError("Backup destination must differ from the source database")
    if destination_path.exists():
        raise DatabaseAdminError(f"Backup destination already exists: {destination_path}")
    verify_database(source_path, require_current_schema=False)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    source_uri = f"file:{source_path.as_posix()}?mode=ro"
    try:
        with (
            sqlite3.connect(source_uri, uri=True) as source_connection,
            sqlite3.connect(destination_path) as destination_connection,
        ):
            source_connection.backup(destination_connection)
        verify_database(destination_path, require_current_schema=False)
    except Exception:
        destination_path.unlink(missing_ok=True)
        raise
    return destination_path


def restore_database(
    backup: str | Path, destination: str | Path, *, overwrite: bool = False
) -> Path:
    """Verify and atomically restore a SQLite backup."""
    backup_path = Path(backup).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    verify_database(backup_path, require_current_schema=False)
    if backup_path == destination_path:
        raise DatabaseAdminError("Backup and restore destination must differ")
    if destination_path.exists() and not overwrite:
        raise DatabaseAdminError(
            f"Restore destination already exists: {destination_path}; pass --force to replace it"
        )
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination_path.name}.", suffix=".restore", dir=destination_path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with (
            sqlite3.connect(backup_path) as source_connection,
            sqlite3.connect(temporary_path) as destination_connection,
        ):
            source_connection.backup(destination_connection)
        verify_database(temporary_path, require_current_schema=False)
        os.replace(temporary_path, destination_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return destination_path
