"""Opt-in real PostgreSQL/checkpoint/Redis tests in disposable schemas."""
import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.initialize import initialize_database
from app.db.models import Base, ChatSession, CodeChunk, Message, Workspace
from app.operations import Lease, client as redis_client
from test_chat_stream import modules

pytestmark = [pytest.mark.infra, pytest.mark.skipif(os.environ.get("CODELIN_INFRA") != "1" or not os.environ.get("CODELIN_TEST_DATABASE_URL"), reason="Set CODELIN_INFRA=1 and CODELIN_TEST_DATABASE_URL to a disposable PostgreSQL database")]


@pytest_asyncio.fixture
async def infrastructure(modules, monkeypatch, tmp_path):
    runner, main = modules
    database_url = os.environ["CODELIN_TEST_DATABASE_URL"]
    name = "codelin_test_" + uuid.uuid4().hex
    admin = create_engine(database_url)
    with admin.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text(f'CREATE SCHEMA "{name}"'))
    engine = create_engine(database_url, connect_args={"options": f"-csearch_path={name},public"})
    try:
        Base.metadata.create_all(engine, checkfirst=False)
        initialize_database(engine)
        initialize_database(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        def dependency():
            with factory() as db:
                yield db
        main.app.dependency_overrides[main.get_db] = dependency
        monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
        monkeypatch.setattr(settings, "file_lock_root", str(tmp_path / "locks"))
        from app.agents.checkpoints import ThreadedPostgresSaver
        checkpoint_url = make_url(database_url).set(drivername="postgresql", query={"options": f"-csearch_path={name}"}).render_as_string(hide_password=False)
        async with ThreadedPostgresSaver.open(checkpoint_url) as saver:
            await asyncio.to_thread(saver.setup)
            monkeypatch.setattr(runner.graph_mod, "graph", runner.graph_mod.build_graph(saver))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
                registration = await client.post("/api/auth/register", json={"username": "verification", "password": "temporary-verification-password"})
                assert registration.status_code == 200
                client.headers["Authorization"] = "Bearer " + registration.json()["token"]
                yield client, factory, saver
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        admin.dispose()


def test_real_redis_shared_exclusive_cross_process_and_safe_release():
    resource = "verification:" + uuid.uuid4().hex
    first = Lease(resource, "shared").acquire()
    second = Lease(resource, "shared").acquire()
    try:
        with pytest.raises(HTTPException) as conflict:
            Lease(resource).acquire()
        assert conflict.value.status_code == 409
        script = "from app.operations import Lease; from fastapi import HTTPException\ntry: Lease(%r).acquire()\nexcept HTTPException as e: print(e.status_code)" % resource
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=15)
        assert result.returncode == 0 and result.stdout.strip() == "409"
        assert first.call(__import__('app.operations', fromlist=['_RENEW'])._RENEW) == 1
    finally:
        first.close(); second.close()
    writer = Lease(resource).acquire()
    try:
        with pytest.raises(HTTPException):
            Lease(resource, "shared").acquire()
        redis_client.set(writer.keys[0], "replacement-owner", px=60000)
    finally:
        writer.close()
    assert redis_client.get(writer.keys[0]) == b"replacement-owner"
    redis_client.delete(*writer.keys)


@pytest.mark.asyncio
async def test_postgres_shared_vector_index_restart_and_cascade(infrastructure, monkeypatch):
    from app.rag import service
    from app.rag.retrieval import bm25_store
    client, factory, saver = infrastructure
    first = (await client.post("/api/workspaces", json={"name": "project"})).json()["id"]
    second = (await client.post("/api/workspaces", json={"name": "other project"})).json()["id"]
    sessions = [(await client.post("/api/sessions", json={"workspace_id": first})).json()["id"] for _ in range(2)]
    with factory() as db:
        root = Path(db.get(Workspace, first).root_path)
        other_root = Path(db.get(Workspace, second).root_path)
    (root / "a.py").write_text("def shared_function():\n    return 42\n")
    (other_root / "secret.py").write_text("other_project_secret = 1\n")
    class Embedder:
        def embed_documents(self, contents):
            return [[1.0] + [0.0] * 1023 for content in contents]
        def embed_query(self, query):
            return [1.0] + [0.0] * 1023
    monkeypatch.setattr(service, "SessionLocal", factory)
    monkeypatch.setattr(service, "get_embedder", lambda: Embedder())
    service.index_workspace(first, root)
    service.index_workspace(second, other_root)
    bm25_store.drop(first)
    result = service.hybrid_search(first, "shared_function")
    assert "shared_function" in result and "other_project_secret" not in result
    with factory() as db:
        indexed_chunks = db.query(CodeChunk).filter_by(workspace_id=first).count()
        assert indexed_chunks > 0
    assert (await client.delete(f"/api/sessions/{sessions[0]}")).status_code == 200
    with factory() as db:
        assert db.query(CodeChunk).filter_by(workspace_id=first).count() == indexed_chunks
    (root / "a.py").unlink()
    service.index_workspace(first, root)
    with factory() as db:
        assert db.query(CodeChunk).filter_by(workspace_id=first).count() == 0
    assert (await client.delete(f"/api/workspaces/{first}")).status_code == 200
    assert not root.exists() and other_root.exists()


@pytest.mark.asyncio
async def test_real_checkpoint_agent_allocation_approval_and_deletion(infrastructure, modules, monkeypatch):
    client, factory, saver = infrastructure
    runner, main = modules
    class Model:
        async def ainvoke(self, messages):
            last = messages[-1]
            if isinstance(last, HumanMessage) and last.content == "build":
                return AIMessage(content="", tool_calls=[{"id": "write", "name": "write_file", "args": {"path": "a.py", "content": "x = 1\n"}}])
            if isinstance(last, HumanMessage) and last.content == "danger":
                return AIMessage(content="", tool_calls=[{"id": "command", "name": "run_command", "args": {"command": "pip install example"}}])
            return AIMessage(content="done")
    monkeypatch.setattr(runner.graph_mod, "_llm_with_tools", Model())
    sid = (await client.post("/api/sessions", json={"title": "verification"})).json()["id"]
    response = await client.post("/api/chat", json={"session_id": sid, "message": "plain"})
    assert "workspace_created" not in response.text and "event: error" not in response.text
    response = await client.post("/api/chat", json={"session_id": sid, "message": "build"})
    assert response.text.count("event: workspace_created") == 1 and "event: error" not in response.text
    assert await saver.aget_tuple({"configurable": {"thread_id": sid}}) is not None
    wid = (await client.get(f"/api/sessions/{sid}")).json()["workspace_id"]
    assert (await client.post("/api/chat", json={"session_id": sid, "message": "danger"})).text.count("approval_required") == 1
    response = await client.post("/api/chat/approve", json={"session_id": sid, "approved": False})
    assert "event: done" in response.text and "event: error" not in response.text
    assert (await client.delete(f"/api/workspaces/{wid}")).status_code == 200
    assert await saver.aget_tuple({"configurable": {"thread_id": sid}}) is None
    with factory() as db:
        assert db.query(ChatSession).count() == 0 and db.query(Message).count() == 0
