---
name: archival
description: AI 对话归档与知识提炼。将 export/ 下未提炼的对话会话提炼为知识页（每知识一页）写入知识库。使用场景：用户说"归档"/"提炼对话"/"archival"/"把豆包/DeepSeek/元宝对话提炼入库"。关键词: archival, 归档, 提炼, AI对话, 知识库入库
---

# Archival — AI 对话归档提炼

## 目标

把 `<repo>\l2-memory\export\<平台>\` 下**未提炼**的对话会话，提炼为**独立知识页**写入 `05-知识/知识库/`。每知识一页，同主题双链。原始对话留在 export/（工程中间态，不进 vault）。

## 输入与去重

- 输入：`export/豆包|DeepSeek|元宝/<conversation_id>-<标题>.md`，frontmatter 含 `title/source/conversation_id/exported_at`
- **超大会话分片（自动）**：`>60KB` 的会话由 `chunk_sessions.py` 按消息段切成 `chunks/<平台>/` 下 ≤60KB 切片（`<原名>__pN.md`），切片保留原 frontmatter（conversation_id 一致）。**已分片的原文件不再单独提炼**，只提炼切片 → 一个会话可提炼多条知识，天然满足"每知识一页"
- **去重游标**：知识库页面 frontmatter 的 `conversation_id` **∪ 来源段"会话: xxx (id)"的全部 id** = 已归档集合（一页可来自多个会话，frontmatter 只记主 id）。会话文件的 `conversation_id` **读文件内 frontmatter**（不是文件名，UUID 文件名截断会误判）若已存在于集合 → 跳过（幂等）。同一会话的多个切片共享 conversation_id，提炼后一并幂等跳过
- 提取方式：`vault_search_notes`（query=该 conversation_id）或用 `python` 扫描知识库 frontmatter + 来源段
- 快速统计未提炼清单的参考命令：
  ```python
  # 建知识库 id 集合（frontmatter conversation_id ∪ 来源段会话 id）→ 逐 export 文件读 frontmatter 比对
  import os, re
  have = set()
  for r, d, fs in os.walk(r'<vault>\05-知识\知识库'):
      for fn in fs:
          if not fn.endswith('.md'): continue
          t = open(os.path.join(r,fn), encoding='utf-8').read(20000)
          for m in re.finditer(r'conversation_id:\s*(\S+)', t):
              have.add(m.group(1).strip().rstrip(','))
          for m in re.finditer(r'会话[：:]\s*(?:.+?)\s*\((\d+|[0-9a-f-]{8,})\)', t):
              have.add(m.group(1).strip())
  for plat in ['豆包','DeepSeek','元宝']:
      d = os.path.join(r'<repo>\l2-memory\export', plat)
      missed = []
      for f in os.listdir(d):
          if not f.endswith('.md'): continue
          m = re.search(r'conversation_id:\s*(\S+)', open(os.path.join(d,f), encoding='utf-8').read(800))
          if not m or m.group(1).strip() not in have: missed.append(f)
      print(plat, '未提炼', len(missed))
  ```

## 流程

### 0. 分片（先决步骤，仅超大会话）
对 `export/<平台>/` 下 `>60KB` 的会话，先运行分片器（幂等，已分片自动跳过）：
`python <repo>\l2-memory\tasks\chunk_sessions.py`
分片落在 `chunks/<平台>/`。后续提炼以**切片**为单位（`export` 原文件若已分片则不再单独提炼）。

### 1. 列出待归档会话
扫描 `export/<平台>/` + `chunks/<平台>/` 全部 .md，比对知识库已有 `conversation_id`，得出未提炼清单。输出：`共 N 个待归档（平台 X）`。命令：`python <repo>\l2-memory\tasks\scan_new.py --json`

### 2. 逐会话提炼（每知识一页）
对每个待归档会话：
- 读原文（frontmatter + 用户/AI 消息段）
- **提炼独立知识条目**：该会话可能含多条独立知识（定义/方法/结论/代码范式），逐条列出
- 对每条：定**主题**（动态生成，不预设分类）+ **知识正文**（浓缩原对话中该知识点的干货，去对话口水）+ **摘要**（1-2 句）

### 3. 写入知识库
每条知识一页，路径 `05-知识/知识库/<骨架>/<子目录>/<主题>.md`：
- **用原语库落盘**：`python <repo>\l2-memory\scripts\primitives.py` 的 `write_kb_page(title, skeleton, subdir, frontmatter, body)`（from primitives import write_kb_page）——frontmatter 序列化、路径解析、骨架白名单兜底、原子写、幂等跳过由函数保证，**不要手写文件格式**
- 骨架/子目录：按主题归入现有 9 骨架（AI与机器学习/编程开发/数学/计算机基础/物理/医疗/学习/生活/娱乐）及子目录；无合适子目录则放骨架顶层
- **frontmatter**：`source`(doubao/deepseek/yuanbao) + `conversation_id`(原会话 id) + `exported_at` + `tags`
- **正文结构**：`## 核心知识`（干货要点）→ `## 要点速记`（条目化）→ `## 来源`（平台/会话）
- **同主题双链**：写前先 `vault_search_notes` 查同主题已有页，相关则加 `[[链接]]`
- 一个会话提炼出多条知识 → 写多个文件，每文件一个 `conversation_id` 关联同源会话

### 4. 写行为记录
用原语库 `append_behavior_log(category="归档", line="平台:<平台> 对话:<id> 提炼知识:<条数> 触发:<手动/自动>")` 追加（`03-日志/行为记录/YYYY-MM-DD.md`，幂等去重）。

### 5. 刷新语义索引（沉淀即索引）
- 执行 `python <repo>\l2-memory\scripts\build_index.py`（增量，只 embed 新增页）
- 失败不阻断：记录到日志，下次重试（幂等）

## 产物

- 知识库新增知识页（每知识一页）
- `03-日志/行为记录/` 归档条目
- 语义索引刷新

## 验收

- [ ] 未提炼会话 → 产出 ≥1 个知识页（每知识一页，非每会话一页）
- [ ] 知识页含 frontmatter（source/conversation_id/exported_at/tags）+ 核心知识 + 来源
- [ ] 同主题已有页被双链/去重
- [ ] 行为记录生成、字段齐全
- [ ] 重复运行不重复提炼（conversation_id 幂等）
- [ ] 语义索引增量刷新，检索能命中新页