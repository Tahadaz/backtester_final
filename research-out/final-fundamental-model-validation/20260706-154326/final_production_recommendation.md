# Final Production Recommendation

Generated: 2026-07-06T15:49:27.983202+00:00

## Verdict

Freeze production as two transparent separate signals: Structural Value (B/M) and Cash-Flow Value (CF/P for non-financials by default). Do not use old SFC as production selector; keep as legacy benchmark/research. Implement first strategy as separate 50/50 B/M and CF/P sleeves with displayed component disagreement; keep B/M-only as fallback when CF/P is not economically applicable.

## Architecture Bakeoff

| sample       | signal                         | definition                              | horizon   |   periods |   pairs |   mean_ic |   median_ic |   ic_std |   hit_rate |   hac_t_stat |   pvalue |   top_bottom_spread |   net_sharpe |   max_drawdown |   turnover |
|:-------------|:-------------------------------|:----------------------------------------|:----------|----------:|--------:|----------:|------------:|---------:|-----------:|-------------:|---------:|--------------------:|-------------:|---------------:|-----------:|
| architecture | book_to_market                 | M1 B/M alone                            | 6m        |        56 |    2254 |    0.1638 |      0.1743 |   0.2419 |     0.7679 |       2.8134 |   0.0049 |              0.1034 |       0.7591 |        -0.8644 |     0.0685 |
| architecture | cashflow_price                 | M2 CF/P alone                           | 6m        |        44 |    2139 |    0.1467 |      0.1329 |   0.1379 |     0.8864 |       5.8144 |   0      |              0.1035 |       1.0634 |        -0.6233 |     0.0988 |
| architecture | value_equal_rank               | M3 equal-weight rank composite          | 6m        |        56 |    2254 |    0.1786 |      0.1556 |   0.1993 |     0.8571 |       3.8735 |   0.0001 |              0.0908 |       1.0525 |        -0.4964 |     0.097  |
| architecture | value_intersection_top_tercile | M5 top tercile in both                  | 6m        |        44 |    2223 |    0.1462 |      0.1439 |   0.2346 |     0.7727 |       2.4605 |   0.0139 |             -0.0241 |      -0.1309 |        -0.9982 |     0.1014 |
| architecture | value_bm_confirmed             | M6 B/M primary, CF/P not bottom tercile | 6m        |        44 |    1440 |    0.1881 |      0.1776 |   0.2978 |     0.7727 |       2.0746 |   0.038  |              0.0147 |       0.0668 |        -0.9939 |     0.088  |
| architecture | value_cfp_confirmed            | M6 CF/P primary, B/M not bottom tercile | 6m        |        44 |    1437 |    0.1324 |      0.125  |   0.2519 |     0.6591 |       2.2536 |   0.0242 |              0.0486 |       0.3241 |        -0.8708 |     0.0837 |
| architecture | value_orthogonal_combo         | M7 B/M + CF/P residualized against B/M  | 6m        |        56 |    2254 |    0.1727 |      0.1521 |   0.2031 |     0.8214 |       3.8834 |   0.0001 |              0.0989 |       0.8435 |        -0.7603 |     0.0968 |
| nan          | separate_sleeves_50_50         | nan                                     | nan       |       nan |     nan |  nan      |    nan      | nan      |   nan      |     nan      | nan      |              0.1035 |       1.6335 |        -0.047  |   nan      |

## B/M Vs CF/P

| sample          | signal         | definition   | horizon   |   periods |   pairs |   mean_ic |   median_ic |   ic_std |   hit_rate |   hac_t_stat |   pvalue |   top_bottom_spread |   net_sharpe |   max_drawdown |   turnover |
|:----------------|:---------------|:-------------|:----------|----------:|--------:|----------:|------------:|---------:|-----------:|-------------:|---------:|--------------------:|-------------:|---------------:|-----------:|
| pairwise_common | book_to_market | B/M          | 6m        |        44 |    2139 |    0.1979 |      0.2105 |   0.2328 |     0.7955 |       2.8668 |   0.0041 |              0.1023 |       0.7403 |        -0.8745 |     0.0685 |
| pairwise_common | cashflow_price | CF/P         | 6m        |        44 |    2139 |    0.1467 |      0.1329 |   0.1379 |     0.8864 |       5.8144 |   0      |              0.1035 |       1.0634 |        -0.6233 |     0.0988 |

