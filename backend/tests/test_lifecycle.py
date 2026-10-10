from contextlib import contextmanager
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.exc import IntegrityError

from app.db.models import ChatSession, CodeChunk, Message, ToolInvocation, Workspace
from app.files.service import FileError
from app.operations import operation
from test_chat_stream import modules
from test_workspaces_api import api_client, workspace


@pytest.mark.asyncio
async def test_create_filter_rename_and_one_way_join(api_client):
    client, factory, other = api_client
    outside = (await client.post("/api/sessions", json={"workspace_id": None, "title": "  讨论  "})).json()
    assert outside["workspace_id"] is None and outside["title"] == "讨论"
    wid = await workspace(client)
    another = await workspace(client)
    inside = (await client.post("/api/sessions", json={"workspace_id": wid})).json()
    assert len((await client.get("/api/sessions")).json()) == 2
    assert [r["id"] for r in (await client.get("/api/sessions?standalone=true")).json()] == [outside["id"]]
    assert [r["id"] for r in (await client.get(f"/api/sessions?workspace_id={wid}")).json()] == [inside["id"]]
    assert (await client.get(f"/api/sessions?workspace_id={wid}&standalone=true")).status_code == 422
    sid = outside["id"]
    with factory() as db:
        db.add(Message(session_id=sid, role="user", content="保留历史"))
        db.commit()
    joined = await client.patch(f"/api/sessions/{sid}", json={"workspace_id": wid, "title": "  新标题  "})
    assert joined.status_code == 200 and joined.json()["title"] == "新标题"
    assert (await client.patch(f"/api/sessions/{sid}", json={"workspace_id": wid})).status_code == 200
    for destination in (None, another):
        assert (await client.patch(f"/api/sessions/{sid}", json={"workspace_id": destination})).status_code == 409
    assert (await client.get(f"/api/sessions/{sid}/messages")).json()[0]["content"] == "保留历史"
    assert (await client.patch(f"/api/workspaces/{wid}", json={"name": "  新名字  "})).json()["name"] == "新名字"
    for path, body in [(f"/api/sessions/{sid}", {"title": " "}), (f"/api/workspaces/{wid}", {"name": " "})]:
        assert (await client.patch(path, json=body)).status_code == 422
        assert (await client.patch(path, json=body, headers=other)).status_code == 404
        assert (await client.delete(path, headers=other)).status_code == 404
    foreign = (await client.post("/api/workspaces", headers=other, json={"name": "other"})).json()["id"]
    new = (await client.post("/api/sessions")).json()["id"]
    assert (await client.patch(f"/api/sessions/{new}", json={"workspace_id": foreign})).status_code == 404
    with factory() as db:
        db.get(ChatSession, new).workspace_id = foreign
        with pytest.raises(IntegrityError):
            db.commit()


def install_model(modules, monkeypatch):
    runner, main = modules
    class Model:
        async def ainvoke(self, messages):
            last = messages[-1]
            if isinstance(last, HumanMessage) and last.content in ("build", "danger"):
                tool = {"id": "call-1", "name": "write_file", "args": {"path": "main.py", "content": "print('ok')\n"}}
                if last.content == "danger":
                    tool = {"id": "cmd-1", "name": "run_command", "args": {"command": "pip install example"}}
                return AIMessage(content="", tool_calls=[tool])
            return AIMessage(content="回答完成")
    monkeypatch.setattr(runner.graph_mod, "_llm_with_tools", Model())
    graph = runner.graph_mod.build_graph(InMemorySaver())
    monkeypatch.setattr(runner.graph_mod, "graph", graph)
    monkeypatch.setattr(main, "check_rate_limit", lambda uid: None)
    return graph


