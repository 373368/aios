import { useCallback, useEffect, useMemo, useState } from "react";

interface ArgSpec {
  name: string;
  type?: "text" | "longtext" | "bool" | "select";
  hint?: string;
  required?: boolean;
  default?: string;
  options?: string[];
}

interface WfItem {
  name: string;
  description: string;
  version: string;
  command: string;
  args: string[];
  required?: string[];
  arguments?: ArgSpec[] | null;
  invokes?: string[];
  path: string;
}

interface SpecItem {
  name: string;
  description: string;
  model: string;
  inputs?: ArgSpec[];
  outputs?: string[];
  declarations?: string[];
  invoked_by?: string[];
  path: string;
}

interface CatalogData {
  workflows: WfItem[];
  agents: SpecItem[];
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
  tools: string[];
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
  tools_available?: string[];
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
 * 能力面板：wfctl 接口（catalog/render/trigger/run-agent + agents/agents-register）监控与运行。
 * 经壳 AiosShell /wfctl 代理调 wfctl.py。
 * 两个页签（均为「卡片列表 → 详情页」两态）：
 *  - 工作流：按管线分组的任务卡（详情页 = 参数表单 + 运行 + 结果 + 调用 Agent 跳转）
 *  - Agents：可运行 Agent（specs）卡 + 身份声明（agentgraph/declarations）× loopx goal 注册
 *    （预览门 → 写入；Goal 名单可逐项移除，chip × → 确认条）
 */
/** 常用参数说明（纯前端提示，不涉及数据；布尔类给固定选项下拉） */
const ARG_HINTS: Record<string, { hint: string; options?: string[] }> = {
  source: { hint: "源目录路径，默认走收件箱" },
  skip_export: { hint: "是否跳过导出", options: ["", "true", "false"] },
  query: { hint: "检索关键词，留空全量" },
  topic: { hint: "调研主题（必填，留空将直接报错）" },
  brief: { hint: "工具需求描述（必填，越具体越好）" },
  url: { hint: "参考网址（可选：指定页面供抓取参考）" },
};

/** 工作流分组（编排布局：按管线归类；未列出的归入「其他」）
 *  机读任务（agent-forge / wf-selfcheck / wf-test-*）由 wfctl 按 ui_hidden 过滤，不上面板 */
const WF_GROUPS: { title: string; names: string[] }[] = [
  { title: "记忆管线", names: ["digest-daily"] },
  { title: "内容管线", names: ["archive-daily", "track-daily", "research"] },
  { title: "工厂", names: ["tool-scout"] },
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
  // —— 能力目录 / 详情页状态 ——
  const [specs, setSpecs] = useState<SpecItem[]>([]);
  const [detail, setDetail] = useState<{ kind: "wf" | "agent"; name: string } | null>(null);
  const [specRunning, setSpecRunning] = useState<string | null>(null);
  const [specOut, setSpecOut] = useState<Record<string, string>>({});
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
  const [declForm, setDeclForm] = useState({ name: "", description: "", model: "", tools: "", body: "" });
  const [declareBusy, setDeclareBusy] = useState(false);
  const [declareMsg, setDeclareMsg] = useState<{ ok: boolean; text: string } | null>(null);
  // —— Agents：AI 填充（brief → 建议草案，只读） ——
  const [suggestBrief, setSuggestBrief] = useState("");
  const [suggestBusy, setSuggestBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const resp = await fetch("/wfctl/catalog");
      if (!resp.ok) throw new Error(`catalog ${resp.status}`);
      const data: CatalogData = await resp.json();
      if (!data || !Array.isArray(data.workflows) || !Array.isArray(data.agents)) {
        throw new Error("catalog 响应结构不符（壳或 wfctl 版本过旧？）");
      }
      setItems(data.workflows);
      setSpecs(data.agents);
      // 并行取各工作流状态
      const r: Record<string, RenderState> = {};
      await Promise.all(
        data.workflows.map(async (it) => {
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
      // 边界校验：旧壳/异常响应（如回退成 list 数组）直接报错降级，避免未守护访问把整页打白
      if (!data || !Array.isArray(data.declarations) || !Array.isArray(data.goals)) {
        throw new Error("agents 响应结构不符（壳或 wfctl 版本过旧？）");
      }
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

  function setArg(scope: string, arg: string, value: string) {
    setArgsVal((prev) => ({
      ...prev,
      [scope]: { ...(prev[scope] ?? {}), [arg]: value },
    }));
  }

  async function trigger(name: string) {
    setRunning(name);
    setLastOut((prev) => ({ ...prev, [name]: "" }));
    // 非空参数拼成 k=v 传 trigger（空的省略，走工作流默认值）
    const kv = Object.entries(argsVal[`wf:${name}`] ?? {})
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

  async function runSpec(name: string) {
    setSpecRunning(name);
    setSpecOut((prev) => ({ ...prev, [name]: "" }));
    const kv = Object.entries(argsVal[`spec:${name}`] ?? {})
      .filter(([, v]) => v.trim() !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join("&");
    try {
      const resp = await fetch(`/wfctl/run-agent?spec=${encodeURIComponent(name)}${kv ? "&" + kv : ""}`);
      const data = await resp.json();
      setSpecOut((prev) => ({ ...prev, [name]: data.output || data.error || `exit=${data.exit}` }));
    } catch (e) {
      setSpecOut((prev) => ({ ...prev, [name]: String(e) }));
    } finally {
      setSpecRunning(null);
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
      if (declForm.tools.trim()) qs.set("tools", declForm.tools.trim());
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
        setDeclForm({ name: "", description: "", model: "", tools: "", body: "" });
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

  // —— Agents：AI 填充（brief → 身份草案建议；只读不落盘，提交仍走 agents-declare 严格校验） ——
  async function doSuggest() {
    const brief = suggestBrief.trim();
    if (!brief) return;
    setSuggestBusy(true);
    setDeclareMsg(null);
    try {
      const resp = await fetch(`/wfctl/agents-suggest?brief=${encodeURIComponent(brief)}`);
      const raw = (await resp.json()) as Record<string, unknown>;
      let res = raw as { ok?: boolean; error?: string; suggestion?: Record<string, unknown> };
      // 壳在异常路径会包成 {exit, output, error}；把 output 里的 JSON 还原
      if (raw && typeof raw.output === "string" && !("ok" in raw)) {
        try {
          res = JSON.parse(raw.output) as typeof res;
        } catch {
          res = { ok: false, error: String(raw.error || raw.output) };
        }
      }
      if (res.ok && res.suggestion) {
        const s = res.suggestion as {
          name?: string;
          description?: string;
          model?: string;
          tools?: string[];
          body?: string;
        };
        setDeclForm({
          name: s.name ?? "",
          description: s.description ?? "",
          model: s.model ?? "",
          tools: (s.tools ?? []).join(", "),
          body: s.body ?? "",
        });
        setDeclareMsg({ ok: true, text: "已由 AI 填充（可直接修改后创建）" });
      } else {
        setDeclareMsg({ ok: false, text: `AI 填充失败：${res.error || "未知错误"}` });
      }
    } catch (e) {
      setDeclareMsg({ ok: false, text: `AI 填充失败：${String(e)}` });
    } finally {
      setSuggestBusy(false);
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

  function wfArgSpecs(it: WfItem): ArgSpec[] {
    if (it.arguments) return it.arguments;
    return (it.args ?? []).map((a) => ({
      name: a,
      type: ARG_HINTS[a]?.options ? "select" : "text",
      hint: ARG_HINTS[a]?.hint,
      required: it.required?.includes(a),
      options: ARG_HINTS[a]?.options,
    }));
  }

  function renderArgField(scope: string, a: ArgSpec) {
    const val = argsVal[scope]?.[a.name] ?? "";
    const set = (v: string) => setArg(scope, a.name, v);
    return (
      <label className="aios-wf__arg" key={a.name}>
        <span className="aios-wf__argname">
          {a.name}
          {a.required ? " *" : ""}
        </span>
        {a.type === "bool" ? (
          <span className="aios-wf__bool">
            <input type="checkbox" checked={val === "true"} onChange={(e) => set(e.target.checked ? "true" : "")} />
            <span>是</span>
          </span>
        ) : a.type === "select" ? (
          <select value={val} onChange={(e) => set(e.target.value)}>
            <option value="">{a.required ? "（必选）" : "（默认）"}</option>
            {(a.options ?? []).map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        ) : a.type === "longtext" ? (
          <textarea
            rows={3}
            value={val}
            onChange={(e) => set(e.target.value)}
            placeholder={a.required ? "必填" : "可选，留空用默认值"}
          />
        ) : (
          <input
            type="text"
            value={val}
            onChange={(e) => set(e.target.value)}
            placeholder={a.required ? "必填" : "可选，留空用默认值"}
          />
        )}
        <small className="aios-wf__arghint">{a.hint ?? (a.required ? "必填" : "留空用默认值")}</small>
      </label>
    );
  }

  function renderWfCard(it: WfItem) {
    return (
      <div
        className="aios-wf__card is-clickable"
        key={it.name}
        role="button"
        tabIndex={0}
        onClick={() => setDetail({ kind: "wf", name: it.name })}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") setDetail({ kind: "wf", name: it.name });
        }}
      >
        <div className="aios-wf__head">
          <strong>{it.name}</strong>
          <span className="aios-wf__kind">任务</span>
          {badge(renders[it.name]?.state)}
        </div>
        <p className="aios-wf__desc">{it.description}</p>
        {renders[it.name]?.last_line && (
          <p className="aios-wf__last" title={renders[it.name]?.last_line}>
            最近: {renders[it.name]?.last_line}
          </p>
        )}
      </div>
    );
  }

  function renderSpecCard(sp: SpecItem) {
    return (
      <div
        className="aios-wf__card is-clickable"
        key={sp.name}
        role="button"
        tabIndex={0}
        onClick={() => setDetail({ kind: "agent", name: sp.name })}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") setDetail({ kind: "agent", name: sp.name });
        }}
      >
        <div className="aios-wf__head">
          <strong>{sp.name}</strong>
          <span className="aios-wf__kind is-agent">Agent</span>
        </div>
        <p className="aios-wf__desc">{sp.description}</p>
        <div className="aios-agent__chips">
          {(sp.declarations ?? []).map((d) => (
            <span className="aios-agent__chip" key={d}>{`身份 · ${d.replace(/\.md$/, "")}`}</span>
          ))}
          {(sp.invoked_by?.length ?? 0) > 0 && (
            <span className="aios-agent__chip is-on">经 {(sp.invoked_by ?? []).join(" / ")} 运行</span>
          )}
        </div>
      </div>
    );
  }

  function renderWfDetail(it: WfItem) {
    const scope = `wf:${it.name}`;
    const argSpecs = wfArgSpecs(it);
    const blocked = argSpecs.some((a) => a.required && !(argsVal[scope]?.[a.name] ?? "").trim());
    return (
      <div className="aios-wf__detail">
        <div className="aios-wf__detailbar">
          <button className="aios-topbar__btn" type="button" onClick={() => setDetail(null)}>
            ← 返回
          </button>
          <strong>{it.name}</strong>
          <span className="aios-wf__kind">任务</span>
          {badge(renders[it.name]?.state)}
        </div>
        <p className="aios-wf__desc">{it.description}</p>
        <p className="aios-wf__path">{it.path}</p>
        {argSpecs.length > 0 && <div className="aios-wf__args">{argSpecs.map((a) => renderArgField(scope, a))}</div>}
        <button
          className="aios-wf__trigger"
          type="button"
          onClick={() => trigger(it.name)}
          disabled={running !== null || blocked}
        >
          {running === it.name ? "运行中…" : "运行"}
        </button>
        {(it.invokes?.length ?? 0) > 0 && (
          <p className="aios-wf__last">
            调用 Agent：
            {(it.invokes ?? []).map((s) => (
              <button
                key={s}
                type="button"
                className="aios-agent__chiplink"
                onClick={() => setDetail({ kind: "agent", name: s })}
              >
                {s}
              </button>
            ))}
          </p>
        )}
        {lastOut[it.name] && <pre className="aios-wf__out">{lastOut[it.name]}</pre>}
      </div>
    );
  }

  function renderSpecDetail(sp: SpecItem) {
    const scope = `spec:${sp.name}`;
    const inputs = sp.inputs ?? [];
    const blocked = inputs.some((a) => a.required && !(argsVal[scope]?.[a.name] ?? "").trim());
    return (
      <div className="aios-wf__detail">
        <div className="aios-wf__detailbar">
          <button className="aios-topbar__btn" type="button" onClick={() => setDetail(null)}>
            ← 返回
          </button>
          <strong>{sp.name}</strong>
          <span className="aios-wf__kind is-agent">Agent</span>
        </div>
        <p className="aios-wf__desc">{sp.description}</p>
        <p className="aios-wf__path">{sp.path}</p>
        <div className="aios-agent__chips">
          {sp.model && <span className="aios-agent__chip">{sp.model}</span>}
          {(sp.declarations ?? []).map((d) => (
            <span className="aios-agent__chip" key={d}>{`身份 · ${d.replace(/\.md$/, "")}`}</span>
          ))}
          {(sp.outputs ?? []).map((o) => (
            <span className="aios-agent__chip" key={o}>{`输出 · ${o}`}</span>
          ))}
        </div>
        {inputs.length > 0 && <div className="aios-wf__args">{inputs.map((a) => renderArgField(scope, a))}</div>}
        <button
          className="aios-wf__trigger"
          type="button"
          onClick={() => runSpec(sp.name)}
          disabled={specRunning !== null || blocked}
        >
          {specRunning === sp.name ? "运行中…" : "运行"}
        </button>
        {(sp.invoked_by?.length ?? 0) > 0 && (
          <p className="aios-wf__last">
            经工作流运行：
            {(sp.invoked_by ?? []).map((w) => (
              <button
                key={w}
                type="button"
                className="aios-agent__chiplink"
                onClick={() => setDetail({ kind: "wf", name: w })}
              >
                {w}
              </button>
            ))}
          </p>
        )}
        {specOut[sp.name] && <pre className="aios-wf__out">{specOut[sp.name]}</pre>}
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

  const wfItem = detail?.kind === "wf" ? items.find((i) => i.name === detail.name) : undefined;
  const spItem = detail?.kind === "agent" ? specs.find((s) => s.name === detail.name) : undefined;

  function renderDetailMissing() {
    return (
      <div className="aios-wf__detail">
        <div className="aios-wf__detailbar">
          <button className="aios-topbar__btn" type="button" onClick={() => setDetail(null)}>
            ← 返回
          </button>
          <strong>未找到</strong>
        </div>
        <p className="aios-workflows__hint">该能力可能已移除，或列表尚未加载。</p>
      </div>
    );
  }

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

      {detail && (wfItem ? renderWfDetail(wfItem) : spItem ? renderSpecDetail(spItem) : renderDetailMissing())}

      {!detail && tab === "workflows" && (
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

      {!detail && tab === "agents" && (
        <>
          {agentsErr && <p className="aios-wf__err">{agentsErr}</p>}

          <p className="aios-wf__group">可运行 Agent（specs）</p>
          {specs.map(renderSpecCard)}
          {!specs.length && <p className="aios-workflows__hint">（无 spec 或 catalog 加载中）</p>}

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
                需求描述（AI 填充：一句话说明要什么样的 agent）
                <textarea
                  rows={2}
                  value={suggestBrief}
                  onChange={(e) => setSuggestBrief(e.target.value)}
                  placeholder="如：盯 arXiv 上 LLM 推理方向的新论文，挑重点摘要给我"
                />
              </label>
              <div className="aios-agent__actions">
                <button
                  className="aios-topbar__btn"
                  type="button"
                  onClick={doSuggest}
                  disabled={suggestBusy || !suggestBrief.trim()}
                >
                  {suggestBusy ? "生成中…（约 10-40s）" : "AI 填充"}
                </button>
              </div>
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
                工具（可选，逗号分隔；须在工具池内）
                <input
                  type="text"
                  value={declForm.tools}
                  onChange={(e) => setDeclForm((f) => ({ ...f, tools: e.target.value }))}
                  placeholder="如 vault_search, web_fetch（留空=无工具）"
                  list="tools-available"
                />
                <small className="aios-wf__arghint">
                  可用：{(agents?.tools_available ?? []).join(" / ") || "（加载中）"}
                </small>
              </label>
              <datalist id="tools-available">
                {(agents?.tools_available ?? []).map((t) => (
                  <option key={t} value={t} />
                ))}
              </datalist>
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
                    {(d.tools ?? []).map((t) => (
                      <span className="aios-agent__chip" key={t}>{`工具 · ${t}`}</span>
                    ))}
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
                {g.registered_agents?.length ? (
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
