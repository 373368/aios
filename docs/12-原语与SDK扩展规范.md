# 原语与 SDK 扩展规范

> 定位：AI-OS 能力体系（原语/工作流/SDK 三层）的原语目录 + 扩展约定。
> 依据：2026-08-22 运行治理统一讨论（原语 = 工具统一体 / 工作流 = 原语编排 / SDK = LLM 参与的整合监控层）。
> 原则：**原语 = 工具（同一事物两个视角名词，确定性执行、无 LLM）；工作流 = 特定场景多原语调用的编排（锁/日志/退出码）；SDK = 需要 LLM 直接参与/监控的高层整合层（控制管理工作流、多工作流整合、错误/意外处理、高层次复杂处理），是直接交给核心 agents 的运行元件。LLM 只在判断点出现，执行永远走原语。**

## 1. 体系三层（原语 / 工作流 / agent 图）

> v2（2026-09-16）：原「SDK 整合监控层」从未实体化，由 **agent 层（agentgraph）** 取代并入三层；「SDK 服务化面」保留为跨 agent 注册/调用面（§5.5）。

```
[agent 层] agentgraph 声明图（LangGraph）：LLM 工具回路 / 多身份 fan-out·join / 身份声明
   │  被工作流以 InvokeAgent 嵌套调用；节点可回落原语（图统一）
   ▼ 嵌套调用
[工作流层] wfengine YAML：固定编排（顺序/分支/循环）+ 判断点（单轮直调）
   │  动作 = InvokePrimitive / InvokeAgent / InvokeLLM / ConditionGroup / Loop / SetVariable
   ▼ 调用
[原语层]（= 工具统一体）← 本规范：原语目录 + 扩展约定
   │ 确定性执行，无 LLM（标准库 / MCP / 脚本 / primitives.py 均属此）
   ▼
资源层（vault / 索引 / 导出）
```

> **原语与工具统一**：工具 = 原语，同一事物两个视角名词（宿主视角称工具，能力目录视角称原语），不存在「凌驾于工具之上的独立原语层」。标准库、MCP、CLI 脚本、primitives.py 业务函数全部归原语层。

| 层 | 规范 | 内容 | 状态 |
|---|---|---|---|
| **agent** | **本规范 §1** + `agentgraph/README.md` | agentgraph 声明图（LangGraph）：工具回路 / 多身份 fan-out / 身份声明 / outputs·expects 契约 | ✅ 4 身份 · 工具池 v1 · InvokeAgent 接入 · loopx goalrun 真跑 |
| 工作流 | 工作流规范（05-工作流规范.md） | **声明式 YAML 编排（wfengine 执行）** + 统一入口契约 + 触发层 + 单实例锁 + 退出码 | ✅ 3 工作流 + InvokeAgent |
| **原语** | **本规范** | 原语（工具统一体）目录 + 原子/幂等/可拔插/回归测试约定 | 📄 本文件 |

**声明式形态（2026-08-23 定案；09-16 扩展 agent 层）**：工作流以 YAML 声明（`l2-memory/workflows/*.yaml`），由 `wfengine.py` 执行——动作 = InvokePrimitive / **InvokeAgent** / InvokeLLM / ConditionGroup / Loop / SetVariable，每个动作可带 `when` 条件；表达式用 `=` 前缀（=System.Args.x / =Local.x / =Loop.Item / 比较运算 / `{var}` 内嵌）；判断点 prompt 存 `workflows/prompts/*_judge.txt`，输出严格 JSON 含 `branch`，由 ConditionGroup 路由，经 modelz 直调（judge_default=opencode-go/deepseek-v4.1-flash）。agent 图以 `agentgraph/specs/*.yaml` 声明：节点 = llm（可带 `tools:` 工具回路，注册表 tools.py）/ primitive；身份 = `declarations/*.md`；产出 = outputs↔expects 契约。使用规范见 `declarative-workflows` skill（<repo>/skills\custom\declarative-workflows\）。

**图式统一（三层同构为图，节点可嵌套）**：原语 = 叶节点（确定性）；固定工作流 = 原语节点 + 判断节点（人写 YAML）；agent 图 = 原语节点 + LLM 节点（工具回路）+ 多身份 fan-out（spec，可并行）。嵌套双向成立：工作流节点可为 agent 图（InvokeAgent）↔ agent 图节点可为原语（primitive）。跨层不变量 = 契约对（stdout 纯 JSON / stderr 日志 / exit 状态；outputs↔expects）+ trace 可审计。唯一空缺：工作流→工作流（子工作流节点）暂未提供，真出现复用需求再补。

