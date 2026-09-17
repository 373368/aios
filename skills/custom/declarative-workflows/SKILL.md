---
name: declarative-workflows
description: AI-OS 声明式三层工作流编排（YAML 声明 + wfengine 执行 + 原语 + LLM 判断点）。凡是创建/执行/扩展声明式工作流（如 digest-daily），或用户提到工作流、YAML 编排、wfengine、判断点、InvokePrimitive、InvokeLLM、声明式，都必须先用本 skill。关键词：workflow, 工作流, 声明式, 编排, wfengine, 判断点, YAML
---

# Declarative Workflows — 声明式三层工作流编排

## 定位

AI-OS 运行治理的**约定面**。把「特定场景多原语编排」写成 YAML 声明，由 `wfengine.py` 执行：**工作流 = YAML 声明（编排）→ 原语（确定性执行）→ LLM 判断点（仅判断）**；复杂任务以 **agent 图**（agentgraph，LangGraph）承担，经 InvokeAgent 嵌套调用。对齐微软 Agent Framework Declarative Workflows 1.0 范式。

体系三层（原语 / 工作流 / agent 图）：
- **原语**：确定性执行，无 LLM（`scripts/primitives.py` 写操作 / 独立脚本 / MCP / 标准库，均属此）
- **工作流**：YAML 声明式多原语编排（本 skill），由 wfengine 执行，管锁/日志/退出码；可含单轮判断点与 agent 节点
- **agent 图**：agentgraph 声明图——LLM 工具回路 / 多身份并行 / 身份声明；节点可回落原语（图式统一）
- **LLM 判断点**（工作流内组件）：只做判断（价值/主题/分类/分支），经 `modelz.chat` 直调判断模型，结果决定工作流分支

载体选型：新工作流默认 YAML 声明式；ps1/py 编排壳仅在需要原生进程控制（细粒度锁/平台 API）时保留。

## 文件位置

