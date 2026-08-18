# Implementation brief — Cross-Asset Strategy Research Lab, Slice 1

**For:** Codex. Self-contained; everything needed is here or in the repo.
**Design doc (context):** `docs/offshore-lab/01-cross-asset-research-lab.md`. Read §3, §8, §11 there for the rationale; this brief is the build spec.
**Golden rule:** build the *proper return pipeline* for **both FX and commodities**, but only present a real backtest where free data supports a **tradable** return. FX = real end-to-end on free data. Commodities = same engine, validated on committed fixtures + a manual contract-CSV import; **never** present a continuous-ticker return as tradable.
**Hard constraints:** do not modify any equity/signal/dashboard/fundamentals code. Pure math in `core/quant_core/cross_asset/` imports **no** SQLAlchemy/FastAPI/app settings. Every backtest is deterministic given (spec, data, seed). No silent forward-fill, no silent instrument drops, no look-ahead.

## Why not reuse the existing backtester

`core/quant_core/signal_engine/backtest_mc.py:418` (`run_signal_backtest`) is single-instrument, scalar-position, close-to-close price-return only (`raw_returns = np.diff(cl)/cl[:-1]`, line 493). It has **no** per-instrument weights, notional, contract multiplier, roll return, financing, or FX conversion. Do **not** extend it. Build a new multi-instrument engine. **Do** reuse its two good ideas: one-bar execution lag (line 477) and proportional-bps cost on position change (line 500). And reuse, unchanged: `core/quant_core/wfo/engine.py` (`run_wfo_engine`), `core/quant_core/risk.py`, `core/quant_core/research/stats/robustness.py` (`deflated_sharpe_ratio`, `stationary_bootstrap_ci`).

## Files to create

```
core/quant_core/cross_asset/__init__.py
core/quant_core/cross_asset/instruments.py
core/quant_core/cross_asset/returns.py
core/quant_core/cross_asset/signals.py
core/quant_core/cross_asset/portfolio.py
core/quant_core/cross_asset/costs.py
core/quant_core/cross_asset/strategy_spec.py
core/quant_core/cross_asset/dataquality.py
core/quant_core/cross_asset/backtest.py
core/quant_core/cross_asset/validation.py
core/quant_core/cross_asset/importer.py          # canonical CSV → tidy frame + validation report

services/api/app/schemas/cross_asset_research.py
services/api/app/routers/cross_asset_research.py
services/api/app/services/cross_asset/__init__.py
services/api/app/services/cross_asset/orchestrator.py   # data assembly + run persistence
services/worker/tasks/cross_asset/__init__.py
services/worker/tasks/cross_asset/run_backtest.py

services/api/alembic/versions/<rev>_add_cross_asset_tables.py

frontend/app/cross-asset-research/page.tsx
frontend/components/cross-asset/strategy-overview.tsx
frontend/components/cross-asset/methodology-chain.tsx
frontend/components/cross-asset/backtest-results.tsx
frontend/components/cross-asset/robustness-panel.tsx
frontend/components/cross-asset/current-signal.tsx

core/tests/fixtures/cross_asset/fx_g10_sample.csv
core/tests/fixtures/cross_asset/commodity_contracts_sample.csv
core/tests/test_ca_returns.py
core/tests/test_ca_signals.py
core/tests/test_ca_portfolio.py
core/tests/test_ca_backtest.py
core/tests/test_ca_dataquality.py
core/tests/test_ca_importer.py
services/api/tests/test_cross_asset_research_router.py
```

## Files to modify (only)

- `services/api/app/main.py` — one `include_router(cross_asset_research.router)`, same pattern as neighbours.
- `frontend/lib/api.ts` — zod schemas + fetchers for the endpoints below.
- The sidebar/nav component (where `dashboard`/`signals` links live) — one entry "Cross-Asset Research" → `/cross-asset-research`.

## Core specification (`core/quant_core/cross_asset/`)

Pure functions + frozen dataclasses; `pandas`/`numpy` only; `datetime.date`; explicit units.

### `instruments.py`
`Instrument(symbol, asset_class, currency, quote_convention, point_value=1.0)`; `FxPair(base_ccy, quote_ccy, ...)` (long = +1 unit base vs quote; document the return sign); `FuturesContract(root, expiry, first_notice, roll_rule, tick_size, ...)`. `roll_rule ∈ {"n_days_before_expiry:<n>", "first_notice", "volume_crossover"}`.

