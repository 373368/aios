# -*- coding: utf-8 -*-
"""原语节点（agent → primitive 协作）离线测试：无 LLM、无网络。

覆盖：
  1. 链路：script-smoke.yaml 两原语节点串联（state → argv 渲染 → state 回写）
  2. json 解析：wfprobe stdout 按 JSON 解析为 list
  3. 失效可见：原语缺失（加载期）/ 原语异常退出（运行期）均报错不静默
  4. 声明身份：md 解析（frontmatter/纯文本/空正文报错）/ 声明缺失报错 / 声明模型优先
"""
import os
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agentgraph as ag  # noqa: E402


def _write(path, spec):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(spec, f, allow_unicode=True)


def _mini_spec(primitive):
    return {"kind": "AgentGraph",
            "state": {"x": {"type": "str"}},
            "nodes": [{"id": "p", "kind": "primitive", "primitive": primitive, "output": "x"}],
            "edges": [["START", "p"], ["p", "END"]]}


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    tmp = tempfile.mkdtemp(prefix="agentgraph-test-")

    # 1+2: 持久冒烟 spec（离线、秒级）
    spec = ag.load_spec(os.path.join(HERE, "specs", "script-smoke.yaml"))
    final = dict(ag.build_graph(spec).invoke(ag._init_state(spec, {"seed": "abc"})))
    assert final["probe"] == ["hello", "abc"], f"probe={final['probe']!r}"
    assert final["again"] and "hello" in final["again"][0], f"again={final['again']!r}"

    # 3a: 原语缺失 → 加载期报错
    p1 = os.path.join(tmp, "bad1.yaml")
    _write(p1, _mini_spec("no-such-script"))
    try:
        ag.load_spec(p1)
        raise AssertionError("原语缺失未报错")
    except SystemExit as e:
        assert "no-such-script" in str(e), f"错误信息不符: {e}"

    # 3b: 原语异常退出 → 运行期报错（含退出码与 stderr 摘要）
    fail_py = os.path.join(tmp, "fail.py")
    with open(fail_py, "w", encoding="utf-8") as f:
        f.write("import sys\nsys.stderr.write('boom')\nsys.exit(7)\n")
    p2 = os.path.join(tmp, "bad2.yaml")
    _write(p2, _mini_spec(fail_py))
    spec2 = ag.load_spec(p2)
    try:
        ag.build_graph(spec2).invoke(ag._init_state(spec2, {}))
        raise AssertionError("异常退出未报错")
    except Exception as e:
        assert "code=7" in str(e) and "boom" in str(e), f"错误信息不符: {e}"

    # 3c: outputs 契约——声明 state 外字段 → 加载期报错
    d = _mini_spec("wfprobe")
    d["outputs"] = ["nope"]
    p3 = os.path.join(tmp, "bad3.yaml")
    _write(p3, d)
    try:
        ag.load_spec(p3)
        raise AssertionError("outputs 未知字段未报错")
    except SystemExit as e:
        assert "outputs 引用未知状态字段" in str(e), f"错误信息不符: {e}"

    # 3d: outputs 契约——state 内但无节点写入 → 加载期报错
    d = _mini_spec("wfprobe")
    d["state"]["y"] = {"type": "str"}
    d["outputs"] = ["y"]
    p4 = os.path.join(tmp, "bad4.yaml")
    _write(p4, d)
    try:
        ag.load_spec(p4)
        raise AssertionError("outputs 未接线未报错")
    except SystemExit as e:
        assert "未被任何节点写入" in str(e), f"错误信息不符: {e}"

    # 4a: 声明加载——frontmatter + 正文
    d1 = os.path.join(tmp, "decl1.md")
    with open(d1, "w", encoding="utf-8") as f:
        f.write("---\nname: t-agent\nmodel: fake/ref\n---\n你是 T。\n")
    meta, body = ag.load_declaration(d1)
    assert meta.get("name") == "t-agent" and meta.get("model") == "fake/ref", f"meta={meta!r}"
    assert body == "你是 T。", f"body={body!r}"

    # 4b: 无 frontmatter → 全文为正文
    d2 = os.path.join(tmp, "decl2.md")
    with open(d2, "w", encoding="utf-8") as f:
        f.write("你是 U。\n")
    meta2, body2 = ag.load_declaration(d2)
    assert meta2 == {} and body2 == "你是 U。", f"meta={meta2!r} body={body2!r}"

    # 4c: 声明缺失 → 加载期报错
    d = {"kind": "AgentGraph", "state": {"x": {"type": "str"}},
         "nodes": [{"id": "a", "declaration": "no-such.md", "prompt": "hi", "output": "x"}],
         "edges": [["START", "a"], ["a", "END"]]}
    p5 = os.path.join(tmp, "bad5.yaml")
    _write(p5, d)
    try:
        ag.load_spec(p5)
        raise AssertionError("声明缺失未报错")
    except SystemExit as e:
        assert "声明文件不存在" in str(e), f"错误信息不符: {e}"

    # 4d: 空正文 → 加载期报错
    d3 = os.path.join(tmp, "decl3.md")
    with open(d3, "w", encoding="utf-8") as f:
        f.write("---\nname: empty\n---\n\n")
    try:
        ag.load_declaration(d3)
        raise AssertionError("空正文未报错")
    except SystemExit as e:
        assert "正文" in str(e), f"错误信息不符: {e}"

    # 4e: 声明 model 参与 used_models（优先级：声明 > 节点 > spec）
    d4 = {"kind": "AgentGraph", "model": "spec/ref", "state": {"x": {"type": "str"}},
          "nodes": [{"id": "a", "declaration": d1, "prompt": "hi", "output": "x"}],
          "edges": [["START", "a"], ["a", "END"]]}
    p6 = os.path.join(tmp, "spec6.yaml")
    _write(p6, d4)
    spec6 = ag.load_spec(p6)
    assert ag.used_models(spec6) == {"fake/ref"}, f"models={ag.used_models(spec6)}"
    assert spec6["nodes"][0]["decl_name"] == "t-agent"

    print("OK: 原语节点离线测试通过 | 链路 ✓ / json ✓ / 失效可见 ✓（加载期+运行期）| "
          "outputs 契约 ✓（未知字段/未接线）| 声明身份 ✓（解析/缺失/空正文/模型优先）")


if __name__ == "__main__":
    main()
