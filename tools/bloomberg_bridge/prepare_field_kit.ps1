param(
  [string]$OutputDir = (Join-Path $PSScriptRoot "dist"),
  [string]$KitName = "bloomberg-field-kit"
)

$ErrorActionPreference = "Stop"

$kitDir = Join-Path $OutputDir $KitName
$zipPath = Join-Path $OutputDir "$KitName.zip"

if (Test-Path -LiteralPath $kitDir) {
  Remove-Item -LiteralPath $kitDir -Recurse -Force
}
New-Item -ItemType Directory -Path $kitDir | Out-Null

$files = @(
  "README.md",
  "FIELD_VISIT_RUNBOOK.md",
  "JUPYTER_RUNBOOK.md",
  "Bloomberg_Jupyter_Bridge.ipynb",
  "bridge.py",
  "requirements.txt",
  "check_connection.ps1",
  "start_listener.ps1",
  "flush_spool.ps1"
)

foreach ($file in $files) {
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $kitDir
}

$exePath = Join-Path $PSScriptRoot "dist\bt-bloomberg-bridge.exe"
if (Test-Path -LiteralPath $exePath) {
  Copy-Item -LiteralPath $exePath -Destination $kitDir
}

if (Test-Path -LiteralPath $zipPath) {
  Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -Path (Join-Path $kitDir "*") -DestinationPath $zipPath

Write-Host "Field kit written to $zipPath" -ForegroundColor Green
