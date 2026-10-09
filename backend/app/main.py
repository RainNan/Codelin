"""M5 版入口：认证 + 会话 + Postgres Checkpoint + 限流。"""
import json
import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from app.agents import graph as graph_mod
from app.agents.runner import resume_events, sse_events
from app.api import auth, sessions, workspaces, files
from app.api.workspaces import owned_workspace
from app.db.migrate import upgrade_database
from app.files.service import FileError
from app.api.auth import current_user
from app.api.ratelimit import check_rate_limit
from app.config import settings
from app.db.models import ChatSession, Message, User
from app.db.session import get_db
from app.llm.titles import DEFAULT_TITLE, start_title_task, stop_title_tasks


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(upgrade_database)
    # 2) LangGraph Checkpoint 换 PostgreSQL：进程重启会话不丢
    from app.agents.checkpoints import ThreadedPostgresSaver
    async with ThreadedPostgresSaver.open(settings.checkpoint_db_url) as cp:
        await asyncio.to_thread(cp.setup)  # 首次自动建 checkpoints 相关表
        graph_mod.graph = graph_mod.build_graph(cp)
        try:
            yield
        finally:
            await stop_title_tasks()
    # 退出时自动清理 checkpoint 连接


app = FastAPI(title="Codelin", version="0.5.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(workspaces.router)
app.include_router(files.router)


@app.exception_handler(FileError)
async def file_error_handler(request, error: FileError):
    return JSONResponse(status_code=error.status, content={"detail": str(error)})


async def persisted_stream(events, sid: str, db: Session, title_pending: bool = False):
    """Persist normal and resumed assistant text using the same SSE wrapper."""
    final_text = []
    if title_pending:
        yield 'event: session_title_pending\ndata: ' + json.dumps({"session_id": sid, "title": DEFAULT_TITLE}) + '\n\n'
    async for event in events:
        if event.startswith("event: token"):
            final_text.append(json.loads(event.split("data: ", 1)[1])["content"])
        yield event
    if final_text:
        db.add(Message(session_id=sid, role="assistant", content="".join(final_text)))
        db.commit()


class ChatIn(BaseModel):
    session_id: str
    message: str


class ApproveIn(BaseModel):
    session_id: str
    approved: bool


@app.post("/api/chat")
async def chat(
        body: ChatIn,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
):
    check_rate_limit(user.id)
    s = db.get(ChatSession, body.session_id)
    if not s or s.user_id != user.id:
        raise HTTPException(404, "会话不存在")
    workspace = owned_workspace(db, user.id, s.workspace_id)
    first_message = db.query(Message.id).filter_by(session_id=s.id, role="user").first() is None
    title_pending = first_message and s.title == DEFAULT_TITLE and bool(body.message.strip())
    message = Message(session_id=s.id, role="user", content=body.message)
    db.add(message)
    db.commit()
    if title_pending:
        # Never hand the request-scoped Session to an asynchronous background task.
        factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
        start_title_task(factory, s.id, user.id, message.id, body.message)

    events = sse_events(s.id, workspace.root_path, body.message, session_id=s.id, workspace_id=workspace.id)
    return StreamingResponse(persisted_stream(events, s.id, db, title_pending), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/chat/approve")
async def approve(body: ApproveIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    s = db.get(ChatSession, body.session_id)
    if not s or s.user_id != user.id:
        raise HTTPException(404)
    workspace = owned_workspace(db, user.id, s.workspace_id)
    events = resume_events(body.session_id, body.approved, workspace_id=workspace.id)
    return StreamingResponse(persisted_stream(events, s.id, db),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/sessions/{sid}/messages")
def get_messages(sid: str, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    s = db.get(ChatSession, sid)
    if not s or s.user_id != user.id:
        raise HTTPException(404)
    rows = db.query(Message).filter_by(session_id=sid).order_by(Message.id).all()
    return [{"role": m.role, "content": m.content, "created_at": str(m.created_at)}
            for m in rows]
