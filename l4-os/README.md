# L4-OS 服务层

AI-OS 的主机侧服务栈：**壳（AiosShell）+ Dashboard（前端）+ loopx 服务栈（8766/8767）+ opencode（4400）+ OpenScience（4401）**。

> 本文档是维护入口。改动壳代码、排查服务异常、理解数据流向，先读这里。

---

## 1. 架构总览

```
┌─ Dashboard (Vite/React, 前端) ─────────────────────────────┐
│  public/ (dist 构建产物，由壳托管)                            │
│  调 /status.json /api/* /graph-data /wfctl (相对路径)         │
└────────────────────────────────────────────────────────────┘
                            │ http://127.0.0.1:8799
┌─ AiosShell (WPF + WebView2 + HttpListener) ────────────────┐
│  唯一对外入口（回环 8799；非回环走密码认证）                    │
│  路由：/status.json→8767  /api/*→8767  /wfctl→wfctl.py       │
│        /graph-data→build_graph_data.py                      │
│  拉起/守护：8766 serve-status  8767 serve_chat               │
│             4400 opencode serve  4401 openscience serve     │
└────────────────────────────────────────────────────────────┘
```

- **Dashboard 代码**：`dashboard/`（src → 构建到 `dashboard/dist`，壳托管静态文件）
- **服务脚本**：`scripts/`（serve_chat.py 等）
- **壳**：`shell/AiosShell/MainWindow.xaml.cs`（全部逻辑单文件）
- **路径解析**：Python 侧 `<repo>/l2-memory/scripts/paths.py`、C# 侧 `shell/AiosShell/Paths.cs`；优先级 `AIOS_*` 环境变量 > `config.json` 的 `paths` 段 > 默认（仓库相对）

## 2. 端口与服务

| 端口 | 服务 | 命令/入口 | 数据源说明 |
|---|---|---|---|
| 8799 | 壳 HttpListener（http.sys，PID 4=System 正常） | AiosShell.exe | 对外唯一入口 |
| 8766 | loopx serve-status | `loopx serve-status`（壳启动） | ⚠️ run_history 投影，**只含跑过 run 的 goal** |
| 8767 | loopx Chat 服务（serve_chat.py） | `python scripts/serve_chat.py`（在 l4-os/ 下） | ✅ **权威数据源**：/status.json 投影全部 registry goal |
| 4400 | opencode serve（--hostname 127.0.0.1） | opencode serve | Chat 后端，iframe 直连 |
| 4401 | OpenScience serve | openscience serve | Chat 可选 agent（绑定方式待收紧验证） |

全局 registry：`<repo>/.loopx-runtime/registry.global.json`；局部 registry：`<repo>/.loopx/registry.json`（goals 数视本机运行情况）。

## 3. 壳代理路由（MainWindow.xaml.cs ServeAsync）

| 路径 | 处理 | 目标 |
|---|---|---|
| `/status.json` `/healthz` | ProxyToStatusAsync | **8767 serve_chat**（勿改回 8766！见 §4） |
| `/graph-data` | ServeGraphDataAsync | build_graph_data.py |
| `/wfctl` | ServeWfctlAsync | wfctl.py |
| `/api/*` | ProxyToChatAsync | 8767 serve_chat |
| `/goal/` `/gate/` `/config/` | ServeLoopxControlAsync | loopx CLI（远程控制写端点） |
| 其余 | 静态文件 | dashboard/dist |

**认证**：桌面回环直放行；非回环须过 `/login` 密码 + session cookie（`AIOS_REMOTE_PASSWORD` → 回退 `OPENCODE_SERVER_PASSWORD`）。

## 4. 2026-09-08 修复记录（卡死 + 数据源，三处根因）

**现象**：后台进程极易卡死；刷新/关工作台即卡；API 极慢（挂 100s）；UI 看不到新发的 goal；报 "LoopX Chat 服务暂时不可用（HTTP 500）"。

### 根因与修复（全部在 MainWindow.xaml.cs）

