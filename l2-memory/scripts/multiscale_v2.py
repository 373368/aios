"""MultiScale memory space v2 — true RG-inspired hierarchical coarse-graining.

RG core ideas implemented:
  1. Iterative coarse-graining: R applied repeatedly across levels
  2. Relevant variables: centroids that persist across scales
  3. Fixed point detection: when structure stops changing
  4. Cross-level navigation: search at any level of granularity

Hierarchy:
  Level 0: original documents (n docs)
  Level 1: first coarse-grain (k1 clusters)
  Level 2: coarse-grain Level 1 centroids (k2 clusters)
  ...
  Level L: fixed point or minimum size reached

numpy only.
"""
from __future__ import annotations

import numpy as np

from block_spin import block_spin_coarse


def _normalize(v):
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def _kmeans(vectors, k, seed=42, iters=50):
    """Simple numpy k-means (k-means++ init). Returns (labels, centroids)."""
    rng = np.random.default_rng(seed)
    n = vectors.shape[0]
    if n <= k:
        return np.arange(n), _normalize(vectors)
    # k-means++ seeding
    centroids = [vectors[rng.integers(n)]]
    for _ in range(1, k):
        d = np.min(np.array([np.sum((vectors - c) ** 2, axis=1) for c in centroids]), axis=0)
        centroids.append(vectors[rng.choice(n, p=d / d.sum())])
    centroids = np.array(centroids)
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        sims = vectors @ centroids.T
        new_labels = sims.argmax(axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for j in range(k):
            m = vectors[labels == j]
            if len(m):
                centroids[j] = _normalize(m.mean(axis=0, keepdims=True))[0]
    return labels, centroids


class MultiScaleSpace:
    """True multi-scale hierarchy inspired by RG flow.

    Each level applies the same coarse-graining operator R to the previous level:
      Level 0: raw documents
      Level 1: R(Level 0) = k-means on documents → centroids
      Level 2: R(Level 1) = k-means on Level 1 centroids → super-centroids
      ...

    Fixed point: when centroids stop changing between levels.
    """
    def __init__(self, vectors):
        self.base = _normalize(np.asarray(vectors, dtype=np.float32))
        self.levels = []  # [(labels, centroids), ...] for each coarse-grained level
        self.level_vectors = [self.base]  # vectors input to each level
        self.n_levels = 0
        self._fixed_point = None

    def build_hierarchy(self, k_schedule=None, max_levels=10, fixed_point_threshold=0.95,
                        sim_threshold=0.5, refine=True):
        """Build multi-scale hierarchy by iteratively coarse-graining.

        Coarse-graining uses the RG block-spin operator (greedy nearest-centroid
        absorption) — single-pass, iteration-free, structurally closer to RG
        than global k-means, and ~470x faster on 2870 docs.

        Args:
            k_schedule: list of k values per level, or None for auto (halve each time)
            max_levels: maximum levels before stopping
            fixed_point_threshold: cosine sim threshold to detect fixed point
            sim_threshold: block-spin absorption threshold (open new block if
                a vector is below this to every current block)
            refine: if True, refine to exactly k blocks per level (fixed-k
                comparison); if False, keep the natural block count from
                threshold absorption
        """
        self.levels = []
        self.level_vectors = [self.base]
        current_vectors = self.base

        for level in range(max_levels):
            n = len(current_vectors)

            # Determine k for this level
            if k_schedule and level < len(k_schedule):
                k = k_schedule[level]
            else:
                k = max(2, n // 5)  # auto: ~20% of current size

            if n <= k or n <= 2:
                break  # too few vectors to cluster

            labels, centroids = block_spin_coarse(current_vectors, k,
                                                  sim_threshold=sim_threshold,
                                                  seed=42 + level)
            if refine and len(centroids) < k and len(centroids) > 0:
                from block_spin import refine_to_k
                labels, centroids = refine_to_k(labels, centroids, current_vectors, k,
                                                sim_threshold=sim_threshold)
            self.levels.append((labels, centroids))
            self.level_vectors.append(centroids)

            # Fixed point: blocks stop changing between levels. Compare each
            # current centroid to its BEST-MATCH in the previous level AND the
            # reverse (symmetric match) — a true fixed point requires the two
            # levels to describe the same blocks, not just "every centroid is
            # near *some* previous centroid" (which is trivially true).
            if level > 0:
                prev_centroids = self.levels[-2][1]
                fwd = np.max(centroids @ prev_centroids.T, axis=1)  # each cur -> best prev
                back = np.max(prev_centroids @ centroids.T, axis=1)  # each prev -> best cur
                # coverage: how well each set is represented by the other, in both directions
                coverage = 0.5 * (fwd.mean() + back.mean())
                if coverage >= fixed_point_threshold and len(centroids) >= len(prev_centroids) * 0.8:
                    self._fixed_point = level
                    break

            current_vectors = centroids

        self.n_levels = len(self.levels)
        return self

    @property
    def fixed_point_level(self):
        """Level at which fixed point was detected, or None."""
        return self._fixed_point

    def get_labels(self, level):
        """Get cluster labels at a specific level.

        Level 0 = each doc is its own cluster (identity).
        Level i = labels from i-th coarse-graining.
        """
        if level == 0:
            return np.arange(len(self.base))
        return self.levels[level - 1][0]

    def get_centroids(self, level):
        """Get centroids at a specific level.

        Level 0 = original documents.
        Level i = centroids from i-th coarse-graining.
        """
        if level == 0:
            return self.base
        return self.levels[level - 1][1]

    def navigate(self, query_vec, level):
        """Find the best-matching cluster at a given level.

        Returns (cluster_index, similarity).
        """
        q = _normalize(np.asarray(query_vec, dtype=np.float32).reshape(1, -1))
        centroids = self.get_centroids(level)
        sims = (centroids @ q.T).ravel()
        best_idx = int(sims.argmax())
        return best_idx, float(sims[best_idx])

    def navigate_path(self, query_vec):
        """Navigate from root (level 0) to leaf, returning the path.

        Returns list of (level, cluster_idx, similarity) at each level.
        """
        path = []
        current_centroids = self.base
        q = _normalize(np.asarray(query_vec, dtype=np.float32).reshape(1, -1))

        for level in range(self.n_levels + 1):
            centroids = self.get_centroids(level)
            sims = (centroids @ q.T).ravel()
            best_idx = int(sims.argmax())
            path.append((level, best_idx, float(sims[best_idx])))

        return path

    def project_to_level(self, level):
        """Assign every ORIGINAL doc to its cluster at the given level.

        Each level's labels index the *previous* level's vectors (which are
        centroids), so to map the base docs to a coarse level we follow the
        absorption chain: base doc -> level-1 block -> level-2 block -> ...
        A coarse-level cluster is non-empty iff at least one original doc
        reaches it, so coverage here is measured over the full 2870 docs.

        Returns an (n,) int array: cluster id per original doc at `level`.
        """
        if level <= 0:
            return np.arange(len(self.base))
        # start: each base doc is its own node
        cur = np.arange(len(self.base))
        for l in range(1, level + 1):
            labels = self.levels[l - 1][0]   # maps level-(l-1) nodes -> level-l clusters
            cur = labels[cur]                 # propagate assignment one level down
        return cur

    def get_level_size(self, level):
        """Get number of clusters at a level."""
        return len(self.get_centroids(level))

    def compression_ratio(self, level):
        """Compression ratio at a level (original docs / clusters at level)."""
        return len(self.base) / max(self.get_level_size(level), 1)

    def summary(self):
        """Print summary of the hierarchy."""
        print(f"=== MultiScale Hierarchy ===")
        print(f"Documents: {len(self.base)}")
        print(f"Levels: {self.n_levels}")
        if self._fixed_point is not None:
            print(f"Fixed point detected at level {self._fixed_point}")
        for level in range(self.n_levels + 1):
            n_clusters = self.get_level_size(level)
            cr = self.compression_ratio(level)
            print(f"  Level {level}: {n_clusters} clusters ({cr:.1f}x compression)")
