"""把 ops 函数包装成 LangChain 工具（声明 Schema 给 LLM）。

关键设计：workspace 参数用 InjectedToolArg 注解 ——
LLM 的 Schema 里没有它，调用时由编排层注入，模型无法伪造工作区。
（声明与执行分离 + 隐藏参数，是防越权的组合拳）
"""
from pathlib import Path
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from app.tools import ops


@tool
def list_dir(path: str, workspace: Annotated[str, InjectedToolArg]) -> str:
    """列出工作区内指定目录的直接子项。先用它了解项目结构。path 用 "." 表示根目录。"""
    return ops.list_dir(Path(workspace), path)


@tool
def read_file(path: str, workspace: Annotated[str, InjectedToolArg]) -> str:
    """读取工作区内一个文本文件，返回带行号的全部内容。适合查看源码/配置。"""
    return ops.read_file(Path(workspace), path)


@tool
def write_file(
        path: str, content: str, workspace: Annotated[str, InjectedToolArg]
) -> str:
    """创建或完整覆写工作区内一个文件。content 必须是完整文件内容（非增量补丁）。"""
    return ops.write_file(Path(workspace), path, content)


@tool
def grep(
        pattern: str,
        glob: str,
        workspace: Annotated[str, InjectedToolArg],
) -> str:
    """在工作区内递归搜索正则 pattern，返回 文件:行号: 内容。glob 限定文件类型，如 *.py。"""
    return ops.grep(Path(workspace), pattern, glob or "*")


@tool("run_command")
async def run_command_tool(
        command: str, workspace: Annotated[str, InjectedToolArg]
) -> str:
    """在工作区目录内执行一条 shell 命令（运行测试/安装依赖/git 等）。危险命令会被拦截等待人工审批。"""
    return await ops.run_command(Path(workspace), command)

@tool
def index_codebase(workspace: Annotated[str, InjectedToolArg],
                   workspace_id: Annotated[str, InjectedToolArg]) -> str:
    """为当前工作区建立代码索引（向量+BM25）。在需要语义搜索代码、或文件较多时先调用。"""
    from app.rag.service import index_workspace
    return index_workspace(workspace_id, Path(workspace))


@tool
def search_code(query: str,
                workspace: Annotated[str, InjectedToolArg],
                workspace_id: Annotated[str, InjectedToolArg]) -> str:
    """混合检索（关键词+语义）工作区代码，返回带 文件:行号 的相关片段。
    适合"XX功能在哪实现/哪里处理了YY"这类问题，比逐个 read_file 高效。"""
    from app.rag.service import hybrid_search
    return hybrid_search(workspace_id, query)


TOOL_LIST = [list_dir, read_file, write_file, grep, run_command_tool, index_codebase, search_code]
TOOL_REGISTRY = {t.name: t for t in TOOL_LIST}  # key 即 "run_command"
