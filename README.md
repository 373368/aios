# memcore — 记忆驱动知识管理系统

> 🚧 **WIP / 开源准备中（未发布、未开发完成）**
> 本仓库处于开源整理阶段：目录结构、接口、文档均在调整中，**尚未发布任何 release，也不构成可用版本**。开发进度与路线会持续变动，请勿视为稳定项目。

> 自用 AI 记忆系统（记忆驱动决策 + 知识生命周期管理）。权威知识库在 Obsidian（`D:\ObsidianVault\04-项目\ai-os\*`），本仓库只放**代码与规范**，不重复知识正文。原项目代号 AI-OS。

## 一句话

**让记忆驱动 AI 操作电脑**：用户发一句话，AI 自主调用记忆与 OS 能力完成任务；原创点在"记忆驱动决策 + 知识生命周期管理"。

## 状态（2026-09-06）

AI-OS **第二阶段收工**，核心闭环：

- ✅ **知识层**：检索定案 fd_bm25（全秩语义 + BM25 RRF），索引 646 页（05-知识 + 06-系统 + 01-记忆）
- ✅ **运行治理**：声明式三层（原语 / 工作流 YAML+wfengine / LLM 判断点），archive-daily / digest-daily / track-daily 三工作流验证通过；C1-C4 控制知识分流落地
- ✅ **专用 agents**：kb-archivist（归档）+ dev（编码专用）+ engineering-* 八个，六维设计规范（15-规范）
- ✅ **OS 壳（l4-os）**：C# WebView2 壳 + React 工作台，Chat 顶栏接 opencode(4400)/OpenScience(4401) 原生 serve；星空背景图（force-graph）
- ✅ **面板=底座**：17-spec 万物皆插件定案，Chat 面板先行落地
- 🔌 **剩余**：H3 全链路验证；OpenScience 配 key 后实测真任务；autonomous/heartbeat 无人值守长跑

## 目录分区（对应架构分层，见分层蓝图）

| 目录 | 层 | 职责 | 内容 |
|---|---|---|---|
| `l1-control/` | L1 主控层 | opencode 工作区：意图理解 / 规划 / 编排 / 会话纪律 / 记忆 | `opencode/`（AGENTS.md、.opencode/agent(kb-archivist)、.opencode/command、memory/TODO.md + 会话记忆）、`open-reason/`、`ponytail/` |
| `l2-memory/` | L2 记忆层（核心） | 知识处理实现：原语 / 工作流 / 检索 / 归档 / 评估 | 见下方「l2-memory 结构」 |
| `l3-tools/` | L3 工具层 | MCP 服务器集群 | windows-mcp / github-mcp / mcpvault / wps-skills |
| `l4-os/` | L4 OS 层 | Windows 壳：AiosShell（WebView2）+ 工作台前端（React/Vite/three.js） | `shell/AiosShell/`（C#）、`dashboard/`（React）、`scripts/`（build_graph_data.py 星空数据源） |
| `agents/` | 数据区 | 第三方 agent 运行时数据（OpenScience 等，git 忽略不入库） | 运行时生成 |
| `skills/` | 技能库 | agent skills | `custom/`（AI-OS 技能）、`ponytail/`、`agent-skills/`、`anthropic/` |
| `docs/` | 规范性文档**镜像副本**（规范/ + 决策/，只读参考） | 权威在 Obsidian `04-项目/ai-os/`，见 `docs/README.md`，单向同步 `sync-docs.ps1` |

### l2-memory 结构

| 目录/文件 | 职责 | 状态 |
|---|---|---|
| `scripts/` | 原语 + 工具（primitives.py / build_index / search_index / modelz / sys_classify_sdk / export-*.js 等） | ✅ 核心 |
| `tasks/` | 抓取/追踪脚本（scan_new / chunk_sessions / fetch_* / track-*.ps1 / auto-archive.ps1） | ✅ 核心 |
| `workflows/` | 声明式工作流：wfengine.py + archive/digest/track YAML + prompts/ 判断点 | ✅ 核心 |
| `archive/` | **统一废弃区**：sdk（废弃 SDK）/ eval-harness（已收束）/ light（历史）/ legacy（旧代码）/ scripts（独立评估脚本）/ docs（历史规划） | 🗄️ 集中归档 |
| `export/` | 原始对话导出中间态 | 📦 数据 |
| `chunks/` | 超大会话分片 | 📦 数据 |
| `index/` | 语义索引生成物 | 📦 数据 |
| `config.json` | 运行时配置（API/model） | ✅ |
| `start-server.ps1` | 常驻 opencode server 管理 | ✅ |

