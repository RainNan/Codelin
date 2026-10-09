import asyncio
from types import SimpleNamespace

import pytest

from app.db.models import ChatSession, Message
from app.llm import titles
from test_chat_stream import modules
from test_workspaces_api import api_client


async def new_session(client, factory, title="新会话"):
    session = (await client.post("/api/sessions", json={"title": title})).json()
    with factory() as db:
        message = Message(session_id=session["id"], role="user", content="帮我实现登录功能")
        db.add(message)
        db.commit()
        return session["id"], message.id


@pytest.mark.asyncio
async def test_title_normalizes_model_output_and_limits_input(monkeypatch):
    seen = []
    class Model:
        async def ainvoke(self, messages):
            seen.extend(messages)
            return SimpleNamespace(content=[{"type": "text", "text": '标题：“实现登录功能”\n这里是解释'}])
    monkeypatch.setattr(titles.provider, "get_llm", lambda: Model())
    assert await titles.generate_title("x" * 6000) == "实现登录功能"
    assert len(seen[1].content) == 4000


@pytest.mark.asyncio
async def test_title_persists_and_remains_owner_only(api_client, monkeypatch):
    client, factory, other = api_client
    sid, mid = await new_session(client, factory)
    async def generate(message):
        assert message == "帮我实现登录功能"
        return "实现登录功能"
    monkeypatch.setattr(titles, "generate_title", generate)
    await titles.update_title(factory, sid, "user-a", mid, "帮我实现登录功能")
    assert (await client.get(f"/api/sessions/{sid}")).json()["title"] == "实现登录功能"
    assert (await client.get(f"/api/sessions/{sid}", headers=other)).status_code == 404


@pytest.mark.asyncio
async def test_only_first_message_and_default_title_generate(api_client, monkeypatch):
    client, factory, _ = api_client
    calls = []
    async def generate(message):
        calls.append(message)
        return "自动标题"
    monkeypatch.setattr(titles, "generate_title", generate)
    custom_sid, mid = await new_session(client, factory, "我的项目")
    await titles.update_title(factory, custom_sid, "user-a", mid, "first")
    sid, first_id = await new_session(client, factory)
    with factory() as db:
        second = Message(session_id=sid, role="user", content="第二次消息")
        db.add(second)
        db.commit()
        second_id = second.id
    await titles.update_title(factory, sid, "user-a", second_id, "second")
    await titles.update_title(factory, sid, "user-b", first_id, "wrong user")
    assert calls == []
    assert (await client.get(f"/api/sessions/{custom_sid}")).json()["title"] == "我的项目"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["rename", "delete"])
async def test_inflight_title_never_overwrites_user_change(api_client, monkeypatch, change):
    client, factory, _ = api_client
    sid, mid = await new_session(client, factory)
    async def generate(message):
        if change == "delete":
            await client.delete(f"/api/sessions/{sid}")
        else:
            with factory() as db:
                db.get(ChatSession, sid).title = "手动命名"
                db.commit()
        return "自动标题"
    monkeypatch.setattr(titles, "generate_title", generate)
    await titles.update_title(factory, sid, "user-a", mid, "first")
    response = await client.get(f"/api/sessions/{sid}")
    if change == "delete":
        assert response.status_code == 404
    else:
        assert response.json()["title"] == "手动命名"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "empty", "provider"])
async def test_model_failure_preserves_temporary_title(api_client, monkeypatch, failure):
    client, factory, _ = api_client
    sid, mid = await new_session(client, factory)
    class Model:
        async def ainvoke(self, messages):
            if failure == "timeout":
                await asyncio.sleep(1)
            if failure == "provider":
                raise RuntimeError("model unavailable")
            return SimpleNamespace(content="")
    monkeypatch.setattr(titles.provider, "get_llm", lambda: Model())
    monkeypatch.setattr(titles.settings, "title_timeout_seconds", .01)
    await titles.update_title(factory, sid, "user-a", mid, "first")
    assert (await client.get(f"/api/sessions/{sid}")).json()["title"] == "新会话"


@pytest.mark.asyncio
async def test_chat_starts_title_without_waiting_and_only_once(api_client, monkeypatch):
    from app import main
    client, factory, _ = api_client
    session = (await client.post("/api/sessions")).json()
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def generate(message):
        calls.append(message)
        started.set()
        await release.wait()
        return "实现登录功能"
    async def events(*args, **kwargs):
        yield 'event: token\ndata: {"content": "正文回复"}\n\n'
        yield 'event: done\ndata: {}\n\n'
    monkeypatch.setattr(titles, "generate_title", generate)
    monkeypatch.setattr(main, "check_rate_limit", lambda uid: None)
    monkeypatch.setattr(main, "sse_events", events)
    try:
        response = await asyncio.wait_for(client.post("/api/chat", json={"session_id": session["id"], "message": "first"}), 2)
        await asyncio.wait_for(started.wait(), 2)
        assert not release.is_set()
        assert "session_title_pending" in response.text and "正文回复" in response.text
        second = await client.post("/api/chat", json={"session_id": session["id"], "message": "second"})
        assert "session_title_pending" not in second.text
        release.set()
        await asyncio.gather(*list(titles._tasks))
        assert calls == ["first"]
        assert (await client.get(f'/api/sessions/{session["id"]}')).json()["title"] == "实现登录功能"
    finally:
        release.set()
        await titles.stop_title_tasks()
