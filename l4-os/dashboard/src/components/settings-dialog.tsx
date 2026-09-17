import { useCallback, useEffect, useState } from "react";
import { RefreshCw, X } from "lucide-react";

interface StatusSummary {
  ok: boolean;
  goal_count: number;
  run_count: number;
  warnings: string[];
  goals: {
    id: string;
    display_name: string;
    lifecycle_phase: string;
    status: string;
    waiting_on?: string;
    quota: { state: string; spent_slots: number; allowed_slots: number };
    user_todos: string[];
    agent_todos: string[];
  }[];
}

/** 只读系统状态概况：经壳代理拉取 loopx serve-status /status.json */
function parseStatus(raw: unknown): StatusSummary {
  const r = (raw ?? {}) as Record<string, any>;
  const attention = Array.isArray(r.attention_queue?.items) ? r.attention_queue.items : [];
  const goals = attention.map((it: any) => {
    const proj = it.goal_channel_projection ?? {};
    const ut = proj.user_todos ?? it.user_todos?.first_open_items ?? [];
    const at = proj.agent_todos ?? it.agent_todos?.first_open_items ?? [];
    const q = proj.quota ?? it.project_asset?.quota ?? {};
    return {
      id: it.goal_id ?? "",
      display_name: proj.display_name ?? it.goal_id ?? "",
      lifecycle_phase: it.lifecycle_phase ?? "",
      status: proj.latest_status ?? it.status ?? "",
      waiting_on: proj.waiting_on ?? it.waiting_on,
      quota: {
        state: q.state ?? "",
        spent_slots: Number(q.spent_slots ?? 0),
        allowed_slots: Number(q.allowed_slots ?? 0),
      },
      user_todos: (ut as any[]).map((t) => t.title ?? t.text ?? "").filter(Boolean),
      agent_todos: (at as any[]).map((t) => t.title ?? t.text ?? "").filter(Boolean),
    };
  });
  const warnings = Array.isArray(r.contract_warnings) ? r.contract_warnings.map(String) : [];
  return { ok: !!r.ok, goal_count: Number(r.goal_count ?? 0), run_count: Number(r.run_count ?? 0), warnings, goals };
}

type Tab = "setup" | "status" | "config" | "check" | "about";

interface ServiceItem {
  id: string;
  name: string;
  port: number;
  url: string;
  up: boolean;
}
interface DiagItem {
  id: string;
  group: string;
  name: string;
  status: string;
  ms: number;
  detail: string;
}
interface DiagResult {
  ok: boolean;
  mode: string;
  items: DiagItem[];
  summary: { [k: string]: number };
  elapsed_s: number;
}

interface Preset {
  id: string;
  name: string;
  provider: string;
  kind: string;
  base: string;
  env: string;
  models: string[];
  default: string;
  judge_default: string;
}

interface SetupStatus {
  ok: boolean;
  python: { path: string; ok: boolean; version: string };
  deps: { ok: boolean; missing: string };
  config: { ok: boolean; default_model: string };
  loopx: { installed: boolean; initialized: boolean; version: string; registry: string };
}

const TAB_LABEL: Record<Tab, string> = {
  setup: "初始化",
  status: "状态",
  config: "配置",
  check: "体检",
  about: "关于",
};
const DIAG_LABEL: Record<string, string> = { pass: "通过", fail: "失败", warn: "警告", skip: "跳过" };