### `returns.py`
```python
def fx_excess_return(spot: pd.Series, r_base: pd.Series, r_quote: pd.Series, daycount: float = 1/12) -> pd.Series
    # spot_return_t + (r_base - r_quote)_{t-1} * daycount ; rates are decimals p.a.; carry uses lagged rate
def futures_excess_return(front: pd.Series, roll_dates: list[date], next_on_roll: dict[date,float],
                          collateral_rate: pd.Series, daycount: float = 1/252) -> pd.Series
    # price_return(front) + roll_return(on roll dates, from front->next ratio) + collateral_rate_{t-1}*daycount
def to_base_ccy(returns: pd.Series, instrument_ccy: str, base_ccy: str, fx: dict[str,pd.Series]) -> pd.Series
def back_adjusted_series(front: pd.Series, roll_dates, next_on_roll) -> pd.Series  # display only
```
A test must prove `back_adjusted_series` price-returns reproduce `futures_excess_return` minus collateral (roll-consistency).

### `signals.py` (point-in-time; every feature at t observable by execution time)
```python
def time_series_momentum(excess_ret: pd.Series, lookback_months: int, lag: int = 1) -> pd.Series  # sign of trailing sum, lagged
def carry_signal(carry: pd.Series, lag: int = 1) -> pd.Series
def vol_scale(excess_ret: pd.Series, target_vol_annual: float, halflife: int, lag: int = 1) -> pd.Series  # lagged vol only
```
Support lookbacks {1,3,6,12} months only — the research-standard set, not dozens of variants.

### `portfolio.py`
```python
def size_positions(signals: pd.DataFrame, vols: pd.DataFrame, *, method: str,
                   target_vol_annual: float|None, max_weight: float, max_gross: float) -> pd.DataFrame
    # method ∈ {"unit","inverse_vol","vol_target"}; caps applied; vols are lagged; returns weight matrix (instruments × dates)
```
No look-ahead: all vols/ranks from data ≤ t−lag.

### `costs.py`
```python
def apply_costs(weights: pd.DataFrame, half_spread_bps: dict|float, slippage_bps: dict|float,
                commission_bps: dict|float) -> tuple[pd.Series, pd.Series]  # (turnover, cost_series) in return units
```

### `strategy_spec.py`
The `StrategyDefinition` dataclass tree from design §9 (Identity, Universe, DataRequirements, SignalSpec, PositionSpec, ExecutionSpec, ReturnSpec, ValidationSpec, Disclosures). `research_source.replication_fidelity ∈ {"faithful","adapted","simplified","extension"}` — **required**. `to_dict()/from_dict()` JSON round-trip + `spec_hash()` (stable json → sha256, reuse `stable_json_dumps` if present in repo, else implement).

### `dataquality.py`
```python
def data_quality_report(panel: pd.DataFrame, instruments: list[Instrument]) -> DataQualityReport
    # per instrument: first/last obs, missing periods, duplicate dates, price discontinuities (|ret|>threshold),
    # contract-metadata completeness, stale runs (unchanged value N+ bars), suspicious roll jumps, excluded+reason
```
`report.blocks_backtest: bool` True on fatal issues (dup dates, all-stale, no overlap). The backtest driver must refuse to run when True.

### `backtest.py`
```python
def run_backtest(spec: StrategyDefinition, panel: pd.DataFrame, *, seed: int = 0) -> BacktestResult
```
Deterministic. Produces the **stage dict** (each an inspectable artifact): `raw`, `tradable_returns`, `signal`, `position`, `executed_position` (lagged), `gross_return`, `costs`, `net_return`, `per_instrument_attribution`, plus `metrics` (ann_return, ann_vol, sharpe, sortino, max_drawdown, calmar, hit_rate, skew, tail_loss_5pct, turnover, gross_leverage, net_exposure, total_costs, long_attr, short_attr, n_eff_caveat) and `warnings`.

### `validation.py`
Thin adapters returning JSON-able dicts: `walk_forward(spec, panel)` via `run_wfo_engine`; `parameter_grid(spec, panel, grids)` → heatmap matrix + **deflated Sharpe** (`deflated_sharpe_ratio`, pass n_variants) + multiple-testing warning; `leave_one_instrument_out`; `subperiod` (by year); `cost_sensitivity` (scale costs 0×–3×); `bootstrap_ci` (`stationary_bootstrap_ci`).

### `importer.py`
Parse the canonical long CSV (`instrument_id,date,field,value,currency,contract_expiry,source`; fields: settle|open|high|low|close|volume|open_interest|rate|forward_points) → tidy panel + a `data_quality_report`. Reject on schema violation with a precise message. No side effects (no DB/network).

## Reference strategies to ship

