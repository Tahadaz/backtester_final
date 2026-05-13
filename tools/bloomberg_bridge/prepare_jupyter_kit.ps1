param(
  [string]$OutputDir = (Join-Path $PSScriptRoot "dist"),
  [string]$KitName = "bloomberg-jupyter-kit"
)

$ErrorActionPreference = "Stop"

$kitDir = Join-Path $OutputDir $KitName
$zipPath = Join-Path $OutputDir "$KitName.zip"

if (Test-Path -LiteralPath $kitDir) {
  Remove-Item -LiteralPath $kitDir -Recurse -Force
}
New-Item -ItemType Directory -Path $kitDir | Out-Null

$files = @(
  "Bloomberg_Jupyter_Bridge.ipynb",
  "JUPYTER_RUNBOOK.md",
  "README.md",
  "requirements.txt"
)

foreach ($file in $files) {
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $kitDir
}

if (Test-Path -LiteralPath $zipPath) {
  Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -Path (Join-Path $kitDir "*") -DestinationPath $zipPath

Write-Host "Jupyter kit written to $zipPath" -ForegroundColor Green
