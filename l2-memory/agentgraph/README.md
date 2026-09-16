# agentgraph — LangGraph 声明式并行 agents

YAML 声明 agent 图 → 编译为 LangGraph StateGraph 执行。定位：AI-OS 三层（声明 → 原语 → LLM）中「agent 粒度」的声明式运行时。

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
    kind: llm                                    # 缺省；prompt 里 {state字段} 渲染
    prompt: "针对 {topic} 给出 3 条要点"
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

## 对外契约

- `run --json`：stdout = 纯 JSON（最终 state）/ stderr = 日志 / exit 0=成功、1=错误
- 被工作流调用：wfengine `InvokeAgent`（契约见 declarative-workflows skill）
- 失败不静默：原语退出码≠0、输出非 JSON、未知字段/节点/边 → 报错带上下文
- 产出契约：spec `outputs` 声明 ←→ 消费侧 `expects` 校验（缺失/空值 → 报错）
- 离线防线：`check` 覆盖 spec 校验 + 图编译 + 模型/原语引用解析

## 验证

```powershell
python test_agentgraph_script.py                 # 原语链路，离线秒级
cd ..\workflows; python test_invoke_agent.py     # workflow→agent，真实 LLM（~20s）
```
