# -*- coding: utf-8 -*-
"""
超大会话分片器：把 export/<平台>/ 下超过阈值的会话 MD 按消息段切成多片，
每片 ≤ 阈值，落盘到 chunks/<平台>/，供提炼流程逐片处理。

切片保留原文件 frontmatter（conversation_id 一致），因此：
- 去重游标不变（按 conversation_id 去重，多片共享同一 id，提炼后全部幂等跳过）
- 一个会话可提炼多条知识 = 每知识一页，天然满足"每知识一页"

切分规则：按消息段标题行（^## .*）作为块边界，块 = 标题 + 其下正文直到下一标题。
单个超长段（正文 > max）不强拆，原样保留（保证不丢内容；提炼时再拆）。

幂等：chunks 里已存在同会话名（同 base）切片 → 跳过。
用法：
  python chunk_sessions.py               # 全平台
  python chunk_sessions.py 元宝          # 单平台
  python chunk_sessions.py --max-kb 60   # 自定义阈值（默认 60KB）
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import paths as _paths  # noqa: E402

EXPORT = _paths.EXPORT_DIR
CHUNKS = _paths.CHUNKS_DIR
PLATFORMS = ["豆包", "DeepSeek", "元宝"]
DEFAULT_MAX_BYTES = 60 * 1024

FM_RE = re.compile(r"^---\n.*?\n---\n", re.S | re.M)
SEG_RE = re.compile(r"^## .*$", re.M)


def split_frontmatter(text):
    m = FM_RE.match(text)
    if not m:
        return "", text
    return m.group(0), text[m.end():]


def split_segments(body):
    """按 ^## 标题切块，返回 [(seg_title, seg_body), ...]；无标题则整段。"""
    matches = list(SEG_RE.finditer(body))
    if not matches:
        return [("", body)]
    segs = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        segs.append((m.group(0), body[start:end]))
    return segs


def chunk_file(path, out_dir, max_bytes):
    raw = open(path, encoding="utf-8").read()
    fm, body = split_frontmatter(raw)
    segs = split_segments(body)

    blocks = []
    cur = []
    cur_len = 0
    idx = 0
    for title, seg in segs:
        seg_len = len(seg)
        if cur and cur_len + seg_len > max_bytes:
            blocks.append((idx, "\n".join(cur)))
            idx += 1
            cur = []
            cur_len = 0
        cur.append(seg)
        cur_len += seg_len
    if cur:
        blocks.append((idx, "\n".join(cur)))

    os.makedirs(out_dir, exist_ok=True)
    written = []
    base = os.path.splitext(os.path.basename(path))[0]
    for n, blk in blocks:
        outp = os.path.join(out_dir, f"{base}__p{n}.md")
        with open(outp, "w", encoding="utf-8") as f:
            f.write(fm + blk + "\n")
        written.append(outp)
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("platform", nargs="?", default=None)
    ap.add_argument("--max-kb", type=float, default=DEFAULT_MAX_BYTES / 1024)
    args = ap.parse_args()
    max_bytes = int(args.max_kb * 1024)

    plats = [args.platform] if args.platform else PLATFORMS
    total_files = 0
    total_chunks = 0

    for plat in plats:
        src = os.path.join(EXPORT, plat)
        if not os.path.isdir(src):
            continue
        out_dir = os.path.join(CHUNKS, plat)
        os.makedirs(out_dir, exist_ok=True)
        existing_bases = {f.rsplit("__p", 1)[0] for f in os.listdir(out_dir) if "__p" in f}
        for fn in sorted(os.listdir(src)):
            if not fn.endswith(".md"):
                continue
            p = os.path.join(src, fn)
            size = os.path.getsize(p)
            if size <= max_bytes:
                continue
            base = os.path.splitext(fn)[0]
            if base in existing_bases:
                continue  # 幂等：已分片
            n = len(chunk_file(p, out_dir, max_bytes))
            total_files += 1
            total_chunks += n
            print(f"[{plat}] {fn[:50]} ({size//1024}KB) -> {n} 片")

    print(f"合计: {total_files} 个会话分片 -> {total_chunks} 片")


if __name__ == "__main__":
    main()