| # | 根因 | 修复 |
|---|---|---|
| 1 | `RedirectStandardOutput/Error=true` 但从不读管道 → stderr 缓冲（~4KB）填满 → 子进程写日志永久阻塞卡死 | 新增 `DrainProcessPipes(Process p)`（Output/ErrorDataReceived 空回调 + Begin*ReadLine），应用到 StartChatServer/StartOpencodeServer/StartOpenScienceServer |
| 2 | 代理用 `new HttpClient()` 默认 100s 超时，upstream 卡住时 UI 全部挂起 | 两代理函数改 `Timeout = 8s` + try/catch → 502 `{"ok":false,"error":"chat upstream unavailable"}` 快速失败 |
| 3 | /status.json 代理 8766 serve-status（run_history 投影只含跑过的 goal）→ UI 看不到新 goal | 转发目标 8766→8767（serve_chat 的 build_chat_status_projection 遍历全部 registry goal） |

**验证**：5 端口全监听；经壳 /status.json → goal 数正确；连续 5 次请求 128-254ms 全 200。

### 教训（后续维护必看）
- **数据源选型**：要"全部 goal"用 8767 serve_chat；8766 serve-status 只反映有 run 历史的活动。
- **子进程重定向必须排空**：任何 Start*Server 若开 Redirect，必须挂 DrainProcessPipes，否则必卡。
- **改代码必须同步重建**：Debug + Release + publish 三个 exe 都要更新。

## 5. 运维手册

### 重启服务栈
1. 关 AiosShell（OnClosed 连带 Kill 全部子服务）
2. 重开 AiosShell（OnLoaded 幂等拉起 5 服务：`PortIsListeningAsync` 已监听则跳过）

### 手动起 serve_chat（排查时）
```powershell
$env:PYTHONUTF8="1"
Start-Process cmd -ArgumentList '/c start /b python "<repo>\l4-os\scripts\serve_chat.py" > "<log>\serve_chat.log" 2>&1'
```
注意：须用 `cmd start /b` 脱离父进程（否则进程可能随父 shell 退出被回收）；日志重定向到任意可写文件。

### 验证命令
```powershell
# 端口全监听
netstat -ano | Select-String ":8799|:8766|:8767|:4400|:4401"
# 权威数据源（serve_chat 直连）
Invoke-WebRequest http://127.0.0.1:8767/status.json
# 经壳代理
Invoke-WebRequest http://127.0.0.1:8799/status.json
```

### 构建
工作目录：`shell/AiosShell/`（或直接指定 csproj 路径）。
```powershell
dotnet build -c Debug                      # 快速验证
dotnet publish -c Release -o "bin\Release\net10.0-windows\publish"   # 发布版
```
要求：.NET 10 SDK + WebView2 Runtime（Win10/11 通常自带；无则装 Evergreen Runtime）。

## 6. 已知遗留

- serve_chat 偶发卡死若复现：loopx 库内部阻塞（ACP 拉会话 5s 超时重试链）需另查
- 壳周期性消失死因未最终确认（Windows RestartManager 事件 10001/10010，疑似 wslinstaller.exe 触发，非被杀）
- 4401 OpenScience 绑定收紧需运行时验证
- 协议不通背景：loopx 0.5.4 的 ACP 用旧式显式 session/new，与 codex 系 ACP 不兼容；B 路线 osrun-goal.py custom-runner 已验证跑通
- 远程控制写端点 /goal/ /gate/ /config/ 已实现（非回环访问需密码认证）

## 7. 2026-09-17 修复记录：Debug 版打开白屏

- **现象**：Debug exe 打开后整页白屏（Release/publish 正常）。
- **根因**：Debug 二进制停留旧构建，缺 `/wfctl/agents` 路由 → 该路径回退成 `wfctl list`（返回数组）→ 前端 `data.goals[0]` 未守护访问抛 TypeError → React 整树卸载白屏（控制台证据：`Cannot read properties of undefined (reading '0')`）。
- **修复**：① `workflows-panel.tsx` `loadAgents` 加边界校验（响应非 `declarations`/`goals` 数组即报错降级显示，不再崩页）+ `registered_agents?.length` 守护；② 重建 Debug/Release/publish 三份 exe；③ `publish\dashboard-dist` 同步最新 `dist`。
- **纪律**：改壳代码必须同步重建 **Debug + Release + publish** 三份；前端已加降级防线（接口不匹配只报错不白屏）。
