# -*- coding: utf-8 -*-
"""记忆引擎 v1 · 定案框架（2026-08-22 简化版）

检索层: fd_bm25 = field_density(全秩几何场) + BM25 → RRF 融合（全库排序，默认）
  — 2026-08-22 定案: multiscale 候选池在真实库压缩比仅 1.06x（无裁剪行为），
    效率全部来自 fd_bm25 自身（numpy 全库矩阵乘 + BM25 稀疏倒排），
    故默认路径移除 multiscale（构建 84ms 净开销 + 质量 NDCG -0.013 无收益）。
组织层: multiscale/连续盆地 = 离线压缩工具，不再进入在线检索默认路径。

超大库可选项: pool_mode="density" → DensitySpace 连续密度盆地候选池
  （k-NN 盆地天然平衡无巨簇、峰=真实文档；质量 -4~7% 边界已知，10k+ 库启用）
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from field_response_geometric import FieldResponseGeometric  # noqa: E402
from hybrid_retrieval import HybridRetriever  # noqa: E402


class V1Engine:
    """定案框架引擎: fd_bm25 (field_density 几何场 + BM25) RRF 融合，默认全库。"""

    def __init__(self, texts, vectors, doc_ids=None, rrf_k=60,
                 pool_mode=None, pool_k=5, pool_top_p=5):
        self.pool_mode = pool_mode          # None=全库 / "density"=连续盆地候选池
        self.pool_k = pool_k
        self.pool_top_p = pool_top_p
        # 向量 L2 归一化（防御除零）
        V = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(V, axis=1, keepdims=True)
        self.V = V / np.where(norms > 0, norms, 1.0)
        # 检索层组件
        self.field = FieldResponseGeometric(self.V, k=20, lam=0.15, density_sign=-1)
        self.hyb = HybridRetriever(texts, self.V, doc_ids=doc_ids, k=rrf_k)
        self._ms = None   # 延迟构建: 组织层 multiscale（离线语义分层工具）
        self._ds = None   # 延迟构建: 超大库密度盆地候选池

    # ── 组织层（延迟构建，离线语义分层/压缩工具） ────────────────────────

    def _ensure_ms(self):
        if self._ms is None:
            from multiscale_v2 import MultiScaleSpace
            ms = MultiScaleSpace(self.V)
            ms.build_hierarchy(k_schedule=[max(2, len(self.V) // 5)], max_levels=5,
                               sim_threshold=0.5, refine=True)
            self._ms = ms
        return self._ms

    @property
    def ms(self):
        return self._ensure_ms()

    def subspace(self, qvec, level=None, pool_top=None):
        """多尺度候选池（仅对比/离线评估用，不在默认检索路径）。"""
        ms = self._ensure_ms()
        level = min(3 if level is None else level, ms.n_levels)
        pool_top = 3 if pool_top is None else pool_top
        proj = ms.project_to_level(level)
        q = np.asarray(qvec, dtype=np.float32)
        qn = np.linalg.norm(q)
        q = q / qn if qn > 0 else q
        sims = ms.get_centroids(level) @ q
        top = np.argsort(-sims)[:pool_top]
        idx = np.unique(np.concatenate([np.where(proj == b)[0] for b in top]))
        return set(int(i) for i in idx)

    def level_sizes(self):
        """组织层每层簇数列表（含 level 0 = 原文档数）。"""
        return [self.ms.get_level_size(l) for l in range(self.ms.n_levels + 1)]

    def coarse_map(self, level=None):
        """{簇id: [doc索引, ...]}，默认 self.level（=3）。"""
        ms = self.ms
        level = min(3 if level is None else level, ms.n_levels)
        proj = ms.project_to_level(level)
        return {int(c): [int(i) for i in np.where(proj == c)[0]]
                for c in np.unique(proj)}

    # ── 检索层 ─────────────────────────────────────────────────────────

    def _candidates(self, qvec):
        """候选池: None=全库（默认）/ density=连续盆地 top-p 并集（超大库）。"""
        if self.pool_mode == "density":
            if self._ds is None:
                from density_space import DensitySpace
                self._ds = DensitySpace(self.V, k=self.pool_k)
            return self._ds.pool_multi(qvec, top_p=self.pool_top_p)
        return None

    def _fd_order(self, qvec, pool=None):
        """field_density 全局得分降序；pool=None 全库，否则过滤到池内。"""
        s = self.field.scores(qvec, "density")
        order = np.argsort(s)[::-1]
        if pool is None:
            return [int(i) for i in order]
        p = set(pool)
        return [int(i) for i in order if i in p]

    def search(self, qvec, qtext, top_k=10, subset=None):
        """定案检索（默认全库）: [field_density 序, BM25 序] → RRF 融合 → top_k。

        subset 非空则与候选池交集做硬过滤（交集空则回退 subset）。
        """
        pool = self._candidates(qvec)          # None = 全库
        if subset:
            inter = (pool & set(subset)) if pool else set(subset)
            pool = inter if inter else set(subset)
        rankings = [self._fd_order(qvec, pool),
                    self.hyb._rank_bm25(qtext, subset=pool)]
        return self.hyb._rrf(rankings)[:top_k]


def _self_check():
    """合成自检: 60 文档 16 维随机向量 + 一个主题聚类，查询取主题附近向量。"""
    n, dim = 60, 16
    rng = np.random.default_rng(42)
    texts = [f"doc {i} 泛化内容 filler" for i in range(n)]
    for i in range(10, 20):
        texts[i] = "主题聚类 shared topic keyword 特化内容"
    V = rng.standard_normal((n, dim)).astype(np.float32)
    center = rng.standard_normal(dim).astype(np.float32)
    V[10:20] += 4.0 * center
    qvec = (center + rng.standard_normal(dim) * 0.05).astype(np.float32)

    eng = V1Engine(texts, V)
    res = eng.search(qvec, "主题聚类 topic keyword", top_k=10)
    assert len(res) == 10, f"应返回 10 个结果，实际 {len(res)}"
    assert all(0 <= i < n for i in res), f"结果索引越界: {res}"
    # 主题文档应占头部（语义+词法双命中）
    assert len(set(res[:5]) & set(range(10, 20))) >= 3, f"主题命中不足: {res[:5]}"
    # 组织层延迟构建: 仅显式调用才触发
    assert eng._ms is None, "默认路径不应构建 multiscale"
    print("search 返回:", res)
    print("层大小:", eng.level_sizes())          # 触发组织层 lazy 构建
    print("level 1 簇数:", len(eng.coarse_map(1)))
    print("OK: V1Engine 全库 fd_bm25 自检通过")


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    _self_check()