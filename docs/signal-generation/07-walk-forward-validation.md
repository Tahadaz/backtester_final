# Signal Generation — Walk-Forward Validation

**Files:** `core/quant_core/pipeline.py`, `core/quant_core/wfo/date_resolution.py`, `core/quant_core/research/horizon.py`

Walk-forward optimization (WFO) is the station's primary defense against overfitting. It ensures that every signal reported as "good" has demonstrated predictive power on **data it has never seen**.

---

## Why In-Sample Performance Is Meaningless

A strategy optimized on historical data will *always* show positive returns on that same data — this is tautological. The optimizer's job is to find parameters that fit the past. The question is whether the pattern generalizes.

**The overfitting problem, formally:**

Given a parameter search over `K` candidates on `N` data points, the probability of finding at least one candidate with spurious in-sample performance grows as:

```
P(max Sharpe_IS > threshold) = 1 - (1 - p)^K
```

where `p = P(Sharpe_IS > threshold | no true skill)`. For K = 1000 candidates and p = 0.01, P ≈ 0.9999. You are *guaranteed* to find something that looks good in-sample, regardless of whether any candidate has true predictive power.

**The only honest test:** Evaluate on data the optimizer has never touched. This is the out-of-sample (OOS) principle.

**References:**
- Bailey, D.H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio." *Journal of Portfolio Management*, 40(5), 94–107.
- Harvey, C.R. & Liu, Y. (2015). "Backtesting." *Journal of Portfolio Management*, 42(1), 13–28.

---

## Walk-Forward vs Simple Train/Test Split

### Simple split (dangerous)
```
|████████████ Train ████████████|████ Test ████|
2015-01                        2022-01        2024-12
```

Problems:
1. **Single sample:** One test window → one OOS Sharpe estimate → high variance
2. **Regime dependence:** If the test window happens to be a bull market, every trend-following signal looks good
3. **Endpoint sensitivity:** Moving the split date by 6 months can flip the conclusion

### Walk-forward (robust)
```
Fold 1: |████ Train ████|██ Test ██|
Fold 2:     |████ Train ████|██ Test ██|
Fold 3:         |████ Train ████|██ Test ██|
Fold 4:             |████ Train ████|██ Test ██|
...
```

Advantages:
1. **Multiple OOS samples:** Average across many test windows → lower variance estimate
2. **Regime diversity:** Test windows span different market conditions (bull, bear, sideways)
3. **Temporal stability:** Can detect if a signal works in early folds but degrades in later folds
4. **No look-ahead:** Every test window strictly follows its train window in time

---

## The Chronology Invariant

**Rule:** For every fold `i`, every bar in the test window has a timestamp strictly greater than every bar in the train window.

```
∀ fold i:  max(train_dates_i) < min(test_dates_i)
```

This invariant is enforced by `build_walk_forward_period_entries()` in `pipeline.py`. Violations would constitute look-ahead bias — the single most destructive error in backtesting research.

**Why this matters for signals specifically:** Indicators like SMA or RSI use rolling windows. If any part of the indicator computation reaches into the test period during training, the signal has implicitly "seen" future data. The warmup padding mechanism (see [04-signal-semantics.md](./04-signal-semantics.md)) ensures indicators are fully warmed up before the evaluation window begins.

---

## Fold Construction Algorithm

### `build_walk_forward_period_entries()`

Location: `core/quant_core/pipeline.py`, lines 88–158

```python
def build_walk_forward_period_entries(
    *,
    start: str,              # Span start (resolved)
    end: str,                # Span end (resolved)
    train_value: int,        # Train window size (e.g., 252)
    train_unit: str,         # "days", "weeks", "months", "years"
    test_value: int,         # Test window size (e.g., 63)
    test_unit: str,
    step_value: int,         # Step between consecutive test starts (e.g., 21)
    step_unit: str,
    anchored: bool,          # Anchored vs rolling (see below)
    max_folds: int | None,   # Safety cap
) -> list[dict[str, str]]:
```

