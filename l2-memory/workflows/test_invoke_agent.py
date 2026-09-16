# -*- coding: utf-8 -*-
"""InvokeAgent 冒烟测试：工作流 → agent 图 协作链路。

阶段 1（真实 LLM，~20s）：wf-test-agent.yaml 调 parallel-analysts，捕获最终状态
阶段 2（离线，秒级）：expects 契约——满足则过、缺失/空值则 WFError
"""
import os
import sys
import tempfile

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wfengine import WFError, Scope, run_action, run_workflow  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def _expects_workflow(tmp_dir, expects):
    wf = {"kind": "Workflow",
          "metadata": {"name": "wf-expects-test"},
          "actions": [{"kind": "InvokeAgent",
                       "spec": "../agentgraph/specs/script-smoke.yaml",
                       "input": {"seed": "x"},
                       "output": "=Local.R",
                       "expects": expects}]}
    path = os.path.join(tmp_dir, "wf-expects-test.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(wf, f, allow_unicode=True)
    return path


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    # 阶段 1：真实链路（LLM）
    local = run_workflow(os.path.join(HERE, "wf-test-agent.yaml"), {})
    out = local.get("Analysis")
    assert isinstance(out, dict), f"Analysis 期望 dict，收到 {type(out).__name__}"
    assert isinstance(out.get("report"), str) and out["report"].strip(), "report 为空"
    findings = out.get("findings") or []
    assert isinstance(findings, list) and len(findings) == 3, f"findings 期望 3 条，收到 {len(findings)}"

    # 失效可见：spec 缺失
    try:
        run_action(Scope({}), {"kind": "InvokeAgent", "spec": "no-such-agent.yaml"})
        raise AssertionError("spec 缺失未报错")
    except WFError:
        pass

    # 阶段 2：expects 契约（离线，script-smoke 纯原语 spec）
    tmp = tempfile.mkdtemp(prefix="wf-expects-")
    local2 = run_workflow(_expects_workflow(tmp, ["probe"]), {})
    assert local2.get("R", {}).get("probe") == ["hello", "x"], f"R={local2.get('R')!r}"
    try:
        run_workflow(_expects_workflow(tmp, ["probe", "missing_field"]), {})
        raise AssertionError("expects 缺失字段未报错")
    except WFError as e:
        assert "missing_field" in str(e), f"错误信息不符: {e}"

    print(f"OK: InvokeAgent 冒烟通过 | report {len(out['report'])} 字 | findings {len(findings)} 条 | "
          f"spec缺失 ✓ | expects 契约 ✓（满足/缺失）")


if __name__ == "__main__":
    main()
