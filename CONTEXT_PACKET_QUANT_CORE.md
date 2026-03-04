# Quant Core Context Packet

## 1) Repo map (Quant Core)

Quant core lives in `core/quant_core`.

### Module/subpackage map (1-line responsibility each)

| Path | Responsibility |
|---|---|
| `core/quant_core/pipeline.py` | Top-level orchestration for plain backtest, optimization, batch periods, and walk-forward (including multi-horizon mode). |
| `core/quant_core/engine.py` | `EngineSpec` contract and `BacktestEngine.run()` orchestration (load -> indicators -> signals -> portfolio -> results). |
| `core/quant_core/data.py` | Market data adapters/loaders + OHLCV normalization + timezone/index hygiene + caching. |
| `core/quant_core/indicators.py` | Feature engine + feature caching (memory/disk) and `FeaturesData` contract. |
| `core/quant_core/strategy.py` | Strategy contracts and signal generation primitives (`SignalFrame`, strategy base/contracts). |
| `core/quant_core/portfolio.py` | Portfolio execution semantics + full simulation + ultra-fast stats-only array path (Numba). |
| `core/quant_core/results.py` | Metrics/series/tables/report assembly with `fast_mode` vs full reporting behavior. |
| `core/quant_core/optimize.py` | Parameter catalog/domain expansion, candidate generation (grid/random), fast trial evaluation, ranking, best-spec reconstruction. |
| `core/quant_core/wfo/date_resolution.py` | Resolve user WFO dates against available bar index (alignment next/prev + warnings). |
| `core/quant_core/research/horizon.py` | Horizon presets (`short/medium/long`) + override validation for train/test/step settings. |
| `core/quant_core/wfo/date_presets.py` | Lookback defaults for WFO date auto-resolution by horizon. |
| `core/quant_core/run_spec.py` | Stable run-spec builder/hash inputs (cache/repro metadata contract). |
| `core/quant_core/plots.py` | Plotly figure builders used by pipeline artifact serialization. |
| `core/quant_core/integrity.py` | Post-run integrity checks (lookahead, leakage, dataset flags, timing contract). |
| `core/quant_core/perf.py` | Lightweight timer helper (`lap`) for wall-clock phase timings. |
| `core/quant_core/s3_keys.py` | Canonical dataset object key builder used across API/worker. |
| `core/quant_core/periods.py` | Static named period windows + window intersection/normalization utilities. |
| `core/quant_core/analysis/*` | Ancillary analysis helpers (e.g., defaults discovery). |
| `core/quant_core/decision/*` | Decision-scoring/backtest helpers integrated by pipeline/worker. |

### Public API surfaces (quant execution)

- `core/quant_core/pipeline.py` -> `run_pipeline(spec_json)`, `build_walk_forward_period_entries(...)`
- `core/quant_core/engine.py` -> `BacktestEngine.run(fast_mode=False)`
- `core/quant_core/optimize.py` -> `run_optimization(...)`, `batch_optimize_by_period(...)`, `build_spec_from_result_row(...)`
- `core/quant_core/wfo/date_resolution.py` -> `resolve_wfo_start_end_dates(...)`

### Direct callers of quant_core (hidden entrypoints)

- Worker runtime:
  - `services/worker/tasks/execute_run.py` (`run_pipeline`)
  - `services/worker/tasks/parallel_opt.py` (`run_pipeline`, optimizer internals)
  - `services/worker/tasks/evaluate_chunk.py` (optimizer internals fast path)
- API runtime:
  - `services/api/app/routers/runs.py` (`resolve_wfo_start_end_dates`, `run_pipeline`)
- Scripts:
  - `scripts/benchmarks/optimize_bench.py` (direct `run_optimization` benchmark script)
  - `services/api/scripts/backfill_object_keys.py` (direct `core.quant_core.s3_keys`)

Source: core/quant_core/pipeline.py:160-176
```python
def run_pipeline(spec_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Canonical pipeline entry point.

    Returns a dict with:
      - leaderboard: list[dict]
      - plot_artifacts: Dict[str, Any]
      - strategy_results: Dict[str, Any] (per-strategy trade_ledger + plot_artifacts + best params)
      - decision_support: Dict[str, Any] (canonical decision inputs + optional walk-forward OOS context)
      - metrics: Dict[str, Any]
      - fills: list[dict]
      - position_ledger: list[dict]
      - artifacts: Dict[str, Any] (run metadata, best params by kind)
    """
    data_json = spec_json.get("data", {})
    portfolio_json = spec_json.get("portfolio", {})
    strategy_json = spec_json.get("strategy", {})
```

