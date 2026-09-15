# -*- coding: utf-8 -*-
"""
Reranker 可插拔接口（cross-encoder 重排层，接口契约同 embedders.py）。

T3  Reranker @ 讯飞 MaaS（OpenAI 兼容 rerank 端点）

用法：
    rk = make_reranker(api_key=KEY)                 # 默认 Qwen3-Reranker-8B
    scores = rk.rerank(query, documents)            # -> [(index, relevance_score), ...] 降序
"""
import json
import os
import time
import urllib.request
import urllib.error

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")


def load_rerank_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("rerank", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


class Reranker:
    """T3: Qwen3-Reranker-8B @ 讯飞 MaaS（/v2/rerank）。"""
    name = "qwen3-reranker-8b"
    kind = "api"

    def __init__(self, api_key, base="https://maas-api.cn-huabei-1.xf-yun.com/v2/rerank",
                 model="xop3qwen8breranker", retries=3):
        self.api_key = api_key
        self.base = base
        self.model = model
        self.retries = retries

    def _call(self, query, documents):
        body = json.dumps({"model": self.model, "query": query,
                           "documents": documents}).encode("utf-8")
        req = urllib.request.Request(self.base, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + self.api_key)
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    resp = json.loads(r.read().decode("utf-8", "replace"))
                results = resp.get("results", [])
                return [(int(x["index"]), float(x["relevance_score"]))
                        for x in sorted(results, key=lambda x: -x["relevance_score"])]
            except Exception as e:
                if attempt < self.retries - 1:
                    wait = 2 ** attempt
                    print(f"  Rerank error (attempt {attempt+1}/{self.retries}): {e}, retry in {wait}s...")
                    time.sleep(wait)
                else:
                    raise

    def rerank(self, query, documents):
        """返回按相关性降序的 [(index, score), ...]。index 为 documents 下标。"""
        return self._call(query, documents)


def make_reranker(**kwargs):
    cfg = load_rerank_config()
    kwargs.setdefault("api_key", cfg.get("api_key", "") or
                      json.load(open(CONFIG_PATH, encoding="utf-8")).get("embedding", {}).get("api_key", ""))
    kwargs.setdefault("base", cfg.get("base", "https://maas-api.cn-huabei-1.xf-yun.com/v2/rerank"))
    kwargs.setdefault("model", cfg.get("model", "xop3qwen8breranker"))
    if not kwargs["api_key"]:
        raise ValueError("缺少 api_key：请在 config.json 的 rerank.api_key 或 embedding.api_key 填写")
    return Reranker(**kwargs)


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    rk = make_reranker()
    docs = ["讯飞 MaaS 的 embedding 接口返回 768 维向量，语义区分度良好。",
            "混合检索用 BM25 加稠密向量做 RRF 融合，召回效果不错。",
            "股票市场今天收涨，家电板块领涨。"]
    for i, s in rk.rerank("增强搜索 rerank 对记忆检索结果的重排作用", docs):
        print(f"  {s:.4f}  {docs[i][:40]}")
    print("OK: rerank 自检通过")