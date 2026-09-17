# -*- coding: utf-8 -*-
"""AI-OS 原语库（SDK 能力层）— 确定性原子函数。

按《12-原语与SDK扩展规范》§4：原子/幂等/可测试/复用本机配置/可拔插/失败可见。
本模块封装 archival/vault-digest 工作流中原本内嵌在 skill 文本里的写操作，
让 LLM 只做判断点，格式与落盘全部走确定性函数。

原语：
  write_kb_page      — 写知识页（05-知识/知识库/<骨架>/<子目录>/<主题>.md）
  write_memory_page  — 写 01-记忆 页（frontmatter type: memory）
  mark_digested      — memory 文件重命名 .digested.md（不删原文）
  append_behavior_log— 追加 03-日志/行为记录/YYYY-MM-DD.md
  append_digest_log  — 追加 03-日志/digest-YYYYMMDD.md（含 COMPLETED 标记）
  declare_agent      — 写身份声明（agentgraph/declarations/<name>.md，幂等）
  declare_agents     — 批量声明（清单 JSON 文件/文本/对象；汇总报告）
  register_tool      — 注册扩展工具（tools_registry.yaml；校验+smoke+幂等）
  save_tool_drafts   — 工具草案落盘（agentgraph/drafts/<name>.tool.json；同名跳过）
  adopt_tool_draft   — 采纳草案（register_tool + 改名 *.adopted.json）
  tool_inventory     — 本地工具源盘点（工具工厂·源搜索本地支）

全部幂等（重复执行不重复产生副作用），原子写（临时→替换防半截）。
用法（库）：
  from primitives import write_kb_page, mark_digested, ...
用法（CLI 自检）：python primitives.py
"""
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as _paths  # noqa: E402

VAULT = _paths.VAULT
KB_ROOT = _paths.KB_ROOT
MEM_ROOT = _paths.MEM_VAULT_ROOT
LOG_ROOT = _paths.LOGS
BEHAVIOR_DIR = _paths.BEHAVIOR_DIR

SKELETONS = ("AI与机器学习", "编程开发", "数学", "计算机基础", "物理",
             "医疗", "学习", "生活", "娱乐", "学术前沿")
SAFE = re.compile(r'[\\/:*?"<>|]')


def _now():
    return datetime.now()


def _safe_name(s):
    return SAFE.sub("_", str(s)).strip().strip(".")


# ── 安全原语：敏感词默认脱敏 ───────────────────────────────────────────

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")
_SECRET_CACHE = None