## Market Alpha

| strategy                            |   periods |   alpha |   alpha_hac_t |    beta |     r2 |   resid_vol |
|:------------------------------------|----------:|--------:|--------------:|--------:|-------:|------------:|
| bm_top_bottom                       |        44 |  0.1161 |        2.9434 | -0.0999 | 0.0073 |      0.192  |
| cfp_top_bottom                      |        44 |  0.076  |        3.6971 |  0.2161 | 0.0673 |      0.133  |
| bm_long_top                         |        44 |  0.0606 |        2.8842 |  1.0753 | 0.7396 |      0.1051 |
| cfp_long_top                        |        44 |  0.05   |        5.1563 |  1.28   | 0.9067 |      0.0679 |
| arch_book_to_market                 |        44 |  0.1161 |        2.9434 | -0.0999 | 0.0073 |      0.192  |
| arch_cashflow_price                 |        44 |  0.076  |        3.6971 |  0.2161 | 0.0673 |      0.133  |
| arch_value_equal_rank               |        44 |  0.0897 |        3.281  |  0.009  | 0.0001 |      0.122  |
| arch_value_intersection_top_tercile |        44 |  0.0336 |        0.8965 | -0.4655 | 0.0852 |      0.2492 |
| arch_value_bm_confirmed             |        31 |  0.1857 |        1.5901 | -0.9819 | 0.1855 |      0.2819 |
| arch_value_cfp_confirmed            |        31 |  0.0931 |        2.6544 | -0.2502 | 0.0176 |      0.2103 |
| arch_value_orthogonal_combo         |        44 |  0.111  |        3.1088 | -0.095  | 0.0089 |      0.1651 |
| arch_separate_sleeves_50_50         |        44 |  0.0958 |        4.6487 |  0.0602 | 0.0123 |      0.089  |

## Third Factor Decision

| challenger                     |   periods |   mean_coef |   hac_t_stat |
|:-------------------------------|----------:|------------:|-------------:|
| operating_profitability_approx |        31 |      0.0581 |       3.4775 |
| conservative_investment        |        31 |      0.0177 |       2.0241 |
| sales_price                    |        33 |      0.0364 |       1.2184 |
| small_size                     |        33 |      0.0524 |       2.1091 |
| momentum_12_1                  |        22 |      0.0649 |       2.714  |
| accrual_quality                |        33 |      0.0643 |       2.0619 |
| ebitda_ev_yield                |        33 |     -0.0226 |      -1.0842 |

## Final Gate Answers

