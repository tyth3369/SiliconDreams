import hashlib
import sqlite3
from pathlib import Path

import pytest

from src.migrations import MIGRATIONS, SCHEMA_VERSION, SchemaMigrationError
from src.storage import Database, stable_id


@pytest.fixture
def database(tmp_path: Path) -> Database:
    return Database(tmp_path / "silicondreams-test.db")


def test_schema_initializes(database):
    assert database.count("sources") == 0
    with database.connect() as connection:
        version = connection.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()["value"]
        history = connection.execute(
            "SELECT version, name, baseline FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert version == str(SCHEMA_VERSION)
    assert [(row["version"], row["name"], row["baseline"]) for row in history] == [
        (migration.version, migration.name, 0) for migration in MIGRATIONS
    ]


def test_stable_id_is_deterministic():
    assert stable_id("src", "official", "url") == stable_id("src", "official", "url")


def test_source_upsert_is_idempotent(database):
    first = database.upsert_source(
        source_type="official",
        title="TSMC results",
        url="https://example.com/results",
        trust_tier=1,
    )
    second = database.upsert_source(
        source_type="official",
        title="TSMC results updated",
        url="https://example.com/results",
        trust_tier=1,
    )
    assert first == second
    assert database.count("sources") == 1


def _document(database):
    source_id = database.upsert_source(source_type="document", title="Annual report")
    digest = hashlib.sha256(b"pdf").hexdigest()
    document_id = database.upsert_document(
        source_id=source_id,
        original_filename="tsmc-2025.pdf",
        stored_path="/tmp/tsmc-2025.pdf",
        sha256=digest,
        page_count=100,
        report_period="FY2025",
        parse_status="ready",
    )
    return source_id, document_id


def test_document_upsert_is_idempotent(database):
    _document(database)
    _document(database)
    assert database.count("documents") == 1


def test_chunk_insert_populates_fts(database):
    source_id, document_id = _document(database)
    database.add_chunk(
        document_id=document_id,
        source_id=source_id,
        page=42,
        chunk_type="text",
        text="gross margin reached a record high",
        section="Results",
    )
    results = database.search_chunks_lexical("gross margin")
    assert results[0]["page"] == 42


def test_bm25_search_supports_chinese_without_spaces(database):
    source_id, document_id = _document(database)
    database.add_chunk(
        document_id=document_id,
        source_id=source_id,
        page=8,
        chunk_type="text",
        text="台积电先进制程推动毛利率持续改善",
        section="经营回顾",
    )
    database.add_chunk(
        document_id=document_id,
        source_id=source_id,
        page=9,
        chunk_type="text",
        text="成熟制程产能利用率保持稳定",
        section="产能",
    )
    results = database.search_chunks_bm25("台积电毛利率")
    assert results[0]["page"] == 8
    assert results[0]["bm25_score"] > 0


def test_chunk_insert_is_idempotent(database):
    source_id, document_id = _document(database)
    kwargs = {
        "document_id": document_id,
        "source_id": source_id,
        "page": 1,
        "chunk_type": "text",
        "text": "same content",
    }
    assert database.add_chunk(**kwargs) == database.add_chunk(**kwargs)
    assert database.count("chunks") == 1


def test_fact_round_trip_includes_provenance(database):
    source_id = database.upsert_source(
        source_type="official",
        title="TSMC Q4 Results",
        url="https://example.com/q4",
        publisher="TSMC",
        trust_tier=1,
    )
    database.upsert_fact(
        source_id=source_id,
        company="TSMC",
        metric="revenue",
        period="2025-Q4",
        value="33.73",
        unit="billion",
        currency="USD",
        page=1,
        quote="Fourth quarter revenue was US$33.73 billion.",
    )
    fact = database.find_facts("TSMC", metric="revenue", period="2025-Q4")[0]
    assert fact["value"] == "33.73"
    assert fact["source_title"] == "TSMC Q4 Results"
    assert fact["source_url"] == "https://example.com/q4"
    assert fact["trust_tier"] == 1


def test_fact_upsert_is_idempotent(database):
    source_id = database.upsert_source(source_type="dataset", title="Dataset")
    kwargs = {
        "source_id": source_id,
        "company": "TSMC",
        "metric": "gross_margin",
        "period": "FY2025",
        "value": 59.9,
        "unit": "percent",
    }
    assert database.upsert_fact(**kwargs) == database.upsert_fact(**kwargs)
    assert database.count("facts") == 1


def test_fact_conflicts_require_same_scope_and_distinct_normalized_values(database):
    first = database.upsert_source(
        source_type="official",
        title="Official Q4",
        url="https://example.com/official",
        trust_tier=1,
    )
    second = database.upsert_source(
        source_type="web", title="News Q4", url="https://example.com/news", trust_tier=2
    )
    for source_id, value in ((first, "33.10"), (second, "33.1")):
        database.upsert_fact(
            source_id=source_id,
            company="TSMC",
            metric="revenue",
            period="2025 Q4",
            value=value,
            unit="billion",
            currency="USD",
        )
    assert database.find_fact_conflicts(company="TSMC") == []

    database.upsert_fact(
        source_id=second,
        company="TSMC",
        metric="revenue",
        period="2025 Q4",
        value="34.0",
        unit="billion",
        currency="USD",
    )
    conflicts = database.find_fact_conflicts(company="TSMC", period="2025 Q4")
    assert len(conflicts) == 1
    assert conflicts[0]["metric"] == "revenue"
    assert {fact["source_title"] for fact in conflicts[0]["facts"]} == {
        "Official Q4",
        "News Q4",
    }


def test_conversation_messages_persist(database):
    conversation_id = database.create_conversation(language="zh", title="TSMC")
    database.add_message(conversation_id, "user", "台积电毛利率？")
    database.add_message(
        conversation_id,
        "assistant",
        "59.9% [1]",
        citations=[{"source_id": "src_1"}],
    )
    messages = database.list_messages(conversation_id)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["citations"] == [{"source_id": "src_1"}]
    assert database.list_conversations()[0]["title"] == "TSMC"


def test_first_user_message_sets_default_conversation_title(database):
    conversation_id = database.create_conversation(language="zh")
    database.add_message(conversation_id, "user", "  台积电   毛利率趋势？  ")
    assert database.list_conversations()[0]["title"] == "台积电 毛利率趋势？"


def test_conversations_can_be_renamed_and_archived(database):
    first = database.create_conversation(language="zh")
    second = database.create_conversation(language="en", title="Second")
    assert database.rename_conversation(first, "  TSMC   research  ") is True
    assert {item["title"] for item in database.list_conversations()} == {
        "TSMC research",
        "Second",
    }

    assert database.archive_conversation(first) is True
    assert database.conversation_exists(first) is False
    assert [item["id"] for item in database.list_conversations()] == [second]
    assert {item["id"] for item in database.list_conversations(include_archived=True)} == {
        first,
        second,
    }
    assert database.restore_conversation(first) is True
    assert database.conversation_exists(first) is True


def test_schema_v1_database_migrates_archived_at_column(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'zh',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
    migrated = Database(path)
    with migrated.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(conversations)")}
        version = connection.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()["value"]
    assert "archived_at" in columns
    assert version == str(SCHEMA_VERSION)


def test_existing_v4_database_is_baselined_without_losing_data(tmp_path):
    path = tmp_path / "existing-v4.db"
    initial = Database(path)
    conversation_id = initial.create_conversation(title="Preserve me")
    initial.add_message(conversation_id, "user", "Keep this message")
    with initial.connect() as connection:
        connection.execute("DROP TABLE schema_migrations")

    reopened = Database(path)
    assert reopened.list_messages(conversation_id)[0]["content"] == "Keep this message"
    with reopened.connect() as connection:
        history = connection.execute(
            "SELECT version, baseline FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert [(row["version"], row["baseline"]) for row in history] == [
        (migration.version, 1) for migration in MIGRATIONS
    ]


def test_newer_database_version_is_rejected_without_rewriting_version(tmp_path):
    path = tmp_path / "future.db"
    database = Database(path)
    with database.connect() as connection:
        connection.execute(
            "UPDATE schema_meta SET value=? WHERE key='version'",
            (str(SCHEMA_VERSION + 1),),
        )

    with pytest.raises(SchemaMigrationError, match="newer than supported"):
        Database(path)
    with sqlite3.connect(path) as connection:
        version = connection.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()[0]
    assert version == str(SCHEMA_VERSION + 1)


def test_migration_checksum_drift_is_rejected(tmp_path):
    path = tmp_path / "drift.db"
    database = Database(path)
    with database.connect() as connection:
        connection.execute("UPDATE schema_migrations SET checksum='tampered' WHERE version=1")

    with pytest.raises(SchemaMigrationError, match="checksum mismatch"):
        Database(path)


def test_schema_drift_is_rejected_even_when_version_claims_current(tmp_path):
    path = tmp_path / "incomplete.db"
    database = Database(path)
    with database.connect() as connection:
        connection.execute("DROP TABLE watchlist")

    with pytest.raises(SchemaMigrationError, match="missing table watchlist"):
        Database(path)


def test_migration_history_ahead_of_schema_version_is_rejected(tmp_path):
    path = tmp_path / "history-ahead.db"
    database = Database(path)
    with database.connect() as connection:
        connection.execute("UPDATE schema_meta SET value='3' WHERE key='version'")

    with pytest.raises(SchemaMigrationError, match="history is ahead"):
        Database(path)


def test_missing_required_trigger_is_detected(tmp_path):
    path = tmp_path / "missing-trigger.db"
    database = Database(path)
    with database.connect() as connection:
        connection.execute("DROP TRIGGER chunks_ai")

    with pytest.raises(SchemaMigrationError, match="missing trigger"):
        Database(path)


def test_watchlist_is_persistent_and_idempotent(database):
    assert database.list_watchlist() == []
    assert database.set_watchlist("台积电", watched=True) is True
    assert database.set_watchlist("台积电", watched=True) is True
    assert database.set_watchlist("中芯国际", watched=True) is True
    assert database.list_watchlist() == ["台积电", "中芯国际"]
    assert database.count("watchlist") == 2
    assert database.set_watchlist("台积电", watched=False) is True
    assert database.list_watchlist() == ["中芯国际"]
    assert database.set_watchlist("  ", watched=True) is False


def test_web_search_cache_expiry_and_content_addressed_snapshots(database):
    results = [
        {
            "title": "TSMC release",
            "url": "https://investor.tsmc.com/update",
            "snippet": "Official update",
            "publisher": "TSMC",
            "published_at": "2026-09-01",
        }
    ]
    database.cache_web_search(
        query_key="query-key",
        query="TSMC latest",
        backend="Tavily",
        results=results,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    cached = database.get_cached_web_search("query-key", now="2026-09-12T00:00:00+00:00")
    assert cached["results"] == results
    assert database.get_cached_web_search("query-key", now="2100-01-01T00:00:00+00:00") is None
    assert database.count("web_snapshots") == 1
    database.cache_web_search(
        query_key="query-key",
        query="TSMC latest",
        backend="Tavily",
        results=results,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    assert database.count("web_snapshots") == 1
    assert database.list_web_snapshots()[0]["content_hash"]


def test_message_limit_returns_most_recent_items_in_conversation_order(database):
    conversation_id = database.create_conversation()
    for index in range(5):
        database.add_message(conversation_id, "user", f"message-{index}")

    assert [item["content"] for item in database.list_messages(conversation_id, limit=3)] == [
        "message-2",
        "message-3",
        "message-4",
    ]


def test_foreign_keys_are_enforced(database):
    with pytest.raises(sqlite3.IntegrityError):
        database.add_message("missing", "user", "orphan")


def test_count_rejects_arbitrary_table_name(database):
    with pytest.raises(ValueError):
        database.count("sqlite_master; DROP TABLE sources")


def test_persistent_job_lifecycle_and_idempotency(database):
    payload = {"document_id": "doc_1", "stored_path": "/tmp/report.pdf"}
    job_id = database.enqueue_job("pdf_ingest", payload, dedupe_key="doc_1")
    assert database.enqueue_job("pdf_ingest", payload, dedupe_key="doc_1") == job_id
    assert database.count("jobs") == 1

    claimed = database.claim_next_job("pdf_ingest")
    assert claimed["id"] == job_id
    assert claimed["status"] == "running"
    assert database.claim_next_job("pdf_ingest") is None

    database.update_job_progress(job_id, stage="indexing", progress=73)
    assert database.get_job(job_id)["result"] == {"stage": "indexing", "progress": 73}

    database.finish_job(
        job_id,
        result={"stage": "completed", "progress": 100, "chunk_count": 12},
    )
    finished = database.get_job(job_id)
    assert finished["status"] == "succeeded"
    assert finished["result"]["chunk_count"] == 12


def test_running_jobs_are_requeued_after_restart(database):
    job_id = database.enqueue_job(
        "pdf_ingest", {"document_id": "doc_restart"}, dedupe_key="doc_restart"
    )
    assert database.claim_next_job("pdf_ingest")["status"] == "running"
    assert database.requeue_running_jobs("pdf_ingest") == 1
    recovered = database.get_job(job_id)
    assert recovered["status"] == "pending"
    assert recovered["result"] == {"stage": "queued", "progress": 0}
