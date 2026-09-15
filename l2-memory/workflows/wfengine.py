# -*- coding: utf-8 -*-
"""声明式工作流引擎（私有 AI-OS 三层：YAML 编排 → 原语执行 → LLM 判断点）。

schema 对齐微软 Agent Framework Declarative Workflows 1.0 范式：
kind: Workflow + trigger + variables + actions（InvokePrimitive / InvokeLLM /
ConditionGroup / Loop）。表达式用 = 前缀（=System.Args.x / =Local.x / =Loop.Item）。
原语经 common.run_py 子进程调用；LLM 判断点经 modelz.chat。
"""
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sdk"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from common import log, run_py, default_ref, judge_ref  # noqa: E402
from modelz import chat  # noqa: E402

WORKFLOWS = os.path.dirname(os.path.abspath(__file__))
PROMPTS = os.path.join(WORKFLOWS, "prompts")


class WFError(Exception):
    pass


class Scope:
    """执行状态：System(CLI args+模型) / Local(动作间变量) / Loop(循环栈)。"""

    def __init__(self, args):
        import primitives as P
        self.system = {"Args": args, "DefaultModel": default_ref(), "JudgeModel": judge_ref(),
                       "MemRoot": P.MEM_SCAN_ROOT, "MemVaultRoot": P.MEM_ROOT,
                       "KbRoot": P.KB_ROOT}
        self.local = {}
        self.loop = []

    def eval(self, expr):
        """求值表达式：=引用 / 字面量。表达式支持 a.b 属性、[i] 索引、比较运算。
        比较运算：=Local.x == "v" / != / > / < / >= / <=（右侧引号值或数字）。"""
        if not isinstance(expr, str) or not expr.startswith("="):
            return expr
        body = expr[1:].strip()
        # 比较运算（对齐微软 Power Fx 表达式）
        import re as _re
        m = _re.match(r'^([^<>!=]+)(==|!=|>=|<=|>|<)(.*)$', body)
        if m:
            left = self._resolve_path(m.group(1).strip())
            right = self._resolve_right(m.group(3).strip())
            op = m.group(2)
            return {"==": lambda: left == right,
                    "!=": lambda: left != right,
                    ">=": lambda: left >= right,
                    "<=": lambda: left <= right,
                    ">": lambda: left > right,
                    "<": lambda: left < right}[op]()
        return self._resolve_path(body)

    def _resolve_path(self, path):
        if path.startswith("Loop."):
            if not self.loop:
                raise WFError(f"Loop 表达式在循环外: {path}")
            root = self.loop[-1]
        elif path.startswith("System."):
            root = self.system
        elif path.startswith("Local."):
            root = self.local
        else:
            root = None
        if root is None:
            raise WFError(f"未知表达式作用域: {path}")
        seg = path.split(".", 1)[1] if "." in path else ""
        if path.startswith("Loop.") and seg.startswith("Item"):
            seg = seg[len("Item"):].lstrip(".")
        return self._get(root, seg)

    @staticmethod
    def _resolve_right(raw):
        raw = raw.strip()
        if raw.startswith(("'", '"')) and raw.endswith(("'", '"')):
            return raw[1:-1]
        try:
            return int(raw)
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            return raw

    @staticmethod
    def _get(root, seg):
        cur = root
        for part in seg.split("."):
            if not part:
                continue
            idx = None
            if part.endswith("]"):
                name, _, i = part.partition("[")
                idx = int(i.rstrip("]"))
                part = name
            if isinstance(cur, dict):
                cur = cur.get(part, {})
            elif isinstance(cur, list) and part.isdigit():
                cur = cur[int(part)]
            elif isinstance(cur, list):
                cur = cur[idx] if idx is not None else cur
            else:
                return None
            if idx is not None:
                cur = cur[idx] if isinstance(cur, list) else {}
        return cur


def _resolve_args(scope, args):
    """动作 args 全字段求值。"""
    if not isinstance(args, dict):
        return scope.eval(args)
    return {k: _resolve_args(scope, v) if isinstance(v, (dict, list)) else scope.eval(v)
            for k, v in args.items()}


def _interp(scope, raw):
    """把 {LocalVar} 内嵌替换为值（供 primitive 名/路径等字段用）。"""
    raw = str(raw)
    for var in scope.local:
        raw = raw.replace("{" + var + "}", str(scope.local[var]).replace("\\", "/"))
    return raw


