# ChatGPT Context Pack For This Repository

Use this file when asking ChatGPT to modify `core/quant_core` or any cross-service behavior. It gives the minimum architecture context needed to avoid guesswork.

## 1) Monorepo Structure

- `core/quant_core`: quant engine library (data, indicators, strategy, portfolio, optimization, plots, pipeline)
- `services/api`: FastAPI service (run creation/start, results read APIs, datasets, market-data ingestion trigger)
- `services/worker`: RQ worker (executes runs via `quant_core.pipeline.run_pipeline`, persists outputs)
- `services/ui_streamlit`: Streamlit UI (builds `spec_json`, computes `spec_hash`, creates/starts runs)
- `quant-backtesting-frontend`: Next.js frontend (same run API contracts via Zod schemas)
- `infra/docker-compose.yml`: local stack (Postgres, Redis, MinIO, API, worker)

## 2) End-to-End Runtime Flow

1. Client builds `spec_json` and `spec_hash`.
   - Streamlit: `services/ui_streamlit/app.py`
   - Next.js: `quant-backtesting-frontend/lib/api.ts` (`computeSpecHash`)
2. API creates deterministic `run_id` from `(spec_hash, dataset_id)`.
   - `services/api/app/routers/runs.py`
3. API enqueues worker job to RQ queue `runs`.
   - `services/api/app/queue.py`, `services/api/app/routers/runs.py`
4. Worker executes run:
   - Loads run + spec from DB
   - Resolves data source (uploaded dataset or canonical store parquet)
   - Calls `run_pipeline(spec_json)`
   - Persists leaderboard + artifacts
   - `services/worker/tasks/execute_run.py`
5. API serves run outputs from DB + MinIO presigned URLs.
   - `services/api/app/routers/runs.py`, `services/api/app/routers/results.py`

## 3) Quant Core Contracts (Critical)

### Canonical pipeline entrypoint

- Function: `run_pipeline(spec_json) -> dict`
- File: `core/quant_core/pipeline.py`

Expected output keys (worker depends on this shape):

- `leaderboard`: list of dict rows
- `plot_artifacts`: `{"symbols": {symbol: plotly_json}}`
- `strategy_results`: `{strategy_kind: {"trade_ledger": [...], "plot_artifacts": {...}, ...}}`
- `artifacts`: metadata dict

If you change this shape, you must also update worker persistence logic in `services/worker/tasks/execute_run.py`.

### Engine and strategy wiring

- Strategy registry and construction: `core/quant_core/engine.py` (`build_strategy`)
- Strategy implementations: `core/quant_core/strategy.py`
- Indicator computation and registry: `core/quant_core/indicators.py`
- Portfolio execution semantics: `core/quant_core/portfolio.py`
- Reporting objects/tables: `core/quant_core/results.py`
- Plot builders: `core/quant_core/plots.py`
- Optimization adapters and param catalogs: `core/quant_core/optimize.py`

## 4) Data Source Modes Actually Used

The worker can mutate incoming spec before pipeline execution:

- Uploaded dataset mode:
  - Converts to `data.source = "bmce"`
  - sets local temp file path in `data.bmce_paths`
- Canonical store mode:
  - If `data.source == "store"`, worker downloads parquet from MinIO and rewrites spec to:
  - `data.source = "parquet"`, `data.parquet_paths = ...`

See `services/worker/tasks/execute_run.py`.

`core/quant_core` data adapters:

- BMCE-like CSV/Excel: `BMCEDataSource` in `core/quant_core/data.py`
- Parquet: `ParquetDataSource` in `core/quant_core/data.py`
- Synthetic: `make_synthetic_ohlcv` in `core/quant_core/data.py`
- Yahoo: `YahooFinanceDataSource` in `core/quant_core/data.py`

## 5) Current API/DB Output Expectations

Models:

- `run`, `dataset`, `artifact`, `strategy_leaderboard`, `run_metric`, `fill`, `position_ledger`
- File: `services/api/app/models.py`

Artifacts persisted by worker include:

- Run-level plot: `artifact_type = "plotly_json"` name `price_indicators_trades`
- Strategy plot: `artifact_type = "strategy_plotly_json"` name `<strategy>.price_indicators_trades`
- Strategy ledger CSV: `artifact_type = "strategy_trade_ledger_csv"` name `<strategy>.trade_ledger`

See `services/worker/tasks/execute_run.py`.

## 6) Cross-File Update Rules (No Guessing)

When changing behavior in `quant_core`, verify related files too:

- New strategy kind:
  - `core/quant_core/strategy.py`
  - `core/quant_core/engine.py` (`build_strategy`, `StrategyKind`)
  - `core/quant_core/optimize.py` (adapter + `default_param_catalog`)
  - `quant-backtesting-frontend/lib/api.ts` (`STRATEGY_CATALOG`, defaults)
  - `services/ui_streamlit/app.py` (`STRATEGY_KINDS`, parameter form/domain defaults)
- New indicator column names:
  - strategy required features + `default_plot_indicators`
  - plot detection/rendering in `core/quant_core/plots.py`
- Pipeline output changes:
  - worker persistence in `services/worker/tasks/execute_run.py`
  - API response schemas if external shape changes

## 7) Spec And Hash Contract

- API expects:
  - `spec_json: dict`
  - `spec_hash: str`
  - optional `dataset_id`
- Pydantic schema: `services/api/app/schemas/runs.py`
- Hash is canonical JSON SHA-256:
  - Streamlit: `services/ui_streamlit/app.py`
  - Next.js: `quant-backtesting-frontend/lib/api.ts`

## 8) Non-Negotiable Invariants For Edits

- Keep `run_pipeline` return schema backward-compatible unless all consumers are updated.
- Keep `strategy_kind` string IDs stable where persisted/queried.
- Keep artifact `name`/`artifact_type` conventions unless API/frontend readers are updated.
- Keep deterministic spec hash semantics (sorted canonical JSON).
- If changing DB fields/contracts, include Alembic migration + API schema + frontend schema updates.

## 9) Command Checklist Before Asking ChatGPT To Edit

Run these in repo root and paste outputs:

```powershell
git status --short
rg --files core\quant_core services\api\app services\worker\tasks
rg -n "def run_pipeline|class BacktestEngine|def build_strategy|def default_param_catalog" core\quant_core\*.py
rg -n "def create_run|def start_run|def execute_run|def _persist_pipeline_output" services\api\app\routers\runs.py services\worker\tasks\execute_run.py
```

Then paste:

- Exact change request
- Files you are OK to modify
- Files that must not be modified
- Required backward compatibility constraints

## 10) Suggested Prompt Payload To Give ChatGPT

Use `docs/CHATGPT_CHANGE_REQUEST_TEMPLATE.md` and fill it completely.
