"""Ordered, transactional SQLite schema migrations."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


class SchemaMigrationError(RuntimeError):
    """Raised when a database cannot be migrated safely."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        payload = f"{self.version}\x1f{self.name}\x1f" + "\x1e".join(self.statements)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


V1_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS sources (
        id TEXT PRIMARY KEY,
        source_type TEXT NOT NULL CHECK (source_type IN ('official', 'web', 'document', 'term', 'dataset')),
        title TEXT NOT NULL,
        url TEXT,
        publisher TEXT,
        published_at TEXT,
        retrieved_at TEXT NOT NULL,
        trust_tier INTEGER NOT NULL DEFAULT 3 CHECK (trust_tier BETWEEN 1 AND 4),
        content_hash TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_url ON sources(url) WHERE url IS NOT NULL AND url != ''",
    """
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        original_filename TEXT NOT NULL,
        stored_path TEXT NOT NULL,
        sha256 TEXT NOT NULL UNIQUE,
        page_count INTEGER NOT NULL DEFAULT 0,
        report_period TEXT,
        parse_status TEXT NOT NULL DEFAULT 'pending',
        parse_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        page INTEGER NOT NULL CHECK (page >= 1),
        section TEXT NOT NULL DEFAULT '',
        chunk_type TEXT NOT NULL CHECK (chunk_type IN ('text', 'table')),
        text TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        vector_id TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        UNIQUE(document_id, content_hash)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chunks_document_page ON chunks(document_id, page)",
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        chunk_id UNINDEXED,
        text,
        section,
        tokenize='unicode61'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
        INSERT INTO chunks_fts(chunk_id, text, section) VALUES (new.id, new.text, new.section);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
        DELETE FROM chunks_fts WHERE chunk_id = old.id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
        DELETE FROM chunks_fts WHERE chunk_id = old.id;
        INSERT INTO chunks_fts(chunk_id, text, section) VALUES (new.id, new.text, new.section);
    END
    """,
    """
    CREATE TABLE IF NOT EXISTS facts (
        id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
        document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
        company TEXT NOT NULL,
        metric TEXT NOT NULL,
        period TEXT NOT NULL,
        value TEXT NOT NULL,
        unit TEXT NOT NULL,
        currency TEXT,
        page INTEGER,
        quote TEXT,
        confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        UNIQUE(company, metric, period, source_id, value, unit)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_facts_lookup ON facts(company, metric, period)",
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        language TEXT NOT NULL DEFAULT 'zh',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
        content TEXT NOT NULL,
        citations_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        job_type TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
        payload_json TEXT NOT NULL DEFAULT '{}',
        result_json TEXT NOT NULL DEFAULT '{}',
        error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
)

V2_STATEMENTS = (
    "ALTER TABLE conversations ADD COLUMN archived_at TEXT",
    """
    UPDATE conversations AS conversation
    SET title=substr(
        (
            SELECT content FROM messages
            WHERE conversation_id=conversation.id AND role='user'
            ORDER BY rowid LIMIT 1
        ),
        1, 48
    )
    WHERE title='' AND EXISTS (
        SELECT 1 FROM messages
        WHERE conversation_id=conversation.id AND role='user'
    )
    """,
)

V3_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS watchlist (
        company TEXT PRIMARY KEY,
        created_at TEXT NOT NULL
    )
    """,
)

V4_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS web_search_cache (
        query_key TEXT PRIMARY KEY,
        query TEXT NOT NULL,
        backend TEXT NOT NULL,
        results_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS web_snapshots (
        id TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        title TEXT NOT NULL,
        snippet TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        publisher TEXT,
        published_at TEXT,
        retrieved_at TEXT NOT NULL,
        UNIQUE(url, content_hash)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_web_snapshots_url ON web_snapshots(url, retrieved_at)",
)

V5_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        target_type TEXT,
        target_id TEXT,
        outcome TEXT NOT NULL CHECK (outcome IN ('success', 'denied', 'error')),
        client_hash TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit_events(action, created_at)",
    """
    CREATE TRIGGER IF NOT EXISTS audit_events_no_update
    BEFORE UPDATE ON audit_events BEGIN
        SELECT RAISE(ABORT, 'audit events are append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
    BEFORE DELETE ON audit_events BEGIN
        SELECT RAISE(ABORT, 'audit events are append-only');
    END
    """,
)

MIGRATIONS = (
    Migration(1, "evidence_conversations_jobs", V1_STATEMENTS),
    Migration(2, "conversation_archive_and_titles", V2_STATEMENTS),
    Migration(3, "company_watchlist", V3_STATEMENTS),
    Migration(4, "web_search_cache_and_snapshots", V4_STATEMENTS),
    Migration(5, "append_only_security_audit", V5_STATEMENTS),
)
SCHEMA_VERSION = MIGRATIONS[-1].version

