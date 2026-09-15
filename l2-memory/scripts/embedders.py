# -*- coding: utf-8 -*-
"""
可插拔 embedder 接口（语义拓扑实现层）。

接口契约：
    name  -> str         标识
    dim   -> int         向量维度
    kind  -> str         "api" | "local" | "stat"
    embed(texts: list[str]) -> list[list[float]]   批量，每文本一向量

实现分级（见 04-知识层设计.md §3）：
    T3  QwenEmbedder      远程 API（讯飞 MaaS）
    T3  OllamaEmbedder    本地 Ollama（OpenAI 兼容端点）
    T2  LocalEncoderEmbedder  本地 encoder（接口预留，未实现）
    T1  WordVecEmbedder       词向量加权（接口预留，未实现）
    T0  BM25Embedder          BM25/TF-IDF（接口预留，未实现）

用法：
    # 远程 API
    embedder = make_embedder("qwen", api_key=KEY)
    # 本地 Ollama
    embedder = make_embedder("ollama", model="qwen3-embedding:latest")
    vecs = embedder.embed(["文本1", "文本2"])
"""
import json
import os
import time
import urllib.request
import urllib.error

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")


def load_config():
    """读取 ai-os/config.json（含 embedding API key）。文件不存在或字段缺失返回空 dict。"""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("embedding", {})
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        print(f"警告: config.json 解析失败: {e}")
        return {}


class Embedder:
    """统一接口基类。子类必须实现 embed()。"""
    name = "base"
    dim = 0
    kind = "stat"  # api | local | stat

    def embed(self, texts):
        raise NotImplementedError


class QwenEmbedder(Embedder):
    """T3: Qwen3-Embedding-8B @ 讯飞 MaaS（OpenAI 兼容 embeddings 端点）。"""
    name = "qwen3-embedding-8b"
    dim = 768
    kind = "api"

    def __init__(self, api_key, base="https://maas-api.cn-huabei-1.xf-yun.com/v2/embeddings",
                 model="xop3qwen8bembedding", batch_size=64):
        self.api_key = api_key
        self.base = base
        self.model = model
        self.batch_size = batch_size

    def _call(self, inputs, retries=3):
        body = json.dumps({"model": self.model, "input": inputs}).encode("utf-8")
        req = urllib.request.Request(self.base, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + self.api_key)
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    resp = json.loads(r.read().decode("utf-8", "replace"))
                return [d["embedding"] for d in resp.get("data", [])]
            except Exception as e:
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    print(f"  API error (attempt {attempt+1}/{retries}): {e}, retry in {wait}s...")
                    time.sleep(wait)
                else:
                    raise

    def embed(self, texts):
        out = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(self._call(texts[i:i + self.batch_size]))
        return out


class OllamaEmbedder(Embedder):
    """本地 Ollama embedding（OpenAI 兼容 /v1/embeddings 端点）。"""
    name = "ollama"
    dim = 0  # 首次调用时自动探测
    kind = "local"

    def __init__(self, model="Qwen3-Embedding-8B:latest",
                 base="http://localhost:11434", batch_size=128):
        self.model = model
        self.base = base.rstrip("/")
        self.batch_size = batch_size
        self._dim = None

    def _call(self, inputs, retries=3):
        """Embed a batch of texts via OpenAI-compatible /v1/embeddings endpoint."""
        url = f"{self.base}/v1/embeddings"
        body = json.dumps({"model": self.model, "input": inputs}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    resp = json.loads(r.read().decode("utf-8", "replace"))
                vecs = [d["embedding"] for d in resp.get("data", [])]
                if self._dim is None and vecs:
                    self._dim = len(vecs[0])
                return vecs
            except Exception as e:
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    print(f"  Ollama error (attempt {attempt+1}/{retries}): {e}, retry in {wait}s...")
                    time.sleep(wait)
                else:
                    raise

    @property
    def dim(self):
        return self._dim or 0

    def embed(self, texts):
        out = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(self._call(texts[i:i + self.batch_size]))
        return out


# 分级占位：保留统一接口，本步不实现不测试（ponytail: 未验证路径不做）
class LocalEncoderEmbedder(Embedder):
    """T2: 本地 encoder（bge-m3 等）。接口预留。"""
    name = "local-encoder"
    kind = "local"

    def embed(self, texts):
        raise NotImplementedError("T2 本地 encoder 未实现（保留接口，切本地时再开发）")


class WordVecEmbedder(Embedder):
    """T1: 词向量加权平均。接口预留。"""
    name = "word2vec"
    kind = "local"

    def embed(self, texts):
        raise NotImplementedError("T1 词向量未实现（保留接口）")


class BM25Embedder(Embedder):
    """T0: BM25/TF-IDF 稀疏向量。接口预留。"""
    name = "bm25"
    kind = "stat"

    def embed(self, texts):
        raise NotImplementedError("T0 BM25 未实现（保留接口）")


_REGISTRY = {
    "qwen": QwenEmbedder,
    "ollama": OllamaEmbedder,
    "local": LocalEncoderEmbedder,
    "word2vec": WordVecEmbedder,
    "bm25": BM25Embedder,
}


def make_embedder(kind, **kwargs):
    """按 kind 构造 embedder。kind: qwen | local | word2vec | bm25"""
    cls = _REGISTRY.get(kind)
    if cls is None:
        raise ValueError(f"未知 embedder 类型: {kind}（可选 {list(_REGISTRY)}）")
    return cls(**kwargs)