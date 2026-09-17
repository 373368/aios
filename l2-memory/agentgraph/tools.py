# -*- coding: utf-8 -*-
"""工具池 v1 — agentgraph 工具注册表（薄适配，零 LLM）。

契约：工具返回文本，成功为内容、失败以 "ERROR:" 开头（模型可自行重试/换路）。
用途：spec 的 llm 节点声明 `tools: [name, ...]` 后由模型自行决定调用次数与顺序；
name 必须在 TOOLS 内（加载期校验）。内置工具见下方 @tool；扩展工具走
`tools_registry.yaml`（统一声明式接口，多 kind：http / script / plugin；mcp 桥接 V1.1）。
"""
import html
import importlib.util
import json
import os
import re
import sys
import urllib.parse
import urllib.request

import yaml
from langchain_core.tools import StructuredTool, tool

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from common import run_capture  # noqa: E402

PY = sys.executable
SEARCH_INDEX = os.path.join(ROOT, "scripts", "search_index.py")
FETCH_ARXIV = os.path.join(ROOT, "tasks", "fetch_arxiv.py")

MAX_OUT = 6000  # 单次工具返回上限（字符），保护上下文
REGISTRY_PATH = os.path.join(HERE, "tools_registry.yaml")


def _truncate(text):
    if len(text) <= MAX_OUT:
        return text
    return text[:MAX_OUT] + f"\n...[截断，共 {len(text)} 字]"


@tool
def vault_search(query: str, k: int = 5) -> str:
    """检索本地知识库（Obsidian vault / 记忆页）。输入查询词，返回最相关页面（路径 + 标题 + 得分）。"""
    code, out, err = run_capture([PY, SEARCH_INDEX, "--json", "--no-log", "--k", str(k), query])
    if code != 0:
        return f"ERROR: vault_search 失败 code={code}: {(err or out).strip()[:200]}"
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return f"ERROR: vault_search 输出非 JSON: {out[:200]}"
    rows = []
    for r in (data.get("results") or [])[:k]:
        score = float(r.get("score") or 0)
        row = f"- {r.get('path', '?')}（{r.get('title', '')}）score={score:.3f}"
        snippet = " ".join(str(r.get("snippet") or "").split())
        if snippet:
            row += f"\n  摘录: {snippet}"
        rows.append(row)
    return _truncate("\n".join(rows) or "（无结果）")


@tool
def arxiv_search(query: str) -> str:
    """检索 arXiv 论文（按提交时间倒序）。输入查询式（如 'cat:cs.AI' 或关键词），返回最新论文标题/日期/链接。"""
    code, out, err = run_capture([PY, FETCH_ARXIV, "--query", query])
    if code != 0:
        return f"ERROR: arxiv_search 失败 code={code}: {(err or out).strip()[:200]}"
    try:
        items = (json.loads(out).get("items") or [])[:5]
    except json.JSONDecodeError:
        return f"ERROR: arxiv_search 输出非 JSON: {out[:200]}"
    rows = [f"- {i.get('title', '')}（{(i.get('date') or '')[:10]}）{i.get('url', '')}"
            for i in items]
    return _truncate("\n".join(rows) or "（无结果）")