> l2-memory 内部结构索引见 `l2-memory/README.md`（2026-08-23 重划：scripts/tasks/workflows 活跃核心 + archive 统一废弃区）。

## 构建与运行（从源码）

**前置依赖**：.NET SDK 10+（net10.0-windows）、Node.js 20+、Python 3.11+；Windows 10/11 + WebView2 Runtime（Win11 自带）。

```powershell
# 1. 工作台前端（React + three.js 星空）
cd l4-os\dashboard
npm install
npm run build        # 产出 dist/

# 2. OS 壳（C# WebView2）
cd ..\shell\AiosShell
dotnet publish -c Release      # 产出 bin\Release\net10.0-windows\publish\AiosShell.exe
# 将 dist/ 拷贝为 publish\dashboard-dist\（壳优先从该目录读前端）
Copy-Item ..\..\dashboard\dist publish\dashboard-dist -Recurse

# 3. 外部 agent（Chat 面板的数据源，可选——面板可只开工作台/工作流）
#    opencode：https://opencode.ai  （壳用 `opencode serve --port 4400` 拉起）
#    OpenScience：https://synthetic-sciences.github.io/OpenScience  （`node <bin>/openscience serve --port 4401`）

# 4. 运行
.\bin\Release\net10.0-windows\publish\AiosShell.exe
# 壳自动拉起：dashboard(8799)、opencode(4400)、OpenScience(4401，若安装)、loopx(8766/8767，若安装)
```

> 说明：仓库 git 只跟踪源码（约 11MB）。运行时数据（`.loopx/`、`.codex/`、`agents/`、浏览器 profile 等）按 `.gitignore` 不入库，首次运行由各工具自行初始化。

## 打开方式（重要）

- **opencode 工作区**：从 `D:\AI OS\l1-control\opencode` 打开 opencode（不要从 D:\MCP 打开）
- **全局配置**：`C:\Users\asus\.config\opencode\opencode.jsonc`（provider/mcp/skills.paths/plugin/command/permission）
- **命令**：`/kbsearch <查询>`（检索）、`/kbbuild`（重建索引）、`/archive`（归档）、`/remember`、`/recall`、`/lsmem`
- **声明式工作流**：`python l2-memory\workflows\wfengine.py <workflow.yaml> [key=value]`（archive-daily / digest-daily / track-daily，见 declarative-workflows skill）
- **模型判断**：经 `scripts/modelz.py` 直调（DeepSeek-V4-Flash），不经 opencode agent 循环

## 约定

- 代码统一放本目录；知识/论证/决策放 Obsidian 不要写进来。
- **例外**：`docs/` 为规范性文档镜像副本（只读参考，单向同步自 vault，见 `docs/README.md`）；权威始终在 Obsidian。
- 写操作全走原语（`primitives.py`）；工作流用 YAML 声明式；LLM 只在判断点。
- 原始对话导出留在 `l2-memory/export/`（工程中间态，不进 vault）；提炼后的知识页直入 `05-知识/知识库/`（每知识一页）。
- 每个层目录内自建 `README.md` 说明该层内部结构。

## 决策记录

`D:\ObsidianVault\04-项目\ai-os\04-决策记录\`（2026-08-17 ~ 2026-08-23，含：AI-OS 定性为 OS 内核 / 目录整理与项目化 / 主控瘦身 skill 按需加载评估 等）。

## 待办

见 opencode 工作区 `D:\AI OS\l1-control\opencode\.opencode\memory\TODO.md`（永久待办，统一路径）。