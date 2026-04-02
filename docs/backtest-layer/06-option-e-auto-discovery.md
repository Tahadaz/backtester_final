# 06 — Option E: Auto-Discovery of Entry/Exit Structure

**References**: Pardo (2008) Ch.9 p.239 (PROM), Ch.10 p.249 (parameter count), Ch.10 p.252 (step sizing)

---

## Purpose

Options A through D on the strategy page allow users to define the **number** of entry/exit levels manually, while WFO optimizes the **values** (thresholds, exposures). Option E goes further: WFO also discovers the optimal **number** of levels.

This is the most powerful configuration option — and the most computationally expensive. It requires joint optimization of indicator parameters, threshold values, exposure values, and level count within a single WFO framework.

---

## How Option E Works

When Option E is selected for entries (or exits), WFO searches over the number of levels as an additional parameter dimension:

```
For level_count in [2, 3, 4]:
    Generate all combinations of:
        - level_count threshold values (from scan ranges)
        - level_count exposure values (from scan ranges)
        - indicator parameters (from horizon ranges)

    For each combination:
        Simulate strategy on IS window
        Compute PROM

    Apply neighbor-averaging to all PROMs
    Best PROM for this level_count = max(smoothed_PROMs)

Overall best = max across all level_counts
Winner determines BOTH the count AND the values
```

### PROM as Natural Level-Count Regulator

PROM's square-root penalty naturally limits the number of levels. More levels means:

1. **Fewer trades per level** — each level triggers only on a subset of opportunities
2. **Bigger sqrt penalty** — with fewer trades, `sqrt(#WT) / #WT` is a larger fraction

**Example:**

```
2-level strategy: 40 trades total
  Level 1: 25 trades (15 wins, 10 losses)
  Level 2: 15 trades (9 wins, 6 losses)
  sqrt penalty on wins: sqrt(15)/15 = 26%, sqrt(9)/9 = 33%

4-level strategy: 40 trades total
  Level 1: 15 trades (9 wins, 6 losses)
  Level 2: 10 trades (6 wins, 4 losses)
  Level 3: 8 trades (5 wins, 3 losses)
  Level 4: 7 trades (4 wins, 3 losses)
  sqrt penalty on wins: sqrt(9)/9 = 33%, sqrt(6)/6 = 41%, sqrt(5)/5 = 45%, sqrt(4)/4 = 50%
```

The 4-level strategy must produce substantially better raw performance to overcome the heavier PROM penalty. This prevents the optimizer from discovering spuriously complex structures.

---

## Joint Optimization Requirement

Option E is **only available when rule parameters are also WFO-optimized** (i.e., indicator parameters are in Semi-WFO or Full-WFO mode). The reason is mathematical: if indicator parameters are fixed manually while WFO searches over level count and thresholds, the optimization surface is incomplete. The indicator parameter might be suboptimal for the discovered level structure.

Joint optimization ensures that the indicator parameters, thresholds, exposures, and level count are all optimized together in a consistent framework.

```
Option E requires:
  - Indicator parameters: WFO-optimized (Semi-WFO or Full-WFO)
  - Entry/exit thresholds: WFO-optimized (by definition, Option E)
  - Entry/exit exposures: WFO-optimized (by definition, Option E)
  - Level count: WFO-searched (2, 3, or 4)
```

---

## Option E for Entries

```
Entry level structure discovered by WFO:

Example result (trend-following SMA strategy):
  Level 1: trend_score > 25, exposure = 30%    (initial position)
  Level 2: trend_score > 50, exposure = 50%    (add on confirmation)
  Level 3: trend_score > 80, exposure = 80%    (full position on strong trend)

WFO determined:
  - 3 levels (not 2, not 4) — best PROM
  - Threshold values: 25, 50, 80
  - Exposure values: 30%, 50%, 80%
```

### Search Space for Entries

```
For each level_count in [2, 3, 4]:
    threshold_combos = ordered_combinations(threshold_range, level_count)
    exposure_combos = ordered_combinations(exposure_range, level_count)
    indicator_combos = product(indicator_param_ranges)

    total_combos = len(threshold_combos) * len(exposure_combos) * len(indicator_combos)
```

**Ordering constraint:** thresholds must be strictly increasing (threshold_1 < threshold_2 < threshold_3). Exposures must be non-decreasing (exposure_1 <= exposure_2 <= exposure_3). This reduces the combinatorial explosion and enforces a sensible ladder structure.

---

## Option E for Exits

Same structure as entries, but with decreasing exposure:

```
Exit level structure discovered by WFO:

Example result (trend-following SMA strategy):
  Level 1: trend_score < 20, reduce to exposure = 60%   (partial exit)
  Level 2: trend_score < -10, reduce to exposure = 30%   (major reduction)
  Level 3: trend_score < -40, reduce to exposure = 0%    (full exit)
```

**Ordering constraint:** exit thresholds must be strictly decreasing. Exposures must be non-increasing.

---

## Total Parameter Count Warning

Option E with multiple families can produce very large parameter spaces:

```
Example: Trend-following strategy with Option E on entries and exits

Indicator parameters:
  SMA period:                    1 parameter
  MACD (fast, slow, signal):     3 parameters
  RSI (period):                  1 parameter
  OBV (ema_period):              1 parameter
                                 --------
                                 6 indicator params

Entry Option E (3 levels):
  3 thresholds + 3 exposures:    6 parameters

Exit Option E (3 levels):
  3 thresholds + 3 exposures:    6 parameters

Risk (WFO-optimized):
  Stop loss + take profit:       2 parameters
                                 --------
Total:                           20 parameters
```

### Pardo's Warning (Ch.10 p.249)

> *"It is always best to have the smallest number of optimizable parameters possible."*

Each additional parameter:
1. Multiplicatively increases the search space
2. Requires more IS data for statistical validity (DF constraint)
3. Increases the risk of overfitting through combinatorial complexity

### Hard Limits for Moroccan Stocks

With approximately 10-15 years of daily data for most Moroccan stocks:

| Total WFO parameters | Assessment | Action |
|----------------------|------------|--------|
| <= 8 | Good | Proceed |
| 9-12 | Acceptable | Warn on review section |
| 13-15 | Marginal | Strong warning + require longer IS windows |
| > 15 | Excessive | Block or require explicit user override |

The **review section on the strategy page** computes and displays the total WFO parameter count. It warns when the count approaches the data-feasibility boundary and explains the tradeoff.

---

## Guidance for Users

| Scenario | Recommended approach |
|----------|---------------------|
| First attempt with a new strategy | Start with Option A or B (manual rules, WFO sizing only) |
| Exploring threshold sensitivity | Option C or D (WFO thresholds, manual or Kelly sizing) |
| Maximum automation with sufficient data | Option E (full auto-discovery) |
| Limited data (< 8 years) | Avoid Option E; use Option C or D with 2-3 levels |
| Many indicator families selected | Use fewer levels or fewer families to stay under parameter limit |

The platform does not restrict the user from making suboptimal choices, but the review section provides clear feedback on parameter count and data requirements.
