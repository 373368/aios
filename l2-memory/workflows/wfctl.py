# -*- coding: utf-8 -*-
"""wfctl — wfengine 工作流规范化桥接层（触发/监控/渲染）。

AI-OS 多 agent 平台 Phase 2：把 l2-memory 已写好的单 agent 短任务工作流
（wfengine YAML）暴露成三个接口，供控制核心/UI 触发与监控。

用法：
  python wfctl.py list                         # 列出可用工作流
  python wfctl.py trigger <wf> <k=v...>        # 同步触发（跑 wfengine），退出码透传
  python wfctl.py status <wf>                  # 读日志尾部 + 判定状态（文本）
  python wfctl.py render <wf>                  # 输出结构化 JSON（给 UI/监控）
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
LOG_DIR = r"D:\ObsidianVault\03-日志"
PYTHON = r"C:\Users\asus\AppData\Local\Programs\Python\Python312\python.exe"
WFENGINE = os.path.join(HERE, "wfengine.py")


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
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
