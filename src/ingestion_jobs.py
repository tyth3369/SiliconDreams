"""Persistent single-worker execution for PDF ingestion jobs."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from src.storage import Database

logger = logging.getLogger(__name__)


class IngestionWorker:
    """Poll SQLite for durable PDF jobs and execute them one at a time."""

    JOB_TYPE = "pdf_ingest"

    def __init__(
        self,
        database_provider: Callable[[], Database],
        handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._database_provider = database_provider
        self._handler = handler
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self, *, recover: bool = False) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            if recover:
                recovered = self._database_provider().requeue_running_jobs(self.JOB_TYPE)
                if recovered:
                    logger.info("Recovered %d interrupted PDF ingestion job(s)", recovered)
            self._thread = threading.Thread(
                target=self._run,
                name="pdf-ingestion-worker",
                daemon=True,
            )
            self._thread.start()

    def wake(self) -> None:
        self.start()
        self._wake_event.set()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            database = self._database_provider()
            job = database.claim_next_job(self.JOB_TYPE)
            if job is None:
                self._wake_event.wait(timeout=1.0)
                self._wake_event.clear()
                continue
            try:
                result = self._handler(job)
                database.finish_job(job["id"], result=result)
            except Exception as exc:
                logger.exception("PDF ingestion job failed: %s", job["id"])
                database.finish_job(
                    job["id"],
                    result={"stage": "failed", "progress": 0},
                    error=str(exc),
                )
