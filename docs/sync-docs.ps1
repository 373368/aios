# 单向同步：Obsidian vault 权威 → 项目 docs/ 镜像（只读参考）
$srcArch = "D:\ObsidianVault\04-项目\ai-os\02-架构设计"
$srcDec = "D:\ObsidianVault\04-项目\ai-os\04-决策记录"
$dst = "D:\AI OS\docs"
foreach ($f in @("05-工作流规范.md", "12-原语与SDK扩展规范.md", "13-系统现状与组织结构.md", "14-与业界对照.md", "15-专用agent设计规范.md")) {
    Copy-Item -LiteralPath "$srcArch\$f" -Destination "$dst\规范\$f" -Force
}
foreach ($f in @("2026-08-17-AI-OS定性为OS内核.md", "2026-08-23-主控瘦身-skill按需加载评估.md")) {
    Copy-Item -LiteralPath "$srcDec\$f" -Destination "$dst\决策\$f" -Force
}
Write-Output "docs 镜像同步完成"