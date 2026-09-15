import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  X,
} from "lucide-react";
import type { ReactNode } from "react";

type AiosPanel = "workspace" | "workflows" | "chat";

interface AiosShellProps {
  workspace: ReactNode;
  workflows: ReactNode;
}

const PANEL_KEY = "aios-panel-state";

function readClosed(): AiosPanel[] {
  try {
    const raw = window.localStorage.getItem(PANEL_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const closed = parsed.filter((p): p is AiosPanel => p === "workspace" || p === "workflows" || p === "chat");
    // 默认所有面板打开：历史状态若为全关（误存/测试残留）则清除恢复
    if (closed.length === 3) {
      window.localStorage.removeItem(PANEL_KEY);
      return [];
    }
    // chat 面板默认关闭（独立于工作台/工作流，需要时手动打开）
    if (!closed.includes("chat")) closed.push("chat");
    return closed;
  } catch {
    return [];
  }
}

function writeClosed(closed: AiosPanel[]) {
  try {
    window.localStorage.setItem(PANEL_KEY, JSON.stringify(closed));
  } catch {
    // best effort
  }
}

function PanelFrame({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <section className="aios-panel">
      <header className="aios-panel__bar">
        <span className="aios-panel__title">{title}</span>
        <button className="aios-panel__close" onClick={onClose} aria-label={`关闭${title}`}>
          <X size={16} />
        </button>
      </header>
      <div className="aios-panel__body">{children}</div>
    </section>
  );
}

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

function SettingsDialog({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState<StatusSummary | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setErr("");
    try {
      const resp = await fetch("/status.json");
      if (!resp.ok) throw new Error(`status ${resp.status}`);
      setStatus(parseStatus(await resp.json()));
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="aios-modal" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="aios-modal__card" onClick={(e) => e.stopPropagation()}>
        <header className="aios-modal__bar">
          <span>系统状态</span>
          <button onClick={onClose} aria-label="关闭设置">
            <X size={16} />
          </button>
        </header>
        <div className="aios-modal__body">
          <div className="aios-sys__bar">
            <span>{status ? (status.ok ? "服务正常" : "服务异常") : "加载中…"}</span>
            <button className="aios-topbar__btn" onClick={load} aria-label="刷新">刷新</button>
          </div>
          {err && <p className="aios-wf__err">{err}</p>}
          {status && (
            <>
              <p className="aios-sys__meta">目标 {status.goal_count} · 运行 {status.run_count}</p>
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
        </div>
      </div>
    </div>
  );
}

/** Chat 面板：可选已接入 loopx 的 agent（opencode / OpenScience），iframe 直连各自 serve */
function ChatPanel() {
  const [agent, setAgent] = useState<"opencode" | "openscience">("opencode");
  const agents = [
    { id: "opencode", label: "OpenCode", url: "http://127.0.0.1:4400/" },
    { id: "openscience", label: "OpenScience", url: "http://127.0.0.1:4401/" },
  ] as const;
  const current = agents.find((a) => a.id === agent) ?? agents[0];
  return (
    <div className="aios-chat">
      <div className="aios-chat__bar" role="tablist" aria-label="选择 Chat 引擎">
        {agents.map((a) => (
          <button
            key={a.id}
            role="tab"
            aria-selected={a.id === agent}
            className={`aios-chat__tab ${a.id === agent ? "is-active" : ""}`}
            onClick={() => setAgent(a.id)}
            type="button"
          >
            {a.label}
          </button>
        ))}
      </div>
      <div className="aios-chat__frame">
        <iframe
          className="aios-panel__frame"
          src={current.url}
          title={`${current.label} Chat`}
          allow="clipboard-read; clipboard-write"
        />
      </div>
    </div>
  );
}

export function AiosShell({ workspace, workflows }: AiosShellProps) {
  const [closed, setClosed] = useState<AiosPanel[]>(readClosed);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const isClosed = (p: AiosPanel) => closed.includes(p);
  const toggle = (p: AiosPanel) =>
    setClosed((prev) => {
      const next = prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p];
      writeClosed(next);
      return next;
    });

  const bothClosed = closed.length === 2;

  return (
    <div className="aios-shell">
      <header className="aios-topbar">
        <div className="aios-topbar__brand">
          <span className="aios-topbar__logo">AI-OS</span>
        </div>
        <nav className="aios-topbar__nav">
          <button
            className={`aios-topbar__btn ${!isClosed("workspace") ? "is-active" : ""}`}
            onClick={() => toggle("workspace")}
            aria-label="工作台"
          >
            {isClosed("workspace") ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            <span>工作台</span>
          </button>
          <button
            className={`aios-topbar__btn ${!isClosed("workflows") ? "is-active" : ""}`}
            onClick={() => toggle("workflows")}
            aria-label="工作流"
          >
            <Activity size={16} />
            <span>工作流</span>
          </button>
          <button
            className={`aios-topbar__btn ${!isClosed("chat") ? "is-active" : ""}`}
            onClick={() => toggle("chat")}
            aria-label="Chat"
          >
            <MessageSquare size={16} />
            <span>Chat</span>
          </button>
        </nav>
        <div className="aios-topbar__right">
          <button
            className="aios-topbar__btn"
            onClick={() => setSettingsOpen(true)}
            aria-label="设置"
          >
            <Settings size={16} />
            <span>设置</span>
          </button>
        </div>
      </header>

      <div className={`aios-panel-grid ${bothClosed ? "is-clear" : ""}`}>
        {!isClosed("workspace") && (
          <PanelFrame title="工作台" onClose={() => toggle("workspace")}>
            {workspace}
          </PanelFrame>
        )}
        {!isClosed("workflows") && (
          <PanelFrame title="工作流" onClose={() => toggle("workflows")}>
            {workflows}
          </PanelFrame>
        )}
        {!isClosed("chat") && (
          <PanelFrame title="Chat" onClose={() => toggle("chat")}>
            <ChatPanel />
          </PanelFrame>
        )}

      </div>

      {settingsOpen && <SettingsDialog onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
