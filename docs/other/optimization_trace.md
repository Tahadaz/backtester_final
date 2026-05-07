# Optimization Execution Trace

Exact call chain for an optimization run, with `file:line` pointers and a clear
breakdown of what runs **once per run**, **once per fold**, and **once per trial**.

---

## Top-Level Entry Points

### API → Worker

| Step | What | File:Line |
|------|------|-----------|
| HTTP POST `/runs` | Creates `Run` row, status=`created` | `services/api/app/routers/runs.py:~899` |
| HTTP POST `/runs/{id}/start` | Enqueues RQ/Celery task | `services/api/app/routers/runs.py:~1064` |
| Worker task | `execute_run(run_id)` | `services/worker/tasks/execute_run.py:2475` |

---

## `execute_run()` — Worker Task

**Runs once per optimization run.**

```
execute_run(run_id)                                              execute_run.py:2475
  │
  ├─ Fetch run row + spec_json from DB                          :2490–2500
  ├─ Detect profiling flag (spec_json.analysis.profile.enabled) :2503–2507
  ├─ Materialize dataset (S3 → temp parquet if needed)          :2605–2642
  ├─ _apply_wfo_defaults(spec_json)                             :2648
  ├─ _persist_run_repro_metadata(...)                           :2654–2660
  │
  ├─ [single-symbol path]
  │     run_pipeline(spec_json)                                 :2786
  │
  ├─ [batch-per-symbol path]
  │     _run_symbol_pipeline(spec_json, symbol, dataset_path)   :2711 (per symbol)
  │
  ├─ _persist_pipeline_output(db, rid, out, ...)               :2792 (fills, ledger, plots, leaderboard)
  ├─ _persist_optimization_timing(db, rid, out)                :2454 (opt.* metrics + profile.txt)
  └─ Mark run succeeded/failed                                  :2836–2954
```

**Profiling artifacts (when `spec_json.analysis.profile.enabled = true`):**
- `opt.load_ms`, `opt.bank_ms`, `opt.trial_total_ms`, `opt.n_trials_run`,
  `opt.avg_trial_ms`, `opt.cache_hits`, `opt.cache_misses` → persisted as `run_metric` rows
- cProfile text → uploaded as `runs/{run_id}/_debug/profile.txt` artifact

---

## `run_pipeline()` — Pipeline Orchestrator

**Runs once per optimization run (or once per WFO fold for walk-forward).**

```
run_pipeline(spec_json)                                          pipeline.py:156
  │
  ├─ Build EngineSpec from spec_json                            :186–256
  ├─ Determine opt_kinds (strategy list), n_trials, method      :997–1001
  ├─ Build OptimizeConfig                                       :1039–1048
  │
  ├─ [walk-forward multi-horizon]
  │     recursive run_pipeline() per horizon                    :1108
  │
  ├─ [walk-forward / batch periods — per FOLD]
  │     For each fold (train period):
  │       run_optimization(train_spec, active_params, cfg)      :~1365 (optimize.py)
  │       BacktestEngine(test_spec).run()                       :1424  ← materialize winner
  │
  ├─ [standard optimization — once]
  │     _run_kind(kind)                                         :1769
  │       run_optimization(base_spec, active_params, cfg)       :1780 (optimize.py)
  │       BacktestEngine(best_spec).run()                       :1786  ← materialize winner
  │
  ├─ Aggregate OptimizeTiming across kinds → _timing_summary    :1872–1888
  └─ Return {leaderboard, strategy_results, fills, metrics,
             optimization_timing, plot_artifacts, ...}          :1890–1907
```

**Pattern: materialize winners only.**
`run_optimization()` ranks N trials cheaply. `BacktestEngine.run()` is called
**once** for the winner to produce fills, trade ledger, plots, and full metrics.

---

## `run_optimization()` — Fast Optimizer Inner Loop

**Runs ONCE PER FOLD (or once per run in non-WFO mode).**

```
run_optimization(base_spec, active_params, cfg)                  optimize.py:1684
  │
  ├─ [ONCE] Select StrategyAdapter from STRATEGY_ADAPTERS        :1705
  │
  ├─ [ONCE] Load market data (_load_market_data_from_spec)       :1721
  │            time tracked → OptimizeTiming.load_ms
  │            Result cached in _MARKET_DATA_CACHE (process-level)
  │
  ├─ [ONCE] Align data, extract numpy price arrays               :1730–1759
  │
  ├─ [ONCE] Build indicator bank (build_bank)                    :1764
  │            time tracked → OptimizeTiming.bank_ms
  │            Precomputes ALL indicator windows needed for ALL trials
  │
  ├─ [ONCE] Compute ADV arrays (if participation cap/gate)       :1775–1787
  │
  ├─ [ONCE] Slice to eval window                                 :1790–1808
  │
  ├─ [ONCE] Pre-hoist PortfolioEngine when no portfolio params   :1824–1829
  │            are being varied (avoids N identical instantiations)
  │
  ├─ [ONCE] Build candidate iterator (grid or random-deduplicated):1817–1821
  │
  ├─ [PER TRIAL] Trial evaluation loop                           :1838–1882
  │     for params in candidates:
  │       if params_key in eval_cache → cache_hit, skip
  │       _eval_one_trial(...)           time tracked → trial_total_ms
  │       eval_cache[params_key] = result
  │
  ├─ [ONCE] Optional cProfile capture                            :1884–1891
  │
  ├─ [ONCE] Build ranked_df, compute top-k signal snapshots      :1904–1990
  │
  └─ Return (best_result, top_df, best_params, best_spec,
              ranked_df, OptimizeTiming)                         :1960 / :2006
```

