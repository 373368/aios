# -*- coding: utf-8 -*-
"""sys_classify_sdk — 06-系统 知识固化分类 SDK（原子化 · 可拔插 · v3）

定位：AI-OS 系统调用库（SDK 能力层）的「分类固化」函数集。
复用本机配置状态（provider/model 取当前会话，不写死）。

六类消费模型（判据指标与 06-系统索引.md「一」节一致）：
  C1 不可协商纪律   → L0 锚点候选（extract_anchors）
  C2 规避经验机械可判 → harness 硬化条款候选（extract_harden）
  C3 规避经验情境触发 → SKILL.md 描述候选（extract_skill_cands）
  C4 流程/决策规则  → L1 检索（保持索引）
  C5 事实/机制      → L2 查阅（保持索引）
  C6 复盘记录       → 01-记忆 / 检索兜底

v3 修订（2026-08-22 对抗审查 10 条全采纳）：
  - 单一判据源：正则/触发词全部从 CLAUSES 生成，判据只存在于一张表
  - 锚点行净化：跳过表格行(/|/)/否定引用(违反/示例/不是)/标题(checkbox)行
  - 平局标记：primary==runner 得 ambiguous=True；boosted/raw_primary 全程可见
  - 词感知：剥 frontmatter + 宿主词排除（区别/类别/特别/级别 不触发 C2 的「别」）
  - 段落级硬化提取：bullet+缩进续行合并为段，对象词限定在禁止词同一窗口
  - markdown 净化：剥离 ** 格式化标记，跳过 # 行与代码围栏
  - 批量隔离：单页异常 try/except 落 error 行，报告带 run_status+timestamp
  - 已知词法极限（接受）：规则页示例文本含 C6 词（记忆-知识分类规则实证）→
    SDK 初判 + LLM 精判兜底，输出全部标 verdict=candidate

用法：
  python scripts/sys_classify_sdk.py                 # 全量 06-系统
  python scripts/sys_classify_sdk.py <某页.md>       # 单页（共享索引过滤）
  python scripts/test_sys_classify.py                # 回归测试（钉已知标签）
"""
import argparse
import json
import os
import re
import sys

SYS_DIR = r"D:\ObsidianVault\06-系统"
OUT_PATH = r"D:\AI OS\l2-memory\eval-harness\cache\sys_classify_report.json"
MODEL = __import__("modelz").load_models().get("default", "")  # 当前会话 model（复用本机配置单源）

# ── 判据词表（唯一判据源，可拔插：改这里 = 换判据，逻辑全自动跟随） ─────
CLAUSES = {
    "C1": ("第一原则", "永远", "一律", "不可协商", "底线", "必须"),
    "C2": ("禁止", "不能", "不可", "切勿", "禁放", "别", "不要", "移出"),
    "C3": ("每次", "遇到", "场景", "之前"),          # 仅情境引导词（实证防词污染）
    "C4": ("时机", "判定", "规则", "何时", "评估", "选择", "决定"),
    "C5": ("是什么", "机制", "原理", "位于", "架构", "配置", "路径", "注册", "事实"),
    "C6": ("排查", "现象", "根因", "踩坑", "经历", "复盘", "修复"),
}
CLASS_DESC = {
    "C1": "不可协商纪律 → L0 锚点候选（AGENTS.md）",
    "C2": "规避经验·机械可判 → harness 硬化条款",
    "C3": "规避经验·情境触发 → SKILL.md 描述候选",
    "C4": "流程/决策规则 → L1 检索（保持索引）",
    "C5": "事实/机制 → L2 查阅（保持索引）",
    "C6": "复盘记录 → 01-记忆 / 检索兜底",
}
# 宿主词排除（词感知：「别」在 区别/类别/特别/级别 中不算 C2）
HOST_EXCLUDE = ("区别", "类别", "特别", "级别")
# C2 硬化的对象词（禁止词同一窗口内需含其一才算可硬化条款）
HARDEN_OBJ = ("python", "heredoc", "jsonc", "目录", "脚本", "命令", "路径",
              "tools", "配置", "内联", "临时区", ".py", ".opencode")
# 沟通动词排除（仅「描述/复述/说明」类引导的句子不算硬化条款）
TALK_VERBS = ("描述", "复述", "说明", "用文字")

