# -*- coding: utf-8 -*-
"""wfctl — wfengine 工作流规范化桥接层（触发/监控/渲染 + 身份注册管理）。

把 l2-memory 已写好的工作流（wfengine YAML）与 agent 身份声明暴露成接口，
供控制核心/UI（AiosShell 的 /wfctl 路由）触发与监控。

用法：
  python wfctl.py list                         # 列出可用工作流
  python wfctl.py catalog                      # 能力目录（工作流 + agent specs；输入元数据/关联/调用方）
  python wfctl.py trigger <wf> <k=v...>        # 同步触发（跑 wfengine），退出码透传
  python wfctl.py run-agent <spec> <k=v...>    # 直跑 agentgraph spec（single-flight；stdout/stderr/退出码透传）
  python wfctl.py agents-suggest --brief <文本>  # AI 填充：brief → 身份草案建议（只读，不落盘）
  python wfctl.py status <wf>                  # 读日志尾部 + 判定状态（文本）
  python wfctl.py render <wf>                  # 输出结构化 JSON（给 UI/监控）
  python wfctl.py agents                       # 身份声明 + goal 注册状态（JSON）
  python wfctl.py agents-register --agent-id <a[,b...]> --goal-id <g> [--execute]
                                               # 注册身份到 goal（缺省预览；--execute 写入）
  python wfctl.py agents-unregister --agent-id <a[,b...]> --goal-id <g> [--execute]
                                               # 从 goal 名单移除身份（缺省预览；--execute 写入）
  python wfctl.py agents-declare --name <slug> [--description ..] [--model ..] [--tools a,b] [--body ..]
                                               # 新建身份声明 declarations/<name>.md（同名拒绝）
                                               # 薄壳：校验与落盘在 primitives.declare_agent 原语
"""
import glob
import io
import json
import os
import subprocess
import sys
import time

# Windows 管道场景下 print() 默认走 locale 编码(cp936/GBK)，导致 UI/代理端按 UTF-8 解码乱码。
# 显式重配置 stdout/stderr 为 UTF-8，保证 JSON/中文跨进程一致。
if getattr(sys.stdout, "reconfigure", None):
    sys.stdout.reconfigure(encoding="utf-8")
if getattr(sys.stderr, "reconfigure", None):
    sys.stderr.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import paths as _paths  # noqa: E402
import loopx_bridge as _bridge  # noqa: E402

LOG_DIR = _paths.LOGS
PYTHON = _paths.PYTHON_EXE or sys.executable
WFENGINE = os.path.join(HERE, "wfengine.py")
DECL_DIR = os.path.normpath(os.path.join(HERE, "..", "agentgraph", "declarations"))
PRIMITIVES = os.path.normpath(os.path.join(HERE, "..", "scripts", "primitives.py"))
SPECS_DIR = os.path.normpath(os.path.join(HERE, "..", "agentgraph", "specs"))
AGENTGRAPH = os.path.normpath(os.path.join(HERE, "..", "agentgraph", "agentgraph.py"))
REGISTRY_PATHS = (
    ("local", _bridge.REGISTRY),
    ("global", os.path.join(_bridge.RUNTIME_ROOT, "registry.global.json")),
)


def _load_wf(path):
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _workflows():
    out = []
    for p in sorted(glob.glob(os.path.join(HERE, "*.yaml"))):
        name = os.path.splitext(os.path.basename(p))[0]
        if name == "wf-test-judge":  # 内部自检，不对外
            continue
        try:
            doc = _load_wf(p)
        except Exception as e:
            out.append({"name": name, "path": p, "error": str(e)})
            continue
        meta = doc.get("metadata", {})
        trg = doc.get("trigger", {})
        if meta.get("ui_hidden"):
            continue  # 机读任务（agent-forge/自检与冒烟）：只给 CLI，不上面板
        args = [k for k in (doc.get("variables") or {}).keys()]
        item = {
            "name": name,
            "description": meta.get("description", ""),
            "version": meta.get("version", ""),
            "command": trg.get("command", ""),
            "args": args,
            "required": [a for a in (trg.get("required") or []) if a in args],
            "arguments": trg.get("arguments") if "arguments" in trg else None,
            "path": p,
        }
        # 输入元数据漂移告警（arguments 必须被 variables 承接或被 =System.Args.* 消费）
        warg = trg.get("arguments")
        if warg is not None:
            text = json.dumps(doc, ensure_ascii=False)
            stray = [a.get("name") for a in warg if isinstance(a, dict)
                     and a.get("name") not in args
                     and f"System.Args.{a.get('name')}" not in text]
            if stray:
                item["metadata_warnings"] = [f"arguments 未被任何 variables/System.Args 消费: {stray}"]
        out.append(item)
    return out


