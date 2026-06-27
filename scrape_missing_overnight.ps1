# Overnight BVC scrape -> ingest -> verify. Run once and walk away.
#
#   powershell -ExecutionPolicy Bypass -File .\scrape_missing_overnight.ps1
#
# Edit the three values below if your paths/keys ever change, then leave it running.

$ErrorActionPreference = "Continue"

# ---- CONFIG ---------------------------------------------------------------
$Keys      = "AIzaSyB2U4KRhDvxigp0SnIv7tZh6_2oHMXr9mw,AIzaSyBerFKd4f-mct7Y8wq5mImddnAxGakS4b0,AIzaSyDon0BRNxYYx1TuxXoLYjyuTtfSAgNXh-s"
$Model     = "gemma-4-31b-it"            # the scraper's native/tuned model (gemini-* returns output the parser can't use -> empty)
$FamaDir   = "C:\Users\taha\Downloads\fama french"
$RepoDir   = "C:\Users\taha\Downloads\backtester_signal_engine_autoaccept"
$Workbook  = "C:\Users\taha\Downloads\fundamental_data_all_structured_market_formula_factors.xlsx"
# TIGHT scope: only the names that genuinely need a BVC balance sheet. Finishes in <1h on free-tier keys.
$Symbols   = "AFM,INV,NKL,VCN,IMO,SNP,STR"
$Companies = "AFMA;Involys;Ennakl;Vicenne;Immorente Invest;SNEP;Stroc Industrie"
$StartYear = 2024
$EndYear   = 2025
# ---------------------------------------------------------------------------

$ts  = Get-Date -Format "yyyyMMdd_HHmmss"
$log = Join-Path $RepoDir "logs\overnight_bvc_$ts.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
function Log($m) { $line = "$(Get-Date -Format o)  $m"; Write-Host $line; Add-Content -Path $log -Value $line }

# Keep the machine awake for the whole run (released when the script exits).
$sig = '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint e);'
$es  = Add-Type -MemberDefinition $sig -Name Power -Namespace Win32 -PassThru
[void]$es::SetThreadExecutionState([uint32]2147483649)  # ES_CONTINUOUS(0x80000000) | ES_SYSTEM_REQUIRED(0x1)
Log "Sleep suppression enabled. Log: $log"

$env:GEMINI_API_KEYS            = $Keys
$env:GEMINI_API_KEY             = ($Keys -split ",")[0]
$env:FUNDAMENTAL_LLM_API_KEYS   = $Keys
$env:FUNDAMENTAL_LLM_MODEL      = $Model
$env:PYTHONUTF8                 = "1"

# ---- STEP 1: scrape (the long part) ---------------------------------------
Log "STEP 1/2  Scraping $($Symbols.Split(',').Count) symbols ($StartYear-$EndYear, model=$Model)..."
$famaPy = Join-Path $FamaDir ".venv\Scripts\python.exe"
& $famaPy (Join-Path $FamaDir "run_full_pipeline.py") `
    --symbols $Symbols --companies $Companies `
    --start-year $StartYear --end-year $EndYear --period-types annual `
    --model $Model --factor-output $Workbook 2>&1 | Tee-Object -FilePath $log -Append
$scrapeExit = $LASTEXITCODE
Log "STEP 1 finished (exit=$scrapeExit). Workbook: $Workbook"

# ---- STEP 2: ingest + verify + revalue ------------------------------------
if (Test-Path $Workbook) {
    Log "STEP 2/2  Ingesting + re-verifying + revaluing..."
    Push-Location $RepoDir
    $env:DATABASE_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"
    & python (Join-Path $RepoDir "scripts\bvc_overnight_ingest.py") $Workbook 2>&1 | Tee-Object -FilePath $log -Append
    Pop-Location
    Log "STEP 2 finished."
} else {
    Log "ERROR: workbook not produced; skipping ingest."
}

[void]$es::SetThreadExecutionState([uint32]2147483648)  # ES_CONTINUOUS -> allow sleep again
Log "ALL DONE. Review $log in the morning."
