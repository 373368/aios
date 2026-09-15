# Auto-archive driver v5 (ASCII + UTF-8 BOM): scripts orchestrate, LLM only distills via &.
#   Lock: single-instance mutex (no concurrent runs)
#   A: export new sessions (browser scripts, zero LLM)
#   B: scan + gate -> 0 candidates = done (zero token)
#   C: headless distill via & opencode run --command distill (kb-archivist, NO browser)
#   D: index + behavior record by distill command
$ErrorActionPreference = 'Stop'
$node = "C:\Program Files\nodejs\node.exe"
$python = "C:\Users\asus\AppData\Local\Programs\Python\Python312\python.exe"
$opencode = "C:\Program Files\nodejs\node_global\node_modules\opencode-ai\bin\opencode.exe"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$logDir = "D:\ObsidianVault\03-日志"
$log = Join-Path $logDir "archive-auto.log"
$runLog = Join-Path $logDir ("archive-auto-" + (Get-Date -Format 'yyyyMMdd-HHmm') + ".log")

function Log([string]$msg) { "[$stamp] $msg" | Out-File -FilePath $log -Append -Encoding utf8 }

# model 单源：config.json models.default（对齐 modelz 原语；缺省回退默认值）
function Get-DefaultModel {
    $cfg = Get-Content "D:\AI OS\l2-memory\config.json" -Raw -Encoding utf8 | ConvertFrom-Json
    if ($cfg.models.default) { return $cfg.models.default }
    return "volcengine-agent-plan/deepseek-v4-flash"
}

# single-instance lock
$mutex = New-Object System.Threading.Mutex($false, "Global\OpenCodeAutoArchive")
if (-not $mutex.WaitOne(0)) { exit 0 }

try {
    Log "== auto-archive start =="

    # A: export (browser scripts, zero LLM)
    & $node "D:\AI OS\l2-memory\scripts\export-doubao.js"  2>&1 | Out-File -FilePath $runLog -Append -Encoding utf8
    Log "export-doubao exit=$LASTEXITCODE"
    & $node "D:\AI OS\l2-memory\scripts\export-yuanbao.js" 2>&1 | Out-File -FilePath $runLog -Append -Encoding utf8
    Log "export-yuanbao exit=$LASTEXITCODE"

    # A3: DeepSeek split — 把手动导出的合并 JSON 拆成逐会话 MD
    $dsImportDir = "D:\AI OS\l2-memory\import"
    $dsExportDir = "D:\AI OS\l2-memory\export\DeepSeek"
    if (Test-Path $dsImportDir) {
        Get-ChildItem "$dsImportDir\deepseek-*.json" -ErrorAction SilentlyContinue | ForEach-Object {
            Log "deepseek split: $($_.Name)"
            & $python "D:\AI OS\l2-memory\tasks\deepseek_split.py" $_.FullName -o $dsExportDir 2>&1 | Out-File -FilePath $runLog -Append -Encoding utf8
            Remove-Item $_.FullName -Force
        }
    }

    # A4: 超大会话分片 — >60KB 会话切成 ≤60KB 片，避免单次上下文过大导致蒸馏慢/卡死
    & $python "D:\AI OS\l2-memory\tasks\chunk_sessions.py" 2>&1 | Out-File -FilePath $runLog -Append -Encoding utf8
    Log "chunk exit=$LASTEXITCODE"

    # B: scan + gate
    $scan = & $python "D:\AI OS\l2-memory\tasks\scan_new.py" --json 2>&1
    $scan | Out-File -FilePath $runLog -Append -Encoding utf8
    $report = $scan -join "`n" | ConvertFrom-Json
    $total = ($report.PSObject.Properties | ForEach-Object { $_.Value.candidates.Count } | Measure-Object -Sum).Sum
    Log "candidates=$total"

    if ($total -eq 0) {
        Log "no candidates, done (zero token)"
        exit 0
    }

    # C: headless distill via command (subagent kb-archivist, NO browser)
    Log "found $total candidates, launching distill command"
    # model 单源（config.json models.default），避免落到讯飞 MaaS Qwen3.5-2B（不支持 tools → 400/卡死）
    $model = Get-DefaultModel
    $out = & $opencode run -m $model --dir "D:\AI OS\l1-control\opencode" --command distill --format json --dangerously-skip-permissions 2>&1
    $code = $LASTEXITCODE
    $out | Out-File -FilePath $runLog -Append -Encoding utf8
    Log "distill exit=$code"
    exit $code

} catch {
    Log "FAIL: $($_.Exception.Message)"
    exit 1
} finally {
    $mutex.ReleaseMutex()
}