---

## 2) Data model + contracts

### Main structures, fields, invariants, serialization

| Structure | Defined in | Key fields | Invariants/contracts | Serialization/output shape |
|---|---|---|---|---|
| `MarketData` | `core/quant_core/data.py` (`class MarketData`) | `bars`, `source`, `timezone`, `interval`, `meta` | Per symbol DF index must be sorted, unique `DatetimeIndex`; timezone localized/converted; canonical OHLCV columns | Primarily in-memory container; downstream converted by pipeline record serializers |
| `FeaturesData` | `core/quant_core/indicators.py` (`class FeaturesData`) | `features`, `source`, `timezone`, `interval`, `meta` | Mirrors `MarketData` by symbol; index alignment expected with market data after slicing | In-memory container; strategy layer consumes directly |
| `SignalFrame` | `core/quant_core/strategy.py` (`class SignalFrame`) | `signals`, `validity`, `meta` | `signals` index must be `DatetimeIndex`; required symbol columns must exist; `validity` index/columns must match `signals` | In-memory signal contract; intent values then consumed by portfolio layer |
| `PortfolioStats` | `core/quant_core/portfolio.py` | `final_equity`, `pnl`, `traded_notional`, `n_fills` | Stats-only fast path output contract | Scalar dataclass returned by fast optimization path |
| `Fill` | `core/quant_core/portfolio.py` | `timestamp`, `symbol`, `qty`, `price`, `notional`, `cost`, plus ledger economics fields | Signed qty convention; cost breakdown expected | Converted to row dicts/tables by results/pipeline |
| `PortfolioResult` | `core/quant_core/portfolio.py` | `equity_curve`, `returns`, `positions`, `trades`, `meta` | Full sim outputs aligned on execution timeline | Converted into report tables/series |
| `BacktestReport` | `core/quant_core/results.py` | `metrics`, `series`, `tables`, `plots`, `style`, `explain`, `meta` | `fast_mode` may skip heavy tables/plots | Core report object; pipeline serializes tables/plots into JSON-like dicts |
| `OptimizeConfig` | `core/quant_core/optimize.py` | `method`, `seed`, `n_trials`, `top_k`, cache flags, profiling flag | `method` currently random/grid behavior path | Config input to optimizer |
| `ParamDef` | `core/quant_core/optimize.py` | `key`, `kind`, `domain`, `cast`, `enabled` | Domain interpretation by kind (`int`, `float`, `choice`, `date_window`) | Candidate/spec expansion primitive |
| `TrialResult` | `core/quant_core/optimize.py` | `params`, `pnl`, `traded_notional`, `efficiency`, `n_fills`, `cagr`, `error` | Error trials represented explicitly (`error` + `-inf` metrics) | Ranked into DataFrames, then flattened in pipeline outputs |

### Time index policy (timezone/calendar/missing days)

- Market data normalization enforces datetime index sorting, deduplication, and timezone localize/convert (`core/quant_core/data.py::_ensure_datetime_index`).
- Strategy layer builds union index for multi-symbol signals and warns on large union/intersection mismatch (`core/quant_core/strategy.py::_build_common_index`).
- Optimizer aligns symbols by inner intersection before array conversion (`core/quant_core/optimize.py::_align_marketdata_inner`).
- WFO date resolver aligns start/end to available bars (`next` for start, `prev` for end) and returns alignment notes (`core/quant_core/wfo/date_resolution.py`).

Source: core/quant_core/data.py:164-171
```python
class MarketData:
    """
    Normalized market data for research backtesting.

    bars: dict[symbol -> DataFrame] where each DF:
      - index: tz-aware DatetimeIndex, sorted ascending, unique
      - columns: Open, High, Low, Close, Volume (+ optional Adj Close)
    """
```

