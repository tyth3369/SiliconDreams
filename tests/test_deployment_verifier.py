import json
from email.message import Message
from urllib.error import URLError

import pytest

from src import deployment_verifier as verifier


def _headers(**values: str) -> Message:
    headers = Message()
    for name, value in values.items():
        headers.add_header(name.replace("_", "-"), value)
    return headers


def test_base_url_requires_https_origin_only():
    with pytest.raises(ValueError, match="https"):
        verifier.verify_deployment("http://example.com", "1.0.0")
    with pytest.raises(ValueError, match="path"):
        verifier.verify_deployment("https://example.com/path", "1.0.0")
    with pytest.raises(ValueError, match="valid IP"):
        verifier.verify_deployment("https://example.com", "1.0.0", expected_ip="not-an-ip")
    with pytest.raises(ValueError, match="public IP"):
        verifier.verify_deployment("https://example.com", "1.0.0", expected_ip="198.18.0.1")
    with pytest.raises(ValueError, match="must differ"):
        verifier.verify_deployment("https://example.com", "1.0.0", alias_url="https://example.com")


def test_successful_public_verification(monkeypatch):
    monkeypatch.setattr(
        verifier.socket,
        "getaddrinfo",
        lambda *_args: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(
        verifier,
        "_check_tls",
        lambda *_args: verifier.CheckResult("tls", True, "TLSv1.3; valid certificate"),
    )

    def fake_request(url: str, _timeout: float):
        if url == "http://sillycon.xyz/":
            return 308, _headers(Location="https://sillycon.xyz/"), b""
        if url == "https://sillycon.xyz/":
            return 303, _headers(Location="/login"), b""
        if url == "https://sillycon.xyz/login":
            headers = _headers()
            headers.add_header("Set-Cookie", "sd_csrf=token; Path=/; SameSite=strict; Secure")
            return 200, headers, b"login"
        if url == "https://sillycon.xyz/healthz":
            return (
                200,
                _headers(
                    Content_Security_Policy="default-src 'self'; frame-ancestors 'none'",
                    Strict_Transport_Security="max-age=31536000; includeSubDomains",
                    X_Content_Type_Options="nosniff",
                    X_Frame_Options="DENY",
                    Referrer_Policy="strict-origin-when-cross-origin",
                ),
                json.dumps({"status": "ok", "version": "1.0.0-rc.4"}).encode(),
            )
        raise AssertionError(url)

    monkeypatch.setattr(verifier, "_request", fake_request)
    report = verifier.verify_deployment(
        "https://sillycon.xyz", "1.0.0-rc.4", expected_ip="93.184.216.34"
    )

    assert report.passed is True
    assert len(report.checks) == 7
    assert report.to_dict()["passed"] is True


def test_verification_reports_failures_without_credentials(monkeypatch):
    monkeypatch.setattr(
        verifier.socket,
        "getaddrinfo",
        lambda *_args: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(
        verifier,
        "_check_tls",
        lambda *_args: verifier.CheckResult("tls", False, "certificate expired"),
    )

    def fake_request(url: str, _timeout: float):
        if url.startswith("http://"):
            return 200, _headers(), b""
        if url.endswith("/healthz"):
            return 200, _headers(), b'{"status":"ok","version":"wrong"}'
        if url.endswith("/login"):
            return 200, _headers(), b"login"
        return 200, _headers(), b"public root"

    monkeypatch.setattr(verifier, "_request", fake_request)
    report = verifier.verify_deployment("https://sillycon.xyz", "1.0.0-rc.4")

    assert report.passed is False
    assert {check.name for check in report.checks if not check.passed} == {
        "tls",
        "http_redirect",
        "health",
        "auth_boundary",
        "security_headers",
        "login_cookie",
    }


def test_health_network_error_is_a_failed_check(monkeypatch):
    monkeypatch.setattr(
        verifier, "_request", lambda *_args: (_ for _ in ()).throw(URLError("down"))
    )
    result = verifier._check_health("https://sillycon.xyz", "1.0.0", 1.0)
    assert result.passed is False
    assert "down" in result.detail


def test_dns_rejects_proxy_fake_ip_and_wrong_expected_address(monkeypatch):
    monkeypatch.setattr(
        verifier.socket,
        "getaddrinfo",
        lambda *_args: [(None, None, None, None, ("198.18.0.32", 443))],
    )
    assert verifier._check_dns("sillycon.xyz").passed is False

    monkeypatch.setattr(
        verifier.socket,
        "getaddrinfo",
        lambda *_args: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    result = verifier._check_dns("sillycon.xyz", "1.1.1.1")
    assert result.passed is False
    assert "expected 1.1.1.1" in result.detail


def test_alias_checks_dns_tls_and_canonical_redirect(monkeypatch):
    monkeypatch.setattr(
        verifier.socket,
        "getaddrinfo",
        lambda *_args: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(
        verifier,
        "_check_tls",
        lambda *_args: verifier.CheckResult("tls", True, "TLSv1.3"),
    )
    monkeypatch.setattr(
        verifier,
        "_request",
        lambda *_args: (
            308,
            _headers(Location="https://sillycon.xyz/research"),
            b"",
        ),
    )

    checks = verifier._check_alias("https://www.sillycon.xyz", "https://sillycon.xyz", timeout=1.0)
    assert [check.name for check in checks] == ["alias_dns", "alias_tls", "alias_redirect"]
    assert all(check.passed for check in checks)


def test_redirect_origin_comparison_rejects_prefix_confusion():
    assert verifier._redirect_targets_origin("https://sillycon.xyz/login", "https://sillycon.xyz")
    assert not verifier._redirect_targets_origin(
        "https://sillycon.xyz.attacker.example/", "https://sillycon.xyz"
    )