def _iter_actions(actions):
    """递归遍历动作树（含 Loop.actions / ConditionGroup.conditions[].actions）。"""
    for a in actions or []:
        if not isinstance(a, dict):
            continue
        yield a
        yield from _iter_actions(a.get("actions"))
        for c in a.get("conditions") or []:
            if isinstance(c, dict):
                yield from _iter_actions(c.get("actions"))


def _collect_spec_refs(path):
    """扫描工作流动作树中的 InvokeAgent.spec 引用（→ spec 文件名，去重保序）。"""
    try:
        doc = _load_wf(path)
    except Exception:
        return []
    out = []
    for a in _iter_actions(doc.get("actions")):
        if a.get("kind") == "InvokeAgent":
            sp = a.get("spec")
            if sp:
                stem = os.path.splitext(os.path.basename(str(sp)))[0]
                if stem not in out:
                    out.append(stem)
    return out


def _specs():
    """agentgraph specs（过滤 *-smoke 自检）→ catalog 的 Agent 能力项。

    输入推导：显式 inputs 优先；缺省 = state 键 − 节点 outputs（未声明输入与中间态区分）。
    """
    out = []
    for p in sorted(glob.glob(os.path.join(SPECS_DIR, "*.yaml"))):
        stem = os.path.splitext(os.path.basename(p))[0]
        if stem.endswith("-smoke"):
            continue
        try:
            doc = _load_wf(p)
        except Exception as e:
            out.append({"name": stem, "path": p, "error": str(e)})
            continue
        meta = doc.get("metadata", {}) or {}
        state = doc.get("state") or {}
        nodes = [n for n in (doc.get("nodes") or []) if isinstance(n, dict)]
        produced = {n.get("output") for n in nodes if n.get("output")}
        decls = []
        for n in nodes:
            d = n.get("declaration")
            if d:
                base = os.path.basename(str(d))
                if base not in decls:
                    decls.append(base)
        explicit = doc.get("inputs")
        warnings = []
        if explicit:
            inputs = [i for i in explicit if isinstance(i, dict)]
            stray = [i.get("name") for i in inputs if i.get("name") not in state]
            if stray:
                warnings.append(f"inputs 不在 state 中: {stray}")
        else:
            inputs = [{"name": k, "type": "text"} for k in state if k not in produced]
        item = {
            "name": stem,
            "description": meta.get("description", ""),
            "model": doc.get("model", ""),
            "inputs": inputs,
            "outputs": doc.get("outputs") or [],
            "declarations": decls,
            "path": p,
        }
        if warnings:
            item["metadata_warnings"] = warnings
        out.append(item)
    return out


def cmd_catalog():
    """能力目录：workflows（含 arguments/调用关系）+ agents（specs 含 inputs/declarations/invoked_by）。"""
    wfs = _workflows()
    specs = _specs()
    refmap = {}
    for wf in wfs:
        if wf.get("error"):
            continue
        refs = _collect_spec_refs(wf["path"])
        wf["invokes"] = refs
        for s in refs:
            refmap.setdefault(s, []).append(wf["name"])
    for s in specs:
        s["invoked_by"] = refmap.get(s["name"], [])
    print(json.dumps({"workflows": wfs, "agents": specs}, ensure_ascii=False, indent=2))


def _tail(path, n=30):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        return lines[-n:]
    except FileNotFoundError:
        return []


def cmd_list():
    print(json.dumps(_workflows(), ensure_ascii=False, indent=2))