---

## `_eval_one_trial()` — Per-Trial Evaluation

**Runs ONCE PER UNIQUE PARAMETER SET.**

```
_eval_one_trial(base_spec, md, common_index, bank, bars_*, ...)  optimize.py:2303
  │
  ├─ [optional] Slice to data.window if param present            :2331–2360
  │
  ├─ Use pre-hoisted PortfolioEngine (or create per-trial)        :2366–2371
  │
  ├─ Build trial-local view of bank/price arrays (refs, no copy) :2378–2430
  │
  ├─ Signal generation (fast array path preferred)               :2432–2470
  │     adapter.make_signal_arrays_fast(symbols, bank, ...)       → Dict[str, ndarray]
  │     Returns {-1, 0, 1} arrays directly from pre-computed bank
  │     (Fallback: adapter.make_signals_from_bank → DataFrame)
  │
  ├─ [PER SYMBOL] Portfolio simulation                           :2478–2507
  │     port.run_stats_only_arrays(open_px, close_px, sig, ...)
  │       → _run_stats_fast_single_nb(...)  [Numba JIT]
  │       Returns (pnl, traded_notional, n_fills, final_equity) only
  │       NO trade fill records, NO ledger, NO plots
  │
  ├─ CAGR calculation                                            :2509–2516
  │
  └─ Return TrialResult(params, pnl, traded_notional,
                         efficiency, n_fills, cagr, error)       :2520–2527
```

---

## Frequency Summary

| Operation | Frequency | Time Tracked |
|-----------|-----------|--------------|
| Module import / Numba JIT warmup | Once per worker process | N/A (at import) |
| `_load_market_data_from_spec()` | Once per `run_optimization()` call | `opt.load_ms` |
| `build_bank()` | Once per `run_optimization()` call | `opt.bank_ms` |
| `PortfolioEngine` + `NBConfig` creation | Once per run (hoisted when no portfolio params vary) | — |
| `_eval_one_trial()` | Once per unique param set | `opt.avg_trial_ms`, `opt.trial_total_ms` |
| `adapter.make_signal_arrays_fast()` | Once per trial | within trial |
| `_run_stats_fast_single_nb()` | Once per trial × symbol | within trial (Numba) |
| `BacktestEngine.run()` (materialize) | Once per winner | after trial loop |
| Plot generation | Once per winner | after trial loop |
| Fill ledger / position ledger | Once per winner | after trial loop |

---

## Key Invariants

1. **No plots in trial loop.** `_eval_one_trial` calls only `run_stats_only_arrays` which
   returns 4 scalars. No Plotly figures, no matplotlib, no artifact uploads.

2. **No fill records in trial loop.** `_run_stats_fast_single_nb` (Numba) computes PnL
   without building a fill ledger. Fills are generated only in `BacktestEngine.run()` for the winner.

3. **No BacktestReport in trial loop.** `ResultsAnalyzer.analyze()` is never called during
   optimization trials. It runs once for the materialized winner.

4. **Indicators precomputed once.** `build_bank()` computes the union of all indicator
   windows needed across all trials. Each trial reads from the shared bank dict (numpy arrays).

5. **Numba JIT loaded at import.** `_warmup_nb_jit()` is called at `portfolio.py` module
   bottom, ensuring the Numba kernel is compiled/loaded before the first optimization request.

6. **Duplicate params deduped.** `_iter_random()` generates without-replacement samples
   capped at `min(n_trials, grid_size)`. Additional cache in the trial loop skips any remaining duplicates.

---

## Strategy Adapters

Adapters are registered in `STRATEGY_ADAPTERS` dict (`optimize.py:~1680`).

| Adapter Class | Strategy Kind | Fast Path |
|--------------|---------------|-----------|
| `MACrossAdapter` | `ma_cross` | `make_signal_arrays_fast()` |
| `PriceAboveSMAAdapter` | `price_above_sma` | `make_signal_arrays_fast()` |
| `RSIStrategyAdapter` | `rsi` | `make_signal_arrays_fast()` |
| `MACDStrategyAdapter` | `macd` | `make_signal_arrays_fast()` |
| `BollingerBandsAdapter` | `bollinger_bands` | `make_signal_arrays_fast()` |
| `OBVAdapter` | `obv` | `make_signal_arrays_fast()` |
| `StochVWAPAdapter` | `stoch_vwap` | `make_signal_arrays_fast()` |
| `IchimokuAdapter` | `ichimoku` | `make_signal_arrays_fast()` |

All implement `required_bank()` (declares needed indicators) and
`make_signal_arrays_fast()` (generates `{-1,0,1}` signal arrays from pre-computed bank).
