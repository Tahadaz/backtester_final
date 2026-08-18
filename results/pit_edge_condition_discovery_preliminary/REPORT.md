# MASI PIT Condition Discovery

- Status: **preliminary**
- Methodology: `pit-dashboard-opportunity-portfolio-edge-policy-v4`
- Candidate rows: 3992
- Decision dates: 50
- Symbols: 45
- Universe: data-backed Moroccan equities tagged `market_region=masi`; exact historical index membership is unavailable.
- Objective: positive net return after costs and positive same-window MASI alpha.

## Horizon results

| Horizon | Status | OOS trades | Net return (95% CI) | MASI alpha (95% CI) | Final rules |
|---|---:|---:|---:|---:|---|
| weekly | preliminary | 190 | -0.004114223413775226 [-0.008625030114230447, 0.0009213414696237312] | -0.004589538902230117 [-0.005510736450688101, -0.003600146231859923] | masi_return_120 <= 0.0720138 AND stock_ma_distance_200 >= 0.101659 |
| monthly | preliminary | 52 | 0.10248417151260171 [0.01965550364522472, 0.2546001712797883] | 0.09102121574608006 [0.013424995551077009, 0.22127369246480988] | masi_volatility_20 >= 0.0842404 AND stock_adv20 >= 1.48697e+07 |
| quarterly | preliminary | 55 | 0.1922820056633592 [0.07842583462504242, 0.262843753094219] | 0.1601864971896046 [0.07070709006189349, 0.2343292664633929] | stock_return_60 >= 0.0406643 AND masi_volatility_20 >= 0.0842404 |

## Approval rule

A policy is accepted only with at least 15 outer-fold trades, positive 95% lower bounds for both net return and MASI alpha, positive alpha in a majority of folds, leave-one-symbol-out stability, and corrected inner-search significance.

No production trading policy is changed by this report.
