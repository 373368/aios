---
description: H3 学术追踪提炼——读采集 JSON，提炼成知识页入 05-知识/知识库/学术前沿/<source>/，索引与行为记录由 track 壳负责。
agent: kb-archivist
---

运行 H3 学术前沿提炼（headless，不抓取不开浏览器）：

参数：`<source> <jsonPath>`（如 `arxiv D:\AI OS\l2-memory\export\arxiv\latest.json`）

1. 读取 `<jsonPath>` 的 JSON（schema: `{source, items:[{id,title,url,authors,date,summary,...}]}`）
2. 逐条判断价值（前沿研究/高相关/新增信息），提炼为知识页：
   - 落点：`D:\ObsidianVault\05-知识\知识库\学术前沿\<source>\YYYY-MM-DD-<序号>.md`
   - 每页 frontmatter：`type: knowledge`, `source: <source>`, `item_id: <id>`, `date: <date>`
   - 正文：标题 + 一句摘要 + 关键要点（2-5 条）+ 来源 URL
   - **同主题去重**：已有同 item_id 页面则跳过；同主题已有页则并入或双链
3. 空/无价值条目跳过

**硬性约束**：
- 禁止运行浏览器/抓取/导出脚本
- 只做：读 JSON → 写知识库页 →（索引和行为记录由 track-common.ps1 在外部调用 build_index.py 完成）

$ARGUMENTS