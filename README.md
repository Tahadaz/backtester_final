# backtester_final

## How to run UI

1. Start infra + API + worker:

```bash
docker compose -f infra/docker-compose.yml up --build
```

2. In another shell (repo root), run Streamlit:

```bash
set API_URL=http://127.0.0.1:8000
streamlit run services/ui_streamlit/app.py
```

PowerShell equivalent:

```powershell
$env:API_URL = "http://127.0.0.1:8000"
streamlit run services/ui_streamlit/app.py
```

Optional API security:

```powershell
$env:API_KEY = "set-a-strong-secret"
```

If `API_KEY` is set for `quant_api`, all `/runs`, `/datasets`, and `/results` requests require `X-API-Key`.

Optional long-job timeout for heavy optimization:

```powershell
$env:RUN_JOB_TIMEOUT_SECONDS = "21600"
```

Use this when running one-click multi-stock optimization (worker queue timeout).

3. Open the Streamlit URL shown in terminal (default `http://localhost:8501`).

## Quick sanity check

Run a synthetic end-to-end smoke test (create run -> start -> poll -> fetch metrics/artifacts):

```bash
python services/ui_streamlit/smoke_test.py --api-url http://127.0.0.1:8000 --symbol IAM
```

If API key auth is enabled:

```bash
python services/ui_streamlit/smoke_test.py --api-url http://127.0.0.1:8000 --symbol IAM --api-key <your-key>
```

Expected outcome: final status is `succeeded`, with non-empty metrics and at least one artifact when plots are enabled.

## Core workflow

- `Backtesting` page: run one strategy on selected symbol set, with period controls.
- `Optimization` page: optimize selected strategies, optional manual candidate domains, optional one-click `batch_per_symbol` mode for all selected stocks, and persistent indicator caching.
- `Results` page: stock leaderboard, plots, trade ledgers, majority/weighted votes, and interactive custom weighted vote.
- `Defaults Discovery` page (`/defaults-discovery`): walk-forward SMA defaults discovery with 9 bucketed defaults and export/apply flow.

See methodology and schema in [`docs/DEFAULTS_DISCOVERY.md`](docs/DEFAULTS_DISCOVERY.md).
