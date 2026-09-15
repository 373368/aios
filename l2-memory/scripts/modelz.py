# -*- coding: utf-8 -*-
"""modelz — 模型选择原语（来源适配 + 选择）。

解决：model 硬编码散落（sys_classify_sdk.py / track-common.ps1 / auto-archive.ps1
各写一个 model 字符串，前缀还不一致）。统一改为：config.json -> models 段单源，
任何脚本/ps1 通过本原语解析 "provider/model" 引用或取 default。

来源适配（provider 可选配置 kind，缺省 "openai"）：
    openai   -> 直调 provider.base/chat/completions（Bearer api_key，OpenAI 兼容）
    opencode -> 经本地 opencode server（复用本机 opencode.jsonc 全部 provider/key）；
                provider 不写时用 serve 解析默认选择
    当前仅支持上述两种，kind 为可选启用字段。

接口契约：
    load_models()            -> dict（config.json 的 models 段）
    list_refs()              -> ["provider/model", ...]
    resolve(ref=None, sources=None) -> {provider, model, base, api_key, kind}（ref 缺省 = default）
    chat(messages, ref=None, sources=None, **kw) -> str（按 kind 分派：openai 直调 / opencode 经 serve）
    request_headers(ref=None, sources=None) -> dict（复用 resolve，供其它脚本取鉴权头）
    validate_yaml_sources(sources) -> None（工作流 YAML sources 段校验，禁明文 key）
    ensure_server()          -> port（确保本地 opencode server 常驻，未启动则拉起）

密钥处理（开源友好）：
    api_key 支持 "$ENV:VAR_NAME" 间接引用（调用时解析环境变量；未设置 → ValueError 不静默）。
    工作流 YAML 的 sources 段禁止明文 key（文件可共享/入库），由 validate_yaml_sources 强制；
    本机 config.json 已被 .gitignore 排除，可继续写明文。
    非本地 openai 源（非 127.0.0.1/localhost）缺 key → resolve 即报错；本地源免鉴权直连。

工作流自定义源（可选配置）：
    resolve/chat 接受 sources={provider: {...}}，逐字段合并进 config.json providers
    （同名 = 覆盖，未写字段 = 继承），实现"用默认源 或 工作流自带新源"。

幂等 / 可测试：纯解析无副作用；chat 需网络。自检：python modelz.py（仅离线解析断言）。
"""
import base64
import json
import os
import subprocess
import time
import urllib.request
import urllib.error

SERVER_PORT = int(os.environ.get("OPENCODE_SERVER_PORT", "4399"))
SERVER_USER = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
SERVER_PASS = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
OPENCODE_EXE = r"C:\Program Files\nodejs\node_global\node_modules\opencode-ai\bin\opencode.exe"

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")


def _load_config():
    """读 config.json（server 段为密码/端口单源）。"""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _apply_server_cfg():
    """server 参数单源：config.json server 段优先，回退环境变量。

    说明：opencode TUI 每次会话注入随机 OPENCODE_SERVER_PASSWORD，
    常驻 serve 用旧密码会失配 → 固定密码放 config.json 保证一致。
    """
    global SERVER_PORT, SERVER_USER, SERVER_PASS
    cfg = _load_config().get("server", {})
    if cfg.get("port"):
        SERVER_PORT = int(cfg["port"])
    if cfg.get("username"):
        SERVER_USER = cfg["username"]
    if cfg.get("password"):
        SERVER_PASS = cfg["password"]


_apply_server_cfg()


def load_models():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("models", {})
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        print(f"警告: config.json 解析失败: {e}")
        return {}


def list_refs():
    """返回全部可引用模型 "provider/model" 列表。"""
    models = load_models()
    out = []
    for prov, conf in models.get("providers", {}).items():
        for m in conf.get("models", []):
            out.append(f"{prov}/{m}")
    return out


def _resolve_key(provider, raw):
    """api_key 取值：支持 $ENV:VAR_NAME 间接引用（LiteLLM 风格）；缺失 → ValueError（不静默）。"""
    if isinstance(raw, str) and raw.startswith("$ENV:"):
        var = raw[len("$ENV:"):].strip()
        val = os.environ.get(var)
        if not val:
            raise ValueError(f"provider {provider} 的 api_key 引用了 $ENV:{var}，但环境变量未设置")
        return val
    return raw


def _is_local(base):
    """本地 base（如本机推理服务，免鉴权直连）。"""
    return bool(base) and base.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]"))


def _merged_providers(models, sources=None):
    """config providers ⊕ 工作流级 sources（同名逐字段覆盖，未写字段继承）。"""
    providers = dict(models.get("providers") or {})
    for name, prov in (sources or {}).items():
        merged = dict(providers.get(name) or {})
        merged.update(prov or {})
        providers[name] = merged
    return providers


