# -*- coding: utf-8 -*-
"""
记忆引擎 v2 · 基线对比方法。

实现 BM25、纯语义、同目录策略和随机基线，与行为增强引擎对比。

用法：
  python baselines.py
"""
import json
import os
import random
import sys
import time
from collections import defaultdict
from math import log

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedders import load_config, make_embedder

INDEX_DIR = r"D:\AI OS\l2-memory\index"
random.seed(42)

# ─── 分词工具 ──────────────────────────────────────────────────────────

def tokenize(text):
    """简单分词：中文 2-gram + unigram，英文空格切分"""
    tokens = []
    i = 0
    while i < len(text):
        if '\u4e00' <= text[i] <= '\u9fff':  # 中文字符
            # 添加 unigram
            tokens.append(text[i])
            # 添加 2-gram（如果有下一个中文字符）
            if i + 1 < len(text) and '\u4e00' <= text[i+1] <= '\u9fff':
                tokens.append(text[i:i+2])
            i += 1
        else:
            # 英文或数字（按空格切分，去首尾标点）
            j = i
            while j < len(text) and not ('\u4e00' <= text[j] <= '\u9fff'):
                j += 1
            word = text[i:j].lower()
            for piece in word.split():
                piece = piece.strip(" .,;:!?\"'()[]{}<>/\\|@#$%^&*+-=~`")
                if piece:
                    tokens.append(piece)
            i = j
    return tokens


# ─── IR 指标 ──────────────────────────────────────────────────────────

def precision_at_k(retrieved, relevant, k):
    """top-k 中相关结果的比例。"""
    top = retrieved[:k]
    return sum(1 for p in top if p in relevant) / k


def recall_at_k(retrieved, relevant, k):
    """top-k 命中的相关结果占全部相关结果的比例。"""
    if not relevant:
        return 0.0
    top = retrieved[:k]
    return sum(1 for p in top if p in relevant) / len(relevant)


def mrr(retrieved, relevant):
    """第一个相关结果的倒数排名。"""
    for i, p in enumerate(retrieved, 1):
        if p in relevant:
            return 1.0 / i
    return 0.0


def dcg_at_k(retrieved, relevant, k):
    """DCG@k：相关文档出现在排名 i 处贡献 1/log2(i+1)。"""
    dcg = 0.0
    for i, p in enumerate(retrieved[:k]):
        if p in relevant:
            dcg += 1.0 / np.log2(i + 2)  # i 从 0 开始，所以 +2
    return dcg


def ndcg_at_k(retrieved, relevant, k):
    """NDCG@k = DCG@k / IDCG@k。"""
    dcg = dcg_at_k(retrieved, relevant, k)
    # 理想排序：所有相关文档排在最前
    ideal_retrieved = list(relevant)[:k]
    idcg = dcg_at_k(ideal_retrieved, relevant, k)
    if idcg == 0:
        return 0.0
    return dcg / idcg


def compute_metrics(results, ground_truth, top_k=10):
    """
    计算 IR 指标
    results: list of {"path": str, "score": float}
    ground_truth: list of str (relevant paths)
    返回: {"precision": float, "recall": float, "mrr": float, "ndcg": float}
    """
    retrieved = [r["path"] for r in results]
    relevant = set(ground_truth)
    
    return {
        "precision": precision_at_k(retrieved, relevant, top_k),
        "recall": recall_at_k(retrieved, relevant, top_k),
        "mrr": mrr(retrieved, relevant),
        "ndcg": ndcg_at_k(retrieved, relevant, top_k)
    }


# ─── 基线类实现 ────────────────────────────────────────────────────────

