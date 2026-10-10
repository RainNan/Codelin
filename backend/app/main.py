"""M5 版入口：认证 + 会话 + Postgres Checkpoint + 限流。"""
import json
import asyncio
from functools import partial
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker
from starlette.background import BackgroundTask

from app.agents import graph as graph_mod
from app.agents.runner import resume_events, sse_events
from app.api import auth, sessions, workspaces, files
from app.api.workspaces import owned_workspace
from app.db.initialize import initialize_database
from app.lifecycle import owned_session, prepare_agent_workspace
from app.operations import Operation
from app.files.service import FileError
from app.api.auth import current_user
from app.api.ratelimit import check_rate_limit
from app.config import settings
from app.db.models import ChatSession, Message, User
from app.db.session import get_db
from app.llm.titles import DEFAULT_TITLE, start_title_task, stop_title_tasks


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(initialize_database)
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


app = FastAPI(title="Codelin", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(workspaces.router)
app.include_router(files.router)


@app.exception_handler(FileError)
async def file_error_handler(request, error: FileError):
    return JSONResponse(status_code=error.status, content={"detail": str(error)})


async def persisted_stream(
        events,
        sid: str,
        db: Session,
        title_pending: bool = False,
):
    """
    包装 SSE 事件流，结束后将收集到的文本保存到消息表。

    参数：
        events:
            上游异步事件流，每次产生一个已经格式化好的 SSE 字符串。
            其中可能包含 token、工具调用、审批提示、完成或错误事件。
        sid:
            当前聊天会话的 ID，用于关联保存的助手消息。
        db:
            本次请求使用的数据库 Session。
        title_pending:
            通知前端标题正在后台生成，可用于前端显示
    """
    final_text = []

    if title_pending:
        yield (
                "event: session_title_pending\ndata: "
                + json.dumps({
            "session_id": sid,
            "title": DEFAULT_TITLE,
        })
                + "\n\n"
        )

    async for event in events:
        if event.startswith("event: token"):
            # 示例：
            # event: token
            # data: {"content": "你好"}
            final_text.append(
                json.loads(event.split("data: ", 1)[1])["content"]
            )

        yield event

    if final_text:
        db.add(
            Message(
                session_id=sid,
                role="assistant",
                content="".join(final_text),
            )
        )
        db.commit()


async def guarded_stream(events, sid, db, guard, title_pending=False):
    try:
        async for event in persisted_stream(events, sid, db, title_pending):
            guard.check()
            yield event
    finally:
        guard.close()


def chat_context(db, uid, sid):
    owned_session(db, uid, sid)
    guard = Operation()
    try:
        guard.acquire(f"session:{sid}")
        db.expire_all()
        session = owned_session(db, uid, sid)
        workspace = None
        if session.workspace_id:
            guard.acquire(f"workspace:{session.workspace_id}", "shared")
            workspace = owned_workspace(db, uid, session.workspace_id)
        factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
        prepare = partial(prepare_agent_workspace, factory, uid, sid, guard)
        return session, workspace, factory, prepare, guard
    except BaseException:
        guard.close()
        raise


class ChatIn(BaseModel):
    session_id: str
    message: str


@app.post("/api/chat")
async def chat(
        body: ChatIn,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
):
    check_rate_limit(user.id)
    s, workspace, factory, prepare, guard = chat_context(db, user.id, body.session_id)
    try:
        return await start_chat(body, user, db, s, workspace, factory, prepare, guard)
    except BaseException:
        guard.close()
        raise


async def start_chat(body, user, db, s, workspace, factory, prepare, guard):
    snapshot = await graph_mod.graph.aget_state({"configurable": {"thread_id": s.id}})
    if snapshot.next == ("approve",):
        raise HTTPException(409, "请先批准或拒绝待审批的操作")
    # 未命名的对话可重试失败的标题任务，始终概括最早的用户消息。
    needs_title = (
            s.title == DEFAULT_TITLE
            and getattr(s, "auto_title", True)
            and bool(body.message.strip())
    )

    message = Message(session_id=s.id, role="user", content=body.message)
    db.add(message)
    db.commit()
    title_pending = False
    if needs_title:
        # Never hand the request-scoped Session to an asynchronous background task.
        first = db.query(Message).filter_by(session_id=s.id, role="user").order_by(Message.id).first()
        title_pending = start_title_task(factory, s.id, user.id, first.id, first.content)

    events = sse_events(s.id, workspace.root_path if workspace else None, body.message, session_id=s.id,
                        workspace_id=workspace.id if workspace else None, prepare_workspace=prepare, operation=guard)
    return StreamingResponse(
        guarded_stream(events, s.id, db, guard, title_pending),
        background=BackgroundTask(guard.close),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


class ApproveIn(BaseModel):
    session_id: str
    approved: bool


@app.post("/api/chat/approve")
async def approve(
        body: ApproveIn,
        user: User = Depends(current_user),
        db: Session = Depends(get_db)
):
    s, workspace, factory, prepare, guard = chat_context(db, user.id, body.session_id)
    try:
        snapshot = await graph_mod.graph.aget_state({"configurable": {"thread_id": s.id}})
        if snapshot.next != ("approve",) or not workspace:
            raise HTTPException(409, "当前对话没有待审批操作")
    except BaseException:
        guard.close()
        raise
    events = resume_events(body.session_id, body.approved, workspace_id=workspace.id,
                           prepare_workspace=prepare, operation=guard)
    return StreamingResponse(
        guarded_stream(events, s.id, db, guard),
        background=BackgroundTask(guard.close),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/api/sessions/{sid}/messages")
def get_messages(
        sid: str,
        user: User = Depends(current_user),
        db: Session = Depends(get_db)
):
    owned_session(db, user.id, sid)
    rows = db.query(Message).filter_by(session_id=sid).order_by(Message.id).all()
    return [{"role": m.role, "content": m.content, "created_at": str(m.created_at)}
            for m in rows]