**选型规则**：从低往高，取第一个够用的层级——需单点判断 → 工作流判断点（InvokeLLM）；需工具/多步/多身份 → agent 图；需无人值守/跨 goal 协作 → loopx 协作面（正交于三层）。

**并行边界**：工作流层零并行（并行 = 协作语义）；agent 图内 fan-out = 步内并行；跨 agent 并行归 loopx。

**边界**：原语不写业务编排（那是工作流/agent 图）；工作流管固定确定编排（可含单轮判断与 agent 节点，不做并行）；agent 图管工具/多步/多身份，不承担跨 goal 调度（那是 loopx）。

## 2. 原语目录（现有能力单元）

> 从 archival / vault-digest / sys_classify 三个工作流提取的原子操作。命名 = 动词，接口 = 入参→出参，幂等 = 重复执行安全。

| 原语 | 接口（入参→出参） | 实现 | 归属工作流 | 幂等 |
|---|---|---|---|---|
| `scan_candidates` | 平台?→{candidates, empty, placeholder} | `tasks/scan_new.py` | archival | ✅ |
| `read_session_meta` | path→conversation_id | scan_new.py `session_cid` | archival | ✅ |
| `dedup_ids` | →已归档 id 集合（frontmatter ∪ 来源段） | scan_new.py `kb_ids` | archival/digest | ✅ |
| `chunk_big_session` | →分片（>60KB 切 chunks/） | `tasks/chunk_sessions.py` | archival | ✅ |
| `refresh_index` | --full?→索引 diff 更新落盘 | `scripts/build_index.py` | archival/digest | ✅ |
| `search_semantic` | 查询,top_k→{path,score}[] | `scripts/search_index.py --engine v1` | archival/digest/classify | ✅ |
| `write_kb_page` | 主题,骨架,frontmatter→写 05-知识 页 | `scripts/primitives.py` | archival/digest | ✅（同主题合并） |
| `write_memory_page` | 主题,内容→写 01-记忆 页（type: memory） | `scripts/primitives.py` | digest | ✅ |
| `mark_digested` | memory 文件→重命名 .digested.md | `scripts/primitives.py` | digest | ✅ |
| `append_behavior_log` | 事件→写 03-日志/行为记录 | `scripts/primitives.py` | archival | ✅ |
| `append_digest_log` | 动作→写 03-日志/digest-*.md（含 COMPLETED） | `scripts/primitives.py` | digest | ✅ |
| `classify_sys` | 页文本→{primary,raw,boosted,ambiguous,scores} | `scripts/sys_classify_sdk.py` | 分类固化 | ✅ |
| `extract_anchors` | 页文本→C1 锚点条款[] | sys_classify_sdk.py | 分类固化 | ✅ |
| `extract_harden` | 页文本→C2 硬化条款[] | sys_classify_sdk.py | 分类固化 | ✅ |
| `extract_skill_cands` | 页文本→C3 skill 候选[] | sys_classify_sdk.py | 分类固化 | ✅ |
| `fetch_arxiv` | 查询?→{source,items[]}（stdout JSON，零 LLM） | `tasks/fetch_arxiv.py` | H3 track | ✅ |
| `fetch_github` | 查询?→{source,items[]}（stdout JSON，零 LLM） | `tasks/fetch_github.py` | H3 track | ✅ |
| `fetch_journal` | 源?→{source,items[]}（stdout JSON，零 LLM） | `tasks/fetch_journal.py` | H3 track | ✅ |
| `append_kb_page` | 主题,骨架,子目录,addition→extend 已有页（幂等去重） | `scripts/primitives.py` | archive 四分支 | ✅ |
| `merge_kb_pages` | target,骨架,子目录,source_paths[]→合并多页（缺源 partial） | `scripts/primitives.py` | archive 四分支 | ✅ |
| `supersede_page` | 主题,骨架,子目录,superseded_by→标 falsify 替换 | `scripts/primitives.py` | archive 四分支 | ✅ |
| `write_skill` | name,description,body→写 SKILL.md（frontmatter+幂等） | `scripts/primitives.py` | C3 固化 | ✅ |
| `write_permission` | rules→写 opencode.jsonc permission（幂等） | `scripts/primitives.py` | C2 硬化 | ✅ |
| `list_memory` | mem_root?→[{name,path,size,modified}]（未 digested，跳 TODO.md） | `scripts/primitives.py` | digest | ✅ |
| `declare_agent` | name,description?,model?,tools?,body?,force?→写 `declarations/<name>.md`（tools⊆工具池，同名拒绝） | `scripts/primitives.py` | agent-forge/身份工厂 | ✅ |
| `declare_agents` | plan（JSON 文件/文本/对象）→批量声明 {results,written,skipped,errors} | `scripts/primitives.py` | agent-forge | ✅（同名跳过，逐项独立） |
| `register_tool` | entry{name,kind,description,config,smoke?}→校验+smoke → 追加 tools_registry.yaml | `scripts/primitives.py` | tool-scout/tool-forge | ✅（同名拒绝，force 覆盖） |
| `save_tool_drafts` | drafts[]（注册条目列表）→写 `agentgraph/drafts/<name>.tool.json`（{drafted_at, entry} 封套） | `scripts/primitives.py` | tool-scout | ✅（同名跳过） |
| `adopt_tool_draft` | path→register_tool（校验+smoke）→草案改名 *.adopted.json（留痕） | `scripts/primitives.py` | tool-scout | ✅（同名跳过） |
| `tool_inventory` | →{tools,scripts,tasks,skills}（本地可包装来源盘点） | `scripts/primitives.py` | tool-scout | ✅（纯读） |

