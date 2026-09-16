#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""goalrun — 声明式 agent（agentgraph spec + 身份声明）接入 loopx 协作的 custom-runner。

契约（与 osrun-goal 相同）：
  user_gate preflight → todo add → quota should-run → execute（agentgraph run）→ todo complete → quota spend-slot

身份两层：
  - loopx 侧：--agent-id（协作身份 / quota 记账对象）
  - agent 侧：--spec 内 llm 节点绑定的声明文档（人设 / 运行规范 / 专用提示词）

用法：
    python goalrun.py register --agent-id <身份> [--goal-id ai-os-goal] [--execute]   # 默认预览；--execute 写入
    python goalrun.py run "<task>" --spec ..\\agentgraph\\specs\\parallel-analysts.yaml \\
        --agent-id <身份> [--task-key topic] [--goal-id ai-os-goal] [--dry-run] [--skip-exec]
    python goalrun.py check

注 1：loopx 要求 agent 先注册到 goal（registered_agents）；未注册时 todo add 报 not registered。
注 2：preflight 会拒绝执行存在未解除 user_gate（阻塞本身份）的 goal——先由 owner 决策
      （loopx todo complete --todo-id <id> --decision-outcome approve|reject）再重试。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

import loopx_bridge as bridge

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
AGENTGRAPH = os.path.normpath(os.path.join(HERE, "..", "agentgraph", "agentgraph.py"))
DEFAULT_GOAL = "ai-os-goal"
DEFAULT_AGENT = "agentgraph"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _gate_blocks(todo, agent):
    """镜像 loopx todos._user_todo_visible_to_agent：global→全员；blocks_agent/bound_agent→等值；无作用域→全员。"""
    if todo.get("global_gate"):
        return True
    ba = todo.get("blocks_agent")
    if ba:
        return ba == agent
    bound = todo.get("bound_agent")
    if bound:
        return bound == agent
    return True


def check_user_gates(goal, agent):
    """预检：读取 goal todos，找出阻塞本身份的未解除 user_gate。"""
    r = bridge.call(["todo", "list", "--goal-id", goal])
    if not r["ok"]:
        return {"checked": False, "blocking": [],
                "error": (r.get("stderr") or r.get("step") or "todo list failed")}
    payload = r["payload"] if isinstance(r["payload"], dict) else {}
    blocking = []
    for t in payload.get("todos") or []:
        if not isinstance(t, dict):
            continue
        if t.get("role") != "user" or t.get("task_class") != "user_gate":
            continue
        if str(t.get("status") or "").lower() == "done":
            continue
        if _gate_blocks(t, agent):
            blocking.append({"todo_id": t.get("todo_id"), "text": t.get("text"),
                             "blocks_agent": t.get("blocks_agent"),
                             "global_gate": bool(t.get("global_gate"))})
    return {"checked": True, "blocking": blocking}


