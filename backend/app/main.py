"""M5 版入口：认证 + 会话 + Postgres Checkpoint + 限流。"""
import json
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents import graph as graph_mod
from app.agents.runner import resume_events, sse_events
from app.api import auth, sessions
from app.api.auth import current_user
from app.api.ratelimit import check_rate_limit
from app.config import settings
from app.db.models import ChatSession, Message, ToolInvocation, User
from app.db.models import Base
from app.db.session import engine, get_db
from sqlalchemy import text


@asynccontextmanager
async def lifespan(app: FastAPI):
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    # 1) 业务表（开发期 create_all；生产应使用 Alembic 迁移——面试点）
    await asyncio.to_thread(Base.metadata.create_all, engine)
    # 2) LangGraph Checkpoint 换 PostgreSQL：进程重启会话不丢
    from app.agents.checkpoints import ThreadedPostgresSaver
    async with ThreadedPostgresSaver.open(settings.checkpoint_db_url) as cp:
        await asyncio.to_thread(cp.setup)  # 首次自动建 checkpoints 相关表
        graph_mod.graph = graph_mod.build_graph(cp)
        yield
    # 退出时自动清理 checkpoint 连接


app = FastAPI(title="Codelin", version="0.5.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(sessions.router)


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
    db.add(Message(session_id=s.id, role="user", content=body.message))
    db.commit()

    async def stream():
        final_text: list[str] = []
        async for ev in sse_events(s.id, s.workspace_path, body.message):
            if ev.startswith('event: token'):
                final_text.append(json.loads(ev.split("data: ", 1)[1])["content"])
            yield ev
        db.add(Message(session_id=s.id, role="assistant",
                       content="".join(final_text)))
        db.commit()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/chat/approve")
async def approve(body: ApproveIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    s = db.get(ChatSession, body.session_id)
    if not s or s.user_id != user.id:
        raise HTTPException(404)
    return StreamingResponse(resume_events(body.session_id, body.approved),
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
