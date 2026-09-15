# -*- coding: utf-8 -*-
"""
Rerank 增强作用 A/B 测试（loomo + bespoke 基准，复用缓存，不重复 embedding）。

对比同一候选池（V1Engine fd_bm25 top-C）：
  baseline = 引擎原生排序 top-K        （当前增强搜索，无 rerank）
  rerank   = Qwen3-Reranker-8B 重排 top-K
指标：Hit@10 / MRR / NDCG@10 / Recall@10，逐查询 NDCG 胜/平/负。

LoCoMo 三粒度（--gran）：
  turns   corpus=turns（5882, dia_id）        qvecs=locomo_v1_query_vectors.npz
  obs     corpus=断言库（2541, dia_id 可多）  qvecs=locomo_obs_query_vectors.npz
  session corpus=session_summary（272, session_key） qvecs=locomo_obs_query_vectors.npz

rerank 分数按 (基准, 粒度, 查询) 缓存，断点可续跑；rerank 走 API 并发（--workers）。

用法：
  python eval_rerank_bench.py --bench locomo --gran all --workers 4   # LoCoMo 三粒度全量
  python eval_rerank_bench.py --bench bespoke                          # BESPOKE 全量
"""
import argparse
import json
import math
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HARNESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive", "eval-harness")
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
for p in (SCRIPTS, os.path.join(HARNESS, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from embedders import load_config  # noqa: E402
from memory_v1 import V1Engine  # noqa: E402
from rerank import make_reranker  # noqa: E402
import eval_bespoke as EB  # noqa: E402

CACHE = os.path.join(HARNESS, "cache")
RR_CACHE = os.path.join(CACHE, "rerank_scores.json")
LOC_DATA = os.path.join(HARNESS, "datasets", "locomo", "locomo10.json")
RERANK_MAX_CHARS = 2500


def load_cache():
    if os.path.isfile(RR_CACHE):
        return json.load(open(RR_CACHE, encoding="utf-8"))
    return {}


def save_cache(cache):
    json.dump(cache, open(RR_CACHE, "w", encoding="utf-8"), ensure_ascii=False)


def dia_set(d):
    """断言 dia_id 可能是 str 或 list（多 turn 引用）。"""
    return {d} if isinstance(d, str) else set(d)


def dia_to_session(dia_id):
    m = re.match(r"D(\d+)", dia_id)
    return f"session_{m.group(1)}" if m else None


# ═══════════════════════ LoCoMo：三粒度文档单元 ═══════════════════════

def build_gran_full(raw, meta, gran):
    """完整构建（含向量切分），返回 (by_conv, qvecs)。"""
    emb_file, qvec_file = {
        "turns":   ("locomo_embeddings.npz", "locomo_v1_query_vectors.npz"),
        "obs":     ("locomo_obs_embeddings.npz", "locomo_obs_query_vectors.npz"),
        "session": ("locomo_session_embeddings.npz", "locomo_obs_query_vectors.npz"),
    }[gran]
    emb_key = "embeddings" if gran == "turns" else "vectors"
    emb = np.load(os.path.join(CACHE, emb_file))[emb_key]
    qvecs = np.load(os.path.join(CACHE, qvec_file))["vectors"]

    # 统一构建 (texts, ids)，再按全局顺序切向量
    units, ids = [], []
    if gran == "turns":
        for gi, t in enumerate(meta["turns"]):
            units.append((t["conv_idx"], t["text"]))
            ids.append(t["dia_id"])
    elif gran == "obs":
        for ci, conv in enumerate(raw):
            for sk in sorted(conv["observation"].keys()):
                speakers = conv["observation"][sk]
                if isinstance(speakers, dict):
                    for lst in speakers.values():
                        for item in lst:
                            units.append((ci, item[0])); ids.append(item[1])
                else:
                    for item in speakers:
                        units.append((ci, item[0])); ids.append(item[1])
    else:  # session
        for ci, conv in enumerate(raw):
            for sk in sorted(conv.get("session_summary", {}).keys()):
                units.append((ci, conv["session_summary"][sk]))
                ids.append(sk.replace("_summary", ""))

    assert len(units) == len(emb), f"{gran}: units {len(units)} != emb {len(emb)}"
    by_conv = defaultdict(list)
    for i, (ci, text) in enumerate(units):
        by_conv[ci].append({"gi": i, "text": text, "id": ids[i]})
    for ci, items in by_conv.items():
        idx = [it["gi"] for it in items]
        by_conv[ci] = {"texts": [it["text"] for it in items],
                       "ids": [it["id"] for it in items],
                       "vecs": np.stack([emb[i] for i in idx])}
    return dict(by_conv), qvecs


def run_locomo(args, rk, cache):
    raw = json.load(open(LOC_DATA, encoding="utf-8"))
    meta = json.load(open(os.path.join(CACHE, "locomo_meta.json"), encoding="utf-8"))
    gran = args.gran
    by_conv, qvecs = build_gran_full(raw, meta, gran)

    engines = {ci: V1Engine(d["texts"], d["vecs"]) for ci, d in by_conv.items()}
    all_qa = [dict(qa, conv_idx=ci) for ci, conv in enumerate(raw) for qa in conv["qa"]]
    assert len(all_qa) == len(qvecs), f"qa {len(all_qa)} != qvecs {len(qvecs)}"

    t0 = time.time()
    # 第一遍：检索候选池（本地），决定哪些查询需 rerank
    items = []
    for qi, qa in enumerate(all_qa):
        if len(items) >= args.maxq:
            break
        relevant = set(qa.get("evidence", []))
        if not relevant:
            continue
        conv = by_conv[qa["conv_idx"]]
        qtext = qa["question"]
        qvec = qvecs[qi]
        cand = engines[qa["conv_idx"]].search(qvec, qtext, top_k=args.cand)
        key = f"locomo:{gran}:{qtext}"
        cached = (key in cache and all(str(i) in cache[key] for i in cand))
        items.append({"qi": qi, "qa": qa, "conv": conv, "key": key,
                      "qtext": qtext, "cand": cand, "cached": cached})

    # 第二遍：并发 rerank 缺失项
    missing = [it for it in items if not it["cached"]]
    if missing:
        def do_rerank(it):
            clipped = [it["conv"]["texts"][i][:RERANK_MAX_CHARS] for i in it["cand"]]
            rk_local = make_reranker()
            scores = {}
            for pos, s in rk_local.rerank(it["qtext"], clipped):
                scores[it["cand"][pos]] = s
            return it["key"], scores
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for i, (key, scores) in enumerate(ex.map(do_rerank, missing), 1):
                cache[key] = {str(j): scores[j] for j in scores}
                if i % 50 == 0:
                    print(f"  rerank {i}/{len(missing)} ({time.time()-t0:.0f}s)")
        save_cache(cache)

    # 第三遍：评估
    rows = []
    for it in items:
        qa, conv, key, cand = it["qa"], it["conv"], it["key"], it["cand"]
        relevant = set(qa.get("evidence", []))
        if gran == "session":
            relevant = {s for e in relevant if (s := dia_to_session(e))}
        def rel_of(order):
            if gran == "session":
                return [conv["ids"][i] for i in order]
            return [d for i in order for d in dia_set(conv["ids"][i])]
        scores = {int(k): v for k, v in cache[key].items()}
        reranked = sorted(scores, key=lambda i: -scores[i])[: args.k]
        base = cand[: args.k]
        def eval_order(order):
            rel = rel_of(order)
            hits = [d for d in rel if d in relevant]
            return dict(hit=int(len(hits) > 0), mrr=EB.mrr(rel, relevant, args.k),
                        ndcg=EB.ndcg(rel, relevant, args.k),
                        recall=EB.recall_at_k(rel, relevant, args.k))
        b, r = eval_order(base), eval_order(reranked)
        rows.append({"hit_base": b["hit"], "mrr_base": b["mrr"],
                     "ndcg_base": b["ndcg"], "recall_base": b["recall"],
                     "hit_rr": r["hit"], "mrr_rr": r["mrr"],
                     "ndcg_rr": r["ndcg"], "recall_rr": r["recall"]})
    save_cache(cache)
    return summarize(f"LoCoMo {gran} (V1Engine fd_bm25)", rows, args.k)


# ── BESPOKE：每用户 V1Engine，证据 = gold 关键词重叠 ─────────────────────

def run_bespoke(args, rk, cache):
    chat, search, queries_df, gold_df = EB.load_bespoke()
    docs = EB.parse_documents(chat, search)
    doc_vecs = np.load(os.path.join(CACHE, "bespoke_v2", "doc_vectors.npz"))["embeddings"]
    q_vecs = np.load(os.path.join(CACHE, "bespoke_v2", "query_vectors.npz"))["embeddings"]
    gold_lookup = EB.parse_gold(gold_df, queries_df)

    user_doc_map = defaultdict(list)
    for i, d in enumerate(docs):
        user_doc_map[d["user"]].append(i)
    q_relevant = EB.build_ground_truth(queries_df, gold_lookup, docs,
                                       user_doc_map, keyword_threshold=3)

    engines = {}
    for user, u_idx in user_doc_map.items():
        texts = [docs[i]["text"] for i in u_idx]
        vecs = np.stack([doc_vecs[i] for i in u_idx])
        engines[user] = V1Engine(texts, vecs)

    rows = []
    t0 = time.time()
    for qi, (_, qrow) in enumerate(queries_df.iterrows()):
        user = qrow["user"]
        u_idx = user_doc_map.get(user, [])
        relevant = q_relevant.get(qi, set())
        if not u_idx or not relevant:
            continue
        eng = engines[user]
        qtext = qrow["query"]
        qvec = q_vecs[qi]
        cand_local = eng.search(qvec, qtext, top_k=args.cand)
        base_local = cand_local[: args.k]
        cand_texts = [docs[u_idx[i]]["text"] for i in cand_local]
        reranked_local = rerank_topk(rk, cache, "bespoke", qtext,
                                     cand_local, cand_texts, args.k)
        def eval_order(local_order):
            global_order = [u_idx[i] for i in local_order]
            return dict(hit=int(any(i in relevant for i in global_order[:args.k])),
                        mrr=EB.mrr(global_order, relevant, args.k),
                        ndcg=EB.ndcg(global_order, relevant, args.k),
                        recall=EB.recall_at_k(global_order, relevant, args.k))
        b, r = eval_order(base_local), eval_order(reranked_local)
        rows.append({"hit_base": b["hit"], "mrr_base": b["mrr"],
                     "ndcg_base": b["ndcg"], "recall_base": b["recall"],
                     "hit_rr": r["hit"], "mrr_rr": r["mrr"],
                     "ndcg_rr": r["ndcg"], "recall_rr": r["recall"]})
        if len(rows) % 25 == 0:
            save_cache(cache)
            print(f"  bespoke [{len(rows)}] {time.time()-t0:.0f}s")
    save_cache(cache)
    return summarize("BESPOKE (V1Engine fd_bm25)", rows, args.k)


def rerank_topk(rk, cache, bench, qtext, cand_idx, cand_texts, k):
    key = f"{bench}:{qtext}"
    scores = None
    if key in cache and all(str(i) in cache[key] for i in cand_idx):
        scores = {i: cache[key][str(i)] for i in cand_idx}
    else:
        clipped = [t[:RERANK_MAX_CHARS] for t in cand_texts]
        scores = {}
        for pos, s in rk.rerank(qtext, clipped):
            scores[cand_idx[pos]] = s
        cache[key] = {str(i): scores[i] for i in cand_idx}
    return sorted(scores, key=lambda i: -scores[i])[:k]


def summarize(name, rows, k):
    n = len(rows)
    agg = {}
    for m in ("base", "rr"):
        agg[f"{m}_hit"] = sum(1 for r in rows if r[f"hit_{m}"]) / n
        agg[f"{m}_mrr"] = sum(r[f"mrr_{m}"] for r in rows) / n
        agg[f"{m}_ndcg"] = sum(r[f"ndcg_{m}"] for r in rows) / n
        agg[f"{m}_recall"] = sum(r[f"recall_{m}"] for r in rows) / n
    print(f"\n=== {name} (n={n}, K={k}) ===")
    print(f"{'method':<10}{'Hit@%d'%k:>10}{'MRR':>10}{'NDCG@%d'%k:>12}{'R@%d'%k:>10}")
    for m in ("baseline", "rerank"):
        p = "base" if m == "baseline" else "rr"
        print(f"{m:<10}{agg[p+'_hit']:>10.4f}{agg[p+'_mrr']:>10.4f}"
              f"{agg[p+'_ndcg']:>12.4f}{agg[p+'_recall']:>10.4f}")
    wins = sum(1 for r in rows if r["ndcg_rr"] > r["ndcg_base"])
    loss = sum(1 for r in rows if r["ndcg_rr"] < r["ndcg_base"])
    print(f"NDCG 胜/平/负: {wins}/{n-wins-loss}/{loss}")
    return agg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default="both", choices=["locomo", "bespoke", "both"])
    ap.add_argument("--gran", default="turns", choices=["turns", "obs", "session", "all"],
                    help="LoCoMo 粒度（all=三粒度全跑）")
    ap.add_argument("--maxq", type=int, default=10 ** 9, help="LoCoMo 最大查询数（默认全量）")
    ap.add_argument("--cand", type=int, default=50)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--workers", type=int, default=4, help="rerank API 并发数")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    rk = make_reranker()
    cache = load_cache()
    print(f"rerank 模型: {rk.model} | 候选 {args.cand} | top-{args.k} | workers {args.workers}")

    if args.bench in ("locomo", "both"):
        grans = ["turns", "obs", "session"] if args.gran == "all" else [args.gran]
        for g in grans:
            args.gran = g
            run_locomo(args, rk, cache)
    if args.bench in ("bespoke", "both"):
        run_bespoke(args, rk, cache)


if __name__ == "__main__":
    main()