"""Exercise the HTTP stream boundary and checkpoint resume without external services."""
from importlib import import_module
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command


@pytest.fixture
def modules(monkeypatch):
    # Importing the graph should not require model credentials or call a model.
    from app.llm import provider

    class FakeModel:
        def bind_tools(self, tools):
            return self

    monkeypatch.setattr(provider, "get_llm", lambda: FakeModel())
    runner = import_module("app.agents.runner")
    main = import_module("app.main")
    return runner, main


@pytest.fixture
def endpoint(modules, monkeypatch):
    runner, main = modules
    calls = []

    class FakeGraph:
        async def astream(self, inputs, config, **kwargs):
            calls.append((inputs, config))
            yield "messages", (AIMessage(content="你好"), {"langgraph_node": "agent"})

        async def aget_state(self, config):
            return SimpleNamespace(next=(), tasks=())

    class FakeDB:
        def __init__(self):
            self.messages = []

        def get(self, model, sid):
            return SimpleNamespace(id=sid, user_id="user-1", workspace_id="workspace-1", workspace_path="test-workspace")

        def add(self, message):
            self.messages.append(message)

        def commit(self):
            pass

    db = FakeDB()
    monkeypatch.setattr(runner.graph_mod, "graph", FakeGraph())
    monkeypatch.setattr(main, "check_rate_limit", lambda uid: None)
    monkeypatch.setattr(main, "owned_workspace", lambda db, uid, wid: SimpleNamespace(id=wid, root_path="test-workspace"))
    main.app.dependency_overrides[main.current_user] = lambda: SimpleNamespace(id="user-1")
    main.app.dependency_overrides[main.get_db] = lambda: db
    try:
        yield main.app, calls, db
    finally:
        main.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_endpoint_passes_session_id_and_persists_reply(endpoint):
    app, calls, db = endpoint
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/chat", json={"session_id": "session-1", "message": "读代码"})
    assert response.status_code == 200
    assert "event: token" in response.text and "event: done" in response.text
    inputs, config = calls[0]
    assert inputs["session_id"] == "session-1"
    assert inputs["workspace_id"] == "workspace-1"
    assert inputs["workspace"] == "test-workspace"
    assert inputs["messages"][0].content == "读代码"
    assert config["configurable"]["thread_id"] == "session-1"
    assert [(m.role, m.content) for m in db.messages] == [("user", "读代码"), ("assistant", "你好")]


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
async def test_approval_endpoint_resumes_same_checkpoint(endpoint, approved):
    app, calls, db = endpoint
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/chat/approve", json={"session_id": "session-1", "approved": approved})
    assert response.status_code == 200
    assert "event: done" in response.text
    inputs, config = calls[0]
    assert isinstance(inputs, Command)
    assert inputs.resume == ("approved" if approved else "rejected")
    assert config["configurable"]["thread_id"] == "session-1"
    assert [(m.role, m.content) for m in db.messages] == [("assistant", "你好")]


@pytest.mark.asyncio
@pytest.mark.parametrize("path,success", [("src/new.py", True), ("../outside.py", False)])
async def test_file_events_only_follow_successful_agent_writes(modules, monkeypatch, tmp_path, path, success):
    runner, _ = modules
    from app.config import settings
    monkeypatch.setattr(settings, "file_lock_root", str(tmp_path / "locks"))
    root = tmp_path / "workspace"
    root.mkdir()

    class Model:
        async def ainvoke(self, messages):
            if len(messages) == 2:
                return AIMessage(content="", tool_calls=[{"id": "write-1", "name": "write_file", "args": {"path": path, "content": "print('hi')\n"}}])
            return AIMessage(content="done")

    from langgraph.checkpoint.memory import InMemorySaver
    monkeypatch.setattr(runner.graph_mod, "_llm_with_tools", Model())
    monkeypatch.setattr(runner.graph_mod, "graph", runner.graph_mod.build_graph(InMemorySaver()))
    events = [event async for event in runner.sse_events("sid", str(root), "write", session_id="sid", workspace_id="wid")]
    changes = [event for event in events if event.startswith("event: file_changed")]
    assert bool(changes) == success
    if success:
        import json
        from app.files.service import read_text
        change = json.loads(changes[0].split("data: ", 1)[1])
        assert change == {"workspace_id": "wid", "path": path, "operation": "created", "version": read_text(root, path)["version"]}
    else:
        assert not (tmp_path / "outside.py").exists()


@pytest.mark.asyncio
async def test_session_id_and_workspace_survive_actual_graph_approval(modules, monkeypatch, tmp_path):
    runner, _ = modules
    graph_module = runner.graph_mod

    class FakeModel:
        async def ainvoke(self, messages):
            if len(messages) == 2:
                return AIMessage(content="", tool_calls=[{"id": "command-1", "name": "run_command", "args": {"command": "pip install example"}}])
            return AIMessage(content="已拒绝命令")

    async def must_not_execute(*args, **kwargs):
        raise AssertionError("Rejected commands must not run")

    monkeypatch.setattr(graph_module, "_llm_with_tools", FakeModel())
    monkeypatch.setattr(graph_module.ops, "run_command", must_not_execute)
    from langgraph.checkpoint.memory import InMemorySaver
    graph = graph_module.build_graph(InMemorySaver())
    monkeypatch.setattr(graph_module, "graph", graph)
    initial = [event async for event in runner.sse_events("session-1", str(tmp_path), "安装依赖", session_id="session-1")]
    assert any("event: approval_required" in event for event in initial)
    resumed = [event async for event in runner.resume_events("session-1", False)]
    assert any("用户拒绝执行" in event for event in resumed)
    assert any("event: done" in event for event in resumed)
    snapshot = await graph.aget_state({"configurable": {"thread_id": "session-1"}})
    assert snapshot.values["session_id"] == "session-1"
    assert snapshot.values["workspace"] == str(tmp_path)