class BM25Baseline:
    """BM25 检索基线"""
    def __init__(self, meta):
        """构建 BM25 索引"""
        self.meta = meta
        self.k1 = 1.5
        self.b = 0.75
        
        # 为每个文档构建索引
        self.doc_tokens = []  # list of list of tokens
        self.doc_paths = []
        self.doc_titles = []
        
        # 倒排索引: token -> list of (doc_idx, term_freq)
        self.inverted_index = defaultdict(list)
        
        # 构建索引
        for idx, item in enumerate(meta):
            # 组合标题和路径作为文档内容
            text = item.get("title", "") + " " + item.get("path", "")
            tokens = tokenize(text)
            self.doc_tokens.append(tokens)
            self.doc_paths.append(item["path"])
            self.doc_titles.append(item.get("title", ""))
            
            # 统计词频
            term_freq = defaultdict(int)
            for token in tokens:
                term_freq[token] += 1
            
            # 更新倒排索引
            for token, freq in term_freq.items():
                self.inverted_index[token].append((idx, freq))
        
        # 计算文档长度和平均文档长度
        self.doc_lengths = [len(tokens) for tokens in self.doc_tokens]
        self.avgdl = sum(self.doc_lengths) / len(self.doc_lengths) if self.doc_lengths else 1
        
        # 计算文档总数
        self.N = len(self.doc_tokens)
        
        # 计算 IDF
        self.idf = {}
        for token, postings in self.inverted_index.items():
            df = len(postings)
            self.idf[token] = log((self.N - df + 0.5) / (df + 0.5) + 1)
    
    def search(self, query, top_k=10):
        """BM25 检索"""
        query_tokens = tokenize(query)
        
        # 计算每个文档的得分
        scores = [0.0] * self.N
        
        for token in query_tokens:
            if token not in self.inverted_index:
                continue
            
            idf = self.idf[token]
            for doc_idx, tf in self.inverted_index[token]:
                dl = self.doc_lengths[doc_idx]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                scores[doc_idx] += idf * numerator / denominator
        
        # 排序并返回 top-k
        indexed_scores = list(enumerate(scores))
        indexed_scores.sort(key=lambda x: -x[1])
        
        results = []
        for doc_idx, score in indexed_scores[:top_k]:
            results.append({
                "path": self.doc_paths[doc_idx],
                "score": score,
                "title": self.doc_titles[doc_idx]
            })
        
        return results


class PureSemanticBaseline:
    """纯语义检索基线（behavior_weight=0）"""
    def __init__(self, vectors_path, meta_path):
        """加载 vectors.npy 和 meta.json"""
        # 加载向量
        self.vectors = np.load(vectors_path)
        
        # 加载元数据
        with open(meta_path, "r", encoding="utf-8") as f:
            self.meta = json.load(f)
        
        self.paths = [item["path"] for item in self.meta]
        self.titles = [item.get("title", "") for item in self.meta]
        
        # 归一化向量（用于余弦相似度）
        norms = np.linalg.norm(self.vectors, axis=1, keepdims=True)
        self.vectors_normalized = self.vectors / np.where(norms > 0, norms, 1)
    
    def search(self, query_vector, top_k=10):
        """余弦相似度检索"""
        # 归一化查询向量
        query_norm = np.linalg.norm(query_vector)
        if query_norm > 0:
            query_normalized = query_vector / query_norm
        else:
            query_normalized = query_vector
        
        # 计算余弦相似度
        similarities = np.dot(self.vectors_normalized, query_normalized)
        
        # 排序并返回 top-k
        indexed_sims = list(enumerate(similarities))
        indexed_sims.sort(key=lambda x: -x[1])
        
        results = []
        for idx, score in indexed_sims[:top_k]:
            results.append({
                "path": self.paths[idx],
                "score": float(score),
                "title": self.titles[idx]
            })
        
        return results


class SameDirectoryBaseline:
    """同目录策略基线：返回同一目录下的笔记"""
    def __init__(self, meta):
        """按目录分组笔记"""
        self.meta = meta
        self.dir_to_notes = defaultdict(list)
        
        for item in meta:
            path = item["path"]
            # 获取目录（去掉文件名）
            directory = os.path.dirname(path)
            self.dir_to_notes[directory].append(item)
    
    def search(self, query_path, top_k=10):
        """返回与查询笔记同一目录的笔记"""
        query_dir = os.path.dirname(query_path)
        
        # 获取同目录下的笔记
        candidates = self.dir_to_notes.get(query_dir, [])
        
        # 按路径排序（确定性）
        candidates.sort(key=lambda x: x["path"])
        
        # 返回 top-k（排除查询本身）
        results = []
        for item in candidates:
            if item["path"] != query_path:
                results.append({
                    "path": item["path"],
                    "score": 1.0,  # 同目录得分为 1
                    "title": item.get("title", "")
                })
                if len(results) >= top_k:
                    break
        
        return results


class RandomBaseline:
    """随机基线：随机返回笔记"""
    def __init__(self, meta):
        """随机排序笔记列表"""
        self.meta = meta
        self.paths = [item["path"] for item in meta]
        self.titles = [item.get("title", "") for item in meta]
        
        # 随机打乱
        self.shuffled_indices = list(range(len(self.meta)))
        random.shuffle(self.shuffled_indices)
    
    def search(self, top_k=10):
        """随机返回 top_k 个笔记"""
        results = []
        for idx in self.shuffled_indices[:top_k]:
            results.append({
                "path": self.paths[idx],
                "score": 1.0,  # 随机结果得分为 1
                "title": self.titles[idx]
            })
        return results


# ─── 评估函数 ──────────────────────────────────────────────────────────

