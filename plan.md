# Fundamentals subsystem — foolproof implementation plan

> Plan only — no code is written by this document. Each phase has explicit deliverables, file paths, and verification checkpoints so the work can be paused, reviewed, and resumed without losing state.

---

## 0 · Current state of the repo (verified, not assumed)

What already exists:

- **ORM classes** for all 8 fundamentals tables in `services/api/app/models.py:518-714`:
  `FundamentalImport`, `FundamentalCompanyMap`, `FundamentalAnnualMetric`,
  `FundamentalLatestSnapshot`, `FundamentalQualityIssue`,
  `FundamentalAssumptionSet`, `FundamentalValuationResult`,
  `FundamentalEnsembleResult`. All carry `methodology_version = "v2"` defaults
  and JSONB blobs (`metrics_json`, `scores_json`, `model_eligibility_json`,
  `coverage_json`, etc.) — i.e. the schema is designed to host the engine, not
  a green-field decision.
- **Worker entry stub** in `services/worker/tasks/__init__.py:43-46` —
  `execute_fundamental_import` is exported, lazy-imports
  `services/worker/tasks/fundamentals.py`.
- **Nav link** to `/fundamentals` in `frontend/components/signals-header.tsx:34`
  (gated under `hiddenWorkspaceNavHrefs`).
- **Universe split source**: `StockMaster.market_region` in
  `services/api/app/models.py:458` — values `"masi" | "us" | "european" | "asian" | NULL`.
  Non-MASI = `market_region != 'masi' AND market_region IS NOT NULL`.
- **Yahoo adapter**: `YahooFinanceDataSource` in `core/quant_core/data.py:524`
  (already a `yfinance` wrapper); `YFinanceMoroccoAdapter` at `:980`.
- **Signal-engine dispatch** in
  `services/worker/tasks/signal_engine_batch.py:215` branches on
  `mode.is_factor_x_ta`; modes are declared in
  `core/quant_core/signal_engine/modes.py` (`resolve_signal_mode`,
  `signal_mode_storage_name`).
- **Dashboard mode toggle**: `DASHBOARD_MODE_OPTIONS` in
  `frontend/app/v1/page.tsx:106-114` (currently `trade_opportunities` and
  `technical_directions`).
- **Signal-evidence drawer**: `frontend/components/strategy/signal-evidence-tab.tsx`
  (989 lines, contributors block already rendered for TA).

What does NOT exist:

- **No Alembic migration** creates the 8 `fundamental_*` tables. Confirmed by
  grepping every file in `services/api/alembic/versions/`. Current Alembic tip:
  `f7a8b9c1d2e3` (`expand_factor_x_ta_to_14`).
- **No `services/worker/tasks/fundamentals.py`** (worker stub will fail at import time on first call).
- **No core fundamentals package** under `core/quant_core/`.
- **No API router** `/fundamentals/*` (nothing mounted in `services/api/app/main.py` for this).
- **No frontend page** `frontend/app/fundamentals/page.tsx`.
- **No Data-page fundamentals tab**.
- **No `fundamental` or `fundamental_x_ta` signal modes**.
- **No fundamental-mode dashboard** or trade-opps column customization.
- **No docs layer** under `docs/fundamentals-layer/`.

---

## 1 · Open questions to lock BEFORE coding (Phase 0 deliverable)

