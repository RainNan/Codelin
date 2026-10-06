"""M3 版入口：/api/chat 跑 Agent 图。"""
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agents.runner import sse_events

app = FastAPI(title="Codelin", version="0.3.0")

ROOT = Path(__file__).resolve().parent.parent.parent / "workspaces"
ROOT.mkdir(exist_ok=True)


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None   # 传入则续聊，不传则新会话


@app.post("/api/chat")
async def chat(body: ChatIn):
    session_id = body.session_id or uuid.uuid4().hex
    workspace = ROOT / session_id
    workspace.mkdir(exist_ok=True)
    return StreamingResponse(
        sse_events(session_id, str(workspace), body.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )