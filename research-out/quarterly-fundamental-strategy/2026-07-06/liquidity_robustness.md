# Liquidity Robustness (Phase 12)

One predeclared rule, not optimized: exclude the bottom liquidity quintile by `adv20` (20-day average dollar volume, already computed in the existing characteristic-study panel), computed as a per-date cross-sectional quintile rank so it adapts to each month's universe rather than a fixed absolute threshold.

| Universe | N periods | Avg holdings | Sharpe | Cumulative return |
|---|---|---|---|---|
| Full trusted universe (baseline) | 51 | 16.8 | 1.62 | +220% |
| **Excluding bottom ADV quintile** | 51 | 16.2 | **1.54** | **+180%** |

The liquidity-filtered result is only modestly weaker (Sharpe 1.54 vs 1.62, cumulative +180% vs +220%), and average holdings barely change (16.2 vs 16.8) — the top-tercile B/M selection was not primarily relying on the least-liquid names in the universe. This is a reassuring, not alarming, robustness result — the prior session's flag that liquidity had not been tested is now addressed, and the result survives.
