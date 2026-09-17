# agentgraph — LangGraph 声明式并行 agents

YAML 声明 agent 图（节点/边/状态/模型/身份声明）→ 编译为 LangGraph StateGraph 执行。定位：AI-OS 三层（声明 → 原语 → LLM）中「agent 粒度」的声明式运行时。

## 命令

```powershell
python agentgraph.py check specs\script-smoke.yaml          # 离线：校验 + 编译（不调 LLM）
python agentgraph.py graph specs\parallel-analysts.yaml     # 打印 mermaid 拓扑
python agentgraph.py run   specs\parallel-analysts.yaml --input topic="..." [--json]
```

## Spec Schema

```yaml
kind: AgentGraph
metadata: {name, description}
model: volcengine-agent-plan/deepseek-v4-flash   # llm 节点默认模型（config.json 引用，仅 openai 兼容来源）
trace: true                                      # 可选：节点起止时间记入 state.trace
outputs: [findings, report]                      # 对外产出契约：check 校验（存在于 state 且被节点写入）
state:                                           # 状态字段（LangGraph channel）
  topic: {type: str}
  findings: {type: list, reducer: add}           # add=并行写入合并；缺省 last-write-wins
nodes:
  - id: tech                                     # 唯一 id
    kind: llm                                    # 缺省
    declaration: ../declarations/tech-analyst.md # 可选：身份声明文档（见下节）
    tools: [vault_search, web_fetch]             # 可选：模型自主调用的工具（注册表 tools.py）
    prompt: "针对 {topic} 给出 3 条要点"           # 任务指令；{state字段} 渲染
    output: findings                             # 写回 state 字段
  - id: probe
    kind: primitive                              # 调确定性脚本原语
    primitive: wfprobe                           # scripts/ 或 tasks/（自动补 .py）；绝对路径亦可
    args: ["hello", "{topic}"]                   # argv；字符串做 {state字段} 渲染
    json: true                                   # stdout 按 JSON 解析（否则原样字符串）
    output: probe
edges:                                           # 多出边=并行 fan-out；多入边=自动 join
  - [START, tech]
  - [tech, synthesis]
  - [synthesis, END]
```

## Agent 声明（身份文档）

llm 节点绑定 `declaration: <md>` 后，该节点 = **一个声明身份**：文档正文作为 system prompt（人设 / 运行规范 / 专用提示词）。同一 spec（同底座）+ 多份声明（不同身份）+ fan-out = 多身份并行协作（见 `specs/parallel-analysts.yaml`：技术/风险/应用/主编）。

```markdown
---
name: tech-analyst                # 身份名（trace.agent 记录用）
description: 技术分析师            # 说明，仅供人读
model: volcengine-agent-plan/deepseek-v4-flash  # 可选：优先于节点/spec 模型
tools: [vault_search]             # 可选：身份工具白名单（节点 tools 须 ⊆ 本列表）
---

你是一名资深技术分析师……（正文即 system prompt，静态文本）
```

- 格式：Markdown；frontmatter 可选（兼容 opencode 风格 agent 定义，其余字段忽略）；正文为静态文本（不做 `{字段}` 渲染）
- 路径：相对 spec 文件目录或绝对路径；`check` 校验存在与可解析（空正文 / 未闭合 frontmatter → 报错）
- 技能（可选）：frontmatter `skills: [<名>...]` → 加载 `skills/custom/<名>/SKILL.md` 全文（去 frontmatter）追加为「## 随附技能：<名>」小节；单一事实源，缺失仅 stderr 告警——身份声明按需内联技能（如 `aios-quickstart` 上手指南）
- 模型优先级：声明 `model` > 节点 `model` > spec `model` > config 默认
- 工具白名单：声明 frontmatter `tools:` 可选；节点 `tools` 超出声明范围 → 加载期报错
- 示例：`declarations/`（tech-analyst / risk-analyst / use-analyst / editor）

## 工具（tools）

llm 节点声明 `tools: [name, ...]` 后，模型自行决定调用次数与顺序（有界循环 ≤6 轮，超出报错）；每次调用以 `<节点>.<工具>` 记入 trace。

| 工具 | 作用 |
|---|---|
| `vault_search(query, k=5)` | 本地知识库检索（薄适配 search_index --json） |
| `arxiv_search(query)` | arXiv 最新论文（薄适配 fetch_arxiv） |
| `web_fetch(url, max_chars=4000)` | 网页抓取 → 正文纯文本 |

**扩展工具（工具工厂）**：`tools_registry.yaml` —— 统一声明式接口，多 kind（`http` 声明式 HTTP 适配 / `script` 声明式脚本包装 / `plugin` Python 插件引用；`mcp` 桥接 V1.1）。写入方式：`primitives.py register_tool` 原语（校验 + 同名拒绝 + 注册即 smoke 契约自检；CLI：`python primitives.py register_tool '<json>'`），手改亦可（加载期逐条校验，坏条目不阻塞内置工具）。

```yaml
tools:
  - name: wttr_weather
    kind: http
    description: 查询指定城市当前天气（免密钥）
    config: {url: "https://wttr.in/{location}?format=j1", method: GET,
             params: [location], rows: {from: current_condition, fields: [temp_C, humidity]}}
    smoke: {args: {location: Beijing}}
```

- 注册表：`tools.py`（内置） + `tools_registry.yaml`（扩展，动态合并进 TOOLS 白名单）；`plugins/local_time.py` = plugin kind 参考实现
- 返回契约：成功=文本；失败=`ERROR:` 前缀（模型可换路）；单次上限 6000 字符
- 冒烟：`python agentgraph.py run specs\tool-smoke.yaml --input topic="记忆引擎检索" --json`（真模型 + 真工具，~6s）
- 源搜索（本地/GitHub/指定网址 → 注册草案）：`python workflows\wfengine.py workflows\tool-scout.yaml brief="..." [url=...]`；草案自动落盘 `drafts/<name>.tool.json`（同名跳过），采纳 = `primitives.py adopt_tool_draft`（校验+smoke → 改名 `*.adopted.json` 留痕）

## 对外契约

- `run --json`：stdout = 纯 JSON（最终 state）/ stderr = 日志 / exit 0=成功、1=错误
- 被工作流调用：wfengine `InvokeAgent`（契约见 declarative-workflows skill）
- 接入 loopx 协作：`workflows/goalrun.py run "<task>" --spec <本 spec> --agent-id <身份>`（custom-runner 契约）
- 失败不静默：原语退出码≠0、输出非 JSON、未知字段/节点/边、声明缺失 → 报错带上下文
- 产出契约：spec `outputs` 声明 ←→ 消费侧 `expects` 校验（缺失/空值 → 报错）
- 离线防线：`check` 覆盖 spec 校验 + 图编译 + 模型/原语/声明引用解析

## 验证

```powershell
python test_agentgraph_script.py                 # 原语链路 + 声明身份，离线秒级
cd ..\workflows; python test_invoke_agent.py     # workflow→agent，真实 LLM（~20s）
```
