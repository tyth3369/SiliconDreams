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
from src.evidence_policy import canonical_fact_value
from src.migrations import migrate


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


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
        connection = self.connect()
        try:
            migrate(connection)
        finally:
            connection.close()

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

    def get_document_by_sha256(self, sha256: str) -> dict[str, Any] | None:
        """Return an existing content-addressed document, if any."""
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM documents WHERE sha256=?", (sha256,)).fetchone()
        return dict(row) if row else None

    def set_document_status(
        self,
        document_id: str,
        status: str,
        *,
        page_count: int | None = None,
        error: str | None = None,
    ) -> None:
        """Update ingestion state without rewriting immutable document identity."""
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE documents
                SET parse_status=?,
                    page_count=COALESCE(?, page_count),
                    parse_error=?,
                    updated_at=?
                WHERE id=?
                """,
                (status, page_count, error, utc_now(), document_id),
            )

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

    def search_chunks_bm25(
        self, query: str, limit: int = 20, sources: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Run true BM25 over persisted chunks with Chinese n-gram tokenization."""
        query_tokens = self._lexical_tokens(query)
        rows = self.list_chunks()
        if sources:
            allowed_sources = set(sources)
            rows = [row for row in rows if row.get("original_filename") in allowed_sources]
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
                SELECT f.*, s.source_type, s.title AS source_title, s.url AS source_url,
                       s.publisher AS source_publisher, s.trust_tier
                FROM facts f
                JOIN sources s ON s.id = f.source_id
                WHERE {where}
                ORDER BY f.period DESC, f.metric
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def find_fact_conflicts(
        self,
        company: str | None = None,
        metric: str | None = None,
        period: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find same-company/metric/period facts with incompatible same-unit values."""
        clauses = []
        params: list[Any] = []
        for column, value in (("f.company", company), ("f.metric", metric), ("f.period", period)):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT f.*, s.title AS source_title, s.url AS source_url,
                       s.publisher AS source_publisher, s.published_at,
                       s.trust_tier
                FROM facts f
                JOIN sources s ON s.id = f.source_id
                {where}
                ORDER BY f.company, f.metric, f.period, s.trust_tier, s.title
                """,
                params,
            ).fetchall()

        groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            key = (
                item["company"],
                item["metric"],
                item["period"],
                str(item["unit"]).casefold(),
                str(item.get("currency") or "").casefold(),
            )
            groups.setdefault(key, []).append(item)

        conflicts = []
        for key, facts in groups.items():
            values = {canonical_fact_value(fact["value"]) for fact in facts}
            if len(values) > 1:
                conflicts.append(
                    {
                        "company": key[0],
                        "metric": key[1],
                        "period": key[2],
                        "unit": facts[0]["unit"],
                        "currency": facts[0].get("currency"),
                        "facts": facts,
                    }
                )
        return conflicts

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
                "SELECT 1 FROM conversations WHERE id=? AND archived_at IS NULL",
                (conversation_id,),
            ).fetchone()
        return row is not None

    def get_conversation(
        self, conversation_id: str, *, include_archived: bool = False
    ) -> dict[str, Any] | None:
        archived_clause = "" if include_archived else "AND archived_at IS NULL"
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT * FROM conversations WHERE id=? {archived_clause}",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_conversations(
        self, *, include_archived: bool = False, limit: int = 30
    ) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE archived_at IS NULL"
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, title, language, archived_at, created_at, updated_at
                FROM conversations
                {where}
                ORDER BY updated_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        normalized = " ".join(title.split()).strip()[:80]
        if not normalized:
            return False
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE conversations SET title=?, updated_at=?
                WHERE id=? AND archived_at IS NULL
                """,
                (normalized, utc_now(), conversation_id),
            )
        return cursor.rowcount == 1

    def archive_conversation(self, conversation_id: str) -> bool:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE conversations SET archived_at=?, updated_at=?
                WHERE id=? AND archived_at IS NULL
                """,
                (now, now, conversation_id),
            )
        return cursor.rowcount == 1

    def restore_conversation(self, conversation_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE conversations SET archived_at=NULL, updated_at=?
                WHERE id=? AND archived_at IS NOT NULL
                """,
                (utc_now(), conversation_id),
            )
        return cursor.rowcount == 1

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
                """
                UPDATE conversations
                SET updated_at=?,
                    title=CASE
                        WHEN title='' AND ?='user' THEN ?
                        ELSE title
                    END
                WHERE id=?
                """,
                (now, role, " ".join(content.split())[:48], conversation_id),
            )
        return message_id

    def list_watchlist(self) -> list[str]:
        """Return watched company keys in insertion order."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT company FROM watchlist ORDER BY created_at, rowid"
            ).fetchall()
        return [str(row["company"]) for row in rows]

    def set_watchlist(self, company: str, *, watched: bool) -> bool:
        """Idempotently add or remove a normalized company key."""
        normalized = " ".join(company.split()).strip()[:80]
        if not normalized:
            return False
        with self.connect() as connection:
            if watched:
                connection.execute(
                    "INSERT OR IGNORE INTO watchlist(company, created_at) VALUES (?, ?)",
                    (normalized, utc_now()),
                )
            else:
                connection.execute("DELETE FROM watchlist WHERE company=?", (normalized,))
        return True

    def get_cached_web_search(self, query_key: str, *, now: str | None = None) -> dict | None:
        """Return an unexpired structured search result."""
        timestamp = now or utc_now()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM web_search_cache WHERE query_key=? AND expires_at>?",
                (query_key, timestamp),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["results"] = json.loads(item.pop("results_json"))
        return item

    def cache_web_search(
        self,
        *,
        query_key: str,
        query: str,
        backend: str,
        results: list[dict[str, Any]],
        expires_at: str,
    ) -> None:
        """Persist a search response plus content-addressed result snapshots."""
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO web_search_cache(
                    query_key, query, backend, results_json, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(query_key) DO UPDATE SET
                    query=excluded.query,
                    backend=excluded.backend,
                    results_json=excluded.results_json,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at
                """,
                (
                    query_key,
                    query,
                    backend,
                    json.dumps(results, ensure_ascii=False),
                    now,
                    expires_at,
                ),
            )
            for result in results:
                url = str(result.get("url") or "")
                snippet = str(result.get("snippet") or "")
                if not url:
                    continue
                content_hash = hashlib.sha256(snippet.encode("utf-8")).hexdigest()
                snapshot_id = stable_id("snap", url, content_hash)
                connection.execute(
                    """
                    INSERT OR IGNORE INTO web_snapshots(
                        id, url, title, snippet, content_hash, publisher,
                        published_at, retrieved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        url,
                        str(result.get("title") or ""),
                        snippet,
                        content_hash,
                        str(result.get("publisher") or ""),
                        str(result.get("published_at") or ""),
                        now,
                    ),
                )

    def list_web_snapshots(self, url: str | None = None, limit: int = 100) -> list[dict]:
        """Inspect immutable search-result snapshots for provenance audits."""
        clause = "WHERE url=?" if url else ""
        params: tuple[Any, ...] = (url, limit) if url else (limit,)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM web_snapshots {clause} ORDER BY retrieved_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_messages(self, conversation_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, role, content, citations_json, created_at
                FROM (
                    SELECT rowid AS ordinal, id, role, content, citations_json, created_at
                    FROM messages
                    WHERE conversation_id=?
                    ORDER BY rowid DESC
                    LIMIT ?
                )
                ORDER BY ordinal ASC
                """,
                (conversation_id, limit),
            ).fetchall()
        messages = []
        for row in rows:
            item = dict(row)
            item["citations"] = json.loads(item.pop("citations_json"))
            messages.append(item)
        return messages

    def enqueue_job(
        self,
        job_type: str,
        payload: dict[str, Any],
        *,
        dedupe_key: str,
    ) -> str:
        """Persist an idempotent job; failed jobs are reset for an explicit retry."""
        job_id = stable_id("job", job_type, dedupe_key)
        now = utc_now()
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT status FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO jobs(
                        id, job_type, status, payload_json, result_json,
                        error, created_at, updated_at
                    ) VALUES (?, ?, 'pending', ?, ?, NULL, ?, ?)
                    """,
                    (
                        job_id,
                        job_type,
                        payload_json,
                        json.dumps({"stage": "queued", "progress": 0}),
                        now,
                        now,
                    ),
                )
            elif existing["status"] == "failed":
                connection.execute(
                    """
                    UPDATE jobs
                    SET status='pending', payload_json=?, result_json=?, error=NULL, updated_at=?
                    WHERE id=?
                    """,
                    (
                        payload_json,
                        json.dumps({"stage": "queued", "progress": 0}),
                        now,
                        job_id,
                    ),
                )
        return job_id

    @staticmethod
    def _decode_job(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        item["result"] = json.loads(item.pop("result_json"))
        return item

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._decode_job(row)

    def list_jobs(
        self,
        *,
        job_type: str | None = None,
        statuses: tuple[str, ...] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if job_type:
            clauses.append("job_type=?")
            params.append(job_type)
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(statuses)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ?", params
            ).fetchall()
        return [self._decode_job(row) for row in rows]

    def requeue_running_jobs(self, job_type: str) -> int:
        """Recover work interrupted by a process restart."""
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status='pending', result_json=?, error=NULL, updated_at=?
                WHERE job_type=? AND status='running'
                """,
                (json.dumps({"stage": "queued", "progress": 0}), now, job_type),
            )
        return cursor.rowcount

    def claim_next_job(self, job_type: str) -> dict[str, Any] | None:
        """Atomically claim the oldest pending job for a single local worker."""
        with self.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE job_type=? AND status='pending'
                ORDER BY created_at
                LIMIT 1
                """,
                (job_type,),
            ).fetchone()
            if row is None:
                return None
            updated = connection.execute(
                """
                UPDATE jobs SET status='running', result_json=?, updated_at=?
                WHERE id=? AND status='pending'
                """,
                (
                    json.dumps({"stage": "starting", "progress": 1}),
                    utc_now(),
                    row["id"],
                ),
            )
            if updated.rowcount != 1:
                return None
            claimed = connection.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
        return self._decode_job(claimed)

    def update_job_progress(
        self,
        job_id: str,
        *,
        stage: str,
        progress: int,
        detail: dict[str, Any] | None = None,
    ) -> None:
        progress = max(0, min(100, int(progress)))
        result = {"stage": stage, "progress": progress, **(detail or {})}
        with self.connect() as connection:
            connection.execute(
                "UPDATE jobs SET result_json=?, updated_at=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False), utc_now(), job_id),
            )

    def finish_job(
        self,
        job_id: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        status = "failed" if error else "succeeded"
        final_result = result or {
            "stage": "failed" if error else "completed",
            "progress": 100 if not error else 0,
        }
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE jobs SET status=?, result_json=?, error=?, updated_at=? WHERE id=?
                """,
                (
                    status,
                    json.dumps(final_result, ensure_ascii=False),
                    error,
                    utc_now(),
                    job_id,
                ),
            )

    def add_audit_event(
        self,
        *,
        request_id: str,
        actor: str,
        action: str,
        outcome: str,
        target_type: str | None = None,
        target_id: str | None = None,
        client_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Append a security/administrative event; rows are immutable by schema trigger."""
        event_id = f"aud_{uuid.uuid4().hex}"
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_events(
                    id, request_id, actor, action, target_type, target_id,
                    outcome, client_hash, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    request_id,
                    actor,
                    action,
                    target_type,
                    target_id,
                    outcome,
                    client_hash,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )
        return event_id

    def list_audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (max(1, min(limit, 1000)),),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            items.append(item)
        return items

    def count(self, table: str) -> int:
        allowed = {
            "sources",
            "documents",
            "chunks",
            "facts",
            "conversations",
            "messages",
            "jobs",
            "watchlist",
            "web_search_cache",
            "web_snapshots",
            "audit_events",
        }
        if table not in allowed:
            raise ValueError(f"Unsupported table: {table}")
        with self.connect() as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