Source: core/quant_core/data.py:188-203
```python
def _ensure_datetime_index(
    df: pd.DataFrame,
    tz: str = "GMT",
) -> pd.DataFrame:
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame index must be a DatetimeIndex after parsing.")
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if df.index.tz is None:
        df.index = df.index.tz_localize(tz)
    else:
        df.index = df.index.tz_convert(tz)
    return df
```

Source: core/quant_core/strategy.py:109-120
```python
def assert_well_formed(self, symbols: Sequence[str]) -> None:
    if not isinstance(self.signals.index, pd.DatetimeIndex):
        raise TypeError("SignalFrame.signals must be indexed by a DatetimeIndex")
    missing_cols = [s for s in symbols if s not in self.signals.columns]
    if missing_cols:
        raise ValueError(f"SignalFrame missing symbols: {missing_cols}")
    if self.validity is not None:
        if not self.validity.index.equals(self.signals.index):
            raise ValueError("SignalFrame.validity index must match signals index")
        if list(self.validity.columns) != list(self.signals.columns):
            raise ValueError("SignalFrame.validity columns must match signals columns")
```

Source: core/quant_core/pipeline.py:465-482
```python
def _df_to_records(df: pd.DataFrame | None, *, ensure_timestamp: bool = True) -> list[dict[str, Any]]:
    if df is None:
        return []
    out = df.copy()
    if ensure_timestamp and "timestamp" not in out.columns:
        if "signal_date" in out.columns:
            out["timestamp"] = out["signal_date"]
        else:
            out["timestamp"] = out.index
    if ensure_timestamp:
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
        if out["timestamp"].isna().all() and len(out) > 0:
            out["timestamp"] = pd.Timestamp.now(tz="UTC")
    out = _normalize_record_frame(out)
    return out.to_dict("records")
```
---

## 3) Backtest execution flow (call graph)

### Highest-level backtest chain

1. `core/quant_core/pipeline.py::run_pipeline(spec_json)`
2. Build config/spec objects (`DataConfig`, `IndicatorsConfig`, `StrategyConfig`, `PortfolioConfig`, `EngineSpec`)
3. If no optimization requested (`run_opt == False`): `BacktestEngine(engine_spec).run()`
4. Inside engine:
   - `load_marketdata(load_cfg)`
   - `slice_marketdata(..., include_windows=None, exclude_windows=None)` for padded indicator history
   - `IndicatorEngine.compute(...)`
   - `slice_marketdata(..., include/exclude windows)` for true backtest range
   - `slice_features(feats_full, md)`
   - `build_strategy(...).generate_signals(...)`
   - `PortfolioEngine.run(md, sf, symbols=...)`
   - `ResultsAnalyzer.analyze(..., fast_mode=...)`
5. Pipeline serializes:
   - strategy payload: `_bundle_to_strategy_result(...)`
   - runtime payload: `_runtime_payload(...)`
   - optional plot payload: `_build_plot_artifacts(...)`
6. Return dict with `metrics`, `fills`, `position_ledger`, `strategy_results`, `plot_artifacts`, `artifacts`.

### Loop sites

- Per-symbol feature compute: `core/quant_core/indicators.py::IndicatorEngine.compute` loops `for sym in symbols` then `for spec in specs`.
- Per-bar portfolio loop: `core/quant_core/portfolio.py::PortfolioEngine.run` loops `for i in range(len(idx)-1)`.
- Per-strategy-kind loop in pipeline optimization mode: `core/quant_core/pipeline.py::_run_kind` and `outputs = [_run_kind(kind) ...]` / threadpool branch.

### Stats-only vs full-artifacts paths (explicit)

- Stats-only path exists:
  - WFO test-fold eval uses `BacktestEngine(...).run(fast_mode=True)` (`core/quant_core/pipeline.py:1457`, `1544`, `1586`).
  - `ResultsAnalyzer.analyze(..., fast_mode=True)` returns lightweight metrics/series and skips heavy tables/plots (`core/quant_core/results.py`).
- Full-artifacts path exists:
  - Plain backtest and winner materialization call `BacktestEngine(...).run()` default `fast_mode=False`.
  - Plot artifacts only included when both `plots.enabled` and `plots.return_plot_artifacts` are true (`core/quant_core/pipeline.py::_build_plot_artifacts`).

