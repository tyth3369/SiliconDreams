import asyncio
import io
import re
import time

import pymupdf
import pytest
from httpx import ASGITransport, AsyncClient

import server
from src.security import SecurityManager, hash_password
from src.storage import Database


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    server._ingestion_worker.stop()
    monkeypatch.setattr(server, "_db", Database(tmp_path / "server-test.db"))
    server._pending_agent_configs.clear()
    server._rate_limiter.clear()
    yield
    server._ingestion_worker.stop()


def _enable_auth(monkeypatch):
    monkeypatch.setattr(server.SecurityConfig, "auth_enabled", True)
    monkeypatch.setattr(server.SecurityConfig, "username", "researcher")
    monkeypatch.setattr(
        server.SecurityConfig,
        "password_hash",
        hash_password("correct horse battery staple", iterations=100_000),
    )
    monkeypatch.setattr(server.SecurityConfig, "session_secret", "s" * 48)
    monkeypatch.setattr(server, "_security", SecurityManager("s" * 48))
    monkeypatch.setitem(server.jinja.globals, "auth_enabled", True)


async def _request(method: str, path: str, **kwargs):
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_homepage_smoke():
    response = asyncio.run(_request("GET", "/"))
    assert response.status_code == 200
    assert "SiliconDreams" in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "'unsafe-inline'" not in response.headers["content-security-policy"]
    assert "nonce-" in response.headers["content-security-policy"]
    nonce = re.search(r"nonce-([^' ]+)", response.headers["content-security-policy"]).group(1)
    assert f'nonce="{nonce}"' in response.text


def test_enabled_auth_login_session_and_csrf(monkeypatch):
    _enable_auth(monkeypatch)

    async def scenario():
        transport = ASGITransport(app=server.app)
        async with AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=False
        ) as client:
            denied = await client.get("/")
            login_page = await client.get("/login")
            preauth_csrf = client.cookies[server.CSRF_COOKIE]
            logged_in = await client.post(
                "/login",
                data={
                    "username": "researcher",
                    "password": "correct horse battery staple",
                    "csrf_token": preauth_csrf,
                },
            )
            home = await client.get("/")
            blocked = await client.post("/chat", data={"message": "csrf should fail"})
            accepted = await client.post(
                "/chat",
                data={"message": "csrf should pass"},
                headers={"X-CSRF-Token": client.cookies[server.CSRF_COOKIE]},
            )
            return denied, login_page, logged_in, home, blocked, accepted

    denied, login_page, logged_in, home, blocked, accepted = asyncio.run(scenario())
    assert denied.status_code == 303
    assert denied.headers["location"] == "/login"
    assert login_page.status_code == 200
    assert "研究终端登录" in login_page.text
    assert logged_in.status_code == 303
    assert server.SESSION_COOKIE in logged_in.cookies
    assert home.status_code == 200
    assert "退出登录" in home.text
    assert blocked.status_code == 403
    assert accepted.status_code == 200
    login_events = [
        event
        for event in server._db.list_audit_events()
        if event["action"] == "POST /login" and event["outcome"] == "success"
    ]
    assert login_events[0]["actor"] == "researcher"


def test_failed_login_is_audited_without_raw_client_address(monkeypatch):
    _enable_auth(monkeypatch)

    async def scenario():
        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/login")
            return await client.post(
                "/login",
                data={
                    "username": "researcher",
                    "password": "wrong password",
                    "csrf_token": client.cookies[server.CSRF_COOKIE],
                },
            )

    response = asyncio.run(scenario())
    assert response.status_code == 401
    event = server._db.list_audit_events()[0]
    assert event["action"] == "POST /login"
    assert event["outcome"] == "denied"
    assert event["actor"] == "anonymous"
    assert event["client_hash"]
    assert "127.0.0.1" not in str(event)


def test_htmx_request_gets_login_redirect_header(monkeypatch):
    _enable_auth(monkeypatch)
    response = asyncio.run(_request("GET", "/sidebar?lang=en", headers={"HX-Request": "true"}))
    assert response.status_code == 401
    assert response.headers["HX-Redirect"] == "/login"


def test_login_rate_limit_returns_retry_after(monkeypatch):
    _enable_auth(monkeypatch)
    monkeypatch.setattr(server.SecurityConfig, "rate_limit_enabled", True)
    monkeypatch.setattr(server.SecurityConfig, "login_attempts_per_5_minutes", 1)

    async def scenario():
        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/login", data={})
            second = await client.post("/login", data={})
            return first, second

    first, second = asyncio.run(scenario())
    assert first.status_code == 422
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1


