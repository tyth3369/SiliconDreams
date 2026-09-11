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