**Algorithm:**

1. Parse `start` and `end` to `pd.Timestamp`
2. Compute `first_test_start = start + train_duration`
3. Initialize `test_start = first_test_start`
4. **Loop** while `test_start < end`:
   - If **anchored**: `train_start = start` (fixed origin)
   - If **rolling**: `train_start = test_start - train_duration`
   - Clamp: `train_start = max(train_start, start)`
   - `train_end = test_start - 1 trading day`
   - `test_end = min(test_start + test_duration - 1 day, end)`
   - Emit fold: `{label, train_start, train_end, test_start, test_end}`
   - Advance: `test_start += step_size`
5. Stop when `test_end >= end` or `max_folds` reached

**Output:** List of fold dicts, each containing ISO-format date strings.

---

## Anchored vs Rolling Windows

### Rolling (default, `anchored=False`)

The train window slides forward with the test window. Train size is constant.

```
Fold 1: [========= 252d train =========][=== 63d test ===]
Fold 2:      [========= 252d train =========][=== 63d test ===]
Fold 3:           [========= 252d train =========][=== 63d test ===]
```

**Properties:**
- Fixed training set size → consistent statistical power across folds
- Recent folds use only recent data → adapts to regime changes
- Early data is eventually discarded → may lose valuable long-term patterns
- **Best for:** Detecting if a signal works *recently*, not just historically

### Anchored (`anchored=True`)

The train window always starts at the span origin. Train size grows over time.

```
Fold 1: [========= train =========][=== test ===]
Fold 2: [============= train =============][=== test ===]
Fold 3: [================== train ==================][=== test ===]
```

**Properties:**
- Expanding training set → more data for later folds → potentially better optimization
- All historical data contributes to every fold → preserves long-term patterns
- Later folds may be dominated by old data → slower to adapt
- **Best for:** Detecting if a signal is robust across the entire history

### Clamping behavior

If rolling mode would place `train_start` before the span start, it is clamped:

```python
if train_start_ts < start_ts:
    train_start_ts = start_ts  # Becomes effectively anchored for early folds
```

This means early folds in rolling mode may behave like anchored folds when history is short relative to the train window.

---

## Horizon Presets

Location: `core/quant_core/research/horizon.py`

Three built-in horizons define window sizes calibrated to different investment timeframes:

| Horizon | Label | Train Window | Test Window | Step Size | Lookback |
|---------|-------|-------------|-------------|-----------|----------|
| `short` | Court terme | 252 days (~1 yr) | 63 days (~3 mo) | 21 days (~1 mo) | 5 years |
| `medium` | Moyen terme | 504 days (~2 yr) | 126 days (~6 mo) | 21 days (~1 mo) | 10 years |
| `long` | Long terme | 756 days (~3 yr) | 252 days (~1 yr) | 21 days (~1 mo) | 20 years |

### Design rationale

- **Train/test ratio:** Approximately 4:1 for all horizons. This follows the empirical finding that training sets need to be significantly larger than test sets for stable optimization (López de Prado, 2018, Ch. 12).
- **Step size = 21 days (~1 month):** Provides granular fold coverage without excessive overlap. With `step = 21` and `test = 63`, consecutive test windows overlap by ~67%, which is a good balance between fold count and independence.
- **Lookback period:** Determines how far back to look for data. Short-horizon signals need less history; long-horizon signals need more for meaningful multi-year evaluation.

### Approximate fold counts

Given sufficient data:
- **Short:** ~60 folds over 5 years (1260 bars / 21 step ≈ 60)
- **Medium:** ~110 folds over 10 years (2520 bars / 21 step ≈ 120, minus train warmup)
- **Long:** ~180 folds over 20 years (5040 bars / 21 step ≈ 240, minus train warmup)

More folds = more OOS samples = more reliable robustness estimates. This is a strength of the walk-forward approach.

