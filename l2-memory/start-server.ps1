# 启动常驻 opencode server（固定密码，与 config.json server 段一致）
# 用法: powershell -File start-server.ps1
# opencode 可执行解析：config.json paths.opencode_exe > 环境变量 AIOS_OPENCODE_EXE > PATH
$cfg = Get-Content (Join-Path $PSScriptRoot "config.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$exe = $cfg.paths.opencode_exe
if (-not $exe) { $exe = $env:AIOS_OPENCODE_EXE }
if (-not $exe) { $exe = "opencode" }

# 杀掉旧实例（端口占用）
$conn = Get-NetTCPConnection -LocalPort $cfg.server.port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conn) {
    Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    Write-Host "killed old server PID $($c.OwningProcess)"
}
Start-Sleep 1

$env:OPENCODE_SERVER_PASSWORD = $cfg.server.password
$env:OPENCODE_SERVER_USERNAME = $cfg.server.username
Start-Process -FilePath $exe -ArgumentList "serve","--port","$($cfg.server.port)" -WindowStyle Hidden
Start-Sleep 6

try {
    $r = Invoke-WebRequest -Uri "http://$($cfg.server.host):$($cfg.server.port)/global/health" `
        -Headers @{Authorization="Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("$($cfg.server.username):$($cfg.server.password)"))} `
        -UseBasicParsing -TimeoutSec 5
    Write-Host "server OK: $($r.Content)"
} catch {
    Write-Host "server start failed: $_"
}