@tool
def web_fetch(url: str, max_chars: int = 4000) -> str:
    """抓取网页并抽取正文文本（截断）。输入完整 http(s) URL，返回页面纯文本。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "aios-agentgraph/0.1"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read(400_000)
            ctype = resp.headers.get("Content-Type", "") or ""
        text = raw.decode("utf-8", "replace")
    except Exception as e:
        return f"ERROR: web_fetch 失败: {e}"
    if "html" in ctype.lower() or "<html" in text[:500].lower():
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return _truncate(text[:max_chars])


# ── 扩展工具：tools_registry.yaml（统一声明式接口，多 kind） ──────────────
# 条目 schema：
#   name: <slug>            # 唯一名（进入 TOOLS 白名单）
#   kind: http|script|plugin
#   description: <一句>      # 给 LLM 的路由说明
#   config:                 # 按 kind：
#     http:   {url: "https://...?q={q}", method: GET, params: [q], headers_env: {Authorization: ENV_NAME}, extract: "data.items", rows: {from: "items", fields: [full_name, description, stargazers_count]}, max_chars: 4000}
#     script: {script: "tasks/xxx.py", args: ["--query", "{q}"], params: [q], max_chars: 6000}
#     plugin: {path: "plugins/xxx.py"}   # 模块暴露 TOOL / TOOLS / get_tools()
#   smoke: {args: {q: "test"}}           # 可选：注册时契约自检用样例参数（缺省=不跑 smoke）
# 契约：可调用、返回文本、失败以 "ERROR:" 开头；声明 tools 时必须 ⊆ TOOLS。


def _slug_ok(name):
    return bool(name) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", str(name))


def _walk(obj, path):
    """按点号路径取 JSON 子节点（缺路径返回原对象）。"""
    for part in (path or "").split("."):
        if not part:
            continue
        obj = obj.get(part, {}) if isinstance(obj, dict) else {}
    return obj


def _http_tool(entry):
    """http kind：声明式 HTTP 适配器（零代码，通用执行器）。"""
    cfg = entry.get("config") or {}
    name = entry["name"]
    url_tpl = str(cfg.get("url") or "")
    if not url_tpl or "{" not in url_tpl:
        raise ValueError("http config.url 需含 {参数} 占位")
    method = str(cfg.get("method") or "GET").upper()
    headers_env = cfg.get("headers_env") or {}
    extract = str(cfg.get("extract") or "")
    rows_cfg = cfg.get("rows") or {}
    max_chars = int(cfg.get("max_chars") or 4000)
    params = [str(p) for p in (cfg.get("params") or [])]

    def _call(**kw):
        url = url_tpl
        for k, v in kw.items():
            url = url.replace("{" + k + "}", urllib.parse.quote(str(v)))
        if "{" in url:
            return f"ERROR: {name} url 占位未全部替换：{url}"
        headers = {"User-Agent": "aios-agentgraph/0.1"}
        for h, env in headers_env.items():
            val = os.environ.get(str(env))
            if val:
                headers[str(h)] = val
        data = None
        if method != "GET":
            data = json.dumps(kw, ensure_ascii=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, headers=headers, data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read(400_000)
            text = raw.decode("utf-8", "replace")
        except Exception as e:
            return f"ERROR: {name} 请求失败: {e}"
        if extract or rows_cfg:
            try:
                data_obj = json.loads(text)
                node = _walk(data_obj, extract) if extract else data_obj
                if rows_cfg:
                    rows = _walk(data_obj, str(rows_cfg.get("from") or ""))
                    fields = [str(f) for f in (rows_cfg.get("fields") or [])]
                    lines = []
                    for r in (rows if isinstance(rows, list) else [])[:5]:
                        if isinstance(r, dict):
                            lines.append("- " + " | ".join(str(r.get(f, "")) for f in fields))
                        else:
                            lines.append("- " + str(r))
                    node = "\n".join(lines)
                text = node if isinstance(node, str) else json.dumps(node, ensure_ascii=False)
            except Exception:
                pass
        return _truncate(str(text).strip()[:max_chars])

    from pydantic import create_model
    args_schema = create_model(f"{name}_Args", **{p: (str, ...) for p in params}) if params else None
    return StructuredTool.from_function(func=_call, name=name,
                                        description=entry.get("description") or name,
                                        args_schema=args_schema)


def _script_tool(entry):
    """script kind：声明式本地脚本包装（零代码，命令模板）。"""
    cfg = entry.get("config") or {}
    name = entry["name"]
    script = str(cfg.get("script") or "")
    if not script:
        raise ValueError("script config.script 必需")
    if not os.path.isabs(script):
        script = os.path.normpath(os.path.join(ROOT, script))
    if not os.path.isfile(script):
        raise ValueError(f"脚本不存在: {script}")
    args_tpl = [str(a) for a in (cfg.get("args") or [])]
    max_chars = int(cfg.get("max_chars") or MAX_OUT)
    params = [str(p) for p in (cfg.get("params") or [])]

    def _call(**kw):
        argv = []
        for a in args_tpl:
            for k, v in kw.items():
                a = a.replace("{" + k + "}", str(v))
            argv.append(a)
        code, out, err = run_capture([PY, script] + argv)
        if code != 0:
            return f"ERROR: {name} 脚本失败 code={code}: {(err or out).strip()[:200]}"
        return _truncate(out.strip()[:max_chars])

    from pydantic import create_model
    args_schema = create_model(f"{name}_Args", **{p: (str, ...) for p in params}) if params else None
    return StructuredTool.from_function(func=_call, name=name,
                                        description=entry.get("description") or name,
                                        args_schema=args_schema)


def _plugin_tool(entry):
    """plugin kind：Python 插件引用（复杂工具；不生成代码，只登记既有实现）。"""
    cfg = entry.get("config") or {}
    name = entry["name"]
    path = str(cfg.get("path") or "")
    if not path:
        raise ValueError("plugin config.path 必需")
    if not os.path.isabs(path):
        path = os.path.normpath(os.path.join(HERE, path))
    if not os.path.isfile(path):
        raise ValueError(f"插件文件不存在: {path}")
    spec = importlib.util.spec_from_file_location(f"aios_plugin_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    single = getattr(mod, "TOOL", None)
    found = {}
    if single is not None:
        found[getattr(single, "name", "")] = single
    else:
        found = dict(getattr(mod, "TOOLS", {}) or {})
        if not found and callable(getattr(mod, "get_tools", None)):
            found = {t.name: t for t in mod.get_tools()}
    if name not in found:
        raise ValueError(f"插件未暴露名为 {name} 的工具（需 TOOL / TOOLS / get_tools()）")
    return found[name]


def build_tool(entry):
    """按 kind 构建工具对象（注册与加载共用）。"""
    name = (entry or {}).get("name")
    if not _slug_ok(name):
        raise ValueError(f"工具名非法: {name!r}（小写字母/数字/下划线/短横线）")
    kind = str((entry or {}).get("kind") or "").strip().lower()
    if kind == "http":
        return _http_tool(entry)
    if kind == "script":
        return _script_tool(entry)
    if kind == "plugin":
        return _plugin_tool(entry)
    if kind == "mcp":
        raise ValueError("kind=mcp 桥接为 V1.1（暂未实现）")
    raise ValueError(f"未知工具 kind: {kind!r}（支持 http/script/plugin）")


def load_registry(path=REGISTRY_PATH):
    """读注册表 → ([工具], [错误])；单条失败不中断（调用方决定告警）。"""
    if not os.path.isfile(path):
        return [], []
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    built, errors = [], []
    for entry in (doc.get("tools") or []):
        try:
            built.append(build_tool(entry))
        except Exception as e:
            errors.append({"name": (entry or {}).get("name"), "error": str(e)})
    return built, errors


TOOLS = {t.name: t for t in (vault_search, arxiv_search, web_fetch)}
_REGISTRY_ERRORS = []
try:
    _extra, _errs = load_registry()
    for _t in _extra:
        TOOLS[_t.name] = _t
    _REGISTRY_ERRORS = _errs
except Exception as _e:  # 注册表整体不可用不阻塞内置工具
    _REGISTRY_ERRORS = [{"name": None, "error": str(_e)}]
if _REGISTRY_ERRORS:
    print(f"[tools] 注册表条目加载失败 {len(_REGISTRY_ERRORS)} 条: {_REGISTRY_ERRORS}",
          file=sys.stderr)
