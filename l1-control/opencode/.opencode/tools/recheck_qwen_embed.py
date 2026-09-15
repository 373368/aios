# -*- coding: utf-8 -*-
"""
复验：短查询 vs 长笔记 的语义区分度（真实知识库笔记）
- 输入换成真实笔记正文（量子纠缠篇 vs 快递收费篇，跨主题）
- 查询：短查询（量子纠缠 / EPR / 快递 / 收费）+ 长查询
- 若长笔记下区分度好 => 模型可用；否则退 BM25
"""
import sys, json, time, urllib.request, urllib.error, math

sys.stdout.reconfigure(encoding='utf-8')

import os as _os
import json as _json
_CFG = _os.path.join(r"D:\AI OS\l2-memory", "config.json")
KEY = _json.load(open(_CFG, encoding="utf-8")).get("embedding", {}).get("api_key", "")   # 从 config.json 读，勿硬编码
BASE = "https://maas-api.cn-huabei-1.xf-yun.com/v2/embeddings"
MODEL = "xop3qwen8bembedding"

# 真实笔记正文（取正文主体，去 frontmatter/来源）
DOC_QUANTUM = """量子纠缠的本质：两个量子粒子处于纠缠态时，整体量子态不可分，必须用单一态函数描述。纠缠态的特点是：对其中一个粒子的测量瞬间决定另一个粒子的对应属性状态。这种关联在制备纠缠态时就已确定，测量只是揭示预先存在的关联性。量子测量是观测者加仪器与被测系统的相互作用，不可避免地干扰系统。坍缩（哥本哈根诠释）：测量导致量子态从叠加态坍缩到某个本征态。粒子自身不会观测，只有宏观仪器和观察者才能执行测量。对纠缠粒子 A 进行测量：A 粒子坍缩到某个确定状态，B 粒子瞬间坍缩到与 A 相关联的状态（关联性非信息传递）。不是 B 感知到 A 被测量，而是纠缠态中预先编码的关联性被揭示。A 坍缩结果完全随机，无法人为控制。为什么不能超光速通信：测量 A 的人无法控制坍缩结果，远方测量 B 的人看到随机结果，无法判断这随机结果是天然的还是因 A 被测量导致的。必须通过经典方式对比结果才能发现关联。"""

DOC_EXPRESS = """快递10+1收费贵不贵：10+1代表首重1kg内10元，续重每kg加1元。判断贵不贵看线路。同城省内：同城首重6-10元、续重1-2元每kg；省内首重8-12元、续重2-5元每kg，10+1首重中位数、续重比主流还低，小件划算。跨省：三通一达首重10-15元、续重4-6元每kg，续重1元异常便宜，警惕是协议价或有隐性费用（体积重/包装费/上楼费/偏远附加/续重进位）。顺丰京东：标快跨省首重18-23元、续重8-12元，不同赛道，不与10+1直接对比。建议：同城寄小件（衣物/文件/退货）10+1合理。跨省报10+1确认是否全包价。比价可用聚合平台（菜鸟裹裹、省寄通等）。续重进位（10.05kg按11kg）是常见多花点。"""

# 查询集: 每项 (标签, 查询文本, 期望相关文档)
QUERIES = [
    ("短查·量子纠缠", "量子纠缠", "quantum"),
    ("短查·EPR", "EPR佯谬", "quantum"),
    ("短查·快递", "快递 10+1 收费", "express"),
    ("短查·贵不贵", "寄快递贵不贵", "express"),
    ("长查·量子", "量子纠缠中测量A粒子如何影响B粒子的状态，为什么不能实现超光速通信", "quantum"),
    ("长查·快递", "同城寄小件快递10+1首重续重划不划算，跨省要注意什么隐性费用", "express"),
]

def call_embed(inputs):
    body = json.dumps({"model": MODEL, "input": inputs}).encode("utf-8")
    req = urllib.request.Request(BASE, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + KEY)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def norm(v):
    n = math.sqrt(sum(x*x for x in v))
    return [x/n for x in v]

def cos(u, v):
    return sum(x*y for x, y in zip(u, v))

if __name__ == "__main__":
    if not KEY:
        print("错误：请先填 KEY")
        sys.exit(1)

    docs = {"quantum": DOC_QUANTUM, "express": DOC_EXPRESS}
    # 索引两个文档
    idx = {}
    for tag, txt in docs.items():
        r = call_embed([txt])
        idx[tag] = norm(r["data"][0]["embedding"])
        print(f"[索引] 文档 {tag} ({len(txt)}字) 已向量化")

    print("=" * 70)
    print("查询 vs 两文档 余弦相似度（区分度应：相关>不相关）")
    print("=" * 70)
    ok = 0; total = 0
    for label, q, target in QUERIES:
        r = call_embed([q])
        qv = norm(r["data"][0]["embedding"])
        s_q = cos(qv, idx["quantum"])
        s_e = cos(qv, idx["express"])
        correct = (s_q > s_e) if target == "quantum" else (s_e > s_q)
        total += 1
        ok += 1 if correct else 0
        mark = "PASS" if correct else "FAIL"
        print(f"[{mark}] {label:14s}  量子={s_q:.4f}  快递={s_e:.4f}  (应命中:{target})")

    print("=" * 70)
    print(f"区分度: {ok}/{total} 查询正确命中目标文档")
    if ok == total:
        print("结论: 长笔记场景下语义区分度良好 => Qwen3-Embedding 可用作索引")
    else:
        print("结论: 区分度不足 => 建议退 BM25 或换模型")