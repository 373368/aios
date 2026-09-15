---
description: 行为增强检索（搜索知识库 + 行为场增强排序）
agent: build
---

使用 search_enhanced.py 进行行为增强检索。

命令：python "D:\AI OS\l2-memory\scripts\search_enhanced.py" $ARGUMENTS

示例：
- search-enhanced "量子纠缠" → 搜索量子相关知识
- search-enhanced "机器学习" --k 10 → 返回 10 条结果
- search-enhanced "AI" --behavior-weight 0.5 → 调整行为权重
