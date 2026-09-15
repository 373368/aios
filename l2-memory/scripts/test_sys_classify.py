# -*- coding: utf-8 -*-
"""sys_classify_sdk 回归测试：钉 06-系统 6 个已知页标签 + 3 个修正案。

用法：python scripts/test_sys_classify.py
无框架纯 assert。判据词表 CLAUSES 变更后必须重跑（防标签漂移）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sys_classify_sdk import classify, extract_harden, _page_filter

SYS = r"D:\ObsidianVault\06-系统"


def read(name):
    return open(os.path.join(SYS, name), encoding="utf-8").read()


def test_known_labels():
    """6 个已确认语义标签（2026-08-22 索引第三节）。"""
    expect = {
        "opencode 系统配置.md": "C5",
        "opencode空回复排查与tools目录注入机制.md": "C6",
        "工作约定.md": "C2",
        "工具调用格式纪律.md": "C1",
        "智能体执行纪律.md": "C1",
        "沉淀触发规则.md": "C4",
    }
    for name, want in expect.items():
        r = classify(read(name))
        assert r["primary"] == want, f"{name}: 期望 {want} 实际 {r['primary']} {r['scores']}"
        print(f"OK {name} -> {want} (raw={r['raw_primary']} boosted={r['boosted']} "
              f"ambiguous={r['ambiguous']})")


def test_regressions():
    """3 个修正案回归。"""
    # 1. 工具调用格式纪律：排错文档形态但锚点条款 → C1（锚点提升）
    r = classify(read("工具调用格式纪律.md"))
    assert r["primary"] == "C1" and r["boosted"], "工具调用格式纪律应锚点提升 C1"
    # 2. 沉淀触发规则：C3 词表修正后不被词污染 → C4
    r = classify(read("沉淀触发规则.md"))
    assert r["primary"] == "C4", f"沉淀触发规则应为 C4: {r['scores']}"
    # 3. 空回复页：C2 单一判据源 → 硬化条款必须提取到（油猴条款）
    h = extract_harden(read("opencode空回复排查与tools目录注入机制.md"))
    assert h, "空回复页应提取硬化条款（油猴脚本移出 .opencode/tools）"
    assert any("tools" in s for s in h), f"硬化条款应含 tools 对象: {h}"
    # 4. 工作约定：PowerShell 三条款全部提取（含「X 不可用」型对象词在前）
    hw = extract_harden(read("工作约定.md"))
    assert len(hw) >= 3, f"工作约定应提取 ≥3 硬化条款，实际 {len(hw)}: {hw}"
    assert any("heredoc" in s.lower() for s in hw), f"heredoc 条款应被提取: {hw}"


def test_filter():
    assert not _page_filter("06-系统索引.md"), "索引页应被过滤"
    assert _page_filter("opencode 系统配置.md"), "普通页不应被过滤"


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    test_filter()
    test_regressions()
    test_known_labels()
    print("\n全部回归通过（6 标签 + 3 修正案 + 过滤）")