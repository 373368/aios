---
name: aios-quickstart
description: aios（AI-OS）上手指南——安装、配置、跑第一个工作流、体检排障、扩展（新增工作流/agent 图/身份/工具）。当用户问「怎么用 aios」「怎么安装/配置」「怎么加一个工作流/agent/工具」「跑不起来怎么查」时使用。关键词：quickstart, 上手, 安装, 配置, 入门, aios
---

# aios Quickstart — 上手指南

## 这是什么

aios = 三层体系 + 控制台 + 治理接入：

- **原语**（`l2-memory/scripts/*.py`）：确定性执行，无 LLM
- **声明式工作流**（`l2-memory/workflows/*.yaml` + wfengine）：多原语编排，含 LLM 判断点
- **agent 图**（`l2-memory/agentgraph/`，LangGraph）：工具回路 / 多身份 / 身份声明
- **控制台**（`l4-os/`）：Windows 壳 + Dashboard（能力面板 / 设置页）
- **治理**（可选，loopx）：goal / 配额 / 证据

入口二选一：控制台（推荐新手）或 CLI（wfengine / wfctl / agentgraph）。

## 一、安装（便携包）

1. 解压 `aios-<版本>-win64.zip` 到任意目录（该目录即程序根）
2. 双击 `启动.cmd`（或 `app\AiosShell.exe`）→ 控制台 `http://127.0.0.1:8799`
3. 依赖：Windows 10/11 x64 + Python 3.10+（`pip install -r l2-memory\requirements.txt`）；
   opencode / loopx / openscience 是**可选外部组件**，缺失时对应功能降级，不影响主界面

## 二、配置

- 方式 A（推荐）：控制台「设置 → 配置」在线编辑 `l2-memory/config.json`（保存前自动备份，校验失败不落盘）
- 方式 B：复制 `l2-memory\config.example.json` → `config.json` 手工编辑
- 关键项：`models.default`（默认模型）/ `models.judge_default`（判断点与轻量任务）/ `models.providers.*`（base / api_key / models）
- 环境变量覆盖：`AIOS_ROOT / AIOS_VAULT / AIOS_PYTHON / AIOS_OPENCODE_EXE / AIOS_LOOPX_EXE / AIOS_OPENSCIENCE_JS`

## 三、跑第一个工作流（约 1 分钟）

- 控制台：「工作流 → 演示 → demo-hello → 运行」→ 结果面板出问候语
- CLI：`python l2-memory\workflows\wfengine.py l2-memory\workflows\demo-hello.yaml name=世界`
- 内置可跑样例：`research topic=<主题>`（调研并写笔记入 vault）、`tool-scout brief=<需求>`（工具侦察）

## 四、体检与排障

- 快速体检（无 LLM，约 20 秒）：`python l2-memory\scripts\diagnostics.py --mode quick`（exit 0 = 无失败）
- 含模型连通：加 `--mode ping`
- 控制台「设置 → 体检」有同样入口（含服务端口探测）
- 常见问题：缺 config.json / Python 依赖缺失 / vault 路径不存在 / opencode 通道未运行（warn，不影响直连模型）

## 五、扩展点

| 想做什么 | 落点 | 参考 |
|---|---|---|
| 新增工作流 | `l2-memory/workflows/<name>.yaml`（wfengine 声明） | skill: **declarative-workflows** |
| 新增 agent 图 | `l2-memory/agentgraph/specs/<name>.yaml` + `python agentgraph.py check <spec>` | `agentgraph/README.md` |
| 新增身份 | `agentgraph/declarations/<name>.md`（或控制台「AI 填充」/ agent-forge） | 同上 |
| 新增工具 | `register_tool` 原语注册（kind=http/script/plugin，注册即 smoke） | `agentgraph/README.md` 工具节；`tool-scout` 工作流 |
| 写知识/记忆 | `primitives.py` 写操作原语（write_kb_page / write_memory_page 等） | skills: **memory** / **vault-digest** |

## 六、目录速查

| 目录 | 内容 |
|---|---|
| `l2-memory/` | 核心：原语库 / 工作流 / agent 图 / 检索 / 路径与模型适配 |
| `l4-os/` | 界面层：Windows 壳（AiosShell）+ Dashboard |
| `l1-control/` | 控制层：会话纪律（AGENTS.md） |
| `skills/custom/` | 系统 skills（工作流 / 记忆 / 分类 / 归档 / 本指南） |
