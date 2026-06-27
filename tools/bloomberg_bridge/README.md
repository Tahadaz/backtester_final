# Bloomberg Bridge

No-Docker Windows-side bridge for pushing Bloomberg Terminal data into the deployed app.

The safest workflow on a locked-down Bloomberg computer is the Jupyter notebook kit. It avoids Docker, an EXE, and standalone `.py` execution while still running on the Bloomberg computer where local Bloomberg access exists.

```powershell
powershell -ExecutionPolicy Bypass -File .\prepare_jupyter_kit.ps1
```

That creates `dist\bloomberg-jupyter-kit.zip`. Open `Bloomberg_Jupyter_Bridge.ipynb` on the Bloomberg computer and follow `JUPYTER_RUNBOOK.md`. The notebook supports both manual uploads and an app-controlled listener cell for the Bloomberg tab's queued jobs.

The browser link alone cannot directly read Bloomberg Terminal data. The notebook, script, or listener must run on the Bloomberg computer and upload data over HTTPS.

For a supervisor/Bloomberg-computer visit, use `FIELD_VISIT_RUNBOOK.md` and package this folder with:

```powershell
powershell -ExecutionPolicy Bypass -File .\prepare_field_kit.ps1
```

That creates `dist\bloomberg-field-kit.zip`.

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

You can run the guided check:

```powershell
.\check_connection.ps1 -Endpoint "https://your-domain.example.com" -BridgeId "supervisor-terminal-01"
```

Or run the bridge directly:

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

## App-Controlled Listener

Run this on the Bloomberg Terminal computer after Bloomberg is open and logged in:

```powershell
.\start_listener.ps1 -Endpoint "https://your-domain.example.com" -BridgeId "supervisor-terminal-01"
```

Or run the bridge directly:

```powershell
.\bt-bloomberg-bridge.exe listen
```

Or with Python:

```powershell
python .\bridge.py listen
```

The listener uses outbound HTTPS only. It polls:

```text
GET /bridge/bloomberg/jobs/next
POST /bridge/bloomberg/jobs/{job_id}/status
POST /bridge/bloomberg/heartbeat
```

The Data page can then queue preflight, discovery, backfill, and refresh jobs. The bridge only runs structured Bloomberg requests from the job spec; it does not run shell commands from the app.
