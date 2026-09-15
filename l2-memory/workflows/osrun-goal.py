#!/usr/bin/env python3
"""osrun-goal: loopx custom-runner orchestration for the OpenScience adapter.

Bridges the loopx custom-runner contract (status -> todo -> quota should-run ->
execute -> validate -> todo complete -> quota spend-slot -> refresh) to the
OpenScience osrun adapter, so an OpenScience research task is visible in the
LoopX control plane (todos, quota, evidence).

Usage:
    python osrun-goal.py run "<goal>" [--dry-run] [--timeout S]
    python osrun-goal.py check
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import paths as _paths  # noqa: E402

LOOPX = _paths.LOOPX_EXE or "loopx"
RUNTIME_ROOT = os.path.join(_paths.ROOT, ".loopx-runtime")
REGISTRY = os.path.join(_paths.ROOT, ".loopx", "registry.json")
OSRUN = os.path.join(_paths.L2_DIR, "workflows", "osrun.py")
GOAL = "ai-os-goal"
AGENT = "openscience"
PY = sys.executable

# Windows: force UTF-8 on piped stdio (defaults to GBK under PS redirection/pipe).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _loopx(args: list[str], timeout: int = 90) -> dict:
    cmd = [LOOPX, "--registry", REGISTRY, "--runtime-root", RUNTIME_ROOT, "--format", "json", *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except FileNotFoundError:
        return {"ok": False, "step": "loopx-not-found", "cmd": cmd}
    except subprocess.TimeoutExpired:
        return {"ok": False, "step": "timeout", "cmd": cmd}
    payload = {}
    if p.stdout.strip():
        try:
            payload = json.loads(p.stdout)
        except json.JSONDecodeError:
            payload = {"raw": p.stdout.strip()}
    return {"ok": not p.returncode, "rc": p.returncode, "payload": payload,
            "stderr": p.stderr.strip() if p.stderr.strip() else None,
            "cmd": cmd}


def _first_todo_id(payload: dict) -> str | None:
    for key in ("todo_id", "todoId", "id"):
        val = payload.get(key)
        if val:
            return str(val)
    return None


def run_goal(goal_text: str, *, dry: bool = False, skip_exec: bool = False, timeout: int = 3600) -> dict:
    result: dict[str, object] = {"goal": goal_text, "dry": dry, "steps": {}}
    base = ["--dry-run"] if dry else []

    # 1. todo add (advancement_task, claimed by openscience)
    add_args = ["todo", "add", "--goal-id", GOAL, "--role", "agent", "--text", goal_text,
                "--task-class", "advancement_task", "--claimed-by", AGENT, *base]
    r = _loopx(add_args)
    result["steps"]["todo_add"] = r
    todo_id = _first_todo_id(r["payload"]) if r["ok"] else None
    if not r["ok"]:
        result["error"] = "todo_add failed"
        return result

    # 2. quota should-run (gate before execution); multi-agent needs identity scope
    q = _loopx(["quota", "should-run", "--goal-id", GOAL, "--agent-id", AGENT])
    result["steps"]["quota_should_run"] = q

    # 3. execute via osrun (skip real model run in dry mode)
    if dry:
        run_result = {"ok": True, "dry_skipped": True, "goal": goal_text}
    elif skip_exec:
        run_result = {"ok": True, "skip_exec": True, "goal": goal_text,
                      "note": "lifecycle test without a real model run"}
    else:
        sub = subprocess.run([PY, OSRUN, "run", goal_text], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=timeout)
        try:
            run_result = json.loads(sub.stdout or "{}")
        except json.JSONDecodeError:
            run_result = {"raw": sub.stdout, "rc": sub.returncode}
        run_result["rc"] = sub.returncode
    result["steps"]["execute"] = run_result
    if not dry and (run_result.get("rc") or run_result.get("exit_code")):
        # non-delivery: void-slot instead of complete
        vs = _loopx(["quota", "void-slot", "--goal-id", GOAL, "--agent-id", AGENT])
        result["steps"]["quota_void_slot"] = vs
        result["error"] = "execution failed -> void-slot"
        return result

    # 4. todo complete (agent lifecycle actor + public-safe evidence)
    ev = run_result.get("elapsed_s") if not dry else "dry-run"
    comp = _loopx(["todo", "complete", "--goal-id", GOAL, "--todo-id", todo_id,
                   "--agent-id", AGENT, "--evidence", f"osrun elapsed_s={ev}", *base])
    result["steps"]["todo_complete"] = comp

    # 5. quota spend-slot (accounting)
    spend = _loopx(["quota", "spend-slot", "--goal-id", GOAL, "--agent-id", AGENT])
    result["steps"]["quota_spend_slot"] = spend
    return result


def main() -> int:
    ap = argparse.ArgumentParser(prog="osrun-goal", description="OpenScience custom-runner orchestration")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run", help="run one OpenScience task through the loopx custom-runner contract")
    pr.add_argument("goal", help="task goal text")
    pr.add_argument("--dry-run", action="store_true", help="preview chain without writing state or running a model")
    pr.add_argument("--skip-exec", action="store_true",
                    help="run real lifecycle commands (todo add/complete, quota) but skip the model execution")
    pr.add_argument("--timeout", type=int, default=3600)
    sub.add_parser("check", help="check loopx/open science paths")
    args = ap.parse_args()

    if args.cmd == "check":
        for name, path in (("LOOPX", LOOPX), ("OSRUN", OSRUN)):
            print(f"{name} exists={os.path.exists(path)}: {path}")
        q = _loopx(["status"])
        print("loopx status ok=", q["ok"], "| error=", q.get("stderr"))
        return 0
    if args.cmd == "run":
        res = run_goal(args.goal, dry=args.dry_run, skip_exec=args.skip_exec, timeout=args.timeout)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if not res.get("error") and res["steps"].get("todo_complete", {}).get("ok") else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