Source: core/quant_core/results.py:121-139
```python
# FAST MODE: skip heavy computations (plots, ledgers, tables)
# Only compute metrics needed for strategy ranking.
cum = (1.0 + rets).cumprod() - 1.0
dd = self._drawdown_from_equity(equity)
pnl = equity.diff().fillna(0.0)
cum_pnl = pnl.cumsum()
pnl_total = float(equity.iloc[-1] - equity.iloc[0]) if len(equity) else 0.0
raw_fills = portfolio_result.trades
n_fills = int(len(raw_fills)) if raw_fills is not None and not raw_fills.empty else 0
if fast_mode:
    volume_inv = self._volume_invested_reset_last_sell_monthly(raw_fills)
    efficiency = 1.0 if volume_inv <= 0 else float(pnl_total / volume_inv)
    metrics = self._headline_metrics(rets, dd, None)
    metrics["Net PnL"] = float(pnl_total)
    metrics["VolumeInv"] = float(volume_inv)
    metrics["Efficiency"] = float(efficiency)
```

Source: core/quant_core/pipeline.py:705-711
```python
if not bool(plots_json.get("enabled", False)):
    return {"symbols": {}}
if not bool(plots_json.get("return_plot_artifacts", False)):
    return {"symbols": {}}
kinds = set(str(k) for k in (plots_json.get("kinds") or []))
if "price_indicators_trades" not in kinds:
    return {"symbols": {}}
```

---

## 4) Optimization + WFO flow (call graph + parameters)

### Optimizer entrypoints

- `core/quant_core/optimize.py::run_optimization(base_spec, active_params, cfg)`
- `core/quant_core/optimize.py::batch_optimize_by_period(...)`
- Candidate generation:
  - grid: `_iter_grid(active)`
  - random: `_iter_random(active, n_trials, seed)` with de-dup (`seen`) and capped attempts

### WFO functions and stepping logic

- Window generation:
  - `core/quant_core/pipeline.py::build_walk_forward_period_entries(...)`
- Date resolution/alignment:
  - `core/quant_core/wfo/date_resolution.py::resolve_wfo_start_end_dates(...)`
- Horizon defaults/overrides:
  - `core/quant_core/research/horizon.py::get_horizon_config(...)`
  - presets from `core/quant_core/research/horizon.py::PRESETS`
  - date auto-lookback from `core/quant_core/wfo/date_presets.py`

### End-to-end WFO call flow (pipeline)

1. Parse `optimization.walk_forward` in `run_pipeline`.
2. Require `resolved_start_date`/`resolved_end_date` (or fail).
3. Derive `train/test/step` values (use horizon defaults when missing).
4. Build folds via `build_walk_forward_period_entries(...)`.
5. For each fold (threaded):
   - Build `train_spec`
   - Run `run_optimization(...)` on train range
   - Build candidate test specs from top train rows
   - Evaluate OOS on `BacktestEngine(test_spec).run(fast_mode=True)`
6. Aggregate fold rows + OOS summaries.
7. Materialize winners full-mode (`BacktestEngine(...).run()`) for final artifacts.

### Key parameters and where expanded

| Param | Source field | Expansion site |
|---|---|---|
| method | `optimization.method` | `OptimizeConfig.method` in `pipeline.py`, candidate path in `optimize.py` |
| n_trials | `optimization.n_trials` | `OptimizeConfig.n_trials`, `_iter_random` target |
| top_k | `optimization.top_k` | `OptimizeConfig.top_k`, `top_df.head(top_k)` |
| train/test/step | `optimization.walk_forward.{train,test,step}` | normalized in `pipeline.py` before fold build |
| anchored/max_folds | `optimization.walk_forward.anchored/max_folds` | `build_walk_forward_period_entries(...)` |
| horizon/horizon_overrides | `optimization.walk_forward.horizon(_overrides)` | `get_horizon_config(...)` then propagated |
| objective | `optimization.walk_forward.objective` / batch objective | used in row ranking and winner selection |
| domains_by_kind | `optimization.domains_by_kind` | `_params_from_catalog` mutates catalog domains |

### Spec builder path (candidate -> executable spec)

- Catalog and custom-domain expansion: `pipeline.py::_params_from_catalog`
- Default domains by strategy: `optimize.py::default_param_catalog`
- Candidate generation: `_iter_grid` / `_iter_random`
- Best-row to spec: `optimize.py::build_spec_from_result_row` -> `_apply_params_to_spec`