def test_healthz():
    response = asyncio.run(_request("GET", "/healthz"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0-rc.4"}


def test_main_page_uses_only_self_hosted_frontend_runtime_assets():
    response = asyncio.run(_request("GET", "/"))
    assert response.status_code == 200
    assert 'src="/static/vendor/htmx-1.9.12.min.js"' in response.text
    assert 'src="/static/vendor/marked-15.0.12.min.js"' in response.text
    assert 'src="/static/vendor/dompurify-3.4.15.min.js"' in response.text
    assert "unpkg.com" not in response.text
    assert "cdn.jsdelivr.net" not in response.text
    assert "fonts.googleapis.com" not in response.text


def test_content_security_policy_has_no_third_party_runtime_origins():
    response = asyncio.run(_request("GET", "/"))
    policy = response.headers["content-security-policy"]
    assert "script-src 'self'" in policy
    assert "style-src 'self'" in policy
    assert "font-src 'self'" in policy
    assert "unpkg.com" not in policy
    assert "cdn.jsdelivr.net" not in policy
    assert "googleapis.com" not in policy


def test_operations_metrics_are_aggregate_and_empty_by_default():
    response = asyncio.run(_request("GET", "/ops/metrics?hours=48"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["window_hours"] == 48
    assert payload["runs"] == 0
    assert payload["estimated_cost_usd"] is None


def test_operations_metrics_require_login_when_auth_is_enabled(monkeypatch):
    _enable_auth(monkeypatch)
    response = asyncio.run(_request("GET", "/ops/metrics"))
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_stats_smoke():
    response = asyncio.run(_request("GET", "/stats"))
    assert response.status_code == 200


def test_watchlist_toggle_persists_and_renders_official_timeline():
    async def scenario():
        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            empty = await client.get("/watchlist?lang=en")
            followed = await client.post(
                "/watchlist/台积电/toggle", data={"watched": "true", "lang": "en"}
            )
            reloaded = await client.get("/watchlist?lang=en")
            invalid = await client.post(
                "/watchlist/unknown/toggle", data={"watched": "true", "lang": "en"}
            )
            return empty, followed, reloaded, invalid

    empty, followed, reloaded, invalid = asyncio.run(scenario())
    assert "Select a company" in empty.text
    assert "TSMC 2026 Q2 results" in followed.text
    assert "TSMC 2Q26 Quarterly Results" in followed.text
    assert "TSMC 2026 Q2 results" in reloaded.text
    assert invalid.status_code == 404


def test_english_sidebar_smoke():
    response = asyncio.run(_request("GET", "/sidebar?lang=en"))
    assert response.status_code == 200
    assert "Knowledge Base" in response.text


def test_chat_history_persists_by_conversation_cookie():
    async def scenario():
        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            home = await client.get("/")
            assert "conversation_id" in client.cookies
            posted = await client.post("/chat", data={"message": "持久化测试"})
            reloaded = await client.get("/")
            return home, posted, reloaded

    _, posted, reloaded = asyncio.run(scenario())
    assert posted.status_code == 200
    assert "持久化测试" in reloaded.text
    assert server._db.count("messages") == 1


def test_completed_chat_persists_privacy_safe_run_telemetry(monkeypatch):
    class FakeProvider:
        model = "fake-model"

        @staticmethod
        def chat_with_tools(messages, tools, model=None, tool_choice="auto"):
            return {"tool_calls": None, "usage": {"prompt_tokens": 5, "completion_tokens": 1}}

        @staticmethod
        def chat_stream(messages, model=None):
            yield "grounded response"

    monkeypatch.setattr(server, "llm_available", lambda: True)
    monkeypatch.setattr(server, "get_llm", lambda: FakeProvider())

    async def scenario():
        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/")
            posted = await client.post("/chat", data={"message": "hello"})
            msg_id = re.search(r'data-stream-msg-id="([^"]+)"', posted.text).group(1)
            streamed = await client.get(f"/chat/stream/{msg_id}")
            metrics = await client.get("/ops/metrics")
            return streamed, metrics

    streamed, metrics = asyncio.run(scenario())
    assert '"done": true' in streamed.text
    payload = metrics.json()
    assert payload["runs"] == 1
    assert payload["statuses"] == {"success": 1}
    assert payload["tokens"]["prompt"] == 5
    assert payload["tokens"]["completion"] == 1
    assert payload["tokens"]["cache_miss"] == 5


def test_separate_clients_get_separate_conversations():
    async def scenario():
        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://test") as first:
            await first.get("/")
            first_id = first.cookies["conversation_id"]
        async with AsyncClient(transport=transport, base_url="http://test") as second:
            await second.get("/")
            second_id = second.cookies["conversation_id"]
        return first_id, second_id

    first_id, second_id = asyncio.run(scenario())
    assert first_id != second_id


def test_conversation_create_rename_switch_and_archive():
    async def scenario():
        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/")
            first_id = client.cookies["conversation_id"]
            await client.post("/chat", data={"message": "First research"})

            created = await client.post("/conversations/new")
            second_id = client.cookies["conversation_id"]
            renamed = await client.post(
                f"/conversations/{second_id}/rename", data={"title": "SMIC margins"}
            )
            selected = await client.post(f"/conversations/{first_id}/select")
            archived = await client.post(f"/conversations/{first_id}/archive")
            restored = await client.post(f"/conversations/{first_id}/restore")
            return (
                first_id,
                second_id,
                created,
                renamed,
                selected,
                archived,
                restored,
                client.cookies,
            )

    first_id, second_id, created, renamed, selected, archived, restored, cookies = asyncio.run(
        scenario()
    )
    assert first_id != second_id
    assert created.status_code == 200
    assert renamed.status_code == 200
    assert "SMIC margins" in renamed.text
    assert "First research" in selected.text
    assert archived.status_code == 200
    assert restored.status_code == 200
    assert cookies["conversation_id"] == first_id
    assert server._db.conversation_exists(first_id) is True


def test_current_conversation_markdown_and_pdf_exports():
    async def scenario():
        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/")
            conversation_id = client.cookies["conversation_id"]
            server._db.add_message(conversation_id, "user", "Quarterly export")
            server._db.add_message(
                conversation_id,
                "assistant",
                "| Metric | Value |\n| --- | ---: |\n| Revenue | 33.7 |",
                citations=[
                    {
                        "icon": "WEB",
                        "display_source": "TSMC Results",
                        "url": "https://investor.tsmc.com/",
                        "source_type": "web",
                    }
                ],
            )
            markdown = await client.get("/exports/current.md")
            pdf = await client.get("/exports/current.pdf")
            return markdown, pdf

    markdown, pdf = asyncio.run(scenario())
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert "attachment;" in markdown.headers["content-disposition"]
    assert "Quarterly export" in markdown.text
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


def test_current_export_requires_a_selected_conversation():
    response = asyncio.run(_request("GET", "/exports/current.md"))
    assert response.status_code == 404


def test_pdf_upload_persists_document_and_exact_page_chunks(tmp_path, monkeypatch):
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "TSMC first page revenue")
    pdf.new_page().insert_text((72, 72), "TSMC second page margin")
    payload = pdf.tobytes()
    pdf.close()

    indexed = []

    class FakeVectorStore:
        def add_chunks(self, chunks):
            indexed.extend(chunks)
            return len(chunks)

    monkeypatch.setattr(server, "PDF_DIR", tmp_path / "pdfs")
    monkeypatch.setattr("src.vector_store.VectorStore", FakeVectorStore)

    response = asyncio.run(
        _request(
            "POST",
            "/upload",
            files={"file": ("TSMC 2025.PDF", io.BytesIO(payload), "application/pdf")},
        )
    )
    assert response.status_code == 200
    assert server._db.count("documents") == 1
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        jobs = server._db.list_jobs(job_type="pdf_ingest")
        if jobs and jobs[0]["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.02)
    assert jobs[0]["status"] == "succeeded"
    assert server._db.count("chunks") >= 2
    assert {chunk.page for chunk in indexed} == {1, 2}
    assert all(chunk.chunk_id.startswith("chk_") for chunk in indexed)

    job_response = asyncio.run(_request("GET", f"/jobs/{jobs[0]['id']}"))
    assert job_response.json()["stage"] == "completed"
    assert job_response.json()["progress"] == 100


def test_pdf_upload_returns_after_persisting_background_job(tmp_path, monkeypatch):
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Queued report")
    payload = pdf.tobytes()
    pdf.close()

    class SleepingWorker:
        awakened = False

        def wake(self):
            self.awakened = True

        def stop(self):
            pass

    worker = SleepingWorker()
    monkeypatch.setattr(server, "PDF_DIR", tmp_path / "pdfs")
    monkeypatch.setattr(server, "_ingestion_worker", worker)

    response = asyncio.run(
        _request(
            "POST",
            "/upload",
            files={"file": ("queued.pdf", io.BytesIO(payload), "application/pdf")},
        )
    )

    assert response.status_code == 200
    assert worker.awakened is True
    assert server._db.list_documents()[0]["parse_status"] == "pending"
    job = server._db.list_jobs(job_type="pdf_ingest")[0]
    assert job["status"] == "pending"
    assert job["result"] == {"stage": "queued", "progress": 0}
    assert 'data-job-active="true"' in response.text


def test_pdf_upload_rejects_spoofed_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "PDF_DIR", tmp_path / "pdfs")
    response = asyncio.run(
        _request(
            "POST",
            "/upload",
            files={"file": ("not-really.pdf", b"plain text", "application/pdf")},
        )
    )
    assert response.status_code == 200
    assert "invalid PDF signature" in response.text
    assert server._db.count("documents") == 0


def test_chat_rejects_oversized_input():
    response = asyncio.run(_request("POST", "/chat", data={"message": "x" * 4001}))
    assert response.status_code == 422


def test_chat_rejects_whitespace_only_input():
    response = asyncio.run(_request("POST", "/chat", data={"message": "   "}))
    assert response.status_code == 400