- **FX (real):** G10 TSM (12-month, monthly rebalance, vol_target 10% annual) **and** carry (rank by rate differential, vol_target). Universe USD-based, pairs vs USD: EUR, JPY, GBP, CHF, AUD, CAD, NZD, NOK, SEK. Spot from the fixture for tests; production path pulls yfinance spot + FRED rates via the orchestrator. `replication_fidelity="adapted"` (document deviations: monthly rebstyle, proxy rates).
- **Commodity (fixture/import only):** same TSM + curve-carry (carry = front/next − 1 annualized) on `commodity_contracts_sample.csv`; **no** production data source wired; UI shows a "fixture data — not a tradable result" banner sourced from the run's `warnings`.

## API (router `cross_asset_research.py`, prefix `/cross-asset-research`, existing API-key auth)

- `POST /strategies` (persist versioned spec) · `GET /strategies` · `GET /strategies/{id}`
- `POST /data-quality` (spec or dataset id → DataQualityReport JSON)
- `POST /runs` → enqueue RQ job (copy the enqueue pattern from `routers/strategy_backtest_runs.py:333`: `get_queue().enqueue(...)`, store `rq_job_id` on the run row); returns run id
- `GET /runs/{id}` (status + metrics) · `GET /runs/{id}/stages` (stage artifacts) · `GET /runs/{id}/robustness`
- `GET /strategies/{id}/current-signal` (latest signal, intended vs previous position, drivers, data timestamp, staleness, next rebalance, reversal conditions)

Every response wraps a transparency envelope: `{inputs, methodology, data_source, calculation_date, assumptions, units, warnings, results, interpretation}`. `data_source` must say `"fixture"` for fixture-backed runs. The monitoring payload must never imply guaranteed profit — include a fixed disclaimer string.

## DB (one Alembic migration)

Add: `cross_asset_instrument` (symbol PK-ish, asset_class, currency, quote_convention, point_value, expiry, roll_rule, metadata JSON); `cross_asset_strategy` (id, name, version, spec_json, spec_hash, replication_fidelity, created_at); `cross_asset_run` (id, strategy_id FK, status, params_json, dataset_hash, git_commit, seed, metrics_json, rq_job_id, error_text, timestamps) — mirror `run` (`models.py:106`). Stage outputs persist as MinIO artifacts via the existing `artifact` mechanism (reuse `s3_keys.py`/storage helpers). Follow the alembic style in `services/api/alembic/versions/`.

## Frontend (route `/cross-asset-research`)

Six views per design §15: Overview, Methodology (raw→tradable→signal→position→executed→gross→net, each stage rendered from `GET /runs/{id}/stages`), Backtest (equity, drawdown, rolling Sharpe/vol, turnover, exposure, per-instrument, benchmark — plotly), Robustness (parameter **heatmap** — add a small plotly heatmap component; subperiod bars; cost-sensitivity; WFO; LOO; bootstrap CI), Current signal (monitor), Run record (strategy version, git commit, dataset hash, params, warnings, notes). French labels + English quant terms. Wire via `frontend/lib/api.ts` zod schemas. A visible unit on every number; the fixture/disclaimer banners always shown when present in `warnings`.

## Tests (deterministic; must pass, and full existing suite still green)

- `test_ca_returns`: FX excess-return identity on a hand-built series; futures roll-return reconstruction equals back-adjusted price-return minus collateral; base-ccy conversion.
- `test_ca_signals`: TSM sign correctness; **look-ahead test** — shifting an input by one bar shifts the signal by exactly one bar and never uses `t`'s return at `t`.
- `test_ca_portfolio`: vol_target hits target vol on synthetic iid data within tolerance; caps enforced; shorts symmetric.
- `test_ca_backtest`: determinism (same spec+data+seed → identical metrics); stage dict has all keys; net = gross − costs.
- `test_ca_dataquality`: corrupted fixture (dup dates / all-stale) sets `blocks_backtest=True` and the driver refuses.
- `test_ca_importer`: valid CSV → tidy panel; schema violation → precise error.
- `test_cross_asset_research_router` (FastAPI TestClient, sqlite like existing API tests): strategy CRUD; data-quality gate returns; run enqueues and status polls; envelope fields all present; monitoring payload includes the disclaimer.

## Acceptance criteria

1. All new tests pass; `pytest core/tests services/api/tests` stays green.
2. `core/quant_core/cross_asset/` imports nothing from `services/`, SQLAlchemy, or FastAPI.
3. No equity/signal/fundamentals files modified beyond the three listed.
4. `/cross-asset-research` renders and runs the **FX reference strategy end-to-end** against the API, showing the full methodology chain, real metrics, and at least the parameter-heatmap + deflated-Sharpe robustness output.
5. The commodity path runs through the identical engine on the fixture and is clearly labelled non-tradable; no continuous-ticker return is ever presented as a tradable result.
6. A run is reproducible: re-running the stored spec+dataset+seed yields identical metrics, and the run record shows git commit + dataset hash.