These five items are the only places where ambiguity could cause rework. Each
must be answered in writing in `docs/fundamentals-layer/00-INDEX.md` (a new
doc folder we create as Phase 0's first PR) before any implementation begins.

1. **Workbook layout contract.** The schema already references
   `source_sheet`, `source_field`, and `raw_metric_name`, implying a real
   template exists. Required artefacts:
   - A canonical sample `.xlsx` checked into `tests/fixtures/fundamentals/sample_v2.xlsx`.
   - A `SHEET_LAYOUT` dict that maps each `(sheet_name, cell_range)` to a
     canonical `metric_name` (e.g. `"revenue"`, `"ebit"`, `"net_debt"`,
     `"shares_outstanding"`, `"book_value"`, `"capex"`, `"depreciation"`).
   - Required vs optional sheets; per-sheet header row index; FY column
     orientation (rows vs columns).
   - Confirm whether multiple companies live in one workbook or one per file —
     `FundamentalCompanyMap` is per-import so multi-company is supported.
2. **yfinance symbol mapping.** `stock_master.symbol` is the Bourse de
   Casablanca ticker. For non-MASI symbols we need the yfinance ticker, which
   for european listings looks like `SAP.DE`, for asian like `7203.T`. **Add a
   column** `yfinance_symbol` to `stock_master` (nullable; falls back to
   `symbol` when null and `market_region = 'us'`). Discovery deliverable: a CSV
   seed populating this column for the existing non-MASI rows.
3. **Scoring composition.** Four sub-scores (Quality, Growth, Value, Momentum)
   with explicit factor formulas, cross-sectional z-score normalisation, sector
   bucketing (use `stock_master.sector`), and composite weights. Lock the
   formulas in `docs/fundamentals-layer/10-scoring.md`. Defaults proposed
   below in §4 — these are the proposal, not a fait accompli.
4. **Valuation methods + ensemble weights.** Three methods (DCF, multiples,
   residual income). Lock the DCF horizon (default 5 yr explicit + terminal),
   the multiples basket (P/E, EV/EBITDA, P/B), and the data-quality-weighted
   ensemble formula in `docs/fundamentals-layer/20-valuation.md`. Defaults
   proposed below in §4.
5. **Auth model.** All ingest (`POST /fundamentals/import/*`) requires
   `require_admin` (matching existing ingest patterns); all reads use the
   session-cookie middleware that protects `/signals`. Confirm by reading
   `services/api/app/dependencies/auth.py` and pinning the exact dependency.

Each item ships as one short doc page (≤2 pages each) reviewed before Phase 2 starts.

---

## 2 · Database — schema activation

Single Alembic revision, placed after current tip.

- **File**: `services/api/alembic/versions/g8b9c1d2e3f4_create_fundamentals_subsystem.py`
- `revision = "g8b9c1d2e3f4"`, `down_revision = "f7a8b9c1d2e3"`.
- Operations (in this exact order to satisfy FK dependencies):
  1. `create_table fundamental_import` — 1:1 with ORM at `models.py:518-544`.
     Add column `data_source VARCHAR(16) NOT NULL DEFAULT 'workbook'`
     (workbook | yfinance | bloomberg). Add column
     `source_universe VARCHAR(16) NULL` (masi | non_masi) for fast filtering
     on dashboards.
  2. `create_table fundamental_company_map` — `models.py:547-567`. Unchanged.
  3. `create_table fundamental_annual_metric` — `models.py:570-590`. Unchanged.
  4. `create_table fundamental_latest_snapshot` — `models.py:593-614`. Add
     column `data_source VARCHAR(16) NOT NULL DEFAULT 'workbook'` mirroring
     `fundamental_import.data_source` so per-symbol queries don't need a join.
  5. `create_table fundamental_quality_issue` — `models.py:617-635`. Unchanged.
  6. `create_table fundamental_assumption_set` — `models.py:638-657`. Unchanged.
  7. `create_table fundamental_valuation_result` — `models.py:660-688`. Unchanged.
  8. `create_table fundamental_ensemble_result` — `models.py:691-714`. Unchanged.
  9. `alter_table stock_master add column yfinance_symbol VARCHAR NULL` — and
     a partial index on `(yfinance_symbol)` where not null.
  10. Seed: insert a single `fundamental_assumption_set` row with
     `scope_type='global', scope_key='GLOBAL', scenario='base'` carrying the
     default DCF/multiples weights from §4 — so the engine has a working
     baseline on first run.
- **Downgrade**: drop in reverse order, drop the two added columns, drop the
  seeded assumption set.
- **Verification**: in CI / locally, `alembic upgrade head` from a clean DB,
  then `alembic downgrade -1`, then `alembic upgrade head` again — must
  succeed end-to-end. Add a `tests/migrations/test_fundamentals_roundtrip.py`
  that runs this with `pytest-alembic`.

Mirror the two new columns into the ORM in `models.py` (`data_source`,
`source_universe`, `yfinance_symbol`) in the same PR.

---

## 3 · Core engine — `core/quant_core/fundamentals/`

New package, no edits to neighbours.

```
core/quant_core/fundamentals/
├── __init__.py            # re-exports the public API
├── domain.py              # dataclasses: Snapshot, AnnualMetric, ScoreRow, ValuationResult, EnsembleResult, AssumptionSet
├── workbook.py            # parser: bytes / path → WorkbookPayload
├── normalize.py           # canonical metric name aliases, unit harmonisation (MAD / USD), FY alignment
├── coverage.py            # computes coverage % per snapshot (used by model_eligibility_json)
├── scoring.py             # Quality / Growth / Value / Momentum + composite
├── valuation/
│   ├── __init__.py
│   ├── dcf.py             # explicit-period FCF + Gordon terminal
│   ├── multiples.py       # peer-median multiples
│   ├── residual_income.py # Ohlson RI model
│   └── ensemble.py        # data-quality-weighted blend
├── providers/
│   ├── __init__.py
│   ├── base.py            # FundamentalsProvider protocol
│   ├── workbook_source.py # wraps workbook.py
│   └── yfinance.py        # wraps yfinance.Ticker.{financials, balance_sheet, cashflow, info}
└── pipeline.py            # ingest(symbol, payload, source) → writes 4 tables, returns FundamentalImport.id
```

### 3.1 Domain types (`domain.py`)

Frozen dataclasses; no DB coupling. Each carries a `to_json()` /
`from_json()` for storage in JSONB blobs.

```python
@dataclass(frozen=True)
class AnnualMetric:
    symbol: str
    fiscal_year: int
    metric_name: str          # canonical name from normalize.CANONICAL_METRICS
    value: float | None
    raw_name: str
    source_sheet: str | None
    source_field: str | None
    is_proxy: bool

@dataclass(frozen=True)
class Snapshot:
    symbol: str
    latest_fy: int
    metrics: dict[str, float]   # canonical_name → value (latest FY only)
    history: dict[str, list[float]]  # 5y history per metric
    sector: str | None
    market_region: str | None
    currency: str
    data_source: Literal["workbook", "yfinance"]

@dataclass(frozen=True)
class ScoreRow:
    pillar: Literal["quality", "growth", "value", "momentum"]
    raw: float
    z: float                  # cross-sectional z-score within sector
    weight: float
    contribution: float       # weight * z, clipped to [-3, 3]

@dataclass(frozen=True)
class Score:
    quality: float            # [-1, 1]
    growth: float
    value: float
    momentum: float
    composite: float
    contributors: list[ScoreRow]
    coverage_pct: float       # fraction of inputs present

@dataclass(frozen=True)
class ValuationResult:
    method: Literal["dcf", "multiples", "residual_income"]
    fair_value: float | None
    low: float | None
    high: float | None
    confidence: Literal["high", "medium", "low", "unavailable"]
    confidence_score: float   # 0..1
    inputs: dict
    warnings: list[str]

@dataclass(frozen=True)
class EnsembleResult:
    fair_value_low: float
    fair_value_base: float
    fair_value_high: float
    current_price: float | None
    upside_pct: float | None
    model_weights: dict[str, float]
    usable_models: int
    excluded_models: int
    warnings: list[str]
```

### 3.2 Workbook parser (`workbook.py`)

- `parse_workbook(buf: bytes | Path) -> WorkbookPayload` where
  `WorkbookPayload = {company_meta, annual_metrics: list[AnnualMetric], qa_issues: list[QaIssue]}`.
- Drives off `SHEET_LAYOUT` (Phase 0 deliverable). No business logic in the
  parser — purely structural.
- **Hard fails** on missing required sheet → raises `WorkbookSchemaError`.
- **Soft fails** (negative revenue, FY gap, currency mismatch) → emits
  `QaIssue(severity="warn", code="…")` and continues. These flow into
  `FundamentalQualityIssue` rows.
- Uses `openpyxl` (pure Python, no native deps) — already in the repo per
  existing Excel ingestion paths.

### 3.3 yfinance provider (`providers/yfinance.py`)

- `fetch(symbol: str) -> WorkbookPayload` — returns the same shape as the
  workbook parser so the downstream pipeline is provider-agnostic.
- Resolves the yfinance ticker via `stock_master.yfinance_symbol` (Phase 0
  seed). Falls back to raw `symbol` for `market_region='us'`.
- Pulls four artefacts per call: `Ticker.financials` (income statement),
  `Ticker.balance_sheet`, `Ticker.cashflow`, `Ticker.info` (current price,
  shares outstanding, sector).
- **Network handling**: 30s timeout, 3 retries with exponential backoff (1s,
  2s, 4s). On final failure, raise `ProviderUnavailableError` — the worker
  task will record this in `FundamentalImport.error_message`.
- **Currency**: yfinance returns local-currency values; we tag `currency` on
  the snapshot but **do not** convert (downstream consumers handle FX
  separately).
- **Last 5 FYs** of income statement, balance sheet, cashflow.

### 3.4 Pipeline (`pipeline.py`)

```python
def ingest(
    *,
    db: Session,
    symbol: str,
    payload: WorkbookPayload,
    source: Literal["workbook", "yfinance"],
    scenario: str = "base",
    triggered_by: str | None = None,
) -> uuid.UUID:
    ...
```

Steps (atomic; rolls back on failure):
1. Insert one `FundamentalImport` row (`status="running"`, `data_source=source`,
   `source_universe="masi" | "non_masi"` derived from `StockMaster.market_region`).
2. Upsert one `FundamentalCompanyMap`.
3. Bulk-insert `FundamentalAnnualMetric` rows (one per metric × FY).
4. Compute `Snapshot` and `coverage_pct` → upsert `FundamentalLatestSnapshot`.
5. Compute `Score` (calls `scoring.compute(snapshot, peer_group)`) → write
   into `scores_json`. `peer_group` = all `FundamentalLatestSnapshot` rows
   with same `sector` and same `source_universe`.
6. Load the active `FundamentalAssumptionSet` for this symbol (symbol-scoped
   → sector-scoped → global, first match wins).
7. Run each valuation method → write `FundamentalValuationResult` rows.
8. Blend into `FundamentalEnsembleResult` (single row per
   `(symbol, scenario)`).
9. Insert any `QaIssue` rows into `FundamentalQualityIssue`.
10. Mark `FundamentalImport.status="succeeded"`, set
    `latest_snapshot_count`, `annual_metric_count`, `quality_issue_count`.

If any step raises, set `status="failed"` and `error_message=str(exc)`; do not
roll back the import row itself so the ops UI can see the failure.

### 3.5 Tests

- `tests/quant_core/fundamentals/test_workbook_parser.py` — fixture workbook
  → asserts exact metric values per FY.
- `tests/quant_core/fundamentals/test_scoring_golden.py` — synthetic Snapshot
  → asserts each sub-score to 3 decimals (golden numbers locked in fixture
  JSON).
- `tests/quant_core/fundamentals/test_valuation_methods.py` — DCF / multiples
  / RI on a hand-constructed firm; asserts fair value to ±1%.
- `tests/quant_core/fundamentals/test_pipeline_integration.py` — uses
  in-process SQLite; runs `pipeline.ingest` and asserts row counts in all 8
  tables.
- `tests/quant_core/fundamentals/test_yfinance_provider.py` — uses
  `responses` / `pytest-vcr` cassettes; no live network in CI.

---

## 4 · Scoring + valuation formulas (defaults, to be ratified in §1.3/§1.4 docs)

These are proposed defaults written down so the implementation is deterministic.
Each line is an editable parameter, not a hard-coded constant.

### Quality (4 factors, equal weight)

| Factor | Formula | Direction |
| --- | --- | --- |
| Return on equity | `net_income_t / avg(equity_t, equity_{t-1})` | higher = better |
| Gross margin | `gross_profit_t / revenue_t` | higher = better |
| Net debt / EBITDA | `(debt_t - cash_t) / ebitda_t` | lower = better |
| Accruals | `(net_income_t - cfo_t) / total_assets_t` | lower = better |

### Growth (4 factors, equal weight)

| Factor | Formula | Direction |
| --- | --- | --- |
| Revenue CAGR (3y) | `(revenue_t / revenue_{t-3})^(1/3) - 1` | higher = better |
| EPS CAGR (3y) | same on EPS | higher = better |
| FCF CAGR (3y) | same on FCF | higher = better |
| Net-margin trend | OLS slope of `net_margin` over 5y | higher = better |

### Value (4 factors, equal weight)

| Factor | Formula | Direction |
| --- | --- | --- |
| P/E (trailing) | `price / eps_ttm` | lower = better |
| EV/EBITDA | `(market_cap + debt - cash) / ebitda_ttm` | lower = better |
| P/B | `price / book_value_per_share` | lower = better |
| FCF yield | `fcf_ttm / market_cap` | higher = better |

### Momentum (fundamental-only, 3 factors, equal weight)

| Factor | Formula | Direction |
| --- | --- | --- |
| EPS revision | `(consensus_eps_t - consensus_eps_{t-90d}) / consensus_eps_{t-90d}` *(skip when consensus unavailable)* | higher = better |
| Earnings surprise | `(actual_eps - expected_eps) / |expected_eps|` (last 4 reports avg) | higher = better |
| Margin expansion | `gross_margin_t - gross_margin_{t-1}` | higher = better |

### Normalisation

For each factor:
1. Winsorise at 1% / 99% within the peer group (same sector + same
   `source_universe`).
2. Z-score within the peer group.
3. Clip to `[-3, 3]`, then map to `[-1, 1]` via `tanh(z / 3)`.

### Sub-score → composite

`composite = 0.30*quality + 0.25*growth + 0.30*value + 0.15*momentum`.
Weights live in `FundamentalAssumptionSet.assumptions_json["composite_weights"]`
so they're tunable per-scenario without code changes.

### Valuation methods

- **DCF**: 5-year explicit FCF projection from CAGR(FCF, 3y), terminal value
  via Gordon growth at `g = 2%`, WACC computed from `(equity_weight*Re +
  debt_weight*Rd*(1-tax))` with `Re = risk_free + beta * ERP` (defaults: `risk_free=4.5%`,
  `ERP=6.0%`, `beta=stock_master.beta` if present else 1.0).
- **Multiples**: peer-median P/E, EV/EBITDA, P/B applied to the symbol's
  trailing fundamentals; outputs `low = 25th-percentile`, `high =
  75th-percentile` of the three method outputs.
- **Residual income**: Ohlson — `V = book_value + Σ (ROE_t - Re) *
  book_value_{t-1} / (1+Re)^t` over 5 years + terminal.

### Ensemble

Per-method `confidence_score ∈ [0, 1]` derived from `coverage_pct` of inputs
that fed it (DCF needs FCF history → low if FCF missing; multiples needs
peer median ≥ 3 peers → otherwise excluded).

```
weight_m = confidence_score_m * method_prior_m
fair_value_base = Σ weight_m * fair_value_m / Σ weight_m
fair_value_low  = min over methods of (fair_value_m - 1*sigma_m)
fair_value_high = max over methods of (fair_value_m + 1*sigma_m)
```

`method_prior` defaults: DCF 0.4, multiples 0.4, RI 0.2. Stored in
`FundamentalAssumptionSet.assumptions_json["method_priors"]`.

A method with `confidence == "unavailable"` is excluded from the blend; its
warning lands in `EnsembleResult.warnings`.

---

## 5 · Worker tasks

### 5.1 `services/worker/tasks/fundamentals.py` (new)

Concrete implementation of the existing stub. Exports:

```python
def execute_fundamental_import(
    *,
    upload_id: str,
    object_key: str,
    triggered_by: str | None = None,
) -> dict: ...

def refresh_yfinance_universe(
    *,
    market_regions: list[str] | None = None,  # default: ["us","european","asian"]
    triggered_by: str | None = None,
) -> dict: ...

def refresh_yfinance_for_symbol(
    *,
    symbol: str,
    triggered_by: str | None = None,
) -> dict: ...
```

- `execute_fundamental_import`: fetches the uploaded file from object storage
  using `object_key`, calls `workbook.parse_workbook`, fans
  out one `pipeline.ingest(symbol=…)` per company found in the workbook.
  Updates the parent `FundamentalImport` row with aggregate counts.
- `refresh_yfinance_universe`: enumerates `StockMaster` rows where
  `market_region IN (...)` and `is_active = TRUE`; enqueues one
  `refresh_yfinance_for_symbol` per symbol; returns batch ID.
- `refresh_yfinance_for_symbol`: calls `providers.yfinance.fetch(symbol)`
  then `pipeline.ingest(..., source="yfinance")`.

### 5.2 RQ wiring

- Register the three callables in the worker's queue config (search for
  existing `execute_run` / `refresh_single_symbol` registrations in
  `services/worker/` to copy the pattern; both are in the same `__init__.py`
  proxies block).
