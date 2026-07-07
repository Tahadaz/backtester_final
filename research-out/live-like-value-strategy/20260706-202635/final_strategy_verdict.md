# Final Strategy Verdict

## 1. Is the new backtest genuinely live-like?

Yes for the core mechanic: genuine sequential monthly realized returns from real end-of-month prices, real turnover, real costs. Not yet fully live-like on execution-lag modeling (close-to-close convention used, no explicit next-open/next-close lag applied) and price-basis verification (raw vs. adjusted vs. total-return not re-audited this session).

## 2. Are monthly returns real sequential realized returns?

Yes — proven by the synthetic test (`test_engine_does_not_reproduce_overlapping_forward_return_compounding_error`): a stock returning +5%/month realizes ~5%/month in the engine once ramped, not the ~34%/month a naive overlapping-forward-return compounding error would produce.

## 3. Is overlapping-vintage accounting correct?

Yes — capital weights sum to 1/6 per active vintage, vintages expire after exactly 6 months (tested), warm-up ramps correctly from 0 to 6 active vintages, turnover reflects entry/exit correctly (all covered by passing tests).

## 4. Is the trusted universe explicit and reproducible?

Yes, and documented with one important honest correction discovered mid-analysis: the *effective* trusted universe (enough eligible names to clear the 9-name minimum) doesn't exist before 2022, four-to-five years later than the full panel's nominal 2017 start. This is now explicit in `trusted_universe.md`, not buried.

## 5. How many stocks are typically eligible?

16.8 average holdings for S1 (B/M), 18.1 for S2 (CF/P), over their respective invested windows (min 3, max 27).

## 6. Does B/M produce positive net long-only performance?

Yes — Sharpe 1.62 (95% bootstrap CI [0.78, 2.53]) over 51 invested months, 2022-03 to 2026-05, beating MASI's own Sharpe (1.39) over the overlapping window.

## 7. Does CF/P produce positive net long-only performance?

Yes — Sharpe 1.99 (CI [1.13, 3.01]) over 42 months, the strongest raw/CAGR of the four architectures.

## 8. Does the equal-rank composite help?

Not clearly — S3's Sharpe (1.83) sits between S1 and S2, with the shortest sample (38 months) and no evidence it improves on simply holding S2 alone.

## 9. Do separate sleeves help?

Yes, modestly — S4's Sharpe (2.13) is the highest of the four and its beta (1.02) is the closest to neutral, consistent with a genuine diversification benefit from combining two only-moderately-correlated signals.

## 10. Which result survives costs?

All four — costs (33bps, applied to real turnover of 3.5-5.9%/month) are small relative to the gross returns; net Sharpe is close to gross in every case.

## 11. Which result survives liquidity filters?

**Not tested this session** — no ADV-based liquidity filter was applied (see `trusted_universe.md`). This is an open question, not a confirmed pass.

## 12. Which result survives contributor analysis?

**Partially fails on close inspection.** S1's top 3 names (ADH, ADI, JET — real estate/construction) account for ~36% of total exposure and were in the top tercile 94-100% of the time. This is a material concentration risk, not tested for S2/S3/S4. The result should not be read as "B/M works broadly across the Moroccan market" — closer to "B/M has, over this period, persistently selected a cluster of real-estate/construction names that performed well."

## 13. Which result survives subperiod checks?

All three (S1/S2/S3) show the same-direction, still-strongly-positive performance in both halves of their invested windows — no collapse, no sign flip. Each half is short (~19-26 months) so this is reassuring but not decisive.

## 14. Does any strategy beat MASI on a defensible basis?

Yes, on a price-only MASI comparison (all four strategies' Sharpe and information ratios exceed MASI's own Sharpe over the same window) — but this comparison is **generous to the strategies** since MASI is not confirmed to be a total-return series (see `benchmark_audit.md`); a true MASI total-return benchmark would be a harder hurdle not tested here.

## 15. Is any Sharpe statistically meaningful?

The bootstrap 95% CIs for all three primary strategies exclude zero, but the bootstrap does not correct for the vintage engine's inherent month-to-month serial correlation (5/6 vintage overlap) — a moving-block bootstrap would likely widen these intervals meaningfully. Effective independent N is closer to 6-9 per strategy than the nominal 38-51 months. **Meaningful but not proven robust** is the honest read.

## 16. What is the strongest honest claim?

"Repaired, PIT-safe B/M and CF/P signals, implemented as a genuine long-only, cost-adjusted, six-vintage monthly-rebalanced strategy, produced a positive and bootstrap-significant Sharpe ratio (1.6-2.1) over the ~3.5-4 year period in which the trusted Moroccan equity universe actually had sufficient fundamental coverage (2022-2026) — but this result is concentrated in a small cluster of real-estate/construction names, has not been tested against a liquidity filter or a true total-return benchmark, and rests on an effective independent sample of roughly 6-9 non-overlapping periods."

## 17. What claims remain forbidden?

- "Sharpe 1.6-2.1 over a long, market-cycle-spanning backtest" — the real invested sample is 3.5-4 years, one broad regime.
- "A diversified value premium" — a material share of the return is a persistent bet on 2-3 real-estate/construction names.
- "Beats MASI total return" — only a price-index comparison was made.
- "Statistically robust" without qualification — the bootstrap CI does not account for vintage-induced serial correlation.
- Any claim reusing `methodology_bakeoff.py::portfolio_table`'s Sharpe/drawdown numbers as strategy performance (that machinery remains predictive-diagnostic-only, now explicitly marked in code).

## 18. Which architecture should the app expose?

**S1 (B/M alone)**, provisionally, given it is the simplest to explain, has the lowest turnover, the most stable subperiod behavior, and avoids CF/P's additional unresolved field-mapping uncertainty (net_income/CFO alias ambiguity flagged in the prior session). This is a recommendation for exposure as a *research/paper-trading* signal, not a live-capital allocation.

## 19. Which architecture should be paper-traded first?

**S1 (B/M)**, for the same reasons — and because it's the easiest to monitor and unwind if the real-estate concentration thesis breaks down.

## 20. What exact next experiment should follow?

In priority order: (1) leave-one-stock-out on S1 removing ADH/ADI/JET to quantify how much Sharpe survives without the real-estate cluster; (2) a liquidity (ADV) filter applied to the trusted universe and rerun; (3) a moving-block bootstrap (block ≥ 6 months) replacing the current i.i.d. bootstrap; (4) sourcing a genuine MASI total-return series; (5) extending the same attribution done for S1 to S2/S3/S4.

## Production classification

**B. RESEARCH STRATEGY — PROMISING**

Not (A) READY FOR PAPER TRADING: the concentration finding (Phase 13) and untested liquidity filter are real, unresolved gaps that should be closed before even paper capital is committed; the statistical inference likely overstates confidence (i.i.d. bootstrap on serially-correlated vintage returns). Not (C) or (D): the engine is genuinely valid, the signals are real (repaired, canonical, bootstrap-significant), and the result is not a null finding — there is real, positive, cost-adjusted, subperiod-persistent evidence. This sits squarely as promising research evidence that needs the five follow-up experiments above before a stronger claim is defensible.
