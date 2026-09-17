# AGENTS.md — aios 仓库开发指南

本文件面向在本仓库工作的 AI 编码代理（opencode / Claude / Codex 等）与人类贡献者。

## 项目是什么

aios = **原语**（确定性执行）/ **声明式工作流**（YAML + wfengine）/ **agent 图**（agentgraph，LangGraph）三层体系 + 控制台（Windows 壳 AiosShell + Dashboard）+ 知识沉淀与治理接入（WIP）。

## 目录

| 目录 | 内容 |
|---|---|
| `l2-memory/` | 核心：原语库（`scripts/primitives.py`）、声明式工作流（`workflows/`）、agent 图（`agentgraph/`）、检索（`scripts/search_index.py`）、路径与模型适配（`paths.py` / `modelz.py`） |
| `l4-os/` | 界面层：Windows 壳（`shell/AiosShell`）、Dashboard（`dashboard/`）、服务脚本（`scripts/`） |
| `l1-control/` | 控制层：会话纪律（`AGENTS.md`） |
| `skills/custom/` | 系统 skills（工作流 / 记忆 / 分类 / 归档 / 上手） |

## 核心不变量（改代码前先读）

1. **三层分工**：原语不做编排；工作流不掺并行；agent 图不管跨 goal 调度
2. **进程契约**：stdout = 纯 JSON / stderr = 日志 / exit 0|1（跨层一致，见 `skills/custom/declarative-workflows`）
3. **产出契约**：agent spec 声明 `outputs` ↔ 调用方声明 `expects`（缺失/空值即报错，不静默）
4. **输入门 fail-fast**：空输入不得喂给 LLM（wfengine 对空对象输入直接报错）
5. **机读入口隐藏**：`metadata.ui_hidden: true`（catalog/面板过滤，CLI 照常）
6. **输入元数据**：谁写 YAML 谁标 `trigger.arguments` / spec `inputs`（同侧变更同步，避免表单放行、运行期拒绝）

## 开发命令

```powershell
# 体检（含 spec 校验、原语自检；改完必跑）
python l2-memory/scripts/diagnostics.py --mode quick

# Dashboard 构建（壳静态托管 dist）
npm --prefix l4-os/dashboard install
npm --prefix l4-os/dashboard run build

# 壳构建（Windows；net10.0-windows）
dotnet build l4-os/shell/AiosShell/AiosShell.csproj -c Release

# 工作流试跑 / agent 图校验
python l2-memory/workflows/wfengine.py l2-memory/workflows/demo-hello.yaml
python l2-memory/agentgraph/agentgraph.py check l2-memory/agentgraph/specs/script-smoke.yaml
```

## 约定

- 提交信息：Conventional Commits（`feat` / `fix` / `chore` / `docs` + 范围）
- 新增工作流 / 工具 / 身份：见 `skills/custom/declarative-workflows` 与 `l2-memory/agentgraph/README.md`
- **路径不得硬编码本机**：Python 走 `l2-memory/scripts/paths.py`（`AIOS_*` env > config.json > 默认）；C# 走 `l4-os/shell/AiosShell/Paths.cs`
- 改壳后需同步构建 Debug / Release / publish（详见 `l4-os/README.md`）