- Add weekly cron in whatever scheduler config holds the macro-refresh job
  (`ingest_macro_series` cron is the model to copy).
- All three tasks log to the existing logger and increment a Prometheus
  counter `fundamentals_ingest_total{source, status}` (see §10
  Observability).

---

## 6 · API — `services/api/app/routers/fundamentals.py` (new)

Mount in `services/api/app/main.py` next to the existing routers.
Pydantic schemas in `services/api/app/schemas/fundamentals.py` (new file).

| Method | Path | Body / params | Returns | Auth |
| --- | --- | --- | --- | --- |
| GET | `/fundamentals/universe` | `?market_region=&has_snapshot=&q=` | `[{symbol, display_name, market_region, sector, has_snapshot, last_imported_at, data_source}]` | session |
| GET | `/fundamentals/snapshot/{symbol}` | – | `{symbol, latest_fy, metrics, scores, contributors, coverage_pct, currency, data_source, computed_at}` | session |
| POST | `/fundamentals/snapshot/batch` | `{symbols: [string]}` (≤ 200) | `{[symbol]: snapshot}` | session |
| GET | `/fundamentals/history/{symbol}` | `?metrics=revenue,ebit,…&years=5` | `{symbol, years:[…], series:{metric:[v,…]}}` | session |
| GET | `/fundamentals/valuation/{symbol}` | `?scenario=base` | `{ensemble, per_method:[…], assumptions:{…}, current_price}` | session |
| POST | `/fundamentals/assumptions/{symbol}` | `{scenario, assumptions_json}` | `{assumption_set_id, ensemble: …}` (re-computes synchronously) | admin |
| GET | `/fundamentals/quality/{symbol}` | – | `[{severity, code, message, metric_name, fiscal_year}]` | session |
| GET | `/fundamentals/coverage` | `?market_region=` | `[{symbol, latest_fy, days_since_import, missing_metrics:[…]}]` | session |
| GET | `/fundamentals/imports` | `?status=&limit=&offset=` | `[{import row, …}]` (paged) | admin |
| POST | `/fundamentals/imports/workbook` | multipart `file` | `{upload_id, rq_job_id}` | admin |
| POST | `/fundamentals/imports/yfinance` | `{symbols?:[string], market_regions?:[string]}` | `{batch_id, enqueued_count}` | admin |

