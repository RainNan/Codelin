"""运行 Agent 图，把执行过程翻译成 SSE 事件（async generator）。"""
import json
import time
from typing import AsyncGenerator

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

from app.agents import graph as graph_mod


async def sse_events(
        thread_id: str,
        workspace: str | None,
        user_message: str | None,
        session_id: str,
        *,
        resume: Command | None = None,
        workspace_id: str | None = None,
        prepare_workspace=None,
        operation=None,
) -> AsyncGenerator[str, None]:
    cfg = {"configurable": {"thread_id": thread_id, "prepare_workspace": prepare_workspace, "operation": operation}}
    inputs = resume or {
        "messages": [HumanMessage(content=user_message)],
        "workspace": workspace,
        "session_id": session_id,
        "file_changes": [],
        "workspace_id": workspace_id,
        "workspace_created": None,
    }
    t0 = time.perf_counter()

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    try:
        if resume is None:
            prior = await graph_mod.graph.aget_state(cfg)
            answered = set()
            unfinished = []
            for message in reversed(getattr(prior, "values", {}).get("messages", [])):
                if isinstance(message, ToolMessage):
                    answered.add(message.tool_call_id)
                elif getattr(message, "tool_calls", None):
                    unfinished = [ToolMessage(
                        content="上一轮中断，工具执行结果未确认。请检查当前项目后继续，不得假设操作成功。",
                        tool_call_id=call["id"], name=call["name"],
                    ) for call in message.tool_calls if call["id"] not in answered]
                    break
                elif message.type == "ai":
                    break
            if unfinished:
                inputs["messages"] = [*unfinished, *inputs["messages"]]
        # 双流模式：messages 拿 token 级增量，updates 拿节点级完成事件
        async for mode, chunk in graph_mod.graph.astream(
                inputs, cfg, stream_mode=["messages", "updates"],
        ):
            if operation:
                operation.check()
            if mode == "messages":
                msg, meta = chunk
                # 只发 agent 节点产生的文本增量（工具节点没有增量）
                if msg.content and meta.get("langgraph_node") == "agent":
                    content = msg.content if isinstance(msg.content, str) else "".join(
                        item if isinstance(item, str) else item.get("text", "")
                        for item in msg.content
                    )
                    if content:
                        yield sse("token", {"content": content})
            elif mode == "updates":
                for node, update in chunk.items():
                    if node == "__interrupt__":
                        continue
                    if not update:
                        continue
                    msgs = update.get("messages", [])
                    if node == "agent":
                        for c in (getattr(msgs[-1], "tool_calls", None) or []) if msgs else []:
                            yield sse("tool_start", {
                                "id": c["id"], "name": c["name"], "args": c["args"],
                            })
                    elif node == "prepare_workspace":
                        if update.get("workspace_created"):
                            yield sse("workspace_created", {"session_id": session_id, "workspace": update["workspace_created"]})
                    elif node == "execute":
                        for m in msgs:
                            if isinstance(m, ToolMessage):
                                yield sse("tool_result", {
                                    "id": m.tool_call_id, "name": m.name,
                                    "preview": m.content[:400],
                                })
                        for change in update.get("file_changes", []):
                            data = {key: value for key, value in change.items() if key != "event"}
                            data["workspace_id"] = data.get("workspace_id") or workspace_id
                            yield sse(change["event"], data)
            # execute 节点的 updates 单独处理：
            # updates 的 dict 里 node 为 "execute"
        # 流结束仍可能有挂起的中断（approve 节点）
        snapshot = await graph_mod.graph.aget_state(cfg)
        if snapshot.next:  # 非空 = 图停在某节点等待
            # for task in snapshot.tasks.values():
            for task in snapshot.tasks:
                for intr in getattr(task, "interrupts", []):
                    yield sse("approval_required", {
                        "thread_id": thread_id,
                        **intr.value,  # approve_node 里 interrupt 的 payload
                    })
            return  # 有中断就不发 done，前端知道会话处于待审批态
        yield sse("done", {"elapsed_ms": int((time.perf_counter() - t0) * 1000)})
    except Exception as e:
        # A failed preparation node leaves tool calls unanswered in the checkpoint.
        # Close them with real failure observations so the next user turn is valid.
        try:
            failed = await graph_mod.graph.aget_state(cfg)
            messages = failed.values.get("messages", [])
            calls = getattr(messages[-1], "tool_calls", []) if messages else []
            if calls:
                await graph_mod.graph.aupdate_state(cfg, {"messages": [
                    ToolMessage(content=f"工具未执行：{type(e).__name__}: {e}", tool_call_id=call["id"], name=call["name"])
                    for call in calls
                ]}, as_node="execute")
        except Exception:
            pass  # Preserve the original error if the checkpoint store is unavailable.
        yield sse("error", {"message": f"{type(e).__name__}: {e}"})


async def resume_events(
        thread_id: str,
        approved: bool,
        *,
        workspace_id: str | None = None,
        prepare_workspace=None,
        operation=None,
) -> AsyncGenerator[str, None]:
    """用户点击批准/拒绝后，从断点恢复图执行。"""
    cmd = Command(resume="approved" if approved else "rejected")
    async for ev in sse_events(
            thread_id, workspace="", user_message=None,
            session_id=thread_id, resume=cmd,
            workspace_id=workspace_id,
            prepare_workspace=prepare_workspace, operation=operation,
    ):
        yield ev
