# Statistical Uncertainty (Phase 12)

2,000-resample bootstrap (with replacement) on each strategy's invested-period monthly net-return series.

| Strategy | N months | Mean monthly return 95% CI | Sharpe 95% CI | Point Sharpe |
|---|---|---|---|---|
| S1 B/M | 51 | [1.03%, 3.84%] | [0.78, 2.53] | 1.62 |
| S2 CF/P | 42 | [1.83%, 5.42%] | [1.13, 3.01] | 1.99 |
| S3 Composite | 38 | [1.38%, 4.81%] | [1.02, 2.77] | 1.83 |

**All three strategies' 95% Sharpe confidence intervals exclude zero** — the positive result is not simply noise around zero at this sample size, per the bootstrap. However, the confidence intervals are wide (e.g., S1's Sharpe could plausibly be anywhere from 0.78 to 2.53) — this reflects genuine short-sample uncertainty, not false precision.

## What this does not include

- **Non-overlapping-period inference and HAC-style correction**: not applied here — the vintage engine's monthly returns are themselves overlapping in the sense that consecutive months share 5 of 6 active vintages, so consecutive realized returns are serially correlated by construction. A simple i.i.d. bootstrap (used above) does not correct for this and likely **understates** the true uncertainty. A moving-block bootstrap (blocks ≥ 6 months, respecting the vintage structure) would be the correct approach and was not implemented this session — flagged as the most important statistical follow-up (see `final_strategy_verdict.md` item 20).
- **Effective independent N**: not separately estimated. Given the 6-month vintage overlap, the effective independent sample is likely closer to N/6 ≈ 6-9 independent observations for each strategy — far too small to support a strong claim on its own, and this caveat should be read alongside the point Sharpe estimates above.
- This section is intentionally kept separate from the predictive-research IC/HAC inference reported in the prior data-quality-repair session (`downstream_research_impact.md`) — they are different objects (cross-sectional predictive IC vs. sequential portfolio realized return) and must not be merged or conflated, per the brief's explicit instruction.