Notes:
- The **batch** endpoint is what the dashboard hits when a user enables
  fundamental columns — avoid N+1 round-trips.
- `/fundamentals/snapshot/*` queries hit only `FundamentalLatestSnapshot` —
  the JSONB blobs already carry everything the UI needs, no joins.
- All write endpoints return the enqueued job ID for status polling via the
  existing `/jobs/{id}` endpoint.

### Tests

- `tests/api/routers/test_fundamentals_router.py` — table-driven happy
  paths and 403/422 cases. Uses the existing API test harness (look at
  `tests/api/routers/test_analytics.py` for the established style).

---

## 7 · Signal engine integration

### 7.1 New modes in `core/quant_core/signal_engine/modes.py`

Add two `SignalMode` instances:

```python
FUNDAMENTAL = SignalMode(
    name="fundamental",
    storage_name="fundamental",
    families=(
        "fundamental_quality",
        "fundamental_value",
        "fundamental_growth",
        "fundamental_momentum",
    ),
    is_factor_x_ta=False,
    is_fundamental=True,         # new flag
)
FUNDAMENTAL_X_TA = SignalMode(
    name="fundamental_x_ta",
    storage_name="fundamental_x_ta",
    families=ALL_TA_FAMILIES + FUNDAMENTAL.families,
    is_factor_x_ta=False,
    is_fundamental=True,
)
```