### Stats-only vs full-artifacts paths (explicit)

- Stats-only in optimization:
  - Trial scoring uses `PortfolioEngine.run_stats_only_arrays(...)` inside `_eval_one_trial`.
  - `batch_optimize_by_period` first computes `stats = eval_stats_only_for_spec_arrays(best_spec)`.
- Full-artifacts in optimization:
  - `batch_optimize_by_period` then runs `BacktestEngine(best_spec).run()` for winner artifact fields.
  - Standard pipeline optimization materializes only selected best specs with full `run()`.

### Known fragile state variables (error-prone)

- `base_spec_by_kind` (`pipeline.py`) holds per-kind baseline specs reused across fold/period rewrites.
- `winner_spec` / `best_specs_by_kind` (`pipeline.py`) rebuilt from leaderboard rows; mismatched row schema can corrupt downstream spec reconstruction.
- `walk_forward_meta` must carry resolved dates + fold metadata; missing resolved dates hard-fail.
- No variable named `best_params_final` found in current quant_core.  
  Inference: prior bugs likely mapped to today’s `best_params_json`, `best_specs_by_kind`, or fold winner reconstruction flow.

Source: core/quant_core/pipeline.py:87-103
```python
def build_walk_forward_period_entries(
    *,
    start: str,
    end: str,
    train_value: int,
    train_unit: str,
    test_value: int,
    test_unit: str,
    step_value: int,
    step_unit: str,
    anchored: bool,
    max_folds: int | None = None,
) -> list[dict[str, str]]:
    start_ts = pd.to_datetime(start, errors="coerce")
    end_ts = pd.to_datetime(end, errors="coerce")
    if pd.isna(start_ts) or pd.isna(end_ts):
        raise ValueError("Walk-forward requires valid data.start and data.end dates.")
```

Source: core/quant_core/optimize.py:1873-1891
```python
for params in candidates:
    params_key = _trial_params_key(params)
    cached_result = eval_cache.get(params_key)
    if cached_result is not None:
        _cache_hits += 1
        results.append(cached_result)
        continue
    ok, err = adapter.validate_params(params, base_spec)
    if not ok:
        invalid_result = TrialResult(
            params=params,
            pnl=float("-inf"),
            traded_notional=0.0,
            efficiency=float("-inf"),
            n_fills=0,
            cagr=float("-inf"),
            error=err or "invalid params",
        )
```

Source: core/quant_core/optimize.py:2236-2260
```python
# ---- stats-only evaluation (fast) ----
stats = eval_stats_only_for_spec_arrays(best_spec)
score = stats.get(objective, np.nan)
...
# ---- FULL run ONLY for best spec (fills -> trade ledger/perf) ----
try:
    best_bundle = BacktestEngine(best_spec).run()
    trades_df = best_bundle.report.tables.get("trades", pd.DataFrame())
    ledger = best_bundle.report.tables.get("trade_ledger", pd.DataFrame())
```

Source: core/quant_core/optimize.py:2618-2634
```python
def _iter_random(active: List[ParamDef], n_trials: int, seed: int) -> Iterable[Dict[str, Any]]:
    rng = random.Random(seed)
    ...
    total_unique = 1
    for k in keys:
        total_unique *= max(1, len(grids[k]))
    target = min(int(n_trials), int(total_unique))
    seen: set[str] = set()
    attempts = 0
    max_attempts = max(target * 10, target + 100)
```
---

## 5) Performance hotspots (evidence-based)

Top 10 likely hotspots ranked by expected impact.

