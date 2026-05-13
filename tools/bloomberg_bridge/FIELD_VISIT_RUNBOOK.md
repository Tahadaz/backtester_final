# Bloomberg Field Visit Runbook

Use this when you are at the Bloomberg Terminal computer and cannot access the development environment.

## What To Send Before The Visit

Send your supervisor or IT:

- The app URL: `https://YOUR_PUBLIC_APP_DOMAIN`
- A short purpose note: outbound HTTPS Bloomberg data bridge for approved data ingestion.
- The bridge field kit zip.
- A note that the bridge requires no Docker and no inbound connection to the bank computer.
- A note that Bloomberg must be open and logged in during the test.

Do not email the bridge key casually. Bring it separately or use an approved secure channel.

## What To Bring

- `bt-bloomberg-bridge.exe` if available.
- `bridge.py` and `requirements.txt` as Python fallback.
- These helper scripts:
  - `check_connection.ps1`
  - `start_listener.ps1`
  - `flush_spool.ps1`
- Your bridge key.
- Your exact app domain.

## Step 1 - Open Bloomberg

Ask the supervisor to:

1. Log into Windows.
2. Open Bloomberg Terminal.
3. Confirm Bloomberg is fully logged in.
4. Keep Bloomberg open.

## Step 2 - Open The App

Open:

```text
https://YOUR_PUBLIC_APP_DOMAIN/data
```

Go to:

```text
Data -> Bloomberg
```

Expected result:

- The page opens.
- The Bloomberg tab is visible.
- Bridge status may say offline before the listener starts.

If the site does not open, stop and ask IT. The bridge will probably be blocked too.

## Step 3 - Extract The Bridge Folder

Extract the field kit to a simple folder, for example:

```text
Desktop\BloombergBridge
```

Open PowerShell in that folder.

## Step 4 - Run Connectivity And Mock Test

Run:

```powershell
.\check_connection.ps1 -Endpoint "https://YOUR_PUBLIC_APP_DOMAIN" -BridgeId "supervisor-terminal-01"
```

The script will ask for the bridge key if it is not already set in the environment.

Expected result:

- Health check returns `200`.
- Mock upload creates a Bloomberg batch in the app.
- Data -> Bloomberg shows a recent batch and indexed series for `ATW MA Equity` / `PX_LAST`.

Common failures:

- `401`: wrong bridge key.
- `404`: deployed app does not include the bridge routes.
- `503`: deployed API is missing `BLOOMBERG_BRIDGE_API_KEY`.
- Network or Fortinet page: IT/network issue.

## Step 5 - Start The Listener

Keep PowerShell open and run:

```powershell
.\start_listener.ps1 -Endpoint "https://YOUR_PUBLIC_APP_DOMAIN" -BridgeId "supervisor-terminal-01"
```

The script will ask for the bridge key if needed.

Expected result:

- The command stays running.
- In the app, Data -> Bloomberg shows the bridge online or busy.
- The bridge ID is `supervisor-terminal-01`.

If this PowerShell window closes, queued app jobs will not run until the listener is started again.

## Step 6 - Run Preflight From The App

In Data -> Bloomberg:

1. Click `Preflight`.
2. Watch the Jobs table.

Expected result:

```text
queued -> leased/running -> succeeded
```

If it fails, inspect the job error:

- `xbbg is not available`: Bloomberg Python API package is not available.
- Bloomberg session error: Terminal may not be logged in or API entitlement is missing.
- Upload/network error: check Fortinet, proxy, bridge key, or app availability.

## Step 7 - Run MASI Discovery

Use conservative settings first:

```text
Job: Discovery
Universe: MASI all
Frequency: Daily
Mode: Discovery only
Fields:
PX_LAST
VOLUME
```

Click `Queue job`.

Expected result:

- The bridge probes MASI Bloomberg candidates.
- Some symbols may be available, unavailable, partial, or not entitled.
- This is normal.

## Step 8 - Run One Small Real Backfill

Before trying all MASI stocks, test one stock:

```text
Job: Backfill
Universe: Selected stocks
Symbols: ATW
Frequency: Daily
Mode: Backfill missing
Fields:
PX_LAST
VOLUME
Start: 2024-01-01
End: blank
```

Expected result:

- Job succeeds.
- Recent batches increase.
- Indexed series increase.
- Row counts and date range update.

## Step 9 - Run Larger MASI Daily Backfill

Only after the single-stock test succeeds:

```text
Job: Backfill
Universe: MASI all
Frequency: Daily
Mode: Backfill missing
Fields:
PX_LAST
VOLUME
Start: 2010-01-01
End: blank
```

Expected result:

- This can take time.
- Some securities may fail because of missing mappings or entitlement.
- Successful chunks still upload and index.

## Step 10 - Intraday Testing

Do not start with all MASI minute history.

First:

```text
Job: Discovery
Universe: Selected stocks
Symbols: ATW
Frequency: Hourly
Mode: Discovery only
Fields:
PX_OPEN
PX_HIGH
PX_LOW
PX_LAST
VOLUME
```

Then test minute data only for a small recent range.

Expected result:

- Hourly/minute availability may be limited.
- Bloomberg entitlement and exchange coverage decide what exists.

## If Uploads Are Spooled

If PowerShell says uploads were spooled, later run:

```powershell
.\flush_spool.ps1 -Endpoint "https://YOUR_PUBLIC_APP_DOMAIN"
```

The script will ask for the bridge key if needed.

## Clean Success Path

```text
App opens
Health check returns 200
Mock upload appears
Listener shows online
Preflight succeeds
Daily MASI discovery completes
Single-stock backfill succeeds
Larger MASI backfill can be attempted
```

