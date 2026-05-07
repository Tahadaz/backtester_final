[CmdletBinding()]
param(
    [string]$TargetRepoPath = "C:\Users\taha\Downloads\dashboard",
    [string]$BasePath = "/dashboard",
    [string]$CommitMessage = "",
    [switch]$PreviewOnly,
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"

$frontendRoot = Split-Path -Parent $PSScriptRoot
$sourceDir = Join-Path $frontendRoot "out-pages"

if (-not (Test-Path $frontendRoot)) {
    throw "Frontend root not found: $frontendRoot"
}

if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
    $CommitMessage = "Update static dashboard $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}

Write-Host "Building public static artifact from $frontendRoot"

Push-Location $frontendRoot
try {
    $env:NEXT_PUBLIC_BASE_PATH = $BasePath

    npm run build:pages
    if ($LASTEXITCODE -ne 0) {
        throw "build:pages failed with exit code $LASTEXITCODE"
    }

    npm run prune:pages
    if ($LASTEXITCODE -ne 0) {
        throw "prune:pages failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path $sourceDir)) {
    throw "Static artifact not found: $sourceDir"
}

if ($PreviewOnly) {
    Write-Host "Preview complete. Static artifact is ready at $sourceDir"
    return
}

if (-not (Test-Path $TargetRepoPath)) {
    throw "Target repo path not found: $TargetRepoPath"
}

$gitDir = Join-Path $TargetRepoPath ".git"
if (-not (Test-Path $gitDir)) {
    throw "Target path is not a git repository: $TargetRepoPath"
}

Write-Host "Syncing artifact to $TargetRepoPath"

& robocopy $sourceDir $TargetRepoPath /MIR /XD .git | Out-Null
$robocopyExitCode = $LASTEXITCODE
if ($robocopyExitCode -gt 7) {
    throw "robocopy failed with exit code $robocopyExitCode"
}

New-Item -Path (Join-Path $TargetRepoPath ".nojekyll") -ItemType File -Force | Out-Null

git -C $TargetRepoPath add -A
if ($LASTEXITCODE -ne 0) {
    throw "git add failed with exit code $LASTEXITCODE"
}

git -C $TargetRepoPath diff --cached --quiet
$hasChanges = $LASTEXITCODE -eq 1
if (-not $hasChanges) {
    Write-Host "No changes to commit."
    return
}

git -C $TargetRepoPath commit -m $CommitMessage
if ($LASTEXITCODE -ne 0) {
    throw "git commit failed with exit code $LASTEXITCODE"
}

if ($NoPush) {
    Write-Host "Commit created locally. Push skipped."
    return
}

git -C $TargetRepoPath push origin main
if ($LASTEXITCODE -ne 0) {
    throw "git push failed with exit code $LASTEXITCODE"
}

Write-Host "Dashboard publish completed."