Register in `resolve_signal_mode` dispatch table. Add `is_fundamental: bool =
False` to the `SignalMode` dataclass.

### 7.2 Four new families under `core/quant_core/signal_engine/families/`

- `fundamental_quality.py`
- `fundamental_value.py`
- `fundamental_growth.py`
- `fundamental_momentum.py`

Each implements the existing family contract (find an existing family file
under `core/quant_core/signal_engine/families/` and copy its signature).
The function reads the latest `FundamentalLatestSnapshot` for the symbol,
extracts the relevant pillar's `z`-score, and emits one signal row per bar:

```
signal_value = tanh(pillar_z / 3)          # in [-1, 1]
direction    = sign(signal_value)
confidence   = min(1.0, coverage_pct)
```

The signal is **stepwise** — it doesn't recompute per bar; it's a constant
over each holding window until the next snapshot arrives.

### 7.3 Worker dispatch

In `services/worker/tasks/signal_engine_batch.py:215`, add a branch:

```python
mode = resolve_signal_mode(variant)
variant = mode.name
if mode.is_factor_x_ta:
    ...  # existing
elif mode.is_fundamental and not mode.families_overlap_ta:
    # pure fundamental — short path
    from services.worker.tasks.fundamental_signal_batch import compute_fundamental_for_symbol
    return compute_fundamental_for_symbol(symbol, horizon, variant=variant)
else:
    # fundamental_x_ta: fall through to the existing full_rebuild_from_pipeline
    # since families are just added to ALL_FAMILIES
    ...
```

