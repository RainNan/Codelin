"""Codelin 后端入口。M1 版本：单接口 /api/chat，SSE 流式返回。"""
import json
import time

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.llm.provider import get_llm

app = FastAPI(title="Codelin", version="0.1.0")


class ChatIn(BaseModel):
    message: str


def sse(event: str, data: dict) -> str:
    """把一条事件编码成 SSE 报文（两行 data + 空行）。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
async def chat(body: ChatIn) -> StreamingResponse:
    llm = get_llm()

    async def event_stream():
        start = time.perf_counter()
        try:
            # astream：异步生成器，每次 yield 一个 token 级消息块
            async for chunk in llm.astream(body.message):
                if chunk.content:  # 空内容块（如角色块）跳过
                    yield sse("token", {"content": chunk.content})
            yield sse("done", {"elapsed_ms": int((time.perf_counter() - start) * 1000)})
        except Exception as e:  # 网络断/余额不足/限流都走这里
            yield sse("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",     # 禁止任何中间层缓存事件流
            "X-Accel-Buffering": "no",       # 告诉 nginx 不要缓冲（M11 部署的关键！）
        },
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}