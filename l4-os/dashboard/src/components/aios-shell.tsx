import { useState } from "react";
import {
  Activity,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  X,
} from "lucide-react";
import type { ReactNode } from "react";
import { SettingsDialog } from "./settings-dialog";

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
