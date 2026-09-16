# -*- coding: utf-8 -*-
"""agentgraph — LangGraph 声明式并行 agents。

YAML 声明图（节点/边/状态/模型）→ 编译为 LangGraph StateGraph 执行：
  - 声明式：拓扑、prompt、模型引用全部在 YAML
  - 并行：同一起点多条出边 = fan-out（同 superstep 内并行执行）；
          fan-in 节点自动等待全部上游；list + reducer=add 合并并行写入
  - 节点类型：llm（默认，prompt/{state字段}渲染）/ primitive（调 scripts|tasks 脚本原语，
              argv 支持 {state字段} 渲染，json: true 解析 stdout）
  - 产出契约：outputs 声明对外产出字段；check 校验（在 state 内 且 被节点写入）
  - 模型：引用 config.json "provider/model"，经 modelz 解析（仅 openai 兼容来源）

用法：
  python agentgraph.py check <spec.yaml>                 # 离线：校验 + 编译（不调 LLM）
  python agentgraph.py graph <spec.yaml>                 # 打印 mermaid 拓扑
  python agentgraph.py run   <spec.yaml> [--input k=v] [--json]

ponytail: 无 checkpointer / 工具节点 / HITL；需要断点续跑或工具调用时
再接（langgraph.checkpoint.*、prebuilt ToolNode）。
"""
import argparse
import json
import operator
import os
import re
import sys
import time
from typing import Annotated, TypedDict

import yaml
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

AGENTGRAPH_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AGENTGRAPH_DIR, "..", "scripts"))
import modelz  # noqa: E402
from common import run_capture  # noqa: E402

