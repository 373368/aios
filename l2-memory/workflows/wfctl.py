# -*- coding: utf-8 -*-
"""wfctl — wfengine 工作流规范化桥接层（触发/监控/渲染 + 身份注册管理）。

把 l2-memory 已写好的工作流（wfengine YAML）与 agent 身份声明暴露成接口，
供控制核心/UI（AiosShell 的 /wfctl 路由）触发与监控。

用法：
  python wfctl.py list                         # 列出可用工作流
  python wfctl.py trigger <wf> <k=v...>        # 同步触发（跑 wfengine），退出码透传
  python wfctl.py status <wf>                  # 读日志尾部 + 判定状态（文本）
  python wfctl.py render <wf>                  # 输出结构化 JSON（给 UI/监控）
  python wfctl.py agents                       # 身份声明 + goal 注册状态（JSON）
  python wfctl.py agents-register --agent-id <a[,b...]> --goal-id <g> [--execute]
                                               # 注册身份到 goal（缺省预览；--execute 写入）
  python wfctl.py agents-unregister --agent-id <a[,b...]> --goal-id <g> [--execute]
                                               # 从 goal 名单移除身份（缺省预览；--execute 写入）
  python wfctl.py agents-declare --name <slug> [--description ..] [--model ..] [--body ..]
                                               # 新建身份声明 declarations/<name>.md（同名拒绝）
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
        args = [k for k in (doc.get("variables") or {}).keys()]
        out.append({
            "name": name,
            "description": meta.get("description", ""),
            "version": meta.get("version", ""),
            "command": trg.get("command", ""),
            "args": args,
            "path": p,
        })
    return out


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
    print(json.dumps({"declarations": decls, "goals": glist}, ensure_ascii=False, indent=2))


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


DECL_TEMPLATE = """# {title}

## 身份
（待补充：这个身份是谁、擅长什么）

## 运行规范
- （待补充：视角、风格、约束）

## 输出要求
（待补充：默认输出格式）
"""


def cmd_agents_declare(name, description, model, body):
    """新建身份声明（declarations/<name>.md）；同名已存在则拒绝（直接编辑文件即可修改）。"""
    import re
    if not name or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
        print(json.dumps({"ok": False, "error": "name 必填，且只能用小写字母/数字/短横线（作为文件名）"},
                         ensure_ascii=False, indent=2))
        return
    path = os.path.join(DECL_DIR, f"{name}.md")
    if os.path.exists(path):
        print(json.dumps({"ok": False, "error": f"已存在同名声明：{name}.md（可直接编辑该文件）"},
                         ensure_ascii=False, indent=2))
        return
    title = name.replace("-", " ").replace("_", " ").strip().title()
    body_text = (body or "").strip() or DECL_TEMPLATE.format(title=title).strip()
    if not body_text.startswith("#"):
        body_text = f"# {title}\n\n{body_text}"
    fm = [f"name: {name}"]
    if (description or "").strip():
        fm.append(f"description: {json.dumps(description.strip(), ensure_ascii=False)}")
    if (model or "").strip():
        fm.append(f"model: {json.dumps(model.strip(), ensure_ascii=False)}")
    os.makedirs(DECL_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("---\n" + "\n".join(fm) + "\n---\n\n" + body_text + "\n")
    print(json.dumps({"ok": True, "name": name, "file": f"{name}.md", "path": path},
                     ensure_ascii=False, indent=2))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    c = sys.argv[1]
    if c == "list":
        cmd_list()
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
    elif c == "agents-declare":
        kv, i = {}, 2
        while i < len(sys.argv):
            a = sys.argv[i]
            if a.startswith("--") and i + 1 < len(sys.argv):
                kv[a[2:].replace("-", "_")] = sys.argv[i + 1]
                i += 1
            i += 1
        cmd_agents_declare(kv.get("name"), kv.get("description"), kv.get("model"), kv.get("body"))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
