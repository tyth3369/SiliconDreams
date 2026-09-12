"""Real-browser regression coverage for the research workbench."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    port = _free_port()
    temp_dir = tmp_path_factory.mktemp("browser-e2e")
    env = os.environ.copy()
    env["SILICONDREAMS_DATABASE_FILE"] = str(temp_dir / "browser.db")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                with urlopen(f"{url}/healthz", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("E2E server did not start")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.mark.e2e
def test_theme_language_charts_and_watchlist_preserve_workspace(live_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(live_server, wait_until="networkidle")

        page.locator("#chat-container").evaluate(
            "node => node.insertAdjacentHTML('beforeend', '<div class=\"chat-msg user\"><div class=\"msg-content\">Browser persistence marker</div></div>')"
        )
        initial_messages = page.locator("#chat-container .chat-msg").count()

        page.get_by_role("button", name="浅色").click()
        assert page.locator("html").get_attribute("data-theme") == "light"
        page.get_by_role("button", name="English").click()
        page.get_by_role("button", name="Data Charts").click()
        page.get_by_role("heading", name="Foundry Financial Analytics").wait_for()
        assert page.locator('[data-chart="line"] svg').count() == 2
        assert page.locator("#chat-container .chat-msg").count() == initial_messages

        page.get_by_role("button", name="Watchlist").click()
        page.get_by_role("heading", name="Company Watchlist").wait_for()
        page.get_by_role("button", name="台积电 Follow").click()
        page.get_by_text("TSMC 2026 Q2 results").wait_for()
        assert page.locator('.event-timeline a[target="_blank"]').count() >= 1
        assert page.locator("#chat-container .chat-msg").count() == initial_messages
        browser.close()
