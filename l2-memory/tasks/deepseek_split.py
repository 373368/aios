# DeepSeek 合并 JSON → 逐会话 Markdown 分割器
#
# 用法：
#   python deepseek_split.py export.json          # 输出到 ./DeepSeek/
#   python deepseek_split.py export.json -o D:/AI OS/l2-memory/export/DeepSeek
#
# 输入：DeepSeek History Exporter "全量合并 1 个 JSON" 导出的文件
# 输出：每会话一 .md 文件（含 frontmatter），直接供 kb-archivist 扫描/提炼

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone


def sanitize_filename(s):
    s = str(s or "").strip() or "无标题"
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", s)
    s = re.sub(r"\s+", " ", s).strip()[:80]
    return s or "无标题"


def extract_text(msg):
    """从消息体中提取纯文本/可读内容。"""
    if not msg or not isinstance(msg, dict):
        return ""

    def blocks_to_text(blocks):
        if not isinstance(blocks, list):
            return ""
        parts = []
        for b in blocks:
            if b is None:
                continue
            if isinstance(b, str):
                parts.append(b)
                continue
            if not isinstance(b, dict):
                parts.append(str(b))
                continue
            t = (b.get("type") or b.get("kind") or "").lower()
            if t in ("text", "") or not t:
                parts.append(b.get("text") or b.get("content") or b.get("value") or "")
            elif "thinking" in t or "reasoning" in t:
                v = b.get("thinking") or b.get("text") or b.get("content") or ""
                parts.append(f"> **{t}**\n> " + str(v).replace("\n", "\n> "))
            elif "tool" in t and "call" in t:
                parts.append("```json\n" + json.dumps(
                    {"tool": b.get("tool") or b.get("name"), "args": b.get("args") or b.get("arguments"),
                     "call_id": b.get("call_id") or b.get("id")}, indent=2, ensure_ascii=False) + "\n```")
            elif "tool" in t and "result" in t:
                parts.append("<details><summary>工具结果</summary>\n\n```json\n" +
                             json.dumps(b.get("result") or b.get("output") or b, indent=2, ensure_ascii=False) +
                             "\n```\n</details>")
            else:
                parts.append("```json\n" + json.dumps(b, indent=2, ensure_ascii=False) + "\n```")
        return "\n\n".join(parts)

    for key in ("content_blocks", "blocks", "message_content", "content_parts", "parts",
                "segments", "content", "body", "text", "message", "raw_content"):
        v = msg.get(key)
        if v is None or v == "":
            continue
        if isinstance(v, str):
            if v.strip():
                return v
        elif isinstance(v, list):
            t = blocks_to_text(v)
            if t:
                return t
        elif isinstance(v, dict):
            t = blocks_to_text([v])
            if t:
                return t

    # fallback: dump non-meta keys
    skip = {"id", "chat_session_id", "role", "created_at", "updated_at",
            "model_type", "parent_id", "token_count", "finish_reason", "status"}
    extra = {k: v for k, v in msg.items() if k not in skip and v is not None}
    if extra:
        return "```json\n" + json.dumps(extra, indent=2, ensure_ascii=False) + "\n```"
    return "_(空消息)_"


def role_icon(role):
    return {"USER": "👤 User", "ASSISTANT": "🤖 Assistant", "SYSTEM": "⚙️ System"}.get(role, f"⚙️ {role}")

ROLE_ICON = {"USER": "👤 User", "ASSISTANT": "🤖 Assistant", "SYSTEM": "⚙️ System"}


def session_to_md(session):
    lines = []
    # frontmatter — 与现有 export/DeepSeek/ 文件格式一致
    lines.append("---")
    lines.append(f"title: {session.get('title', '无标题')}")
    lines.append(f"source: deepseek")
    lines.append(f"conversation_id: {session.get('id', session.get('chat_session_id', ''))}")
    ts = session.get("exported_at") or session.get("updated_at") or ""
    if ts and isinstance(ts, (int, float)):
        ts = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    if ts:
        lines.append(f"exported_at: {ts}")
    lines.append("---")
    lines.append("")

    for m in (session.get("messages") or []):
        role = m.get("role", "UNKNOWN").upper()
        label = ROLE_ICON.get(role, f"⚙️ {role}")
        lines.append(f"## {label}")
        lines.append("")
        lines.append(extract_text(m))
        lines.append("")

    return "\n".join(lines)


def split(input_path, output_dir):
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    os.makedirs(output_dir, exist_ok=True)
    sessions = data.get("sessions") or []
    written = 0

    for s in sessions:
        title = sanitize_filename(s.get("title"))
        sid = (s.get("id") or "unknown")[:8]
        filename = f"{sid}-{title}.md"
        filepath = os.path.join(output_dir, filename)
        content = session_to_md(s)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        written += 1

    return written


def main():
    ap = argparse.ArgumentParser(description="DeepSeek JSON → 逐会话 Markdown 分割")
    ap.add_argument("input", help="DeepSeek 合并 JSON 文件路径")
    ap.add_argument("-o", "--output-dir", default=None,
                    help="输出目录（默认 ./DeepSeek/）")
    args = ap.parse_args()

    output_dir = args.output_dir or os.path.join(os.path.dirname(args.input) or ".", "DeepSeek")
    n = split(args.input, output_dir)
    print(f"✓ 已分割 {n} 个会话 → {output_dir}")


if __name__ == "__main__":
    main()