def _secrets():
    """收集需脱敏的字符串：config.json 内所有含 key/token/secret 的值 + 常见 key 前缀。"""
    global _SECRET_CACHE
    if _SECRET_CACHE is None:
        vals = []
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            def walk(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        if re.search(r"key|token|secret|api", k, re.I) and isinstance(v, str):
                            vals.append(v)
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
            walk(cfg)
        except Exception:
            pass
        _SECRET_CACHE = [v for v in vals if len(v) >= 8]
    return _SECRET_CACHE


_KEY_PAT = re.compile(r"\b(?:sk|ark|ghp|Bearer)\b[-\w]{8,}", re.I)


def redact_sensitive(text):
    """安全原语：默认替换 SDK 执行过程中的敏感词（api key / token / 密钥值）。

    替换 config.json 中记录的密钥值 + 常见 key 前缀形态（sk-*/ark-*/ghp-*/Bearer *）。
    幂等：已替换的内容不会被二次替换。入参 None → None。
    """
    if not text:
        return text
    out = str(text)
    for v in _secrets():
        out = out.replace(v, "[REDACTED]")
    out = _KEY_PAT.sub("[REDACTED]", out)
    return out


def _atomic_write(path, content):
    """原子写：先写临时→再替换（防半截文件，对齐 digest 中断恢复约定）。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


# ── 原语：write_kb_page ───────────────────────────────────────────────

def _kb_path(title, skeleton, subdir, kb_root=KB_ROOT):
    sk = skeleton if skeleton in SKELETONS else "其他"
    return os.path.join(kb_root, sk, subdir, _safe_name(title) + ".md")


def append_kb_page(title, skeleton, subdir, addition, kb_root=KB_ROOT):
    """四分支·extend：向已有知识页追加新内容（幂等：同内容已存在跳过）。

    入参：title/skeleton/subdir 定位已有页；addition 追加正文
    出参：(path, appended|created|skipped)；页不存在 → 创建（视为 new 兜底）
    """
    path = _kb_path(title, skeleton, subdir, kb_root)
    addition = redact_sensitive(addition).strip()
    if not addition:
        return path, "skipped"
    text = ""
    if os.path.isfile(path):
        text = open(path, encoding="utf-8").read()
    if addition in text:
        return path, "skipped"               # 幂等：内容已存在
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not text:
        _atomic_write(path, f"# {title}\n\n" + addition + "\n")
        return path, "created"
    _atomic_write(path, text.rstrip() + "\n\n" + addition + "\n")
    return path, "appended"


def merge_kb_pages(target_title, skeleton, subdir, source_paths,
                   kb_root=KB_ROOT):
    """四分支·merge：把多个来源页内容并入目标页（幂等）。

    入参：target_title 目标页；source_paths 来源页绝对路径列表
    出参：(path, merged|skipped|partial)；来源缺页记 partial，不失败
    """
    path = _kb_path(target_title, skeleton, subdir, kb_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = ""
    if os.path.isfile(path):
        text = open(path, encoding="utf-8").read()
    added, missing = 0, []
    for src in source_paths:
        if not os.path.isfile(src):
            missing.append(src)
            continue
        chunk = redact_sensitive(open(src, encoding="utf-8").read()).strip()
        if chunk and chunk not in text:
            text = (text.rstrip() + "\n\n" if text else "") + chunk + "\n"
            added += 1
    if not added:
        return path, "skipped"
    _atomic_write(path, text)
    return path, "merged" if not missing else "partial"


def supersede_page(title, skeleton, subdir, superseded_by, kb_root=KB_ROOT):
    """四分支·falsify：标记知识页已被证伪/取代（frontmatter 记录，正文不动）。

    入参：title 目标页；superseded_by 取代它的页面主题
    出参：(path, superseded|skipped|missing)
    """
    path = _kb_path(title, skeleton, subdir, kb_root)
    if not os.path.isfile(path):
        return path, "missing"
    text = open(path, encoding="utf-8").read()
    if "superseded_by" in text:
        return path, "skipped"               # 幂等：已标记
    stamp = f"superseded_by: {_safe_name(superseded_by)}\nsuperseded_at: {_now():%Y-%m-%d}"
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[:end] + stamp + "\n" + text[end:]
            _atomic_write(path, text)
            return path, "superseded"
    # 无 frontmatter：文件头插入
    _atomic_write(path, "---\n" + stamp + "\n---\n\n" + text.lstrip("\n"))
    return path, "superseded"


def write_kb_page(title, skeleton, subdir, frontmatter=None, body="",
                  kb_root=KB_ROOT, force=False):
    """写知识页。骨架不在白名单 → 放「其他」兜底；force=False 时已存在则跳过。

    入参：
      title       主题（将作为文件名，清洗非法字符）
      skeleton    骨架目录（9 骨架白名单）
      subdir      子目录（可空）
      frontmatter dict（source/conversation_id/exported_at/tags 等）
      body        正文（# 主题 之后的部分，调用方给核心知识/要点/来源）
    出参：(path, written|skipped|merged)
    """
    sk = skeleton if skeleton in SKELETONS else "其他"
    t = _safe_name(title)
    path = os.path.join(kb_root, sk, subdir, t + ".md")
    if not force and os.path.exists(path):
        return path, "skipped"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fm = "---\n" + "".join(f"{k}: {v}\n" for k, v in (frontmatter or {}).items()) + "---\n"
    b = redact_sensitive(body).lstrip()
    if b.startswith("# "):
        first, _, rest = b.partition("\n")
        if first[2:].strip() == str(title).strip():
            b = rest.lstrip("\n")
    content = fm + f"# {title}\n\n" + b.rstrip() + "\n"
    _atomic_write(path, content)
    return path, "written"


# ── 原语：write_memory_page ───────────────────────────────────────────

def write_memory_page(topic, content, mem_root=MEM_ROOT, force=False):
    """写 01-记忆 页（frontmatter type: memory + 双链标注位）。

    入参：topic（主题，每主题一页）/ content（会话过程记录正文）
    出参：(path, written|skipped)
    """
    t = _safe_name(topic)
    path = os.path.join(mem_root, t + ".md")
    if not force and os.path.exists(path):
        return path, "skipped"
    os.makedirs(mem_root, exist_ok=True)
    fm = f"---\ntype: memory\ntopic: {t}\ncreated: {_now():%Y-%m-%d}\n---\n"
    _atomic_write(path, fm + redact_sensitive(content).rstrip() + "\n")
    return path, "written"


# ── 原语：mark_digested ───────────────────────────────────────────────

def mark_digested(path):
    """memory 文件重命名 <name>.md → <name>.digested.md（内容不动，不删原文）。

    入参：文件绝对路径（TODO.md 永不被 digest——调用方负责不传）
    出参：新路径；已带 .digested 后缀或不存在 → 原样返回（幂等）
    """
    if not os.path.isfile(path):
        return path
    if path.endswith(".digested.md"):
        return path
    new = path[:-3] + ".digested.md"
    os.rename(path, new)
    return new


# ── 原语：append_behavior_log ─────────────────────────────────────────

def append_behavior_log(category, line, day=None, behavior_dir=BEHAVIOR_DIR):
    """追加行为记录 03-日志/行为记录/YYYY-MM-DD.md（按天）。

    入参：category（检索/归档/翻阅…）/ line（事件描述一行）
    幂等：同日同 category 同 line 已存在 → 跳过（不重复追加）
    """
    day = day or _now().strftime("%Y-%m-%d")
    path = os.path.join(behavior_dir, f"{day}.md")
    os.makedirs(behavior_dir, exist_ok=True)
    text = ""
    if os.path.isfile(path):
        text = open(path, encoding="utf-8").read()
    marker = f"## {category}\n"
    entry = f"{_now():%H:%M:%S} {redact_sensitive(line)}"
    if marker not in text:
        text = (text.rstrip() + "\n\n" if text else "") + marker + "- " + entry + "\n"
    elif f"- {entry}" in text:
        return path, "skipped"          # 幂等：已存在
    else:
        text = text.rstrip() + "\n- " + entry + "\n"
    _atomic_write(path, text)
    return path, "appended"


# ── 原语：append_digest_log ───────────────────────────────────────────

def append_digest_log(summary, completed=False, day=None, log_root=LOG_ROOT):
    """追加 digest 日志 03-日志/digest-YYYYMMDD.md。

    入参：summary（本次动作摘要）/ completed（写 COMPLETED 标记）
    出参：(path, appended)
    """
    day = day or _now().strftime("%Y%m%d")
    path = os.path.join(log_root, f"digest-{day}.md")
    os.makedirs(log_root, exist_ok=True)
    text = ""
    if os.path.isfile(path):
        text = open(path, encoding="utf-8").read()
    entry = f"- {_now():%H:%M:%S} {redact_sensitive(summary)}\n"
    if entry.rstrip("\n") in text:
        return path, "skipped"
    text = (text.rstrip() + "\n" if text else "") + entry
    if completed:
        text += f"COMPLETED {_now():%Y-%m-%d %H:%M:%S}\n"
    _atomic_write(path, text)
    return path, "appended"


# ── 原语：C1-C3 落盘（锚点 / permission / skill） ───────────────────────

SKILLS_ROOT = _paths.SKILLS_ROOT
AGENTS_PATH = _paths.AGENTS_PATH
OPENCODE_CONFIG = _paths.OPENCODE_CONFIG


def append_anchor(clause, agents_path=AGENTS_PATH):
    """C1 落盘：锚点条款追加到 AGENTS.md（幂等：同条款已存在跳过）。

    入参：clause（一条 C1 锚点条款，如 "第一原则：...")
    出参：(path, appended|skipped)
    """
    clause = clause.strip()
    if not clause:
        return agents_path, "skipped"
    text = ""
    if os.path.isfile(agents_path):
        text = open(agents_path, encoding="utf-8").read()
    if clause in text:
        return agents_path, "skipped"
    text = text.rstrip() + f"\n\n- {redact_sensitive(clause)}\n"
    _atomic_write(agents_path, text)
    return agents_path, "appended"


def write_skill(name, description, body, skills_root=SKILLS_ROOT):
    """C3 落盘：写 SKILL.md（skills_root/<name>/SKILL.md，frontmatter name/description）。

    入参：
      name        skill 名（目录名，清洗非法字符）
      description frontmatter description（opencode 用，一句）
      body        正文（What it does / How to use 等；调用方给完整 markdown）
    出参：(path, written|skipped)
    """
    n = _safe_name(name)
    path = os.path.join(skills_root, n, "SKILL.md")
    if os.path.exists(path):
        return path, "skipped"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = (f"---\nname: {n}\ndescription: {description}\n---\n\n"
               + redact_sensitive(body).rstrip() + "\n")
    _atomic_write(path, content)
    return path, "written"


def write_permission(rules, config_path=OPENCODE_CONFIG):
    """C2 落盘：合并更新 opencode.jsonc 的 permission 键（幂等）。

    入参：rules dict，如 {"bash": {"rm -rf *": "deny"}, "edit": "ask"}
      —— 逐条合并；键已存在且值相同 → 跳过；存在但值不同 → 更新（保留注释）。
    出参：(path, updated|skipped)；配置无 permission 键 → 在文件末尾插入。
    """
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"opencode 配置不存在: {config_path}")
    text = open(config_path, encoding="utf-8").read()
    # 已有 permission 块：在块内做 JSON 文本级合并（保留 jsonc 注释）
    perm_pat = re.compile(r'("permission"\s*:\s*)\{')
    if perm_pat.search(text):
        # 找块结束的大括号（不跨出该块；简单实现：从 "permission" 起数括号）
        start = perm_pat.search(text).end() - 1          # 指向 {
        depth, i = 1, start + 1
        while depth and i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        block = text[start:i]
        try:
            perm = json.loads(block)
        except json.JSONDecodeError:
            raise ValueError(f"{config_path} 的 permission 块非纯 JSON，需手工合并")
        before = json.dumps(perm, ensure_ascii=False, sort_keys=True)
        merged = False
        for k, v in rules.items():
            if perm.get(k) != v:
                perm[k] = v
                merged = True
        if not merged:
            return config_path, "skipped"
        after = json.dumps(perm, ensure_ascii=False, indent=2, sort_keys=True)
        text = text[:start] + after + text[i:]
    else:
        # 无 permission 块：在最后一个顶层块闭合 } 前插入（保守，不破坏 jsonc 注释）
        depth, top_close = 0, None
        for i, c in enumerate(text):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    top_close = i
        if top_close is None:
            raise ValueError(f"{config_path} 结构异常，无法插入 permission")
        rules_json = "\n".join(("  " + ln if ln else ln) for ln in json.dumps(rules, ensure_ascii=False, indent=2).split("\n"))
        chunk = ",\n  \"permission\": " + rules_json + "\n"
        text = text[:top_close] + chunk + text[top_close:]
    _atomic_write(config_path, text)
    return config_path, "updated"


# ── 原语：list_memory（扫描待沉淀记忆） ─────────────────────────────────

MEM_SCAN_ROOT = _paths.MEMORY


def list_memory(mem_root=MEM_SCAN_ROOT, include_digested=False):
    """扫描 memory 目录，列出待沉淀的记忆文件（未 digested）。

    入参：mem_root（记忆目录，缺省统一路径）/ include_digested（是否含已消化）
    出参：[{name, path, size, modified}]，按修改时间降序；跳过 TODO.md。
    """
    if not os.path.isdir(mem_root):
        return []
    out = []
    for name in os.listdir(mem_root):
        if not name.endswith(".md") or name == "TODO.md":
            continue
        if not include_digested and ".digested" in name:
            continue
        p = os.path.join(mem_root, name)
        if os.path.isfile(p):
            st = os.stat(p)
            out.append({"name": name, "path": p, "size": st.st_size,
                        "modified": st.st_mtime})
    out.sort(key=lambda x: x["modified"], reverse=True)
    return out


# ── 原语：declare_agent / declare_agents（身份工厂） ─────────────────────

AGENTGRAPH_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "agentgraph"))
DECL_ROOT = os.path.normpath(os.path.join(AGENTGRAPH_DIR, "declarations"))
AGENT_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")

DECL_TEMPLATE = """# {title}

