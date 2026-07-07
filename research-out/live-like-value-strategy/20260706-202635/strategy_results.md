# Strategy Results (Phase 11), Invested-Period-Only (honest sample)

All numbers are genuine realized monthly returns from the vintage engine, gross of nothing hidden, net of 33bps round-trip costs, computed only over each strategy's actually-invested window (see `trusted_universe.md` for why the full 111-month panel is not the right denominator).

| Strategy | Window | N months | Cumulative | CAGR | Ann. Vol | Sharpe | Max DD | Hit Rate | Beta vs MASI | IR |
|---|---|---|---|---|---|---|---|---|---|---|
| S1 B/M | 2022-03 → 2026-05 | 51 | +220% | 31.5% | 18.0% | **1.62** | -13.9% | 58.8% | 0.80 | 1.22 |
| S2 CF/P | 2022-12 → 2026-05 | 42 | +309% | 49.6% | 21.6% | **1.99** | -15.3% | 73.8% | 1.24 | 1.65 |
| S3 Composite | 2023-04 → 2026-05 | 38 | +191% | 40.2% | 19.6% | **1.83** | -11.5% | 73.7% | 1.15 | 1.44 |
| S4 Sleeves | 2022-12 → 2026-05 | 42 | +280% | 46.4% | 18.9% | **2.13** | -14.4% | 66.7% | 1.02 | 1.58 |
| MASI (benchmark, price-only) | 35 overlapping months | 35 | +63% | 18.2% | 12.6% | 1.39 | -14.4% | 57.1% | — | — |

**All four strategies show a positive net Sharpe over their invested windows, all comfortably above the MASI benchmark's own Sharpe (1.39) over the same overlapping period.** S4 (separate sleeves) has the highest Sharpe (2.13) and a beta near 1.0, making it the closest to a "clean" relative-return profile.

## What this does and does not prove

This is a genuine, honestly-computed, sequential realized-return result — not an artifact of compounding overlapping IC. It is **not** proof of a robust, long-run edge: the invested sample is 38-51 months (about 3-4 years), overlapping almost entirely with a single Moroccan equity market regime (post-COVID recovery into 2022-2026), and — critically — concentrated in a small number of persistently-held names (see `holdings_attribution.md`). Both caveats materially limit how much confidence this result deserves; see `statistical_uncertainty.md` and `subperiod_robustness.md`.
