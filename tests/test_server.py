import asyncio
import io
import time

import pymupdf
import pytest
from httpx import ASGITransport, AsyncClient

import server
from src.storage import Database


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    server._ingestion_worker.stop()
    monkeypatch.setattr(server, "_db", Database(tmp_path / "server-test.db"))
    server._pending_agent_configs.clear()
    yield
    server._ingestion_worker.stop()


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


def test_healthz():
    response = asyncio.run(_request("GET", "/healthz"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.9.0-dev.5"}


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
