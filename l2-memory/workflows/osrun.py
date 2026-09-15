#!/usr/bin/env python3
"""OpenScience custom-runner adapter for the AI-OS control plane.

Bridges the loopx custom-runner contract to OpenScience's headless CLI:
    wake -> quota should-run -> openscience run --format json -> validate
    -> todo complete -> refresh-state -> quota spend-slot

OpenScience CLI (2.0.x): `openscience run "<msg>" --format json [--port N]`
Headless server: `openscience serve --port N`; attach via `--attach`.

Usage:
    python osrun.py check            # health: openscience available + (optionally) server up
    python osrun.py list-models      # what models are available (needs keys configured)
    python osrun.py run "<goal>"     # one-shot research task via `openscience run --format json`
                                    #   [--port N]   attach/start local server on port
                                    #   [--model M]  provider/model override
                                    #   [--timeout S] process timeout (default 3600)
    python osrun.py serve-start --port N   # start headless server (detached)
    python osrun.py serve-stop --port N    # stop the server on a port
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_PORT = 4096

NODE = "node"
OPENSCIENCE_JS = r"C:\Program Files\nodejs\node_global\node_modules\@synsci\openscience\bin\openscience"

def _openscience_cmd() -> list[str]:
    # Prefer node + the package JS entry (reliable across shells/PATH).
    return [NODE, OPENSCIENCE_JS]


def _run_cmd(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", f"command not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"


def check() -> dict:
    code, out, err = _run_cmd([*_openscience_cmd(), "--version"])
    return {
        "ok": code == 0,
        "version": out.strip().splitlines()[-1] if out.strip() else None,
        "error": err.strip() if code != 0 else None,
    }


def list_models() -> dict:
    code, out, err = _run_cmd([*_openscience_cmd(), "model"])
    models = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return {"ok": code == 0, "models": models, "error": err.strip() if code else None}


def run_oneshot(goal: str, port: int | None = None, model: str | None = None, timeout: int = 3600) -> dict:
    args = [*_openscience_cmd(), "run", goal, "--format", "json"]
    if port:
        args += ["--port", str(port)]
    if model:
        args += ["-m", model]
    start = time.time()
    code, out, err = _run_cmd(args, timeout=timeout)
    elapsed = round(time.time() - start, 1)
    events = []
    if out.strip():
        for line in out.strip().splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"raw": line})
    return {
        "exit_code": code,
        "elapsed_s": elapsed,
        "event_count": len(events),
        "events": events,
        "stderr": err.strip() if err.strip() else None,
    }


def serve_start(port: int = DEFAULT_PORT) -> dict:
    logfile = Path(f"openscience-serve-{port}.log")
    with logfile.open("w", encoding="utf-8") as f:
        p = subprocess.Popen(
            [*_openscience_cmd(), "serve", "--port", str(port)],
            stdout=f,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    return {"ok": True, "pid": p.pid, "logfile": str(logfile.resolve()), "port": port}


def serve_stop(port: int = DEFAULT_PORT) -> dict:
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connected = s.connect_ex(("127.0.0.1", port)) == 0
    s.close()
    if not connected:
        return {"ok": False, "error": f"no server listening on {port}"}
    # best-effort: openscience serve has no stop verb; owner kills by pid
    return {"ok": False, "error": f"server on {port} running; kill by pid (no CLI stop verb)"}


def main() -> int:
    ap = argparse.ArgumentParser(prog="osrun", description="OpenScience custom-runner adapter")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="health check")
    sub.add_parser("list-models", help="list configured models")

    p_run = sub.add_parser("run", help="one-shot research task")
    p_run.add_argument("goal", help="research goal text")
    p_run.add_argument("--port", type=int, default=None)
    p_run.add_argument("--model", default=None)
    p_run.add_argument("--timeout", type=int, default=3600)

    p_ss = sub.add_parser("serve-start", help="start headless server")
    p_ss.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_stop = sub.add_parser("serve-stop", help="stop headless server")
    p_stop.add_argument("--port", type=int, default=DEFAULT_PORT)

    args = ap.parse_args()

    if args.cmd == "check":
        print(json.dumps(check(), ensure_ascii=False))
    elif args.cmd == "list-models":
        print(json.dumps(list_models(), ensure_ascii=False))
    elif args.cmd == "run":
        print(json.dumps(run_oneshot(args.goal, args.port, args.model, args.timeout), ensure_ascii=False))
    elif args.cmd == "serve-start":
        print(json.dumps(serve_start(args.port), ensure_ascii=False))
    elif args.cmd == "serve-stop":
        print(json.dumps(serve_stop(args.port), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

