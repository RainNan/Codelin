import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import Base, User, Workspace, ChatSession, Message, ToolInvocation, CodeChunk
from app.db.session import get_db
from app.api.auth import create_token
from test_chat_stream import modules


@pytest_asyncio.fixture
async def api_client(modules, tmp_path, monkeypatch):
    _, main = modules
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([User(id="user-a", username="a", password_hash="unused"), User(id="user-b", username="b", password_hash="unused")])
        db.commit()
    def dependency():
        with factory() as db:
            yield db
    main.app.dependency_overrides[get_db] = dependency
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "file_lock_root", str(tmp_path / "locks"))
    headers = {"Authorization": f"Bearer {create_token('user-a')}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test", headers=headers) as client:
        yield client, factory, {"Authorization": f"Bearer {create_token('user-b')}"}
    main.app.dependency_overrides.clear()
    engine.dispose()


async def workspace(client):
    response = await client.post("/api/workspaces", json={"name": "项目 A"})
    assert response.status_code == 201
    assert "root_path" not in response.json()
    return response.json()["id"]


@pytest.mark.asyncio
async def test_workspaces_files_and_save_conflicts(api_client):
    client, _, _ = api_client
    wid = await workspace(client)
    prefix = f"/api/workspaces/{wid}"
    assert (await client.post(prefix + "/entries", json={"path": "src", "type": "directory"})).status_code == 201
    assert (await client.post(prefix + "/entries", json={"path": "src/main.py", "type": "file", "content": "你好\r\n"})).status_code == 201
    assert (await client.get(prefix + "/files", params={"path": "src"})).json()["entries"][0]["name"] == "main.py"
    read = await client.get(prefix + "/file", params={"path": "src/main.py"})
    assert read.json()["content"] == "你好\r\n"
    assert read.headers["etag"] == '"' + read.json()["version"] + '"'
    body = {"path": "src/main.py", "content": "new", "version": read.json()["version"]}
    assert (await client.put(prefix + "/file", json=body)).status_code == 200
    assert (await client.put(prefix + "/file", json=body)).status_code == 409
    assert (await client.put(prefix + "/file", json={"path": "src/main.py", "content": "new"})).status_code == 422


@pytest.mark.asyncio
async def test_another_user_cannot_list_read_write_or_bind_workspace(api_client):
    client, _, other = api_client
    wid = await workspace(client)
    prefix = f"/api/workspaces/{wid}"
    assert (await client.get("/api/workspaces", headers=other)).json() == []
    for method, path, kwargs in [
        ("GET", prefix, {}), ("GET", prefix + "/files", {}),
        ("GET", prefix + "/file?path=x", {}),
        ("PUT", prefix + "/file", {"json": {"path": "x", "content": "bad", "version": "0" * 64}}),
        ("POST", prefix + "/entries", {"json": {"path": "x", "type": "file"}}),
        ("POST", "/api/sessions", {"json": {"workspace_id": wid}}),
        ("GET", "/api/sessions?workspace_id=" + wid, {}),
    ]:
        assert (await client.request(method, path, headers=other, **kwargs)).status_code == 404


@pytest.mark.asyncio
async def test_workspace_shared_by_chats_and_retained_after_chat_deletion(api_client):
    client, factory, _ = api_client
    wid = await workspace(client)
    chats = [(await client.post("/api/sessions", json={"workspace_id": wid})).json() for _ in range(2)]
    assert len((await client.get("/api/sessions", params={"workspace_id": wid})).json()) == 2
    with factory() as db:
        assert all(db.get(ChatSession, chat["id"]).workspace_id == wid for chat in chats)
        db.add(Message(session_id=chats[0]["id"], role="user", content="hello"))
        db.add(ToolInvocation(session_id=chats[0]["id"], call_id="c", tool="read_file", args={}, ok=True, duration_ms=1))
        db.commit()
    await client.post(f"/api/workspaces/{wid}/entries", json={"path": "keep.txt", "type": "file", "content": "keep"})
    assert (await client.delete("/api/sessions/" + chats[0]["id"])).status_code == 200
    assert (await client.get(f"/api/workspaces/{wid}/file", params={"path": "keep.txt"})).json()["content"] == "keep"
    with factory() as db:
        assert db.get(Workspace, wid) is not None
        assert db.query(Message).count() == 0 and db.query(ToolInvocation).count() == 0


@pytest.mark.asyncio
async def test_empty_body_creates_independent_session_and_file_errors(api_client):
    client, _, _ = api_client
    response = await client.post("/api/sessions")
    assert response.status_code == 200 and response.json()["workspace_id"] is None
    assert (await client.get("/api/workspaces")).json() == []
    wid = await workspace(client)
    prefix = f"/api/workspaces/{wid}"
    assert (await client.get(prefix + "/files")).json()["entries"] == []
    assert (await client.get(prefix + "/file", params={"path": "../outside"})).status_code == 403
    assert (await client.get(prefix + "/file", params={"path": "missing"})).status_code == 404
    assert (await client.get(prefix + "/files", params={"limit": 1000})).status_code == 422
    assert (await client.post("/api/workspaces", json={"name": "   "})).status_code == 422


@pytest.mark.asyncio
async def test_chat_uses_workspace_root(api_client, modules, monkeypatch):
    client, factory, _ = api_client
    runner, main = modules
    wid = await workspace(client)
    sid = (await client.post("/api/sessions", json={"workspace_id": wid})).json()["id"]
    with factory() as db:
        assert not hasattr(db.get(ChatSession, sid), "workspace_path")
        correct_root = db.get(Workspace, wid).root_path
        db.commit()
    calls = []
    async def fake_events(thread_id, workspace, message, session_id, *, workspace_id, **kwargs):
        calls.append((workspace, workspace_id))
        yield 'event: done\ndata: {"elapsed_ms": 1}\n\n'
    monkeypatch.setattr(main, "sse_events", fake_events)
    monkeypatch.setattr(main, "check_rate_limit", lambda uid: None)
    async def empty_state(config):
        from types import SimpleNamespace
        return SimpleNamespace(next=(), tasks=())
    monkeypatch.setattr(runner.graph_mod.graph, "aget_state", empty_state)
    assert (await client.post("/api/chat", json={"session_id": sid, "message": "hello"})).status_code == 200
    assert calls == [(correct_root, wid)]
