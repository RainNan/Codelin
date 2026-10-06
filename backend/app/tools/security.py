"""路径安全：所有文件工具的必经之路。

核心思想：把 LLM 给的任意 path 解析到工作区内部，逃逸一律拒绝。
这是防"路径穿越攻击"（../../etc/passwd）的标准做法。
"""
from pathlib import Path

from fastapi import HTTPException


class ToolError(Exception):
    """工具级错误：消息会回传给 LLM 让它自行修正，而不是崩掉整个请求。"""


def resolve_safe_path(workspace: Path, rel_path: str) -> Path:
    """把相对路径安全解析到 workspace 内。

    resolve() 会展开 ../ 和符号链接，然后用 is_relative_to 判断边界，
    所以 "../secrets"、"/etc/passwd"、"a/../../b" 这类都会被拦截。
    """
    root = workspace.resolve()
    target = (root / rel_path).resolve()
    if not target.is_relative_to(root):
        raise ToolError(f"路径越界（禁止访问工作区之外）: {rel_path}")
    return target