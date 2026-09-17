# -*- coding: utf-8 -*-
"""
知识库检索：查询 → 向量 → cosine/v1(定案框架) → top-k 结果 + 行为记录。

用法：
  python search_index.py "量子纠缠和EPR佯谬"                      # top-5, v1 (定案框架)
  python search_index.py "量子纠缠" --k 10
  python search_index.py "量子纠缠" --json                         # 机器可读（供 AI 调用）
  python search_index.py "量子纠缠" --no-log                       # 不写行为记录
  python search_index.py "量子纠缠" --engine cosine --kind qwen   # 旧余弦引擎
  python search_index.py "量子纠缠" --rerank                       # v1 检索后 Qwen3-Reranker 重排（可选，默认关闭）
"""
import argparse
import json
import math
import os
import sys
import time
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedders import load_config, make_embedder
from rerank import make_reranker
import paths as _paths

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

INDEX_BASE = _paths.INDEX_DIR
BEHAVIOR_DIR = _paths.BEHAVIOR_DIR


def load_index(kind):
    INDEX_DIR = os.path.join(INDEX_BASE, kind)
    idx = json.load(open(os.path.join(INDEX_DIR, "index.json"), encoding="utf-8"))
    meta = json.load(open(os.path.join(INDEX_DIR, "meta.json"), encoding="utf-8"))
    import numpy as np
    vectors = np.load(os.path.join(INDEX_DIR, "vectors.npy"))
    return idx, meta, vectors


def cosine_sim(u, v):
    return float(u @ v / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-12))


def log_behavior(query, results, k, trigger="手动"):
    """行为拓扑采集：写 03-日志/行为记录/YYYY-MM-DD.md"""
    if not os.path.isdir(BEHAVIOR_DIR):
        os.makedirs(BEHAVIOR_DIR)
    day = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%H:%M:%S")
    fp = os.path.join(BEHAVIOR_DIR, f"{day}.md")
    header = f"# 行为记录 {day}\n"
    entry = (
        f"## 检索\n"
        f"- {ts} 查询「{query}」top-{k} 触发:{trigger}\n"
        f"  - 命中: " + "; ".join(f"{r['path']}({r['score']:.3f})" for r in results) + "\n"
    )
    if os.path.exists(fp):
        with open(fp, "a", encoding="utf-8") as f:
            f.write("\n" + entry)
    else:
        with open(fp, "w", encoding="utf-8") as f:
            f.write(header + "\n" + entry)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="查询文本")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--kind", default="", help="embedder 类型(qwen/ollama)，默认读 config.json")
    ap.add_argument("--key", default=load_config().get("api_key", ""))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-log", action="store_true")
    ap.add_argument("--engine", default="v1", choices=["cosine", "v1"],
                    help="检索引擎: v1 (定案框架, 默认) / cosine (旧基线)")
    ap.add_argument("--rerank", action="store_true",
                    help="v1 检索后用 Qwen3-Reranker-8B 重排 top-k（默认关闭；经 LoCoMo 三粒度验证显著提升精确证据定位）")
    ap.add_argument("--rerank-cand", type=int, default=50,
                    help="rerank 候选池大小（送入重排的文档数，默认 50）")
    args = ap.parse_args()

    cfg = load_config()
    kind = args.kind or cfg.get("kind", "qwen")
    INDEX_DIR = os.path.join(INDEX_BASE, kind)
    if not os.path.isfile(os.path.join(INDEX_DIR, "vectors.npy")):
        print(f"错误：索引不存在（{INDEX_DIR}），先运行 build_index.py --kind {kind}")
        sys.exit(1)

    idx, meta, vectors = load_index(kind)
    kwargs = {}
    if kind == "qwen":
        key = args.key or cfg.get("api_key", "")
        if not key:
            print("错误：qwen 缺少 API key。请在 config.json 的 embedding.api_key 填写，或用 --key")
            sys.exit(1)
        kwargs = {"api_key": key}
    elif kind == "ollama":
        kwargs = {"model": cfg.get("ollama_model", "Qwen3-Embedding-8B:latest"),
                  "base": cfg.get("ollama_base", "http://localhost:11434")}

    embedder = make_embedder(kind, **kwargs)
    [qv] = embedder.embed([args.query])
    qv = np.array(qv, dtype=np.float32)

    t0 = time.time()
    if args.engine == "cosine":
        # 余弦检索（默认）
        scores = [cosine_sim(qv, v) for v in vectors]
        top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[: args.k]
        results = []
        for i in top:
            m = meta[i]
            results.append({"path": m["path"], "title": m["title"],
                            "skeleton": m["skeleton"], "score": round(scores[i], 4)})
    elif args.engine == "v1":
        # 定案框架: fd_bm25 全库 (field_density 几何场 + BM25 RRF)
        # 2026-08-22: multiscale 候选池移出默认路径（实测压缩比 1.06x 无裁剪行为）
        from memory_v1 import V1Engine
        tp = os.path.join(INDEX_DIR, "texts.json")
        if not os.path.isfile(tp):
            print(f"错误：索引缺少 texts.json，请先运行 build_index.py --kind {kind}")
            sys.exit(1)
        texts = json.load(open(tp, encoding="utf-8"))
        eng = V1Engine(texts, vectors, doc_ids=[m["path"] for m in meta])
        # rerank 模式: 先取更大候选池，再 cross-encoder 重排取 top-k
        top = args.rerank_cand if args.rerank else args.k
        hits = eng.search(qv, args.query, top_k=top)
        if args.rerank:
            t_rk = time.time()
            cand_texts = [texts[i][:2500] for i in hits]
            rk = make_reranker()
            scores = dict((hits[pos], s) for pos, s in rk.rerank(args.query, cand_texts))
            hits = sorted(scores, key=lambda i: -scores[i])[: args.k]
            dt_rk = (time.time() - t_rk) * 1000
        results = []
        for rank, i in enumerate(hits):
            m = meta[i]
            results.append({"path": m["path"], "title": m["title"],
                            "skeleton": m["skeleton"],
                            "score": round(1.0 / (rank + 1), 4),
                            "snippet": " ".join((texts[i] or "")[:280].split())})
    dt = (time.time() - t0) * 1000

    if args.json:
        extra = {"rerank": args.rerank, "rerank_ms": round(dt_rk)} if args.rerank else {}
        print(json.dumps({"query": args.query, "k": args.k, "ms": round(dt), **extra,
                          "results": results}, ensure_ascii=False, indent=2))
    else:
        suffix = f" +rerank({dt_rk:.0f}ms)" if args.rerank else ""
        print(f"查询: {args.query}  ({dt:.0f}ms{suffix}, 索引 {len(meta)} 页, embedder={idx['embedder_name']})")
        for r in results:
            print(f"  {r['score']:.4f}  [{r['skeleton']}] {r['title']}  ({r['path']})")

    if not args.no_log:
        log_behavior(args.query, results, args.k)


if __name__ == "__main__":
    main()