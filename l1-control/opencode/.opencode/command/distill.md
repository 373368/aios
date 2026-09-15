---
description: 纯提炼工作流（headless 用）——扫描现有 export、逐会话提炼入库、增量索引、行为记录。不抓取、不开浏览器。
agent: kb-archivist
---

运行知识提炼工作流（**不含抓取/浏览器**，export 已由外部脚本完成）：

1. 运行 `python D:\AI OS\l2-memory\tasks\scan_new.py` 得待提炼清单
2. 校验导出完整性（用户消息是否齐全、空会话/占位识别）
3. 逐会话提炼入库（同主题去重、价值判断、每知识一页）
4. 增量索引 `build_index.py`
5. 行为记录 + 汇报

**硬性约束**：
- **禁止运行任何浏览器/抓取/导出脚本**（export-doubao.js / export-yuanbao.js 等一律不跑）
- **禁止使用浏览器类工具**（Playwright MCP、browser-task 等）
- 只做：读 export 文件 → 写知识库页 → 跑索引 → 写行为记录

$ARGUMENTS
