#!/usr/bin/env python3
"""aios 体检（diagnostics）：一次跑完 环境/配置/引擎自检，输出 JSON。

用法:
  python diagnostics.py [--mode quick|ping]
    quick = 无 LLM（默认）：环境 + 配置 + 路径 + 能力目录 + 原语自检 + spec 校验 + 工具池 + 演示工作流
    ping  = 追加一次模型连通性检测（1 次极短调用，消耗少量 token）

输出（stdout 仅 JSON）:
  {"ok": bool, "mode": str, "items": [{id,group,name,status,ms,detail}], "summary": {...}, "elapsed_s": float}
  status: pass | fail | warn | skip
退出码: ok(body) → 0，有 fail → 1

约定: OSS 树用 scripts/paths.py 取路径；私有树无 paths.py → 回退默认常量。
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # l2-memory
SCRIPTS = os.path.join(ROOT, "scripts")
WORKFLOWS = os.path.join(ROOT, "workflows")
AGENTGRAPH = os.path.join(ROOT, "agentgraph")
SPECS = os.path.join(AGENTGRAPH, "specs")
CONFIG_PATH = os.path.join(ROOT, "config.json")
PY = sys.executable

try:  # OSS 树：路径参数化（scripts/paths.py）
    sys.path.insert(0, SCRIPTS)
    import paths as _p  # type: ignore
except Exception:
    _p = None

VAULT = getattr(_p, "VAULT", r"D:\ObsidianVault") if _p else r"D:\ObsidianVault"


def _run(args, timeout=120):
    t0 = time.time()
    try:
        p = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, cwd=ROOT,
        )
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip(), int((time.time() - t0) * 1000)
    except subprocess.TimeoutExpired:
        return -1, "", f"超时（>{timeout}s）", int((time.time() - t0) * 1000)


def _item(id_, group, name, status, ms=0, detail=""):
    return {"id": id_, "group": group, "name": name, "status": status, "ms": ms, "detail": detail}


def _last_line(text, n=200):
    lines = [l for l in (text or "").splitlines() if l.strip()]
    return lines[-1][:n] if lines else ""


def check_python():
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 10)
    return _item("python", "环境", "Python 版本", "pass" if ok else "fail", 0, f"{v.major}.{v.minor}.{v.micro}")


def check_deps():
    need = ["yaml", "requests", "pydantic", "langchain_core", "langgraph"]
    missing = [m for m in need if importlib.util.find_spec(m) is None]
    return _item("deps", "环境", "依赖导入", "pass" if not missing else "fail", 0,
                 "全部就绪" if not missing else "缺少: " + ", ".join(missing) + "（pip install -r requirements.txt）")


def check_config():
    if not os.path.isfile(CONFIG_PATH):
        return _item("config", "配置", "config.json", "fail", 0, "文件不存在（可从 config.example.json 复制）")
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:  # noqa: BLE001
        return _item("config", "配置", "config.json", "fail", 0, f"JSON 解析失败: {e}")
    models = cfg.get("models") or {}
    provs = models.get("providers") or {}
    default = models.get("default") or ""
    if not default or not provs:
        return _item("config", "配置", "config.json", "fail", 0, "缺少 models.default 或 providers")
    return _item("config", "配置", "config.json", "pass", 0, f"default={default} · {len(provs)} providers")


def check_paths():
    msgs, ok = [], True
    if os.path.isdir(VAULT):
        msgs.append(f"vault={VAULT}")
    else:
        ok = False
        msgs.append(f"vault 不存在: {VAULT}")
    for label, p in (("workflows", WORKFLOWS), ("specs", SPECS)):
        if not os.path.isdir(p):
            ok = False
            msgs.append(f"{label} 缺失: {p}")
    return _item("paths", "配置", "路径", "pass" if ok else "fail", 0, " · ".join(msgs))


def check_catalog():
    rc, out, err, ms = _run([PY, os.path.join(WORKFLOWS, "wfctl.py"), "catalog"], timeout=60)
    if rc != 0:
        return _item("catalog", "引擎", "能力目录（wfctl catalog）", "fail", ms, _last_line(err or out))
    try:
        data = json.loads(out)
    except Exception as e:  # noqa: BLE001
        return _item("catalog", "引擎", "能力目录（wfctl catalog）", "fail", ms, f"输出非 JSON: {e}")
    wf = len(data.get("workflows") or [])
    ag = len(data.get("agents") or [])
    warns = len(data.get("metadata_warnings") or [])
    return _item("catalog", "引擎", "能力目录（wfctl catalog）", "pass" if warns == 0 else "warn", ms,
                 f"workflows={wf} agents={ag} warnings={warns}")


def check_primitives():
    rc, out, err, ms = _run([PY, os.path.join(SCRIPTS, "primitives.py"), "--self-check"], timeout=120)
    return _item("primitives", "引擎", "原语自检", "pass" if rc == 0 else "fail", ms, _last_line(out or err))


def check_specs():
    try:
        files = sorted(f for f in os.listdir(SPECS) if f.endswith(".yaml"))
    except FileNotFoundError:
        return _item("specs", "引擎", "agent spec 校验", "fail", 0, f"目录缺失: {SPECS}")
    bad, total_ms, last = [], 0, ""
    for f in files:
        rc, out, err, ms = _run([PY, os.path.join(AGENTGRAPH, "agentgraph.py"), "check", os.path.join(SPECS, f)], timeout=90)
        total_ms += ms
        if rc != 0:
            bad.append(f)
            last = _last_line(err or out, 160)
    detail = f"{len(files) - len(bad)}/{len(files)} 通过"
    if bad:
        detail += f" · 失败: {', '.join(bad)}"
        if last:
            detail += f" · {last}"
    return _item("specs", "引擎", f"agent spec 校验（{len(files)}）", "pass" if not bad else "fail", total_ms, detail)


def check_tools():
    rc, out, err, ms = _run([PY, os.path.join(SCRIPTS, "primitives.py"), "agent_tools", "{}"], timeout=60)
    if rc != 0:
        return _item("tools", "引擎", "工具池加载", "fail", ms, _last_line(err or out))
    try:
        names = json.loads(out)
        n = len(names) if isinstance(names, list) else len(names or {})
    except Exception:  # noqa: BLE001
        n = -1
    return _item("tools", "引擎", "工具池加载", "pass" if n >= 0 else "fail", ms,
                 f"{n} 件（内置 + 注册表）")


def check_demo():
    demo = os.path.join(WORKFLOWS, "demo-hello.yaml")
    ok = os.path.isfile(demo)
    return _item("demo", "引擎", "演示工作流", "pass" if ok else "warn", 0,
                 "demo-hello.yaml 就绪（在工作流页可一键试跑）" if ok else "缺少 workflows/demo-hello.yaml")


def check_opencode_server():
    import socket
    port = 4399
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))
        up = True
    except Exception:  # noqa: BLE001
        up = False
    finally:
        s.close()
    return _item("opencode_server", "连通", f"opencode server（{port}）", "pass" if up else "warn", 0,
                 "运行中（kind=opencode 默认模型可用）" if up
                 else "未运行——kind=opencode 模型不可用（其余通道不受影响，按需自动拉起）")


def check_model_ping():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        ref = (((cfg.get("models") or {}).get("judge_default")) or "").strip() or None
        sys.path.insert(0, SCRIPTS)
        import modelz  # type: ignore
        t0 = time.time()
        resp = modelz.chat([{"role": "user", "content": "ping"}], ref=ref, max_tokens=16, timeout=60)
        ms = int((time.time() - t0) * 1000)
        return _item("model_ping", "连通", f"模型连通（{ref or 'default'}）", "pass", ms, str(resp)[:100])
    except Exception as e:  # noqa: BLE001
        return _item("model_ping", "连通", "模型连通", "fail", 0, str(e)[:200])


def main():
    ap = argparse.ArgumentParser(description="aios 体检")
    ap.add_argument("--mode", choices=["quick", "ping"], default="quick")
    args = ap.parse_args()

    t0 = time.time()
    items = [
        check_python(),
        check_deps(),
        check_config(),
        check_paths(),
        check_catalog(),
        check_primitives(),
        check_specs(),
        check_tools(),
        check_demo(),
        check_opencode_server(),
    ]
    if args.mode == "ping":
        items.append(check_model_ping())

    summary = {"pass": 0, "fail": 0, "warn": 0, "skip": 0}
    for it in items:
        summary[it["status"]] = summary.get(it["status"], 0) + 1

    print(json.dumps({
        "ok": summary["fail"] == 0,
        "mode": args.mode,
        "items": items,
        "summary": summary,
        "elapsed_s": round(time.time() - t0, 1),
    }, ensure_ascii=False))
    return 0 if summary["fail"] == 0 else 1


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
