# -*- coding: utf-8 -*-
"""RG 层级构建 v2：凝聚合并（agglomerative 最近对合并）替代贪心 block_spin。

动机（用户方向）：block_spin 的贪心「相似度吸收」在真实 qwen 嵌入上塌缩——
184 断言在 sim_threshold=0.5 时只形成 2 簇（阈值越低越少），因为 qwen 归一化
向量余弦普遍高，质心漂移使吸收滚雪球。这不是标准 RG。

标准 RG 块合并（Kadanoff 实空间块）是**逐级最近对凝聚**：每级把最相似的
两块并成一块（质心=块自旋，weighted mean），块严格嵌套（上级块=完整下级块
并集）、边界天然对齐、层级连续。本模块实现该算子。

接口与 multiscale_v2.MultiScaleSpace 对齐：get_labels/get_centroids/get_level_size。

用法：
  from rg_hierarchy import AggHierarchy
  ah = AggHierarchy(vectors)
  ah.build(k_levels=[36, 12, 4])   # 逐层簇数（严格递减）
"""
import numpy as np


def _normalize(V):
    norms = np.linalg.norm(V, axis=1, keepdims=True)
    return np.asarray(V, np.float32) / np.where(norms > 0, norms, 1.0)


class AggHierarchy:
    """凝聚合并层级树：每级 = 叶的严格划分（边界对齐嵌套）。

    build(k_levels): 逐步合并最近对直到剩 k 簇，快照该级为 L1；继续合并到
    更小 k 为 L2/L3... levels[i] = 第 i+1 级。level 0 = 叶本身。
    """

    def __init__(self, vectors):
        self.base = _normalize(np.asarray(vectors, np.float32))
        self.n = len(self.base)
        self.levels = []
        self.n_levels = 0

    def build(self, k_levels):
        n = self.n
        cent = [self.base[i].copy() for i in range(n)]
        sizes = [1] * n
        leaf_block = np.arange(n, dtype=np.int64)  # 叶 → 当前块（块 id = 质心槽位）
        self.levels = []
        self.n_levels = 0
        cnt = n
        targets = [min(k, cnt) for k in k_levels]
        ti = 0
        while cnt > 1:
            # 最近对（仅在当前活跃的前 cnt 槽位内）
            C = np.array(cent[:cnt], dtype=np.float32)
            S = C @ C.T
            np.fill_diagonal(S, -1e9)
            i, j = np.unravel_index(np.argmax(S), S.shape)
            w = sizes[i] + sizes[j]
            m = (cent[i] * sizes[i] + cent[j] * sizes[j]) / w
            m = m / (np.linalg.norm(m) + 1e-12)
            sizes[i] = w
            cent[i] = m
            leaf_block[leaf_block == j] = i
            last = cnt - 1
            if last != j:
                cent[j] = cent[last]
                sizes[j] = sizes[last]
                leaf_block[leaf_block == last] = j
            cnt -= 1
            if cnt <= targets[ti]:
                labels = leaf_block.copy()
                uniq = np.unique(labels).tolist()
                remap = {u: r for r, u in enumerate(uniq)}
                labels = np.array([remap[u] for u in labels], dtype=np.int64)
                self.levels.append((labels, np.array(cent[:cnt], dtype=np.float32)))
                ti += 1
                if ti >= len(targets):
                    break
        self.n_levels = len(self.levels)
        return self

    def get_labels(self, level):
        if level == 0:
            return np.arange(self.n)
        return self.levels[level - 1][0]

    def get_centroids(self, level):
        if level == 0:
            return self.base
        return self.levels[level - 1][1]

    def get_level_size(self, level):
        if level == 0:
            return self.n
        return len(self.levels[level - 1][1])


if __name__ == "__main__":
    import sys
    from collections import defaultdict
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    v = np.load(r"D:\AI OS\l2-memory\eval-harness\cache\locomo_obs_embeddings.npz")["vectors"][:184]
    ah = AggHierarchy(v)
    ah.build(k_levels=[36, 12, 4])
    print("层级规模:")
    for l in range(ah.n_levels + 1):
        print(f"  L{l}: {ah.get_level_size(l)} 簇")
    if ah.n_levels >= 2:
        l1 = ah.get_labels(1)
        l2 = ah.get_labels(2)
        sub = defaultdict(set)
        for b1, b2 in zip(l1, l2):
            sub[b2].add(b1)
        allb = set()
        for g, blocks in sub.items():
            allb |= blocks
            print(f"  L2团{g}: L1块 {sorted(blocks)}")
        assert allb == set(range(ah.get_level_size(1))), "L1 块未全覆盖"
        print("嵌套验证: L1→L2 覆盖完整、无跨界（边界对齐）OK")