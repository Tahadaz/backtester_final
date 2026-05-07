# 08 - Statistical Validation

> Status: `Implemented` in the clean-slice four-page WFO flow.

## Purpose

The four-page backtest now separates three questions:

1. `Does optimization transfer from IS to OOS?`
   This is handled by WFE and the walk-forward diagnostics.
2. `Is the selected Sharpe still credible after multiple testing?`
   This is handled by Deflated Sharpe Ratio on concatenated WFO OOS returns.
3. `How fragile is the final held-out OOS path to alternate plausible timelines?`
   This is handled by final-held-out-OOS Monte Carlo robustness.

## Current User-Facing Methodology

### 1. Deflated Sharpe Ratio

DSR is applied to concatenated WFO OOS returns from the winning configuration and uses the number of tested candidate tuples as the multiple-testing count.

Inputs:

- concatenated WFO OOS returns
- total candidate tuples evaluated
- risk-free rate, default `0`

Outputs:

- observed Sharpe
- benchmark Sharpe
- DSR statistic
- p-value
- skewness
- kurtosis
- number of OOS observations
- number of tested variants

### 2. Final Held-Out OOS Monte Carlo Robustness

The supported four-page Monte Carlo feature is **not** a trade-order permutation test anymore.

It now runs **after** the optimized strategy has completed its final held-out OOS test and applies a **circular block bootstrap** to daily held-out returns.

It is produced for:

- each stock held-out OOS path
- the portfolio-level held-out OOS path

Default settings:

- `n_paths = 1000`
- `block_length = min(20, max(5, round(sqrt(N))))`

Where `N` is the number of held-out daily return observations.

### Returned robustness outputs

- actual normalized equity curve
- sampled simulated curves
- percentile bands through time
- terminal return distribution summary
- max drawdown distribution summary
- realized path percentile rank

### Sample-size rules

- fewer than `30` held-out observations: Monte Carlo is skipped with a low-sample warning
- `30` to `125` observations: Monte Carlo runs, but the result carries a low-statistical-power warning

## Retired Interpretation

The older permutation-based Monte Carlo description is no longer the shipped four-page methodology. If permutation testing remains in helper code, it is an internal or legacy diagnostic, not the user-facing robustness layer for the clean-slice backtest.

## Validation Summary

A fully implemented four-page WFO result now reports:

- WFE
- robustness ratio
- single-window dominance
- DSR
- final held-out OOS test metrics
- final held-out OOS Monte Carlo robustness

These outputs are complementary:

- WFE checks optimization transfer
- DSR checks multiple-testing inflation
- final-OOS Monte Carlo checks path fragility on unseen data