| # | Label | Location | Why hot | Vectorization/cache/batching opportunity |
|---|---|---|---|---|
| 1 | `Orchestration` | `core/quant_core/pipeline.py` multi-horizon recursion (`run_pipeline` calls itself at `1117`) | Re-runs almost full pipeline per horizon; can multiply total runtime 2-3x+ | Reuse shared loaded data/feature bank across horizons; compile horizon configs once and evaluate in a single orchestrator pass |
| 2 | `Orchestration` | `core/quant_core/pipeline.py::_eval_fold` WFO fold loop + threadpool (`1397+`, `1516+`) | Per fold does optimize + backtest, with nested loops over folds, kinds, train candidates | Batch fold evaluation by pre-sliced indices; separate train-optimization and test-scoring phases with shared caches |
| 3 | `Compute` | `core/quant_core/optimize.py::run_optimization` trial loop (`1873+`) | One `_eval_one_trial` per candidate; large `n_trials` dominates runtime | Batch candidate eval with vectorized parameter matrix where possible; cache signal arrays keyed by (strategy params, window) |
| 4 | `Compute` | `core/quant_core/optimize.py::_eval_one_trial` per-symbol run_stats loop (`2521+`) | Python loop over symbols/candidates calls stats engine repeatedly | Move multi-symbol stats to vectorized 2D arrays / numba kernel; reduce Python dispatch per symbol |
| 5 | `Compute` | `core/quant_core/portfolio.py::run` main bar loop (`443+`) | Python per-bar/per-symbol execution logic in full path | Expand Numba path for richer metrics; keep full path only for artifact winners |
| 6 | `Compute` | `core/quant_core/optimize.py` top-k signal enrichment using `iterrows` (`1961`, `2006`) | Recomputes latest signal per top row with DataFrame row iteration | Precompute last-bar signals once per candidate or vectorize using adapter fast arrays |
| 7 | `Serialization/reporting` | `core/quant_core/pipeline.py::_df_to_records` and `_bundle_to_strategy_result` (`465+`, `832+`) | Repeated DataFrame copies + datetime formatting + `to_dict("records")` | Delay serialization until API boundary; keep internal payloads as typed arrays/frames |
| 8 | `Serialization/reporting` | `core/quant_core/results.py` trade ledger/perf builders using `iterrows` (`1021`, `1333`) | Row-wise pandas loops over fills are expensive on long histories | Replace with vectorized group ops or cython/numba for ledger assembly |
| 9 | `I/O` | `services/worker/tasks/execute_run.py::_persist_pipeline_output` artifact loops (`2321+`, `2508+`) | Many JSON uploads per symbol/strategy/plot in same run path | Split persistence stage async; compress/bundle artifacts; make plot persistence optional for optimization runs |
|10| `I/O` | `core/quant_core/optimize.py::_load_market_data_from_spec` (`2786+`) under fold/period workloads | Data load/alignment repeats across folds/processes; process-local cache only | Introduce cross-fold shared dataset object + immutable aligned arrays cache keyed by date window |

### Existing profiling/timing hooks

- `core/quant_core/optimize.py`:
  - `OptimizeTiming` (`load_ms`, `bank_ms`, `trial_total_ms`, cache hit/miss)
  - Optional cProfile capture (`profiling_enabled`)
- `core/quant_core/perf.py::lap(...)` lightweight phase timer helper
- `scripts/benchmarks/optimize_bench.py` benchmark script + optional cProfile
- `docs/optimization_trace.md` and `docs/optimization_diagnosis.md` contain profiling-oriented traces

### Suggested timer insertion points (proposal only; not implemented)

- `pipeline.py::_build_plot_artifacts` and `_build_summary_plot_artifacts` (serialization/render cost)
- `optimize.py` top-k signal enrichment loop (`_latest_signal_for_params` area)
- `execute_run.py::_persist_pipeline_output` around each artifact family (plot JSON, batch CSV, strategy summary plots)
- `pipeline.py` fold-level breakdown already exists; add split for train-opt vs test-eval serialization overhead

Source: core/quant_core/optimize.py:1867-1874
```python
# Optional cProfile capture
import cProfile, pstats, io as _io
_prof = cProfile.Profile() if cfg.profiling_enabled else None
if _prof is not None:
    _prof.enable()
for params in candidates:
    params_key = _trial_params_key(params)
```

Source: core/quant_core/portfolio.py:443-451
```python
for i in range(len(idx) - 1):
    t = pd.Timestamp(idx[i])
    t1 = pd.Timestamp(idx[i + 1])
    sig_row = signal_frame.signals.loc[t, symbols]
    sig_row = sig_row.copy()
    for s in symbols:
        raw_sig = float(signal_frame.signals.loc[t, s])
```

---

## 6) Artifact/output generation

### Where plots/reports are generated

