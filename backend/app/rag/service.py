"""索引流水线与混合检索。"""
import json
from pathlib import Path

import numpy as np
from sqlalchemy import text as sql_text

from app.db.models import CodeChunk
from app.db.session import SessionLocal
from app.rag.chunker import chunk_code
from app.rag.embeddings import get_embedder
from app.rag.retrieval import bm25_store, rrf_fuse
from app.files.service import safe_path, FileError
from app.operations import operation

CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".cpp", ".h",
             ".sql", ".sh", ".yaml", ".yml", ".toml", ".json", ".md", ".txt", ".html", ".css"}
MAX_FILE_CHARS = 100_000


def iter_code_files(workspace: Path):
    for p in sorted(workspace.rglob("*")):
        relative = p.relative_to(workspace)
        if (p.is_file() and p.suffix.lower() in CODE_EXTS
                and not any(part.startswith(".") for part in relative.parts)):
            try:
                yield safe_path(workspace, relative.as_posix())
            except FileError:
                continue


def index_workspace(workspace_id: str, workspace: Path) -> str:
    """解析 → 切块 → 嵌入 → pgvector 入库 + BM25 建索引。幂等：先清旧块。"""
    with operation(f"index:{workspace_id}") as guard:
        return _index_workspace(workspace_id, workspace, guard)


def _index_workspace(workspace_id, workspace, guard):
    chunks: list[CodeChunk] = []
    for f in iter_code_files(workspace):
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")[:MAX_FILE_CHARS]
        except OSError:
            continue
        rel = f.relative_to(workspace).as_posix()
        for c in chunk_code(rel, content):
            chunks.append(CodeChunk(workspace_id=workspace_id, path=c.path,
                                    start_line=c.start_line, end_line=c.end_line,
                                    content=c.content))
    if not chunks:
        with SessionLocal() as db:
            db.query(CodeChunk).filter_by(workspace_id=workspace_id).delete()
            guard.check()
            db.commit()
        bm25_store.drop(workspace_id)
        return "工作区内没有可索引的文件"

    vectors = get_embedder().embed_documents([c.content for c in chunks])

    db = SessionLocal()
    try:
        db.query(CodeChunk).filter_by(workspace_id=workspace_id).delete()
        for ch, v in zip(chunks, vectors, strict=True):
            ch.embedding = np.asarray(v, dtype=float).tolist()
        db.add_all(chunks)
        guard.check()
        db.commit()
    finally:
        db.close()

    bm25_store.build(workspace_id, chunks)
    n_files = len({c.path for c in chunks})
    return f"索引完成：{n_files} 个文件，{len(chunks)} 个代码块（向量库+BM25 双路）"


def hybrid_search(workspace_id: str, query: str, top_k: int = 5) -> str:
    """BM25 + 向量 → RRF → 带引用返回。给 LLM 的输出必须带 file:line（Citation）。"""
    qvec = get_embedder().embed_query(query)

    db = SessionLocal()
    try:
        # 向量路：余弦距离 <=>，按工作区隔离
        vec_rows = db.execute(
            sql_text("""
                SELECT id FROM code_chunks
                WHERE workspace_id = :wid AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:qv AS vector)
                LIMIT 20
            """),
            {"wid": workspace_id, "qv": json.dumps(qvec)},
        ).scalars().all()
        chunks = db.query(CodeChunk).filter_by(workspace_id=workspace_id).order_by(CodeChunk.id).all()
        by_id = {ch.id: ch for ch in chunks}
        bm25_store.build(workspace_id, chunks)  # Works after restart and across worker processes.
        bm_ranking = bm25_store.search(workspace_id, query, top_k=20)
    finally:
        db.close()

    fused = rrf_fuse([bm_ranking, list(vec_rows)])[:top_k]

    out = []
    for rank, idx in enumerate(fused, 1):
        ch = by_id.get(idx)
        if ch is not None:
            out.append(f"[{rank}] {ch.path}:{ch.start_line}-{ch.end_line}\n{ch.content[:600]}")
    return "\n\n".join(out) if out else "(没有找到相关代码，可先运行 index_codebase)"