# ── 从 CLAUSES 单一生成正则（判据只存在一张表） ──────────────────────────
_alt = lambda k: "|".join(map(re.escape, CLAUSES[k]))
ANCHOR_RE = re.compile(f"({_alt('C1')})")
HARDEN_RE = re.compile(f"({_alt('C2')}).{{0,80}}(?:。|$)")
SKILL_WS = CLAUSES["C3"]           # skill 触发词直接引用判据表

MD_STRIP = re.compile(r"\*\*?|`")
FENCE_RE = re.compile(r"^```|^~~~")
HOST_RE = re.compile("|".join(map(re.escape, HOST_EXCLUDE)))


def _body(text):
    """剥 frontmatter + 跳过代码围栏段。"""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            text = text[end + 4:]
    lines, in_fence = [], False
    for ln in text.splitlines():
        if FENCE_RE.match(ln.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        lines.append(ln)
    return "\n".join(lines)


def _lines(text):
    """净化行：剥 markdown，跳过表格/标题/checkbox/锚点碎片。"""
    out = []
    for ln in _body(text).splitlines():
        s = ln.strip()
        if not s or s.startswith(("#", "|", "```", "- [")):
            continue
        out.append(MD_STRIP.sub("", s).strip())
    return out


def _segments(text):
    """段落级聚合：bullet + 缩进续行合并。"""
    segs, cur = [], None
    for ln in _body(text).splitlines():
        s = ln.strip()
        stripped = re.sub(r"^[-*]?\s*(?:[0-9]+\.\s*)?", "", s).strip()
        if not stripped or stripped.startswith(("#", "|")):
            continue
        if re.match(r"^[-*]\s", ln) or re.match(r"^[0-9]+\.\s", ln):
            if cur:
                segs.append(cur)
            cur = MD_STRIP.sub("", stripped)
        else:  # 非 bullet 行：正文行或续行
            stripped = MD_STRIP.sub("", stripped)
            if cur and not re.match(r"^[A-Za-z#]", stripped) and len(cur) > 30:
                cur += " " + stripped  # 视为续行
            elif stripped:
                segs.append(stripped)   # 独立正文段
    if cur:
        segs.append(cur)
    return [s for s in segs if 10 <= len(s) <= 400]


# ── 原子函数 ──────────────────────────────────────────────────────────

def classify(text):
    """六类计分 → {primary, raw_primary, boosted, ambiguous, scores}。

    主类=最高分；并列 → ambiguous=True（不静默选 C1）。
    锚点提升：C1 计分 ≥2 且提取到净化后的锚点条款 → primary=C1（boosted 标记）。
    """
    scores = {k: 0 for k in CLAUSES}
    body = _body(text)
    for k, ws in CLAUSES.items():
        for w in ws:
            n = body.count(w)
            if k == "C2" and w == "别":
                n = max(0, len(re.findall(r"别", body)) -
                        len(re.findall(HOST_RE.pattern, body)))
            scores[k] += n
    order = sorted(scores.items(), key=lambda kv: -kv[1])
    top, runner = order[0][1], order[1][1]
    raw_primary = order[0][0]
    ambiguous = top == runner
    boosted = False
    primary = raw_primary
    if scores["C1"] >= 2 and extract_anchors(text):
        primary, boosted = "C1", True
    return {
        "primary": primary, "raw_primary": raw_primary,
        "boosted": boosted, "ambiguous": ambiguous, "scores": scores,
    }


def extract_anchors(text):
    """C1 → L0 锚点候选：净化行中含锚点词的短句。跳过表格/否定引用。"""
    out, seen = [], set()
    for s in _lines(text):
        if len(s) <= 90 and ANCHOR_RE.search(s) and s not in seen \
                and not re.search(r"(违反|说明|示例|比如|并非|引用|区别)", s):
            seen.add(s)
            out.append(s)
    return out[:8]


def extract_harden(text):
    """C2 → 硬化条款候选：段落级，禁止词窗口内须含对象词；排除沟通句。"""
    out, seen = [], set()
    for seg in _segments(text):
        m = HARDEN_RE.search(seg)
        if not m:
            continue
        # 窗口 = 禁止词前 40 字符到段尾（覆盖「X 不可用」型：对象词在禁止词前）
        window = seg[max(0, m.start() - 40):]
        if not any(o.lower() in window.lower() for o in HARDEN_OBJ):
            continue
        if any(t in window for t in TALK_VERBS):
            continue
        if seg in seen:
            continue
        seen.add(seg)
        out.append(seg[:240])
    return out[:10]


def extract_skill_cands(text):
    """C3 → SKILL.md 描述候选：情境引导词段（词表引用 CLAUSES）。"""
    out, seen = [], set()
    for seg in _segments(text):
        if not any(w in seg for w in SKILL_WS):
            continue
        key = seg[:30]
        if key in seen:
            continue
        seen.add(key)
        out.append(seg[:240])
    return out[:6]


# ── 批量/报告 ─────────────────────────────────────────────────────────

def _page_filter(name):
    return name.endswith(".md") and "索引" not in name and not name.startswith("_")


def classify_all(dir_path=None):
    dir_path = dir_path or SYS_DIR
    report = {"run_status": "partial", "timestamp": None, "pages": []}
    import datetime
    report["timestamp"] = datetime.datetime.now().isoformat(timespec="seconds")
    for name in sorted(p for p in os.listdir(dir_path) if _page_filter(p)):
        try:
            text = open(os.path.join(dir_path, name), encoding="utf-8").read()
            r = classify(text)
            report["pages"].append({
                "file": name,
                "verdict": "candidate",
                "primary": r["primary"], "raw_primary": r["raw_primary"],
                "boosted": r["boosted"], "ambiguous": r["ambiguous"],
                "scores": r["scores"],
                "primary_desc": CLASS_DESC[r["primary"]],
                "mixed": [k for k, s in sorted(r["scores"].items(),
                                               key=lambda kv: -kv[1])[1:]
                          if s >= 2 and k != r["primary"]],
                "anchors": extract_anchors(text),
                "harden": extract_harden(text),
                "skill_cands": extract_skill_cands(text),
            })
        except Exception as e:  # 单页隔离：失败不杀全量
            report["pages"].append({"file": name, "error": str(e)})
    report["run_status"] = "complete"
    return report


def _single(page):
    p = page if os.path.isabs(page) else os.path.join(SYS_DIR, page)
    if not _page_filter(os.path.basename(p)):
        return {"run_status": "skipped", "reason": "index/meta page excluded",
                "pages": []}
    text = open(p, encoding="utf-8").read()
    r = classify(text)
    return {"run_status": "complete", "pages": [{
        "file": os.path.basename(p), "verdict": "candidate",
        "primary": r["primary"], "raw_primary": r["raw_primary"],
        "boosted": r["boosted"], "ambiguous": r["ambiguous"],
        "scores": r["scores"], "primary_desc": CLASS_DESC[r["primary"]],
        "mixed": [k for k, s in sorted(r["scores"].items(),
                                       key=lambda kv: -kv[1])[1:]
                  if s >= 2 and k != r["primary"]],
        "anchors": extract_anchors(text),
        "harden": extract_harden(text),
        "skill_cands": extract_skill_cands(text),
    }]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page", nargs="?", default=None)
    args = ap.parse_args()
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    report = _single(args.page) if args.page else classify_all()
    for r in report["pages"]:
        if "error" in r:
            print(f"-- {r['file']} ERROR: {r['error']}")
            continue
        tag = ""
        if r["ambiguous"]:
            tag += " [平局]"
        if r["boosted"]:
            tag += f" [锚点提升 {r['raw_primary']}→{r['primary']}]"
        print(f"-- {r['file']}{tag}")
        print(f"  主类 {r['primary']} | {r['primary_desc']} | 原始 {r['raw_primary']} | 混合 {r['mixed'] or '无'}")
        print(f"  计分 {r['scores']}")
        if r["anchors"]:
            print("  [L0 锚点候选] " + " ‖ ".join(r["anchors"]))
        if r["harden"]:
            print("  [硬化条款]   " + " ‖ ".join(r["harden"][:3]))
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"报告已存: {OUT_PATH} ({report['run_status']}, {len(report['pages'])} 页) "
          f"| model={MODEL}")


if __name__ == "__main__":
    main()