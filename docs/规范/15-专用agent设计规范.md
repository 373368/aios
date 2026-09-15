---
created: 2026-08-23
updated: 2026-08-23
topic: 专用 agent 设计规范
tags: [AI-OS, 运行治理, 机制, subagent, dev]
---

# 15-专用 agent 设计规范

## 1. 问题：dev 是 build 子集，不是专用

现状对照（2026-08-23）：

| | build（主控） | dev（现状） | kb-archivist（真专用 ✓） |
|---|---|---|---|
| 职责 | 通用全能（编排+治理+编码+知识管理） | 「代码开发专用模式」 | 对话提炼入库（独立产出） |
| 能力 | 全部 skills + MCP + 子代理 | = build 白名单裁剪（deny 多数） | 专属脚本 + 检索 + 判断 |
| 流程 | 无域内固定序列 | 无 | 6 步固定工作流 |
| 上下文 | 全量注入 | 仅减负，无独立设计 | 定位 + 触发 + 规则完整 |
| 模型 | 默认 | 未指定（继承） | 独立指定 volcengine/deepseek |

**dev 无独立产出、无独立流程、无独立能力、无独立模型 → 是 build 的受限子集，不是真正的专用 agent。**

## 2. 专用 agent 判定：有主控没有的东西

> 专用 = **域内有独立产出的专家**（独特能力/流程/知识），而非主控的裁剪版。
> 真正的专用 agent 必然带出「build 本来就不该亲自做」的职责。

## 3. 六维设计框架

设计一个专用 agent，按以下 6 个维度逐项确立（缺一不可）：

### ① 职责边界（域定义）
- **你做**：域的独立产出是什么，一句话可说明
- **你不做**：明确排除，避免与主控/其他 agent 重叠
- **出错升级**：域内失败怎么处理（自修脚本 / 报人工），禁止静默失败

### ② 触发契约
- description 首行写清触发词与委派条件（用户说 X → 委派；主控遇到 Y → 委派）
- mode：primary（用户主动切换专注）/ subagent（主控委派）/ all

### ③ 能力集
- **专属工具**：域内脚本/CLI/固定命令（kb-archivist 的 export 脚本）
- **skills 白名单**：permission.skill 放行域内所需，deny 域外（**注意：只控执行，不省描述注入**）
- **知识源**：域内知识经 skill/引用/检索按需加载
- **模型**：可独立指定（域特性匹配，如编码用快模型、提炼用判断模型）

### ④ 流程/方法论
- 域内固定操作序列（kb-archivist 6 步；编码域 = spec→plan→TDD→实现→review→test→lint）
- 域内专用判断点（去重/价值/分类等 LLM 判断）

### ⑤ 上下文策略
- prompt 最小化：只含职责边界 + 关键规则 + 流程骨架，细节按需加载
- 不依赖主控的运维语境（AGENTS.md 会话纪律由主控承载，专用 agent 聚焦域）

### ⑥ 协作契约
- 任务封装：一次委派 = 封装好的独立问题（带输入、期望输出）
- 返回格式：固定汇报格式（成功 N / 跳过 M / 异常 K），主控可拼接
- 长任务：切片，每片回主会话，防止上下文缺失（子代理 5 问题之一）

## 4. 与主控的分工契约（build/dev 重叠解法）

职责重叠不可避免（主控也会动代码），解法是**分工契约化**而非裁剪：

| 任务特征 | 归属 |
|---|---|
| 短改、单行、随手调 | build 直接做（不委派） |
| 域内完整产出（开发功能/重构/审查/归档一批/沉淀一批） | 委派专用 agent |
| 编排/治理/知识管理/运行运维 | build（主控核心） |
| 需要用户实时纠偏的深度会话 | 用户主动切专用模式（dev primary） |

## 5. dev 重设计样例（编码域）

> **已实施（2026-08-23）**：`C:\Users\asus\.config\opencode\agents\dev.md` 已按本样例改造完成——职责边界/触发契约/编码方法论/上下文策略/协作契约 + frontmatter 能力集（22 编码 skills 白名单、8 engineering-* 子代理委派、4 办公/数据/浏览器/桌面 MCP 关闭）。验证：frontmatter yaml 解析通过。

### 职责边界
- **你做**：独立交付编码任务——新功能、重构、调试、代码审查、测试、批量重构（含 AI-OS 自身代码）
- **你不做**：不承担 AI-OS 运行治理/知识管理/归档/检索（那是 build 主控）
- **出错升级**：编译/测试失败定位根因修；环境不可用报原因

### 触发契约
- 用户切 dev 模式（primary）专注编码，或 build 委派编码短任务
- mode: primary（保持，用户主动进入）

### 能力集
- skills 白名单：agent-skills 工程方法论（tdd/review/refactor/planning/spec/security）+ ponytail 族 + memory/vault-digest（沉淀编码产物）
- 委派权：8 个 engineering-* 子代理（专项查证/审查/批量重构）
- 模型：可独立指定（如编码用 fast 模型，默认继承，待验证）
- tools 过滤：关 wps-office/kaggle/playwright/windows-mcp（已做）

### 流程/方法论
spec/plan → TDD（先红后绿）→ 实现 → 代码审查 → 测试+lint → 汇报（含 ponytail 懒人检查）

### 上下文策略
- prompt 精简：职责边界 + 编码方法论引用（agent-skills SKILL.md 按需读，不注入全文）
- 不加载 AI-OS 运维语境

### 协作契约
- 一次任务封装：目标 + 涉及文件 + 验收标准
- 汇报：改动文件清单 + 测试结果 + 遗留问题
- 长任务切片回主会话

### frontmatter 骨架（改造目标）
```yaml
description: 编码专用运行模式。独立交付功能/重构/调试/审查/测试，不承担 AI-OS 治理。触发：切 dev 专注编码、build 委派编码任务
mode: primary
model: <可选独立编码模型>
permission:
  task:
    "*": deny
    "engineering-*": allow
  skill:
    "*": deny
    "ponytail*": allow
    "agent-skills 编码类": allow
    "memory": allow
    "vault-digest": allow
tools:
  "wps-office_*": false
  "kaggle_*": false
  "playwright_*": false
  "windows-mcp_*": false
```

## 6. 判定 checklist（新专用 agent 立项）

- [ ] 域有独立产出（build 不亲自做的理由）
- [ ] 有独立流程/方法论，非主控裁剪
- [ ] 有能力集（专属工具/skills/知识源/模型）明确
- [ ] 触发契约 + 协作契约（封装/返回）定义
- [ ] 上下文策略（prompt 最小化 + 按需加载）