# Final Decision Report

Generated: 2026-07-06T14:29:58.998755+00:00

## Decision Framework

Decision framework: prioritize 6m native and common IC, stability/hit-rate, size robustness, net spread/Sharpe after costs, coverage, and simplicity. No weighted meta-score is used. Model B is marked reconstructed-PIT because persisted valuation vintages start in 2026 and cannot support the historical test.

## Head-To-Head Summary

| sample   | signal                    | definition                                                                                        | horizon   |   periods |   pairs |   mean_ic |   median_ic |   ic_std |   hit_rate |   hac_t_stat |   pvalue |   top_bottom_spread |   net_sharpe |   max_drawdown |   turnover |   observations |   dates |   avg_names_per_date | methodology                       |
|:---------|:--------------------------|:--------------------------------------------------------------------------------------------------|:----------|----------:|--------:|----------:|------------:|---------:|-----------:|-------------:|---------:|--------------------:|-------------:|---------------:|-----------:|---------------:|--------:|---------------------:|:----------------------------------|
| native   | classical_characteristics | A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components            | 6m        |        56 |    2307 |    0.0229 |      0.0458 |   0.3366 |     0.5893 |       0.2438 |   0.8074 |              0.1094 |       0.8621 |        -0.5278 |     0.1174 |           2809 |      63 |              44.5873 | A. Classical characteristics      |
| native   | intrinsic_valuation       | B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions     | 6m        |        15 |     506 |    0.1137 |      0.1084 |   0.2057 |     0.7333 |       2.4699 |   0.0135 |              0.0891 |       0.7112 |        -0.165  |     0.456  |            608 |      17 |              35.7647 | B. Systematic intrinsic valuation |
| native   | fundamental_momentum      | C accounting change/improvement composite; no analyst revisions due lack of true revision history | 6m        |        68 |    2354 |    0.1119 |      0.0676 |   0.3044 |     0.6176 |       1.7619 |   0.0781 |             -0.0435 |      -0.296  |        -0.9925 |     0.1941 |           2856 |      75 |              38.08   | C. Fundamental momentum/change    |
| native   | residual_value            | D cheapness residual from log(P/B) explained by ROE, revenue growth, and size                     | 6m        |        31 |    1930 |    0.1162 |      0.0761 |   0.1582 |     0.7419 |       1.868  |   0.0618 |              0.0892 |       0.878  |        -0.5442 |     0.0802 |           2404 |      38 |              63.2632 | D. Relative/residual valuation    |

## Common-Sample IC

| sample   | signal                    | definition                                                                                        | horizon   |   periods |   pairs |   mean_ic |   median_ic |   ic_std |   hit_rate |   hac_t_stat |   pvalue |
|:---------|:--------------------------|:--------------------------------------------------------------------------------------------------|:----------|----------:|--------:|----------:|------------:|---------:|-----------:|-------------:|---------:|
| common   | classical_characteristics | A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components            | 1m        |        12 |     557 |    0.0126 |     -0.0004 |   0.1674 |     0.5    |       0.2662 |   0.7901 |
| common   | classical_characteristics | A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components            | 3m        |        11 |     505 |    0.0601 |      0.0677 |   0.1355 |     0.6364 |       2.0636 |   0.0391 |
| common   | classical_characteristics | A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components            | 6m        |        10 |     458 |    0.0676 |      0.0398 |   0.15   |     0.7    |       2.9555 |   0.0031 |
| common   | classical_characteristics | A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components            | 12m       |         8 |     365 |    0.1453 |      0.1555 |   0.0436 |     1      |      29.7258 |   0      |
| common   | intrinsic_valuation       | B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions     | 1m        |        12 |     557 |   -0.0031 |      0.0277 |   0.1375 |     0.5833 |      -0.0792 |   0.9369 |
| common   | intrinsic_valuation       | B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions     | 3m        |        11 |     505 |    0.0349 |      0.0313 |   0.1406 |     0.5455 |       1.4196 |   0.1557 |
| common   | intrinsic_valuation       | B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions     | 6m        |        10 |     458 |    0.0805 |      0.1123 |   0.1106 |     0.7    |       3.9786 |   0.0001 |
| common   | intrinsic_valuation       | B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions     | 12m       |         8 |     365 |    0.1691 |      0.174  |   0.1103 |     0.875  |       4.3645 |   0      |
| common   | fundamental_momentum      | C accounting change/improvement composite; no analyst revisions due lack of true revision history | 1m        |        12 |     557 |    0.0425 |     -0.0097 |   0.1415 |     0.5    |       1.2105 |   0.2261 |
| common   | fundamental_momentum      | C accounting change/improvement composite; no analyst revisions due lack of true revision history | 3m        |        11 |     505 |    0.0361 |      0.0182 |   0.1583 |     0.5455 |       1.0677 |   0.2856 |
| common   | fundamental_momentum      | C accounting change/improvement composite; no analyst revisions due lack of true revision history | 6m        |        10 |     458 |    0.0394 |      0.0599 |   0.1596 |     0.6    |       1.1207 |   0.2624 |
| common   | fundamental_momentum      | C accounting change/improvement composite; no analyst revisions due lack of true revision history | 12m       |         8 |     365 |   -0.0244 |     -0.0389 |   0.1568 |     0.5    |      -0.4063 |   0.6845 |
| common   | residual_value            | D cheapness residual from log(P/B) explained by ROE, revenue growth, and size                     | 1m        |        12 |     557 |    0.1282 |      0.1395 |   0.1203 |     0.75   |       3.9885 |   0.0001 |
| common   | residual_value            | D cheapness residual from log(P/B) explained by ROE, revenue growth, and size                     | 3m        |        11 |     505 |    0.0492 |      0.0311 |   0.1825 |     0.7273 |       0.7498 |   0.4533 |
| common   | residual_value            | D cheapness residual from log(P/B) explained by ROE, revenue growth, and size                     | 6m        |        10 |     458 |    0.0869 |      0.0843 |   0.1791 |     0.7    |       1.2486 |   0.2118 |
| common   | residual_value            | D cheapness residual from log(P/B) explained by ROE, revenue growth, and size                     | 12m       |         8 |     365 |    0.0535 |      0.0776 |   0.204  |     0.75   |       0.7775 |   0.4368 |

