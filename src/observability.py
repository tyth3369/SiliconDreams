"""Privacy-safe request telemetry for the bounded Agent pipeline."""

from __future__ import annotations

import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import InvalidOperation
from threading import Lock
from typing import Any

from config import ObservabilityConfig
from src.tools.calculator import calculate_llm_usage_cost


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _milliseconds(seconds: float) -> int:
    return max(0, round(seconds * 1000))


def _nonnegative_int(value: Any) -> int:
    """Normalize optional provider counters without letting telemetry break a request."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


@dataclass
class RunTelemetry:
    """Collect aggregate operational signals without prompts, answers, or source names."""

    request_id: str
    conversation_id: str
    provider: str
    model: str
    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex}")
    started_at: str = field(default_factory=_utc_now)
    _started_monotonic: float = field(default_factory=time.perf_counter, repr=False)
    _first_token_ms: int | None = field(default=None, repr=False)
    _model_calls: int = field(default=0, repr=False)
    _model_errors: int = field(default=0, repr=False)
    _prompt_tokens: int = field(default=0, repr=False)
    _completion_tokens: int = field(default=0, repr=False)
    _cache_hit_tokens: int = field(default=0, repr=False)
    _cache_miss_tokens: int = field(default=0, repr=False)
    _tool_events: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _error_code: str | None = field(default=None, repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def model_call_started(self) -> None:
        with self._lock:
            self._model_calls += 1

    def model_call_failed(self, code: str = "model_call_failed") -> None:
        with self._lock:
            self._model_errors += 1
            self._error_code = self._error_code or code

    def add_usage(self, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        prompt_tokens = _nonnegative_int(usage.get("prompt_tokens"))
        cache_hit_tokens = _nonnegative_int(
            usage.get("prompt_cache_hit_tokens") or usage.get("cache_hit_tokens")
        )
        raw_cache_miss = usage.get("prompt_cache_miss_tokens")
        if raw_cache_miss is None:
            raw_cache_miss = usage.get("cache_miss_tokens")
        cache_miss_tokens = (
            _nonnegative_int(raw_cache_miss)
            if raw_cache_miss is not None
            else max(0, prompt_tokens - cache_hit_tokens)
        )
        with self._lock:
            self._prompt_tokens += prompt_tokens
            self._completion_tokens += _nonnegative_int(usage.get("completion_tokens"))
            self._cache_hit_tokens += cache_hit_tokens
            self._cache_miss_tokens += cache_miss_tokens

    def record_tool(self, name: str, elapsed_seconds: float, *, error: bool = False) -> None:
        with self._lock:
            self._tool_events.append(
                {
                    "id": f"tool_{uuid.uuid4().hex}",
                    "tool_name": name,
                    "outcome": "error" if error else "success",
                    "duration_ms": _milliseconds(elapsed_seconds),
                    "created_at": _utc_now(),
                }
            )
            if error:
                self._error_code = self._error_code or "tool_execution_failed"

    def first_token(self) -> None:
        with self._lock:
            if self._first_token_ms is None:
                self._first_token_ms = _milliseconds(time.perf_counter() - self._started_monotonic)

    def fail(self, code: str) -> None:
        with self._lock:
            self._error_code = code[:100]

    def _estimated_cost(self) -> str | None:
        if not ObservabilityConfig.pricing_configured():
            return None
        try:
            return calculate_llm_usage_cost(
                cache_hit_tokens=self._cache_hit_tokens,
                cache_miss_tokens=self._cache_miss_tokens,
                completion_tokens=self._completion_tokens,
                cache_hit_usd_per_million=(ObservabilityConfig.input_cache_hit_usd_per_million),
                cache_miss_usd_per_million=(ObservabilityConfig.input_cache_miss_usd_per_million),
                output_usd_per_million=ObservabilityConfig.output_usd_per_million,
            )
        except (InvalidOperation, ValueError):
            return None

    def finish(
        self,
        citations: list[dict[str, Any]],
        *,
        status: str | None = None,
    ) -> dict[str, Any]:
        completed_at = _utc_now()
        source_types = Counter(
            str(citation.get("source_type") or "unknown") for citation in citations
        )
        tool_errors = sum(event["outcome"] == "error" for event in self._tool_events)
        resolved_status = status
        if resolved_status is None:
            if self._error_code == "final_response_failed":
                resolved_status = "error"
            else:
                resolved_status = "degraded" if self._model_errors or tool_errors else "success"
        return {
            "id": self.run_id,
            "request_id": self.request_id,
            "conversation_id": self.conversation_id,
            "provider": self.provider,
            "model": self.model,
            "status": resolved_status,
            "duration_ms": _milliseconds(time.perf_counter() - self._started_monotonic),
            "first_token_ms": self._first_token_ms,
            "model_calls": self._model_calls,
            "model_errors": self._model_errors,
            "tool_calls": len(self._tool_events),
            "tool_errors": tool_errors,
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
            "cache_hit_tokens": self._cache_hit_tokens,
            "cache_miss_tokens": self._cache_miss_tokens,
            "estimated_cost_usd": self._estimated_cost(),
            "source_count": len(citations),
            "source_types": dict(sorted(source_types.items())),
            "error_code": self._error_code,
            "started_at": self.started_at,
            "completed_at": completed_at,
            "created_at": completed_at,
            "tool_events": list(self._tool_events),
        }


def is_tool_error(result: str) -> bool:
    """Recognize structured tool failures without retaining their sensitive payloads."""
    stripped = result.lstrip()
    return stripped.startswith("{") and '"error"' in stripped[:200]


__all__ = ["RunTelemetry", "is_tool_error"]
