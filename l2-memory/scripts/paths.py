# -*- coding: utf-8 -*-
"""paths — 统一路径解析（开源可移植·单源）。

解析优先级：环境变量 > config.json["paths"] > 默认值。
环境变量（config.json 同名键不带前缀）：
  AIOS_ROOT           仓库根
  AIOS_VAULT          vault 根（记忆/知识落盘位置；Obsidian 可选，纯 markdown 目录）
  AIOS_MEMORY         会话记忆目录（默认 <root>/l1-control/opencode/.opencode/memory）
  AIOS_LOGS           日志目录（默认 <vault>/03-日志）
  AIOS_PYTHON         python 解释器（默认 sys.executable）
  AIOS_NODE           node 可执行（默认 PATH 探测）
  AIOS_OPENCODE_EXE   opencode 可执行（默认 PATH 探测）
  AIOS_LOOPX_EXE      loopx 可执行（默认 PATH 探测；pip install loopx 后可用）
  AIOS_OPENSCIENCE_JS openscience 入口（默认 PATH 探测）
  AIOS_OPENCODE_CONFIG opencode.jsonc 路径（默认 ~/.config/opencode/opencode.jsonc）
  AIOS_INDEX / AIOS_EXPORT / AIOS_CHUNKS  数据目录（默认 <l2>/index|export|chunks）

自举：python paths.py --init   # 创建 vault 最小目录结构 + 记忆目录
查看：python paths.py --show   # 打印全部解析结果（JSON）

注：解析结果在 import 时固定；改环境变量/config 后需重启进程生效。
"""
import json
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))       # l2-memory/scripts
L2_DIR = os.path.dirname(_HERE)                          # l2-memory
_ROOT_DEFAULT = os.path.dirname(L2_DIR)                  # 仓库根
_CONFIG_PATH = os.path.join(L2_DIR, "config.json")


def _cfg_paths():
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f).get("paths") or {}
    except Exception:
        return {}


_CFG = _cfg_paths()


def _pick(env_key, cfg_key, default=None):
    v = os.environ.get(env_key)
    if v:
        return v
    v = _CFG.get(cfg_key)
    if v:
        return v
    return default


def _which(exe):
    try:
        return shutil.which(exe)
    except Exception:
        return None


ROOT = _pick("AIOS_ROOT", "root", _ROOT_DEFAULT)
VAULT = _pick("AIOS_VAULT", "vault", os.path.join(ROOT, "vault"))
MEMORY = _pick("AIOS_MEMORY", "memory",
               os.path.join(ROOT, "l1-control", "opencode", ".opencode", "memory"))
LOGS = _pick("AIOS_LOGS", "logs", os.path.join(VAULT, "03-日志"))
PYTHON_EXE = _pick("AIOS_PYTHON", "python", sys.executable)
NODE_EXE = _pick("AIOS_NODE", "node", _which("node"))
OPENCODE_EXE = _pick("AIOS_OPENCODE_EXE", "opencode_exe", _which("opencode"))
LOOPX_EXE = _pick("AIOS_LOOPX_EXE", "loopx_exe", _which("loopx"))
OPENSCIENCE_JS = _pick("AIOS_OPENSCIENCE_JS", "openscience_js", _which("openscience"))
OPENCODE_CONFIG = _pick("AIOS_OPENCODE_CONFIG", "opencode_config",
                        os.path.join(os.path.expanduser("~"), ".config", "opencode", "opencode.jsonc"))

# ── 派生路径（结构约定；随 VAULT / L2_DIR / ROOT 变化） ──────────────
KB_ROOT = os.path.join(VAULT, "05-知识", "知识库")
MEM_VAULT_ROOT = os.path.join(VAULT, "01-记忆")
SYS_DIR = os.path.join(VAULT, "06-系统")
BEHAVIOR_DIR = os.path.join(LOGS, "行为记录")
INDEX_DIR = _pick("AIOS_INDEX", "index", os.path.join(L2_DIR, "index"))
EXPORT_DIR = _pick("AIOS_EXPORT", "export", os.path.join(L2_DIR, "export"))
CHUNKS_DIR = _pick("AIOS_CHUNKS", "chunks", os.path.join(L2_DIR, "chunks"))
SKILLS_ROOT = os.path.join(ROOT, "skills", "custom")
AGENTS_PATH = os.path.join(ROOT, "l1-control", "opencode", "AGENTS.md")


def ensure_dirs():
    """自举：vault 最小结构 + 记忆目录（幂等）。"""
    for d in (VAULT, MEMORY, LOGS, KB_ROOT, MEM_VAULT_ROOT, SYS_DIR, BEHAVIOR_DIR):
        os.makedirs(d, exist_ok=True)
    return {"vault": VAULT, "memory": MEMORY}


def show():
    keys = ["ROOT", "VAULT", "MEMORY", "LOGS", "PYTHON_EXE", "NODE_EXE",
            "OPENCODE_EXE", "LOOPX_EXE", "OPENSCIENCE_JS", "KB_ROOT",
            "MEM_VAULT_ROOT", "SYS_DIR", "BEHAVIOR_DIR", "INDEX_DIR",
            "EXPORT_DIR", "CHUNKS_DIR", "SKILLS_ROOT", "AGENTS_PATH", "OPENCODE_CONFIG"]
    return {k: globals()[k] for k in keys}


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    if "--init" in sys.argv:
        ensure_dirs()
        print("OK: 目录已自举")
    print(json.dumps(show(), ensure_ascii=False, indent=2))
