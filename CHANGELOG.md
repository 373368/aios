# Changelog

版本号与本地便携包 `aios-<版本>-win64.zip` 对应；未发布 GitHub Release。

## 0.4.3 — 2026-09-17

- **初始化向导**（设置 → 初始化）：四步引导（Python 解释器 → 依赖安装 → 模型配置 → loopx 安装与建档）；loopx 从"可选"升为必需引导项（registry 未建档 / 未安装均引导完成初始化，不再只是降级）；附「重启壳」一键操作
- **快速配置**：内置常见模型源预设（`config.presets.json`：硅基流动 / 火山方舟 / OpenCode Go / DeepSeek / Moonshot / 智谱）→ 选源 + 粘贴 key 一键应用：自动写 provider 与默认模型，并把 API key 写入用户级环境变量（无需手写 JSON）
- **壳路径契约对齐**（修真实 bug）：`Paths.cs` 现在与 `paths.py` 同契约（环境变量 > `config.json["paths"]` > 默认）——此前写在 config.json 的 vault 路径壳看不见，导致「星空知识图谱 0 节点 / 一片黑」
- **星图确认**：`build_graph_data.py` 对任意 markdown 目录通用（note / tag / wikilink 全支持），0 节点根因即上条路径错位
- **工作台浅字修复**（aios 主题）：修正 `--pw-body` 未定义变量导致的按钮白底浅字、当前 tab 白底白字、快捷提示/目标卡片/已停止计数 chip 的浅底残留
- **loopx 未初始化**归入降级引导（`degraded_reason=loopx-uninitialized`），健康面板不再报契约错误
- 健康面板契约项附首条错误/警告明细；体检新增「壳视角（python / vault）」一致性项 + Python 项显示 `sys.executable`
- `requirements.txt` 显式补 `requests` / `pydantic`（防 `--no-deps` 踩传递依赖）
- 壳新增路由：`config-presets · config-apply · setup-status · setup-install-deps · setup-install-loopx · setup-init-loopx · setup-set-python · restart-shell`

## 0.4.2 — 2026-09-17

- 修复无 loopx 机器上仍报「无法加载实时状态」：降级载荷按 dashboard schema 补全字段（缺失字段会被前端 Zod 校验拒绝）；前端识别 `degraded` 标记并显示顶部提示条，健康关注点文案改为人话

## 0.4.1 — 2026-09-17

- 修复：/status.json 在未安装 loopx 的机器上返回 HTTP 502（"无法加载实时状态"）→ 改为降级 JSON（HTTP 200 + 说明），并回退尝试 8766 serve-status；loopx 为可选组件，不再阻断控制台

## 0.4.0 — 2026-09-17

- 控制台设置页：状态（服务端口探测 + goals）/ 配置（config.json 在线编辑，校验 + 自动备份）/ 体检 / 关于
- `diagnostics.py` 体检条例：环境（Python/依赖）/ 配置（config/路径）/ 引擎（能力目录 · 原语自检 · spec 校验 · 工具池 · 演示）/ 连通（opencode 端口 + 模型 ping）
- `demo-hello` 演示工作流（开箱即跑，无外部依赖）+ 工作流级 `outputs:` 回显到结果面板
- 身份声明 frontmatter 新增 `skills:`：内联 `skills/custom/<名>/SKILL.md` 全文（单一事实源）
- 壳新增路由：`/wfctl/services · diagnostics · config-get · config-set`
- 新增 `aios-quickstart` 上手 skill

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
