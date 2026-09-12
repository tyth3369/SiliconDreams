import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from src.database_admin import (
    DatabaseAdminError,
    backup_database,
    inspect_database,
    restore_database,
    verify_database,
)
from src.migrations import SCHEMA_VERSION
from src.storage import Database


def _populated_database(path: Path) -> tuple[Database, str]:
    database = Database(path)
    conversation_id = database.create_conversation(title="Backup test")
    database.add_message(conversation_id, "user", "Preserve this")
    return database, conversation_id


def _downgrade_fixture_to_v4(database: Database) -> None:
    with database.connect() as connection:
        connection.execute("UPDATE schema_meta SET value='4' WHERE key='version'")
        connection.execute("DELETE FROM schema_migrations WHERE version IN (5, 6)")
        for name in (
            "idx_audit_events_created",
            "idx_audit_events_action",
            "idx_ai_runs_created",
            "idx_ai_runs_status",
            "idx_ai_tool_events_run",
            "idx_ai_tool_events_tool",
        ):
            connection.execute(f"DROP INDEX {name}")
        connection.execute("DROP TRIGGER audit_events_no_update")
        connection.execute("DROP TRIGGER audit_events_no_delete")
        connection.execute("DROP TABLE ai_tool_events")
        connection.execute("DROP TABLE ai_runs")
        connection.execute("DROP TABLE audit_events")


def test_inspect_and_verify_current_database(tmp_path):
    database, _ = _populated_database(tmp_path / "source.db")
    status = inspect_database(database.path)
    assert status["schema_version"] == SCHEMA_VERSION
    assert status["integrity"] == "ok"
    assert status["foreign_key_issues"] == 0
    assert [item["version"] for item in status["migrations"]] == list(range(1, SCHEMA_VERSION + 1))
    assert verify_database(database.path)["path"] == str(database.path.resolve())


def test_online_backup_and_restore_preserve_data(tmp_path):
    source, conversation_id = _populated_database(tmp_path / "source.db")
    backup_path = backup_database(source.path, tmp_path / "backups" / "snapshot.db")
    restored_path = restore_database(backup_path, tmp_path / "restored.db")
    restored = Database(restored_path)
    assert restored.list_messages(conversation_id)[0]["content"] == "Preserve this"


def test_backup_refuses_overwrite_and_cleans_invalid_destination(tmp_path):
    source, _ = _populated_database(tmp_path / "source.db")
    destination = tmp_path / "snapshot.db"
    destination.write_text("existing", encoding="utf-8")
    with pytest.raises(DatabaseAdminError, match="already exists"):
        backup_database(source.path, destination)
    assert destination.read_text(encoding="utf-8") == "existing"


def test_restore_requires_force_for_existing_destination(tmp_path):
    source, _ = _populated_database(tmp_path / "source.db")
    backup_path = backup_database(source.path, tmp_path / "snapshot.db")
    destination = tmp_path / "destination.db"
    destination.write_text("do not replace", encoding="utf-8")
    with pytest.raises(DatabaseAdminError, match="pass --force"):
        restore_database(backup_path, destination)
    assert destination.read_text(encoding="utf-8") == "do not replace"


def test_restore_force_replaces_existing_database_atomically(tmp_path):
    source, conversation_id = _populated_database(tmp_path / "source.db")
    backup_path = backup_database(source.path, tmp_path / "snapshot.db")
    destination, other_conversation_id = _populated_database(tmp_path / "destination.db")

    restore_database(backup_path, destination.path, overwrite=True)
    restored = Database(destination.path)
    assert restored.list_messages(conversation_id)[0]["content"] == "Preserve this"
    assert restored.list_messages(other_conversation_id) == []


def test_invalid_backup_is_rejected_before_destination_changes(tmp_path):
    invalid = tmp_path / "invalid.db"
    invalid.write_text("not sqlite", encoding="utf-8")
    destination = tmp_path / "destination.db"
    destination.write_text("unchanged", encoding="utf-8")
    with pytest.raises(sqlite3.DatabaseError):
        restore_database(invalid, destination, overwrite=True)
    assert destination.read_text(encoding="utf-8") == "unchanged"


def test_restore_accepts_verified_older_schema_and_migrates_on_open(tmp_path):
    source, conversation_id = _populated_database(tmp_path / "source.db")
    _downgrade_fixture_to_v4(source)
    backup_path = tmp_path / "v4.db"
    with source.connect() as source_connection, sqlite3.connect(backup_path) as backup_connection:
        source_connection.backup(backup_connection)

    restored_path = restore_database(backup_path, tmp_path / "restored.db")
    migrated = Database(restored_path)
    assert migrated.list_messages(conversation_id)[0]["content"] == "Preserve this"
    assert inspect_database(restored_path)["schema_version"] == SCHEMA_VERSION


def test_online_backup_accepts_supported_older_schema(tmp_path):
    source, _ = _populated_database(tmp_path / "source.db")
    _downgrade_fixture_to_v4(source)

    backup_path = backup_database(source.path, tmp_path / "v4-backup.db")
    assert inspect_database(backup_path)["schema_version"] == 4


def test_database_admin_cli_runs_from_project_root(tmp_path):
    database, _ = _populated_database(tmp_path / "cli.db")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/manage_database.py",
            "--database",
            str(database.path),
            "status",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["integrity"] == "ok"


def test_database_admin_cli_reads_audit_events(tmp_path):
    database, _ = _populated_database(tmp_path / "audit-cli.db")
    database.add_audit_event(
        request_id="req-cli",
        actor="researcher",
        action="POST /chat",
        outcome="success",
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/manage_database.py",
            "--database",
            str(database.path),
            "audit",
            "--limit",
            "1",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["events"][0]["request_id"] == "req-cli"


def test_database_admin_cli_reports_operational_metrics(tmp_path):
    database, _ = _populated_database(tmp_path / "metrics-cli.db")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/manage_database.py",
            "--database",
            str(database.path),
            "metrics",
            "--hours",
            "12",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["window_hours"] == 12
    assert payload["runs"] == 0
