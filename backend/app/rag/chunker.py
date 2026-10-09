"""结构感知切块：优先按顶层 def/class 边界，超长再按行窗口二切。"""
import re
from dataclasses import dataclass

TOP_BOUNDARY = re.compile(r"^(?:class |def |async def |function |export |const \w+ = )", re.M)
MAX_CHARS = 1500      # bge-m3 窗口 8192 token，1500 字符留足余量
OVERLAP_LINES = 3     # 窗口重叠，避免边界处语义断裂


@dataclass
class Chunk:
    path: str
    start_line: int
    end_line: int
    content: str


def chunk_code(path: str, text: str) -> list[Chunk]:
    lines = text.splitlines()
    # 1) 找结构边界行号
    bounds = [m.start() for m in TOP_BOUNDARY.finditer(text)]
    starts = ([0] + [text.count("\n", 0, b) + 1 for b in bounds]) if bounds else [0]
    starts = sorted(set(starts))
    chunks: list[Chunk] = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(lines)
        block = "\n".join(lines[s:e])
        if not block.strip():
            continue
        if len(block) <= MAX_CHARS:
            chunks.append(Chunk(path, s + 1, e, block))
        else:
            # 2) 超长块滑窗二切
            w = next((n for n in range(len(lines[s:e]), 0, -1)
                      if len("\n".join(lines[s:s + n])) <= MAX_CHARS), 1)
            for ws in range(s, e, max(w - OVERLAP_LINES, 1)):
                we = min(ws + w, e)
                piece = "\n".join(lines[ws:we])
                if piece.strip():
                    chunks.append(Chunk(path, ws + 1, we, piece))
                if we >= e:
                    break
    return chunks