def cmd_trigger(name, kv):
    p = os.path.join(HERE, f"{name}.yaml")
    if not os.path.exists(p):
        print(f"error: workflow '{name}' not found", file=sys.stderr)
        return 2
    # 必填槽预校验（trigger.required：wfengine 的 fail-fast 是兜底，这里提前拦）
    try:
        required = _load_wf(p).get("trigger", {}).get("required") or []
    except Exception:
        required = []
    if required:
        kvd = dict(k.split("=", 1) for k in kv if "=" in k)
        missing = [r for r in required if not str(kvd.get(r, "")).strip()]
        if missing:
            print(f"error: 缺少必填参数 {missing}（用法：trigger {name} "
                  + " ".join(f'{r}=<值>' for r in required) + "）", file=sys.stderr)
            return 2
    cmd = [PYTHON, WFENGINE, p] + kv
    print(f"[wfctl] trigger {name} {' '.join(kv)}", file=sys.stderr)
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=1800)
        dur = time.time() - t0
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        print(f"[wfctl] done in {dur:.1f}s exit={r.returncode}", file=sys.stderr)
        return r.returncode
    except subprocess.TimeoutExpired:
        print("error: workflow timed out (30min)", file=sys.stderr)
        return 3


RUN_LOCK = os.path.join(os.environ.get("TEMP") or HERE, "aios-wfctl", "run-agent.lock")


