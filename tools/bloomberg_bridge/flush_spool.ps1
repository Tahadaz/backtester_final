param(
  [string]$Endpoint = $env:BT_BLOOMBERG_ENDPOINT,
  [string]$BridgeKey = $env:BT_BLOOMBERG_BRIDGE_KEY
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

if ([string]::IsNullOrWhiteSpace($Endpoint)) {
  $Endpoint = Read-Host -Prompt "App endpoint, for example https://your-domain.example.com"
}
if ([string]::IsNullOrWhiteSpace($BridgeKey)) {
  $BridgeKey = Read-SecretPlainText "Bloomberg bridge key"
}

$Endpoint = $Endpoint.TrimEnd("/")
if ([string]::IsNullOrWhiteSpace($Endpoint)) { throw "Endpoint is required" }
if ([string]::IsNullOrWhiteSpace($BridgeKey)) { throw "BridgeKey is required" }

$env:BT_BLOOMBERG_ENDPOINT = $Endpoint
$env:BT_BLOOMBERG_BRIDGE_KEY = $BridgeKey

$exe = Join-Path $PSScriptRoot "bt-bloomberg-bridge.exe"
$bridgePy = Join-Path $PSScriptRoot "bridge.py"

Write-Host "Flushing Bloomberg bridge spool..." -ForegroundColor Cyan
if (Test-Path -LiteralPath $exe) {
  & $exe flush-spool
} elseif (Test-Path -LiteralPath $bridgePy) {
  & python $bridgePy flush-spool
} else {
  throw "Neither bt-bloomberg-bridge.exe nor bridge.py was found in $PSScriptRoot"
}