For `fundamental_x_ta`, ensure `_families_for_variant(variant)` returns the
combined set so the batch job's `total_units` is correct.

### 7.4 New worker module `services/worker/tasks/fundamental_signal_batch.py`

Mirrors `factor_x_ta_batch.py` — `compute_fundamental_for_symbol(symbol,
horizon, variant)` reads the latest snapshot, calls each family, writes
signal rows via the same `signal_engine.signal_store` helpers the TA path uses.

### Tests

- `tests/quant_core/signal_engine/test_fundamental_families.py` — golden
  signal values for a known snapshot.
- `tests/worker/test_fundamental_signal_batch.py` — end-to-end with SQLite.

---

## 8 · Frontend — workspace page `/fundamentals`

`frontend/app/fundamentals/page.tsx` (new). Nav link already present.

### 8.1 Layout

Three-column on desktop, single-column stacked on mobile.

| Column | Content |
| --- | --- |
| Left (240 px) | Symbol picker. Grouped collapsible sections: MASI, US, European, Asian. Each row: ticker, display name, source-badge (`Workbook` / `yfinance`), freshness dot (green ≤7 d, amber ≤30 d, red >30 d). Search bar at top filters all groups. |
| Center | The four pillar gauges (Quality / Growth / Value / Momentum) as horizontal bars in `[-1, 1]`. Below them, the composite score badge with peer-rank ("3rd / 12 banks"). |
| Right (360 px) | Valuation summary: current price, fair-value triangle (low / base / high), upside %, confidence badge. |

Below the three columns, a `Tabs` block with four tabs (reuse `frontend/components/ui/tabs.tsx`):

1. **Overview** — narrative summary; top-3 positive and top-3 negative contributors from `scores.contributors[]`.
2. **Financials** — annual metrics table (revenue, EBIT, EBITDA, net income, FCF, total debt, cash, equity), 5y columns, sparklines per row.
3. **Valuation** — per-method results table (method, fair value, low/high, confidence, weight, warnings); below, an editable assumptions form (WACC, terminal growth, method priors, composite weights). On save, calls `POST /fundamentals/assumptions/{symbol}` and re-renders.
4. **Quality** — `FundamentalQualityIssue` list with severity chips and metric/year context.

### 8.2 Data plumbing

- Server component fetches `/fundamentals/snapshot/{symbol}` and
  `/fundamentals/valuation/{symbol}` in parallel.
- Client component handles the assumptions form and re-fetch.
- Use `swr` or React Query (whichever the rest of the app uses — search for
  existing patterns under `frontend/lib/`).

### 8.3 Tests

- `frontend/__tests__/fundamentals/page.test.tsx` — render with mocked
  snapshot, assert gauges and tabs are present.
- Playwright smoke (if the repo has Playwright): pick a symbol, switch tabs,
  edit an assumption, verify the valuation triangle updates.

---

## 9 · UI integrations beyond `/fundamentals`

### 9.1 Data-page fundamentals tab

`frontend/app/data/page.tsx` currently keys off `asset_type`. Add a
top-level tab **Fundamentals** alongside the existing asset-type tabs.

Inside the tab:
- **Coverage matrix** — symbol × `latest_fy`; cell colour by freshness;
  hover-tooltip lists missing metrics.
- **Imports log** — paged `FundamentalImport` table (filename, source, status,
  rows imported, errors, started/completed).
- **Action bar** — two buttons:
  - "Upload workbook" → file picker → `POST /fundamentals/imports/workbook`.
  - "Refresh non-MASI (yfinance)" → opens a modal with checkboxes for
    `market_regions`, defaults to all three, then `POST
    /fundamentals/imports/yfinance`.

