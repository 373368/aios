# aios

AI-OS：原语（primitives）/ 声明式工作流（wfengine）/ agent 图（agentgraph）三层体系 + 控制台（Windows 壳 + Dashboard）+ 知识沉淀与治理接入。

> 🚧 **WIP — 未发布，未开发完成**。README 将在发布前补齐。

## 仓库结构

| 目录 | 内容 |
|---|---|
| `l2-memory/` | 核心：原语库（`scripts/primitives.py`）、声明式工作流（`workflows/`）、agent 图（`agentgraph/`）、检索（`scripts/search_index.py`）、路径与模型适配（`paths.py` / `modelz.py`） |
| `l4-os/` | 界面层：Windows 壳（`shell/AiosShell`）、Dashboard 源码（`dashboard/`）、服务脚本（`scripts/`） |
| `l1-control/` | 控制层：opencode 会话纪律（`AGENTS.md`） |
| `skills/custom/` | 系统 skills：declarative-workflows / memory / vault-digest / control-classify / archival 等 |
| `docs/` | 架构与运行规范（三层体系 / 原语目录 / agent 设计规范，见 `docs/README.md`） |

## 快速开始

- **Windows 便携包**：`aios-<ver>-win64.zip` — 解压 → 双击 `启动.cmd`（详见包内 `安装说明.txt`）
- **源码运行**：壳 `dotnet build -c Debug`（见 `l4-os/README.md`）；能力目录 `python l2-memory/workflows/wfctl.py list`