- Report assembly:
  - `core/quant_core/results.py::ResultsAnalyzer.analyze`
- Plot object creation:
  - `core/quant_core/plots.py` (`make_drawdown_plot`, `make_cumreturn_vs_benchmark_plot`, `make_monthly_heatmap_plot`, `make_batch_period_heatmap_plot`, `make_yearly_return_bar_plot`)
- Pipeline packaging:
  - `core/quant_core/pipeline.py::_build_plot_artifacts`, `_build_summary_plot_artifacts`, `_bundle_to_strategy_result`, `_runtime_payload`

### Heavy artifacts produced

- In-memory pipeline output:
  - `leaderboard` rows (dict/list)
  - `strategy_results` including `trade_ledger`, `trade_performance`, decision payloads
  - `plot_artifacts` (Plotly JSON dicts)
  - `batch_period` payload including heatmap JSON and results rows
- Persisted by worker:
  - Plotly JSON files per symbol/strategy (`.../plots/*.json`)
  - Batch/WFO results CSV + heatmap JSON
  - Perf profile JSON (`runs/{run_id}/_perf/profile.json`)
  - Integrity/risk/significance JSON reports

### Storage handling (local/minio/s3 keys)

- Worker storage client: `services/worker/storage.py::s3_client`, bucket bootstrap via `ensure_bucket`.
- API storage client: `services/api/app/storage.py::s3_client`, `presign_get`.
- Canonical dataset key helper: `core/quant_core/s3_keys.py::build_dataset_object_key` (`datasets/{data_hash}/{filename}`).
- Worker persistence keys mostly under `runs/{run_id}/...` in `_persist_pipeline_output`.

### Coupling that can slow compute

- Compute and reporting are tightly coupled in `run_pipeline` payload shape (strategy results include serialized tables/plots).
- Worker persists artifacts immediately in same task execution path.
- Parallel optimization path re-runs full `run_pipeline` for top-N artifacts (`parallel_opt.py`), adding extra full runs after ranking.

Source: services/worker/tasks/execute_run.py:2320-2334
```python
# --- 1) plot artifacts ---
plot_artifacts = (out.get("plot_artifacts") or {}).get("symbols") or {}
for sym, fig_json in plot_artifacts.items():
    if not fig_json:
        continue
    object_key = f"runs/{rid}/symbols/{sym}/plots/price_indicators_trades.json"
    size_bytes, sha256, effective_key = _upload_json(object_key, fig_json, db=db)
```

Source: services/worker/tasks/parallel_opt.py:324-345
```python
# 7. Re-run best candidate(s) in full mode
for rank_i in range(min(top_n_artifacts, len(global_topk))):
    best_entry = global_topk[rank_i]
    best_params = dict(best_entry.get("params") or {})
    ...
    patched.setdefault("optimization", {})["parallel"] = False
    out = _run_pipeline(patched)
```
---

## 7) Correctness/robustness risks

Top 10 risks with location + mechanism.

| # | Risk | Location | Why this is a risk |
|---|---|---|---|
| 1 | Dual `slice_marketdata`/`slice_features` definitions (shadowing) | `core/quant_core/engine.py` (`58/65` and `673/704`) | Later definitions override earlier ones; behavior drift/confusion likely during maintenance/refactors. |
| 2 | Lookahead/exec timing contract depends on config guards | `core/quant_core/portfolio.py:363-366`, `core/quant_core/integrity.py:273-297` | Guard exists, but any alternate path bypassing these checks can silently violate t+1 assumptions. |
| 3 | Multi-symbol calendar mismatch may distort signals | `core/quant_core/strategy.py:_build_common_index` | Uses union index with NaN handling; high union/intersection mismatch only warns, can alter strategy behavior materially. |
| 4 | Multi-symbol optimization fallback not implemented | `core/quant_core/optimize.py:2327-2334` | Returns `-inf` trials instead of full multi-asset logic; can silently degrade optimization quality if triggered. |
| 5 | WFO hard dependency on pre-resolved dates | `core/quant_core/pipeline.py:1271-1274` | Missing resolution raises runtime error; integration points must always provide resolved bounds. |
| 6 | WFO start/end alignment can change intended windows | `core/quant_core/wfo/date_resolution.py:59-70`, `78-88`, `110-115` | Start snaps to next bar and end snaps to previous bar; objective windows can differ from user-entered dates. |
| 7 | Benchmark alignment via forward-fill may mask gaps/regime breaks | `core/quant_core/results.py:269-278` | `bpx.reindex(...).ffill()` can smear stale benchmark prices through missing intervals. |
| 8 | Fee/cost column normalization complexity can introduce inconsistencies | `core/quant_core/results.py` trade table/ledger conversion (`653+`, `707+`, `833+`) | Multiple aliases (`cost`, `fees`, components) and transformations increase risk of double-counting/mismatch. |
| 9 | Survivorship/corporate-actions handling mostly metadata-based | `core/quant_core/integrity.py:255-262` | Data-quality bias checks rely on dataset flags and may return warning, not strict fail, when metadata is absent. |
|10| Worker chunk evaluator imports non-existent storage helper | `services/worker/tasks/evaluate_chunk.py:34` vs `services/worker/storage.py` | Imports `get_s3_client`, but storage module exposes `s3_client`; potential runtime failure in parallel chunk path. |

