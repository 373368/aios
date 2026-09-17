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

type Tab = "status" | "config" | "check" | "about";

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

const TAB_LABEL: Record<Tab, string> = { status: "状态", config: "配置", check: "体检", about: "关于" };
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
  }, [loadStatus, loadServices]);

  useEffect(() => {
    if (tab === "config" && !cfgText) loadConfig();
  }, [tab, cfgText, loadConfig]);

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
              <p className="aios-sys__sub">
                编辑 l2-memory/config.json：模型 / provider / 服务端口。保存前自动备份（config.json.bak-时间戳）；
                密钥明文仅存本机，本页只监听 127.0.0.1。
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
                体检条例：环境（Python/依赖）· 配置（config.json/路径）· 引擎（能力目录/原语自检/spec 校验/工具池/演示工作流）·
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
              <p className="aios-sys__sub">设置页入口：状态（服务/goals）· 配置（config.json）· 体检（自检与模型连通）</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
