# Bloomberg Jupyter Bridge Runbook

Use this when the Bloomberg computer has Jupyter but you do not want to run an EXE, Docker, or a standalone `.py` script.

## Before going to the Bloomberg computer

1. Bring the Jupyter kit file: `dist/bloomberg-jupyter-kit.zip`.
2. Know the deployed app URL, including `https://`.
3. Know the bridge key. Do not send it in email or chat. Type it into the notebook password prompt only.
4. Ask the supervisor to have Bloomberg Terminal open and logged in before you start.

## On the Bloomberg computer

1. Extract `bloomberg-jupyter-kit.zip` to a normal folder such as Desktop or Documents.
2. Open Jupyter Notebook or JupyterLab.
3. Open `Bloomberg_Jupyter_Bridge.ipynb`.
4. Run the package check cell.
   - If installs are blocked, continue only if the imports already show OK.
   - If `xbbg` cannot be installed or imported, ask IT to enable Bloomberg Python access in that Jupyter environment.
5. In the configuration cell, replace:
   - `https://YOUR_PUBLIC_APP_DOMAIN` with the deployed app URL.
   - `supervisor-bloomberg-terminal-01` with a useful terminal name if desired.
6. Run the configuration cell and type the bridge key into the password prompt.
7. Run the health check cell.
   - Expected result: HTTP 200.
   - If it times out, the bank network is still blocking the domain or route.
   - If it returns 403, the bridge key is wrong.
8. Run the upload helpers cell.
9. Run the mock upload test.
   - Expected result: HTTP 200 or 201 and a JSON response with batch details.
   - This proves Jupyter can send data to the deployed app before using Bloomberg.
10. Run the Bloomberg access cell.
    - Expected result: `OK: xbbg imported` and a small table for `ATW MA Equity`.
    - If it fails, Bloomberg is not available from this Jupyter Python kernel.
11. Run the normalization helper cell.
12. Run the one-security daily upload cell.
    - Start with `ATW MA Equity`.
    - Default Bloomberg OHLCV fields are `PX_OPEN`, `PX_HIGH`, `PX_LOW`, `PX_LAST`, and `VOLUME`.
    - Confirm rows are shown before upload.
13. Probe MASI availability.
    - Edit `MASI_SYMBOLS` if you have a fuller ticker list.
    - The notebook tests `MA Equity` and `MC Equity` suffixes.
14. Upload available MASI daily data.
    - Keep the first run small.
    - After confirming the app displays the data, expand the date range or ticker list.
15. Optional: run intraday and BQL cells.
    - Intraday availability depends on entitlements and history limits.
    - BQL availability depends on the local Bloomberg Python setup.

## What to expect

- The browser link alone cannot read Bloomberg data. The notebook must run on the Bloomberg computer because Bloomberg's local services and entitlements live there.
- The deployed app receives only uploaded Parquet batches and manifests over HTTPS.
- The app never receives the supervisor's Bloomberg login.
- The bridge key should be rotated after the visit if it was typed on a shared computer.

## Common failures

- `No module named xbbg`: the Jupyter Python environment does not have Bloomberg Python access.
- `blpapi` or session errors: Bloomberg Terminal is closed, not logged in, or the Bloomberg API is not available to that Python environment.
- Empty Bloomberg result: ticker, field, date range, or entitlement is unavailable.
- Upload timeout: batch is too large or network is unstable. Use fewer tickers or a shorter date range.
- HTTP 403: wrong bridge key.
- HTTP 404: wrong app URL or the deployed app version does not include the Bloomberg bridge routes.
