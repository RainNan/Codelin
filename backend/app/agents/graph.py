"""Codelin 核心：LangGraph ReAct 执行图。"""
import time
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.prompts import SYSTEM_PROMPT
from app.async_utils import run_blocking
from app.agents.state import CodelinState
from app.llm.provider import get_llm
from app.rag.service import index_workspace, hybrid_search
from app.tools import ops
from app.tools.definitions import TOOL_LIST
from langgraph.types import Command, interrupt

_llm = get_llm()
# 声明工具，由模型根据任务决定是否调用。
_llm_with_tools = _llm.bind_tools(TOOL_LIST)

# 执行注册表：M4 会在这里插入审批逻辑
OPS_REGISTRY: dict[str, object] = {
    "list_dir": lambda ws, a: ops.list_dir(ws, a.get("path", ".")),
    "read_file": lambda ws, a: ops.read_file(ws, a["path"]),
    "write_file": lambda ws, a: ops.write_file(ws, a["path"], a["content"]),
    "grep": lambda ws, a: ops.grep(ws, a["pattern"], a.get("glob", "*")),
    "index_codebase": lambda ws, a, sid: index_workspace(sid, ws),
    "search_code": lambda ws, a, sid: hybrid_search(sid, a["query"])
}


async def agent_node(state: CodelinState) -> dict:
    """调 LLM。messages 已含全部历史（含工具结果），LLM 决定继续调工具或收尾。"""
    context = ("当前对话属于工作区，文件工具只能访问该工作区。" if state.get("workspace_id") else
               "当前是独立对话。知识问答直接回答；开发任务仍应调用项目工具，系统会自动建立空工作区并关联原对话。不要声称该空工作区已有用户项目。")
    messages = [SystemMessage(content=SYSTEM_PROMPT + "\n\n" + context), *state["messages"]]
    resp: AIMessage = await _llm_with_tools.ainvoke(messages)
    return {"messages": [resp]}


async def prepare_workspace_node(state: CodelinState, config: RunnableConfig) -> dict:
    calls = getattr(state["messages"][-1], "tool_calls", [])
    if not any(c["name"] in (*OPS_REGISTRY, "run_command") for c in calls):
        return {"workspace_created": None}
    prepare = config.get("configurable", {}).get("prepare_workspace")
    if prepare:
        wid, root, created = await run_blocking(prepare)
        return {"workspace_id": wid, "workspace": root, "workspace_created": created}
    if not state.get("workspace"):
        raise RuntimeError("项目工具执行前必须准备工作区")
    return {"workspace_created": None}


async def execute_node(state: CodelinState, config: RunnableConfig) -> dict:
    """执行上一条 AIMessage 要求的所有工具调用，结果以 ToolMessage 追加。"""
    last: AIMessage = state["messages"][-1]
    ws = Path(state["workspace"]) if state.get("workspace") else None
    rejected = state.get("approval_decision") == "rejected"
    wid = state.get("workspace_id")

    results: list[ToolMessage] = []
    changes: list[dict] = []

    for call in last.tool_calls:
        guard = config.get("configurable", {}).get("operation")
        if guard:
            guard.check()
        name, args = call["name"], dict(call["args"])
        if (rejected and name == "run_command"
                and ops.is_dangerous(args.get("command", ""))):
            obs = f"[人工审批：用户拒绝执行] {args['command']}。请改用不需要审批的替代方案。"
            results.append(ToolMessage(content=obs, tool_call_id=call["id"], name=name))
            continue
        t0 = time.perf_counter()
        try:
            if name == "run_command":
                obs = await ops.run_command(ws, args["command"])
                changes.append({"event": "workspace_changed", "workspace_id": state.get("workspace_id")})
            elif name == "write_file":
                result = await run_blocking(ops.write_file_result, ws, args["path"], args["content"], args.get("expected_version"))
                obs = result["summary"]
                changes.append({"event": "file_changed", "workspace_id": state.get("workspace_id"),
                                "path": result["path"], "operation": result["operation"], "version": result["version"]})
            elif name in ("index_codebase", "search_code"):
                obs = await run_blocking(OPS_REGISTRY[name], ws, args, wid)
            elif name in OPS_REGISTRY:
                obs = await run_blocking(OPS_REGISTRY[name], ws, args)
            else:
                obs = f"未知工具: {name}"
            ok = True
        except Exception as e:
            obs, ok = f"工具错误: {type(e).__name__}: {e}", False
        print(f"[tool] {name} ok={ok} {int((time.perf_counter() - t0) * 1000)}ms")
        results.append(
            ToolMessage(content=str(obs), tool_call_id=call["id"], name=name)
        )
    return {"messages": results, "approval_decision": None, "file_changes": changes}


async def approve_node(state: CodelinState) -> dict:
    """扫描本轮 tool_calls，发现危险命令则挂起等待人工审批。

    interrupt() 在恢复重放时直接返回用户提交的决定，
    所以本节点自身永远没有副作用 —— 这正是拆独立节点的原因。
    """
    last: AIMessage = state["messages"][-1]
    dangerous = [
        c["args"].get("command", "")
        for c in last.tool_calls
        if c["name"] == "run_command" and ops.is_dangerous(c["args"].get("command", ""))
    ]
    decision = interrupt({
        "tools": [{"name": "run_command", "commands": dangerous}],
        "reason": "检测到影响环境的命令，需要人工审批",
    })
    return {"approval_decision": decision}  # "approved" | "rejected"


def route_after_agent(state: CodelinState) -> str:
    last = state["messages"][-1]
    calls = getattr(last, "tool_calls", None) or []
    if not calls:
        return END
    return "prepare_workspace"


def route_after_workspace(state: CodelinState) -> str:
    calls = getattr(state["messages"][-1], "tool_calls", None) or []
    has_dangerous = any(
        c["name"] == "run_command" and ops.is_dangerous(c["args"].get("command", ""))
        for c in calls
    )
    return "approve" if has_dangerous else "execute"


def build_graph(checkpointer=None):
    g = StateGraph(CodelinState)
    g.add_node("agent", agent_node)
    g.add_node("prepare_workspace", prepare_workspace_node)
    g.add_node("approve", approve_node)
    g.add_node("execute", execute_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route_after_agent,
                            {"prepare_workspace": "prepare_workspace", END: END})
    g.add_conditional_edges("prepare_workspace", route_after_workspace,
                            {"approve": "approve", "execute": "execute"})
    g.add_edge("approve", "execute")
    g.add_edge("execute", "agent")  # execute 完成后清空审批标记再回 agent
    return g.compile(checkpointer=checkpointer)


# 进程级单例（M5 换 PostgresSaver）
graph = build_graph(InMemorySaver())
