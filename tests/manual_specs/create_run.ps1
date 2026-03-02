$API="http://127.0.0.1:8000"
$headers = @{
  "Content-Type"="application/json"
  "x-api-key"=$env:API_KEY
}

$datasetId="25b41c96-fbd9-4666-9918-d4d3a8557c97"
$specPath="tests/manual_specs/spec_iam_obv.json"

$specText = Get-Content $specPath -Raw

# sha256(spec_json text) -> spec_hash
$bytes = [System.Text.Encoding]::UTF8.GetBytes($specText)
$sha = [System.Security.Cryptography.SHA256]::Create()
$hash = ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join ""

$body = @{
  spec_json = ($specText | ConvertFrom-Json)
  spec_hash = $hash
  dataset_id = $datasetId
} | ConvertTo-Json -Depth 50

Invoke-RestMethod -Method Post -Uri "$API/runs" -Headers $headers -Body $body
