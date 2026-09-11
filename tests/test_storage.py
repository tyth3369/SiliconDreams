import hashlib
import sqlite3
from pathlib import Path

import pytest

from src.storage import Database, stable_id


@pytest.fixture
def database(tmp_path: Path) -> Database:
    return Database(tmp_path / "silicondreams-test.db")


def test_schema_initializes(database):
    assert database.count("sources") == 0


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
    assert version == "3"


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
