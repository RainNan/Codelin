"""工具的纯执行逻辑：框架无关，可单测，被 Agent 执行器和 MCP Server 共用。"""
import re
import subprocess
from pathlib import Path

from app.tools.security import ToolError, resolve_safe_path
from app.files import service as files

MAX_READ_CHARS = 30_000      # 防止把超长文件塞爆上下文
MAX_OUTPUT_CHARS = 8_000     # 命令输出截断
CMD_TIMEOUT_SECONDS = 60

# 危险命令模式：M3 先检测记录，M4 升级为人工审批
DANGEROUS_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\b",  # rm -rf
    r"\bsudo\b",
    r"\bmkfs\b",
    r"\bdd\b[^|]*of=/dev/",
    r"\b(shutdown|reboot)\b",
    r"(curl|wget).+[|;]\s*(ba)?sh\b",     # 下载脚本直接执行
    r"\bgit\s+push\s+(-f|--force)\b",
    r"\bpip\s+install\b",                 # 改环境，需审批（很好的演示用例）
    r"\bnpm\s+(install|i)\b",
]


def is_dangerous(command: str) -> bool:
    return any(re.search(p, command) for p in DANGEROUS_PATTERNS)


def list_dir(workspace: Path, rel_path: str = ".") -> str:
    listing = files.list_directory(workspace, rel_path, limit=500)
    entries = [(entry["name"], "dir" if entry["type"] == "directory" else "file") for entry in listing["entries"]]
    if not entries:
        return "(空目录)"
    return "\n".join(f"{'[目录]' if t == 'dir' else '[文件]'} {n}" for n, t in entries)


def read_file(workspace: Path, rel_path: str) -> str:
    text = files.read_text(workspace, rel_path)["content"]
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + f"\n...(截断，全文 {len(text)} 字符)"
    # 带行号输出：LLM 精确定位 + 前端可展示行号（Claude Code 同款体验）
    return "\n".join(
        f"{i:>4} | {line}" for i, line in enumerate(text.splitlines(), start=1)
    )


def write_file_result(workspace: Path, rel_path: str, content: str, expected_version: str | None = None) -> dict:
    result = files.write_text(workspace, rel_path, content, expected_version=expected_version, create_parents=True)
    action = "覆写" if result["operation"] == "updated" else "创建"
    result["summary"] = f"已{action} {rel_path}（{len(content)} 字符，{content.count(chr(10)) + 1} 行）"
    return result


def write_file(workspace: Path, rel_path: str, content: str, expected_version: str | None = None) -> str:
    return write_file_result(workspace, rel_path, content, expected_version)["summary"]


def grep(
    workspace: Path, pattern: str, glob: str = "*",
) -> str:
    """递归正则搜索。glob 如 "*.py" 限定文件类型。"""
    root = workspace.resolve()
    rx = re.compile(pattern)
    hits: list[str] = []
    for p in sorted(root.rglob(glob)):
        if not p.is_file() or any(part.startswith(".") for part in p.parts):
            continue  # 跳过隐藏目录（.git/.venv）
        try:
            p = resolve_safe_path(root, p.relative_to(root).as_posix())
            for i, line in enumerate(
                p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                if rx.search(line):
                    rel = p.relative_to(root)
                    hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(hits) >= 50:
                        return "\n".join(hits) + "\n...(结果截断至 50 条)"
        except (ToolError, PermissionError, OSError):
            continue
    return "\n".join(hits) if hits else "(无匹配)"


async def run_command(workspace: Path, command: str) -> str:
    """在线程中执行命令，兼容 Windows Selector 事件循环。"""
    try:
        from app.async_utils import run_blocking
        proc = await run_blocking(
            subprocess.run,
            command,
            shell=True,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=CMD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"命令超时（>{CMD_TIMEOUT_SECONDS}s）被终止: {command}") from exc
    text = proc.stdout.decode(errors="replace")[:MAX_OUTPUT_CHARS]
    return f"[exit code {proc.returncode}]\n{text}"
