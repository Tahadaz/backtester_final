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
| weekly | preliminary (rejected) | 190 | -0.004114223413775226 [-0.008625030114230447, 0.0009213414696237312] | -0.004589538902230117 [-0.005510736450688101, -0.003600146231859923] | masi_return_120 <= 0.0720138 AND stock_ma_distance_200 >= 0.101659 |
| monthly | preliminary (rejected) | 52 | 0.10248417151260171 [0.01965550364522472, 0.2546001712797883] | 0.09102121574608006 [0.013424995551077009, 0.22127369246480988] | masi_volatility_20 >= 0.0842404 AND stock_adv20 >= 1.48697e+07 |
| quarterly | preliminary (accepted) | 55 | 0.1922820056633592 [0.07842583462504242, 0.262843753094219] | 0.1601864971896046 [0.07070709006189349, 0.2343292664633929] | stock_return_60 >= 0.0406643 AND masi_volatility_20 >= 0.0842404 |

## Rejected and lower-ranked rules

### Weekly
- `masi_volatility_60 >= 0.0706822 AND stock_ma_distance_200 >= 0.101659` - net=0.017780611218953902, alpha=0.012956994846844452, q=0.0021175071103878944; reasons: lower_ranked.
- `hit_ci_lower >= 0.511391 AND masi_volatility_20 >= 0.0686672` - net=0.04538384670058368, alpha=0.0376262238423021, q=0.16875419840783296; reasons: multiple_testing.
- `masi_volatility_60 >= 0.0706822 AND stock_ma_distance_50 >= 0.0617953` - net=0.034625349564528146, alpha=0.029834158462967, q=1.0; reasons: multiple_testing.

### Monthly
- `stock_drawdown_60 >= -0.0106313 AND stock_adv20 >= 1.48697e+07` - net=0.07245176179919473, alpha=0.04849466692202066, q=0.056344852657640915; reasons: lower_ranked.
- `stock_drawdown_60 >= -0.0106313 AND stock_adv20 >= 1.06399e+07` - net=0.07245176179919473, alpha=0.04849466692202066, q=0.056344852657640915; reasons: lower_ranked.
- `masi_volatility_20 >= 0.100939 AND stock_volatility_60 <= 0.207992` - net=0.05405730778241157, alpha=0.03154851374628484, q=5.527688348367084e-05; reasons: lower_ranked.

### Quarterly
- `masi_volatility_20 >= 0.0842404 AND stock_return_60 >= 0.0595238` - net=0.2550067939638003, alpha=0.2058565082358631, q=4.318905492260829e-07; reasons: lower_ranked.
- `stock_return_60 >= 0.0406643 AND masi_volatility_60 >= 0.0688509` - net=0.25201226734137167, alpha=0.2013694449048089, q=1.7345449708697308e-08; reasons: lower_ranked.
- `stock_return_60 >= 0.0406643 AND masi_return_120 <= 0.0877295` - net=0.25260835898355005, alpha=0.19823507410879698, q=5.2518940708870295e-12; reasons: lower_ranked.


## Approval rule

A policy is accepted only with at least 15 outer-fold trades, positive 95% lower bounds for both net return and MASI alpha, positive alpha in a majority of folds, leave-one-symbol-out stability, and corrected inner-search significance.

No production trading policy is changed by this report.
