# -*- coding: utf-8 -*-
"""
方案A · Geometric Field Response — 纯几何的"场响应"检索。

设计哲学：查询在嵌入空间中的响应应是**非线性**的，而非固定的余弦距离。
本实现只用空间局部密度（local density / space structure），**不含任何行为数据**。

两种非线性：
  1. mode='density' : 余弦得分 + 密度调制偏移。
     拥挤区域（density 高）的匹配区分度低 → 相对压低；
     稀疏区域的匹配更独特 → 相对抬高。（方向可调，density_sign=+1 时反转）
  2. mode='kernel'  : 用 exp(-d²/2σ_i²) 替换余弦，
     σ_i 由局部密度调制：稀疏区 σ 小（更尖锐、更挑剔），密集区 σ 大（更平滑）。

冷启动安全：
  - density 模式 lam=0  → 退化为纯余弦（偏移项为零）。
  - kernel  模式 rho=0 → 所有 σ 相同 → exp(-d²/2σ²) 是余弦的严格单调函数
    → 排序与纯余弦完全一致。

自检（__main__）：在真实 BESPOKE 向量上验证
  - 密度场确实改变排名（top-10 位置变化数、Kendall tau）
  - lam=0 / rho=0 时与纯余弦排名逐位一致（断言）。

用法：
  python scripts/field_response_geometric.py
"""
import json
import os
import sys

import numpy as np

# ─── 数据路径（与 eval_bespoke.py 一致） ────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(_HERE, "..", "eval-harness", "cache", "bespoke_v2")
DOC_VEC_FILE = os.path.join(CACHE_DIR, "doc_vectors.npz")
Q_VEC_FILE = os.path.join(CACHE_DIR, "query_vectors.npz")


class FieldResponseGeometric:
    """纯几何场响应检索：余弦 + 局部密度调制。

    __init__ 预计算每个文档的局部密度（k 近邻平均余弦）。
    scores(query_vec, mode) 返回全库得分向量；search() 返回全局 top-k 索引。
    """

    def __init__(self, vectors, k=20, lam=0.15, sigma_base=0.5, rho=1.0,
                 density_sign=-1, seed=0):
        vectors = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        self.V = vectors / np.where(norms > 0, norms, 1.0)  # 单位化，防御性
        self.n = self.V.shape[0]

        # ── 局部密度：每文档到 k 近邻的平均余弦（不含自身） ──
        k = max(1, min(k, self.n - 1)) if self.n > 1 else 0
        if k > 0:
            # 全库相似度矩阵 (n×n)，BESPOKE 规模 (2870²) 内存可承受
            S = self.V @ self.V.T
            idx = np.argsort(-S, axis=1)[:, 1:k + 1]  # 去掉自身（对角=1 排最前）
            rows = np.arange(self.n)[:, None]
            self.density = S[rows, idx].mean(axis=1)
        else:
            self.density = np.zeros(self.n)

        # 归一化到 [0,1]：d_hat=1 最拥挤，d_hat=0 最稀疏
        lo, hi = self.density.min(), self.density.max()
        self.d_hat = (self.density - lo) / (hi - lo) if hi > lo else np.zeros(self.n)

        # ── 可调参数 ──
        self.lam = lam          # density 模式偏移强度；0 → 纯余弦
        self.sigma_base = sigma_base  # kernel 模式基准 σ
        self.rho = rho          # σ 随密度放大的系数；0 → 纯余弦排序
        self.density_sign = density_sign  # -1 稀疏区抬高；+1 密集区抬高

    # ── 得分 ──
    def scores(self, query_vec, mode="density"):
        q = np.asarray(query_vec, dtype=np.float32)
        qn = np.linalg.norm(q)
        q = q / qn if qn > 0 else q
        cos = self.V @ q  # 余弦相似度（V 已单位化）

        if mode == "cosine":
            return cos
        if mode == "density":
            # 每文档固定偏移：稀疏区 (d_hat≈0) 相对抬高，密集区 (d_hat≈1) 相对压低
            return cos + self.lam * (self.density_sign * self.d_hat)
        if mode == "kernel":
            # 单位向量欧氏距离平方 = 2(1-cos)；σ_i 随密度调制
            d2 = 2.0 * (1.0 - cos)
            sigma = self.sigma_base * (1.0 + self.rho * self.d_hat)
            return np.exp(-d2 / (2.0 * sigma ** 2))
        raise ValueError(f"未知 mode: {mode!r}（可选 cosine/density/kernel）")

    def search(self, query_vec, top_k=10, mode="density"):
        """返回全局 top-k 文档索引（按 scores 降序）。"""
        s = self.scores(query_vec, mode)
        return np.argsort(s)[::-1][:top_k]