@pytest.mark.asyncio
async def test_agent_allocates_once_and_preserves_history(api_client, modules, monkeypatch):
    client, factory, _ = api_client
    graph = install_model(modules, monkeypatch)
    sid = (await client.post("/api/sessions", json={"title": "自定义"})).json()["id"]
    response = await client.post("/api/chat", json={"session_id": sid, "message": "hello"})
    assert "event: done" in response.text and "workspace_created" not in response.text
    assert (await client.get("/api/workspaces")).json() == []
    response = await client.post("/api/chat", json={"session_id": sid, "message": "build"})
    assert "event: error" not in response.text
    assert response.text.count("event: workspace_created") == 1
    assert response.text.index("event: workspace_created") < response.text.index("event: file_changed")
    updated = (await client.get(f"/api/sessions/{sid}")).json()
    wid = updated["workspace_id"]
    assert updated["id"] == sid and updated["title"] == "自定义"
    assert (await client.get(f"/api/workspaces/{wid}/file?path=main.py")).json()["content"] == "print('ok')\n"
    second = await client.post("/api/chat", json={"session_id": sid, "message": "build"})
    assert "workspace_created" not in second.text
    assert len((await client.get("/api/workspaces")).json()) == 1
    state = await graph.aget_state({"configurable": {"thread_id": sid}})
    assert state.values["workspace_id"] == wid
    assert [message.content for message in state.values["messages"] if isinstance(message, HumanMessage)] == ["hello", "build", "build"]
    with factory() as db:
        assert db.query(Message).filter_by(session_id=sid, role="user").count() == 3


@pytest.mark.asyncio
async def test_workspace_failure_stops_tools_and_rolls_back(api_client, modules, monkeypatch):
    from sqlalchemy import event
    from app.config import settings
    client, factory, _ = api_client
    install_model(modules, monkeypatch)
    sid = (await client.post("/api/sessions", json={"title": "自定义"})).json()["id"]
    def fail(*args):
        raise RuntimeError("database allocation failed")
    event.listen(Workspace, "before_insert", fail)
    try:
        response = await client.post("/api/chat", json={"session_id": sid, "message": "build"})
    finally:
        event.remove(Workspace, "before_insert", fail)
    assert "event: error" in response.text and "event: file_changed" not in response.text
    assert (await client.get(f"/api/sessions/{sid}")).json()["workspace_id"] is None
    with factory() as db:
        assert db.query(Workspace).count() == 0
    assert not list(Path(settings.workspace_root).rglob("main.py"))
    assert not [p for p in (Path(settings.workspace_root) / "user-a").iterdir() if p.is_dir()]
    retry = await client.post("/api/chat", json={"session_id": sid, "message": "build"})
    assert "event: workspace_created" in retry.text and "event: error" not in retry.text


@pytest.mark.asyncio
async def test_approval_rejection_and_checkpoint_deletion(api_client, modules, monkeypatch):
    client, factory, _ = api_client
    graph = install_model(modules, monkeypatch)
    sid = (await client.post("/api/sessions", json={"title": "自定义"})).json()["id"]
    response = await client.post("/api/chat", json={"session_id": sid, "message": "danger"})
    assert "workspace_created" in response.text and "approval_required" in response.text
    assert (await client.post("/api/chat", json={"session_id": sid, "message": "hello"})).status_code == 409
    response = await client.post("/api/chat/approve", json={"session_id": sid, "approved": False})
    assert "event: done" in response.text and "event: error" not in response.text
    assert len((await client.get("/api/workspaces")).json()) == 1
    await client.post("/api/chat", json={"session_id": sid, "message": "danger"})
    assert (await client.delete(f"/api/sessions/{sid}")).status_code == 200
    state = await graph.aget_state({"configurable": {"thread_id": sid}})
    assert not state.values and not state.next
    assert (await client.post("/api/chat/approve", json={"session_id": sid, "approved": True})).status_code == 404