def validate_yaml_sources(sources):
    """校验工作流 YAML 的 sources 段：api_key 只接受 $ENV:VAR 引用。

    工作流文件可共享/入库，禁明文 key（密钥放环境变量或本机 config.json）。
    """
    for name, prov in (sources or {}).items():
        key = (prov or {}).get("api_key")
        if key and not (isinstance(key, str) and key.startswith("$ENV:")):
            raise ValueError(
                f"工作流 sources.{name}.api_key 禁止明文（工作流文件可共享/入库），"
                f"请改用 $ENV:VAR_NAME 引用环境变量")


def resolve(ref=None, sources=None):
    """解析 "provider/model" 引用 → 连接信息。ref=None 用 default。

    出参：{provider, model, base, api_key, kind}。找不到 → ValueError（不静默）。
    kind 来自 provider 配置（缺省 "openai"）。
    sources：可选工作流级自定义 provider（合并进 config providers，同名逐字段覆盖）。
    api_key：支持 $ENV:VAR 引用；非本地 openai 源缺 key → ValueError。
    """
    models = load_models()
    ref = ref or models.get("default")
    if not ref:
        raise ValueError("config.json 未配置 models.default，且未显式传 ref")
    if "/" not in ref:
        raise ValueError(f"model 引用必须是 'provider/model' 格式，收到: {ref}")
    provider, model = ref.split("/", 1)
    providers = _merged_providers(models, sources)
    prov = providers.get(provider)
    if not prov:
        raise ValueError(f"未知 provider: {provider}（可选 {list(providers)}）")
    if model not in prov.get("models", []):
        raise ValueError(f"provider {provider} 无模型 {model}（可选 {prov.get('models')}）")
    kind = prov.get("kind", "openai")
    base = prov["base"].rstrip("/") if prov.get("base") else ""
    key = _resolve_key(provider, prov.get("api_key"))
    if kind == "openai" and not base:
        raise ValueError(f"provider {provider}（kind=openai）缺 base")
    if kind == "openai" and not key and not _is_local(base):
        raise ValueError(f"provider {provider} 缺 api_key（非本地源必须配置，或用 $ENV:VAR_NAME 引用环境变量）")
    return {"provider": provider, "model": model, "base": base, "api_key": key, "kind": kind}


def _chat_openai(info, messages, temperature, max_tokens, timeout):
    url = info["base"] + "/chat/completions"
    body = {"model": info["model"], "messages": messages}
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if info.get("api_key"):
        req.add_header("Authorization", "Bearer " + info["api_key"])
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.loads(r.read().decode("utf-8", "replace"))
            return resp["choices"][0]["message"]["content"]
        except Exception:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise


def _server_auth_header():
    if not SERVER_PASS:
        raise ValueError("未设置环境变量 OPENCODE_SERVER_PASSWORD，无法连 opencode server")
    token = base64.b64encode(f"{SERVER_USER}:{SERVER_PASS}".encode()).decode()
    return {"Authorization": "Basic " + token}


def _server_healthy(port):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/global/health")
        for k, v in _server_auth_header().items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode("utf-8", "replace")).get("healthy", False)
    except Exception:
        return False