## 身份
（待补充：这个身份是谁、擅长什么）

## 运行规范
- （待补充：视角、风格、约束）

## 输出要求
（待补充：默认输出格式）
"""

_TOOLS_CACHE = None
_TOOLS_MOD = None


def _tools_mod():
    """agentgraph tools 模块（延迟加载；TOOLS 白名单唯一权威来源）。"""
    global _TOOLS_MOD
    if _TOOLS_MOD is None:
        import importlib.util as _iu
        path = os.path.join(AGENTGRAPH_DIR, "tools.py")
        try:
            spec = _iu.spec_from_file_location("agentgraph_tools", path)
            mod = _iu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _TOOLS_MOD = mod
        except Exception as e:
            raise RuntimeError(f"工具白名单加载失败（{path}）: {e}")
    return _TOOLS_MOD


def agent_tools():
    """工具池白名单（TOOLS 注册表键列表；含声明式扩展工具；延迟加载）。

    白名单是声明校验的唯一权威来源；加载失败 → 明确报错（fail-closed）。
    """
    global _TOOLS_CACHE
    if _TOOLS_CACHE is None:
        _TOOLS_CACHE = sorted(_tools_mod().TOOLS)
    return _TOOLS_CACHE


def declare_agent(name, description="", model="", tools=None, body="",
                  force=False, decl_root=DECL_ROOT):
    """写身份声明 declarations/<name>.md（生成态 → 固化态：一文件一身份）。

    入参：
      name        身份名（^[a-z0-9][a-z0-9-]{0,63}$，作文件名）
      description 一句描述（frontmatter）
      model       模型引用（空 = 运行时默认）
      tools       工具白名单（list 或逗号串；须 ⊆ agentgraph TOOLS）
      body        正文（空 = 模板骨架）
      force       True 覆盖已存在文件（默认同名拒绝，幂等）
    出参：(path, written|skipped)；校验失败抛 ValueError（批量调用方逐项收集）。
    """
    name = (name or "").strip()
    if not AGENT_NAME.fullmatch(name):
        raise ValueError(f"name 非法：{name!r}（只允许小写字母/数字/短横线，≤64 字符）")
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",") if t.strip()]
    tools = list(tools or [])
    if tools:
        known = agent_tools()
        bad = [t for t in tools if t not in known]
        if bad:
            raise ValueError(f"工具不在白名单：{bad}；可用：{known}")
    path = os.path.join(decl_root, f"{name}.md")
    if os.path.exists(path) and not force:
        return path, "skipped"                      # 幂等：同名拒绝（编辑文件即可修改）
    title = name.replace("-", " ").replace("_", " ").title()
    body_text = (body or "").strip() or DECL_TEMPLATE.format(title=title).strip()
    if not body_text.startswith("#"):
        body_text = f"# {title}\n\n{body_text}"
    fm = [f"name: {name}"]
    if (description or "").strip():
        fm.append("description: " + json.dumps(description.strip(), ensure_ascii=False))
    if (model or "").strip():
        fm.append("model: " + json.dumps(model.strip(), ensure_ascii=False))
    if tools:
        fm.append("tools: [" + ", ".join(tools) + "]")
    os.makedirs(decl_root, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("---\n" + "\n".join(fm) + "\n---\n\n" + body_text + "\n")
    os.replace(tmp, path)
    return path, "written"


def declare_agents(plan, force=False, decl_root=DECL_ROOT, behavior_dir=None):
    """批量声明（身份工厂）：plan 为清单 JSON（文件路径 / JSON 文本 / 对象）。

    清单形态：{"agents": [{name, description, model, tools, body}, ...]} 或裸数组。
    逐项独立（幂等：同名 skipped；单项校验失败记 error，不中断整批）。
    有效写入时追加一条行为记录（03-日志/行为记录）。
    出参：{results: [{name, status, path, error?}], written, skipped, errors}
    """
    if isinstance(plan, str):
        s = plan.strip()
        if os.path.isfile(s):
            with open(s, encoding="utf-8") as f:
                plan = json.load(f)
        else:
            try:
                plan = json.loads(s)
            except json.JSONDecodeError as e:
                raise ValueError(f"plan 需为 JSON 文件路径或 JSON 文本：{e}")
    items = plan.get("agents") if isinstance(plan, dict) else plan
    if not isinstance(items, list) or not items:
        raise ValueError("plan 需含非空 agents 列表（或为数组）")
    results = []
    for item in items:
        if not isinstance(item, dict):
            results.append({"name": None, "status": "error", "error": "清单项非对象"})
            continue
        try:
            path, status = declare_agent(
                item.get("name"), item.get("description", ""), item.get("model", ""),
                item.get("tools"), item.get("body", ""),
                force=force or bool(item.get("force")), decl_root=decl_root)
            results.append({"name": item.get("name"), "status": status, "path": path})
        except ValueError as e:
            results.append({"name": item.get("name"), "status": "error", "error": str(e)})
    report = {
        "results": results,
        "written": sum(1 for r in results if r["status"] == "written"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "errors": sum(1 for r in results if r["status"] == "error"),
    }
    if report["written"] or report["errors"]:
        names = ", ".join(r["name"] or "?" for r in results)
        append_behavior_log("身份工厂",
                            f"声明 {len(results)} 个身份：written={report['written']} "
                            f"skipped={report['skipped']} errors={report['errors']} [{names}]",
                            behavior_dir=behavior_dir or BEHAVIOR_DIR)
    return report


# ── 原语：register_tool（工具工厂） ─────────────────────────────────────

TOOLS_REGISTRY = os.path.join(AGENTGRAPH_DIR, "tools_registry.yaml")
_TOOL_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")  # 与 agentgraph tools._slug_ok 一致


def register_tool(entry, force=False, skip_smoke=False, registry_path=TOOLS_REGISTRY):
    """注册扩展工具到 tools_registry.yaml（统一声明式接口，多 kind：http/script/plugin）。

    入参：
      entry  工具条目 dict：{name, kind, description, config{...}, smoke{args{...}}?}
             kind=http 需 config.url（含 {参数} 占位）；script 需 config.script；plugin 需 config.path
      force  同名覆盖（默认同名拒绝，幂等）
    流程：校验 →（有 smoke 时）契约自检（构建+样例调用，成功文本为准，ERROR: 即失败）
          → 追加落盘（LF，原子写）；工具名进 TOOLS 白名单（消费面自动生效，新进程加载）
    出参：(path, registered|skipped)；任何校验/smoke 失败抛 ValueError（不落盘）。
    """
    global _TOOLS_CACHE, _TOOLS_MOD
    import yaml
    if not isinstance(entry, dict):
        raise ValueError("entry 需为 dict")
    name = str(entry.get("name") or "").strip()
    if not _TOOL_NAME.fullmatch(name):
        raise ValueError(f"工具名非法：{name!r}（小写字母/数字/下划线/短横线，≤64）")
    kind = str(entry.get("kind") or "").strip().lower()
    if kind == "mcp":
        raise ValueError("kind=mcp 桥接为 V1.1（暂未实现）")
    if kind not in ("http", "script", "plugin"):
        raise ValueError(f"kind 需为 http/script/plugin（got {kind!r}）")
    cfg = entry.get("config") or {}
    need = {"http": "url", "script": "script", "plugin": "path"}[kind]
    if not str(cfg.get(need) or "").strip():
        raise ValueError(f"kind={kind} 需 config.{need}")
    with open(registry_path, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    tools = [t for t in (doc.get("tools") or []) if isinstance(t, dict)]
    if any(str(t.get("name")) == name for t in tools) and not force:
        return registry_path, "skipped"          # 幂等：同名拒绝
    # smoke 自检（条目声明了 smoke 即触发；构建走与加载同一路径）
    if "smoke" in entry and not skip_smoke:
        tool_obj = _tools_mod().build_tool(entry)
        smoke_args = (entry.get("smoke") or {}).get("args") or {}
        try:
            result = tool_obj.invoke(smoke_args)
        except Exception as e:
            raise ValueError(f"smoke 自检异常：{e}")
        if not isinstance(result, str) or result.startswith("ERROR:"):
            raise ValueError(f"smoke 自检失败（契约=成功返回内容文本）：{str(result)[:200]}")
    tools = [t for t in tools if str(t.get("name")) != name]
    tools.append(entry)
    doc["tools"] = tools
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    tmp = registry_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, registry_path)
    # 同进程刷新：注册后白名单立即生效（跨进程场景靠新加载，此为兜底）
    _TOOLS_CACHE = None
    _TOOLS_MOD = None
    return registry_path, "registered"


# ── 原语：tool_inventory（工具工厂·本地源盘点） ─────────────────────────

OP_SKILLS = _paths.SKILLS_ROOT


def tool_inventory(tasks_root=None, scripts_root=None, skills_root=OP_SKILLS):
    """盘点本地可包装为工具的现成来源（工具工厂·源搜索之本地支）。

    出参：{tools: [{name, description}], scripts: [相对路径], tasks: [文件名], skills: [名]}
    纯读操作；用于源搜索前避免重造（对齐"本地优先"）。
    """
    tasks_root = tasks_root or os.path.join(AGENTGRAPH_DIR, "..", "tasks")
    scripts_root = scripts_root or os.path.dirname(os.path.abspath(__file__))
    tools = []
    try:
        for t in _tools_mod().TOOLS.values():
            tools.append({"name": t.name, "description": (t.description or "")[:120]})
    except Exception:
        pass
    def _files(root, pat="_"):
        try:
            return sorted(f for f in os.listdir(root) if f.endswith(".py"))
        except Exception:
            return []
    skills = []
    try:
        skills = sorted(d for d in os.listdir(skills_root)
                        if os.path.isdir(os.path.join(skills_root, d)))
    except Exception:
        pass
    return {
        "tools": tools,
        "tasks": _files(tasks_root),
        "scripts": _files(scripts_root),
        "skills": skills,
    }


# ── 原语：工具草案（工具工厂·草案落盘 / 采纳闭环） ─────────────────────

DRAFTS_DIR = os.path.join(AGENTGRAPH_DIR, "drafts")


def save_tool_drafts(drafts, drafts_dir=DRAFTS_DIR):
    """工具草案落盘（工具工厂）：drafts = register_tool 条目列表（scout 产出）。

    每个草案写 <drafts_dir>/<name>.tool.json（{drafted_at, entry}，临时文件原子替换）；
    同名跳过（幂等，不覆盖已有草案）。
    出参：{saved: [路径], skipped: [名], errors: [{name, error}]}
    """
    if not isinstance(drafts, list) or not drafts:
        raise ValueError("drafts 需为非空列表（register_tool 条目）")
    os.makedirs(drafts_dir, exist_ok=True)
    saved, skipped, errors = [], [], []
    for entry in drafts:
        name = str((entry or {}).get("name") or "").strip() if isinstance(entry, dict) else ""
        if not _TOOL_NAME.fullmatch(name):
            errors.append({"name": name or None, "error": "草案缺合法 name（或非对象）"})
            continue
        path = os.path.join(drafts_dir, f"{name}.tool.json")
        if os.path.exists(path):
            skipped.append(name)
            continue
        payload = {"drafted_at": datetime.now().isoformat(timespec="seconds"), "entry": entry}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        saved.append(path)
    return {"saved": saved, "skipped": skipped, "errors": errors}


def adopt_tool_draft(path, force=False, registry_path=TOOLS_REGISTRY):
    """采纳工具草案（工具工厂）：读草案 → register_tool（校验+smoke）→ 草案改名 *.adopted.json。

    入参：path = 草案文件（<name>.tool.json，格式 {entry: {...}}）
    出参：{registry, status: registered|skipped, draft: 采纳后路径}；
    校验/smoke 失败抛 ValueError（草案保持原样，不落盘）。
    """
    if not os.path.isfile(path):
        raise ValueError(f"草案文件不存在：{path}")
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    entry = doc.get("entry") if isinstance(doc, dict) else None
    if not isinstance(entry, dict):
        raise ValueError(f"草案格式需为 {{entry: ...}}：{path}")
    registry_path, status = register_tool(entry, force=force, registry_path=registry_path)
    adopted = path
    if path.endswith(".tool.json"):
        adopted = path[: -len(".tool.json")] + ".adopted.json"
    if adopted != path:
        os.replace(path, adopted)
    return {"registry": registry_path, "status": status, "draft": adopted}


# ── CLI 自检（ponytail：非平凡逻辑留一个可运行检查） ───────────────────

def _self_check():
    import tempfile
    assert redact_sensitive("key=ark-fake0000111122223333deadbeef") != \
        "key=ark-fake0000111122223333deadbeef", "redact_sensitive"
    assert "REDACTED" in redact_sensitive("sk-abcdef1234567890"), "redact key 前缀"
    assert redact_sensitive(None) is None and redact_sensitive("普通文本") == "普通文本"
    tmp = tempfile.mkdtemp(prefix="primitives_self_")
    p, st = write_kb_page("测试主题", "学习", "", {"source": "test", "tags": "x"},
                          "## 核心知识\n内容", kb_root=tmp)
    assert st == "written" and os.path.isfile(p), f"write_kb_page: {p} {st}"
    assert write_kb_page("测试主题", "学习", "", {}, "x", kb_root=tmp)[1] == "skipped"
    m = os.path.join(tmp, "a.md")
    open(m, "w", encoding="utf-8").write("x")
    md = mark_digested(m)
    assert md.endswith(".digested.md") and not os.path.isfile(m), "mark_digested"
    bdir = os.path.join(tmp, "行为记录")
    b, st2 = append_behavior_log("归档", "平台:test 对话:1 提炼:2", day="2026-08-22",
                                 behavior_dir=bdir)
    assert st2 == "appended", append_behavior_log("归档", "平台:test 对话:1 提炼:2",
                                                  day="2026-08-22",
                                                  behavior_dir=bdir)[1]
    d, st3 = append_digest_log("沉淀1项", completed=True, day="20260822",
                               log_root=tmp)
    assert st3 == "appended" and "COMPLETED" in open(d, encoding="utf-8").read()
    # C1-C3 落盘原语
    sk, st4 = write_skill("test-skill", "测试 skill", "## Usage\nxxx", skills_root=tmp)
    assert st4 == "written" and os.path.isfile(sk), f"write_skill: {sk} {st4}"
    assert write_skill("test-skill", "d", "b", skills_root=tmp)[1] == "skipped"
    assert "name: test-skill" in open(sk, encoding="utf-8").read(), "write_skill frontmatter"
    ag = os.path.join(tmp, "AGENTS.md")
    open(ag, "w", encoding="utf-8").write("# 会话纪律\n")
    a1 = append_anchor("第一原则：不可协商", agents_path=ag)
    assert a1[1] == "appended" and "第一原则：不可协商" in open(ag, encoding="utf-8").read()
    assert append_anchor("第一原则：不可协商", agents_path=ag)[1] == "skipped", "锚点去重"
    cfg = os.path.join(tmp, "opencode.jsonc")
    open(cfg, "w", encoding="utf-8").write('{\n  "$schema": "https://opencode.ai/config.json",\n  "model": "x"\n}\n')
    p1 = write_permission({"bash": {"rm -rf *": "deny"}}, config_path=cfg)
    assert p1[1] == "updated" and '"permission"' in open(cfg, encoding="utf-8").read()
    p2 = write_permission({"bash": {"rm -rf *": "deny"}}, config_path=cfg)
    assert p2[1] == "skipped", "permission 幂等"
    # 四分支原语
    kp = os.path.join(tmp, "kb")
    w1 = write_kb_page("主题A", "学习", "", {"source": "t"}, "## 核心\n旧内容", kb_root=kp)
    assert w1[1] == "written"
    ap = append_kb_page("主题A", "学习", "", "新增要点", kb_root=kp)
    assert ap[1] == "appended" and "新增要点" in open(ap[0], encoding="utf-8").read()
    assert append_kb_page("主题A", "学习", "", "新增要点", kb_root=kp)[1] == "skipped", "extend 幂等"
    src2 = os.path.join(kp, "来源.md")
    open(src2, "w", encoding="utf-8").write("## 来源内容")
    mp = merge_kb_pages("主题B", "学习", "", [src2, os.path.join(kp, "不存在.md")], kb_root=kp)
    assert mp[1] == "partial" and "来源内容" in open(mp[0], encoding="utf-8").read(), f"merge: {mp}"
    sp = supersede_page("主题A", "学习", "", "主题B", kb_root=kp)
    assert sp[1] == "superseded" and "superseded_by" in open(sp[0], encoding="utf-8").read()
    assert supersede_page("主题A", "学习", "", "主题B", kb_root=kp)[1] == "skipped", "falsify 幂等"
    lm = list_memory(mem_root=tmp)
    assert isinstance(lm, list), "list_memory"
    # 身份工厂原语
    dr = os.path.join(tmp, "decl")
    dp, dst = declare_agent("tmp-checker", "测试身份", "m/x", ["vault_search"],
                            "", decl_root=dr)
    assert dst == "written" and os.path.isfile(dp), f"declare_agent: {dp} {dst}"
    text = open(dp, encoding="utf-8").read()
    assert "name: tmp-checker" in text and "tools: [vault_search]" in text, "declare 落盘"
    assert declare_agent("tmp-checker", decl_root=dr)[1] == "skipped", "declare 幂等"
    assert declare_agent("tmp-checker", force=True, decl_root=dr)[1] == "written", "declare force"
    try:
        declare_agent("Bad Name", decl_root=dr)
        raise AssertionError("非法 name 未拦截")
    except ValueError:
        pass
    try:
        declare_agent("tmp-checker2", tools=["nope"], decl_root=dr)
        raise AssertionError("越权工具未拦截")
    except ValueError:
        pass
    rp = declare_agents(
        {"agents": [{"name": "tmp-checker"}, {"name": "Bad Name"},
                    {"name": "tmp-checker", "force": True}]}, decl_root=dr,
        behavior_dir=os.path.join(tmp, "行为记录"))
    assert rp["skipped"] == 1 and rp["errors"] == 1 and rp["written"] == 1, f"declare_agents: {rp}"
    pl = os.path.join(tmp, "plan.json")
    open(pl, "w", encoding="utf-8").write('{"agents": [{"name": "tmp-plan-a"}]}')
    assert declare_agents(pl, decl_root=dr, behavior_dir=os.path.join(tmp, "行为记录"))["written"] == 1, "declare_agents 文件输入"
    # 工具工厂原语
    tr = os.path.join(tmp, "tools.yaml")
    open(tr, "w", encoding="utf-8").write("tools: []\n")
    ts = os.path.join(tmp, "echo_tool.py")
    open(ts, "w", encoding="utf-8").write("import sys\nprint('ECHO:' + sys.argv[1])\n")
    tp, tst = register_tool({"name": "tmp-echo", "kind": "script", "description": "测试脚本工具",
                             "config": {"script": ts, "args": ["{q}"], "params": ["q"]},
                             "smoke": {"args": {"q": "hi"}}}, registry_path=tr)
    assert tst == "registered" and os.path.isfile(tp), f"register_tool: {tp} {tst}"
    assert register_tool({"name": "tmp-echo", "kind": "script",
                          "config": {"script": ts}}, registry_path=tr)[1] == "skipped", "register_tool 幂等"
    tb = os.path.join(tmp, "bad_tool.py")
    open(tb, "w", encoding="utf-8").write("print('ERROR: nope')\n")
    try:
        register_tool({"name": "tmp-bad", "kind": "script",
                       "config": {"script": tb}, "smoke": {"args": {}}}, registry_path=tr)
        raise AssertionError("smoke 失败未拦截")
    except ValueError:
        pass
    try:
        register_tool({"name": "tmp-x", "kind": "mcp", "config": {}}, registry_path=tr)
        raise AssertionError("mcp 未拦截")
    except ValueError:
        pass
    import yaml as _yaml
    reg = _yaml.safe_load(open(tr, encoding="utf-8"))
    assert len(reg.get("tools") or []) == 1, "注册表落盘"
    inv = tool_inventory()
    assert isinstance(inv, dict) and inv.get("tools"), f"tool_inventory: {inv}"
    # 工具草案（落盘/采纳闭环）
    dd = os.path.join(tmp, "drafts")
    sd = save_tool_drafts([
        {"name": "tmp-draft-a", "kind": "script", "description": "d",
         "config": {"script": ts, "args": ["{q}"], "params": ["q"]},
         "smoke": {"args": {"q": "hi"}}},
        {"name": "Bad Name"},
        {"name": "tmp-draft-a", "kind": "script", "description": "dup"},
    ], drafts_dir=dd)
    assert len(sd["saved"]) == 1 and sd["skipped"] == ["tmp-draft-a"] and len(sd["errors"]) == 1, \
        f"save_tool_drafts: {sd}"
    ad = adopt_tool_draft(sd["saved"][0], registry_path=tr)
    assert ad["status"] == "registered" and ad["draft"].endswith(".adopted.json") \
        and os.path.isfile(ad["draft"]) and not os.path.isfile(sd["saved"][0]), f"adopt: {ad}"
    print("OK: primitives 自检通过（write_kb_page/write_memory/mark_digested/行为/digest 日志/锚点/skill/permission/四分支/list_memory/身份声明/工具注册/源盘点/工具草案）")


def _cli():
    """CLI 分发：python primitives.py <name> '<json-args>' → JSON 结果。
    供声明式引擎 wfengine InvokePrimitive 调用；无副作用原语，幂等可重跑。
    """
    if len(sys.argv) < 2:
        print("用法: python primitives.py <name> '<json-args>'")
        return 1
    name = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    fn = {
        "write_kb_page": write_kb_page,
        "append_kb_page": append_kb_page,
        "merge_kb_pages": merge_kb_pages,
        "supersede_page": supersede_page,
        "append_behavior_log": append_behavior_log,
        "append_digest_log": append_digest_log,
        "append_anchor": append_anchor,
        "write_skill": write_skill,
        "write_permission": write_permission,
        "list_memory": list_memory,
        "mark_digested": mark_digested,
        "write_memory_page": write_memory_page,
        "declare_agent": declare_agent,
        "declare_agents": declare_agents,
        "register_tool": register_tool,
        "save_tool_drafts": save_tool_drafts,
        "adopt_tool_draft": adopt_tool_draft,
        "tool_inventory": tool_inventory,
        "agent_tools": agent_tools,
    }.get(name)
    if fn is None:
        print(f"未知原语: {name}", file=sys.stderr)
        return 1
    try:
        result = fn(**args)
    except TypeError as e:
        print(f"原语 {name} 参数错误: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"原语 {name} 校验失败: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "--self-check":
        _self_check()
    else:
        sys.exit(_cli())