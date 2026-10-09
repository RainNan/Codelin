"""索引流水线与混合检索。"""
import json
import re
from pathlib import Path

import numpy as np
from sqlalchemy import text as sql_text

from app.db.models import CodeChunk
from app.db.session import SessionLocal
from app.rag.chunker import chunk_code
from app.rag.embeddings import get_embedder
from app.rag.retrieval import bm25_store, rrf_fuse

CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".cpp", ".h",
             ".sql", ".sh", ".yaml", ".yml", ".toml", ".json", ".md", ".txt", ".html", ".css"}
MAX_FILE_CHARS = 100_000


def iter_code_files(workspace: Path):
    for p in sorted(workspace.rglob("*")):
        if (p.is_file() and p.suffix.lower() in CODE_EXTS
                and not any(part.startswith(".") for part in p.parts)):
            yield p


def index_workspace(session_id: str, workspace: Path) -> str:
    """解析 → 切块 → 嵌入 → pgvector 入库 + BM25 建索引。幂等：先清旧块。"""
    chunks: list[CodeChunk] = []
    raw = []
    for f in iter_code_files(workspace):
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")[:MAX_FILE_CHARS]
        except OSError:
            continue
        rel = f.relative_to(workspace).as_posix()
        for c in chunk_code(rel, content):
            chunks.append(CodeChunk(session_id=session_id, path=c.path,
                                    start_line=c.start_line, end_line=c.end_line,
                                    content=c.content))
            raw.append(c)
    if not chunks:
        return "工作区内没有可索引的文件"

    vectors = get_embedder().embed_documents([c.content for c in chunks])

    db = SessionLocal()
    try:
        db.query(CodeChunk).filter_by(session_id=session_id).delete()
        db.add_all(chunks)
        db.commit()
        for ch, v in zip(chunks, vectors):
            db.execute(
                sql_text("UPDATE code_chunks SET embedding = :v WHERE id = :id"),
                {"v": json.dumps(np.asarray(v, dtype=float).tolist()), "id": ch.id},
            )
        db.commit()
    finally:
        db.close()

    bm25_store.build(session_id, raw)
    n_files = len({c.path for c in chunks})
    return f"索引完成：{n_files} 个文件，{len(chunks)} 个代码块（向量库+BM25 双路）"


def hybrid_search(session_id: str, query: str, top_k: int = 5) -> str:
    """BM25 + 向量 → RRF → 带引用返回。给 LLM 的输出必须带 file:line（Citation）。"""
    qvec = get_embedder().embed_query(query)

    db = SessionLocal()
    try:
        # 向量路：余弦距离 <=>，按会话隔离
        vec_rows = db.execute(
            sql_text("""
                SELECT id FROM code_chunks
                WHERE session_id = :sid AND embedding IS NOT NULL
                ORDER BY embedding <=> (:qv ::vector)
                LIMIT 20
            """),
            {"sid": session_id, "qv": json.dumps(qvec)},
        ).scalars().all()
        all_rows = db.execute(
            sql_text("SELECT id FROM code_chunks WHERE session_id = :sid ORDER BY id"),
            {"sid": session_id},
        ).scalars().all()
    finally:
        db.close()

    pos_map = {cid: i for i, cid in enumerate(all_rows)}          # db id → 序号
    vec_ranking = [pos_map[c] for c in vec_rows if c in pos_map]  # 向量排名（序号空间）
    bm_ranking = bm25_store.search(session_id, query, top_k=20)   # BM25 排名（同空间）

    fused = rrf_fuse([bm_ranking, vec_ranking])[:top_k]

    db = SessionLocal()
    try:
        out = []
        for rank, idx in enumerate(fused, 1):
            ch = db.get(CodeChunk, all_rows[idx])
            out.append(
                f"[{rank}] {ch.path}:{ch.start_line}-{ch.end_line}\n{ch.content[:600]}"
            )
        return "\n\n".join(out) if out else "(没有找到相关代码，可先运行 index_codebase)"
    finally:
        db.close()