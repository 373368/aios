# l2-memory — L2 记忆层实现

> 知识处理核心：原语 / 声明式工作流 / 检索 / 归档 / 数据。按生命周期划分，废弃集中统一。

## 结构索引（2026-08-23 重划）

| 目录 | 职责 | 内容 | 状态 |
|---|---|---|---|
| `scripts/` | 活跃核心代码 | 原语（primitives.py）、检索（search_index/build_index/embedders/modelz）、导出（export-doubao/yuanbao/deepseek_export.js）、**算法簇**（memory_v1 → multiscale_v2/block_spin/density_space/flow_basin/rg_hierarchy/field_response_geometric/hybrid_retrieval/baselines，search_index 依赖链）、common.py（wfengine 公共层）、sys_classify_sdk + 回归 | ✅ 活跃 |
| `tasks/` | 抓取/追踪脚本 | scan_new / chunk_sessions / deepseek_split / fetch_arxiv\|github\|journal / track-*.ps1 / auto-archive.ps1 | ✅ 活跃 |
| `workflows/` | 声明式工作流 | wfengine.py + archive-daily/digest-daily/track-daily.yaml + wf-selfcheck/test-judge + prompts/（判断点模板） | ✅ 活跃 |
| `archive/` | **统一废弃区** | 所有不活跃内容集中（见下） | 🗄️ 不活跃 |
| `export/` | 原始对话导出中间态 | 豆包/元宝/DeepSeek 导出（gitignore） | 📦 数据 |
| `chunks/` | 超大会话分片（>60KB 按消息段切） | 供提炼以切片为单位 | 📦 数据 |
| `index/` | 语义索引生成物 | build_index 产物（gitignore） | 📦 数据 |
| `logs/` | 运行日志 | wfengine/工作流日志 | 📄 |
| `node_modules/` + `package.json` | JS 导出脚本依赖 | npm | 🔧 |
| `config.json` | 运行时配置 | API/model/路径 | ⚙️ |
| `start-server.ps1` | 常驻 opencode server 管理 | — | ✅ |

### archive/（统一废弃区）

| 子目录 | 内容 | 原位置 |
|---|---|---|
| `sdk/` | 废弃 SDK 层（archive/classify/landing/track_sdk；**SDK=多余中间层已废弃**，判断点由 agents 直调；common.py 已移出至 scripts/ 供 wfengine） | l2-memory/sdk |
| `eval-harness/` | 检索/行为评估框架（已收束 #11/#1b；如需重跑需 sys.path 加 scripts/） | l2-memory/eval-harness |
| `light/` | 旧轻量导出数据 | l2-memory/light |
| `legacy/` | 旧代码归档（含 LEGACY.md 与旧评估脚本） | l2-memory/legacy |
| `scripts/` | 独立评估/测试脚本（bench_v1_perf / eval_real_ranking / test_multiscale_v2 / synthetic_data / daily-reminder.ps1） | l2-memory/scripts |
| `docs/` | 历史规划文档（plan*.md / todo*.md） | l2-memory/tasks |

> 规则：**任何不再活跃的文件/脚本 → 移入 `archive/` 对应子目录，不散落各处**。archive 内脚本需要运行时 `sys.path` 指向 `scripts/`（模块依赖保留在 scripts）。

## 常用命令

```powershell
# 原语（写操作）
python scripts\primitives.py <name> '<json>'

# 声明式工作流（推荐入口）
python workflows\wfengine.py workflows\archive-daily.yaml source=doubao
python workflows\wfengine.py workflows\digest-daily.yaml dry_run=true
python workflows\wfengine.py workflows\track-daily.yaml source=arxiv query="cat:cs.AI"

# 检索 / 索引
python scripts\search_index.py "<查询>" --k 5 --json
python scripts\build_index.py

# 分类固化（06-系统）
python scripts\sys_classify_sdk.py            # 全量
python scripts\sys_classify_sdk.py <某页.md>  # 单页
```

详见 `declarative-workflows` skill（声明式三层）与 `control-classify` skill（C1-C6 分类固化）。