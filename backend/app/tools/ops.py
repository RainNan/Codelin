"""工具的纯执行逻辑：框架无关，可单测，被 Agent 执行器和 MCP Server 共用。"""
import asyncio
import re
from pathlib import Path

from app.tools.security import ToolError, resolve_safe_path

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
    root = resolve_safe_path(workspace, rel_path)
    if not root.is_dir():
        raise ToolError(f"不是目录: {rel_path}")
    entries = sorted(
        ((e.name, "dir" if e.is_dir() else "file") for e in root.iterdir()),
        key=lambda x: (x[1] != "dir", x[0].lower()),  # 目录在前
    )
    if not entries:
        return "(空目录)"
    return "\n".join(f"{'[目录]' if t == 'dir' else '[文件]'} {n}" for n, t in entries)


def read_file(workspace: Path, rel_path: str) -> str:
    target = resolve_safe_path(workspace, rel_path)
    if not target.is_file():
        raise ToolError(f"文件不存在: {rel_path}")
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + f"\n...(截断，全文 {len(text)} 字符)"
    # 带行号输出：LLM 精确定位 + 前端可展示行号（Claude Code 同款体验）
    return "\n".join(
        f"{i:>4} | {line}" for i, line in enumerate(text.splitlines(), start=1)
    )


def write_file(workspace: Path, rel_path: str, content: str) -> str:
    target = resolve_safe_path(workspace, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(content, encoding="utf-8")
    action = "覆写" if existed else "创建"
    return f"已{action} {rel_path}（{len(content)} 字符，{content.count(chr(10)) + 1} 行）"


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
            for i, line in enumerate(
                p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                if rx.search(line):
                    rel = p.relative_to(root)
                    hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(hits) >= 50:
                        return "\n".join(hits) + "\n...(结果截断至 50 条)"
        except (PermissionError, OSError):
            continue
    return "\n".join(hits) if hits else "(无匹配)"


async def run_command(workspace: Path, command: str) -> str:
    """在工作区目录内执行 shell 命令（超时+输出截断+行数限制）。"""
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(workspace),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,  # 合并标准错误，LLM 能看到报错才能自我修正
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=CMD_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        raise ToolError(f"命令超时（>{CMD_TIMEOUT_SECONDS}s）被终止: {command}")
    text = out.decode(errors="replace")[:MAX_OUTPUT_CHARS]
    return f"[exit code {proc.returncode}]\n{text}"