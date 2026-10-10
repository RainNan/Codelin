"""BM25（进程内）+ RRF 融合。"""
import re
from collections import defaultdict

from rank_bm25 import BM25Okapi

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")


def code_tokenize(text: str) -> list[str]:
    """代码分词：标识符级 + 驼峰拆分 + 小写。中文注释按字切。"""
    toks = []
    for m in _TOKEN.finditer(text):
        w = m.group(0)
        toks.append(w.lower())
        # CamelCase → camel case（让 searchUser 命中 user）
        toks.extend(x.lower() for x in re.findall(r"[A-Z][a-z]*", w))
    toks.extend(text) if False else toks.extend(
        c for c in text if "\u4e00" <= c <= "\u9fff"
    )
    return toks


class BM25Index:
    """每个工作区一个索引；排名使用数据库主键，避免重建后序号错配。"""
    def __init__(self) -> None:
        self._store: dict[str, tuple[BM25Okapi, list[int]]] = {}  # sid → (索引, chunk_ids)

    def build(self, sid: str, chunks: list) -> list[int]:
        self.drop(sid)
        if not chunks:
            return []
        ids = [c.id for c in chunks]
        tok = [code_tokenize(c.content) for c in chunks]
        self._store[sid] = (BM25Okapi(tok), ids)
        return ids

    def search(self, sid: str, query: str, top_k: int = 20) -> list[int]:
        idx = self._store.get(sid)
        if not idx:
            return []
        bm25, _ = idx
        scores = bm25.get_scores(code_tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: -scores[i])[:top_k]
        return [idx[1][i] for i in ranked if scores[i] > 0]

    def drop(self, wid: str):
        self._store.pop(wid, None)


def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[int]:
    """多路排名 → RRF 融合排名。公式: sum(1/(k+rank))。"""
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            scores[doc] += 1.0 / (k + rank)
    return sorted(scores, key=lambda d: -scores[d])


bm25_store = BM25Index()