1. B/M is robust to ordinary outlier handling. Raw, percentile-rank, 1/99 winsorized, 2.5/97.5 winsorized, and MAD-clipped versions all retain the same positive 6m economic result; the rank IC remains about 0.164-0.165 with HAC t about 2.8.
2. CF/P is also robust to ordinary outlier handling. Raw, rank, winsorized, and MAD-clipped versions retain 6m IC about 0.146-0.147 with HAC t about 5.8 and positive top-bottom economics.
3. B/M has material single-name sensitivity. Removing IAM lowers B/M IC from 0.164 to 0.103 and HAC t to 1.68. The signal is still economically meaningful, but the statistical margin is thinner than the headline suggests.
4. CF/P is not driven by one name. The worst leave-one-stock case still has IC 0.105 and HAC t 5.57; removing IAM leaves IC 0.112 and HAC t 3.84.
5. Neither leader is driven by one date. The worst leave-one-date CF/P IC remains 0.141 with HAC t above 5.9. B/M date influence is materially less severe than its IAM stock influence.
6. B/M is not merely a small-cap effect in this sample. Excluding the smallest 10% and 20% by market cap improves B/M IC to 0.186 and 0.194, respectively, and improves Sharpe.
7. CF/P is not merely a liquidity effect. Excluding the lowest-liquidity bucket leaves CF/P IC 0.191, HAC t 6.82, spread 13.2%, and Sharpe 1.26, although turnover rises materially.
8. Both leaders retain broad-market alpha under the available raw market-return attribution. B/M top-bottom alpha is 11.6% with HAC t 2.94 and beta -0.10; CF/P top-bottom alpha is 7.6% with HAC t 3.70 and beta 0.22. No risk-free history was fabricated.
9. CF/P should not be treated as economically comparable for financial firms in the production UI. The financial-only result is statistically positive, but operating cash flow has different meaning for banks/insurers. Use CF/P for non-financials by default and show a financial-firm applicability warning.
10. B/M remains the strongest structural standalone predictor on a pairwise common sample: IC 0.198 versus CF/P 0.147. CF/P is the cleaner statistically stable complementary predictor: HAC t 5.81 and better spread Sharpe.
11. CF/P remains incremental beyond B/M in the prior established-characteristic study and remains stable in this final gate. Its low average rank correlation with B/M and retained controlled IC support keeping it separate rather than treating it as redundant B/M.
12. No third factor earns production admission now. Operating profitability, conservative investment, small size, momentum, and accrual quality show isolated incremental coefficients, but none clears the full gate of standalone robustness, economic harvestability, accounting comparability, and conceptual fit as a production fundamental sleeve.
13. The best strategy architecture is M4, separate 50/50 B/M and CF/P sleeves. It has the strongest economic profile in this gate: net Sharpe 1.63, max drawdown -4.7%, market alpha 9.6% with HAC t 4.65, and beta near zero.
14. The most robust single displayed score is not a single opaque score. Equal-rank B/M+CF/P has good IC and drawdown, but lower spread than the sleeves. Orthogonal combo is defensible for research, not necessary for production UI.
15. Intersection and confirmation overlays fail the production gate. Top-tercile intersection has negative spread and near-total drawdown; confirmation overlays raise IC in places but destroy economics.
16. The simplest defensible production method is two transparent value signals plus a portfolio-level two-sleeve implementation. Do not fit weights.
17. The old SFC should be removed from production selection and retained only as a legacy benchmark/research/debug display. It is not clearer or more robust than the two-leader value architecture.
18. Freeze the production methodology as: Structural Value = B/M percentile; Cash-Flow Value = CF/P percentile for non-financials; portfolio implementation = 50/50 capital allocation to independent top-tercile sleeves, with B/M-only fallback when CF/P is unavailable or economically inapplicable.

## App Representation

Display `Fundamental Signals` as separate components, not one black-box score.

- `Structural Value`: raw B/M, market percentile, sector/peer percentile where breadth permits, availability date, and a plain-language interpretation.
- `Cash-Flow Value`: raw CF/P, market percentile, sector/peer percentile where breadth permits, availability date, and an applicability flag. For financial firms, default to `not production-ranked` unless a separate financial-sector cash-flow methodology is approved.
- `Value Consensus`: display only as a transparent diagnostic derived from the two component percentiles. Show agreement/disagreement; do not hide B/M and CF/P behind it.
- `Quality/Profitability`: display as diagnostics/watchlist only. Do not rank production portfolios on gross profitability, operating profitability, ROE, or ROA yet.
- `Momentum`: display in a separate market/technical layer, not inside the fundamental score.
- `Intrinsic Valuation`: keep as a research/valuation diagnostic, not the production systematic selector.
- `Legacy SFC`: research/debug benchmark only.

## First Strategy To Implement

Backtest and implement first: monthly PIT-rebalanced two-sleeve value strategy using the existing universe, liquidity rules, transaction costs, and tercile portfolio machinery.

- Sleeve 1: long top tercile by B/M.
- Sleeve 2: long top tercile by CF/P for economically applicable non-financial names.
- Allocation: 50% capital to each sleeve, equal-weight within sleeve.
- Fallback: if CF/P is unavailable or inapplicable, allocate that name-selection decision to B/M rather than imputing CF/P.
- Benchmark: equal-weight eligible market return and existing legacy SFC benchmark.
- Governance: no fitted weights, no threshold optimization, no sign changes, and no third factor until a new predeclared validation gate supports it.