### 9.2 Dashboard mode `fundamental_directions`

Extend `frontend/app/v1/page.tsx:106-114`:

```ts
const DASHBOARD_MODE_OPTIONS = [
  { value: "trade_opportunities" as const, label: "Trade opportunities" },
  { value: "technical_directions" as const, label: "Technical directions" },
  { value: "fundamental_directions" as const, label: "Fundamental directions" },
]
```

When `dashboardMode === "fundamental_directions"`:
- Hide the `TECHNICAL_DIRECTION_MODE_OPTIONS` inline-after block (only show
  for `technical_directions`).
- Hide the Familles-TA toggle group (currently at `frontend/app/v1/page.tsx:1342`).
- Replace the row's columns with: `Symbole · Composite · Quality · Growth ·
  Value · Momentum · Upside vs spot · Confiance`.
- Source: client-side call to `POST /fundamentals/snapshot/batch` for the
  symbols visible in the current `view` (the dashboard's existing universe filter).
- Empty state when a symbol has no snapshot: render an em-dash with a tooltip
  "Aucune analyse fondamentale".

### 9.3 Trade-opportunities column customization

Trade-opps table is rendered when `dashboardMode === "trade_opportunities"`
(same file). Add a "Columns" chip group mirroring the Familles-TA group, with
toggles for:

- Always-on: `Edge`, `Confiance`.
- Optional: `Liquidité`, `Score fondamental`, `Valuation gap`, `Quality`,
  `Growth`, `Value`, `Momentum`.

Persistence: `localStorage` key `dashboard.trade_opps.columns.v1` storing a
record `{column: boolean}`. SSR-safe (no access on initial render; hydrate
on `useEffect`).

Data: when any fundamental column is enabled, batch-fetch
`/fundamentals/snapshot/batch` for the visible symbols on mount and on
row-set change (debounced 250 ms). Join client-side on `symbol`.

### 9.4 Signal-evidence drawer — fundamental contributors

`frontend/components/strategy/signal-evidence-tab.tsx`. Inside
`SignalEvidenceTab` (line 936), add a conditional `<section>` rendered when
the signal's `variant` is `fundamental` or `fundamental_x_ta`:

- Heading: "Contributeurs fondamentaux".
- For each contributor in `scores.contributors[]`: row with `pillar`,
  `factor`, `raw`, `z`, `weight`, `contribution`. Sort by `|contribution|`
  desc. Show top 6 by default with "Voir tout" expander.
- Reuse the existing contributor row component if signature-compatible;
  otherwise a thin local variant in the same file.

---

## 10 · Cross-cutting concerns

### 10.1 Authentication & authorisation

- Reads: existing session middleware (the one that gates `/signals` and
  `/dashboard`). Pin the exact dependency in
  `services/api/app/routers/fundamentals.py` so it's reviewable.
- Writes (imports + assumptions): `require_admin`. Match the existing pattern
  in `services/api/app/routers/admin/ops.py`.
- No new roles, no new tokens.

### 10.2 Observability

Add to the existing Prometheus registry (search for existing `Counter` /
`Histogram` declarations in `services/worker/`):

- `fundamentals_ingest_total{source, status}` — counter.
- `fundamentals_ingest_duration_seconds{source}` — histogram (buckets 1, 5,
  15, 60, 300).
- `fundamentals_snapshot_coverage_pct{symbol}` — gauge, set on each ingest.
- `fundamentals_yfinance_provider_errors_total{code}` — counter (timeouts,
  rate limits, parse errors).

Structured-log every ingest with `symbol`, `source`, `import_id`,
`duration_ms`, `coverage_pct`, `qa_issue_count`.

### 10.3 Rate-limit hygiene (yfinance)

- Default batch size: 25 symbols per `refresh_yfinance_universe` run.
- 1.5 s sleep between symbols in a single worker process.
- One worker only consumes the `fundamentals_yfinance` queue at a time
  (queue-level concurrency = 1 in the RQ config).
- On `429`-like error, exponential backoff up to 5 min, then mark the symbol
  failed and continue.

### 10.4 Feature flag / rollout

- Gate all four UI surfaces (page, data tab, dashboard mode, trade-opps
  columns, signal-evidence section) on
  `process.env.NEXT_PUBLIC_FUNDAMENTALS_ENABLED === "true"`.
- Default `false` in CI, `true` in dev + prod once Phase 4 is verified.
- Backend endpoints can be public — they 404-empty until data exists.

### 10.5 Backfill & freshness

- No historical signal backfill. The new modes start emitting rows from
  deploy time forward.
- Workbook ingestion is on-demand (user uploads via UI).
- yfinance refresh: weekly cron + manual trigger via Data-page button.
- Staleness display: any snapshot with `imported_at` older than 90 d shows a
  red "Stale" chip on the `/fundamentals` page; older than 365 d is hidden
  from the dashboard mode.

### 10.6 Documentation deliverables (`docs/fundamentals-layer/`)

New folder, mirroring the existing `docs/factor-layer/` structure. Pages:

- `00-INDEX.md`
- `01-overview-and-design-philosophy.md`
- `10-scoring.md` (the §1.3 lock-down doc)
- `20-valuation.md` (the §1.4 lock-down doc)
- `30-workbook-spec.md` (the §1.1 lock-down doc)
- `40-yfinance-provider.md`
- `50-api-contracts.md` (the table in §6, expanded)
- `60-signal-engine-integration.md`
- `70-ui-contracts.md`
- `80-ops-runbook.md` (how to re-run a failed import, how to clear stuck
  yfinance jobs, how to tune assumptions in prod).

Add an entry in `docs/APP_MAP.md` pointing to the new folder.

### 10.7 Risk register

| Risk | Mitigation |
| --- | --- |
| Workbook layout drifts and parser silently mis-aligns cells | Hard-fail on missing required sheets; `QaIssue` warns on suspicious values; fixture-driven parser tests in CI. |
| yfinance returns sparse or stale data for thin tickers | `coverage_pct` gates score visibility; "unavailable" valuation methods are excluded from the ensemble; UI shows freshness chip. |
| Peer-group too small for z-score (sector with 2 companies) | Fall back to whole-universe z-score when peer group <5; flag via `QaIssue`. |
| Sub-score formulas controversial | All weights live in `FundamentalAssumptionSet`; can be tuned in prod via the admin endpoint without a deploy. |
| Fundamental signals correlate with TA features in `fundamental_x_ta` | Existing factor selection / conditioning pipeline will down-weight redundant families; document this in `60-signal-engine-integration.md`. |
| yfinance rate-limited or banned | Single-worker queue + jitter; fail-open (workbook path unaffected); manual fallback documented in `80-ops-runbook.md`. |
| Currency mismatch (workbook MAD vs yfinance USD) | `currency` field on Snapshot; valuation upside computed in snapshot currency only; UI shows currency in fair-value triangle. |
| Schema migration breaks existing DB | Migration is purely additive (8 new tables + 2 columns); roundtrip-tested by `pytest-alembic`. |

---

## 11 · Sequenced execution (5 PRs, each independently shippable)

Each PR ends with explicit verification steps the reviewer can run.

### PR-1 · Lock decisions (docs-only)

- Deliverables: the 9 docs under `docs/fundamentals-layer/`, sample workbook
  in `tests/fixtures/fundamentals/sample_v2.xlsx`, the
  `yfinance_symbol` seed CSV.
- No code changes.
- Verify: review docs, confirm sample workbook parses (manually).

### PR-2 · Schema + core engine + worker

- Alembic migration `g8b9c1d2e3f4`.
- `core/quant_core/fundamentals/` package complete.
- `services/worker/tasks/fundamentals.py` implementing the stub.
- All unit and integration tests passing.
- No API, no UI.
- Verify:
  - `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`.
  - `pytest tests/quant_core/fundamentals tests/worker -q` green.
  - Manual RQ invocation: enqueue `execute_fundamental_import` against the
    sample workbook → DB rows appear in all 8 tables.

### PR-3 · API router

- `services/api/app/routers/fundamentals.py` + schemas.
- Wired into `main.py`.
- Router tests green.
- Verify: curl each endpoint locally; OpenAPI docs surface the new routes.

### PR-4 · `/fundamentals` workspace page + Data-page fundamentals tab

- `frontend/app/fundamentals/page.tsx` + components.
- Data-page tab + `Refresh non-MASI` modal.
- Feature flag default `true` in dev.
- Verify: navigate to `/fundamentals`, pick a MASI symbol, edit an assumption,
  see valuation re-render; navigate to `/data`, switch to Fundamentals tab,
  upload sample workbook, see import progress; trigger yfinance refresh for
  one symbol, see snapshot appear.

### PR-5 · Signal engine modes + dashboard + trade-opps + evidence

- New `fundamental` / `fundamental_x_ta` modes.
- Four fundamental families.
- Worker dispatch branch.
- Dashboard `fundamental_directions` mode.
- Trade-opps column customization (localStorage-persisted).
- Signal-evidence drawer fundamental contributors section.
- Verify:
  - Enqueue `compute_fundamental_for_symbol` for a symbol with a snapshot →
    signal rows appear with stepwise values.
  - Dashboard mode switch shows pillar columns; empty cells for symbols
    without snapshots.
  - Trade-opps column toggles persist across reload.
  - Click a fundamental signal in the evidence drawer → contributors list
    renders.

---

## 12 · Out of scope (explicit)

- No historical backfill of fundamental signal rows prior to deploy.
- No edits to existing TA families, factor_x_ta, or conditioning code.
- No new authentication mechanism; reuse existing session + admin guards.
- No new design-system primitives; reuse `frontend/components/ui/*`.
- No FX conversion across currencies; snapshots stay in their native
  currency.
- No real-time fundamentals (snapshots are weekly cadence at best).
- No Bloomberg / Refinitiv integration (`BloombergIngestBatch` exists in the
  schema at `models.py:717` but is its own subsystem).
