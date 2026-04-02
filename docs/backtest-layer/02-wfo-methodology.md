# 02 — WFO Methodology

**This is the core document.** It describes the full Walk-Forward Analysis (WFA) pipeline as implemented on the backtest page, following Pardo (2008) methodology throughout.

---

## Overview

Walk-Forward Analysis is a rolling optimization-and-validation procedure. For each (stock, family, horizon) tuple:

1. Split available data into overlapping (IS, OOS) windows
2. In each IS window: optimize parameters using PROM, apply neighbor-averaging, check optimization profile, select winner
3. In each OOS window: test the IS winner on data it has never seen
4. Compute Walk-Forward Efficiency (WFE) across all windows
5. Accept or reject the strategy based on WFE and robustness checks

The pipeline does not pick a "good" parameter set from a single optimization. It tests whether the **process of optimization** reliably produces parameters that work on unseen data.

---

## Pipeline Per (Stock, Family, Horizon)

### Step 1 — Generate All Variants

Generate all parameter combinations within horizon-appropriate ranges.

**For indicator parameters:** ranges come from the horizon definition (see table below).

**For strategy parameters** (entry/exit thresholds, exposure levels, risk parameters): ranges come from the strategy page, where the user defined scan intervals and steps for each WFO-flagged parameter.

**Step sizing concern** (Pardo Ch.10 p.252):

> *"Excessively fine scanning of a parameter range can be a significant contributing factor to overfitting."*

Use proportional steps for large ranges. The goal is approximately **30-50 candidates per parameter dimension**:

| Range size | Recommended step | Candidates |
|-----------|-----------------|------------|
| 5-40 (35 values) | 1 | 36 |
| 20-100 (80 values) | 2 | 41 |
| 50-250 (200 values) | 5 | 41 |

This is a deliberate deviation from "test all step=1" for large ranges, following Pardo's own recommendation.

### Step 2 — Determine Feasible (IS, OOS) Configurations

A configuration is a specific choice of IS window size and OOS window size. Multiple configurations are tested; the best one (by WFE) is selected.

**Constraints:**

```
IS >= 10 x max_lookback          (DF > 90%, Pardo Ch.6 p.163)
OOS = IS x ratio                  ratio in [0.25, 0.35] (Pardo Ch.11 p.282)
step = OOS                        standard WFA (Pardo Ch.11)
n_walk_forwards = floor((T_available - IS) / OOS)
```

Where:
- `max_lookback` = longest indicator lookback among all WFO-flagged parameters (e.g., SMA period 250 for long horizon)
- `T_available` = total bars available from WFO start date to end of WFO period (excluding test period)
- `DF` = Degrees of Freedom = 1 - (parameters / data points). IS >= 10 x max_lookback ensures DF > 90%.

**Example** (SMA long horizon, 15 years of data):
```
max_lookback = 250 (longest SMA period in range)
IS >= 10 x 250 = 2500 bars (~10 years)
ratio = 0.30 -> OOS = 750 bars (~3 years)
T_available = 15 x 252 = 3780 bars
n_walk_forwards = floor((3780 - 2500) / 750) = floor(1.71) = 1

Only 1 walk-forward -- insufficient. Need more data or shorter IS.
Try ratio = 0.25 -> OOS = 625 -> n = floor((3780 - 2500) / 625) = 2

Still marginal. This is a real constraint for long-horizon strategies.
```

The system enumerates all feasible configurations and runs WFA on each.

### Step 3 — For Each Feasible Configuration: Rolling Walk-Forward

```
for config in feasible_configurations:
    windows = []

    for w in range(n_walk_forwards):
        is_start = w * OOS
        is_end   = is_start + IS
        oos_start = is_end
        oos_end   = oos_start + OOS

        # --- IS WINDOW ---
        is_data = data[is_start : is_end]

        # Run all parameter combinations on IS data
        for combo in all_variants:
            trades = simulate(is_data, combo)
            prom[combo] = compute_prom(trades, capital)

        # Apply neighbor-averaging (see doc 04)
        smoothed_prom = neighbor_average(prom)

        # Optimization profile check (see doc 04)
        profile = check_optimization_profile(prom)
        if not profile.passes:
            flag_window(w, profile.diagnostics)
            continue  # skip this window's winner

        # Select IS winner
        is_winner = argmax(smoothed_prom)

        # --- OOS WINDOW ---
        oos_data = data[oos_start : oos_end]
        oos_result = simulate(oos_data, is_winner)

        windows.append({
            'is_prom': prom[is_winner],
            'is_smoothed_prom': smoothed_prom[is_winner],
            'oos_return': oos_result.total_return,
            'oos_trades': oos_result.trades,
            'oos_profitable': oos_result.total_return > 0,
            'is_winner_params': is_winner,
            'profile': profile,
        })

    # Compute WFE for this configuration (see doc 05)
    wfe = compute_wfe(windows)
    config.wfe = wfe
    config.windows = windows
```