---

## Date Resolution

Location: `core/quant_core/wfo/date_resolution.py`

Before folds can be built, the raw user dates must be resolved to actual trading dates in the data.

### `resolve_wfo_start_end_dates()`

**Inputs:**
- `bars_df`: DataFrame with sorted, monotonic DatetimeIndex
- `horizon`: "short" | "medium" | "long"
- Optional user-provided `start_date`, `end_date`
- `end_date_policy`: "latest" (use last available bar) or "fixed" (require exact date)

**Logic:**

1. **End date:** If no `end_date` provided and policy="latest", use `bars_df.index[-1]`. If provided, snap to the previous available trading day using binary search.

2. **Start date:** If no `start_date` provided, compute lookback:
   - Short: `end - 5 × 252 bars`
   - Medium: `end - 10 × 252 bars`
   - Long: `end - 20 × 252 bars`
   - Clamp to `bars_df.index[0]` if lookback exceeds available history

3. **Validation:** Ensure `resolved_start < resolved_end`. Record alignment notes for debugging.

**Output:**
```python
{
    "resolved_start_date": date,
    "resolved_end_date": date,
    "warnings": list[str],
    "alignment_notes": {
        "start_aligned": bool, "start_alignment": "next" | "none",
        "end_aligned": bool, "end_alignment": "prev" | "none",
    }
}
```

---

## Per-Fold Evaluation Flow

Location: `core/quant_core/pipeline.py`, `_eval_fold()` (lines ~1482–1605)

For each fold in the WFO sequence:

### Phase 1: Train (In-Sample Optimization)

```
Input: market data restricted to [train_start, train_end]
Process: run_optimization() — search parameter space
Output: top-K ranked candidates (by PnL or CAGR)
```

The optimization engine (see [06-optimization-engine.md](./06-optimization-engine.md)) searches the parameter space on the training window only. It returns a ranked list of trial results.

### Phase 2: Test (Out-of-Sample Evaluation)

```
Input: market data restricted to [test_start, test_end]
Process: For each top-K candidate from Phase 1:
         - Apply winning parameters to a BacktestEngine spec
         - Run BacktestEngine.run(fast_mode=True) on the test window
Output: OOS metrics per candidate: pnl, cagr, sharpe, max_drawdown, win_pct, n_fills
```

**Key invariant:** The test-phase backtest uses parameters found during training but evaluates them on data the optimizer never saw. This is the fundamental OOS guarantee.

### Phase 3: Record

Each fold produces rows with:
```python
{
    "fold_index": fold_idx * 1000 + trial_rank,
    "train_start": str,
    "train_end": str,
    "test_start": str,
    "test_end": str,
    "stat.pnl": float,
    "stat.cagr": float,
    "stat.sharpe": float,
    "stat.max_drawdown": float,
    "stat.win_pct": float,
    "is_holdout": False,
}
```

---

## Cross-Fold Aggregation

After all folds are evaluated, candidates are aggregated across folds:

### Grouping

```
Group by: (strategy_kind, trial_id, parameter_set)
```

Each unique parameter combination may appear as a top-K candidate in multiple folds. The aggregation collects all OOS metrics for that parameter set across all folds where it was selected.

### Statistics

For each parameter group:
- `mean_oos_sharpe` — average Sharpe ratio across test windows
- `median_oos_sharpe` — median (robust to outlier folds)
- `std_oos_sharpe` — standard deviation (measures stability)
- `fraction_positive_folds` — fraction of folds with positive OOS PnL
- `mean_oos_max_drawdown` — average worst drawdown across test windows

### Selection criterion

```python
best_params = argmax(mean_oos_metric)  # where metric = objective (default: mean OOS PnL)
```

The winner is the parameter set with the best *average* OOS performance — not the best single fold. This is critical: a parameter set that wins one fold spectacularly but loses in all others is rejected in favor of one that performs consistently.

