---
description: 运行知识归档工作流——抓取最新 AI 对话并提炼入库
agent: kb-archivist
---

运行知识归档工作流。

参数：传 "skip-export" 时跳过浏览器抓取（export 已手动完成），直接从扫描开始；不传则执行完整流程。

1. 抓取增量：若参数为 skip-export 则跳过；否则运行豆包和元宝导出脚本，检查 DeepSeek 是否有新导出
2. 校验导出完整性（用户消息是否齐全、空会话/占位识别）
3. 运行 `python D:\AI OS\l2-memory\tasks\scan_new.py` 得待提炼清单
4. 逐会话提炼入库（同主题去重、价值判断、每知识一页）
5. 增量索引 `build_index.py`
6. 行为记录 + 汇报

$ARGUMENTS
