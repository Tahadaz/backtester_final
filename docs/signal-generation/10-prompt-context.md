# Signal Generation — Prompt Context Blocks

Copy-paste context blocks for LLM-assisted signal development. Each block is self-contained and can be dropped into a prompt to give an AI assistant the context it needs to work on a specific part of the signal generation layer.

---

## Block 1: Signal Architecture Overview

```
SIGNAL GENERATION LAYER — ARCHITECTURE CONTEXT

Station mandate: Transform raw OHLCV data into informative directional signals (+1/0/-1)
with measurable OOS predictive power. Signals express intent, not orders.

Key files:
- core/quant_core/indicators.py — indicator implementations (pandas path)
- core/quant_core/optimize.py — indicator bank (numpy fast path) + optimization engine
- core/quant_core/strategy.py — strategy classes (generate_signals → SignalFrame)
- core/quant_core/pipeline.py — WFO fold construction + per-fold evaluation
- core/quant_core/portfolio.py — signal interpretation (fills at next-open)
- core/quant_core/research/horizon.py — HorizonConfig presets (short/medium/long)
- core/quant_core/wfo/date_resolution.py — WFO date alignment to actual trading days

Signal flow:
  OHLCV → Indicators (SMA, RSI, MACD, etc.) → Decision rules → Signal array {-1, 0, +1}
  Signal array → Portfolio engine (position sizing, costs, cooldown) → PnL

Timing convention: signal computed at Close(t), fill at Open(t+1).
No look-ahead: indicator warmup is padded before evaluation window.

8 strategy adapters: ma_cross, sma_price, rsi, macd, bollinger, obv, stoch_vwap, ichimoku
Each implements: required_bank(), make_signal_arrays_fast(), validate_params()
```

---

## Block 2: Indicator Bank & Optimization Fast Path

```
OPTIMIZATION FAST PATH — PERFORMANCE CONTEXT

The optimization engine evaluates 100-1000 parameter combinations per run.
Performance is critical: 38x speedup achieved via indicator bank + Numba kernels.

Architecture:
1. Load data ONCE: load_market_data() → {symbol: DataFrame}
2. Build indicator bank ONCE: build_bank(close, high, low, vol, BankRequest) → {sym: {key: ndarray}}
   - BankRequest declares ALL indicator variants needed across the entire parameter grid
   - Adapters declare needs via required_bank() method
   - Bank keys: "sma_20", "rsi_14", "macd_12_26_9", "stoch_k_14_3_1", etc.
3. Trial loop: for each candidate_params:
   - make_signal_arrays_fast() looks up bank[sym][f"sma_{w}"] → O(1) per trial
   - run_stats_only_arrays() → Numba @njit kernel → returns 4 scalars (pnl, cagr, n_fills, efficiency)
   - NO DataFrames, NO plots, NO BacktestReport in the trial loop
4. Materialize winner ONCE: BacktestEngine.run() for best params only

Key invariants:
- eval_cache: frozenset(params.items()) → TrialResult (dedup identical params)
- PortfolioEngine hoisted outside loop (reused across trials)
- Numba JIT warmed at module import via _warmup_nb_jit()
- Per-trial cost: ~0.2ms (down from ~18ms without bank)

Benchmark: 100 trials, 3 symbols: 47.6ms total (420 trials/sec)
```

---

## Block 3: Walk-Forward Validation

```
WALK-FORWARD OPTIMIZATION (WFO) — VALIDATION CONTEXT

WFO ensures signals are validated on data the optimizer never saw.

Fold construction: build_walk_forward_period_entries() in pipeline.py
  - Rolling (default): fixed-size train window slides forward with test window
  - Anchored: train always starts at span origin (expanding window)
  - Step size: 21 days (~1 month) between consecutive test starts

Horizon presets (core/quant_core/research/horizon.py):
  short:  train=252d, test=63d,  step=21d, lookback=5yr   (~60 folds)
  medium: train=504d, test=126d, step=21d, lookback=10yr  (~110 folds)
  long:   train=756d, test=252d, step=21d, lookback=20yr  (~180 folds)

Per-fold flow (_eval_fold in pipeline.py):
  1. Train: run_optimization() on [train_start, train_end] → top-K candidates
  2. Test: BacktestEngine.run(fast_mode=True) on [test_start, test_end] per candidate
  3. Record: OOS metrics (pnl, cagr, sharpe, max_dd, win_pct)

Cross-fold aggregation:
  - Group by (strategy_kind, trial_id, parameter_set)
  - Compute mean/median/std of OOS metrics across all folds
  - Winner = argmax(mean OOS metric)

Date resolution: resolve_wfo_start_end_dates() snaps user dates to actual trading days.
Chronology invariant: max(train_dates) < min(test_dates) for every fold.

Data persistence:
  DB: run_fold (per-fold details), run_wfo_period (per-fold winners)
  S3: runs/{id}/wfo/{symbol}/{horizon}/folds.json, summary.json
```

---

## Block 4: Strategy Adapter Implementation

