# -*- coding: utf-8 -*-
"""连续密度空间：密度场 + 盆地分块（连续替代离散聚类）。

用户方向（语义空间是连续流形，分块 = 密度天然划分）：
- 密度 rho[i] = k-NN 平均相似度（局部密度），不需要指定簇数
- 盆地归属：每个文档沿「更高密度近邻」爬升（mean-shift 式密度峰追踪），
  递归收敛到局部密度峰 → 盆地根 = 峰文档 id
- 块 = 盆地：有多少文档落在盆地它就是多大；无文档区域 = 空语义（无支撑）
- 候选池 = 查询 q 的响应盆地（q 从其高密度邻居爬升到的峰所属盆地）

连续分块的性质（相对离散聚类的改进）：
- 无 k 参数，天然平衡（大簇吞并不可能，密度峰局部决定归属）
- 无支撑区自动为空：查询落入低密度区时盆地很小 → 干净小候选池
- 密度峰即「语义核心」，盆地边界即「语义边界」

用法：
  from density_space import DensitySpace
  ds = DensitySpace(vectors, k=20)
  pool, stats = ds.pool(qvec)   # stats: 盆地大小/峰密度
"""
import numpy as np


def _normalize(V):
    norms = np.linalg.norm(V, axis=1, keepdims=True)
    return np.asarray(V, np.float32) / np.where(norms > 0, norms, 1.0)


class DensitySpace:
    """连续密度空间：rho（局部密度）+ 盆地归属（密度峰追踪）."""

    def __init__(self, V, k=20):
        self.n = len(V)
        self.k = min(k, max(1, self.n - 1))
        V = _normalize(V)
        self.V = V
        S = V @ V.T
        np.fill_diagonal(S, -np.inf)  # 排除自身
        self.sim = S
        # k-NN（按相似度 top-k）
        self.knn = np.argsort(-S, axis=1)[:, : self.k]
        # 密度 = k-NN 平均相似度
        self.rho = S[np.arange(self.n)[:, None], self.knn].mean(axis=1)
        # 盆地归属：沿更高密度近邻爬升
        nbr_rho = self.rho[self.knn]  # (n,k)
        best = nbr_rho.argmax(axis=1)  # (n,) 每行最高密度近邻列
        best_rho = nbr_rho[np.arange(self.n), best]  # (n,)
        self.parent = np.where(best_rho > self.rho,
                               self.knn[np.arange(self.n), best], np.arange(self.n))
        # 峰缓存：每个文档的盆地根
        self._root_cache = {}

    def root(self, i):
        """沿 parent 链爬到盆地根（局部密度峰文档 id）。"""
        r = self._root_cache.get(i)
        if r is None:
            seen = set()
            j = int(i)
            while self.parent[j] != j and self.parent[j] not in seen:
                seen.add(j)
                j = int(self.parent[j])
            r = int(self.parent[j])
            self._root_cache[i] = r
        return r

    def basin_members(self, root_id):
        """盆地根 = root_id 的全部文档（连续分块 = 密度盆地）。"""
        return {int(i) for i in range(self.n) if self.root(i) == root_id}

    def basin_stats(self):
        """盆地大小分布（验证连续分块平衡性：无大簇吞并）。"""
        from collections import Counter
        roots = Counter(self.root(i) for i in range(self.n))
        sizes = sorted(roots.values(), reverse=True)
        return {"n_basins": len(roots), "size": sizes,
                "mean": float(np.mean(sizes)), "max": sizes[0],
                "median": float(np.median(sizes)),
                "coverage_pct": float(len(roots) / self.n * 100)}

    def pool(self, qvec, return_all=False):
        """查询 q 的响应盆地。返回 (候选池 set, stats dict)。

        q 归属：q 从其 k-NN 文档中密度最高的那个出发，沿 parent 爬升到峰。
        候选池 = 该峰所属盆地（有多少落在这块就是多少）。
        """
        q = _normalize(np.asarray(qvec, np.float32).reshape(1, -1)).ravel()
        s = self.V @ q
        nn = np.argsort(-s)[: self.k]
        nn = nn[s[nn] > 0]
        if len(nn) == 0:
            return set(), {"peak_density": 0.0, "pool_size": 0, "unsupported": True}
        peak = self.root(nn[np.argmax(self.rho[nn])])
        members = self.basin_members(peak)
        stats = {"peak_density": float(self.rho[peak]), "pool_size": len(members),
                 "unsupported": len(members) < max(2, self.k)}
        if return_all:
            return members, stats
        return members, stats

    def basin_index(self):
        """盆地索引：{root_id: [成员索引]} + {root_id: 质心}（归一化均值）。"""
        if getattr(self, "_bi", None) is None:
            roots = {}
            for i in range(self.n):
                roots.setdefault(self.root(i), []).append(i)
            cents = {}
            for r, idxs in roots.items():
                cents[r] = _normalize(self.V[idxs].mean(axis=0).reshape(1, -1)).ravel()
            self._bi = (roots, cents)
        return self._bi

    def pool_multi(self, qvec, top_p=5):
        """多盆地响应：盆地质心与查询相似度 top-P 盆地的并集。

        连续场「响应区」：不是单落点盆地，而是查询支撑的多个盆地
        （跨语义区证据可被多个盆地分别支撑）。跨盆地=连续流流动。
        """
        roots, cents = self.basin_index()
        q = _normalize(np.asarray(qvec, np.float32).reshape(1, -1)).ravel()
        sims = {r: float(cents[r] @ q) for r in roots}
        sel = [r for r in sorted(roots, key=sims.get, reverse=True)
               if sims[r] > 0][:top_p]
        pool = set()
        for r in sel:
            pool |= set(roots[r])
        return pool, {"sel_basins": sorted([round(sims[r], 3) for r in sel], reverse=True),
                      "pool_size": len(pool)}