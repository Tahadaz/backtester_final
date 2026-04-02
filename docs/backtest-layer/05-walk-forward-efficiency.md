# 05 — Walk-Forward Efficiency

**Reference**: Pardo (2008) Ch.11

---

## Purpose

Walk-Forward Efficiency (WFE) is the central metric that determines whether a strategy's optimization process is sound. It answers a specific question: **does the performance observed in-sample reliably transfer to out-of-sample data?**

A strategy with high IS returns but low OOS returns is overfitted. A strategy where OOS returns are a substantial fraction of IS returns has a robust optimization process. WFE quantifies this.

---

## WFE Formula

```
WFE = annualized_OOS_return / annualized_IS_return
```

Where:
- `annualized_OOS_return` = annualized return of the concatenated OOS windows
- `annualized_IS_return` = annualized return of the IS optimizations (using winner parameters)

### Computation

```python
def compute_wfe(windows: list[WalkForwardWindow]) -> float:
    """
    Compute Walk-Forward Efficiency across all windows.

    Returns:
        WFE as a ratio (e.g., 0.65 = 65%)
    """
    # Concatenate all IS returns (using each window's winner)
    is_total_return = 1.0
    is_total_bars = 0
    for w in windows:
        is_total_return *= (1 + w.is_winner_return)
        is_total_bars += w.is_bars

    # Concatenate all OOS returns
    oos_total_return = 1.0
    oos_total_bars = 0
    for w in windows:
        oos_total_return *= (1 + w.oos_return)
        oos_total_bars += w.oos_bars

    # Annualize
    is_annualized = (is_total_return) ** (252 / is_total_bars) - 1
    oos_annualized = (oos_total_return) ** (252 / oos_total_bars) - 1

    if is_annualized <= 0:
        return 0.0  # IS optimization failed entirely

    wfe = oos_annualized / is_annualized
    return wfe
```

---

## Acceptance Threshold: WFE >= 50%

**Pardo Ch.11:** WFE >= 50% indicates a robust optimization process.

| WFE Range | Interpretation | Action |
|-----------|---------------|--------|
| >= 80% | Excellent transfer | Accept — optimization is highly robust |
| 50% - 80% | Good transfer | Accept — optimization transfers reliably |
| 30% - 50% | Marginal transfer | Reject — optimization may not be reliable |
| < 30% | Poor transfer | Reject — strategy is likely overfitted |
| <= 0% | No transfer | Reject — OOS performance is negative |

**Why 50%?** If the OOS annualized return is less than half the IS annualized return, the gap between optimization and reality is too large. The IS optimization is finding patterns that don't persist — the definition of overfitting.

---

## Configuration Selection

Multiple (IS, OOS) window size configurations are tested. Each produces its own WFE:

```python
configs = enumerate_feasible_configs(data_length, max_lookback)

for config in configs:
    config.wfe = run_wfa_and_compute_wfe(config)

# Select best viable configuration
viable = [c for c in configs if c.wfe >= 0.50]

if len(viable) == 0:
    result = NotViable(diagnostics={
        'best_wfe': max(c.wfe for c in configs),
        'all_configs': configs,
        'recommendation': "Strategy optimization does not transfer to OOS. "
                          "Consider simpler parameters or different indicator."
    })
else:
    winner = max(viable, key=lambda c: c.wfe)
```

**Why test multiple configurations?** The IS/OOS window size affects WFE. A too-short IS window may not capture enough data for reliable optimization. A too-long IS window may include stale data. Testing multiple configurations finds the sweet spot.

---

## Additional Robustness Checks

WFE alone is necessary but not sufficient. Two additional checks:

### Check 1: Majority of OOS Windows Profitable

```python
n_profitable = sum(1 for w in winner.windows if w.oos_profitable)
n_total = len(winner.windows)
robustness_ratio = n_profitable / n_total
```

**Threshold:** robustness_ratio >= 0.50 (majority profitable).

Pardo Ch.11 p.289 example: RSI Counter-Trend had 19/30 = 63% profitable OOS windows — considered acceptable. A strategy where 80% of OOS windows are profitable with WFE = 55% is more trustworthy than one where 51% are profitable with WFE = 75%.

### Check 2: No Single Window Dominance

```python
max_single_window_contribution = max(
    abs(w.oos_return) for w in winner.windows
) / sum(abs(w.oos_return) for w in winner.windows)

if max_single_window_contribution > 0.50:
    flag_warning("single_window_dominance",
                 f"One window contributes {max_single_window_contribution:.0%} of total OOS return")
```

If one OOS window contributes more than half of the total OOS return, the WFE may be driven by a single lucky window rather than consistent performance. This is a warning, not a rejection.

---

## When No Configuration Achieves WFE >= 50%

The strategy is flagged as **"not viable"** with diagnostic data:

```
Strategy Result: NOT VIABLE

Best configuration:
  IS = 2520 bars, OOS = 756 bars, n_walk_forwards = 8
  WFE = 34% (threshold: 50%)
  Profitable OOS windows: 5/8 (62%)

Diagnostics:
  - IS annualized return: 18.3%
  - OOS annualized return: 6.2%
  - Gap: IS optimization finds patterns that don't persist
  - Suggestion: Simplify parameter space (fewer WFO-flagged parameters)
```

The system does not silently accept a marginal strategy. The user sees exactly why the strategy failed and receives actionable suggestions.

---

## How WFO Chooses Between Indicator Types (Full-WFO Mode)

When the strategy is configured in Full-WFO mode (WFO chooses the best indicator type per family), each candidate indicator type gets its own complete WFO analysis:

```
Family: Tendance
  - SMA: WFO analysis -> WFE = 62%
  - EMA: WFO analysis -> WFE = 55%    (future indicator type)
  - DEMA: WFO analysis -> WFE = 48%   (future indicator type)

Winner: SMA (WFE = 62%, above 50% threshold)
```

**Selection rule:** The indicator type with the highest WFE wins, provided it passes the 50% threshold. If no indicator type in a family achieves WFE >= 50%, the family is excluded from the strategy.

This is a clean extension of the per-type WFO: instead of running WFO once (for a user-specified type), run it N times (once per candidate type) and select the best.

---

## The Final Parameter Set

The winning parameter set is extracted from the **last IS window** of the winning configuration:

```python
winning_config = max(viable_configs, key=lambda c: c.wfe)
last_is_window = winning_config.windows[-1]
final_params = last_is_window.is_winner_params
```

**Why the last IS window?** It is the most recently calibrated parameter set, reflecting the current market regime. Earlier IS windows may have captured parameter values appropriate for past regimes that no longer apply.

This is the parameter set used for:
- Statistical validation via Monte Carlo + DSR (doc 08)
- The test period validation (doc 09)
- Live trading (if the strategy is deployed)
- Display on the results page as "WFO-optimized parameters"

---

## What Comes After WFE

WFE validates the optimization *process*. Two additional metrics (doc 08) validate the *results*:

1. **Monte Carlo Permutation Test** — Is the OOS performance statistically distinguishable from random? (p < 0.05 required)
2. **Deflated Sharpe Ratio** — Is the OOS Sharpe significant after correcting for N parameter combinations tested? (p < 0.05 required)

A strategy must pass all three — WFE, Monte Carlo, DSR — to be considered statistically validated. Each catches a different failure mode.