TYPES = {"str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict}
REDUCERS = {"add": operator.add}
DEFAULTS = {"str": "", "int": 0, "float": 0.0, "bool": False, "list": list, "dict": dict}
_LLM_CACHE = {}


def _fail(msg):
    raise SystemExit(f"[agentgraph] {msg}")


def load_spec(path):
    with open(path, encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    if not isinstance(spec, dict) or spec.get("kind") != "AgentGraph":
        _fail(f"{path}: kind 必须是 AgentGraph")
    spec.setdefault("state", {})
    spec.setdefault("nodes", [])
    spec.setdefault("edges", [])
    if spec.get("trace"):
        spec["state"].setdefault("trace", {"type": "list", "reducer": "add"})
    for name, f in spec["state"].items():
        if f is None:
            spec["state"][name] = f = {}
        if f.get("type", "str") not in TYPES:
            _fail(f"state.{name}: 未知类型 {f.get('type')}（可选 {sorted(TYPES)}）")
        if f.get("reducer") not in (None, "overwrite", "add"):
            _fail(f"state.{name}: 未知 reducer {f.get('reducer')}（可选 add/overwrite）")
    ids = [n.get("id") for n in spec["nodes"]]
    if not ids or None in ids or len(ids) != len(set(ids)):
        _fail("nodes 为空、存在缺 id 或 id 重复")
    for n in spec["nodes"]:
        kind = n.get("kind", "llm")
        if kind not in ("llm", "primitive"):
            _fail(f"节点 {n.get('id')}: 未知 kind {kind}（可选 llm/primitive）")
        for k in ("id", "output"):
            if not n.get(k):
                _fail(f"节点 {n.get('id')}: 缺字段 {k}")
        if n["output"] not in spec["state"]:
            _fail(f"节点 {n['id']}: output 字段 {n['output']} 不在 state 中")
        refs = []
        if kind == "llm":
            if not n.get("prompt"):
                _fail(f"节点 {n['id']}: llm 节点缺 prompt")
            refs.append(n["prompt"])
        else:
            if not n.get("primitive"):
                _fail(f"节点 {n['id']}: primitive 节点缺 primitive")
            if not isinstance(n.get("args", []), list):
                _fail(f"节点 {n['id']}: args 必须是列表")
            refs.extend(str(a) for a in n.get("args", []))
            n["script_path"] = _resolve_primitive(n["primitive"])
        for tpl in refs:
            unknown = set(re.findall(r"\{(\w+)\}", tpl)) - set(spec["state"])
            if unknown:
                _fail(f"节点 {n['id']}: 模板引用未知状态字段 {sorted(unknown)}")
    outputs = spec.get("outputs", [])
    if outputs:
        if not isinstance(outputs, list) or not all(isinstance(o, str) for o in outputs):
            _fail("outputs 必须是字符串列表")
        unknown = set(outputs) - set(spec["state"])
        if unknown:
            _fail(f"outputs 引用未知状态字段: {sorted(unknown)}")
        unwired = set(outputs) - {n["output"] for n in spec["nodes"]}
        if unwired:
            _fail(f"outputs 未被任何节点写入: {sorted(unwired)}")
    known = set(ids)
    for e in spec["edges"]:
        if not isinstance(e, list) or len(e) != 2:
            _fail(f"edges 必须是 [from, to] 二元组: {e}")
        for ep in e:
            if ep not in known and ep not in ("START", "END"):
                _fail(f"edge 引用未知节点: {ep}")
    return spec


def used_models(spec):
    default_ref = spec.get("model") or modelz.load_models().get("default")
    return {n.get("model") or default_ref for n in spec["nodes"]
            if n.get("kind", "llm") == "llm"}


def build_llm(ref):
    if ref in _LLM_CACHE:
        return _LLM_CACHE[ref]
    info = modelz.resolve(ref)
    if info["kind"] != "openai":
        _fail(f"模型 {ref} 的来源 kind={info['kind']}；LangGraph 侧仅支持 openai 兼容来源"
              f"（例：volcengine-agent-plan/deepseek-v4-flash）")
    llm = ChatOpenAI(model=info["model"], base_url=info["base"], api_key=info["api_key"],
                     timeout=180, max_retries=2)
    _LLM_CACHE[ref] = llm
    return llm


def _render(tpl, state):
    def sub(m):
        v = state.get(m.group(1), "")
        if isinstance(v, list):
            return "\n".join(f"- {i}" for i in v)
        if isinstance(v, dict):
            return json.dumps(v, ensure_ascii=False)
        return str(v)
    return re.sub(r"\{(\w+)\}", sub, tpl)


def _extract_json(text):
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    return json.loads(m.group(1) if m else text)


def _add_trace(spec, node, t0, result):
    if spec.get("trace"):
        result["trace"] = [{"node": node["id"], "t0": round(t0, 3),
                            "t1": round(time.time(), 3)}]


def _resolve_primitive(name):
    """原语脚本解析：绝对路径原样；否则 scripts/ 或 tasks/ 下（自动补 .py）。"""
    if os.path.isabs(name):
        if os.path.exists(name):
            return name
        _fail(f"原语脚本不存在: {name}")
    for base in ("scripts", "tasks"):
        cand = os.path.normpath(os.path.join(AGENTGRAPH_DIR, "..", base, name))
        cand_py = cand if cand.endswith(".py") else cand + ".py"
        if os.path.exists(cand_py):
            return cand_py
    _fail(f"原语脚本不存在: {name}（scripts/ 或 tasks/）")


def make_primitive_node(spec, node):
    """primitive 节点：子进程调用脚本原语（stdout=数据 / stderr=日志 / exit=状态）。"""
    out_field = node["output"]
    out_is_list = spec["state"][out_field].get("type") == "list"
    script = node["script_path"]

    def fn(cur):
        t0 = time.time()
        argv = [sys.executable, script] + [_render(str(a), cur) for a in node.get("args", [])]
        code, out, err = run_capture(argv)
        if code != 0:
            raise RuntimeError(f"[agentgraph] 原语 {node['primitive']} 失败 code={code}: "
                               f"{(err or out).strip()[:300]}")
        if node.get("json"):
            try:
                value = json.loads(out.strip())
            except json.JSONDecodeError as e:
                raise RuntimeError(f"[agentgraph] 原语 {node['primitive']} 输出非 JSON: "
                                   f"{out[:200]} ({e})")
        else:
            value = out.strip()
        if out_is_list and not isinstance(value, list):
            value = [value]
        result = {out_field: value}
        _add_trace(spec, node, t0, result)
        return result
    return fn


def make_llm_node(spec, node):
    out_field = node["output"]
    out_is_list = spec["state"][out_field].get("type") == "list"

    def fn(cur):
        t0 = time.time()
        msgs = []
        if node.get("system"):
            msgs.append(("system", _render(node["system"], cur)))
        msgs.append(("human", _render(node["prompt"], cur)))
        resp = build_llm(node.get("model") or spec.get("model") or
                         modelz.load_models().get("default")).invoke(msgs)
        content = resp.content
        text = content if isinstance(content, str) else "".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
        value = _extract_json(text) if node.get("json") else text.strip()
        if out_is_list and not isinstance(value, list):
            value = [value]
        result = {out_field: value}
        _add_trace(spec, node, t0, result)
        return result
    return fn


def _field_type(f):
    t = TYPES[f.get("type", "str")]
    if f.get("reducer") == "add":
        return Annotated[t, REDUCERS["add"]]
    return t


def build_graph(spec):
    state_cls = TypedDict("AgentState",
                          {name: _field_type(f) for name, f in spec["state"].items()},
                          total=False)
    g = StateGraph(state_cls)
    for n in spec["nodes"]:
        factory = make_primitive_node if n.get("kind") == "primitive" else make_llm_node
        g.add_node(n["id"], factory(spec, n))
    vmap = {"START": START, "END": END}
    for a, b in spec["edges"]:
        g.add_edge(vmap.get(a, a), vmap.get(b, b))
    return g.compile()


def _cast(raw, t):
    if t == "int":
        return int(raw)
    if t == "float":
        return float(raw)
    if t == "bool":
        return raw.lower() in ("1", "true", "yes")
    if t in ("list", "dict"):
        return json.loads(raw)
    return raw


def _init_state(spec, inputs):
    init = {}
    for name, f in spec["state"].items():
        t = f.get("type", "str")
        init[name] = DEFAULTS[t]() if t in ("list", "dict") else DEFAULTS[t]
    for k, v in inputs.items():
        if k not in spec["state"]:
            _fail(f"--input {k} 不在 state 中（可用: {sorted(spec['state'])}）")
        init[k] = _cast(v, spec["state"][k].get("type", "str"))
    return init


def _print_result(final, as_json):
    if as_json:
        print(json.dumps(final, ensure_ascii=False, indent=2))
        return
    for k, v in final.items():
        if k == "trace":
            continue
        print(f"== {k} ==")
        print(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2))
    trace = final.get("trace")
    if isinstance(trace, list) and trace:
        base = min(r["t0"] for r in trace)
        print("== trace ==")
        for r in sorted(trace, key=lambda r: r["t0"]):
            print(f"  {r['node']}: +{r['t0'] - base:.2f}s → +{r['t1'] - base:.2f}s")
        overlaps = sum(1 for i, a in enumerate(trace) for b in trace[i + 1:]
                       if b["t0"] < a["t1"] and a["t0"] < b["t1"])
        print(f"  并行重叠对: {overlaps}")


def cmd_check(spec_path):
    spec = load_spec(spec_path)
    build_graph(spec)
    refs = sorted(used_models(spec))
    for ref in refs:
        build_llm(ref)
    name = (spec.get("metadata") or {}).get("name", spec_path)
    print(f"OK: {name} | {len(spec['nodes'])} 节点 / {len(spec['edges'])} 边 | 模型 {refs}")


def cmd_graph(spec_path):
    print(build_graph(load_spec(spec_path)).get_graph().draw_mermaid())


def cmd_run(spec_path, inputs, as_json):
    spec = load_spec(spec_path)
    app = build_graph(spec)
    init = _init_state(spec, inputs)
    t0 = time.time()
    final = dict(app.invoke(init))
    print(f"[agentgraph] 执行完成 {time.time() - t0:.2f}s", file=sys.stderr)
    _print_result(final, as_json)


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="agentgraph")
    sub = p.add_subparsers(dest="cmd", required=True)
    for cmd in ("check", "graph", "run"):
        sp = sub.add_parser(cmd)
        sp.add_argument("spec")
        if cmd == "run":
            sp.add_argument("--input", action="append", default=[],
                            help="k=v，可重复；list/dict 用 JSON")
            sp.add_argument("--json", action="store_true")
    args = p.parse_args()
    if args.cmd == "check":
        cmd_check(args.spec)
    elif args.cmd == "graph":
        cmd_graph(args.spec)
    else:
        inputs = {}
        for kv in args.input:
            k, _, v = kv.partition("=")
            inputs[k] = v
        cmd_run(args.spec, inputs, args.json)


if __name__ == "__main__":
    main()
