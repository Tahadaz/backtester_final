# Bloomberg Bridge

No-Docker Windows-side bridge for pushing Bloomberg Terminal data into the deployed app.

## Configuration

Set environment variables on the Bloomberg machine:

```powershell
$env:BT_BLOOMBERG_ENDPOINT = "https://your-domain.example.com"
$env:BT_BLOOMBERG_BRIDGE_KEY = "bridge_key_from_/etc/bt/env"
$env:BT_BLOOMBERG_BRIDGE_ID = "bank-terminal-01"
```

The bridge posts to:

```text
POST /bridge/bloomberg/batches
```

## Mock Smoke Test

```powershell
python .\bridge.py mock `
  --security "ATW MA Equity" `
  --field PX_LAST `
  --start 2026-05-01 `
  --end 2026-05-05 `
  --upload
```

## Bloomberg Examples

Historical series through `xbbg`:

```powershell
python .\bridge.py bdh `
  --security "ATW MA Equity" `
  --field PX_LAST `
  --field VOLUME `
  --start 2024-01-01 `
  --end 2026-05-12 `
  --upload
```

BQL tabular response:

```powershell
python .\bridge.py bql --query "get(px_last) for(['ATW MA Equity'])" --upload
```

## Package As EXE

```powershell
python -m pip install -r requirements.txt pyinstaller
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

The executable is written to `dist\bt-bloomberg-bridge.exe`.
