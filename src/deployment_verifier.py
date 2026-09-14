"""Public, credential-free verification for a SiliconDreams deployment."""

from __future__ import annotations

import ipaddress
import json
import socket
import ssl
from dataclasses import asdict, dataclass, replace
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

SECURITY_HEADERS = {
    "content-security-policy": ("default-src 'self'", "frame-ancestors 'none'"),
    "strict-transport-security": ("max-age=31536000", "includeSubDomains"),
    "x-content-type-options": ("nosniff",),
    "x-frame-options": ("DENY",),
    "referrer-policy": ("strict-origin-when-cross-origin",),
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class VerificationReport:
    base_url: str
    expected_version: str
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def _request(url: str, timeout: float) -> tuple[int, object, bytes]:
    opener = build_opener(_NoRedirect)
    request = Request(url, headers={"User-Agent": "SiliconDreams-Deployment-Verifier/1.0"})
    try:
        response = opener.open(request, timeout=timeout)
        return response.status, response.headers, response.read()
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def _normalized_base_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if not value:
        raise ValueError("base URL cannot be empty")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("base URL must be an https:// URL with a hostname")
    if parsed.path or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("base URL must not include a path, query, or fragment")
    return value


def _redirect_targets_origin(location: str, expected_origin: str) -> bool:
    actual = urlparse(location)
    expected = urlparse(expected_origin)
    return actual.scheme == expected.scheme and actual.netloc == expected.netloc


def _check_dns(hostname: str, expected_ip: str = "") -> CheckResult:
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(hostname, 443)})
    except socket.gaierror as exc:
        return CheckResult("dns", False, f"{hostname} did not resolve: {exc}")
    public_addresses = [address for address in addresses if ipaddress.ip_address(address).is_global]
    if not public_addresses:
        return CheckResult(
            "dns",
            False,
            f"{hostname} resolved only to non-public addresses: {', '.join(addresses)}",
        )
    if expected_ip and expected_ip not in public_addresses:
        return CheckResult(
            "dns",
            False,
            f"{hostname} -> {', '.join(public_addresses)}; expected {expected_ip}",
        )
    expected_detail = f"; expected {expected_ip}" if expected_ip else ""
    return CheckResult("dns", True, f"{hostname} -> {', '.join(public_addresses)}{expected_detail}")


def _check_tls(hostname: str, port: int, timeout: float) -> CheckResult:
    context = ssl.create_default_context()
    try:
        with (
            socket.create_connection((hostname, port), timeout=timeout) as raw_socket,
            context.wrap_socket(raw_socket, server_hostname=hostname) as tls_socket,
        ):
            certificate = tls_socket.getpeercert()
            protocol = tls_socket.version() or "unknown"
    except (OSError, ssl.SSLError) as exc:
        return CheckResult("tls", False, f"TLS handshake failed: {exc}")
    subject_alt_names = [
        value for key, value in certificate.get("subjectAltName", []) if key == "DNS"
    ]
    detail = f"{protocol}; certificate covers {', '.join(subject_alt_names) or hostname}"
    return CheckResult("tls", True, detail)


def _check_http_redirect(base_url: str, timeout: float) -> CheckResult:
    parsed = urlparse(base_url)
    http_url = f"http://{parsed.netloc}/"
    try:
        status, headers, _body = _request(http_url, timeout)
    except (OSError, URLError) as exc:
        return CheckResult("http_redirect", False, f"HTTP request failed: {exc}")
    location = headers.get("Location", "")
    passed = status in {301, 302, 307, 308} and _redirect_targets_origin(location, base_url)
    return CheckResult("http_redirect", passed, f"HTTP {status}; Location={location or '<none>'}")


