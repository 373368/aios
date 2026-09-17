#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""loopx custom-runner 桥接公共层。

供 osrun-goal.py / goalrun.py 共用：loopx CLI 调用封装 + 路径常量。
解析优先级：环境变量（LOOPX_CLI / LOOPX_REGISTRY / LOOPX_RUNTIME_ROOT）
> paths.py（AIOS_LOOPX_EXE 等）> 默认值。
"""
from __future__ import annotations

import json
import locale
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import paths as _paths  # noqa: E402

LOOPX = os.environ.get("LOOPX_CLI") or _paths.LOOPX_EXE or "loopx"
RUNTIME_ROOT = os.environ.get("LOOPX_RUNTIME_ROOT") or os.path.join(_paths.ROOT, ".loopx-runtime")
REGISTRY = os.environ.get("LOOPX_REGISTRY") or os.path.join(_paths.ROOT, ".loopx", "registry.json")


def _decode(bs):
    """loopx stdout/stderr 解码：优先 utf-8，退 locale（Windows 中文为 cp936），最后 replace。"""
    if not bs:
        return ""
    for enc in ("utf-8", locale.getpreferredencoding(False)):
        try:
            return bs.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return bs.decode("utf-8", errors="replace")


def call(args, timeout=90):
    """调 loopx CLI（--format json）：返回 {ok, rc, payload, stderr, cmd}。"""
    cmd = [LOOPX, "--registry", REGISTRY, "--runtime-root", RUNTIME_ROOT,
           "--format", "json", *args]
    # loopx CLI 的 stdout 在无控制台子进程中默认走 locale（GBK）编码；payload 含非 GBK 字符（如 ↔）
    # 时 print 直接崩溃（UnicodeEncodeError）→ 子进程强制 UTF-8 模式（与 shell/serve 侧同一纪律）。
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
    except FileNotFoundError:
        return {"ok": False, "step": "loopx-not-found", "cmd": cmd}
    except subprocess.TimeoutExpired:
        return {"ok": False, "step": "timeout", "cmd": cmd}
    out, err = _decode(p.stdout), _decode(p.stderr)
    payload = {}
    if out.strip():
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            payload = {"raw": out.strip()}
    return {"ok": not p.returncode, "rc": p.returncode, "payload": payload,
            "stderr": err.strip() if err.strip() else None, "cmd": cmd}


def first_todo_id(payload):
    for key in ("todo_id", "todoId", "id"):
        val = payload.get(key)
        if val:
            return str(val)
    return None