REQUIRED_COLUMNS = {
    "sources": (1, {"id", "source_type", "title", "retrieved_at", "trust_tier"}),
    "documents": (1, {"id", "source_id", "sha256", "parse_status"}),
    "chunks": (1, {"id", "document_id", "source_id", "page", "text", "content_hash"}),
    "facts": (1, {"id", "source_id", "company", "metric", "period", "value", "unit"}),
    "conversations": (1, {"id", "title", "language", "created_at", "updated_at"}),
    "messages": (1, {"id", "conversation_id", "role", "content", "citations_json"}),
    "jobs": (1, {"id", "job_type", "status", "payload_json", "result_json"}),
    "watchlist": (3, {"company", "created_at"}),
    "web_search_cache": (4, {"query_key", "query", "backend", "results_json", "expires_at"}),
    "web_snapshots": (4, {"id", "url", "content_hash", "retrieved_at"}),
    "audit_events": (5, {"id", "request_id", "actor", "action", "outcome", "created_at"}),
}
REQUIRED_COLUMNS_BY_MIGRATION = {2: {"conversations": {"archived_at"}}}
REQUIRED_OBJECTS = {
    "index": {
        "idx_sources_url",
        "idx_chunks_document_page",
        "idx_facts_lookup",
        "idx_messages_conversation",
    },
    "trigger": {"chunks_ai", "chunks_ad", "chunks_au"},
}
REQUIRED_OBJECTS_BY_MIGRATION = {
    4: {
        "index": {
            "idx_web_snapshots_url",
        }
    },
    5: {
        "index": {
            "idx_audit_events_created",
            "idx_audit_events_action",
        },
        "trigger": {
            "audit_events_no_update",
            "audit_events_no_delete",
        },
    },
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()}


def _ensure_migration_metadata(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            baseline INTEGER NOT NULL DEFAULT 0 CHECK (baseline IN (0, 1))
        )
        """
    )


def _current_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError) as exc:
        raise SchemaMigrationError(f"Invalid schema version: {row[0]!r}") from exc


def _apply_migration(connection: sqlite3.Connection, migration: Migration) -> None:
    for statement in migration.statements:
        if (
            migration.version == 2
            and statement.lstrip().upper().startswith("ALTER TABLE")
            and "archived_at" in _columns(connection, "conversations")
        ):
            continue
        connection.execute(statement)


def _record_migration(
    connection: sqlite3.Connection, migration: Migration, *, baseline: bool
) -> None:
    connection.execute(
        """
        INSERT INTO schema_migrations(version, name, checksum, applied_at, baseline)
        VALUES (?, ?, ?, ?, ?)
        """,
        (migration.version, migration.name, migration.checksum, _utc_now(), int(baseline)),
    )


def validate_schema(connection: sqlite3.Connection, version: int = SCHEMA_VERSION) -> None:
    """Reject partially migrated or manually drifted databases."""
    errors: list[str] = []
    requirements = {
        table: set(columns)
        for table, (introduced, columns) in REQUIRED_COLUMNS.items()
        if introduced <= version
    }
    for migration_version, additions in REQUIRED_COLUMNS_BY_MIGRATION.items():
        if migration_version <= version:
            for table, columns in additions.items():
                requirements.setdefault(table, set()).update(columns)
    for table, required in requirements.items():
        if not _table_exists(connection, table):
            errors.append(f"missing table {table}")
            continue
        missing = required - _columns(connection, table)
        if missing:
            errors.append(f"table {table} missing columns: {', '.join(sorted(missing))}")
    if not _table_exists(connection, "chunks_fts"):
        errors.append("missing FTS table chunks_fts")
    object_requirements = {
        object_type: set(names) for object_type, names in REQUIRED_OBJECTS.items()
    }
    for migration_version, additions in REQUIRED_OBJECTS_BY_MIGRATION.items():
        if migration_version <= version:
            for object_type, names in additions.items():
                object_requirements.setdefault(object_type, set()).update(names)
    for object_type, required in object_requirements.items():
        present = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type=?", (object_type,)
            ).fetchall()
        }
        missing = required - present
        if missing:
            errors.append(f"missing {object_type}(s): {', '.join(sorted(missing))}")
    if errors:
        raise SchemaMigrationError("Schema validation failed: " + "; ".join(errors))


def migrate(connection: sqlite3.Connection) -> int:
    """Migrate a database atomically and return its resulting version."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        _ensure_migration_metadata(connection)
        current = _current_version(connection)
        if current > SCHEMA_VERSION:
            raise SchemaMigrationError(
                f"Database schema v{current} is newer than supported v{SCHEMA_VERSION}"
            )

        history = {
            row[0]: row
            for row in connection.execute(
                "SELECT version, name, checksum FROM schema_migrations"
            ).fetchall()
        }
        unknown_history = sorted(set(history) - {item.version for item in MIGRATIONS})
        if unknown_history:
            raise SchemaMigrationError(
                f"Unknown migration history version(s): {', '.join(map(str, unknown_history))}"
            )
        ahead = sorted(version for version in history if version > current)
        if ahead:
            raise SchemaMigrationError(
                f"Migration history is ahead of schema version: {', '.join(map(str, ahead))}"
            )
        for migration in MIGRATIONS:
            recorded = history.get(migration.version)
            if recorded and (recorded[1] != migration.name or recorded[2] != migration.checksum):
                raise SchemaMigrationError(
                    f"Migration v{migration.version} checksum mismatch; database history drifted"
                )
            if migration.version <= current:
                if not recorded:
                    _record_migration(connection, migration, baseline=True)
                continue

            _apply_migration(connection, migration)
            _record_migration(connection, migration, baseline=False)
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', ?)",
                (str(migration.version),),
            )
            current = migration.version

        validate_schema(connection)
        connection.commit()
        return current
    except Exception:
        connection.rollback()
        raise
