# -*- coding: utf-8 -*-
"""
Qwen3-Embedding-8B 实测脚本（讯飞 MaaS, OpenAI 兼容 embeddings 端点）

用法：
  1. 把下面 KEY 换成你的讯飞 MaaS key
  2. python probe_qwen_embed.py

只做只读测试：单个 embedding 调用 + 维度/耗时输出。
不修改任何文件。
"""
import sys, json, time, urllib.request, urllib.error

sys.stdout.reconfigure(encoding='utf-8')

# ===== key 从 l2-memory/config.json 读取（勿硬编码）=====
import json as _json
import os as _os
_CFG = _os.path.join(r"D:\AI OS\l2-memory", "config.json")
KEY = _json.load(open(_CFG, encoding="utf-8")).get("embedding", {}).get("api_key", "")

BASE = "https://maas-api.cn-huabei-1.xf-yun.com/v2/embeddings"
MODEL = "xop3qwen8bembedding"   # 配置里模型名 xop3qwen8bembedding，这里用真实模型名；若 404/400 可试 xop3qwen8bembedding

TEST_CASES = [
    "量子纠缠是什么",
    "EPR佯谬",
    "量子力学中的测量问题",
]

def call_embed(inputs):
    body = json.dumps({"model": MODEL, "input": inputs}).encode("utf-8")
    req = urllib.request.Request(BASE, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + KEY)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode("utf-8", "replace"))
    dt = time.time() - t0
    return resp, dt

if __name__ == "__main__":
    if not KEY:
        print("错误：请先在本脚本顶部 KEY = '' 处填入你的 key")
        sys.exit(1)

    print(f"测试模型: {MODEL} @ {BASE}")
    print("=" * 60)

    # 1) 单条查询，看结构和维度
    resp, dt = call_embed(TEST_CASES[0])
    data = resp.get("data", [])
    if not data:
        print("返回结构异常:", json.dumps(resp, ensure_ascii=False)[:500])
        sys.exit(1)

    vec = data[0]["embedding"]
    print(f"[单条] HTTP OK  耗时 {dt*1000:.0f} ms  向量维度: {len(vec)}")
    print(f"       前 5 个值: {[round(x,4) for x in vec[:5]]}")

    # 2) 相似度 sanity check：相关 vs 不相关
    print("-" * 60)
    a, _ = call_embed(TEST_CASES)
    def norm(v): 
        import math
        n = math.sqrt(sum(x*x for x in v)); return [x/n for x in v]
    va, vb, vc = [norm(d["embedding"]) for d in a["data"]]
    def cos(u, v): return sum(x*y for x, y in zip(u, v))
    print(f"[相关] '量子纠缠' vs 'EPR佯谬':  cos = {cos(va,vb):.4f}")
    print(f"[不相关] '量子纠缠' vs '量子力学测量': cos = {cos(va,vc):.4f}")

    # 3) 批量能力
    print("-" * 60)
    t0 = time.time()
    resp_batch, _ = call_embed(TEST_CASES)
    dt_batch = time.time() - t0
    print(f"[批量] 3 条一次调用 OK  耗时 {dt_batch*1000:.0f} ms")

    print("=" * 60)
    print("结论: 端点可达 + 鉴权通过 + 向量产出正常")