def run_action(scope, act):
    kind = act.get("kind")
    # 顶层 when 条件（微软范式：动作可带 when）
    if act.get("when"):
        if not _truthy(scope.eval(act["when"])):
            return None
    if kind == "InvokePrimitive":
        args = _resolve_args(scope, act.get("args", {}))
        if "primitive" not in act:
            raise WFError("InvokePrimitive 缺 primitive")
        primitive = _interp(scope, act["primitive"])
        # 原语经 primitives CLI 分发（命名参数 JSON）或独立脚本（argparse 风格）
        if act.get("via") == "primitives":
            code, out = run_py("primitives", primitive, json.dumps(args, ensure_ascii=False))
        else:
            # 独立脚本：布尔 True→--flag，普通值→--key value
            argv = []
            for k, v in sorted(args.items()):
                if v is True:
                    argv.append(f"--{k}")
                elif v is False:
                    continue
                else:
                    argv.extend([f"--{k}", str(v)])
            code, out = run_py(primitive, *argv)
        if code != 0:
            raise WFError(f"{primitive} 失败 code={code}: {out[:300]}")
        # 原语 stdout → 结果：JSON 解析（json=true 或 primitives 分发）
        result = out.strip()
        if act.get("args", {}).get("json") or act.get("via") == "primitives":
            try:
                result = json.loads(result)
            except json.JSONDecodeError as e:
                raise WFError(f"{primitive} 输出非 JSON: {result[:200]} ({e})")
        if "output" in act:
            target = act["output"]
            if isinstance(target, str):
                # 简写：output: Local.Candidates → 结果直接存该变量
                if str(target).startswith("=Local."):
                    scope.local[str(target)[7:]] = result
                else:
                    scope.local[target] = result
            elif isinstance(target, dict):
                for var, expr in target.items():
                    if expr is None or str(expr).startswith("=Local."):
                        scope.local[var] = result
                    elif str(expr).startswith("="):
                        scope.local[var] = scope.eval(expr)
                    else:
                        scope.local[var] = result
        return out

    if kind == "SetVariable":
        # 微软 Declarative Workflows 动作：将值（支持 {var} 内嵌替换）写入 Local
        raw = str(act.get("value", ""))
        raw = _interp(scope, raw)
        # 再求值：=Local.X 路径或字面量
        scope.local[act["var"]] = scope.eval(raw)
        return scope.local[act["var"]]

    if kind == "InvokeLLM":
        prompt_tpl = act.get("prompt_template")
        if prompt_tpl:
            path = os.path.join(PROMPTS, f"{prompt_tpl}.txt")
            if not os.path.exists(path):
                raise WFError(f"prompt 模板不存在: {path}")
            prompt = open(path, encoding="utf-8").read()
            inp = scope.eval(act.get("input"))
            if inp is not None:
                prompt = prompt.replace("{content}", str(inp))
        else:
            prompt = str(scope.eval(act.get("prompt", "")))
        model = scope.eval(act.get("model")) or scope.system["JudgeModel"]
        raw = chat([{"role": "user", "content": prompt}], ref=model, temperature=0.2, timeout=300)
        result = raw
        if act.get("json_output"):
            result = _extract_json(raw)
        outvar = act.get("output")
        if isinstance(outvar, dict):
            for var, expr in outvar.items():
                scope.local[var] = result if str(expr).startswith("=") else expr
        elif isinstance(outvar, str):
            name = outvar
            if name.startswith("=Local."):
                name = name[len("=Local."):]
            scope.local[name] = result
        return result

    if kind == "ConditionGroup":
        for cond in act.get("conditions", []):
            when = cond.get("when")
            hit = _truthy(scope.eval(when)) if when else True
            if hit:
                for sub in cond.get("actions", []):
                    run_action(scope, sub)
                break
        return None

    if kind == "Loop":
        items = scope.eval(act.get("over")) or []
        for item in items:
            scope.loop.append(item)
            for sub in act.get("actions", []):
                run_action(scope, sub)
            scope.loop.pop()
        return None

    raise WFError(f"未知动作 kind: {kind}")


def _extract_json(raw):
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b <= a:
        raise WFError(f"LLM 未返回 JSON: {raw[:200]}")
    return json.loads(s[a:b + 1])


def _truthy(v):
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes", "on")
    return bool(v)


def run_workflow(wf_path, args):
    with open(wf_path, encoding="utf-8") as f:
        wf = yaml.safe_load(f)
    if wf.get("kind") != "Workflow":
        raise WFError("不是 Workflow 声明")
    scope = Scope(args)
    for var, expr in wf.get("variables", {}).items():
        scope.local[var] = scope.eval(expr)
    for act in wf.get("actions", []):
        run_action(scope, act)
    log(wf["metadata"]["name"], f"完成 actions={len(wf.get('actions', []))}")


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("用法: python wfengine.py <workflow.yaml> [key=value ...]")
        return 1
    wf = sys.argv[1]
    args = dict(a.split("=", 1) for a in sys.argv[2:])
    try:
        run_workflow(wf, args)
        return 0
    except Exception as e:
        log("wfengine", f"ERROR {wf}: {e}")
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())