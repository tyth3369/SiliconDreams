import asyncio
import io

import pymupdf
import pytest
from httpx import ASGITransport, AsyncClient

import server
from src.storage import Database


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_db", Database(tmp_path / "server-test.db"))
    server._pending_agent_configs.clear()


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
    assert response.json() == {"status": "ok", "version": "0.8.0-dev.1"}


def test_stats_smoke():
    response = asyncio.run(_request("GET", "/stats"))
    assert response.status_code == 200


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
    assert server._db.count("chunks") >= 2
    assert {chunk.page for chunk in indexed} == {1, 2}
    assert all(chunk.chunk_id.startswith("chk_") for chunk in indexed)


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
