import { useCallback, useEffect, useMemo, useState } from "react";

interface WfItem {
  name: string;
  description: string;
  version: string;
  command: string;
  args: string[];
  path: string;
}

interface RenderState {
  name: string;
  log: string;
  total_lines: number;
  last_line: string;
  state: string;
}

interface DeclItem {
  name: string;
  file: string;
  description: string;
  model: string;
  path: string;
  registered_in: string[];
}

interface GoalItem {
  id: string;
  display_name: string;
  activation_state: string;
  registered_agents: string[];
  agent_model: string;
  sources?: string[];
}

interface AgentsData {
  declarations: DeclItem[];
  goals: GoalItem[];
}

interface RegisterPayload {
  written?: boolean;
  changed?: boolean;
  requested_agents?: string[];
  existing_agents?: string[];
  registered_agents?: string[];
  heartbeat_prompt_migration?: { status?: string } | null;
}

interface RegisterResult {
  ok: boolean;
  execute?: boolean;
  goal_id?: string;
  agent_id?: string;
  error?: string;
  stderr?: string | null;
  payload?: RegisterPayload | null;
}

/**
 * 工作流面板：wfctl 接口（list/render/trigger + agents/agents-register）监控与触发。
 * 经壳 AiosShell /wfctl 代理调 wfctl.py。
 * 两个页签：
 *  - 工作流：按管线分组的卡片（触发/状态）
 *  - Agents：身份声明（agentgraph/declarations）× loopx goal 注册（预览门 → 写入；
 *    Goal 名单可逐项移除，chip × → 确认条）
 */
/** 常用参数说明（纯前端提示，不涉及数据；布尔类给固定选项下拉） */
const ARG_HINTS: Record<string, { hint: string; options?: string[] }> = {
  source: { hint: "源目录路径，默认走收件箱" },
  skip_export: { hint: "是否跳过导出", options: ["", "true", "false"] },
  query: { hint: "检索关键词，留空全量" },
};

/** 工作流分组（编排布局：按管线归类；未列出的归入「其他」） */
const WF_GROUPS: { title: string; names: string[] }[] = [
  { title: "记忆管线", names: ["digest-daily"] },
  { title: "内容管线", names: ["archive-daily", "track-daily"] },
  { title: "自检与冒烟", names: ["wf-selfcheck", "wf-test-agent", "wf-test-source", "wf-test-judge"] },
];

const TAB_KEY = "aios-wf-tab";
type Tab = "workflows" | "agents";