def run_task(task, *, spec, goal, agent, task_key, dry=False, skip_exec=False, timeout=3600):
    spec = os.path.abspath(spec)
    result = {"task": task, "spec": os.path.basename(spec), "goal_id": goal,
              "agent_id": agent, "dry": dry, "steps": {}}
    base = ["--dry-run"] if dry else []

    # 0. 预检：user_gate（存在阻塞本身份的未解除 gate → 拒绝执行；dry 仅记录）
    gate = check_user_gates(goal, agent)
    result["steps"]["user_gate_preflight"] = gate
    if not gate["checked"]:
        result["error"] = f"user_gate preflight 无法完成: {gate.get('error')}"
        return result
    if gate["blocking"] and not dry:
        ids = ", ".join(str(g.get("todo_id") or "?") for g in gate["blocking"])
        result["error"] = (f"存在未解除的 user_gate 阻塞本身份（{ids}）；先由 owner 决策: "
                           f"loopx todo complete --goal-id {goal} --todo-id <id> "
                           f"--decision-outcome approve|reject")
        return result

    # 0b. 预检：spec 编译（check，不调 LLM）——失败不污染 loopx 状态
    if not skip_exec:
        pre = subprocess.run([PY, AGENTGRAPH, "check", spec], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=120)
        if pre.returncode != 0:
            result["error"] = f"spec check 失败: {(pre.stderr or pre.stdout).strip()[:300]}"
            return result

    # 1. todo add（以本 agent 身份认领）
    r = bridge.call(["todo", "add", "--goal-id", goal, "--role", "agent", "--text", task,
                     "--task-class", "advancement_task", "--claimed-by", agent, *base])
    result["steps"]["todo_add"] = r
    if not r["ok"]:
        hint = ""
        err = r["payload"].get("error") if isinstance(r["payload"], dict) else ""
        if err and "not registered" in err:
            hint = f"；先注册身份: python goalrun.py register --agent-id {agent} --execute"
        result["error"] = f"todo_add failed{hint}"
        return result
    todo_id = bridge.first_todo_id(r["payload"])

    # 2. quota should-run（执行前置门）
    result["steps"]["quota_should_run"] = bridge.call(
        ["quota", "should-run", "--goal-id", goal, "--agent-id", agent])

    # 3. execute：agentgraph run <spec> --json --input <task-key>=<task>
    if dry:
        run_result = {"ok": True, "dry_skipped": True}
    elif skip_exec:
        run_result = {"ok": True, "skip_exec": True, "note": "lifecycle test without agent run"}
    else:
        t0 = time.time()
        argv = [PY, AGENTGRAPH, "run", spec, "--json", "--input", f"{task_key}={task}"]
        sub = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout)
        run_result = {"rc": sub.returncode, "elapsed_s": round(time.time() - t0, 1)}
        try:
            run_result["result"] = json.loads(sub.stdout or "{}")
        except json.JSONDecodeError:
            run_result["result"] = {"raw": (sub.stdout or "")[:300]}
        if sub.returncode != 0:
            run_result["stderr"] = (sub.stderr or "")[-300:]
    result["steps"]["execute"] = run_result
    if not dry and run_result.get("rc"):
        result["steps"]["quota_void_slot"] = bridge.call(
            ["quota", "void-slot", "--goal-id", goal, "--agent-id", agent])
        result["error"] = "execution failed -> void-slot"
        return result

    # 4. todo complete（证据=可公开审计的执行摘要）
    evidence = f"agentgraph {os.path.basename(spec)} elapsed_s={run_result.get('elapsed_s', 'dry-run')}"
    result["steps"]["todo_complete"] = bridge.call(
        ["todo", "complete", "--goal-id", goal, "--todo-id", todo_id, "--agent-id", agent,
         "--evidence", evidence, *base])

    # 5. quota spend-slot（记账）
    result["steps"]["quota_spend_slot"] = bridge.call(
        ["quota", "spend-slot", "--goal-id", goal, "--agent-id", agent])
    return result


def main():
    ap = argparse.ArgumentParser(prog="goalrun",
                                 description="声明式 agent → loopx custom-runner 接入")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run", help="以声明式 agent 身份跑一个 loopx 任务")
    pr.add_argument("task", help="任务文本（写入 todo，并作为 agent 输入）")
    pr.add_argument("--spec", required=True, help="agentgraph spec 路径（llm 节点绑定声明文档）")
    pr.add_argument("--goal-id", default=DEFAULT_GOAL)
    pr.add_argument("--agent-id", default=DEFAULT_AGENT, help="loopx 协作身份 / quota 记账对象")
    pr.add_argument("--task-key", default="task", help="spec state 中接收任务文本的字段名")
    pr.add_argument("--dry-run", action="store_true", help="预览链路：不写 loopx 状态、不跑 agent")
    pr.add_argument("--skip-exec", action="store_true", help="真实生命周期但不跑 agent 模型")
    pr.add_argument("--timeout", type=int, default=3600)
    preg = sub.add_parser("register", help="注册 agent 身份到 goal（默认预览；--execute 写入）")
    preg.add_argument("--agent-id", required=True, help="要注册的身份 id（逗号分隔可多个）")
    preg.add_argument("--goal-id", default=DEFAULT_GOAL)
    preg.add_argument("--execute", action="store_true", help="真正写入 registry（缺省仅预览）")
    sub.add_parser("check", help="检查 loopx / agentgraph 路径与 loopx 状态")
    args = ap.parse_args()

    if args.cmd == "check":
        for name, path in (("LOOPX", bridge.LOOPX), ("AGENTGRAPH", AGENTGRAPH)):
            print(f"{name} exists={os.path.exists(path)}: {path}")
        q = bridge.call(["status"])
        print("loopx status ok=", q["ok"], "| error=", q.get("stderr"))
        return 0

    if args.cmd == "register":
        argv = ["register-agent", "--goal-id", args.goal_id]
        for aid in [a.strip() for a in args.agent_id.split(",") if a.strip()]:
            argv += ["--agent-id", aid]  # repeatable 形式（逗号串形态实测不可靠）
        if args.execute:
            argv.append("--execute")
        r = bridge.call(argv)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["ok"] else 1

    res = run_task(args.task, spec=args.spec, goal=args.goal_id, agent=args.agent_id,
                   task_key=args.task_key, dry=args.dry_run, skip_exec=args.skip_exec,
                   timeout=args.timeout)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    ok = (not res.get("error")) and res["steps"].get("todo_complete", {}).get("ok")
    return 0 if ok or res.get("dry") else 1


if __name__ == "__main__":
    raise SystemExit(main())
