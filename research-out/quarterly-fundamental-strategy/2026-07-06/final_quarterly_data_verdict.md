# Final Quarterly Data Verdict

## 1. Are the quarterly data truly quarterly, or mostly cumulative/interim?

Mixed, but resolved: Revenue, NetIncome, EBITDA (where present) are genuine **standalone quarters**, confirmed by summing Q1-Q4 against independently-ingested FY figures (ratio ≈1.000). Book equity is a balance-sheet snapshot, not subject to cumulative/standalone ambiguity at all. Operating_Cash_Flow has essentially no quarterly-granularity data at all — it's predominantly semiannual.

## 2. Which fields are standalone?

Revenue, NetIncome, EBITDA (flow items, confirmed via the sum-to-FY check); Capitaux_propres/Total_Equity/Shares_Outstanding (balance-sheet snapshots, standalone by construction).

## 3. Which are YTD cumulative?

None found to be genuinely cumulative-YTD among the fields checked — this specific bug class (the brief's central concern) was **not found** in this dataset for Revenue/NetIncome/EBITDA. The pipeline's own `"StockAnalysis H2 derived from FY minus H1"` documents show an existing, already-correct standalone-reconstruction step for semiannual stockanalysis data.

## 4. Can standalone quarters be reconstructed safely?

Not needed for Revenue/NetIncome/EBITDA (already standalone) or book equity (snapshot). Not attempted for CFO since the underlying quarterly granularity doesn't exist to reconstruct from.

## 5. Can TTM CFO be constructed safely?

**No.** Zero symbol-years have complete standalone Q1-Q4 CFO. Not forced.

## 6. Does quarterly B/M improve on annual B/M?

**No, negligibly.** The current pipeline already blends quarterly/semiannual book-equity updates into the same resolver as annual data (confirmed for ATW). An annual-only ablation produces almost the same panel (377 vs 381 refresh events out of ~3,104 stock-months; only 5 of 71 symbols affected, by 1 event each).

## 7. Does TTM CF/P improve on annual CF/P?

Not tested — TTM is infeasible (item 5), and a coarser semiannual-annualized variant (QC2) was judged not worth the added accounting-semantics risk given CF/P is already benefiting from the same quarterly-blending mechanism as B/M.

## 8. How much monthly data are merely repeated stale fundamentals?

**87.7%** of monthly book-equity observations repeat the prior month's numerator; only 12.3% are genuinely new.

## 9. Does quarterly formation produce more honest independent decisions?

Not meaningfully more than monthly — since the underlying fundamental content is nearly identical either way (item 6/8), a quarterly formation schedule doesn't yield more genuine information events, just fewer, larger re-ranking steps on the same information.

## 10. Does quarterly strategy performance survive costs?

Yes — net Sharpe 1.21, net of the same 33bps cost assumption.

## 11. Does it beat the monthly six-vintage design?

**No.** Nearly identical cumulative return/CAGR (+217% vs +220%, 31.1% vs 31.5% CAGR) but materially worse Sharpe (1.21 vs 1.62) due to losing the vintage-smoothing diversification and higher realized volatility (25.5% vs 18.0%).

## 12. Which design has lower uncertainty?

The monthly six-vintage design — both its point Sharpe and its (now dependence-aware, moving-block) confidence interval [0.65, 3.09] sit above the quarterly design's point estimate of 1.21, and the quarterly design's shorter sample (17 periods) is too thin for a comparably rigorous interval.

## 13. Is B/M still concentrated in ADH/ADI/JET?

Yes, materially — removing them nearly halves cumulative return (220% → 99%).

## 14. Does the result survive removing the real-estate/construction cluster?

**Yes** — Sharpe 1.36, cumulative +84% even after removing ADH, ADI, JET, ARD, RDS entirely. Weaker, but not null.

## 15. Does it survive a fixed liquidity filter?

**Yes** — excluding the bottom ADV quintile: Sharpe 1.54, cumulative +180% (vs 1.62 / +220% baseline). Modest decline, not a collapse.

## 16. Is fundamental momentum feasible from the quarterly data?

Yes, for Revenue- and NetIncome-based deltas at quarterly frequency (~29 symbol-year coverage); CFO-based deltas only at semiannual frequency; margin/ROA/leverage deltas feasible in principle but inherit unresolved field-mapping ambiguities.

## 17. What exact design should be retained?

**The existing monthly six-vintage engine and the existing (already quarterly-blended) canonical B/M and CF/P definitions** — no changes to signal construction or rebalance cadence are justified by this audit.

## 18. What exact design should be abandoned?

The proposed **quarterly fixed-cadence rebalance** (R3 / Q-S1-S4 as a rebalance-frequency change) — it does not improve returns and meaningfully worsens risk-adjusted performance. Also abandoned (not pursued further): TTM CFO construction (infeasible) and a bespoke semiannual-annualized CF/P variant (not worth the accounting-semantics risk given minimal expected benefit).

## Production classification

**A. MONTHLY DESIGN RETAINED**

The quarterly/interim data genuinely exist and are broadly present across the universe, but (a) they are already substantially incorporated into the current monthly six-vintage design via the shared PIT resolver, (b) TTM CF/P construction is infeasible on data-coverage grounds, not a fixable bug, and (c) a direct, apples-to-apples strategy comparison shows quarterly-cadence rebalancing underperforms the existing monthly design on a risk-adjusted basis for no offsetting return benefit. This is a genuine, evidence-based negative result on the specific question asked ("would quarterly rebalancing help") — not a failure to try hard enough. The concentration and liquidity robustness checks (Phases 11-12, run against the *existing* monthly design during this task) both came back reassuring and are folded into the standing "B — RESEARCH STRATEGY, PROMISING" verdict from the prior session without requiring escalation or de-escalation of that classification.