export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("status");

  // 状态
  const [status, setStatus] = useState<StatusSummary | null>(null);
  const [statusErr, setStatusErr] = useState("");
  const [services, setServices] = useState<ServiceItem[] | null>(null);
  const [servicesErr, setServicesErr] = useState("");

  // 配置
  const [cfgText, setCfgText] = useState("");
  const [cfgMsg, setCfgMsg] = useState("");
  const [cfgErr, setCfgErr] = useState("");
  const [cfgBusy, setCfgBusy] = useState(false);

  // 快速配置（预设模型源）
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetId, setPresetId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [setDefault, setSetDefault] = useState(true);
  const [qcBusy, setQcBusy] = useState(false);
  const [qcMsg, setQcMsg] = useState("");
  const [qcErr, setQcErr] = useState("");

  // 初始化向导
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [setupErr, setSetupErr] = useState("");
  const [saBusy, setSaBusy] = useState("");
  const [saMsg, setSaMsg] = useState("");
  const [saErr, setSaErr] = useState("");
  const [pyPath, setPyPath] = useState("");
  const [goalId, setGoalId] = useState("ai-os-goal");
  const [goalName, setGoalName] = useState("AI-OS 工作台");
  const [goalObjective, setGoalObjective] = useState("");

  // 体检
  const [diag, setDiag] = useState<DiagResult | null>(null);
  const [diagBusy, setDiagBusy] = useState(false);
  const [diagErr, setDiagErr] = useState("");

  const loadStatus = useCallback(async () => {
    setStatusErr("");
    try {
      const resp = await fetch("/status.json");
      if (!resp.ok) throw new Error(`status ${resp.status}`);
      setStatus(parseStatus(await resp.json()));
    } catch (e) {
      setStatusErr(String(e));
    }
  }, []);

  const loadServices = useCallback(async () => {
    setServicesErr("");
    try {
      const resp = await fetch("/wfctl/services");
      const data = await resp.json().catch(() => null);
      if (!resp.ok || !data?.services)
        throw new Error(data?.error || `services 响应结构不符（壳版本过旧？请重建 AiosShell）：HTTP ${resp.status}`);
      setServices(data.services as ServiceItem[]);
    } catch (e) {
      setServicesErr(String(e));
    }
  }, []);

  const loadPresets = useCallback(async () => {
    try {
      const resp = await fetch("/wfctl/config-presets");
      const data = await resp.json().catch(() => null);
      if (!resp.ok || !Array.isArray(data?.presets)) return;
      setPresets(data.presets as Preset[]);
      setPresetId((cur) => cur || (data.presets[0]?.id ?? ""));
    } catch {
      /* 预设缺失不阻塞 */
    }
  }, []);

  const loadConfig = useCallback(async () => {
    setCfgErr("");
    setCfgMsg("");
    try {
      const resp = await fetch("/wfctl/config-get");
      const data = await resp.json().catch(() => null);
      if (!resp.ok || !data?.ok)
        throw new Error(data?.error || `config 响应结构不符（壳版本过旧？请重建 AiosShell）：HTTP ${resp.status}`);
      setCfgText(data.text as string);
    } catch (e) {
      setCfgErr(String(e));
    }
  }, []);

  const saveConfig = useCallback(async () => {
    setCfgBusy(true);
    setCfgErr("");
    setCfgMsg("");
    try {
      const resp = await fetch("/wfctl/config-set", { method: "POST", body: cfgText });
      const data = await resp.json().catch(() => null);
      if (!resp.ok || !data?.ok) throw new Error(data?.error || `保存失败 ${resp.status}`);
      setCfgMsg(`已保存（${data.bytes} 字节）· 备份 ${data.backup}`);
    } catch (e) {
      setCfgErr(String(e));
    } finally {
      setCfgBusy(false);
    }
  }, [cfgText]);

  const loadSetup = useCallback(async () => {
    setSetupErr("");
    try {
      const resp = await fetch("/wfctl/setup-status");
      const data = await resp.json().catch(() => null);
      if (!data?.python)
        throw new Error(data?.error || `setup 响应结构不符（壳版本过旧？请重建 AiosShell）：HTTP ${resp.status}`);
      setSetup(data as SetupStatus);
      return data as SetupStatus;
    } catch (e) {
      setSetupErr(String(e));
      return null;
    }
  }, []);

  const applyPreset = useCallback(async () => {
    setQcBusy(true);
    setQcErr("");
    setQcMsg("");
    try {
      const resp = await fetch("/wfctl/config-apply", {
        method: "POST",
        body: JSON.stringify({ preset_id: presetId, api_key: apiKey, set_default: setDefault }),
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok || !data?.ok) throw new Error(data?.error || `应用失败 ${resp.status}`);
      setQcMsg(
        `已写入 provider「${data.provider}」${data.default_model ? ` · 默认模型 = ${data.default_model}` : ""} · API key → 环境变量 ${data.env}（自动完成，无需手写）`,
      );
      setApiKey("");
      loadConfig();
      loadSetup();
    } catch (e) {
      setQcErr(String(e));
    } finally {
      setQcBusy(false);
    }
  }, [presetId, apiKey, setDefault, loadConfig, loadSetup]);

  const setupAction = useCallback(
    async (path: string, body?: unknown) => {
      setSaBusy(path);
      setSaMsg("");
      setSaErr("");
      try {
        const resp = await fetch(`/wfctl/${path}`, {
          method: "POST",
          body: body === undefined ? undefined : JSON.stringify(body),
        });
        const data = await resp.json().catch(() => null);
        if (!resp.ok || data?.ok === false) throw new Error(data?.error || `请求失败 ${resp.status}`);
        const detail = data?.output ? `\n${data.output}` : data?.note ? ` · ${data.note}` : "";
        setSaMsg(`${path} 完成${detail}`);
        if (path !== "restart-shell") loadSetup();
      } catch (e) {
        setSaErr(`${path}: ${String(e)}`);
      } finally {
        setSaBusy("");
      }
    },
    [loadSetup],
  );

  const runDiag = useCallback(async (mode: "quick" | "ping") => {
    setDiagBusy(true);
    setDiagErr("");
    try {
      const resp = await fetch(`/wfctl/diagnostics?mode=${mode}`);
      const data = await resp.json().catch(() => null);
      if (!data?.items) throw new Error(data?.error || `体检失败 ${resp.status}`);
      setDiag(data as DiagResult);
    } catch (e) {
      setDiagErr(String(e));
    } finally {
      setDiagBusy(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
    loadServices();
    loadPresets();
    loadSetup().then((s) => {
      if (!s) return;
      setPyPath((p) => p || s.python.path || "");
      if (!s.ok) setTab("setup");
    });
  }, [loadStatus, loadServices, loadPresets, loadSetup]);

  useEffect(() => {
    if (tab === "config" && !cfgText) loadConfig();
  }, [tab, cfgText, loadConfig]);

  const badge = (ok: boolean, okText = "就绪", badText = "未完成") => (
    <span className={`aios-wf__badge ${ok ? "is-pass" : "is-fail"}`}>{ok ? okText : badText}</span>
  );

  const quickConfig = (
    <div className="aios-qc">
      <p className="aios-sys__sub">
        快速配置：选一个常见模型源 → 粘贴 API key → 应用。将自动写入 provider 与默认模型，并把 key 存入用户级环境变量（无需手写 JSON）。
      </p>
      <div className="aios-sys__bar">
        <select
          className="aios-qc__select"
          value={presetId}
          onChange={(e) => setPresetId(e.target.value)}
          aria-label="模型源预设"
        >
          {presets.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <input
          className="aios-setup__input"
          type="password"
          placeholder="API key（将写入环境变量）"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          aria-label="API key"
        />
        <label className="aios-qc__check">
          <input type="checkbox" checked={setDefault} onChange={(e) => setSetDefault(e.target.checked)} />
          设为默认模型
        </label>
        <button className="aios-topbar__btn" onClick={applyPreset} disabled={qcBusy || !presetId || !apiKey}>
          <span>{qcBusy ? "应用中…" : "应用"}</span>
        </button>
      </div>
      {qcMsg && <p className="aios-cfg__msg">{qcMsg}</p>}
      {qcErr && <p className="aios-wf__err">{qcErr}</p>}
    </div>
  );

  return (
    <div className="aios-modal" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="aios-modal__card is-wide" onClick={(e) => e.stopPropagation()}>
        <header className="aios-modal__bar">
          <span>设置</span>
          <button onClick={onClose} aria-label="关闭设置">
            <X size={16} />
          </button>
        </header>

        <div className="aios-settings__tabs" role="tablist">
          {(Object.keys(TAB_LABEL) as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              className={`aios-settings__tab ${tab === t ? "is-active" : ""}`}
              onClick={() => setTab(t)}
              type="button"
            >
              {TAB_LABEL[t]}
            </button>
          ))}
        </div>

        <div className="aios-modal__body">
          {tab === "setup" && (
            <>
              <p className="aios-sys__sub">
                初始化向导（按顺序四步；loopx 为必需组件，opencode / OpenScience 为可选）。完成后控制台全部功能可用。
              </p>
              <div className="aios-sys__bar">
                <button className="aios-topbar__btn" onClick={loadSetup} aria-label="刷新状态">
                  <RefreshCw size={14} />
                  <span>刷新状态</span>
                </button>
                {setup && badge(setup.ok, "全部就绪", "未完成")}
              </div>
              {setupErr && <p className="aios-wf__err">{setupErr}</p>}

              {setup && (
                <>
                  <div className="aios-setup__step">
                    <div className="aios-diag__head">
                      {badge(setup.python.ok)}
                      <strong>1 · Python 解释器</strong>
                    </div>
                    <p className="aios-diag__detail">
                      当前：{setup.python.path || "(未设置)"} · {setup.python.version || "无法运行"}
                    </p>
                    <div className="aios-sys__bar">
                      <input
                        className="aios-setup__input"
                        placeholder="python.exe 完整路径（如 D:\conda\python.exe）"
                        value={pyPath}
                        onChange={(e) => setPyPath(e.target.value)}
                        aria-label="python 路径"
                      />
                      <button
                        className="aios-topbar__btn"
                        onClick={() => setupAction("setup-set-python", { path: pyPath })}
                        disabled={saBusy !== "" || !pyPath}
                      >
                        <span>写入 AIOS_PYTHON</span>
                      </button>
                      <button
                        className="aios-topbar__btn"
                        onClick={() => setupAction("restart-shell")}
                        disabled={saBusy !== ""}
                      >
                        <span>重启壳</span>
                      </button>
                    </div>
                  </div>

                  <div className="aios-setup__step">
                    <div className="aios-diag__head">
                      {badge(setup.deps.ok)}
                      <strong>2 · Python 依赖</strong>
                    </div>
                    <p className="aios-diag__detail">
                      {setup.deps.ok ? "依赖齐备（yaml/requests/pydantic/langchain_core/langgraph）" : `缺少：${setup.deps.missing}`}
                    </p>
                    <div className="aios-sys__bar">
                      <button
                        className="aios-topbar__btn"
                        onClick={() => setupAction("setup-install-deps")}
                        disabled={saBusy !== ""}
                      >
                        <span>{saBusy === "setup-install-deps" ? "安装中…（可数分钟）" : "安装依赖（pip）"}</span>
                      </button>
                    </div>
                  </div>

                  <div className="aios-setup__step">
                    <div className="aios-diag__head">
                      {badge(setup.config.ok)}
                      <strong>3 · 模型配置</strong>
                    </div>
                    <p className="aios-diag__detail">
                      {setup.config.ok ? `默认模型：${setup.config.default_model}` : "未配置 models.default"}
                    </p>
                    {quickConfig}
                  </div>

                  <div className="aios-setup__step">
                    <div className="aios-diag__head">
                      {badge(setup.loopx.installed && setup.loopx.initialized)}
                      <strong>4 · loopx（治理运行时，必需）</strong>
                    </div>
                    <p className="aios-diag__detail">
                      {setup.loopx.installed ? setup.loopx.version : "未安装"} ·{" "}
                      {setup.loopx.initialized ? "registry 已建档" : "registry 未建档（实时状态 / Chat 写通道不可用）"}
                    </p>
                    <div className="aios-sys__bar">
                      <button
                        className="aios-topbar__btn"
                        onClick={() => setupAction("setup-install-loopx")}
                        disabled={saBusy !== ""}
                      >
                        <span>{saBusy === "setup-install-loopx" ? "安装中…" : "安装 loopx（pip）"}</span>
                      </button>
                    </div>
                    {!setup.loopx.initialized && (
                      <>
                        <p className="aios-diag__detail">创建首个目标（registry + state，之后可随时增删目标）：</p>
                        <div className="aios-sys__bar">
                          <input
                            className="aios-setup__input"
                            placeholder="目标 id（小写字母/数字/连字符，如 ai-os-goal）"
                            value={goalId}
                            onChange={(e) => setGoalId(e.target.value)}
                            aria-label="目标 id"
                          />
                          <input
                            className="aios-setup__input"
                            placeholder="显示名（如 AI-OS 工作台）"
                            value={goalName}
                            onChange={(e) => setGoalName(e.target.value)}
                            aria-label="目标显示名"
                          />
                        </div>
                        <div className="aios-sys__bar">
                          <input
                            className="aios-setup__input is-wide"
                            placeholder="目标描述（这个目标要达成什么）"
                            value={goalObjective}
                            onChange={(e) => setGoalObjective(e.target.value)}
                            aria-label="目标描述"
                          />
                          <button
                            className="aios-topbar__btn"
                            onClick={() =>
                              setupAction("setup-init-loopx", {
                                goal_id: goalId,
                                display_name: goalName,
                                objective: goalObjective,
                              })
                            }
                            disabled={saBusy !== "" || !goalId}
                          >
                            <span>{saBusy === "setup-init-loopx" ? "初始化中…" : "初始化 registry 与首个目标"}</span>
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                </>
              )}

              {saMsg && <pre className="aios-setup__out">{saMsg}</pre>}
              {saErr && <p className="aios-wf__err">{saErr}</p>}
            </>
          )}

          {tab === "status" && (
            <>
              <div className="aios-sys__bar">
                <span>{status ? (status.ok ? "服务正常" : "服务异常") : "加载中…"}</span>
                <button
                  className="aios-topbar__btn"
                  onClick={() => {
                    loadStatus();
                    loadServices();
                  }}
                  aria-label="刷新"
                >
                  <RefreshCw size={14} />
                  <span>刷新</span>
                </button>
              </div>
              {services && (
                <div className="aios-svc">
                  {services.map((s) => (
                    <div className="aios-svc__row" key={s.id}>
                      <span className="aios-svc__name">{s.name}</span>
                      <span className="aios-svc__meta">:{s.port}</span>
                      <span className={`aios-wf__badge ${s.up ? "is-pass" : "is-fail"}`}>
                        {s.up ? "运行中" : "未运行"}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {servicesErr && <p className="aios-wf__err">{servicesErr}</p>}
              {statusErr && <p className="aios-wf__err">{statusErr}</p>}
              {status && (
                <>
                  <p className="aios-sys__meta">
                    目标 {status.goal_count} · 运行 {status.run_count}
                  </p>
                  {status.goals.map((g) => (
                    <div className="aios-sys__goal" key={g.id}>
                      <div className="aios-sys__goalHead">
                        <strong>{g.display_name}</strong>
                        <span className="aios-wf__badge is-run">{g.status}</span>
                      </div>
                      <p className="aios-sys__sub">
                        生命周期 {g.lifecycle_phase}
                        {g.waiting_on ? ` · 等待 ${g.waiting_on}` : ""} · 配额
                        {g.quota.state}（已用 {g.quota.spent_slots}/{g.quota.allowed_slots}）
                      </p>
                      {g.user_todos.length > 0 && (
                        <ul className="aios-sys__todos">
                          {g.user_todos.map((t, i) => (
                            <li key={i}>【用户】{t}</li>
                          ))}
                        </ul>
                      )}
                      {g.agent_todos.length > 0 && (
                        <ul className="aios-sys__todos">
                          {g.agent_todos.map((t, i) => (
                            <li key={i}>【代理】{t}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                  {status.warnings.length > 0 && (
                    <div className="aios-sys__warn">
                      {status.warnings.map((w, i) => (
                        <p key={i}>{w}</p>
                      ))}
                    </div>
                  )}
                </>
              )}
            </>
          )}

          {tab === "config" && (
            <>
              {quickConfig}
              <p className="aios-sys__sub">
                或直接编辑 l2-memory/config.json：模型 / provider / 服务端口。保存前自动备份（config.json.bak-时间戳）；
                密钥建议用 $ENV:名称 引用环境变量，本页只监听 127.0.0.1。
              </p>
              <textarea
                className="aios-cfg__area"
                value={cfgText}
                onChange={(e) => setCfgText(e.target.value)}
                spellCheck={false}
                aria-label="config.json 内容"
              />
              <div className="aios-sys__bar">
                <button className="aios-topbar__btn" onClick={loadConfig} disabled={cfgBusy}>
                  <RefreshCw size={14} />
                  <span>重新加载</span>
                </button>
                <button className="aios-topbar__btn" onClick={saveConfig} disabled={cfgBusy}>
                  <span>{cfgBusy ? "保存中…" : "保存"}</span>
                </button>
              </div>
              {cfgMsg && <p className="aios-cfg__msg">{cfgMsg}</p>}
              {cfgErr && <p className="aios-wf__err">{cfgErr}</p>}
            </>
          )}

          {tab === "check" && (
            <>
              <div className="aios-sys__bar">
                <button className="aios-topbar__btn" onClick={() => runDiag("quick")} disabled={diagBusy}>
                  <span>{diagBusy ? "运行中…" : "运行快速体检"}</span>
                </button>
                <button className="aios-topbar__btn" onClick={() => runDiag("ping")} disabled={diagBusy}>
                  <span>含模型连通（+3s）</span>
                </button>
              </div>
              <p className="aios-sys__sub">
                体检条例：环境（Python/依赖/壳视角一致性）· 配置（config.json/路径）· 引擎（能力目录/原语自检/spec 校验/工具池/演示工作流）·
                连通（opencode server 端口；模型连通需手动触发）。快速体检约 20 秒。
              </p>
              {diagBusy && <p className="aios-sys__sub">体检运行中（约 20~60 秒）…</p>}
              {diagErr && <p className="aios-wf__err">{diagErr}</p>}
              {diag && (
                <>
                  <p className="aios-sys__meta">
                    模式 {diag.mode} · 通过 {diag.summary.pass ?? 0} · 失败 {diag.summary.fail ?? 0} · 警告{" "}
                    {diag.summary.warn ?? 0} · 用时 {diag.elapsed_s}s
                  </p>
                  {diag.items.map((it) => (
                    <div className="aios-diag__item" key={it.id}>
                      <div className="aios-diag__head">
                        <span className={`aios-wf__badge ${`is-${it.status}`}`}>{DIAG_LABEL[it.status] ?? it.status}</span>
                        <strong>
                          {it.group}·{it.name}
                        </strong>
                        {it.ms > 0 && <span className="aios-svc__meta">{it.ms}ms</span>}
                      </div>
                      {it.detail && <p className="aios-diag__detail">{it.detail}</p>}
                    </div>
                  ))}
                </>
              )}
            </>
          )}

          {tab === "about" && (
            <>
              <p className="aios-sys__meta">aios 控制台（WIP）· 原语 / 声明式工作流 / agent 图 三层体系</p>
              <p className="aios-sys__sub">仓库 github.com/373368/aios · 核心目录 l2-memory · 面板仅监听 127.0.0.1</p>
              <p className="aios-sys__sub">
                设置页入口：初始化（四步向导）· 状态（服务/goals）· 配置（快速配置 + config.json）· 体检（自检与模型连通）
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
