param(
  [string]$Endpoint = $env:BT_BLOOMBERG_ENDPOINT,
  [string]$BridgeKey = $env:BT_BLOOMBERG_BRIDGE_KEY,
  [string]$BridgeId = $(if ($env:BT_BLOOMBERG_BRIDGE_ID) { $env:BT_BLOOMBERG_BRIDGE_ID } else { "supervisor-terminal-01" }),
  [string]$SmokeSecurity = "ATW MA Equity",
  [string]$SmokeField = "PX_LAST",
  [string]$SmokeStart = "2026-05-01",
  [string]$SmokeEnd = "2026-05-05"
)

$ErrorActionPreference = "Stop"

function Read-SecretPlainText([string]$Prompt) {
  $secure = Read-Host -Prompt $Prompt -AsSecureString
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try {
    [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
  }
}

function Require-Value([string]$Name, [string]$Value) {
  if ([string]::IsNullOrWhiteSpace($Value)) {
    throw "$Name is required"
  }
}

if ([string]::IsNullOrWhiteSpace($Endpoint)) {
  $Endpoint = Read-Host -Prompt "App endpoint, for example https://your-domain.example.com"
}
if ([string]::IsNullOrWhiteSpace($BridgeKey)) {
  $BridgeKey = Read-SecretPlainText "Bloomberg bridge key"
}

$Endpoint = $Endpoint.TrimEnd("/")
Require-Value "Endpoint" $Endpoint
Require-Value "BridgeKey" $BridgeKey
Require-Value "BridgeId" $BridgeId

$env:BT_BLOOMBERG_ENDPOINT = $Endpoint
$env:BT_BLOOMBERG_BRIDGE_KEY = $BridgeKey
$env:BT_BLOOMBERG_BRIDGE_ID = $BridgeId

Write-Host "Testing deployed bridge health..." -ForegroundColor Cyan
$headers = @{
  "X-Bloomberg-Bridge-Key" = $BridgeKey
  "X-Bloomberg-Bridge-Id" = $BridgeId
}
$healthUrl = "$Endpoint/bridge/bloomberg/health"
$health = Invoke-WebRequest -UseBasicParsing -Method Get -Uri $healthUrl -Headers $headers
Write-Host "Health OK: HTTP $($health.StatusCode)" -ForegroundColor Green

$exe = Join-Path $PSScriptRoot "bt-bloomberg-bridge.exe"
$bridgePy = Join-Path $PSScriptRoot "bridge.py"

Write-Host "Running mock upload..." -ForegroundColor Cyan
if (Test-Path -LiteralPath $exe) {
  & $exe mock --security $SmokeSecurity --field $SmokeField --start $SmokeStart --end $SmokeEnd --upload
} elseif (Test-Path -LiteralPath $bridgePy) {
  & python $bridgePy mock --security $SmokeSecurity --field $SmokeField --start $SmokeStart --end $SmokeEnd --upload
} else {
  throw "Neither bt-bloomberg-bridge.exe nor bridge.py was found in $PSScriptRoot"
}

if ($LASTEXITCODE -ne 0) {
  throw "Mock upload failed with exit code $LASTEXITCODE"
}

Write-Host "Connection and mock upload succeeded. Check Data -> Bloomberg in the app." -ForegroundColor Green
