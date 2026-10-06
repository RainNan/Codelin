"""Codelin 核心：LangGraph ReAct 执行图。"""
import time
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.prompts import SYSTEM_PROMPT
from app.agents.state import CodelinState
from app.llm.provider import get_llm
from app.tools import ops
from app.tools.definitions import TOOL_LIST

_llm = get_llm()
# bind_tools 把 5 个工具的 JSON Schema 绑到 LLM 上（只是声明，不执行）
_llm_with_tools = _llm.bind_tools(TOOL_LIST)

# 执行注册表：M4 会在这里插入审批逻辑
OPS_REGISTRY: dict[str, object] = {
    "list_dir": lambda ws, a: ops.list_dir(ws, a.get("path", ".")),
    "read_file": lambda ws, a: ops.read_file(ws, a["path"]),
    "write_file": lambda ws, a: ops.write_file(ws, a["path"], a["content"]),
    "grep": lambda ws, a: ops.grep(ws, a["pattern"], a.get("glob", "*")),
}


async def agent_node(state: CodelinState) -> dict:
    """调 LLM。messages 已含全部历史（含工具结果），LLM 决定继续调工具或收尾。"""
    messages = [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]]
    resp: AIMessage = await _llm_with_tools.ainvoke(messages)
    return {"messages": [resp]}


async def execute_node(state: CodelinState) -> dict:
    """执行上一条 AIMessage 要求的所有工具调用，结果以 ToolMessage 追加。"""
    last: AIMessage = state["messages"][-1]
    ws = Path(state["workspace"])
    results: list[ToolMessage] = []
    for call in last.tool_calls:
        name, args = call["name"], dict(call["args"])
        t0 = time.perf_counter()
        try:
            if name == "run_command":
                obs = await ops.run_command(ws, args["command"])
            elif name in OPS_REGISTRY:
                obs = OPS_REGISTRY[name](ws, args)
            else:
                obs = f"未知工具: {name}"
            ok = True
        except Exception as e:
            obs, ok = f"工具错误: {type(e).__name__}: {e}", False
        print(f"[tool] {name} ok={ok} {int((time.perf_counter()-t0)*1000)}ms")
        results.append(
            ToolMessage(content=str(obs), tool_call_id=call["id"], name=name)
        )
    return {"messages": results}


def route_after_agent(state: CodelinState) -> str:
    last = state["messages"][-1]
    return "execute" if getattr(last, "tool_calls", None) else END


def build_graph(checkpointer=None):
    g = StateGraph(CodelinState)
    g.add_node("agent", agent_node)
    g.add_node("execute", execute_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route_after_agent, {"execute": "execute", END: END})
    g.add_edge("execute", "agent")   # 工具结果回灌 → 形成循环
    return g.compile(checkpointer=checkpointer)


# 进程级单例（M5 换 PostgresSaver）
graph = build_graph(InMemorySaver())