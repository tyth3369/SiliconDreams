from src.security import SecurityManager, SlidingWindowLimiter, hash_password, verify_password


def test_password_hash_is_salted_and_verifies():
    first = hash_password("a sufficiently long password")
    second = hash_password("a sufficiently long password")
    assert first != second
    assert verify_password("a sufficiently long password", first) is True
    assert verify_password("wrong", first) is False
    assert verify_password("anything", "invalid") is False


def test_signed_session_rejects_tampering_and_expiry():
    manager = SecurityManager("s" * 32, session_ttl_seconds=60)
    token = manager.issue_session("researcher", now=100)
    session = manager.verify_session(token, now=120)
    assert session.username == "researcher"
    assert session.expires_at == 160
    assert manager.verify_session(token + "x", now=120) is None
    assert manager.verify_session(token, now=160) is None
    assert manager.verify_session(token, now=161) is None


def test_malformed_password_hash_is_rejected():
    assert verify_password("anything", "pbkdf2_sha256$600000$%%%$%%%") is False


def test_csrf_token_is_bound_to_session():
    manager = SecurityManager("s" * 32)
    token = manager.issue_csrf("session-a")
    assert manager.verify_csrf(token, "session-a") is True
    assert manager.verify_csrf(token, "session-b") is False
    assert manager.verify_csrf(token + "x", "session-a") is False


def test_sliding_window_limiter_returns_retry_after_and_expires_events():
    limiter = SlidingWindowLimiter()
    assert limiter.allow("actor", limit=2, window_seconds=60, now=100) == (True, 0)
    assert limiter.allow("actor", limit=2, window_seconds=60, now=101) == (True, 0)
    allowed, retry_after = limiter.allow("actor", limit=2, window_seconds=60, now=102)
    assert allowed is False
    assert retry_after > 0
    assert limiter.allow("actor", limit=2, window_seconds=60, now=161) == (True, 0)
