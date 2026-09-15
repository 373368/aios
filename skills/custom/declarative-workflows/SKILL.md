---
name: declarative-workflows
description: AI-OS 声明式三层工作流编排（YAML 声明 + wfengine 执行 + 原语 + LLM 判断点）。凡是创建/执行/扩展声明式工作流（archive-daily / digest-daily / track-daily），或用户提到工作流、YAML 编排、wfengine、判断点、InvokePrimitive、InvokeLLM、声明式，都必须先用本 skill。关键词：workflow, 工作流, 声明式, 编排, wfengine, 判断点, YAML
---

# Declarative Workflows — 声明式三层工作流编排

## 定位

AI-OS 运行治理的**约定面**（TODO #12）。把「特定场景多原语编排」写成 YAML 声明，由 `wfengine.py` 执行：**工作流 = YAML 声明（编排）→ 原语（确定性执行）→ LLM 判断点（仅判断）**。对齐微软 Agent Framework Declarative Workflows 1.0 范式。

三层职责（`12-原语与SDK扩展规范.md` §1）：
- **原语**：确定性执行，无 LLM（`scripts/primitives.py` 写操作 / 独立脚本 / MCP / 标准库，均属此）
- **工作流**：YAML 声明式多原语编排（本 skill），由 wfengine 执行，管锁/日志/退出码
- **LLM 判断点**：只做判断（价值/主题/分类/分支），经 `modelz.chat` 直调判断模型，结果决定工作流分支

## 文件位置

| 组件 | 路径 |
|---|---|
| 引擎 | `<repo>\l2-memory\workflows\wfengine.py` |
| 工作流 YAML | `<repo>\l2-memory\workflows\*.yaml` |
| 判断点 prompt | `<repo>\l2-memory\workflows\prompts\*_judge.txt` |
| 写操作原语库 | `<repo>\l2-memory\scripts\primitives.py` |
| 模型适配 | `<repo>\l2-memory\scripts\modelz.py`（default=DeepSeek-V4-Flash，judge_default 判断点专用） |
| SDK 公共层 | `<repo>\l2-memory\sdk\common.py`（run_py/log/锁/退出码） |

## 执行命令

```powershell
python <repo>\l2-memory\workflows\wfengine.py <workflow.yaml> [key=value ...]
```

- **archive-daily**（对话提炼归档）：`... archive-daily.yaml source=doubao`（source 支持英文别名 doubao/deepseek/yuanbao，scan_new 内部映射平台目录；导出需在浏览器/油猴前置完成）
- **digest-daily**（记忆沉淀）：`... digest-daily.yaml`（**预览用 `dry_run=true`**，拦截全部写/标记动作，只跑判断）
- **track-daily**（学术追踪）：`... track-daily.yaml source=arxiv query="cat:cs.AI"`（source=arxiv/github/journal）

退出码 0=成功；运行日志追加 `<vault>\03-日志\wfengine.log` 与 `<工作流名>.log`。

## 工作流 Schema

```yaml
kind: Workflow
metadata: {name, description, version}
trigger: {kind: OnCommand, command: archive}   # 声明入口（当前统一 OnCommand）
variables:                                     # 顶部变量，可被 actions 引用
  source: =System.Args.source
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

## 判断点规范

- prompt 模板存 `workflows/prompts/<name>_judge.txt`，末尾用 `{content}` 占位输入
- 输出**严格 JSON**（`json_output: true` 自动抽取）：必须含 `branch` 字段，工作流用 ConditionGroup 按 branch 路由
- 判断模型默认 `=System.JudgeModel`（judge_default），走 **openai 直调**（kind=openai），**不经 opencode agent 会话**（prompt_async 进 agent 循环会返回空）
- 骨架白名单必须与 `primitives.py` 的 SKELETONS 一致（AI与机器学习/编程开发/数学/计算机基础/物理/医疗/学习/生活/娱乐/学术前沿）

现有判断点：`archive_judge`（new|extend|merge|falsify|skip）、`digest_judge`（memory|kb|todo）、`track_judge`（keep|skip）。

## 新增工作流流程

1. 定链路：原语编排序列 + 判断点位置（一个工作流一般 1 个判断点 + 1 个 ConditionGroup 路由）
2. 写 YAML：复用 `InvokePrimitive / InvokeLLM / ConditionGroup / Loop / SetVariable`，参考 archive-daily.yaml 结构
3. 写判断点 prompt 模板（`prompts/<name>_judge.txt`，输出 JSON 含 branch）
4. 新原语时：实现 → 幂等 → 附自检/回归 → 注册进 `primitives.py` CLI 分发表 → 登记 `12-规范 §2 原语目录`
5. 验证：先用 `dry_run` 或小样本跑通；参考 `wf-selfcheck.yaml` / `wf-test-judge.yaml` / `wf-test-source.yaml`（自定义 API 源 + $ENV key 引用）
6. 更新 `13-系统现状` 工作流面 + `12-规范` 映射

## 坑（来自实测）

- **PowerShell 给 python CLI 传 JSON 引号转义必炸**（JSONDecodeError）→ 引擎内 subprocess 传 argv 数组无此问题；**手动验证用 python 直接 import 调函数**，别拼命令行 JSON
- **dry_run 拦截**：写/标记原语必须带 `when: =System.Args.dry_run != "true"`（digest-daily 已示范），否则预览即真写
- **工作流 YAML 禁明文 api_key**：`sources.*.api_key` 只接受 `$ENV:VAR_NAME` 引用（加载时 validate_yaml_sources 拦截明文）；密钥放环境变量或本机 config.json（.gitignore 已排除）。非本地 openai 源缺 key → resolve 直接报错
- 中文乱码是 PowerShell 控制台显示问题，脚本输出字节是 UTF-8，以 `sys.stdout.reconfigure(encoding="utf-8")` 后为准

## 验收

- [ ] `wfengine.py <yaml> [k=v]` 退出码 0，`03-日志/wfengine.log` 有记录
- [ ] 三工作流可执行：archive-daily source=<平台> / digest-daily [dry_run=true] / track-daily source=<源>
- [ ] 新增工作流遵循本 schema，判断点输出 JSON 含 branch 且骨架白名单一致
- [ ] 写操作全走 primitives（skill 内嵌命令形态已消除）