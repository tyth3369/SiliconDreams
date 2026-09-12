import pytest

from config import SearchConfig, SecurityConfig


def test_tavily_placeholder_is_not_treated_as_configured(monkeypatch):
    monkeypatch.setattr(SearchConfig, "api_key", "tvly-your-tavily-api-key-here")
    assert SearchConfig.is_configured() is False


def test_real_tavily_key_is_treated_as_configured(monkeypatch):
    monkeypatch.setattr(SearchConfig, "api_key", "tvly-test-value")
    assert SearchConfig.is_configured() is True


def test_production_refuses_to_start_without_auth(monkeypatch):
    monkeypatch.setattr(SecurityConfig, "environment", "production")
    monkeypatch.setattr(SecurityConfig, "auth_enabled", False)
    with pytest.raises(RuntimeError, match="AUTH_ENABLED must be true"):
        SecurityConfig.validate()


def test_production_security_configuration_validates(monkeypatch):
    monkeypatch.setattr(SecurityConfig, "environment", "production")
    monkeypatch.setattr(SecurityConfig, "auth_enabled", True)
    monkeypatch.setattr(SecurityConfig, "username", "researcher")
    monkeypatch.setattr(SecurityConfig, "password_hash", "pbkdf2_sha256$600000$salt$digest")
    monkeypatch.setattr(SecurityConfig, "session_secret", "s" * 32)
    monkeypatch.setattr(SecurityConfig, "cookie_secure", True)
    monkeypatch.setattr(SecurityConfig, "rate_limit_enabled", True)
    SecurityConfig.validate()


def test_security_limits_must_be_positive(monkeypatch):
    monkeypatch.setattr(SecurityConfig, "environment", "development")
    monkeypatch.setattr(SecurityConfig, "auth_enabled", True)
    monkeypatch.setattr(SecurityConfig, "username", "researcher")
    monkeypatch.setattr(SecurityConfig, "password_hash", "pbkdf2_sha256$600000$salt$digest")
    monkeypatch.setattr(SecurityConfig, "session_secret", "s" * 32)
    monkeypatch.setattr(SecurityConfig, "request_limit_per_minute", 0)
    with pytest.raises(RuntimeError, match="REQUEST_LIMIT_PER_MINUTE"):
        SecurityConfig.validate()


def test_production_requires_rate_limiting(monkeypatch):
    monkeypatch.setattr(SecurityConfig, "environment", "production")
    monkeypatch.setattr(SecurityConfig, "auth_enabled", True)
    monkeypatch.setattr(SecurityConfig, "username", "researcher")
    monkeypatch.setattr(SecurityConfig, "password_hash", "pbkdf2_sha256$600000$salt$digest")
    monkeypatch.setattr(SecurityConfig, "session_secret", "s" * 32)
    monkeypatch.setattr(SecurityConfig, "cookie_secure", True)
    monkeypatch.setattr(SecurityConfig, "rate_limit_enabled", False)
    with pytest.raises(RuntimeError, match="RATE_LIMIT_ENABLED=true"):
        SecurityConfig.validate()


def test_unknown_application_environment_is_rejected(monkeypatch):
    monkeypatch.setattr(SecurityConfig, "environment", "prod")
    with pytest.raises(RuntimeError, match="APP_ENV must be"):
        SecurityConfig.validate()
