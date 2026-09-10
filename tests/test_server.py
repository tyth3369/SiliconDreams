import asyncio

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