def _acquire_run_lock(stale_s=1800):
    """run-agent single-flight 锁（跨进程 O_EXCL；陈锁按 mtime 超时抢回）→ 锁文件路径或 None。"""
    os.makedirs(os.path.dirname(RUN_LOCK), exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(RUN_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return RUN_LOCK
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(RUN_LOCK) > stale_s:
                    os.remove(RUN_LOCK)
                    continue
            except OSError:
                pass
            return None
    return None


def _release_run_lock():
    try:
        os.remove(RUN_LOCK)
    except OSError:
        pass


def cmd_run_agent(spec, kv):
    """直跑 agentgraph spec（spec 名或路径；必填输入预检 → run --json，stdout/退出码透传）。

    single-flight：同一时刻只允许一个 run-agent（防并发抢资源/日志交叉）。
    """
    p = spec if os.path.exists(spec) else os.path.join(SPECS_DIR, f"{spec}.yaml")
    if not os.path.exists(p):
        print(f"error: spec '{spec}' not found", file=sys.stderr)
        return 2
    try:
        inputs_meta = _load_wf(p).get("inputs") or []
    except Exception:
        inputs_meta = []
    kvd = dict(k.split("=", 1) for k in kv if "=" in k)
    missing = [i.get("name") for i in inputs_meta
               if isinstance(i, dict) and i.get("required")
               and not str(kvd.get(i.get("name"), "")).strip()]
    if missing:
        stem = os.path.splitext(os.path.basename(p))[0]
        print(f"error: 缺少必填输入 {missing}（用法：run-agent {stem} "
              + " ".join(f"{m}=<值>" for m in missing) + "）", file=sys.stderr)
        return 2
    if _acquire_run_lock() is None:
        print("error: 已有 run-agent 在运行（single-flight 保护）；请等待完成再试", file=sys.stderr)
        return 3
    try:
        argv = [PYTHON, AGENTGRAPH, "run", p, "--json"]
        for k, v in kvd.items():
            argv += ["--input", f"{k}={v}"]
        print(f"[wfctl] run-agent {os.path.basename(p)} {' '.join(kv)}", file=sys.stderr)
        t0 = time.time()
        try:
            r = subprocess.run(argv, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=1800)
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            print(f"[wfctl] done in {time.time() - t0:.1f}s exit={r.returncode}", file=sys.stderr)
            return r.returncode
        except subprocess.TimeoutExpired:
            print("error: run-agent timed out (30min)", file=sys.stderr)
            return 3
    finally:
        _release_run_lock()


def _available_models():
    """config.json 模型清单（default + providers 展开成 provider/model）。"""
    p = os.path.normpath(os.path.join(HERE, "..", "config.json"))
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            ms = (json.load(f).get("models") or {})
        if ms.get("default"):
            out.append(ms["default"])
        for prov, cfg in (ms.get("providers") or {}).items():
            for m in (cfg.get("models") or []):
                out.append(f"{prov}/{m}")
    except Exception:
        pass
    return [m for m in dict.fromkeys(out) if m]


def cmd_agents_suggest(brief):
    """AI 填充：brief → 身份草案建议（agent-draft spec；只读不落盘，提交仍走 agents-declare 严格校验）。"""
    if not (brief or "").strip():
        print(json.dumps({"ok": False, "error": "需要 --brief（一句话描述想要的身份）"},
                         ensure_ascii=False, indent=2))
        return
    tools = []
    try:
        r = subprocess.run([PYTHON, PRIMITIVES, "agent_tools", "{}"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60)
        if r.returncode == 0:
            tools = json.loads(r.stdout)
    except Exception:
        pass
    argv = [PYTHON, AGENTGRAPH, "run", os.path.join(SPECS_DIR, "agent-draft.yaml"), "--json",
            "--input", f"brief={brief}",
            "--input", f"tools_catalog={', '.join(tools)}",
            "--input", f"models_catalog={', '.join(_available_models())}"]
    t0 = time.time()
    print(f"[wfctl] agents-suggest (brief {len(brief)} 字)", file=sys.stderr)
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
    except subprocess.TimeoutExpired:
        print(json.dumps({"ok": False, "error": "AI 填充超时（10min）"}, ensure_ascii=False, indent=2))
        return
    if r.returncode != 0:
        lines = (r.stderr or "").strip().splitlines()
        print(json.dumps({"ok": False, "error": lines[-1] if lines else f"agent-draft exit={r.returncode}"},
                         ensure_ascii=False, indent=2))
        return
    try:
        final = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(json.dumps({"ok": False, "error": "agent-draft 输出不是 JSON"}, ensure_ascii=False, indent=2))
        return
    sug = final.get("suggestion")
    if isinstance(sug, str):
        try:
            sug = json.loads(sug)
        except json.JSONDecodeError:
            pass
    if not isinstance(sug, dict) or not str(sug.get("name") or "").strip():
        print(json.dumps({"ok": False, "error": "草案结构不符（缺 name）", "raw": sug},
                         ensure_ascii=False, indent=2))
        return
    sug["tools"] = [t for t in (sug.get("tools") or []) if isinstance(t, str)]
    print(json.dumps({"ok": True, "suggestion": sug, "elapsed_s": round(time.time() - t0, 1)},
                     ensure_ascii=False, indent=2))


def cmd_status(name):
    logpath = os.path.join(LOG_DIR, f"{name}.log")
    lines = _tail(logpath)
    last = lines[-1] if lines else ""
    print(f"workflow: {name}")
    print(f"log: {logpath}")
    print(f"lines: {len(_tail(logpath, 100000))}")
    print(f"last: {last}")
    # 判定：最后一行是否含"完成"（成功信号），粗略
    if lines:
        state = "completed" if any(k in last for k in ("完成", "success", "done")) else "running/unknown"
    else:
        state = "no-log"
    print(f"state: {state}")


def cmd_render(name):
    logpath = os.path.join(LOG_DIR, f"{name}.log")
    lines = _tail(logpath, 100000)
    last = lines[-1] if lines else ""
    if lines:
        state = "completed" if any(k in last for k in ("完成", "success", "done")) else "running"
    else:
        state = "no-log"
    print(json.dumps({
        "name": name,
        "log": logpath,
        "total_lines": len(lines),
        "last_line": last,
        "state": state,
    }, ensure_ascii=False, indent=2))


def _decl_meta(path):
    """读声明 frontmatter（name/description/model）；解析失败返回空 dict（列表不因单文件失败）。"""
    import yaml
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                meta = yaml.safe_load(parts[1]) or {}
                if isinstance(meta, dict):
                    return meta
    except Exception:
        pass
    return {}


def _read_registry(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def cmd_agents():
    """身份声明（agentgraph/declarations/*.md）+ 各 goal 注册状态。"""
    decls = []
    for p in sorted(glob.glob(os.path.join(DECL_DIR, "*.md"))):
        meta = _decl_meta(p)
        stem = os.path.splitext(os.path.basename(p))[0]
        decls.append({
            "name": meta.get("name") or stem,
            "file": stem,
            "description": meta.get("description", ""),
            "model": meta.get("model", ""),
            "tools": meta.get("tools") or [],
            "path": p,
        })
    goals = {}
    for role, rp in REGISTRY_PATHS:
        data = _read_registry(rp)
        for g in (data.get("goals") or []):
            if not isinstance(g, dict) or not g.get("id"):
                continue
            item = goals.get(g["id"])
            if item is None:
                coord = g.get("coordination") or {}
                item = goals[g["id"]] = {
                    "id": g.get("id"),
                    "display_name": g.get("display_name", ""),
                    "activation_state": (g.get("activation") or {}).get("state", ""),
                    "registered_agents": coord.get("registered_agents") or [],
                    "agent_model": coord.get("agent_model", ""),
                    "sources": [],
                }
            item["sources"].append(role)
    glist = sorted(goals.values(), key=lambda x: x.get("id", ""))
    for d in decls:
        d["registered_in"] = [g["id"] for g in glist
                              if d["name"] in (g.get("registered_agents") or [])]
    out = {"declarations": decls, "goals": glist}
    # 可用工具清单（工具推荐/表单 datalist；取不到不阻塞）
    try:
        r = subprocess.run([PYTHON, PRIMITIVES, "agent_tools", "{}"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
        if r.returncode == 0:
            out["tools_available"] = json.loads(r.stdout)
    except Exception:
        pass
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_agents_register(agent_id, goal_id, execute):
    """注册身份到 goal（loopx register-agent 的薄封装；缺省预览，--execute 写入）。"""
    if not agent_id or not goal_id:
        print(json.dumps({"ok": False, "error": "需要 --agent-id 和 --goal-id"},
                         ensure_ascii=False, indent=2))
        return
    import loopx_bridge as bridge
    argv = ["register-agent", "--goal-id", goal_id]
    for aid in [a.strip() for a in agent_id.split(",") if a.strip()]:
        argv += ["--agent-id", aid]  # repeatable 形式（逗号串形态实测不可靠）
    if execute:
        argv.append("--execute")
    r = bridge.call(argv)
    out = {"ok": bool(r.get("ok")), "execute": execute, "goal_id": goal_id,
           "agent_id": agent_id, "payload": r.get("payload"), "stderr": r.get("stderr")}
    print(json.dumps(out, ensure_ascii=False, indent=2))


def _goal_registered_agents(goal_id):
    """读源 registry 中某 goal 的 registered_agents（权威名单）。"""
    data = _read_registry(REGISTRY_PATHS[0][1])
    for g in (data.get("goals") or []):
        if isinstance(g, dict) and g.get("id") == goal_id:
            return list((g.get("coordination") or {}).get("registered_agents") or [])
    return None  # goal 不存在


def cmd_agents_unregister(agent_id, goal_id, execute):
    """从 goal 名单移除身份（configure-goal 替换语义；缺省预览，--execute 写入）。"""
    if not agent_id or not goal_id:
        print(json.dumps({"ok": False, "error": "需要 --agent-id 和 --goal-id"},
                         ensure_ascii=False, indent=2))
        return
    remove = [a.strip() for a in agent_id.split(",") if a.strip()]
    current = _goal_registered_agents(goal_id)
    if current is None:
        print(json.dumps({"ok": False, "error": f"goal 不存在：{goal_id}"},
                         ensure_ascii=False, indent=2))
        return
    after = [a for a in current if a not in remove]
    not_in = [a for a in remove if a not in current]
    out = {"ok": True, "execute": execute, "goal_id": goal_id,
           "current": current, "remove": remove, "not_in_list": not_in,
           "after": after, "changed": after != current}
    if not out["changed"]:
        out["note"] = "目标身份不在名单中，无需变更"
    if execute and out["changed"]:
        import loopx_bridge as bridge
        argv = ["configure-goal", "--goal-id", goal_id]
        if after:
            for a in after:
                argv += ["--registered-agent", a]
        else:
            argv.append("--clear-registered-agents")
        argv.append("--execute")
        r = bridge.call(argv)
        out["ok"] = bool(r.get("ok"))
        out["payload"] = r.get("payload")
        out["stderr"] = r.get("stderr")
        out["readback"] = _goal_registered_agents(goal_id)
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_agents_declare(name, description, model, body, tools=None):
    """新建身份声明（薄壳 → primitives.declare_agent 原语；同名拒绝，唯一实现在原语层）。"""
    args = {"name": name or ""}
    if (description or "").strip():
        args["description"] = description.strip()
    if (model or "").strip():
        args["model"] = model.strip()
    if (tools or "").strip():
        args["tools"] = tools
    if (body or "").strip():
        args["body"] = body.strip()
    r = subprocess.run([PYTHON, PRIMITIVES, "declare_agent",
                        json.dumps(args, ensure_ascii=False)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    if r.returncode != 0:
        lines = (r.stderr or r.stdout).strip().splitlines()
        print(json.dumps({"ok": False, "error": lines[-1] if lines else "declare_agent 失败"},
                         ensure_ascii=False, indent=2))
        return
    path, status = json.loads(r.stdout)
    if status == "skipped":
        print(json.dumps({"ok": False, "error": f"已存在同名声明：{name}.md（可直接编辑该文件）"},
                         ensure_ascii=False, indent=2))
        return
    print(json.dumps({"ok": True, "name": name, "file": f"{name}.md", "path": path},
                     ensure_ascii=False, indent=2))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    c = sys.argv[1]
    if c == "list":
        cmd_list()
    elif c == "catalog":
        cmd_catalog()
    elif c == "run-agent" and len(sys.argv) >= 3:
        return cmd_run_agent(sys.argv[2], sys.argv[3:])
    elif c == "trigger" and len(sys.argv) >= 3:
        return cmd_trigger(sys.argv[2], sys.argv[3:])
    elif c == "status" and len(sys.argv) >= 3:
        cmd_status(sys.argv[2])
    elif c == "render" and len(sys.argv) >= 3:
        cmd_render(sys.argv[2])
    elif c == "agents":
        cmd_agents()
    elif c == "agents-register":
        kv, flags, i = {}, set(), 2
        while i < len(sys.argv):
            a = sys.argv[i]
            if a == "--execute":
                flags.add("execute")
            elif a.startswith("--") and i + 1 < len(sys.argv):
                kv[a[2:].replace("-", "_")] = sys.argv[i + 1]
                i += 1
            i += 1
        cmd_agents_register(kv.get("agent_id"), kv.get("goal_id"), "execute" in flags)
    elif c == "agents-unregister":
        kv, flags, i = {}, set(), 2
        while i < len(sys.argv):
            a = sys.argv[i]
            if a == "--execute":
                flags.add("execute")
            elif a.startswith("--") and i + 1 < len(sys.argv):
                kv[a[2:].replace("-", "_")] = sys.argv[i + 1]
                i += 1
            i += 1
        cmd_agents_unregister(kv.get("agent_id"), kv.get("goal_id"), "execute" in flags)
    elif c == "agents-suggest":
        kv, i = {}, 2
        while i < len(sys.argv):
            a = sys.argv[i]
            if a.startswith("--") and i + 1 < len(sys.argv):
                kv[a[2:].replace("-", "_")] = sys.argv[i + 1]
                i += 1
            i += 1
        cmd_agents_suggest(kv.get("brief"))
    elif c == "agents-declare":
        kv, i = {}, 2
        while i < len(sys.argv):
            a = sys.argv[i]
            if a.startswith("--") and i + 1 < len(sys.argv):
                kv[a[2:].replace("-", "_")] = sys.argv[i + 1]
                i += 1
            i += 1
        cmd_agents_declare(kv.get("name"), kv.get("description"), kv.get("model"),
                           kv.get("body"), kv.get("tools"))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
