# 原语与 SDK 扩展规范

> 定位：AI-OS 能力体系（原语/工作流/SDK 三层）的原语目录 + 扩展约定。
> 依据：2026-08-22 运行治理统一讨论（原语 = 工具统一体 / 工作流 = 原语编排 / SDK = LLM 参与的整合监控层）。
> 原则：**原语 = 工具（同一事物两个视角名词，确定性执行、无 LLM）；工作流 = 特定场景多原语调用的编排（锁/日志/退出码）；SDK = 需要 LLM 直接参与/监控的高层整合层（控制管理工作流、多工作流整合、错误/意外处理、高层次复杂处理），是直接交给核心 agents 的运行元件。LLM 只在判断点出现，执行永远走原语。**

## 1. 体系三层（原语 / 工作流 / SDK）

```
LLM 核心（agents，只做判断点：价值/主题/分类精判/边界/错误处理）
   │
   ▼ 直接持有
[SDK 层] ← 本规范核心：LLM 参与的整合监控层（运行元件）
   │ 控制/管理工作流、多工作流整合、错误与意外处理、高层复杂处理
   ▼ 驱动
[工作流层] ← 05-工作流规范：特定场景多原语编排（锁/日志/退出码）
   ▼ 调用
[原语层]（= 工具统一体）← 本规范：原语目录 + 扩展约定
   │ 确定性执行，无 LLM（标准库 / MCP / 脚本 / primitives.py 均属此）
   ▼
资源层（vault / 索引 / 导出）
```

> **原语与工具统一**：工具 = 原语，同一事物两个视角名词（宿主视角称工具，能力目录视角称原语），不存在「凌驾于工具之上的独立原语层」。标准库、MCP、CLI 脚本、primitives.py 业务函数全部归原语层。

| 层 | 规范 | 内容 | 状态 |
|---|---|---|---|
| **SDK** | **本规范** | LLM 参与/监控的整合层：工作流控制、多工作流整合、错误/意外处理、高层复杂处理 | 📄 本文件 + 14-业界对照 |
| 工作流 | 工作流规范（05-工作流规范.md） | **声明式 YAML 编排（wfengine 执行）** + 统一入口契约 + 触发层 + 单实例锁 + 退出码 | ✅ 3 工作流 |
| **原语** | **本规范** | 原语（工具统一体）目录 + 原子/幂等/可拔插/回归测试约定 | 📄 本文件 |

**声明式形态（2026-08-23 定案）**：工作流以 YAML 声明（`l2-memory/workflows/*.yaml`），由 `wfengine.py` 执行——动作 = InvokePrimitive / InvokeLLM / ConditionGroup / Loop / SetVariable，每个动作可带 `when` 条件；表达式用 `=` 前缀（=System.Args.x / =Local.x / =Loop.Item / 比较运算 / `{var}` 内嵌）；判断点 prompt 存 `workflows/prompts/*_judge.txt`，输出严格 JSON 含 `branch`，由 ConditionGroup 路由。使用规范见 `declarative-workflows` skill（D:\AI OS\skills\custom\declarative-workflows\）。

**边界**：原语不写业务编排（那是工作流）；工作流是确定性流程载体（锁/日志/退出码），不掺 LLM 判断（那是 SDK 职责）；SDK 是 LLM 参与的运行元件，所有工作流理论上都被 SDK 驱动（错误/意外处理需 LLM 监控）。

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

### 3.5 共享面（跨工作流复用）
| 原语 | 复用场景 |
|---|---|
| `refresh_index` | 所有「写入后必须检索可见」的工作流 |
| `search_semantic` | 所有「去重/关联判断」 |
| `write_kb_page` | archival + digest 共用写页模板 |
| `dedup_ids` | archival 去重游标 + digest 归档判重 |

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
- **SDK 与工作流**：SDK 不写工作流逻辑，只做「LLM 参与的控制/监控/整合」；工作流是确定性编排，SDK 是其 LLM 侧运行元件

## 6. 当前状态与待办

- ✅ 原语目录已建立（21 个，3 工作流共享面已标）
- ✅ **声明式工作流 YAML 化（2026-08-23）**：archive/track/digest 三工作流由 wfengine.py 执行验证通过（含 dry_run 预览拦截、判断点直调）
- ✅ sys_classify SDK 已按扩展规范实现（原子/幂等/可拔插/回归测试）
- ✅ **archival/digest 写操作已封装为原语库**（`scripts/primitives.py`：write_kb_page / write_memory_page / mark_digested / append_behavior_log / append_digest_log；原子写+幂等+自检通过）——skill 内嵌命令形态已消除
- 🔌 工作流规范 §6「第 2 个工作流出现才建通用触发器」——classify 固化工作流出现后，评估是否触发通用触发层