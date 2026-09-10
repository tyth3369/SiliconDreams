"""SQLite persistence for evidence, documents, facts, jobs, and conversations."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config import DATABASE_FILE

SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

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
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_url
ON sources(url) WHERE url IS NOT NULL AND url != '';

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
);

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
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_page ON chunks(document_id, page);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    text,
    section,
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(chunk_id, text, section) VALUES (new.id, new.text, new.section);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE chunk_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE chunk_id = old.id;
    INSERT INTO chunks_fts(chunk_id, text, section) VALUES (new.id, new.text, new.section);
END;

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
);

CREATE INDEX IF NOT EXISTS idx_facts_lookup ON facts(company, metric, period);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'zh',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    citations_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class Database:
    """Small explicit repository around SQLite; no ORM or hidden session state."""

    def __init__(self, path: str | Path = DATABASE_FILE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def upsert_source(
        self,
        *,
        source_type: str,
        title: str,
        url: str | None = None,
        publisher: str | None = None,
        published_at: str | None = None,
        trust_tier: int = 3,
        content_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        source_id = stable_id("src", source_type, url or title)
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sources(
                    id, source_type, title, url, publisher, published_at, retrieved_at,
                    trust_tier, content_hash, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    publisher=COALESCE(excluded.publisher, sources.publisher),
                    published_at=COALESCE(excluded.published_at, sources.published_at),
                    retrieved_at=excluded.retrieved_at,
                    trust_tier=MIN(sources.trust_tier, excluded.trust_tier),
                    content_hash=COALESCE(excluded.content_hash, sources.content_hash),
                    metadata_json=excluded.metadata_json
                """,
                (
                    source_id,
                    source_type,
                    title,
                    url,
                    publisher,
                    published_at,
                    now,
                    trust_tier,
                    content_hash,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                ),
            )
        return source_id

    def upsert_document(
        self,
        *,
        source_id: str,
        original_filename: str,
        stored_path: str,
        sha256: str,
        page_count: int = 0,
        report_period: str | None = None,
        parse_status: str = "pending",
        parse_error: str | None = None,
    ) -> str:
        document_id = stable_id("doc", sha256)
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO documents(
                    id, source_id, original_filename, stored_path, sha256, page_count,
                    report_period, parse_status, parse_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    original_filename=excluded.original_filename,
                    stored_path=excluded.stored_path,
                    page_count=excluded.page_count,
                    report_period=COALESCE(excluded.report_period, documents.report_period),
                    parse_status=excluded.parse_status,
                    parse_error=excluded.parse_error,
                    updated_at=excluded.updated_at
                """,
                (
                    document_id,
                    source_id,
                    original_filename,
                    stored_path,
                    sha256,
                    page_count,
                    report_period,
                    parse_status,
                    parse_error,
                    now,
                    now,
                ),
            )
        return document_id

    def list_documents(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT d.*, s.title AS source_title
                FROM documents d
                JOIN sources s ON s.id = d.source_id
                ORDER BY d.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_chunk(
        self,
        *,
        document_id: str,
        source_id: str,
        page: int,
        chunk_type: str,
        text: str,
        section: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunk_id = stable_id("chk", document_id, page, chunk_type, content_hash)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO chunks(
                    id, document_id, source_id, page, section, chunk_type, text,
                    content_hash, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id, content_hash) DO UPDATE SET
                    page=excluded.page,
                    section=excluded.section,
                    chunk_type=excluded.chunk_type,
                    metadata_json=excluded.metadata_json
                """,
                (
                    chunk_id,
                    document_id,
                    source_id,
                    page,
                    section,
                    chunk_type,
                    text,
                    content_hash,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )
        return chunk_id

    def search_chunks_lexical(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        terms = [token for token in query.replace('"', " ").split() if token]
        if not terms:
            return []
        fts_query = " OR ".join(f'"{term}"' for term in terms)
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT c.*, bm25(chunks_fts) AS rank
                FROM chunks_fts
                JOIN chunks c ON c.id = chunks_fts.chunk_id
                WHERE chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_chunks(self, limit: int = 100_000) -> list[dict[str, Any]]:
        """Return persisted chunks with source metadata for lexical retrieval."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT c.*, d.original_filename, s.title AS source_title,
                       s.url AS source_url, s.publisher, s.published_at,
                       s.trust_tier
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                JOIN sources s ON s.id = c.source_id
                ORDER BY c.created_at, c.id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _lexical_tokens(text: str) -> list[str]:
        """Tokenize English/numbers and overlapping Chinese n-grams deterministically."""
        normalized = text.lower()
        tokens = re.findall(r"[a-z0-9]+(?:[._%-][a-z0-9]+)*", normalized)
        for span in re.findall(r"[\u3400-\u9fff]+", normalized):
            tokens.append(span)
            tokens.extend(span[index : index + 2] for index in range(max(0, len(span) - 1)))
            tokens.extend(span[index : index + 3] for index in range(max(0, len(span) - 2)))
        return tokens

    def search_chunks_bm25(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Run true BM25 over persisted chunks with Chinese n-gram tokenization."""
        query_tokens = self._lexical_tokens(query)
        rows = self.list_chunks()
        if not query_tokens or not rows:
            return []

        corpus = [self._lexical_tokens(f"{row['section']} {row['text']}") for row in rows]
        document_frequency: Counter[str] = Counter()
        for tokens in corpus:
            document_frequency.update(set(tokens))

        total_documents = len(corpus)
        average_length = sum(len(tokens) for tokens in corpus) / total_documents
        k1, b = 1.5, 0.75
        scored: list[dict[str, Any]] = []
        for row, tokens in zip(rows, corpus, strict=True):
            frequencies = Counter(tokens)
            document_length = len(tokens)
            score = 0.0
            for term in set(query_tokens):
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                df = document_frequency[term]
                inverse_document_frequency = math.log(1 + (total_documents - df + 0.5) / (df + 0.5))
                denominator = frequency + k1 * (
                    1 - b + b * document_length / max(average_length, 1)
                )
                score += inverse_document_frequency * frequency * (k1 + 1) / denominator
            if score > 0:
                item = dict(row)
                item["bm25_score"] = score
                scored.append(item)

        scored.sort(key=lambda item: item["bm25_score"], reverse=True)
        return scored[:limit]

    def upsert_fact(
        self,
        *,
        source_id: str,
        company: str,
        metric: str,
        period: str,
        value: str | int | float,
        unit: str,
        currency: str | None = None,
        document_id: str | None = None,
        page: int | None = None,
        quote: str | None = None,
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        fact_id = stable_id("fact", company, metric, period, source_id, value, unit)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO facts(
                    id, source_id, document_id, company, metric, period, value, unit,
                    currency, page, quote, confidence, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(company, metric, period, source_id, value, unit) DO UPDATE SET
                    document_id=COALESCE(excluded.document_id, facts.document_id),
                    currency=COALESCE(excluded.currency, facts.currency),
                    page=COALESCE(excluded.page, facts.page),
                    quote=COALESCE(excluded.quote, facts.quote),
                    confidence=excluded.confidence,
                    metadata_json=excluded.metadata_json
                """,
                (
                    fact_id,
                    source_id,
                    document_id,
                    company,
                    metric,
                    period,
                    str(value),
                    unit,
                    currency,
                    page,
                    quote,
                    confidence,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )
        return fact_id

    def find_facts(
        self, company: str, metric: str | None = None, period: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["f.company = ?"]
        params: list[Any] = [company]
        if metric:
            clauses.append("f.metric = ?")
            params.append(metric)
        if period:
            clauses.append("f.period = ?")
            params.append(period)
        where = " AND ".join(clauses)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT f.*, s.title AS source_title, s.url AS source_url,
                       s.publisher AS source_publisher, s.trust_tier
                FROM facts f
                JOIN sources s ON s.id = f.source_id
                WHERE {where}
                ORDER BY f.period DESC, f.metric
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def create_conversation(self, language: str = "zh", title: str = "") -> str:
        conversation_id = f"conv_{uuid.uuid4().hex}"
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO conversations(id, title, language, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, title, language, now, now),
            )
        return conversation_id

    def conversation_exists(self, conversation_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
        return row is not None

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
    ) -> str:
        message_id = f"msg_{uuid.uuid4().hex}"
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO messages(id, conversation_id, role, content, citations_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    conversation_id,
                    role,
                    content,
                    json.dumps(citations or [], ensure_ascii=False),
                    now,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id)
            )
        return message_id

    def list_messages(self, conversation_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, role, content, citations_json, created_at
                FROM messages
                WHERE conversation_id=?
                ORDER BY rowid ASC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
        messages = []
        for row in rows:
            item = dict(row)
            item["citations"] = json.loads(item.pop("citations_json"))
            messages.append(item)
        return messages

    def count(self, table: str) -> int:
        allowed = {"sources", "documents", "chunks", "facts", "conversations", "messages", "jobs"}
        if table not in allowed:
            raise ValueError(f"Unsupported table: {table}")
        with self.connect() as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
