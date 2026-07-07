# Dependence-Aware Uncertainty (Phase 10)

The prior session's i.i.d. bootstrap on S1's monthly returns was flagged as likely understating uncertainty, since six overlapping monthly vintages induce serial correlation (consecutive months share 5 of 6 active vintages). This session replaces it with a **moving-block bootstrap**, block length 6 (matching the vintage life, a defensible, non-searched choice), 2,000 resamples.

| Method | Sharpe 95% CI | Mean monthly return 95% CI |
|---|---|---|
| i.i.d. bootstrap (prior session) | [0.78, 2.53] | [1.03%, 3.84%] |
| **Moving-block bootstrap (block=6, this session)** | **[0.65, 3.09]** | [0.92%, 4.51%] |

The moving-block interval is meaningfully wider, as expected — but **the lower bound (0.65) remains positive**, so the result is still bootstrap-significant under the more conservative, dependence-aware test, just with less precision than the prior i.i.d. estimate implied. Point Sharpe estimate: 1.62 (unchanged — the bootstrap only affects the confidence interval, not the point estimate).

Quarterly fixed-stride's shorter sample (17 periods) was not separately bootstrapped — 17 observations is too few for a moving-block bootstrap with block length 6 to produce a meaningful interval (fewer than 3 independent blocks).

Predictive-layer HAC/non-overlapping inference (`downstream_research_impact.md`, prior session) is retained separately and not merged with this strategy-level uncertainty, per the standing instruction.
