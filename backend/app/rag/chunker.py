"""根据文件名或扩展名选择 Tree-sitter 解析器，优先沿语法树拆分超长节点，
并合并相邻小片段，每块最多 1500 字符；未知语言、语法错误或无法继续拆分的超长内容，
改用按行窗口切分，窗口之间尽量重叠最后 3 行，超长单行则按字符切开。
每块保留原文、文件路径和准确的起止行号，空白片段不输出。"""
import logging
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

from tree_sitter_language_pack import get_parser

logger = logging.getLogger(__name__)
MAX_CHARS = 1500
OVERLAP_LINES = 3

# 文件识别和索引入口共用，新增语言只需补充此映射。
LANGUAGE_BY_EXT = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx",
    ".java": "java", ".go": "go", ".rs": "rust",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".cs": "csharp", ".php": "php", ".rb": "ruby",
    ".kt": "kotlin", ".kts": "kotlin", ".swift": "swift",
    ".scala": "scala", ".lua": "lua", ".dart": "dart",
    ".vue": "vue", ".svelte": "svelte",
    ".sh": "bash", ".bash": "bash", ".ps1": "powershell",
    ".sql": "sql", ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".json": "json",
    ".md": "markdown", ".graphql": "graphql", ".proto": "proto",
}
LANGUAGE_BY_NAME = {"dockerfile": "dockerfile", "makefile": "make", "cmakelists.txt": "cmake"}


@dataclass
class Chunk:
    path: str
    start_line: int
    end_line: int
    content: str


def _structure_spans(text: str, language: str) -> list[tuple[int, int]]:
    """沿语法树拆大节点、合并相邻小节点，返回连续的字符区间。"""
    source = text.encode("utf-8")
    root = get_parser(language).parse(source).root_node
    if root.has_error:
        raise ValueError("source contains syntax errors")
    pending = [(root, 0, len(source))]
    spans = []
    cursor = 0
    while pending:
        node, start, end = pending.pop()
        size = len(source[start:end].decode("utf-8"))
        children = node.named_children
        if size > MAX_CHARS and children:
            # 将节点之间的空白、注释及父节点的括号也留在原文区间内。
            bounds = [start] + [child.start_byte for child in children[1:]] + [end]
            pending.extend(reversed([
                (child, bounds[i], bounds[i + 1]) for i, child in enumerate(children)
            ]))
            continue
        stop = cursor + size
        if spans and stop - spans[-1][0] <= MAX_CHARS:
            spans[-1] = (spans[-1][0], stop)
        else:
            spans.append((cursor, stop))
        cursor = stop
    return spans


def _windows(text: str, start: int, end: int):
    """动态按行切分，超长单行按字符切分，保证每块不超过 MAX_CHARS。"""
    while start < end:
        stop = min(start + MAX_CHARS, end)
        if stop < end:
            newline = text.rfind("\n", start, stop)
            if newline >= start:
                stop = newline + 1
        yield start, stop
        if stop == end:
            break
        lines = text[start:stop].splitlines(keepends=True)
        overlap = len("".join(lines[-OVERLAP_LINES:])) if len(lines) > OVERLAP_LINES else 0
        start = stop - overlap


def chunk_code(path: str, text: str) -> list[Chunk]:
    """接收文件路径和已读取的文本，返回 list[Chunk]"""
    if not text.strip():
        return []
    file = Path(path)
    language = LANGUAGE_BY_NAME.get(file.name.lower()) or LANGUAGE_BY_EXT.get(file.suffix.lower())
    spans = [(0, len(text))]
    if language:
        try:
            spans = _structure_spans(text, language)
        except (LookupError, ValueError, RuntimeError) as exc:
            logger.debug("Text chunking fallback for %s: %s", path, exc)
    line_starts = [0] + [i + 1 for i, char in enumerate(text) if char == "\n"]
    chunks = []
    for start, end in spans:
        for s, e in _windows(text, start, end):
            content = text[s:e]
            if content.strip():
                chunks.append(Chunk(path, bisect_right(line_starts, s),
                                    bisect_right(line_starts, e - 1), content))
    return chunks
