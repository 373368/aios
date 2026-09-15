# -*- coding: utf-8 -*-
"""
Hybrid retrieval: BM25 (lexical) + dense (semantic) fused via RRF.

RRF(d) = Σ_engine 1 / (k + rank_engine(d))

Reuses tokenize / BM25Baseline from baselines.py (does not reimplement BM25).

用法：
  python hybrid_retrieval.py        # 自检（合成语料验证 BM25 对精确词条的贡献）
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from baselines import BM25Baseline  # noqa: E402


class HybridRetriever:
    """Fuse dense-cosine ranking with BM25 lexical ranking via Reciprocal Rank Fusion."""

    def __init__(self, doc_texts, doc_vectors, doc_ids=None, k=60):
        self.k = k
        self.N = len(doc_texts)
        if doc_ids is None:
            doc_ids = [str(i) for i in range(self.N)]
        self.doc_ids = list(doc_ids)
        self.path_to_idx = {pid: i for i, pid in enumerate(self.doc_ids)}

        # normalized doc vectors for cosine (numpy only)
        norms = np.linalg.norm(doc_vectors, axis=1, keepdims=True)
        self.vectors_normed = doc_vectors / np.where(norms > 0, norms, 1)

        # BM25 over full doc texts (title=text, path=doc_id so results carry ids)
        meta = [{"path": pid, "title": t} for pid, t in zip(self.doc_ids, doc_texts)]
        self.bm25 = BM25Baseline(meta)

    # ── engine rankings (full ordering of `subset`) ────────────────────────

    def _rank_semantic(self, query_vec, subset):
        idx = np.arange(self.N) if subset is None else np.array(list(subset), dtype=int)
        q = query_vec / (np.linalg.norm(query_vec) + 1e-12)
        scores = self.vectors_normed[idx] @ q
        return [int(i) for i in idx[np.argsort(scores)[::-1]]]

    def _rank_bm25(self, query_text, subset):
        results = self.bm25.search(query_text, top_k=self.N)
        ranking = [self.path_to_idx[r["path"]] for r in results]
        if subset is None:
            return ranking
        sub = set(subset)
        return [i for i in ranking if i in sub]

    # ── public search API ──────────────────────────────────────────────────

    def search_semantic(self, query_vec, top_k=10, subset=None):
        """Pure semantic cosine ranking (numpy). Returns doc indices."""
        return self._rank_semantic(query_vec, subset)[:top_k]

    def search_bm25(self, query_text, top_k=10, subset=None):
        """BM25 lexical ranking. Returns doc indices."""
        return self._rank_bm25(query_text, subset)[:top_k]

    def _rrf(self, rankings):
        scores = {}
        for ranking in rankings:
            for rank, idx in enumerate(ranking, 1):
                scores[idx] = scores.get(idx, 0.0) + 1.0 / (self.k + rank)
        return sorted(scores, key=lambda i: -scores[i])

    def search_hybrid(self, query_vec, query_text, top_k=10, subset=None):
        """RRF fusion of semantic + BM25 rankings. Returns doc indices."""
        return self._rrf([
            self._rank_semantic(query_vec, subset),
            self._rank_bm25(query_text, subset),
        ])[:top_k]


def _self_check():
    """Synthetic corpus: a unique exact term 'bm25x' lives in doc d0; d2 is
    semantically closest to the query. BM25 must lift d0 to rank 1 in hybrid."""
    doc_texts = [
        "bm25x exact term lexical retrieval ranking",   # d0: exact-match doc
        "cat dog fish bird elephant",                    # d1: filler
        "deep learning neural transformer attention",    # d2: semantic top
    ]
    # normalized vectors, cos sim with q=[1,0,0]: d2=0.9, d0=0.8, d1=0.7
    doc_vectors = np.array([
        [0.8, 0.6, 0.0],
        [0.7, 0.71414284, 0.0],
        [0.9, 0.43588989, 0.0],
    ])
    q = np.array([1.0, 0.0, 0.0])

    ret = HybridRetriever(doc_texts, doc_vectors, doc_ids=["d0", "d1", "d2"], k=60)
    sem = ret.search_semantic(q, 3)
    bm = ret.search_bm25("bm25x", 3)
    hyb = ret.search_hybrid(q, "bm25x", 3)

    print("semantic:", sem)
    print("bm25:    ", bm)
    print("hybrid:  ", hyb)

    assert sem[0] == 2, "semantic top should be d2"
    assert bm[0] == 0, "bm25 top should be the exact-match d0"
    assert hyb[0] == 0, "hybrid should rank exact-match d0 first"
    assert hyb.index(0) < sem.index(0), \
        "hybrid must lift the exact-match doc above its pure-semantic rank"

    print("\nOK: exact-match doc rank semantic=%d -> hybrid=%d (BM25 contribution)" %
          (sem.index(0) + 1, hyb.index(0) + 1))
    return True


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    _self_check()
