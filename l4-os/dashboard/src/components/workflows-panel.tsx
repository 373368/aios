import { useCallback, useEffect, useState } from "react";

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

/**
 * 工作流面板：wfctl 四接口（list/render/status/trigger）监控与触发。
 * 经壳 AiosShell /wfctl 代理调 wfctl.py。
 */
/** 常用参数说明（纯前端提示，不涉及数据；布尔类给固定选项下拉） */
const ARG_HINTS: Record<string, { hint: string; options?: string[] }> = {
  source: { hint: "源目录路径，默认走收件箱" },
  skip_export: { hint: "是否跳过导出", options: ["", "true", "false"] },
  query: { hint: "检索关键词，留空全量" },
};

export function WorkflowsPanel() {
  const [items, setItems] = useState<WfItem[]>([]);
  const [renders, setRenders] = useState<Record<string, RenderState>>({});
  const [running, setRunning] = useState<string | null>(null);
  const [lastOut, setLastOut] = useState<Record<string, string>>({});
  const [loadErr, setLoadErr] = useState("");
  const [argsVal, setArgsVal] = useState<Record<string, Record<string, string>>>({});

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

  useEffect(() => {
    load();
  }, [load]);

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

  return (
    <div className="aios-workflows">
      <div className="aios-wf__bar">
        <span className="aios-wf__title">工作流</span>
        <button className="aios-topbar__btn" onClick={load} aria-label="刷新">
          刷新
        </button>
      </div>

      {loadErr && <p className="aios-wf__err">{loadErr}</p>}

      {items.length === 0 && !loadErr && <p className="aios-workflows__hint">无可用工作流。</p>}

      {items.map((it) => (
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
      ))}
    </div>
  );
}