## Caveats

Analyst revisions excluded; current SFC retained only as legacy benchmark; no causal claims.

## Verdict

Overall recommended methodology: **keep multiple separate sleeves, led by relative/residual valuation and raw book-to-market value; do not replace the desk process with intrinsic valuation alone.**

Evidence summary:

| Question | Verdict |
|---|---|
| Best native 6m predictive IC among primary methods | **D residual value**: mean IC 0.116, HAC t 1.87, 31 periods, 1,930 pairs. |
| Strongest common-sample 6m IC | **B intrinsic valuation**: mean IC 0.080, HAC t 3.98 on 10 common periods; caveat: reconstructed/sampled valuation, not persisted historical valuation vintages. |
| Most investable on native sample | **D residual value** narrowly: 6m net spread 8.9%, Sharpe 0.88, turnover 8.0%; SFC legacy benchmark has stronger spread/Sharpe but is not one of the four primary methods. |
| Most investable on common sample | **A classical characteristics**: 6m net spread 7.8%, Sharpe 1.37, max drawdown -7.9%. |
| Most robust after size control | **D residual value**: size-neutral 6m IC 0.117; intrinsic falls to 0.040; fundamental momentum turns negative. |
| Does sophisticated intrinsic valuation beat simple characteristics? | **Not cleanly.** It has stronger IC on its native/common valuation sample, but lower common-sample net spread than classical and material reconstruction/outlier-warning caveats. |
| Does fundamental momentum add information? | **Weakly in IC, not harvestably.** Native 6m IC is 0.112, but size-neutral IC is -0.046 and net spread is negative. Individual earnings growth and cash-flow-conversion changes are stronger than the composite. |
| Does residual valuation add beyond raw value? | **Yes, but raw B/M is still the cleanest single signal.** Residual value has good IC and size robustness, low redundancy with B/M/common signals, and low turnover; raw B/M has higher individual 6m IC 0.185, HAC t 3.85. |
| Does any method clearly beat existing SFC? | **For IC, yes: raw B/M, residual value, intrinsic valuation, and fundamental momentum beat SFC's 6m IC of 0.033. For investable spread, no primary method clearly beats SFC legacy's 12.7% 6m spread and Sharpe 1.42.** |

Decision:

1. Adopt **residual valuation + raw B/M/classical value** as the primary research signal family for Morocco today.
2. Keep **intrinsic valuation** as a diagnostic/overlay, not the primary systematic selector, until historical valuation-vintage assumptions and unit warnings are resolved.
3. Do **not** deploy the current fundamental-momentum composite as a standalone portfolio rule. Retain earnings-growth and cash-flow-conversion change as candidate sub-signals.
4. Keep SFC as a legacy benchmark; its investable backtest remains strong, but its proof IC is weaker than the value-oriented methods and its FMOM component has known design caveats.
