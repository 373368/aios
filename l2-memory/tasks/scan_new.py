# -*- coding: utf-8 -*-
"""
扫描 ai-os/export 下未提炼的对话会话清单。

去重游标 = 知识库 frontmatter conversation_id ∪ 来源段"会话: xxx (id)"。
输出未提炼清单 + 空会话/占位标记，供 kb-archivist 子代理决定提炼对象。

用法：
  python scan_new.py                  # 全平台
  python scan_new.py 豆包             # 单平台（支持英文别名 doubao/deepseek/yuanbao）
  python scan_new.py --json           # 机器可读（报告键=传入平台名原文）
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import paths as _paths  # noqa: E402

KB = _paths.KB_ROOT
EXPORT = _paths.EXPORT_DIR
CHUNKS = _paths.CHUNKS_DIR
PLATFORMS = ["豆包", "DeepSeek", "元宝"]
ALIASES = {"doubao": "豆包", "deepseek": "DeepSeek", "yuanbao": "元宝"}


def kb_ids():
    """知识库已归档 id 集合：frontmatter conversation_id ∪ 来源段会话 id。"""
    have = set()
    for r, d, fs in os.walk(KB):
        for fn in fs:
            if not fn.endswith(".md"):
                continue
            try:
                t = open(os.path.join(r, fn), encoding="utf-8").read(20000)
            except Exception:
                continue
            for m in re.finditer(r"conversation_id:\s*(\S+)", t):
                have.add(m.group(1).strip().rstrip(","))
            for m in re.finditer(r"会话[：:]\s*(?:.+?)\s*\((\d+|[0-9a-f-]{8,})\)", t):
                have.add(m.group(1).strip())
    return have


def session_cid(path):
    """读会话文件 frontmatter 的 conversation_id（权威字段，勿解析文件名）。"""
    try:
        head = open(path, encoding="utf-8").read(800)
    except Exception:
        return None
    m = re.search(r"conversation_id:\s*(\S+)", head)
    return m.group(1).strip() if m else None


def classify(text):
    """空/占位会话识别。返回 (value, reason)。"""
    if len(text) < 200:
        return ("empty", "文件过短")
    if re.match(r"^(已解答，查看讲解|该内容需查看讲解|.*查看讲解)$", text.strip(), re.S):
        return ("placeholder", "占位文本")
    return ("ok", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("platform", nargs="?", default=None)
    ap.add_argument("--platform", dest="platform_opt", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.platform_opt:
        args.platform = args.platform_opt

    have = kb_ids()
    # (报告键, 扫描目录名)：别名映射只影响目录；报告键保留调用方传入原文（工作流表达式按原文取值）
    pairs = [(args.platform, ALIASES.get(args.platform.lower(), args.platform))] \
        if args.platform else [(p, p) for p in PLATFORMS]
    report = {}

    for given, plat in pairs:
        # 已分片集合：chunks/<平台>/ 里出现过的会话 base（原文件不再单独列候选，只处理切片）
        chunk_dir = os.path.join(CHUNKS, plat)
        chunked_bases = set()
        if os.path.isdir(chunk_dir):
            for f in os.listdir(chunk_dir):
                if "__p" in f:
                    chunked_bases.add(f.rsplit("__p", 1)[0])
        missed, empty, placeholder = [], [], []
        # 1) export 原文件（跳过已分片者）
        d = os.path.join(EXPORT, plat)
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".md"):
                    continue
                base = os.path.splitext(fn)[0]
                if base in chunked_bases:
                    continue  # 已分片，原文件不单独提炼
                p = os.path.join(d, fn)
                cid = session_cid(p)
                if cid and cid in have:
                    continue
                text = open(p, encoding="utf-8").read()
                cls, why = classify(text)
                item = {"file": fn, "conversation_id": cid, "size": len(text), "dir": "export"}
                if cls == "empty":
                    empty.append(item)
                elif cls == "placeholder":
                    placeholder.append(item)
                else:
                    missed.append(item)
        # 2) chunks 切片
        if os.path.isdir(chunk_dir):
            for fn in sorted(os.listdir(chunk_dir)):
                if not fn.endswith(".md"):
                    continue
                p = os.path.join(chunk_dir, fn)
                cid = session_cid(p)
                if cid and cid in have:
                    continue
                text = open(p, encoding="utf-8").read()
                cls, why = classify(text)
                item = {"file": fn, "conversation_id": cid, "size": len(text), "dir": "chunks"}
                if cls == "empty":
                    empty.append(item)
                elif cls == "placeholder":
                    placeholder.append(item)
                else:
                    missed.append(item)
        report[given] = {"candidates": missed, "empty": empty, "placeholder": placeholder}

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    total = 0
    for plat, r in report.items():
        c = len(r["candidates"])
        total += c
        print(f"[{plat}] 待提炼: {c}  空/占位跳过: {len(r['empty'])+len(r['placeholder'])}")
        for item in r["candidates"]:
            print(f"    {item['file'][:70]}  ({item['size']}B)")
    print(f"合计待提炼: {total}")


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