def generate_test_set(cooc, n_queries=15, top_neighbors=3):
    """
    从 cooccurrence.json 自动生成测试集。
    """
    # 收集所有页及其邻居
    page_scores = {}  # path → 总共现次数
    page_neighbors = {}  # path → [(neighbor, count), ...] 按 count 降序

    for a, neighbors in cooc.items():
        if a not in page_scores:
            page_scores[a] = 0
            page_neighbors[a] = []
        for b, count in neighbors.items():
            page_scores[a] += count
            page_neighbors[a].append((b, count))
            # b 也可能作为 a
            if b not in page_scores:
                page_scores[b] = 0
                page_neighbors[b] = []
            page_neighbors[b].append((a, count))

    # 按总共现次数排序，优先选高频页
    sorted_pages = sorted(page_scores.items(), key=lambda x: -x[1])

    # 采样查询（避免太慢）
    n = min(n_queries, len(sorted_pages))
    sampled_paths = [p for p, _ in sorted_pages[:n]]

    # 构建 ground_truth
    queries = []
    ground_truth = {}

    for path in sampled_paths:
        # 获取该页的邻居，按共现次数降序取 top-3
        neighbors = page_neighbors.get(path, [])
        neighbors.sort(key=lambda x: -x[1])
        relevant = [b for b, _ in neighbors[:top_neighbors]]

        if not relevant:
            continue

        # 用路径去掉 .md 作为查询文本
        query_text = os.path.basename(path).replace(".md", "")
        queries.append({"query": query_text, "path": path})
        ground_truth[path] = relevant

    return queries, ground_truth


def run_evaluation(queries, ground_truth, baselines, embedder=None, top_k=10):
    """
    运行所有基线评估
    """
    # 收集所有指标
    all_metrics = {}
    for name in baselines.keys():
        all_metrics[name] = {"precision": [], "recall": [], "mrr": [], "ndcg": []}
    
    total = len(queries)
    t_start = time.time()
    
    for qi, q in enumerate(queries):
        query_text = q.get("query", "")
        query_path = q.get("path", "")
        relevant = ground_truth.get(query_path, [])
        
        if not relevant:
            continue
        
        # 对每个基线进行评估
        for name, baseline in baselines.items():
            try:
                if name == "bm25":
                    results = baseline.search(query_text, top_k=top_k)
                elif name == "pure_semantic":
                    # 获取查询向量
                    if embedder is None:
                        print(f"  警告: 无 embedder，跳过纯语义基线")
                        continue
                    query_vector = embedder.embed([query_text])[0]
                    results = baseline.search(query_vector, top_k=top_k)
                elif name == "same_directory":
                    results = baseline.search(query_path, top_k=top_k)
                elif name == "random":
                    results = baseline.search(top_k=top_k)
                else:
                    results = []
                
                # 计算指标
                metrics = compute_metrics(results, relevant, top_k)
                for metric in ["precision", "recall", "mrr", "ndcg"]:
                    all_metrics[name][metric].append(metrics[metric])
                    
            except Exception as e:
                print(f"  ⚠ 基线 {name} 查询 {qi+1} 失败: {e}")
        
        # 进度
        elapsed = time.time() - t_start
        eta = (elapsed / (qi + 1)) * (total - qi - 1) if qi > 0 else 0
        print(f"  [{qi+1}/{total}] {query_text[:30]}  ETA {eta:.0f}s")
    
    # 汇总
    result = {}
    for name, metrics in all_metrics.items():
        result[name] = {}
        for metric in ["precision", "recall", "mrr", "ndcg"]:
            values = metrics[metric]
            result[name][metric] = round(sum(values) / len(values), 4) if values else 0.0
    
    return result


# ─── 主入口 ──────────────────────────────────────────────────────────────

