# -*- coding: utf-8 -*-
"""
知识库索引构建（支持增量）：遍历 05-知识/知识库 → 每页正文向量化 → 落盘索引。

索引落盘：ai-os/index/（不进 vault，避免污染 Obsidian）
  - vectors.npy    所有向量 (N, dim) float32，顺序与 meta.json 一致
  - meta.json      [{path, title, skeleton, subdir, size, sha}]
  - texts.json     中文正文列表，与 meta.json 顺序对齐
  - index.json     {embedder_name, dim, built_at, n}

增量策略（meta.json 的 sha 是 diff 基准）：
  - 新增页（meta 里没有的 path）→ 只 embed 新增部分
  - 变更页（sha 不同）→ 只重新 embed 变更部分
  - 删除页（vault 里已不存在的 path）→ 从索引移除
  未变页完全不动（不重新 embed，省 API 调用）。

用法：
  python build_index.py            # 从 ai-os/config.json 读 key
  python build_index.py --key xxx  # 或直接传 key 覆盖
  python build_index.py --full     # 强制全量重建
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedders import load_config, make_embedder

VAULT_KB = r"D:\ObsidianVault\05-知识\知识库"
INDEX_BASE = r"D:\AI OS\l2-memory\index"
# 多源扫描：领域知识 + 个人记忆（01-记忆：个人经历/会话结论，L1 语义检索必达）
# + 控制知识（06-系统 全量纳入，L0/L2 注入类可检索无害）
SCAN_ROOTS = [
    (VAULT_KB, "05-知识"),
    (r"D:\ObsidianVault\01-记忆", "01-记忆"),
    (r"D:\ObsidianVault\06-系统", "06-系统"),
]

# frontmatter: --- 到 --- 之间；来源段: ## 来源 之后
FM_RE = re.compile(r"^---\n.*?\n---\n", re.S | re.M)
SRC_RE = re.compile(r"^## 来源.*$", re.S | re.M)


def clean_text(raw):
    """正文提取：剥 frontmatter、来源段，去 # 标题行和空行。"""
    t = FM_RE.sub("", raw)
    t = SRC_RE.sub("", t)
    t = re.sub(r"^#+.*$", "", t, flags=re.M)   # 标题行
    t = re.sub(r"[|>\-*`]", " ", t)            # markdown 符号
    t = re.sub(r"\s+", " ", t).strip()
    return t


def collect_pages():
    """返回 {path: {text, skeleton, subdir, title}}。多源扫描。"""
    pages = {}
    for root, prefix in SCAN_ROOTS:
        for r, dirs, files in os.walk(root):
            for fn in sorted(files):
                if not fn.endswith(".md") or fn == "00-骨架.md":
                    continue
                p = os.path.join(r, fn)
                with open(p, encoding="utf-8") as f:
                    raw = f.read()
                text = clean_text(raw)
                if len(text) < 20:
                    continue  # 空页跳过
                rel = os.path.relpath(p, root)
                parts = rel.split(os.sep)
                skeleton = prefix + "/" + parts[0] if parts else prefix
                subdir = parts[1] if len(parts) > 2 else ""
                title = fn[:-3]
                pages[rel] = {"text": text, "skeleton": skeleton,
                              "subdir": subdir, "title": title, "prefix": prefix}
    return pages


def load_existing():
    """读现有索引。返回 (meta_by_path, vectors_by_path)。索引不存在则空。"""
    mp = os.path.join(INDEX_DIR, "meta.json")
    vp = os.path.join(INDEX_DIR, "vectors.npy")
    if not (os.path.isfile(mp) and os.path.isfile(vp)):
        return {}, {}
    import numpy as np
    meta = json.load(open(mp, encoding="utf-8"))
    vecs = np.load(vp)
    meta_by_path = {m["path"]: m for m in meta}
    vecs_by_path = {m["path"]: vecs[i] for i, m in enumerate(meta)}
    return meta_by_path, vecs_by_path


