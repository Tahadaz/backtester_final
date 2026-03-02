param(
    [string]$OutputPath = "docs/CHATGPT_RUNTIME_SNAPSHOT.md"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

function Run-Or-Note {
    param([scriptblock]$Script)
    try {
        return (& $Script 2>&1 | Out-String).TrimEnd()
    } catch {
        return "[command failed] $($_.Exception.Message)"
    }
}

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add('# ChatGPT Runtime Snapshot')
$lines.Add('')
$lines.Add("Generated: $(Get-Date -Format o)")
$lines.Add("Repo: $repoRoot")
$lines.Add('')

$lines.Add('## Git')
$lines.Add('```text')
$gitInside = & git rev-parse --is-inside-work-tree 2>$null
if ($LASTEXITCODE -eq 0 -and ($gitInside | Out-String).Trim().ToLower() -eq 'true') {
    $lines.Add((Run-Or-Note { git branch --show-current }))
    $head = Run-Or-Note { git rev-parse --verify HEAD }
    if ($head.StartsWith('[command failed]')) {
        $lines.Add('HEAD: (repository has no commits yet)')
    } else {
        $lines.Add($head)
    }
    $lines.Add((Run-Or-Note { git status --short --untracked-files=no }))
} else {
    $lines.Add('Not a git worktree at this path.')
}
$lines.Add('```')
$lines.Add('')

$lines.Add('## Top-Level Tree')
$lines.Add('```text')
$lines.Add((Run-Or-Note { Get-ChildItem -Name }))
$lines.Add('```')
$lines.Add('')

$lines.Add('## Key Function Map')
$lines.Add('```text')
$lines.Add((Run-Or-Note { rg -n 'def run_pipeline|class BacktestEngine|def build_strategy|def default_param_catalog' core\quant_core }))
$lines.Add((Run-Or-Note { rg -n 'def create_run|def start_run|def execute_run|def _persist_pipeline_output' services\api\app\routers\runs.py services\worker\tasks\execute_run.py }))
$lines.Add('```')
$lines.Add('')

$keyFiles = @(
    "core/quant_core/pipeline.py",
    "core/quant_core/engine.py",
    "core/quant_core/strategy.py",
    "core/quant_core/optimize.py",
    "core/quant_core/plots.py",
    "services/worker/tasks/execute_run.py",
    "services/api/app/routers/runs.py",
    "services/api/app/models.py",
    "services/api/app/schemas/runs.py",
    "quant-backtesting-frontend/lib/api.ts",
    "services/ui_streamlit/app.py"
)

$lines.Add('## Key Files (First 220 Lines Each)')
$lines.Add('')

foreach ($file in $keyFiles) {
    if (-not (Test-Path $file)) {
        $lines.Add("### $file")
        $lines.Add('Missing')
        $lines.Add('')
        continue
    }

    $lines.Add("### $file")
    $lines.Add('```text')
    $lines.Add((Get-Content $file -TotalCount 220 | Out-String).TrimEnd())
    $lines.Add('```')
    $lines.Add('')
}

$outDir = Split-Path -Parent $OutputPath
if ($outDir -and -not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir | Out-Null
}

$lines -join "`r`n" | Set-Content -Path $OutputPath -Encoding UTF8
Write-Output "Wrote snapshot to $OutputPath"
