"""First-party authentication, CSRF, and in-process rate limiting."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, *, iterations: int = PASSWORD_ITERATIONS) -> str:
    """Create a salted PBKDF2-SHA256 password verifier."""
    if not password:
        raise ValueError("Password must not be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{PASSWORD_ALGORITHM}${iterations}${_b64_encode(salt)}${_b64_encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password without exposing parser/timing details."""
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        iterations = int(rounds)
        if iterations < 100_000 or iterations > 2_000_000:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), _b64_decode(salt), iterations)
        return hmac.compare_digest(digest, _b64_decode(expected))
    except (binascii.Error, TypeError, ValueError):
        return False


@dataclass(frozen=True)
class AuthSession:
    username: str
    session_id: str
    expires_at: int


class SecurityManager:
    """Issue and verify stateless HMAC-signed browser tokens."""

    def __init__(self, secret: str, session_ttl_seconds: int = 12 * 60 * 60):
        self._secret = secret.encode("utf-8")
        self.session_ttl_seconds = session_ttl_seconds

    def _sign(self, payload: str) -> str:
        return _b64_encode(hmac.new(self._secret, payload.encode(), hashlib.sha256).digest())

    def issue_session(self, username: str, *, now: int | None = None) -> str:
        timestamp = int(time.time() if now is None else now)
        payload = _b64_encode(
            json.dumps(
                {
                    "sub": username,
                    "sid": secrets.token_urlsafe(18),
                    "exp": timestamp + self.session_ttl_seconds,
                },
                separators=(",", ":"),
            ).encode()
        )
        return f"{payload}.{self._sign(payload)}"

    def verify_session(self, token: str | None, *, now: int | None = None) -> AuthSession | None:
        if not token:
            return None
        try:
            payload, signature = token.split(".", 1)
            if not hmac.compare_digest(signature, self._sign(payload)):
                return None
            data = json.loads(_b64_decode(payload))
            current = int(time.time() if now is None else now)
            if int(data["exp"]) <= current:
                return None
            return AuthSession(str(data["sub"]), str(data["sid"]), int(data["exp"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def issue_csrf(self, binding: str) -> str:
        nonce = secrets.token_urlsafe(24)
        payload = f"{binding}.{nonce}"
        return f"{nonce}.{self._sign(payload)}"

    def verify_csrf(self, token: str | None, binding: str) -> bool:
        if not token:
            return False
        try:
            nonce, signature = token.split(".", 1)
            return hmac.compare_digest(signature, self._sign(f"{binding}.{nonce}"))
        except ValueError:
            return False

    def hash_identifier(self, value: str) -> str:
        """Create a stable, non-reversible identifier for audit/rate-limit metadata."""
        return hmac.new(self._secret, value.encode(), hashlib.sha256).hexdigest()[:24]


class SlidingWindowLimiter:
    """Thread-safe bounded sliding-window limiter for the required single process."""

    def __init__(self):
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
        now: float | None = None,
    ) -> tuple[bool, int]:
        current = time.monotonic() if now is None else now
        cutoff = current - window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(window_seconds - (current - events[0])))
                return False, retry_after
            events.append(current)
            return True, 0

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