def ensure_server(timeout=60):
    """确保本地 opencode server 常驻。未启动则拉起 opencode serve（后台、固定端口）。"""
    if _server_healthy(SERVER_PORT):
        return SERVER_PORT
    if not os.path.exists(OPENCODE_EXE):
        raise ValueError(f"找不到 opencode 可执行文件: {OPENCODE_EXE}")
    subprocess.Popen([OPENCODE_EXE, "serve", "--port", str(SERVER_PORT)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _server_healthy(SERVER_PORT):
            return SERVER_PORT
        time.sleep(0.5)
    raise TimeoutError(f"opencode server 在 {timeout}s 内未就绪（端口 {SERVER_PORT}）")


def _chat_opencode(messages, model_ref, timeout=300):
    """经本地 opencode server 调用 LLM。model_ref = "providerID/modelID"（如 siliconflow-cn/deepseek-ai/DeepSeek-V4-Flash）。"""
    port = ensure_server()
    if "/" not in model_ref:
        raise ValueError(f"opencode 来源模型引用必须 'providerID/modelID'，收到: {model_ref}")
    provider_id, model_id = model_ref.split("/", 1)
    base = f"http://127.0.0.1:{port}"
    auth = _server_auth_header()

    # 创建 session
    req = urllib.request.Request(base + "/session", data=b"{}", method="POST")
    for k, v in auth.items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        sid = json.loads(r.read().decode("utf-8", "replace"))["id"]

    # 异步发 prompt
    body = {"model": {"providerID": provider_id, "modelID": model_id},
            "parts": [{"type": "text", "text": m.get("content", "")} for m in messages]}
    req = urllib.request.Request(base + f"/session/{sid}/prompt_async",
                                 data=json.dumps(body).encode(), method="POST")
    for k, v in auth.items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        r.read()

    # 轮询拿回复
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(base + f"/session/{sid}/message?limit=50")
            for k, v in auth.items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=15) as r:
                msgs = json.loads(r.read().decode("utf-8", "replace"))
            for m in msgs:
                if m.get("info", {}).get("role") == "assistant":
                    parts = m.get("parts", [])
                    texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
                    if texts:
                        return "\n".join(t for t in texts if t)
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError(f"opencode server 在 {timeout}s 内未返回 LLM 回复（session {sid}）")


def chat(messages, ref=None, temperature=None, max_tokens=None, timeout=300, sources=None):
    """LLM 调用（按来源 kind 分派）。messages: [{"role":..., "content":...}]

    出参：assistant 文本。
      openai   -> 直调 base/chat/completions，重试 3 次
      opencode -> 经本地 opencode server（session + prompt_async + 轮询）
    sources：可选工作流级自定义 provider（透传 resolve）。
    """
    info = resolve(ref, sources=sources)
    if info["kind"] == "opencode":
        return _chat_opencode(messages, info["model"], timeout=timeout)
    return _chat_openai(info, messages, temperature, max_tokens, timeout)


def request_headers(ref=None, sources=None):
    """复用 resolve 返回鉴权头（供其它脚本直接发请求）。仅 openai 来源有意义。"""
    info = resolve(ref, sources=sources)
    if info["kind"] != "openai":
        raise ValueError(f"request_headers 仅支持 openai 来源，收到 kind={info['kind']}")
    headers = {"Content-Type": "application/json"}
    if info.get("api_key"):
        headers["Authorization"] = "Bearer " + info["api_key"]
    return headers


def _self_check():
    m = load_models()
    assert "default" in m, "config.json 缺 models.default"
    refs = list_refs()
    assert m["default"] in refs, f"default {m['default']} 不在 providers 列表 {refs}"
    info = resolve()
    assert info["provider"] and info["model"], "resolve() 缺字段"
    assert info["kind"] in ("openai", "opencode"), f"未知 kind: {info['kind']}"
    if info["kind"] == "openai":
        assert info["base"].startswith("http"), f"base 非法: {info['base']}"
    assert len(refs) >= 2, f"期望 ≥2 个 ref（openai+opencode），收到 {len(refs)}"
    try:
        resolve("nope/none")
        raise AssertionError("未知 provider 未抛错")
    except ValueError:
        pass
    # $ENV: 间接引用 + sources 合并（离线）
    os.environ["MODELZ_TEST_KEY"] = "test-secret-12345678"
    try:
        custom = {"envtest": {"name": "env 引用测试", "kind": "openai",
                              "base": "https://example.com/v1",
                              "api_key": "$ENV:MODELZ_TEST_KEY",
                              "models": ["t1"]}}
        info2 = resolve("envtest/t1", sources=custom)
        assert info2["api_key"] == "test-secret-12345678", "$ENV 未解析"
        # 同名覆盖：只覆盖 api_key，base/models 继承 config
        pname = m["judge_default"].split("/", 1)[0]
        ov = resolve(m["judge_default"], sources={pname: {"api_key": "$ENV:MODELZ_TEST_KEY",
                                                          "base": "https://example.com/v1"}})
        assert ov["api_key"] == "test-secret-12345678" and ov["base"], "同名 sources 覆盖/继承"
    finally:
        os.environ.pop("MODELZ_TEST_KEY", None)
    try:
        resolve("envtest/t1", sources={"envtest": {"base": "https://example.com/v1",
                                                   "api_key": "$ENV:MODELZ_TEST_MISSING",
                                                   "models": ["t1"]}})
        raise AssertionError("$ENV 缺环境变量未抛错")
    except ValueError:
        pass
    try:
        resolve("envtest/t1", sources={"envtest": {"base": "https://example.com/v1",
                                                   "models": ["t1"]}})
        raise AssertionError("非本地源缺 api_key 未抛错")
    except ValueError:
        pass
    validate_yaml_sources({"x": {"api_key": "$ENV:ANY"}})  # 合法：不抛
    try:
        validate_yaml_sources({"x": {"api_key": "sk-plaintext-12345678"}})
        raise AssertionError("YAML 明文 key 未拦截")
    except ValueError:
        pass
    print(f"OK: modelz 自检通过 | default={m['default']} | refs={len(refs)} 个 | 来源 kinds 存在"
          f" | $ENV/sources/明文拦截 已覆盖")


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    _self_check()