## 3. 工作流 → 原语映射

### 3.1 archive-daily（AI 对话归档提炼，载体 = workflows/archive-daily.yaml）
```
fetch(export_{source},可选) → scan_new → (每会话 Loop) LLM 判断点 archive_judge
  → ConditionGroup 四分支（new→write_kb_page / extend→append_kb_page / merge→merge_kb_pages / falsify→supersede_page）
  → build_index → append_behavior_log
```
原语：9 个（fetch/scan/write/append/merge/supersede/index/log）+ 1 判断点

### 3.2 digest-daily（记忆沉淀，载体 = workflows/digest-daily.yaml）
```
list_memory → (每条 Loop) LLM 判断点 digest_judge
  → ConditionGroup 三分支（memory→write_memory_page / kb→write_kb_page / todo→跳过）
  → mark_digested → build_index → append_behavior_log
  全部写/标记动作带 when: dry_run != "true"（预览拦截）
```
原语：4 个（list/write/mark/index）+ 1 判断点

### 3.3 sys_classify（06-系统分类固化）
```
classify_sys → (按类) extract_anchors | extract_harden | extract_skill_cands
  → LLM 判断点：确认候选 → 落盘（AGENTS 锚点 / permission / SKILL.md / 索引）
```
原语：4 个（classify + 3 extract）+ 1 判断点

### 3.4 track-daily（学术前沿追踪，载体 = workflows/track-daily.yaml）
```
fetch_{source}（按 Source 分发，纯编排壳只选一个）→ Loop
  → LLM 判断点 track_judge → ConditionGroup（keep→write_kb_page 学术前沿 / skip→忽略）
  → build_index
```
原语：3 个（fetch_* 按源）+ 1 判断点。track-*.ps1 = 纯编排壳（锁/日志/退出码），无业务逻辑。

### 3.5 research（主题调研，载体 = workflows/research.yaml）
```
topic（CLI 变量）→ InvokeAgent（agent 层 research-agent 图）
  → research（工具回路：vault_search/arxiv_search/web_fetch）→ compose（严格 JSON 成稿）
  → write（primitive 节点 → write_kb_page）→ expects [note, write_result]
```
原语：1 个（write_kb_page，经图内 primitive 节点）+ 0 判断点（LLM 在图内）。首个 L2→L3→L1 三层嵌套工作流（2026-09-16）。

### 3.6 共享面（跨工作流复用）
| 原语 | 复用场景 |
|---|---|
| `refresh_index` | 所有「写入后必须检索可见」的工作流 |
| `search_semantic` | 所有「去重/关联判断」 |
| `write_kb_page` | archival + digest 共用写页模板 |
| `dedup_ids` | archival 去重游标 + digest 归档判重 |