def _check_health(base_url: str, expected_version: str, timeout: float) -> CheckResult:
    try:
        status, _headers, body = _request(urljoin(base_url + "/", "healthz"), timeout)
        payload = json.loads(body.decode("utf-8"))
    except (OSError, URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return CheckResult("health", False, f"health request failed: {exc}")
    actual_version = str(payload.get("version", ""))
    passed = status == 200 and payload.get("status") == "ok" and actual_version == expected_version
    return CheckResult(
        "health",
        passed,
        f"HTTP {status}; status={payload.get('status')}; version={actual_version or '<missing>'}",
    )


def _check_readiness(base_url: str, expected_version: str, timeout: float) -> CheckResult:
    try:
        status, _headers, body = _request(urljoin(base_url + "/", "readyz"), timeout)
        payload = json.loads(body.decode("utf-8"))
    except (OSError, URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return CheckResult("readiness", False, f"readiness request failed: {exc}")
    checks = payload.get("checks")
    checks_ready = (
        isinstance(checks, dict)
        and bool(checks)
        and all(value is True for value in checks.values())
    )
    actual_version = str(payload.get("version", ""))
    passed = (
        status == 200
        and payload.get("status") == "ready"
        and actual_version == expected_version
        and checks_ready
    )
    failed_checks = (
        sorted(name for name, value in checks.items() if value is not True)
        if isinstance(checks, dict)
        else ["missing_checks"]
    )
    detail = (
        f"HTTP {status}; status={payload.get('status')}; version={actual_version or '<missing>'}; "
        f"failed={','.join(failed_checks) or '<none>'}"
    )
    return CheckResult("readiness", passed, detail)


def _check_auth_boundary(base_url: str, timeout: float) -> CheckResult:
    try:
        status, headers, _body = _request(base_url + "/", timeout)
    except (OSError, URLError) as exc:
        return CheckResult("auth_boundary", False, f"root request failed: {exc}")
    location = headers.get("Location", "")
    passed = status == 303 and location == "/login"
    return CheckResult("auth_boundary", passed, f"HTTP {status}; Location={location or '<none>'}")


def _check_security_headers(base_url: str, timeout: float) -> CheckResult:
    try:
        status, headers, _body = _request(urljoin(base_url + "/", "healthz"), timeout)
    except (OSError, URLError) as exc:
        return CheckResult("security_headers", False, f"health request failed: {exc}")
    failures: list[str] = []
    for header, required_values in SECURITY_HEADERS.items():
        actual = headers.get(header, "")
        for required in required_values:
            if required.lower() not in actual.lower():
                failures.append(f"{header} missing {required!r}")
    detail = "; ".join(failures) if failures else f"all {len(SECURITY_HEADERS)} policies present"
    return CheckResult("security_headers", status == 200 and not failures, detail)


def _check_login_cookie(base_url: str, timeout: float) -> CheckResult:
    try:
        status, headers, _body = _request(urljoin(base_url + "/", "login"), timeout)
    except (OSError, URLError) as exc:
        return CheckResult("login_cookie", False, f"login request failed: {exc}")
    cookies = headers.get_all("Set-Cookie") or []
    csrf_cookie = next((cookie for cookie in cookies if cookie.startswith("sd_csrf=")), "")
    lowered = csrf_cookie.lower()
    passed = (
        status == 200 and bool(csrf_cookie) and "secure" in lowered and "samesite=strict" in lowered
    )
    detail = (
        f"HTTP {status}; CSRF cookie has Secure and SameSite=Strict"
        if passed
        else f"HTTP {status}; production CSRF cookie attributes are incomplete"
    )
    return CheckResult("login_cookie", passed, detail)


def _check_alias(alias_url: str, canonical_url: str, timeout: float) -> list[CheckResult]:
    parsed = urlparse(alias_url)
    hostname = parsed.hostname or ""
    port = parsed.port or 443
    dns = replace(_check_dns(hostname), name="alias_dns")
    tls = replace(_check_tls(hostname, port, timeout), name="alias_tls")
    try:
        status, headers, _body = _request(alias_url + "/", timeout)
    except (OSError, URLError) as exc:
        redirect = CheckResult("alias_redirect", False, f"alias request failed: {exc}")
    else:
        location = headers.get("Location", "")
        passed = status in {301, 302, 307, 308} and _redirect_targets_origin(
            location, canonical_url
        )
        redirect = CheckResult(
            "alias_redirect", passed, f"HTTP {status}; Location={location or '<none>'}"
        )
    return [dns, tls, redirect]


def verify_deployment(
    base_url: str,
    expected_version: str,
    *,
    expected_ip: str = "",
    alias_url: str = "",
    timeout: float = 10.0,
) -> VerificationReport:
    """Run non-destructive public deployment checks without credentials."""
    normalized = _normalized_base_url(base_url)
    normalized_alias = _normalized_base_url(alias_url) if alias_url else ""
    if normalized_alias == normalized:
        raise ValueError("alias URL must differ from the canonical base URL")
    if expected_ip:
        try:
            parsed_expected_ip = ipaddress.ip_address(expected_ip)
        except ValueError as exc:
            raise ValueError("expected IP must be a valid IP address") from exc
        if not parsed_expected_ip.is_global:
            raise ValueError("expected IP must be a public IP address")
        expected_ip = str(parsed_expected_ip)
    parsed = urlparse(normalized)
    hostname = parsed.hostname or ""
    port = parsed.port or 443
    checks = [
        _check_dns(hostname, expected_ip),
        _check_tls(hostname, port, timeout),
        _check_http_redirect(normalized, timeout),
        _check_health(normalized, expected_version, timeout),
        _check_readiness(normalized, expected_version, timeout),
        _check_auth_boundary(normalized, timeout),
        _check_security_headers(normalized, timeout),
        _check_login_cookie(normalized, timeout),
    ]
    if normalized_alias:
        checks.extend(_check_alias(normalized_alias, normalized, timeout))
    return VerificationReport(normalized, expected_version, checks)