Source: core/quant_core/engine.py:673-680
```python
def slice_marketdata(
    md,
    start: Optional[str],
    end: Optional[str],
    include_windows: Optional[List[Tuple[str, str]]] = None,
    exclude_windows: Optional[List[Tuple[str, str]]] = None,
):
```

Source: services/worker/tasks/evaluate_chunk.py:33-35
```python
from services.worker.db import SessionLocal
from services.worker.storage import get_s3_client
```

---

## 8) “Fix & Optimize Plan” (proposal only)

### P0 correctness blockers

1. Unify engine slicing helpers
   - Remove duplicate `slice_marketdata`/`slice_features` definitions in `engine.py`; keep one contract and enforce typed signatures.
2. Enforce WFO date-resolution contract at API and worker boundaries
   - Validate resolved date fields before `run_pipeline` dispatch; fail fast with explicit diagnostics.
3. Harden multi-symbol optimization behavior
   - Replace `_eval_one_trial_slow_pandas` sentinel `-inf` path with explicit hard error unless multi-symbol fast path is implemented.
4. Fix worker storage import mismatch
   - Align `evaluate_chunk.py` import with `services/worker/storage.py` API.

### P1 big speed wins

1. Compile spec + params into array-native trial plans
   - Precompile candidate params into contiguous arrays (ints/floats) and avoid per-trial dict churn.
2. Indicator cache by `(symbol, interval, indicator_family, params_hash, window_slice)`
   - Reuse across folds/horizons/periods, not only within one `run_optimization` call.
3. Vectorized multi-candidate signal evaluation
   - For strategies with simple thresholds/crossovers, evaluate many candidates in one pass over arrays.
4. Vectorized/batched portfolio stats
   - Extend Numba kernels from single candidate/symbol to candidate-batched evaluation.
5. Separate compute from reporting
   - Make `run_pipeline` compute payload lean by default; defer report serialization/plots to explicit materialization stage.

### P2 architecture cleanup

1. Introduce explicit contracts between modules
   - `DataBundle`, `FeatureBundle`, `SignalBundle`, `StatsResult`, `ArtifactBundle` typed boundaries.
2. Split orchestration layers
   - `pipeline_core` (pure compute) vs `pipeline_materialize` (tables/plots/serialization).
3. Normalize artifact persistence interfaces
   - Worker persistence should consume stable artifact contracts, independent from internal compute objects.
4. Add focused perf instrumentation map
   - Standardized timers around optimizer inner loops, fold orchestration, and persistence.

### Complexity/cost notes (rough)

- Current dominant cost pattern is repeated `O(N_candidates * N_bars * N_symbols)` plus repeated orchestration/materialization overhead.
- Caching and batched array evaluation do not change asymptotic candidate-bar complexity, but can substantially cut constants:
  - fewer dataframe conversions/copies
  - fewer repeated indicator recomputations
  - fewer Python-level loops in inner paths
- Separating compute/reporting removes expensive serialization from ranking loops, improving throughput and lowering peak memory.

**Non-goals:** No behavior changes in Phase 1; refactor only.

---

Context packet generated: CONTEXT_PACKET_QUANT_CORE.md