def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    
    print("=== 基线对比报告 ===\n")

    # 行为模块已归档（memory_engine 已从工作区移除）— v2 评估停用
    try:
        from memory_engine import load_cooccurrence, search_with_behavior
    except ImportError:
        print("错误: memory_engine 已归档，v2 基线评估停用（v1 定案框架见 memory_v1.py）")
        sys.exit(0)

    # 1. 加载元数据
    meta_path = os.path.join(INDEX_DIR, "meta.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    print(f"  元数据: {len(meta)} 条记录")
    
    # 2. 加载共现数据
    cooc = load_cooccurrence()
    if not cooc:
        print("错误: cooccurrence.json 为空")
        sys.exit(1)
    total_pairs = sum(len(v) for v in cooc.values())
    print(f"  共现数据: {total_pairs} 对")
    
    # 3. 生成测试集
    queries, ground_truth = generate_test_set(cooc, n_queries=15, top_neighbors=3)
    print(f"  测试集: {len(queries)} 个查询")
    if not queries:
        print("错误: 无法生成测试集")
        sys.exit(1)
    
    # 4. 创建基线
    bm25 = BM25Baseline(meta)
    same_dir = SameDirectoryBaseline(meta)
    random_baseline = RandomBaseline(meta)
    
    # 5. 创建 embedder（用于纯语义基线）
    vectors_path = os.path.join(INDEX_DIR, "vectors.npy")
    pure_semantic = None
    embedder = None
    
    # 始终创建 embedder（用于纯语义基线和行为增强引擎）
    config = load_config()
    api_key = config.get("api_key", "")
    if api_key:
        try:
            embedder = make_embedder(config.get("kind", "qwen"), api_key=api_key)
            print(f"  Embedder: {embedder.name}")
        except Exception as e:
            print(f"  警告: 创建 embedder 失败: {e}")
    
    # 加载预计算向量（用于纯语义基线）
    if os.path.exists(vectors_path):
        try:
            pure_semantic = PureSemanticBaseline(vectors_path, meta_path)
            print(f"  纯语义基线: 已加载预计算向量")
        except Exception as e:
            print(f"  警告: 加载预计算向量失败: {e}")
    
    # 6. 准备基线字典
    baselines = {
        "bm25": bm25,
        "same_directory": same_dir,
        "random": random_baseline
    }
    
    if pure_semantic:
        baselines["pure_semantic"] = pure_semantic
    
    # 7. 运行评估
    print("\n  开始基线评估...")
    t0 = time.time()
    try:
        baseline_results = run_evaluation(queries, ground_truth, baselines, embedder, top_k=10)
    except Exception as e:
        print(f"\n错误: 评估失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    dt = time.time() - t0
    print(f"  基线评估完成，耗时 {dt:.1f}s")
    
    # 8. 运行行为增强引擎评估（作为对比）
    print("\n  运行行为增强引擎评估...")
    if embedder is None:
        print("  警告: 无 embedder，跳过行为增强引擎评估")
    else:
        try:
            # 评估行为增强引擎
            beh_metrics = {"precision": [], "recall": [], "mrr": [], "ndcg": []}
            beh_success = 0
            beh_fail = 0
            for qi, q in enumerate(queries):
                path = q["path"]
                query_text = q["query"]
                relevant = set(ground_truth.get(path, []))
                
                if not relevant:
                    continue
                
                try:
                    # 行为增强搜索
                    beh_results = search_with_behavior(
                        query_text, embedder, top_k=10, behavior_weight=0.3, verbose=False
                    )
                    
                    if not beh_results:
                        beh_fail += 1
                        continue
                    
                    # 计算指标
                    beh_paths = [r["path"] for r in beh_results]
                    sp = precision_at_k(beh_paths, relevant, 10)
                    sr = recall_at_k(beh_paths, relevant, 10)
                    sm = mrr(beh_paths, relevant)
                    sn = ndcg_at_k(beh_paths, relevant, 10)
                    
                    beh_metrics["precision"].append(sp)
                    beh_metrics["recall"].append(sr)
                    beh_metrics["mrr"].append(sm)
                    beh_metrics["ndcg"].append(sn)
                    beh_success += 1
                except Exception as e:
                    beh_fail += 1
                    if qi < 3:  # 只打印前几个错误
                        print(f"  ⚠ 行为增强查询 {qi+1} 失败: {e}")
            
            print(f"  行为增强: 成功 {beh_success}, 失败 {beh_fail}")
            
            # 汇总
            def avg(lst):
                return round(sum(lst) / len(lst), 4) if lst else 0.0
            
            if beh_metrics["precision"]:
                baseline_results["behavior_engine"] = {k: avg(v) for k, v in beh_metrics.items()}
            else:
                print("  警告: 行为增强引擎无有效结果")
        except Exception as e:
            print(f"  警告: 行为增强引擎评估失败: {e}")
    
    # 9. 输出对比报告
    print(f"\n{'='*60}")
    print(f"  基线对比报告")
    print(f"{'='*60}\n")
    
    header = f"{'Method':<20} {'Precision@10':<14} {'Recall@10':<14} {'MRR':<14} {'NDCG@10':<14}"
    print(header)
    print("-" * 60)
    
    # 按 NDCG 排序
    sorted_methods = sorted(baseline_results.items(), key=lambda x: x[1]["ndcg"], reverse=True)
    
    for method, metrics in sorted_methods:
        p = metrics.get("precision", 0)
        r = metrics.get("recall", 0)
        m = metrics.get("mrr", 0)
        n = metrics.get("ndcg", 0)
        print(f"{method:<20} {p:<14.4f} {r:<14.4f} {m:<14.4f} {n:<14.4f}")
    
    # 10. 保存结果
    result_path = os.path.join(INDEX_DIR, "baseline_comparison.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(baseline_results, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存到: {result_path}")


if __name__ == "__main__":
    main()