| 组件 | 路径 |
|---|---|
| 引擎 | `<repo>\l2-memory\workflows\wfengine.py` |
| 工作流 YAML | `<repo>\l2-memory\workflows\*.yaml` |
| 判断点 prompt | `<repo>\l2-memory\workflows\prompts\*_judge.txt` |
| 写操作原语库 | `<repo>\l2-memory\scripts\primitives.py` |
| 模型适配 | `<repo>\l2-memory\scripts\modelz.py`（default=opencode/zhipuai/glm-4.7-flash；judge_default=opencode-go/deepseek-v4.1-flash 判断点直调） |
| 公共层 | `<repo>\l2-memory\scripts\common.py`（run_py/run_capture/log/锁/退出码） |
| agent 图运行时 | `<repo>\l2-memory\agentgraph\agentgraph.py`（LangGraph 声明式并行 agents） |
| agent spec | `<repo>\l2-memory\agentgraph\specs\*.yaml` |
| agent 身份声明 | `<repo>\l2-memory\agentgraph\declarations\*.md`（正文=人设/规范/提示词 → system；frontmatter 可选 name/description/model/tools/**skills**——`skills: [<名>...]` 内联 `skills/custom/<名>/SKILL.md` 全文为「随附技能」小节，缺失仅告警） |
| agent 工具池 | `<repo>\l2-memory\agentgraph\tools.py`（vault_search / arxiv_search / web_fetch 内置；节点 `tools:` 回路，声明可设白名单） |
| 工具注册表 | `<repo>\l2-memory\agentgraph\tools_registry.yaml`（扩展工具声明：kind=http/script/plugin；`register_tool` 原语写入 + smoke 自检；动态合并进 TOOLS） |
| 工具草案 | `<repo>\l2-memory\agentgraph\drafts\*.tool.json`（tool-scout 产出；`adopt_tool_draft` 采纳后改名 `*.adopted.json` 留痕） |
| 体检脚本 | `<repo>\l2-memory\scripts\diagnostics.py`（`--mode quick\|ping`；环境/配置/引擎自检/模型连通；控制台设置页「体检」的后端） |

## 执行命令

```powershell
python <repo>\l2-memory\workflows\wfengine.py <workflow.yaml> [key=value ...]
```

- **digest-daily**（记忆沉淀）：`... digest-daily.yaml`（**预览用 `dry_run=true`**，拦截全部写/标记动作，只跑判断）
- **research**（主题调研）：`... research.yaml topic="<主题>"`（InvokeAgent → research-agent 图：工具回路检索取证 → 成稿 → 写库，笔记入 vault）
- **tool-scout**（工具侦察·源搜索三源）：`... tool-scout.yaml brief="<需求>" [url=<参考网址>]`（本地盘点 + GitHub + 指定网址 → 候选清单 + 注册条目草案落盘 `agentgraph/drafts/`；采纳走 `adopt_tool_draft` 原语——校验 + smoke 通过才进注册表）
- **agent-forge**（身份工厂，机读入口）：`... agent-forge.yaml plan=<清单 JSON 或文件路径>`（批量声明身份；同名跳过逐项报告；`dry_run=true` 预览）
- **agent-draft**（身份草拟，spec）：由 `python wfctl.py agents-suggest --brief "<文本>"` 调用（brief → 建议 name/description/model/tools/body；只读不落盘，提交仍走 agents-declare 严格校验）
- **demo-hello**（演示）：`... demo-hello.yaml [name=世界]`（最小链路开箱样例：SetVariable 默认链 → InvokeLLM（judge 直连）→ 结果经 `outputs:` 回显；无外部依赖）
- **体检**（非工作流，直跑脚本）：`python <repo>\l2-memory\scripts\diagnostics.py --mode quick`（或 `--mode ping` 追加模型连通）——退出码 0=全过（warn 不拦）
- 自带冒烟示例：`wf-selfcheck.yaml`（引擎自检）/ `wf-test-judge.yaml`（判断点单测）/ `wf-test-source.yaml`（自定义 API 源 + `$ENV` key 引用）

**契约**：统一入口（触发器只认 `wfengine.py <yaml> [k=v]`）+ 退出码 0=成功 / 非 0=失败 + 运行日志追加 `<vault>\03-日志\wfengine.log` 与 `<工作流名>.log`。并发防重入用 `common.SingleLock`（`main_entry` 封装，锁冲突退出码 3）。

## 工作流 Schema

```yaml
kind: Workflow
metadata: {name, description, version}
                                          # 可选 metadata.ui_hidden: true — 机读任务不上面板（catalog 过滤；CLI 照常）
trigger: {kind: OnCommand, command: archive, required: [source]}
                                               # 声明入口（OnCommand）；required=必填槽（wfctl trigger 预检，缺参 exit 2 不启动引擎）
                                               # 可选 arguments: [{name, type, hint, required, options}] — 详情页表单元数据（type=text|longtext|bool|select）
variables:                                     # 顶部变量，可被 actions 引用
  source: =System.Args.source
outputs: [字段名, ...]                          # 可选：完成后向 stdout 回显 {字段: Local 值}（控制台结果面板；demo-hello 示范）
model: =System.Args.model   # 可选：本工作流默认 LLM 源（缺省 =System.JudgeModel）
sources:                    # 可选：自定义 API 源（合并进 config.json models.providers；同名逐字段覆盖）
  my-source:
    kind: openai            # openai 直调 | opencode 经本地 server
    base: https://api.example.com/v1
    api_key: $ENV:MY_API_KEY  # 只接受 $ENV:VAR 引用（工作流文件可共享/入库，禁明文）
    models: [model-a]
actions:                                       # 顺序执行；每个动作可带 when / id
  - kind: ...
```

## 动作类型

| kind | 作用 | 关键字段 |
|---|---|---|
| `InvokePrimitive` | 调原语（确定性执行） | `primitive`（原语名）、`args`（JSON）、可选 `via: primitives`、`output` |
| `InvokeAgent` | 调 agent 图（LangGraph，声明式并行） | `spec`（相对 workflows/ 或绝对）、`input`（表达式字典）、`output`、可选 `expects`（产出契约） |
| `InvokeLLM` | LLM 判断点 | `prompt_template`（prompts/<名>.txt，`{content}` 注入 `input`）、`model`（缺省 =System.WorkflowModel→JudgeModel）、`json_output: true`、`output` |
| `ConditionGroup` | 分支路由 | `conditions: [{when, actions:[...]}]`，首个命中执行并 break |
| `Loop` | 遍历 | `over`（列表表达式）、`actions`；当前项 = `=Loop.Item` |
| `SetVariable` | 写局部变量 | `var`、`value`（支持 `{var}` 内嵌 + =引用求值） |

所有动作可带顶层 `when:` 做条件跳过（如 digest 的 `when: =System.Args.dry_run != "true"`）。

## 表达式（= 前缀，对齐 Power Fx）

- **作用域**：`=System.Args.<k>`（CLI 参数）/ `=System.JudgeModel`、`=System.DefaultModel`、`=System.WorkflowModel`（工作流级默认 LLM 源，由顶层 `model:` 覆盖）、`=System.MemRoot`、`=System.MemVaultRoot`、`=System.KbRoot` / `=Local.<var>`（动作间变量）/ `=Loop.Item`、`=Loop.Item.<field>`、`=Loop.Item[<i>]`
- **比较运算**：`=Local.Verdict.branch == "new"`（== != >= <= > <，右侧引号字符串或数字）→ 布尔
- **内嵌替换**：`{LocalVar}` 在 primitive 名/路径等字符串字段中被替换为局部变量值（反斜杠转 `/`）
- **字面量**：不以 = 开头的字符串原样传递

## 原语调用两种形态

1. **`via: primitives`**（推荐，写操作）：`python primitives.py <name> '<json args>'`，参数命名、JSON 序列化结果。
   ```yaml
   - kind: InvokePrimitive
     via: primitives
     primitive: write_kb_page
     args: {title: =Local.Verdict.title, skeleton: =Local.Verdict.skeleton, subdir: =Local.Verdict.subdir, body: =Local.Verdict.body}
   ```
2. **独立脚本**（默认）：`python <script> --key value`（布尔 True→`--flag`，False→跳过该参数）。

`output` 捕获：`=Local.X` 简写直接存；`{var: expr}` 字典按表达式映射。原语 stdout 为 JSON 时自动解析（`args.json: true` 或 `via: primitives`）。

## Agent 调用契约（InvokeAgent）

agent 图 = `<repo>\l2-memory\agentgraph\`（YAML spec → LangGraph StateGraph，声明式并行；节点类型 llm / primitive）。
工作流经 `InvokeAgent` 子进程调用，契约与 Unix 对齐：

- **argv**：`agentgraph.py run <spec> --json --input k=v ...`
- **stdout = 纯 JSON**（agent 最终状态）；**stderr = 日志**；**exit**：0 成功 / 1 spec 或执行错误
- spec 路径相对 `workflows/` 目录（或绝对路径）；input 值为字符串或 JSON 序列化
- output 捕获与 InvokePrimitive 同构（`=Local.X` 简写 / 字典映射）
- 产出契约：agent spec 声明 `outputs`；调用方可声明 `expects`（缺失/空值 → 报错，不静默）
- 身份声明：llm 节点可绑 `declaration: <md>`（相对 spec 目录；正文=人设/规范/提示词 → system prompt）；多份声明 fan-out = 多身份并行（同底座）；模型优先级 声明 > 节点 > spec
- 输入元数据（推荐）：spec 顶层 `inputs: [{name, type, hint, required, options}]` — 控制台详情页表单与 run-agent 必填预检共用
- 工具回路：llm 节点 `tools: [name, ...]` 声明可用工具（白名单=TOOLS）；模型自行决定调用次数与顺序（≤6 轮），每次调用记入 trace
- loopx 协作接入：`python goalrun.py run "<task>" --spec <spec> --agent-id <身份> [--task-key <字段>] [--dry-run]`（custom-runner 契约：user_gate preflight→todo→quota→agentgraph→complete；桥接层 `loopx_bridge.py`；存在未解除的 user_gate 且阻塞本身份时直接拒绝执行）
- 离线校验：`python agentgraph.py check <spec>`（编译图 + 校验模型/声明引用，不调 LLM）

```yaml
- kind: InvokeAgent
  id: analysts
  spec: ../agentgraph/specs/parallel-analysts.yaml
  input: {topic: =Local.topic}
  output: =Local.Analysis
  expects: [findings, report]
```

## 原语扩展约定

新增原语（确定性能力单元）必须满足：

1. **接口**：命名 `<动词>_<对象>`；单入口（CLI 或库函数，宿主无关）；入参出参结构化（JSON 可描述）
2. **幂等**：重复执行不产生副作用；写入类必须可安全重跑
3. **可测试**：附自检/回归（非平凡逻辑留一个可运行检查）
4. **配置注入**：provider/model/key 走 config/环境变量，不写死
5. **可拔插**：可变面独立成数据表（如分类判据表），改动不动核心逻辑
6. **注册**：进 `primitives.py` CLI 分发表；跨 ≥2 工作流复用的才提取为独立原语
7. **失败可见**：异常不静默（写错误日志），批量场景单条隔离不杀全量

现有原语速览：`scripts/primitives.py`（写 KB/记忆/日志/skill/permission）+ `scripts/`（索引/检索/分类 SDK）+ `tasks/`（扫描/切片/fetch_*，stdout JSON）。

## 判断点规范

- prompt 模板存 `workflows/prompts/<name>_judge.txt`，末尾用 `{content}` 占位输入
- 输出**严格 JSON**（`json_output: true` 自动抽取）：必须含 `branch` 字段，工作流用 ConditionGroup 按 branch 路由
- 判断模型默认 `=System.JudgeModel`（judge_default），走 **openai 直调**（kind=openai），**不经 opencode agent 会话**（prompt_async 进 agent 循环会返回空）
- 骨架白名单必须与 `primitives.py` 的 SKELETONS 一致（AI与机器学习/编程开发/数学/计算机基础/物理/医疗/学习/生活/娱乐/学术前沿）

现有判断点：`digest_judge`（memory|kb|todo）。

## 工作流发现与触发（wfctl）

`l2-memory/workflows/wfctl.py` 是面向 agent / UI 的统一桥接：

| 接口 | 命令 | 输出 |
|---|---|---|
| 发现 | `python wfctl.py list` | 扫描 `workflows/*.yaml` 编目（name/description/version/command/args/path） |
| 监控 | `python wfctl.py status <wf>` | 读运行日志判状态（state/last/lines） |
| 渲染 | `python wfctl.py render <wf>` | 结构化状态 JSON（给 UI） |
| 触发 | `python wfctl.py trigger <wf> <k=v...>` | 调 wfengine 同步执行，透传退出码；必填槽缺失 exit 2 且不启动引擎 |
| 能力目录 | `python wfctl.py catalog` | workflows（arguments/invokes）+ agents specs（inputs/declarations/invoked_by）；过滤 `ui_hidden` 工作流与 `*-smoke` spec；附漂移检查 `metadata_warnings` |
| 直跑 spec | `python wfctl.py run-agent <spec> <k=v...>` | 必填输入预检 exit 2 → `agentgraph run --json`；single-flight 锁（已有运行 exit 3）；stdout/退出码透传 |
| AI 填充 | `python wfctl.py agents-suggest --brief <文本>` | brief → 身份草案建议（name/description/model/tools/body；只读不落盘） |
| 体检 | `python <repo>\l2-memory\scripts\diagnostics.py --mode quick\|ping` | 环境/配置/引擎自检（+模型连通）统一入口；控制台设置页「体检」后端（JSON：items[]/summary） |
| 身份清单 | `python wfctl.py agents` | 身份声明（`agentgraph/declarations`）+ 各 goal 注册状态（JSON） |
| 注册身份 | `python wfctl.py agents-register --agent-id <a[,b...]> --goal-id <g> [--execute]` | 加入 goal 协作名单（缺省预览；loopx 侧要求 goal 已存在；逗号串需拆为重复参数） |
| 移除身份 | `python wfctl.py agents-unregister --agent-id <a[,b...]> --goal-id <g> [--execute]` | 从 goal 名单移除（configure-goal 名单替换语义 + 全局同步） |
| 新建身份 | `python wfctl.py agents-declare --name <slug> [--description ..] [--model ..] [--tools a,b] [--body ..]` | 新建声明 `declarations/<name>.md`（tools ⊆ 工具池；同名拒绝；薄壳 → `primitives.declare_agent` 原语） |

agent 使用路径：`list`/`catalog` 发现 → `status`/`render` 监控 → `trigger` / `run-agent` 执行；身份管理走 `agents*`（配合 loopx goal 协作名单）。

## 新增工作流流程

1. 定链路：原语编排序列 + 判断点位置（一个工作流一般 1 个判断点 + 1 个 ConditionGroup 路由）
2. 写 YAML：复用 `InvokePrimitive / InvokeAgent / InvokeLLM / ConditionGroup / Loop / SetVariable`，参考 digest-daily.yaml 结构
3. 写判断点 prompt 模板（`prompts/<name>_judge.txt`，输出 JSON 含 branch）
4. 新原语时：实现 → 幂等 → 附自检/回归 → 注册进 `primitives.py` CLI 分发表
5. 验证：先用 `dry_run` 或小样本跑通；参考 `wf-selfcheck.yaml` / `wf-test-judge.yaml` / `wf-test-source.yaml`（自定义 API 源 + $ENV key 引用）

## 坑（来自实测）

- **PowerShell 给 python CLI 传 JSON 引号转义必炸**（JSONDecodeError）→ 引擎内 subprocess 传 argv 数组无此问题；**手动验证用 python 直接 import 调函数**，别拼命令行 JSON
- **dry_run 拦截**：写/标记原语必须带 `when: =System.Args.dry_run != "true"`（digest-daily 已示范），否则预览即真写
- **缺参 fail fast**：`=System.Args.x` 缺失时求值为 `{}`；InvokeAgent / InvokeLLM 的空对象输入会直接报错终止（不会把 `"{}"` 喂给 LLM）——触发前以 k=v 传参，或在 variables 给默认值
- **提示词禁用花括号字面量**：模板校验正则匹配 `{词}`（含中文）→ 示例里写 `{参数}` 会被误判为占位符；用尖括号演示
- **工作流 YAML 禁明文 api_key**：`sources.*.api_key` 只接受 `$ENV:VAR_NAME` 引用（加载时 validate_yaml_sources 拦截明文）；密钥放环境变量或本机 config.json（.gitignore 已排除）。非本地 openai 源缺 key → resolve 直接报错
- 中文乱码是 PowerShell 控制台显示问题，脚本输出字节是 UTF-8，以 `sys.stdout.reconfigure(encoding="utf-8")` 后为准

## 验收

- [ ] `wfengine.py <yaml> [k=v]` 退出码 0，`03-日志/wfengine.log` 有记录
- [ ] digest-daily 可执行（`dry_run=true` 预览不落盘）；`wf-selfcheck.yaml` 跑通
- [ ] `wfctl.py catalog` 输出 workflows + agents（inputs/invokes/ui_hidden 过滤）；`run-agent` 直跑冒烟 spec exit 0
- [ ] 体检全绿：`python <repo>\l2-memory\scripts\diagnostics.py --mode quick`（exit 0；warn 允许）
- [ ] 工具工厂闭环：`tool-scout` 产出草案 → `adopt_tool_draft` 采纳（smoke 过）→ 新进程 TOOLS 含该工具
- [ ] 新增工作流遵循本 schema，判断点输出 JSON 含 branch 且骨架白名单一致
- [ ] 写操作全走 primitives（skill 内嵌命令形态已消除）
- [ ] agent 协作链路：`python test_invoke_agent.py` 通过；`python agentgraph\test_agentgraph_script.py` 通过（离线）