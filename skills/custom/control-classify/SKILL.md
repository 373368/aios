---
name: control-classify
description: 06-系统 控制知识 C1-C6 分类固化（sys_classify_sdk 机械初判 + LLM 精判 → 落盘载体）。凡是处理控制知识分流、分类固化、C1/C2/C3/C4/C5/C6 分流落地、AGENTS.md 锚点候选、permission 硬化条款、skill 候选、控制知识生命周期，或用户说「分类固化/分流落地/06-系统」，都必须先用本 skill。关键词：control-classify, 分类固化, C1-C6 分流, sys_classify, 锚点, 硬化, skill候选
---

# Control-Classify — 06-系统 控制知识分类固化

## 定位

把 06-系统 控制知识按六类消费模型分流到落地载体（C1-C6）。**低频动作**，不走声明式工作流（YAML/wfengine），以本 skill 在触发时引导完成。判据词与 `06-系统/06-系统索引.md` §1 一致。

六类消费模型：
| 类 | 判据词（CLAUSES 单源） | 落地载体 |
|---|---|---|
| C1 不可协商纪律 | 第一原则/永远/一律/不可协商/底线/必须 | L0 锚点 → AGENTS.md |
| C2 规避经验·机械可判 | 禁止/不能/切勿/禁放/别/不要/移出 | harness 硬化 → permission（write_permission 原语）/ 检查点条款 |
| C3 规避经验·情境触发 | 每次/遇到/场景/之前 | SKILL.md（新 skill 或并入既有） |
| C4 流程/决策规则 | 时机/判定/规则/何时/评估 | L1 检索（保持 06-系统 索引） |
| C5 事实/机制 | 是什么/机制/原理/架构/配置/路径 | L2 查阅（保持索引） |
| C6 复盘记录 | 排查/现象/根因/踩坑/复盘 | 01-记忆 / 检索兜底 |

## 执行流程

1. **初判（原语）**：`python <repo>\l2-memory\scripts\sys_classify_sdk.py`（全量 06-系统）或 `<某页.md>`（单页）。输出 `<repo>\l2-memory\eval-harness\cache\sys_classify_report.json`。
2. **精判（LLM）**：SDK 初判只是候选（verdict=candidate），LLM 复核分类与抽取结果再定稿。
3. **落盘（按类路由）**：
   - C1 → 合并进 `<repo>\l1-control\opencode\AGENTS.md`（锚点短句，不删旧）
   - C2 → 可 permission 化的条款 → 用 `write_permission` 原语写入全局 opencode.jsonc（插入顺序：broad 规则在前，narrow deny 在后）；不可 permission 化（heredoc/油猴目录类）→ 留检查点，注明「文档+skill 面」
   - C3 → 情境触发的写新 skill（走 skill-creator）；机械动作已在 declarative-workflows 等既有 skill 的，并入其流程段
   - C4/C5 → 页面保持 06-系统 索引，验证 `search_index.py` 可命中
   - C6 → 归 01-记忆
4. **回写**：更新 `06-系统索引.md` 该页分类标注 + 13-系统现状 消费列。

## 验证

- 回归：`python <repo>\l2-memory\scripts\test_sys_classify.py`（6 标签钉住，标签变更多半是判据词变了）
- 检索可达：`python <repo>\l2-memory\scripts\search_index.py "<规则关键词>" --k 3` 命中对应 06-系统 页（可加 `--rerank` 启用 Qwen3-Reranker 重排，默认关闭）
- 配置合法：permission 写入后剥注释 json.loads 校验（参考 declarative-workflows skill 的坑）；改动配置需重启 opencode 生效

## 约束

- **判据单源**：CLAUSES 表（sys_classify_sdk.py 顶部）——改判据 = 改这张表，正则/触发词自动跟随。判据词被宿主词污染时（如「别」在 区别/类别 中）已由 HOST_EXCLUDE 词感知处理，勿绕过
- 分类命中 C1/C2/C3 但该载体已固化 → 走幂等（锚点已存在/原语 skipped），不重复写入
- 新增 06-系统 页后需跑全量分类；历史页可增量按页处理

## 验收

- [ ] sys_classify_sdk 单页/全量跑通，报告 JSON 可读（含 run_status/timestamp）
- [ ] 每条候选经 LLM 精判定稿，落盘载体与分类一一对应
- [ ] 06-系统索引 分类标注已更新；13-现状 消费列已同步
- [ ] 回归测试通过；配置/AGENTS.md 变更幂等无重复