def sha(text):
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=cfg.get("api_key", ""))
    ap.add_argument("--kind", default=cfg.get("kind", "qwen"))
    ap.add_argument("--full", action="store_true", help="强制全量重建")
    args = ap.parse_args()

    global INDEX_DIR
    INDEX_DIR = os.path.join(INDEX_BASE, args.kind)

    kwargs = {}
    if args.kind == "qwen":
        key = args.key or cfg.get("api_key", "")
        if not key:
            print("错误：qwen 缺少 API key。请在 ai-os/config.json 的 embedding.api_key 填写，或用 --key")
            sys.exit(1)
        kwargs = {"api_key": key}
    elif args.kind == "ollama":
        kwargs = {"model": cfg.get("ollama_model", "Qwen3-Embedding-8B:latest"),
                  "base": cfg.get("ollama_base", "http://localhost:11434")}

    pages = collect_pages()
    print(f"vault 当前页数: {len(pages)}")

    embedder = make_embedder(args.kind, **kwargs)

    # 增量 diff
    if args.full:
        existing_meta, existing_vecs = {}, {}
    else:
        existing_meta, existing_vecs = load_existing()

    to_add = []     # (path, text) 新增或变更
    to_remove = []  # path 已删除
    for path, p in pages.items():
        cur_sha = sha(p["text"])
        if path not in existing_meta:
            to_add.append(path)
        elif existing_meta[path].get("sha") != cur_sha:
            to_add.append(path)

    for path in existing_meta:
        if path not in pages:
            to_remove.append(path)

    print(f"新增/变更: {len(to_add)}  删除: {len(to_remove)}  未变: {len(pages) - len(to_add)}")

    # 只 embed 新增/变更
    new_vecs = {}
    if to_add:
        texts = [pages[path]["text"] for path in to_add]
        t0 = time.time()
        vecs = embedder.embed(texts)
        dt = time.time() - t0
        print(f"向量化 {len(to_add)} 条, 耗时 {dt:.0f}s ({dt/max(len(to_add),1)*1000:.0f}ms/条)")
        for path, v in zip(to_add, vecs):
            new_vecs[path] = v

    # 组装最终 meta + vectors（保持原有顺序，追加新的，去掉删除的）
    import numpy as np
    final_meta = []
    final_vecs = []
    if not args.full:
        for m in existing_meta.values():
            if m["path"] in pages and m["path"] not in to_add and m["path"] not in to_remove:
                final_meta.append(m)
                final_vecs.append(existing_vecs[m["path"]])
    for path in to_add:
        p = pages[path]
        final_meta.append({
            "path": path, "skeleton": p["skeleton"], "subdir": p["subdir"],
            "title": p["title"], "size": len(p["text"]),
            "sha": sha(p["text"]),
        })
        final_vecs.append(new_vecs[path])

    if len(final_meta) != len(final_vecs):
        print(f"错误: meta {len(final_meta)} != vecs {len(final_vecs)}")
        sys.exit(1)

    # 落盘
    os.makedirs(INDEX_DIR, exist_ok=True)
    arr = np.array(final_vecs, dtype=np.float32)
    np.save(os.path.join(INDEX_DIR, "vectors.npy"), arr)
    with open(os.path.join(INDEX_DIR, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(final_meta, f, ensure_ascii=False, indent=1)
    with open(os.path.join(INDEX_DIR, "texts.json"), "w", encoding="utf-8") as f:
        json.dump([pages[m["path"]]["text"] for m in final_meta], f,
                  ensure_ascii=False)
    idx = {
        "embedder_name": embedder.name, "dim": embedder.dim,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"), "n": len(final_meta),
    }
    with open(os.path.join(INDEX_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)

    print(f"索引已更新: {INDEX_DIR}  ({len(final_meta)} 页, 新增{len(to_add)}, 删除{len(to_remove)})")


if __name__ == "__main__":
    main()