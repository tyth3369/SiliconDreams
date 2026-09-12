#!/usr/bin/env python3
"""Generate production application-auth environment values."""

from __future__ import annotations

import getpass
import secrets
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.security import hash_password  # noqa: E402


def main() -> None:
    username = input("Application username [researcher]: ").strip() or "researcher"
    password = getpass.getpass("Application password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    if len(password) < 12:
        raise SystemExit("Use at least 12 characters")
    print("APP_ENV=production")
    print("AUTH_ENABLED=true")
    print(f"APP_USERNAME={shlex.quote(username)}")
    print(f"APP_PASSWORD_HASH={shlex.quote(hash_password(password))}")
    print(f"APP_SESSION_SECRET={shlex.quote(secrets.token_urlsafe(48))}")
    print("COOKIE_SECURE=true")
    print("TRUST_PROXY_HEADERS=true")
    print("RATE_LIMIT_ENABLED=true")


if __name__ == "__main__":
    main()
