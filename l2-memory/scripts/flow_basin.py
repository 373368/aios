# -*- coding: utf-8 -*-
"""多尺度连续流盆地（MultiScaleFlow）— 连续分块的多尺度 RG 流。

用户方向（b7 定案后延续）：
- 连续密度盆地已证 = 候选池物理裁剪器（质量基本持平）
- 质量提升方向 = 多尺度连续 RG 流：同一嵌入空间多档尺度盆地族，
  查询沿「细 → 粗」尺度流动（细盆地置信不足 → 上抛粗盆地），
  跨尺度并集 = 层级间流动连续 + 分块边界在尺度间保持（无离散聚类的大簇吞并）。

与贪心多层次压缩（MultiScaleSpace/block_spin）的区别：
- 贪心：单次贪心吸收 + 逐层对质心再粗粒化 → 离散块、层次靠投影链
- 本组件：每层独立密度盆地（无参数聚类、天然平衡）→ 连续流

用法：
  from flow_basin import MultiScaleFlow
  mf = MultiScaleFlow(vectors, k_schedule=[5, 15, 40])   # 细/中/粗三档
  pool, stats = mf.pool_flow(qvec)          # RG 流：细→粗上抛
  pool_m, stats = mf.pool_multi_flow(qvec)  # 跨尺度并集（连续响应区）
"""
import numpy as np

from density_space import DensitySpace


def _normalize(V):
    norms = np.linalg.norm(V, axis=1, keepdims=True)
    return np.asarray(V, np.float32) / np.where(norms > 0, norms, 1.0)


class MultiScaleFlow:
    """多尺度密度盆地族 + RG 流候选池。

    k_schedule: [细 k, 中 k, 粗 k] 每档构造独立 DensitySpace 盆地族。
    尺度层级：k 越大越粗（更大盆地、更少峰）。
    """

    def __init__(self, V, k_schedule=(5, 15, 40), flow_threshold=0.35, top_p=5, seed=0):
        self.V = _normalize(np.asarray(V, np.float32))
        self.n = len(self.V)
        self.scales = []
        for k in k_schedule:
            k = min(k, max(2, self.n - 1))
            self.scales.append(DensitySpace(self.V, k=k))
        self.k_schedule = [min(k, max(2, self.n - 1)) for k in k_schedule]
        self.flow_threshold = flow_threshold
        self.top_p = top_p
        self._rng = np.random.default_rng(seed)

    # ── 单尺度池（委托 DensitySpace）──
    def pool_scale(self, qvec, si):
        """单尺度响应：si=0 细 / -1 粗。返回 (pool, stats)。"""
        return self.scales[si].pool_multi(qvec, top_p=self.top_p)

    # ── RG 流：细 → 粗（置信不足上抛）──
    def pool_flow(self, qvec):
        """查询从细尺度出发，置信不足逐级上抛粗尺度。返回 (pool, stats)。

        置信 = 该尺度 top 盆地质心相似度峰值。低于 flow_threshold 时，
        该尺度候选不可信 → 上抛更粗尺度（更大盆地、更全候选）。
        语义：连续流在尺度间的流动 = RG 流（分辨率不足就放大尺度）。
        """
        q = _normalize(np.asarray(qvec, np.float32).reshape(1, -1)).ravel()
        pool = set()
        conf = []
        for si in range(len(self.scales)):
            ds = self.scales[si]
            roots, cents = ds.basin_index()
            sims = {r: float(cents[r] @ q) for r in roots}
            sel = [r for r in sorted(roots, key=sims.get, reverse=True)
                   if sims[r] > 0][:self.top_p]
            cur = set()
            for r in sel:
                cur |= set(roots[r])
            peak_sim = sims[sel[0]] if sel else 0.0
            pool |= cur
            conf.append(peak_sim)
            if peak_sim >= self.flow_threshold:
                break  # 置信足够，停在当前尺度
        stats = {"scales_used": len(conf), "confidence": [round(c, 3) for c in conf],
                 "pool_size": len(pool), "compression": len(pool) / self.n}
        return pool, stats

    # ── 跨尺度并集（连续响应区：多尺度各自支撑 → 并集）──
    def pool_multi_flow(self, qvec):
        """所有尺度的 top 盆地并集（跨尺度总响应区）。"""
        pool = set()
        sizes, conf = [], []
        for ds in self.scales:
            p, st = ds.pool_multi(qvec, top_p=self.top_p)
            pool |= p
            sizes.append(len(p))
            conf.append(st["sel_basins"])
        stats = {"pool_size": len(pool), "compression": len(pool) / self.n,
                 "per_scale": sizes, "confidence": conf}
        return pool, stats

    def basin_stats_all(self):
        """每尺度盆地大小分布（验证平衡性）。"""
        out = []
        for k, ds in zip(self.k_schedule, self.scales):
            st = ds.basin_stats()
            out.append({"k": k, "n_basins": st["n_basins"], "max": st["max"],
                        "mean": round(st["mean"], 2), "coverage_pct": st["coverage_pct"]})
        return out

    # ── 贪心多层次压缩对比方（block_spin 层次投影池）──
    def greedy_pool(self, qvec, ms, top_blocks=5):
        """贪心多层次压缩的候选池：在各层质心取 top_blocks 块并集（投影到叶）。

        对比语义：贪心层次「块」是离散块（block_spin 贪心吸收），
        候选 = 顶层 top-block 投影到叶的并集。
        """
        q = _normalize(np.asarray(qvec, np.float32).reshape(1, -1)).ravel()
        pool = set()
        project = np.arange(self.n)
        for l in range(1, ms.n_levels + 1):
            cents = ms.get_centroids(l)
            labels = ms.project_to_level(l)
            s = cents @ q
            sel = np.argsort(-s)[:top_blocks]
            for ci in sel[np.isin(sel, np.unique(labels))]:
                pool |= set(int(i) for i in np.where(labels == ci)[0])
        return pool