```
STRATEGY ADAPTER — IMPLEMENTATION CONTEXT

To add a new strategy adapter:

1. Define the adapter class in optimize.py:
   class NewAdapter(StrategyAdapter):
       def required_bank(self, base_spec, active_params) -> BankRequest:
           # Declare all indicator variants needed across the parameter grid
           req = BankRequest()
           for param in active_params:
               if param.key == "strategy.my_window":
                   lo, hi, step = param.domain
                   req.sma.update(range(lo, hi + 1, step))
           return req

       def make_signal_arrays_fast(self, symbols, bank, close, high, low, vol,
                                     params, base_spec) -> Dict[str, np.ndarray]:
           # Fast numpy signal generation using bank lookups (NOT indicator computation)
           w = params["strategy.my_window"]
           result = {}
           for sym in symbols:
               indicator = bank[sym][f"sma_{w}"]  # O(1) lookup
               signal = np.where(close[sym] > indicator, 1.0, -1.0)
               result[sym] = signal
           return result

       def validate_params(self, params) -> bool:
           # Reject invalid parameter combinations
           return True

2. Register in STRATEGY_ADAPTERS dict:
   STRATEGY_ADAPTERS["new_strategy"] = NewAdapter()

3. Add ParamDef entries to the default catalog (if optimizable)

4. Add corresponding Strategy class in strategy.py for single-backtest mode

Signal contract:
  - Return Dict[str, np.ndarray] mapping symbol → signal array
  - Signal values: +1.0 (buy intent), -1.0 (exit intent), 0.0 (neutral)
  - Array length must match close array length
  - NaN handling: use 0.0 for warmup period (flat policy)
```

---

## Block 5: Signal Engine Pipeline (Planned)

```
SIGNAL ENGINE — PLANNED PIPELINE CONTEXT

Package: core/quant_core/signal_engine/

7-layer pipeline (A → G):

Layer A — candidates.py: generate_sma_candidates(horizon) → list[VariantDef]
  - Structured archetypes (price_vs_sma, sma_cross, slope_confirmed)
  - 8-12 candidates per family × horizon
  - Deterministic, auditable code constants

Layer B — oos_eval.py: evaluate_variant_oos(close, variant, horizon) → list[OOSWindowResult]
  - Rolling walk-forward evaluation
  - Signal-at-close, fill-at-next-open convention
  - Net of transaction costs (cost_bps parameter)

Layer C — robustness.py: score_variant_robustness(oos_results) → VariantRobustnessSummary
  - reliability_score = weighted combination:
    0.35 * sharpe_score + 0.30 * stability + 0.20 * consistency + 0.15 * drawdown
  - Viability gate: n_windows >= 3 AND fraction_positive >= 0.40

Layer D — survivor.py: filter_survivors(summaries) → list[survivors]
  - Absolute floor: reliability_score >= 0.25
  - Relative filter: percentile rank >= 40th percentile

Layer E — redundancy.py: reduce_redundancy(survivors, close) → list[representatives]
  - Compute signal-level Pearson correlation
  - Greedy selection: keep if max|corr| with already-selected <= 0.85
  - Cap at max_representatives=6

Layer F — current_signal.py: compute_current_signal(close, variant) → VariantCurrentSignal
  - Latest bar signal: +1/-1/0
  - Human-readable explanation: "Close 124.5 > SMA-50 118.2 → BUY"

Layer G — ensemble.py: combine_family_signals(reps, signals) → FamilyCombinedSignal
  - family_score_pct = 100 * Σ(w_i * s_i) / Σ(w_i)
  - Per-representative attribution for UI drill-down

Entry point: run_sma_ensemble(close, symbol, horizon) → full pipeline A→G

Domain objects: VariantDef, OOSWindowResult, VariantRobustnessSummary,
                VariantCurrentSignal, FamilyCombinedSignal
```

---

## Block 6: Adding a New Signal Family

```
ADDING A NEW SIGNAL FAMILY — CHECKLIST

Example: Adding the RSI family to the signal engine.

Backend (core/quant_core/signal_engine/):

1. candidates.py — Add generate_rsi_candidates(horizon):
   - Define archetypes: level_reversal, persistence, reversal_confirmation
   - Define parameter neighborhoods per horizon
   - Return list[VariantDef] with family="rsi"

2. oos_eval.py — Ensure evaluate_variant_oos handles RSI variants:
   - Compute RSI indicator from close series
   - Apply archetype-specific decision rule
   - Return OOS window results (same format as SMA)

3. ensemble.py — Add run_rsi_ensemble() entry point:
   - Calls generate_rsi_candidates → evaluate → score → filter → reduce → combine
   - Returns FamilyCombinedSignal with family="rsi"

4. Tests (core/tests/test_signal_engine.py):
   - test_rsi_candidate_universe_horizons — non-empty, deduplicated per horizon
   - test_rsi_oos_chronology — no future bar used in test window
   - test_rsi_reliability_bounds — score always in [0,1]

API (services/api/app/routers/strategy_signals.py):

5. Add endpoint: POST /strategy/signal/rsi-ensemble
   - Body: { "symbol": "AAA", "horizon": "medium" }
   - Calls run_rsi_ensemble()

Frontend (quant-backtesting-frontend/):

6. lib/api.ts — Add RsiEnsembleResponseSchema, fetchRsiEnsemble()
7. components/strategy/technical-analysis-panel.tsx — Enable RSI family gauge
8. components/strategy/rsi-drill-down.tsx — Level 2+3 RSI detail view

Key principle: The pipeline layers (C through G) are family-agnostic.
Only Layers A and B (and the archetype-specific signal computation in B)
need family-specific code. The filtering, scoring, and ensemble logic is shared.
```

---

## Usage Notes

- Each block is designed to fit within a typical LLM context window alongside code
- Blocks reference file paths and line numbers that may shift as the codebase evolves — verify against current code
- Block 5 and 6 describe *planned* architecture from `strategy_signal_generation_plan.md` — the signal_engine package does not yet exist
- Blocks 1–4 describe *implemented* architecture that is live in the codebase
- For the most current file:line references, use `git grep` or read the source files directly
