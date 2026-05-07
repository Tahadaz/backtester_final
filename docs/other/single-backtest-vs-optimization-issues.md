# Single Backtest vs Optimization: Why Results Look Wrong

## What Changed Earlier

The earlier fix was only in the BMCE market-data loader.

- `core/quant_core/data.py`
  - Added normalized BMCE/French header aliases so uploaded files with columns like `Ouverture`, `+haut`, `+bas`, `Close`, and even `Volue` are mapped to canonical `Open/High/Low/Close/Volume`.
  - Reused that normalization in both the local BMCE file loader and the Bourse-direct loader path.
- `core/tests/test_bmce_data_source.py`
  - Added a regression test for those header variants.

That fix only affects data ingestion. It does **not** change optimizer behavior, ranking, or portfolio math.

## Why You Are Seeing Weird Results

### 1. A "single backtest" is not an optimization run

In `core/quant_core/pipeline.py:1066-1068`, the pipeline only enters optimization mode when at least one of these is true:

- `optimization.n_trials > 0`
- `optimization.kinds` is non-empty
- `optimization.walk_forward.enabled == true`

If those are not present, the code runs a plain `BacktestEngine(engine_spec).run()` with the params already in the spec.

Implication:

- Setting `optimization.method = "grid"` alone is not enough.
- If `n_trials` is `0` and `kinds` is empty, you are not optimizing anything.

### 2. The API `mode` label is misleading for optimization runs

In `services/api/app/routers/runs.py:112`, `_infer_mode()` returns only:

- `"walk_forward"` when walk-forward is enabled
- `"single"` for everything else

But `_infer_run_type()` in `services/api/app/routers/runs.py:101` separately classifies runs as `"optimization"` when `n_trials > 0` or `kinds` is non-empty.

Implication:

- A real optimization run can still have `mode = "single"`.
- That can make the UI or logs look like you ran a single backtest when the run type was actually optimization.

### 3. Strategy detail materialization intentionally disables optimization

In `services/api/app/routers/runs.py:868`, `_prepare_detail_spec()` rebuilds a detail-view spec and then at `services/api/app/routers/runs.py:931` forces:

- `spec_json["optimization"] = {"n_trials": 0, "kinds": []}`

Implication:

- Clicking a leaderboard row or materializing strategy details is a deterministic rerun of one chosen parameter set.
- It is not a fresh grid search.
- If you expected the detail panel to still be "the optimizer", that expectation does not match the code.

### 4. Sequential optimization ignores `rank_metric`

The normal optimizer in `core/quant_core/optimize.py:1953` and `core/quant_core/optimize.py:1998` ranks rows with:

- `sort_values(["pnl", "cagr"], ascending=[False, False])`

So sequential optimization is effectively hard-wired to `pnl`, then `cagr`.

But the parallel optimization path reads `optimization.rank_metric` in:

- `services/worker/tasks/parallel_opt.py:75`
- `services/worker/tasks/evaluate_chunk.py:68`

Implication:

- The same spec can select different winners depending on whether `optimization.parallel` is on.
- If you expected optimization by Sharpe, max drawdown, efficiency, or another metric, the sequential path is not honoring that.

### 5. Optimization drops several user strategy settings and resets them to defaults

In `core/quant_core/pipeline.py:2169`, optimization rebuilds each candidate strategy with:

- `StrategyConfig(kind=k, params={})`

That wipes non-optimized strategy settings from the original run spec before the search starts.

This is especially dangerous for strategies whose behavior depends on non-window params, for example:

- `sma_price.signal_mode`
- `rsi.mode`
- `macd.trigger`
- `allow_short`
- `nan_policy`

Implication:

- You may think you optimized "your" strategy, but the optimizer may actually be evaluating default strategy behavior instead.
- The selected "best" params can therefore look unrelated to the original single backtest setup.

This is likely one of the main reasons the results feel wrong.

### 6. Optimization and full backtest do not use the same evaluation path

The optimizer uses the fast stats-only path:

- `core/quant_core/portfolio.py:662`
- `core/quant_core/portfolio.py:695`
- `core/quant_core/portfolio.py:795`

The optimization loop in `core/quant_core/optimize.py:1711` evaluates candidates through `_eval_one_trial()` and `run_stats_only_arrays()` instead of the full report-generation path.

Implication:

- Candidate ranking is done with a simplified evaluator for speed.
- Full reruns and detail views go through the richer engine/reporting path.
- Small or medium differences between leaderboard ranking and final detailed artifacts are therefore possible by design.

## Most Likely Root Causes In Your Case

The strongest candidates are:

1. Your run is being treated as a plain backtest because the spec does not actually trigger optimization.
2. The UI/detail flow is rerunning a single deterministic backtest from one row, not re-running grid search.
3. The optimizer is resetting non-optimized strategy params to defaults before searching.
4. The sequential optimizer is ranking by `pnl`/`cagr` even if you expected another objective.

## What To Check In The Spec

Check the run spec for these fields:

- `optimization.kinds`
- `optimization.method`
- `optimization.n_trials`
- `optimization.parallel`
- `optimization.rank_metric`
- `strategy.params`

If you want a real grid optimization, the minimum expectation is:

- `optimization.method = "grid"`
- `optimization.kinds` contains the strategy kind(s) you want optimized
- the domains for those kinds are defined if you want custom search ranges

## Practical Conclusion

The weird behavior is not explained by the BMCE header fix. The real issues are in the optimization orchestration and in the mismatch between:

- backtest mode vs optimization mode
- sequential optimizer vs parallel optimizer ranking
- original strategy params vs params actually used during optimization
- optimizer fast path vs full detail rerun path

If you want, the next step should be to fix the highest-impact bug first:

1. preserve original `strategy.params` during optimization instead of resetting them to `{}`
2. make sequential optimization honor `optimization.rank_metric`
3. make `mode` distinguish optimization from true single-backtest runs