### Step 4 — Select Configuration with Best WFE

```
viable = [c for c in feasible_configurations if c.wfe >= 0.50]

if len(viable) == 0:
    return StrategyResult(viable=False, diagnostics=all_configs)

best = max(viable, key=lambda c: c.wfe)
```

**WFE >= 50%** is the acceptance threshold (Pardo Ch.11). Below this, the optimization process does not transfer to OOS reliably enough to justify trading.

### Step 5 — Robustness Check

```
n_profitable = sum(1 for w in best.windows if w['oos_profitable'])
n_total = len(best.windows)
robustness_ratio = n_profitable / n_total

# Pardo Ch.11 p.289: majority must be profitable
if robustness_ratio < 0.50:
    flag_robustness_warning(best, robustness_ratio)
```

Pardo's example (Ch.11 p.289): RSI Counter-Trend had 19/30 = 63% profitable OOS windows — considered acceptable.

### Step 6 — Extract Winner

The final parameter set is the **winner from the last IS window** of the winning configuration. This is the most recently calibrated parameter set, reflecting the current market regime.

```
final_params = best.windows[-1]['is_winner_params']
```

### Step 7 — Sizing from Concatenated OOS Trades

Concatenate all OOS trades from the winning configuration and compute Kelly sizing (see doc 07).

```
all_oos_trades = concat([w['oos_trades'] for w in best.windows])
win_rate, wl_ratio = compute_trade_stats(all_oos_trades)
kelly_fraction = win_rate - (1 - win_rate) / wl_ratio
```

---

## Parameter Ranges by Horizon

| Family | Short | Medium | Long |
|--------|-------|--------|------|
| **SMA** | period 5-40 | period 20-100 | period 50-250 |
| **RSI** | period 5-14, thresholds {30/70, 25/75, 20/80} | period 10-25 | period 14-40 |
| **MACD** | fast 5-12, slow 12-26, signal 5-9 | fast 8-18, slow 20-40, signal 7-12 | fast 12-26, slow 26-52, signal 9-18 |
| **OBV** | period 5-40 | period 20-100 | period 50-250 |

**Ranges derived from horizon meaning:**
- **Short** = weekly to monthly decisions (order flow, sentiment). Indicators need fast response: short lookback periods, tight thresholds.
- **Medium** = per trimester (quarterly earnings, sector rotation). Moderate lookback captures multi-week trends.
- **Long** = 6 months to 1+ year (macro cycles, geopolitics). Long lookback smooths noise, captures structural trends.

**RSI threshold sets:** For short horizon, RSI uses discrete threshold combinations {30/70, 25/75, 20/80} rather than continuous scanning. This reflects the natural semantic meaning of RSI levels (Wilder 1978).

---

## Number of Walk-Forwards

The number of walk-forward windows is **not fixed**. It depends on:
- Available data length
- IS window size (determined by max_lookback and DF constraint)
- OOS window size (determined by IS x ratio)

**Typical ranges by horizon:**

| Horizon | Data span | Typical n_walk_forwards |
|---------|-----------|------------------------|
| Short | Up to 5 years | 5-15 |
| Medium | Up to 10 years | 8-15 |
| Long | Up to 20 years | 8-20 |

Pardo recommends **10 or more** walk-forward windows when data allows. More windows provide greater statistical power for WFE estimation and robustness checks.

When fewer than 5 walk-forwards are feasible, the system warns that statistical power is limited but still runs the analysis.

---

## Full Pipeline Diagram

```
INPUT: Strategy definition (from strategy page) + WFO configuration (from backtest page)
  |
  v
[1] Generate variants within horizon ranges
  |
  v
[2] Enumerate feasible (IS, OOS) configurations
  |
  v
[3] For EACH configuration:
  |    |
  |    +---> Roll IS+OOS windows through data
  |    |       |
  |    |       +---> IS: all combos -> PROM -> neighbor-avg -> profile check -> winner
  |    |       |
  |    |       +---> OOS: test IS winner
  |    |
  |    +---> Compute WFE
  |
  v
[4] Select config with best WFE >= 50%
  |
  v
[5] Robustness: majority OOS windows profitable?
  |
  v
[6] Final params = last IS window's winner
  |
  v
[7] Kelly sizing from concatenated OOS trades
  |
  v
[8] Test period: run optimized strategy on remaining data
  |
  v
OUTPUT: Viable/not-viable verdict + WFO diagnostics + sizing + test period results
```