export function WorkflowsPanel() {
  const [tab, setTab] = useState<Tab>(() => {
    try {
      return localStorage.getItem(TAB_KEY) === "agents" ? "agents" : "workflows";
    } catch {
      return "workflows";
    }
  });
  // —— 工作流页签状态 ——
  const [items, setItems] = useState<WfItem[]>([]);
  const [renders, setRenders] = useState<Record<string, RenderState>>({});
  const [running, setRunning] = useState<string | null>(null);
  const [lastOut, setLastOut] = useState<Record<string, string>>({});
  const [loadErr, setLoadErr] = useState("");
  const [argsVal, setArgsVal] = useState<Record<string, Record<string, string>>>({});
  // —— Agents 页签状态 ——
  const [agents, setAgents] = useState<AgentsData | null>(null);
  const [agentsErr, setAgentsErr] = useState("");
  const [sel, setSel] = useState<string[]>([]);
  const [goalSel, setGoalSel] = useState("");
  const [regBusy, setRegBusy] = useState(false);
  const [preview, setPreview] = useState<RegisterResult | null>(null);
  // —— Agents：移除注册状态 ——
  const [removeTarget, setRemoveTarget] = useState<{ goalId: string; agent: string } | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeMsg, setRemoveMsg] = useState<{ ok: boolean; text: string } | null>(null);
  // —— Agents：新建身份声明状态 ——
  const [declareOpen, setDeclareOpen] = useState(false);
  const [declForm, setDeclForm] = useState({ name: "", description: "", model: "", body: "" });
  const [declareBusy, setDeclareBusy] = useState(false);
  const [declareMsg, setDeclareMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const resp = await fetch("/wfctl/list");
      if (!resp.ok) throw new Error(`list ${resp.status}`);
      const data: WfItem[] = await resp.json();
      setItems(data);
      // 并行取各工作流状态
      const r: Record<string, RenderState> = {};
      await Promise.all(
        data.map(async (it) => {
          try {
            const res = await fetch(`/wfctl/render?name=${encodeURIComponent(it.name)}`);
            if (res.ok) r[it.name] = await res.json();
          } catch {
            /* 单个失败不阻塞 */
          }
        }),
      );
      setRenders(r);
    } catch (e) {
      setLoadErr(String(e));
    }
  }, []);

  const loadAgents = useCallback(async () => {
    setAgentsErr("");
    try {
      const resp = await fetch("/wfctl/agents");
      if (!resp.ok) throw new Error(`agents ${resp.status}`);
      const data: AgentsData = await resp.json();
      setAgents(data);
      setGoalSel((g) => g || data.goals[0]?.id || "");
    } catch (e) {
      setAgentsErr(String(e));
    }
  }, []);

  useEffect(() => {
    load();
    loadAgents();
  }, [load, loadAgents]);

  function switchTab(t: Tab) {
    setTab(t);
    try {
      localStorage.setItem(TAB_KEY, t);
    } catch {
      /* best effort */
    }
  }

  function setArg(name: string, arg: string, value: string) {
    setArgsVal((prev) => ({
      ...prev,
      [name]: { ...(prev[name] ?? {}), [arg]: value },
    }));
  }

  async function trigger(name: string) {
    setRunning(name);
    setLastOut((prev) => ({ ...prev, [name]: "" }));
    // 非空参数拼成 k=v 传 trigger（空的省略，走工作流默认值）
    const kv = Object.entries(argsVal[name] ?? {})
      .filter(([, v]) => v.trim() !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join("&");
    try {
      const resp = await fetch(`/wfctl/trigger?name=${encodeURIComponent(name)}${kv ? "&" + kv : ""}`);
      const data = await resp.json();
      setLastOut((prev) => ({ ...prev, [name]: data.output || data.error || `exit=${data.exit}` }));
    } catch (e) {
      setLastOut((prev) => ({ ...prev, [name]: String(e) }));
    } finally {
      setRunning(null);
      load(); // 刷新状态
    }
  }

  function badge(state: string | undefined) {
    const cls = state === "completed" ? "is-ok" : state === "no-log" ? "is-idle" : "is-run";
    return <span className={`aios-wf__badge ${cls}`}>{state || "…"}</span>;
  }

  // —— Agents：注册流程（预览门 → 显式写入） ——
  function toggleSel(name: string) {
    setSel((prev) => (prev.includes(name) ? prev.filter((x) => x !== name) : [...prev, name]));
    setPreview(null);
  }

  async function callRegister(execute: boolean): Promise<RegisterResult> {
    const qs = new URLSearchParams({ agent_id: sel.join(","), goal_id: goalSel });
    if (execute) qs.set("execute", "1");
    const resp = await fetch(`/wfctl/agents-register?${qs.toString()}`);
    const raw = (await resp.json()) as Record<string, unknown>;
    // 壳在异常路径会包成 {exit, output, error}；把 output 里的 JSON 还原
    if (raw && typeof raw.output === "string" && !("ok" in raw)) {
      try {
        return JSON.parse(raw.output) as RegisterResult;
      } catch {
        return { ok: false, error: String(raw.error || raw.output) };
      }
    }
    return raw as unknown as RegisterResult;
  }

  async function doPreview() {
    if (!sel.length || !goalSel) return;
    setRegBusy(true);
    setPreview(null);
    try {
      setPreview(await callRegister(false));
    } catch (e) {
      setPreview({ ok: false, error: String(e) });
    } finally {
      setRegBusy(false);
    }
  }

  async function doExecute() {
    setRegBusy(true);
    try {
      const r = await callRegister(true);
      setPreview(r);
      if (r.ok) {
        setSel([]);
        await loadAgents();
      }
    } catch (e) {
      setPreview({ ok: false, error: String(e) });
    } finally {
      setRegBusy(false);
    }
  }

  // —— Agents：移除注册（configure-goal 名单替换；先确认后写入） ——
  async function callUnregister(goalId: string, agent: string, execute: boolean) {
    const qs = new URLSearchParams({ agent_id: agent, goal_id: goalId });
    if (execute) qs.set("execute", "1");
    const resp = await fetch(`/wfctl/agents-unregister?${qs.toString()}`);
    const raw = (await resp.json()) as Record<string, unknown>;
    // 壳在异常路径会包成 {exit, output, error}；把 output 里的 JSON 还原
    if (raw && typeof raw.output === "string" && !("ok" in raw)) {
      try {
        return JSON.parse(raw.output) as { ok?: boolean; error?: string; readback?: string[] };
      } catch {
        return { ok: false, error: String(raw.error || raw.output) } as {
          ok?: boolean;
          error?: string;
          readback?: string[];
        };
      }
    }
    return raw as { ok?: boolean; error?: string; readback?: string[] };
  }

  async function doRemove() {
    if (!removeTarget) return;
    setRemoveBusy(true);
    setRemoveMsg(null);
    try {
      const r = await callUnregister(removeTarget.goalId, removeTarget.agent, true);
      if (r.ok) {
        setRemoveMsg({
          ok: true,
          text: `已从 ${removeTarget.goalId} 移除 ${removeTarget.agent}（当前名单：${(r.readback ?? []).join(", ") || "空"}）`,
        });
        setRemoveTarget(null);
        await loadAgents();
      } else {
        setRemoveMsg({ ok: false, text: `移除失败：${r.error || "未知错误"}` });
      }
    } catch (e) {
      setRemoveMsg({ ok: false, text: `移除失败：${String(e)}` });
    } finally {
      setRemoveBusy(false);
    }
  }

  // —— Agents：新建身份声明（落盘 declarations/<name>.md） ——
  async function doDeclare() {
    const name = declForm.name.trim();
    if (!name) return;
    setDeclareBusy(true);
    setDeclareMsg(null);
    try {
      const qs = new URLSearchParams({ name });
      if (declForm.description.trim()) qs.set("description", declForm.description.trim());
      if (declForm.model.trim()) qs.set("model", declForm.model.trim());
      if (declForm.body.trim()) qs.set("body", declForm.body.trim());
      const resp = await fetch(`/wfctl/agents-declare?${qs.toString()}`);
      const raw = (await resp.json()) as Record<string, unknown>;
      let res: { ok?: boolean; error?: string } = raw as { ok?: boolean; error?: string };
      // 壳在异常路径会包成 {exit, output, error}；把 output 里的 JSON 还原
      if (raw && typeof raw.output === "string" && !("ok" in raw)) {
        try {
          res = JSON.parse(raw.output) as { ok?: boolean; error?: string };
        } catch {
          res = { ok: false, error: String(raw.error || raw.output) };
        }
      }
      if (res.ok) {
        setDeclareMsg({ ok: true, text: `已创建 ${name}.md（可继续编辑文件补充正文）` });
        setDeclForm({ name: "", description: "", model: "", body: "" });
        await loadAgents();
      } else {
        setDeclareMsg({ ok: false, text: `创建失败：${res.error || "未知错误"}` });
      }
    } catch (e) {
      setDeclareMsg({ ok: false, text: `创建失败：${String(e)}` });
    } finally {
      setDeclareBusy(false);
    }
  }

  const groups = useMemo(() => {
    if (!items.length) return [] as { title: string; list: WfItem[] }[];
    const map = new Map<string, WfItem[]>();
    for (const it of items) {
      const g = WF_GROUPS.find((x) => x.names.includes(it.name))?.title ?? "其他";
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(it);
    }
    const order = [...WF_GROUPS.map((g) => g.title), "其他"];
    return order.filter((t) => map.has(t)).map((t) => ({ title: t, list: map.get(t)! }));
  }, [items]);

  function renderWfCard(it: WfItem) {
    return (
      <div className="aios-wf__card" key={it.name}>
        <div className="aios-wf__head">
          <strong>{it.name}</strong>
          {badge(renders[it.name]?.state)}
        </div>
        <p className="aios-wf__desc">{it.description}</p>
        {renders[it.name]?.last_line && (
          <p className="aios-wf__last" title={renders[it.name]?.last_line}>
            最近: {renders[it.name]?.last_line}
          </p>
        )}
        {it.args.length > 0 && (
          <div className="aios-wf__args">
            {it.args.map((arg) => {
              const hint = ARG_HINTS[arg];
              return (
                <label className="aios-wf__arg" key={arg}>
                  <span className="aios-wf__argname">{arg}</span>
                  {hint?.options ? (
                    <select
                      value={argsVal[it.name]?.[arg] ?? ""}
                      onChange={(e) => setArg(it.name, arg, e.target.value)}
                    >
                      {hint.options.map((o) => (
                        <option key={o} value={o}>
                          {o === "" ? "留空用默认值" : o}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={argsVal[it.name]?.[arg] ?? ""}
                      onChange={(e) => setArg(it.name, arg, e.target.value)}
                      placeholder="留空用默认值"
                    />
                  )}
                  <small className="aios-wf__arghint">{hint?.hint ?? "参数值，留空使用工作流默认值"}</small>
                </label>
              );
            })}
          </div>
        )}
        <button
          className="aios-wf__trigger"
          onClick={() => trigger(it.name)}
          disabled={running !== null}
        >
          {running === it.name ? "运行中…" : "触发"}
        </button>
        {lastOut[it.name] && <pre className="aios-wf__out">{lastOut[it.name]}</pre>}
      </div>
    );
  }

  function renderPreview() {
    if (!preview) return null;
    if (!preview.ok) {
      const msg =
        preview.error ||
        (preview.payload as { error?: string } | null | undefined)?.error ||
        preview.stderr ||
        "未知错误";
      return <p className="aios-wf__err">注册失败：{msg}</p>;
    }
    const p = preview.payload ?? {};
    const req = p.requested_agents ?? [];
    const existing = p.existing_agents ?? [];
    const hb = p.heartbeat_prompt_migration?.status;
    return (
      <div className="aios-agent__msg">
        <p>
          {preview.execute ? "已写入 ✓" : "预览（未写入）"} · goal <code>{preview.goal_id}</code>
        </p>
        <p>本次身份：{req.length ? req.join(", ") : "无（未选中或已注册）"}</p>
        <p>
          注册前已有：{existing.length ? existing.join(", ") : "无"} · changed={String(p.changed)} written=
          {String(p.written)}
        </p>
        {hb === "required" && <p>提示：宿主 heartbeat 需重新生成（migration required）。</p>}
        {!preview.execute && req.length > 0 && (
          <div className="aios-agent__actions">
            <button className="aios-wf__trigger" onClick={doExecute} disabled={regBusy}>
              {regBusy ? "写入中…" : "确认写入"}
            </button>
            <button className="aios-topbar__btn" onClick={() => setPreview(null)}>
              取消
            </button>
          </div>
        )}
      </div>
    );
  }

  const goals = agents?.goals ?? [];
  const declarations = agents?.declarations ?? [];

  return (
    <div className="aios-workflows">
      <div className="aios-wf__tabs" role="tablist" aria-label="面板页签">
        <button
          role="tab"
          aria-selected={tab === "workflows"}
          className={`aios-wf__tab ${tab === "workflows" ? "is-active" : ""}`}
          onClick={() => switchTab("workflows")}
          type="button"
        >
          工作流
        </button>
        <button
          role="tab"
          aria-selected={tab === "agents"}
          className={`aios-wf__tab ${tab === "agents" ? "is-active" : ""}`}
          onClick={() => switchTab("agents")}
          type="button"
        >
          Agents{agents ? ` (${declarations.length})` : ""}
        </button>
        <button
          className="aios-topbar__btn"
          onClick={() => (tab === "workflows" ? load() : loadAgents())}
          aria-label="刷新"
        >
          刷新
        </button>
      </div>

      {tab === "workflows" && (
        <>
          {loadErr && <p className="aios-wf__err">{loadErr}</p>}
          {items.length === 0 && !loadErr && <p className="aios-workflows__hint">无可用工作流。</p>}
          {groups.map((g) => (
            <div className="aios-wf__section" key={g.title}>
              <p className="aios-wf__group">{g.title}</p>
              {g.list.map(renderWfCard)}
            </div>
          ))}
        </>
      )}

      {tab === "agents" && (
        <>
          {agentsErr && <p className="aios-wf__err">{agentsErr}</p>}

          <div className="aios-agent__headrow">
            <p className="aios-wf__group">身份声明（agentgraph/declarations）</p>
            <button
              className="aios-topbar__btn"
              type="button"
              onClick={() => {
                setDeclareOpen((v) => !v);
                setDeclareMsg(null);
              }}
            >
              {declareOpen ? "收起" : "＋ 新建身份"}
            </button>
          </div>
          {declareOpen && (
            <div className="aios-agent__form">
              <label>
                name（文件名：小写字母/数字/短横线）
                <input
                  type="text"
                  value={declForm.name}
                  onChange={(e) => setDeclForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="如 research-analyst"
                />
              </label>
              <label>
                描述
                <input
                  type="text"
                  value={declForm.description}
                  onChange={(e) => setDeclForm((f) => ({ ...f, description: e.target.value }))}
                  placeholder="一句话说明这个身份"
                />
              </label>
              <label>
                模型（留空用运行时默认）
                <input
                  type="text"
                  value={declForm.model}
                  onChange={(e) => setDeclForm((f) => ({ ...f, model: e.target.value }))}
                  placeholder="如 volcengine-agent-plan/deepseek-v4-flash"
                />
              </label>
              <label>
                正文（人设/运行规范/输出要求；留空生成模板）
                <textarea
                  rows={4}
                  value={declForm.body}
                  onChange={(e) => setDeclForm((f) => ({ ...f, body: e.target.value }))}
                  placeholder="可直接写正文；留空则写入标准模板"
                />
              </label>
              <div className="aios-agent__actions">
                <button
                  className="aios-wf__trigger"
                  type="button"
                  onClick={doDeclare}
                  disabled={declareBusy || !declForm.name.trim()}
                >
                  {declareBusy ? "创建中…" : "创建"}
                </button>
                <button className="aios-topbar__btn" type="button" onClick={() => setDeclareOpen(false)}>
                  取消
                </button>
              </div>
              {declareMsg && (
                <p className={declareMsg.ok ? "aios-agent__hint" : "aios-wf__err"}>{declareMsg.text}</p>
              )}
            </div>
          )}
          <div className="aios-agent__bar">
            <select
              value={goalSel}
              onChange={(e) => {
                setGoalSel(e.target.value);
                setPreview(null);
              }}
              disabled={!goals.length}
              aria-label="目标 goal"
            >
              {goals.length === 0 && <option value="">（无 goal）</option>}
              {goals.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.display_name || g.id}
                </option>
              ))}
            </select>
            <button
              className="aios-wf__trigger"
              onClick={doPreview}
              disabled={!sel.length || !goalSel || regBusy}
            >
              预览注册（已选 {sel.length}）
            </button>
          </div>
          {!goals.length && (
            <p className="aios-agent__hint">
              还没有 goal：注册身份需要先有一个 goal（测试 goals 已清理，自动链阶段重建后即可用）。
            </p>
          )}
          {renderPreview()}

          {declarations.map((d) => {
            const checked = sel.includes(d.name);
            return (
              <div className={`aios-agent ${checked ? "is-sel" : ""}`} key={d.name}>
                <label className="aios-agent__check">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleSel(d.name)}
                    aria-label={`选择 ${d.name}`}
                  />
                </label>
                <div className="aios-agent__main">
                  <div className="aios-agent__head">
                    <strong>{d.name}</strong>
                    {d.model && <span className="aios-agent__model">{d.model}</span>}
                  </div>
                  {d.description && <p className="aios-agent__desc">{d.description}</p>}
                  <div className="aios-agent__chips">
                    {d.registered_in.length > 0 ? (
                      d.registered_in.map((g) => (
                        <span className="aios-agent__chip is-on" key={g}>
                          已注册 · {g}
                        </span>
                      ))
                    ) : (
                      <span className="aios-agent__chip">未注册</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
          {!agents && !agentsErr && <p className="aios-workflows__hint">加载中…</p>}

          <p className="aios-wf__group">Goals 注册表</p>
          {goals.map((g) => (
            <div className="aios-wf__card" key={g.id}>
              <div className="aios-wf__head">
                <strong>{g.display_name || g.id}</strong>
                <span
                  className={`aios-wf__badge ${g.activation_state === "stopped" ? "is-idle" : "is-ok"}`}
                >
                  {g.activation_state || "?"}
                </span>
              </div>
              <p className="aios-wf__desc">
                id: {g.id}
                {g.agent_model ? ` · agent_model: ${g.agent_model}` : ""}
              </p>
              <div className="aios-agent__chips">
                {g.registered_agents.length ? (
                  g.registered_agents.map((a) => (
                    <span className="aios-agent__chip is-on" key={a}>
                      {a}
                      <button
                        type="button"
                        className="aios-agent__chip-x"
                        title={`从 ${g.id} 移除 ${a}`}
                        onClick={() => {
                          setRemoveMsg(null);
                          setRemoveTarget({ goalId: g.id, agent: a });
                        }}
                        aria-label={`移除 ${a}`}
                      >
                        ×
                      </button>
                    </span>
                  ))
                ) : (
                  <span className="aios-agent__chip">无注册身份</span>
                )}
              </div>
              {removeTarget?.goalId === g.id && (
                <div className="aios-agent__confirmbar">
                  <span>
                    从 {g.id} 移除 <b>{removeTarget.agent}</b>？
                  </span>
                  <button className="aios-wf__trigger" type="button" onClick={doRemove} disabled={removeBusy}>
                    {removeBusy ? "移除中…" : "确认移除"}
                  </button>
                  <button className="aios-topbar__btn" type="button" onClick={() => setRemoveTarget(null)}>
                    取消
                  </button>
                </div>
              )}
            </div>
          ))}
          {removeMsg && (
            <p className={removeMsg.ok ? "aios-agent__hint" : "aios-wf__err"}>{removeMsg.text}</p>
          )}
          {agents && goals.length === 0 && (
            <p className="aios-workflows__hint">（无 goal 记录）</p>
          )}
        </>
      )}
    </div>
  );
}