### 3.7 agent-forge（身份工厂，载体 = workflows/agent-forge.yaml）
```
plan（清单 JSON：文件路径/文本/对象）→ declare_agents（批量原语：逐项校验 name + tools⊆工具池
  → 写 declarations/<name>.md，同名跳过；单项失败记 error 不中断）
  → 有效写入时写行为记录「身份工厂」
  写动作带 when: dry_run != "true"（预览拦截）
```
原语：1 个（declare_agents，内部复用 declare_agent）+ 0 判断点。生成态=清单 → 固化态=declarations/*.md；UI「新建身份」= wfctl agents-declare（薄壳 → 原语）。2026-09-16 立。

### 3.8 tool-scout（工具侦察/源搜索，载体 = workflows/tool-scout.yaml）
```
brief（+可选 url）→ tool_inventory（本地盘点）→ InvokeAgent（tool-scout 图）
  → scout（工具回路：github_search/web_fetch/vault_search 检索三源候选）
  → draft（严格 JSON：注册条目草案 ≤2 个）
  → save_tool_drafts（草案落盘 agentgraph/drafts/，dry_run 门拦截）
```
原语：3 个（tool_inventory / save_tool_drafts / adopt_tool_draft）+ 0 判断点（LLM 在图内，工具选型师身份）。采纳闭环：`save_tool_drafts` 落盘（同名跳过、留 {drafted_at, entry} 封套）→ 人工/面板 `adopt_tool_draft`（register_tool 校验+smoke → 草案改名 *.adopted.json 留痕）；消费面 = agentgraph TOOLS 白名单（声明/规格 tools 校验自动扩展）。2026-09-17 立，同日补草案闭环。

## 4. SDK 扩展规范（新增原语的约定）

新增一个原语（能力单元）必须满足以下约束：

1. **接口契约**（与 05-工作流规范 §1 同精神）：
   - 命名：`<动词>_<对象>`（如 `scan_candidates`）
   - 单入口：一个原语 = 一个可调用函数（CLI 或库函数，宿主无关）
   - 入参出参明确，出参结构化（JSON schema 可描述）
2. **幂等**：重复执行不产生副作用（写入类原语必须可安全重跑）
3. **可测试**：附 `test_<原语>.py` 或并入回归（ponytail 规则：非平凡逻辑留一个可运行检查）
4. **复用本机配置**：provider/model/key 取当前会话/本机 config，不写死（model 字段 = 当前会话 model）
5. **可拔插**：参数/判据等可变面独立成数据表（如 CLAUSES），改动不动核心逻辑
6. **文档**：注册进本规范 §2 原语目录（名称/接口/归属/幂等），供工作流发现
7. **失败可见**：异常不静默（写入错误日志），批量场景单条隔离不杀全量

**新增原语的流程**：
```
识别原语（跨 ≥2 工作流复用 或 单工作流内确定性步骤）
  → 实现（脚本/库函数） → 附回归测试 → 注册 §2 目录 → 更新归属工作流映射
```

## 5. 与既有规范的关系

- **工作流规范（05）**：原语是工作流的「内部组件」；工作流入口契约（§1）面向触发器，原语接口面向工作流编排——层间不混淆
- **工具面（04 知识层设计 §3 / MCP）**：embedder/MCP 与 CLI 脚本同属原语层（工具统一体），原语内部可调裸工具
- **系统索引消费模型（06-系统索引 §1）**：原语的固化产物（锚点/硬化条款/skill 候选）由六类消费模型决定去向
- **agent 层与工作流**：工作流管固定编排（锁/日志/退出码），agent 图管复杂任务（工具/多步/多身份）；二者以 InvokeAgent 契约嵌套，互不写对方逻辑；跨 agent 调度归 loopx（§5.5 服务化面）

## 5.5 跨 agent 注册 / 发现 / 调用规范（SDK 服务化面）

> 定位：让任何接入的 agent（opencode/OpenScience/未来）都能**发现、监控、触发**已注册的工作流/工具/原语。规范化 = 定义并暴露「注册规范」本身（接口契约对 agent 透明可查），而非让每个 agent 看到每个具体插件。2026-09-05 定案。

**桥接层**：`<repo>/l2-memory\workflows\wfctl.py`（能力桥：工作流 + agent spec 统一目录/运行入口）：

| 接口 | 命令 | 作用 | 输出 |
|---|---|---|---|
| 发现 | `python wfctl.py list` | 扫描 workflows/*.yaml 编目 | JSON：name/description/version/command/args/path |
| 目录 | `python wfctl.py catalog` | 合并 workflows + agentgraph specs 能力目录 | JSON：workflows[]（arguments/invokes）+ agents[]（inputs/declarations/invoked_by）；过滤 ui_hidden 工作流与 *-smoke spec；漂移检查 → metadata_warnings |
| 监控 | `python wfctl.py status <wf>` | 读 03-日志/<wf>.log 判状态 | workflow/log/lines/last/state |
| 渲染 | `python wfctl.py render <wf>` | 结构化状态 JSON（给 UI） | name/log/total_lines/last_line/state |
| 触发 | `python wfctl.py trigger <wf> <k=v...>` | 绝对路径调 wfengine 同步跑 | 透传退出码 0/1 |
| 直跑 | `python wfctl.py run-agent <spec> <k=v...>` | 直跑 agentgraph spec（inputs.required 预检 → run --json；single-flight 锁，忙 exit 3） | 透传 stdout/退出码 |
| 建议 | `python wfctl.py agents-suggest --brief <文本>` | AI 填充：brief → 身份草案建议（agent-draft 图；工具池/模型清单自动注入；只读不落盘） | JSON：ok/suggestion{name,description,model,tools,body} |

**注册规范（新增工作流/原语必须满足，对齐 §4）**：
1. 工作流载体 = `workflows/<name>.yaml`（wfengine 声明式格式）
2. 触发 = `wfengine.py <name>.yaml <k=v...>`（System.Args，退出码 0/1）
3. 监控 = 运行日志写 `03-日志/<name>.log`（`[时间戳]` 行）
4. 发现 = 经 wfctl list 可编目（description 必须写清用途/参数）
5. agent 使用路径 = `wfctl list` 发现 → `wfctl status/render` 监控 → `wfctl trigger` 触发
6. **输入元数据（推荐，控制台详情页表单驱动）**：workflow 用 `trigger.arguments`、spec 用 `inputs`（同 shape：name/type=text|longtext|bool|select/hint/required/options/default）；**谁写 YAML 谁标注**，须与运行期校验一致（同侧变更即同步，避免表单放行、运行期拒绝）；空 `arguments: []` = 显式无参数，缺省键 = 控制台按 args 回退推导；漂移由 catalog `metadata_warnings` 暴露（arguments 须被 variables/System.Args 承接、inputs 须在 state 中）
7. **机读任务隐藏（2026-09-17）**：面向 agent/内部的自检与批量入口（agent-forge / wf-selfcheck / wf-test-*）在 YAML `metadata.ui_hidden: true`；catalog/面板过滤该标记，CLI 触发不受影响——人机入口分离，不靠约定口头维持

**运行前置**：真实工作流含 InvokeLLM 判断点（wfengine → modelz.chat → openai 兼容源直调，当前 judge_default=opencode-go/deepseek-v4.1-flash），**无需 opencode server 常驻**。

## 6. 当前状态与待办

- ✅ 原语目录已建立（21 个，3 工作流共享面已标）
- ✅ **声明式工作流 YAML 化（2026-08-23）**：archive/track/digest 三工作流由 wfengine.py 执行验证通过（含 dry_run 预览拦截、判断点直调）
- ✅ sys_classify SDK 已按扩展规范实现（原子/幂等/可拔插/回归测试）
- ✅ **archival/digest 写操作已封装为原语库**（`scripts/primitives.py`：write_kb_page / write_memory_page / mark_digested / append_behavior_log / append_digest_log；原子写+幂等+自检通过）——skill 内嵌命令形态已消除
- ✅ **agent 层落地（2026-09-16）**：agentgraph 声明图 + 4 身份声明 + 工具池 v1（vault_search/arxiv_search/web_fetch）+ 节点工具回路（trace 可审计）；工作流 InvokeAgent 接入（test_invoke_agent 全绿）；loopx goalrun 真跑闭环
- ✅ **控制台能力面板（2026-09-17）**：catalog/run-agent/agents-suggest 三接口 + 壳 /wfctl 路由 + 面板「能力卡 → 详情页」两态（元数据表单/就地运行/互跳）；机读任务 ui_hidden 隐藏；AI 填充（agent-draft 图）打通「一句话 → 身份草案 → 人工修订 → 严格落盘」
- 🔌 工作流规范 §6「第 2 个工作流出现才建通用触发器」——classify 固化工作流出现后，评估是否触发通用触发层