@pytest.mark.asyncio
async def test_shared_index_survives_session_delete_and_workspace_removes_all(api_client):
    client, factory, _ = api_client
    wid = await workspace(client)
    sessions = [(await client.post("/api/sessions", json={"workspace_id": wid})).json()["id"] for _ in range(2)]
    with factory() as db:
        root = Path(db.get(Workspace, wid).root_path)
        db.add(CodeChunk(workspace_id=wid, path="a.py", start_line=1, end_line=1, content="x"))
        for sid in sessions:
            db.add(Message(session_id=sid, role="user", content="hello"))
            db.add(ToolInvocation(session_id=sid, call_id="c", tool="read_file", args={}, ok=True, duration_ms=1))
        db.commit()
    (root / "a.py").write_text("x")
    assert (await client.delete(f"/api/sessions/{sessions[0]}")).status_code == 200
    with factory() as db:
        assert db.query(CodeChunk).count() == 1
    assert root.exists()
    assert (await client.delete(f"/api/workspaces/{wid}")).status_code == 200
    assert not root.exists()
    with factory() as db:
        assert all(db.query(model).count() == 0 for model in (Workspace, ChatSession, CodeChunk, Message, ToolInvocation))


@pytest.mark.asyncio
async def test_busy_operations_block_join_delete_and_file_access(api_client):
    client, _, _ = api_client
    wid = await workspace(client)
    sid = (await client.post("/api/sessions")).json()["id"]
    with operation(f"session:{sid}"):
        assert (await client.patch(f"/api/sessions/{sid}", json={"workspace_id": wid})).status_code == 409
        assert (await client.delete(f"/api/sessions/{sid}")).status_code == 409
    with operation(f"workspace:{wid}", "shared"):
        assert (await client.delete(f"/api/workspaces/{wid}")).status_code == 409
    with operation(f"workspace:{wid}"):
        assert (await client.get(f"/api/workspaces/{wid}/files")).status_code == 409


@pytest.mark.asyncio
async def test_failed_cleanup_is_retryable(api_client, monkeypatch):
    from app.api import workspaces
    client, factory, _ = api_client
    wid = await workspace(client)
    sid = (await client.post("/api/sessions", json={"workspace_id": wid})).json()["id"]
    original = workspaces.remove_workspace_files
    def fail(workspace):
        raise FileError(500, "disk busy")
    monkeypatch.setattr(workspaces, "remove_workspace_files", fail)
    response = await client.delete(f"/api/workspaces/{wid}")
    assert response.status_code == 500
    assert (await client.get(f"/api/workspaces/{wid}")).json()["deleting"] is True
    assert (await client.get(f"/api/workspaces/{wid}/files")).status_code == 409
    assert (await client.post("/api/sessions", json={"workspace_id": wid})).status_code == 409
    assert (await client.get(f"/api/sessions/{sid}")).status_code == 200
    monkeypatch.setattr(workspaces, "remove_workspace_files", original)
    assert (await client.delete(f"/api/workspaces/{wid}")).status_code == 200


@pytest.mark.asyncio
async def test_new_turn_closes_unanswered_tools_after_disconnect(api_client, modules, monkeypatch):
    from langchain_core.messages import ToolMessage
    client, _, _ = api_client
    graph = install_model(modules, monkeypatch)
    sid = (await client.post("/api/sessions", json={"title": "自定义"})).json()["id"]
    config = {"configurable": {"thread_id": sid}}
    await graph.aupdate_state(config, {"session_id": sid, "workspace": None, "workspace_id": None, "messages": [
        HumanMessage(content="build"), AIMessage(content="", tool_calls=[{"id": "interrupted", "name": "write_file", "args": {"path": "a.py", "content": "x"}}])
    ]}, as_node="agent")
    response = await client.post("/api/chat", json={"session_id": sid, "message": "hello"})
    assert response.status_code == 200 and "event: error" not in response.text
    snapshot = await graph.aget_state(config)
    assert any(isinstance(message, ToolMessage) and message.tool_call_id == "interrupted" for message in snapshot.values["messages"])
    assert (await client.get("/api/workspaces")).json() == []
