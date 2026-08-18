# Bloomberg Bridge

Windows-side bridge for pushing Bloomberg Terminal data into the deployed app.

## Start here: connect from the app itself

The supported path needs nothing from this folder. On the computer that has the
Bloomberg Terminal, open the deployed app and go to **Data → Bloomberg →
Connexion d'un poste Bloomberg**. Name the machine, click **Générer un code de
connexion**, and paste the command it produces into PowerShell or a Jupyter cell
on that machine. The connector then finds Python, installs what is missing,
downloads `bridge.py`, exchanges the code for a per-terminal key, and starts
listening — no file to carry over, no key to type, no script to edit.

The end-user walkthrough lives in the app at `/glossary#bloomberg-connexion`.

Under the hood the app serves:

```text
GET  /bridge/bloomberg/connect.ps1?token=...          pre-filled PowerShell connector
GET  /bridge/bloomberg/connect.py?token=...           pre-filled Jupyter/Python connector
GET  /bridge/bloomberg/connector/bridge.py?token=...  the listener source (this file)
POST /bridge/bloomberg/enroll                         token -> per-terminal bridge key
```

The enrollment token is single-use and expires after an hour (default). The key
it issues is stored hashed server-side and written to
`%LOCALAPPDATA%\bt-bloomberg-bridge\config.json` on the Bloomberg computer, so
subsequent runs need no arguments at all. Revoke either from **Data → Bloomberg**.

A browser tab still cannot read Bloomberg on its own: `blpapi` only answers on
`localhost` of the machine running the Terminal. The connector is what closes
that gap, and the app is what builds and hands out the connector.

## Manual paths (fallback)

The Jupyter notebook kit avoids Docker, an EXE, and standalone `.py` execution:

```powershell
powershell -ExecutionPolicy Bypass -File .\prepare_jupyter_kit.ps1
```

That creates `dist\bloomberg-jupyter-kit.zip`. Open
`Bloomberg_Jupyter_Bridge.ipynb` on the Bloomberg computer and follow
`JUPYTER_RUNBOOK.md`. The notebook supports both manual uploads and an
app-controlled listener cell for the Bloomberg tab's queued jobs.

For a supervisor/Bloomberg-computer visit, use `FIELD_VISIT_RUNBOOK.md` and
package this folder with:

```powershell
powershell -ExecutionPolicy Bypass -File .\prepare_field_kit.ps1
```

That creates `dist\bloomberg-field-kit.zip`.

## Configuration

Enrollment writes the configuration for you. To wire a bridge by hand instead,
set environment variables on the Bloomberg machine:

```powershell
$env:BT_BLOOMBERG_ENDPOINT = "https://your-domain.example.com"
$env:BT_BLOOMBERG_BRIDGE_KEY = "bridge_key_from_/etc/bt/env"
$env:BT_BLOOMBERG_BRIDGE_ID = "bank-terminal-01"
```

Or enroll explicitly with a code generated in the app:

```powershell
python .\bridge.py enroll --endpoint "https://your-domain.example.com" --enroll-token "bbe_..."
```

Resolution order for every command is: CLI flag, then environment variable, then
the stored `config.json`.

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