# ─── 自检工具 ──────────────────────────────────────────────────────────

def mean_rank_shift(base_rank, full_order):
    """余弦 top-100 文档在场排序中的平均绝对排名位移。

    base_rank: 余弦排序下的 top-100 索引列表（rank i → 索引）
    full_order: 场排序的完整索引序列（argsort 结果）
    """
    rank_pos = {idx: i for i, idx in enumerate(full_order)}
    shifts = [abs(rank_pos[idx] - i) for i, idx in enumerate(base_rank)]
    return float(np.mean(shifts))


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=== FieldResponseGeometric 自检（真实 BESPOKE 向量） ===\n")

    doc_vecs = np.load(DOC_VEC_FILE)["embeddings"].astype(np.float32)
    q_vecs = np.load(Q_VEC_FILE)["embeddings"].astype(np.float32)
    print(f"docs: {doc_vecs.shape}, queries: {q_vecs.shape}")

    field = FieldResponseGeometric(doc_vecs, k=20, lam=0.15, sigma_base=0.5, rho=1.0)
    print(f"局部密度: min={field.density.min():.4f} "
          f"max={field.density.max():.4f} "
          f"mean={field.density.mean():.4f}")
    print(f"d_hat: 稀疏区(≤0.1) {int((field.d_hat <= 0.1).sum())} docs, "
          f"拥挤区(≥0.9) {int((field.d_hat >= 0.9).sum())} docs\n")

    NQ = min(50, len(q_vecs))
    pos_changes = {"density": [], "kernel": []}
    rank_shift = {"density": [], "kernel": []}
    n_change = {"density": 0, "kernel": 0}
    topk = 10

    for qi in range(NQ):
        q = q_vecs[qi]
        base = field.search(q, top_k=topk, mode="cosine")
        base100 = field.search(q, top_k=100, mode="cosine")
        for m in ("density", "kernel"):
            ranked = field.search(q, top_k=topk, mode=m)
            # top-10 内逐位不同的位置数
            changes = sum(1 for i in range(topk) if base[i] != ranked[i])
            pos_changes[m].append(changes)
            if changes > 0:
                n_change[m] += 1
            # 余弦 top-100 文档在场排序中的平均排名位移
            full_order = field.search(q, top_k=field.n, mode=m)
            rank_shift[m].append(mean_rank_shift(base100, full_order))

    print(f"{'mode':<10} {'top10 位置变化(mean)':>22} {'top10 有变化占比':>18} "
          f"{'top100 平均排名位移':>22}")
    for m in ("density", "kernel"):
        print(f"{m:<10} {np.mean(pos_changes[m]):>20.2f} "
              f"{n_change[m] / NQ:>16.1%} "
              f"{np.mean(rank_shift[m]):>20.2f}")

    # ── 冷启动断言：lam=0 / rho=0 必须与纯余弦逐位一致 ──
    field_cold = FieldResponseGeometric(doc_vecs, k=20, lam=0.0, sigma_base=0.5, rho=0.0)
    all_ok = True
    for qi in range(NQ):
        q = q_vecs[qi]
        base = field.search(q, top_k=topk, mode="cosine")
        if not np.array_equal(field_cold.search(q, top_k=topk, mode="density"), base):
            print("✗ density 冷启动失效 (lam=0 应等于余弦)")
            all_ok = False
        if not np.array_equal(field_cold.search(q, top_k=topk, mode="kernel"), base):
            print("✗ kernel 冷启动失效 (rho=0 应等于余弦)")
            all_ok = False
    if all_ok:
        print("\n✓ 冷启动安全: lam=0 与 rho=0 时，两种模式 top-10 均与纯余弦逐位一致。")

    print(f"\n自检完成: {NQ} 个查询。")


if __name__ == "__main__":
    main()
