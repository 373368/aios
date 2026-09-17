# Changelog

版本号与本地便携包 `aios-<版本>-win64.zip` 对应；未发布 GitHub Release。

## 0.3.1 — 2026-09-17

- 便携包补齐 `skills/custom/`（系统 skills：工作流 / 记忆 / 分类 / 归档）+ 安装说明（含 `AIOS_*` 环境变量）
- 环境变量前缀 `MEMCORE_*` → `AIOS_*`（`paths.py` / `Paths.cs` 等 8 文件）
- 壳启动器加固：解析 npm `.cmd` 垫片 + 可选外部组件缺失静默降级（不再因 `async void` 异常崩壳）

## 0.3.0 — 2026-09-17

- 首个公开版本（github.com/373368/aios）
- 三层体系：原语库（`primitives.py`）/ 声明式工作流（wfengine）/ agent 图（agentgraph，LangGraph）
- 工具池 + 工具工厂：多 kind 注册表（`http` / `script` / `plugin`）+ `register_tool` / `save_tool_drafts` / `adopt_tool_draft`
- 控制台：能力面板（catalog 驱动「能力卡 → 详情页」+ 元数据表单就地运行 + AI 填充）
- Windows 便携包：自包含 .NET 壳 + Dashboard + l2-memory + skills

## 0.2.0 — 内部里程碑

- 声明式工作流三件套（archive / track / digest）+ loopx goalrun 治理闭环
- 检索 v1（fd_bm25）与知识层整合

## 0.1.0 — 内部里程碑

- 原语化（写操作 100% 原语库）+ 记忆沉淀 / 归档提炼工作流
