# -*- coding: utf-8 -*-
"""SDK 公共层：单实例锁 / 日志 / 退出码 / 子进程辅助。

所有 SDK 工作流共用。原则：锁与日志内建，确定性步骤经 subprocess 调原语，
LLM 判断点经 modelz.chat()（本地 opencode server）。
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))          # sdk/
L2 = os.path.dirname(ROOT)                                  # l2-memory/
SCRIPTS = os.path.join(L2, "scripts")
TASKS = os.path.join(L2, "tasks")
LOG_DIR = r"D:\ObsidianVault\03-日志"

PYTHON = r"C:\Users\asus\AppData\Local\Programs\Python\Python312\python.exe"
NODE = r"C:\Program Files\nodejs\node.exe"


def log(name, msg):
    """追加日志：03-日志/<name>.log，[时间戳] 前缀。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, f"{name}.log"), "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _pid_alive(pid):
    """进程存活探测。Windows 不能用 os.kill(pid, 0)——那是 TerminateProcess（会杀进程）。"""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class SingleLock:
    """跨进程单实例锁（Windows 命名 Mutex 不可跨语言直接用，改用文件锁）。"""

    def __init__(self, name):
        lock_dir = LOG_DIR
        try:
            os.makedirs(lock_dir, exist_ok=True)
        except OSError:
            lock_dir = tempfile.gettempdir()
        self.path = os.path.join(lock_dir, f".lock-{name}")
        self.fd = None

    def __enter__(self):
        try:
            self.fd = open(self.path, "x", encoding="utf-8")
            self.fd.write(str(os.getpid()))
            self.fd.flush()
        except FileExistsError:
            # 锁文件存在：持有者存活 → 拒绝（False）；死锁文件 → 清理重试
            try:
                pid = int(open(self.path, encoding="utf-8").read().strip())
            except (ValueError, OSError):
                pid = 0
            if pid and _pid_alive(pid):
                return False
            try:
                os.remove(self.path)
            except OSError:
                pass
            return self.__enter__()
        return True

    def __exit__(self, *a):
        if self.fd:
            self.fd.close()
            try:
                os.remove(self.path)
            except OSError:
                pass


def run(argv, timeout=600, **kw):
    """子进程执行，返回 (exit_code, stdout_text)。"""
    p = subprocess.run(argv, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       timeout=timeout, **kw)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_py(script, *args, timeout=600):
    """python <script> <args...>，脚本在 scripts/ 或 tasks/。"""
    if not os.path.isabs(script):
        for base in (SCRIPTS, TASKS):
            cand = os.path.join(base, script)
            if not os.path.exists(cand) and not script.endswith(".py"):
                cand += ".py"
            if os.path.exists(cand):
                script = cand
                break
    return run([PYTHON, script, *args], timeout=timeout)


def run_node(script, *args, timeout=900):
    return run([NODE, script, *args], timeout=timeout)


def load_config():
    with open(os.path.join(L2, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def default_ref():
    """config.json models.default（modelz 同源）。"""
    cfg = load_config()
    ref = cfg.get("models", {}).get("default")
    if not ref:
        raise ValueError("config.json 缺 models.default")
    return ref


def judge_ref():
    """判断点专用模型：config.json models.judge_default，回退 default。

    判断点（InvokeLLM）需纯 LLM 直调（kind=openai），不经 opencode agent 会话。
    """
    cfg = load_config()
    ref = cfg.get("models", {}).get("judge_default") or cfg.get("models", {}).get("default")
    if not ref:
        raise ValueError("config.json 缺 models.default / models.judge_default")
    return ref


def main_entry(name, fn):
    """SDK CLI 统一入口：sys.argv[1:] 传给 fn，锁内执行，退出码规范。

    退出码：0=成功 / 1=fn 返回 False / 3=已有实例在运行（锁冲突，跳过）。
    """
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    lock = SingleLock(name)
    if lock.__enter__() is False:
        sys.stderr.write(f"[{name}] 已有实例在运行，本次跳过\n")
        return 3
    try:
        ok = fn(sys.argv[1:])
    finally:
        lock.__exit__(None, None, None)
    if ok is False:
        return 1
    return 0 if ok is None or ok is True else (1 if ok else 0)