---

## Multi-Horizon WFO

When `walk_forward.multi_horizon = true`, the system runs independent WFO pipelines for each horizon in `walk_forward.horizons` (e.g., ["short", "medium", "long"]).

Each horizon produces:
- Its own set of folds (different window sizes)
- Its own candidate ranking
- Its own OOS aggregation

Results are combined into a `simple_wfo_multi_horizon` artifact, allowing the user to see which signal parameters work at which investment horizon.

---

## Data Persistence

### Database tables

| Table | Content |
|-------|---------|
| `run_fold` | Per-fold, per-trial detailed results (fold_index, dates, all metrics, parameters) |
| `run_wfo_period` | Per-fold winner summary (fold_no, horizon, dates, OOS metrics) |

### S3 artifacts

| Key | Content |
|-----|---------|
| `runs/{run_id}/wfo/{symbol}/{horizon}/folds.json` | Complete fold-by-fold results |
| `runs/{run_id}/wfo/{symbol}/{horizon}/summary.json` | Aggregated OOS summary statistics |

---

## Overfitting Control Mechanisms

WFO is the primary overfitting control, but it works in concert with several other mechanisms:

### 1. Multiple OOS windows (statistical)
The central limit theorem applies: the mean OOS metric across K folds converges to the true expected performance as K grows. With 60+ folds (short horizon), the estimate is reasonably precise.

### 2. Parameter deduplication (computational)
The `eval_cache` in the optimization engine prevents re-evaluating identical parameter sets, but more importantly, it prevents the same parameter set from accumulating multiple "votes" in the aggregation.

### 3. Warmup padding (data integrity)
Indicators are warmed up on data *before* the evaluation window, ensuring no NaN-contaminated signals leak into the OOS metrics.

### 4. Minimum window requirements
A parameter set must appear in enough folds to be statistically meaningful. Candidates appearing in only 1–2 folds are not reliable.

### 5. The deflated Sharpe ratio (planned)
Bailey & López de Prado (2014) showed that the expected maximum Sharpe ratio under the null (no skill) depends on the number of trials, the variance of Sharpe estimates, and the skewness/kurtosis of returns. The deflated Sharpe ratio adjusts for these factors. The architecture supports adding this as a post-aggregation filter.

---

## Limitations and Honest Caveats

1. **Overlapping test windows:** With `step < test_window`, consecutive OOS windows share bars. This reduces the effective number of independent samples. A correction factor could be applied (Newey-West HAC standard errors), but is not currently implemented.

2. **No formal multiple testing correction:** The WFO selects the best candidate across the grid without applying White's Reality Check or Hansen's SPA test. The `methodology_status` field honestly reports this as "robust_oos_ensemble", not as a formally controlled experiment.

3. **Non-stationarity:** Market regimes change. A signal that worked in 2015–2022 folds may not work in 2023–2024. WFO detects this (via declining OOS metrics in later folds), but does not automatically adapt.

4. **Survivorship bias in data:** WFO validates signal robustness, but cannot correct for survivorship bias in the underlying stock universe. If the data only contains stocks that survived to the present, even honest OOS metrics may be upward-biased.

---

## References

- Bailey, D.H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality." *Journal of Portfolio Management*, 40(5), 94–107.
- Harvey, C.R. & Liu, Y. (2015). "Backtesting." *Journal of Portfolio Management*, 42(1), 13–28.
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapter 12: "Backtests on Synthetic Data."
- White, H. (2000). "A Reality Check for Data Snooping." *Econometrica*, 68(5), 1097–1126.
- Hansen, P.R. (2005). "A Test for Superior Predictive Ability." *Journal of Business & Economic Statistics*, 23(4), 365–380.
- Hansen, P.R., Lunde, A., Nason, J.M. (2011). "The Model Confidence Set." *Econometrica*, 79(2), 453–497.
- Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies*. Wiley. — The original walk-forward analysis reference.