if __name__ == "__main__":
    # self-check: RG 流在无支撑区上抛粗尺度（池变大），有支撑区停细尺度
    rng = np.random.default_rng(3)
    # 有结构主题区（可支撑查询） + 无结构散点区
    theme = rng.normal(0, 0.08, (150, 64)) + np.array([2.0, 0.0] + [0.0] * 62)
    noise = rng.normal(0, 0.5, (400, 64))
    V = _normalize(np.vstack([theme, noise]))
    mf = MultiScaleFlow(V, k_schedule=[5, 15, 40])

    print("盆地尺寸（每尺度）:")
    for b in mf.basin_stats_all():
        print(f"  k={b['k']}: {b['n_basins']} 盆地, max={b['max']}, mean={b['mean']}")

    q_theme = np.zeros(64, dtype=np.float32); q_theme[0] = 2.0
    q_theme = _normalize(q_theme.reshape(1, -1)).ravel()
    q_noise = _normalize(rng.normal(0, 0.5, (1, 64)).astype(np.float32)).ravel()

    p1, s1 = mf.pool_flow(q_theme)
    p2, s2 = mf.pool_flow(q_noise)
    print(f"\n主题查询: 池={len(p1)} ({s1['compression']:.0%}) 置信={s1['confidence']} 尺度={s1['scales_used']}")
    print(f"无支撑查询: 池={len(p2)} ({s2['compression']:.0%}) 置信={s2['confidence']} 尺度={s2['scales_used']}")
    assert s1["scales_used"] < s2["scales_used"], "主题查询应停在细尺度，无支撑应流入更多尺度"
    print("\nself-check OK: RG 流按置信在尺度间流动",
          f"(主题停在 {s1['scales_used']} 尺度, 无支撑流入 {s2['scales_used']} 尺度)")