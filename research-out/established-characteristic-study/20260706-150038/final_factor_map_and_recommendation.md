# Final Factor Map And Methodology Recommendation

Generated: 2026-07-06T15:03:08.462348+00:00

## Factor Tiers

| signal                         | group                 | tier                              |   mean_ic |   hac_t_stat |   fdr_qvalue |   spread |   sharpe |
|:-------------------------------|:----------------------|:----------------------------------|----------:|-------------:|-------------:|---------:|---------:|
| book_to_market                 | value                 | Tier 1 - strong candidate         |    0.1638 |       2.8134 |       0.0376 |   0.1034 |   0.7591 |
| cashflow_price                 | value                 | Tier 2 - promising but uncertain  |    0.1467 |       5.8144 |       0      |   0.1035 |   1.0634 |
| low_leverage                   | distress              | Tier 4 - not supported            |    0.116  |       2.04   |       0.2377 |  -0.0197 |  -0.2167 |
| small_size                     | risk_size             | Tier 2 - promising but uncertain  |    0.0839 |       1.3013 |       0.7404 |   0.1557 |   1.0794 |
| momentum_12_1                  | market_behavior       | Tier 2 - promising but uncertain  |    0.0751 |       0.6582 |       0.9197 |   0.1436 |   0.5967 |
| earnings_yield                 | value                 | Tier 4 - not supported            |    0.0674 |       1.0878 |       0.9091 |  -0.0741 |  -0.6438 |
| ebitda_ev_yield                | value                 | Tier 4 - not supported            |    0.0513 |       0.6542 |       0.9197 |  -0.0464 |  -0.5922 |
| sales_price                    | value                 | Tier 2 - promising but uncertain  |    0.051  |       0.797  |       0.9197 |   0.1503 |   1.4447 |
| dividend_yield                 | value                 | Tier 4 - not supported            |    0.0395 |       0.4734 |       0.9197 |  -0.0891 |  -0.812  |
| momentum_6_1                   | market_behavior       | Tier 4 - not supported            |    0.0279 |       0.4127 |       0.9197 |   0.0466 |   0.2995 |
| operating_profitability_approx | profitability_quality | Tier 4 - not supported            |    0.0161 |       0.273  |       0.9501 |  -0.0908 |  -1.0744 |
| short_reversal                 | market_behavior       | Tier 4 - not supported            |   -0.0171 |      -0.4665 |       0.9197 |  -0.0386 |  -0.3602 |
| roa_standalone                 | profitability_quality | Tier 4 - not supported            |   -0.0207 |      -0.3172 |       0.9501 |  -0.1159 |  -1.1452 |
| piotroski_lite                 | profitability_quality | Tier 4 - not supported            |   -0.026  |      -0.4762 |       0.9197 |  -0.0412 |  -0.4384 |
| roe_standalone                 | profitability_quality | Tier 4 - not supported            |   -0.0324 |      -0.4273 |       0.9197 |  -0.1185 |  -1.1682 |
| accrual_quality                | profitability_quality | Tier 4 - not supported            |   -0.0376 |      -0.5117 |       0.9197 |   0.0392 |   0.3386 |
| conservative_investment        | investment            | Tier 4 - not supported            |   -0.057  |      -0.8597 |       0.9197 |   0.0772 |   0.9042 |
| size_log_mcap                  | risk_size             | Tier 4 - not supported            |   -0.0839 |      -1.3013 |       0.7404 |  -0.1564 |  -1.0835 |
| gross_profitability            | profitability_quality | Tier 4 - not supported            |   -0.1958 |      -3.2706 |       0.0123 |  -0.2175 |  -1.5245 |
| beta_high                      | risk_size             | Tier 5 - infeasible/thin coverage |  nan      |       0      |       1      | nan      | nan      |
| beta_low                       | risk_size             | Tier 5 - infeasible/thin coverage |  nan      |       0      |       1      | nan      | nan      |
| low_total_volatility           | risk_size             | Tier 5 - infeasible/thin coverage |  nan      |       0      |       1      | nan      | nan      |
| low_idio_volatility            | risk_size             | Tier 5 - infeasible/thin coverage |  nan      |       0      |       1      | nan      | nan      |

## Recommendation

Preliminary rule: promote B/M from benchmark to primary standalone fundamental signal if it remains Tier 1. Use other Tier 1/Tier 2 signals only as separate sleeves when incremental regressions and orthogonalized IC support them. Do not create an equal-weight composite from weak or redundant characteristics.

## Top Leaderboard Rows

| signal                         | group                 |   mean_ic |   hac_t_stat |   fdr_qvalue |   top_bottom_spread |   net_sharpe |   turnover |   monotonic |
|:-------------------------------|:----------------------|----------:|-------------:|-------------:|--------------------:|-------------:|-----------:|------------:|
| book_to_market                 | value                 |    0.1638 |       2.8134 |       0.0376 |              0.1034 |       0.7591 |     0.0685 |           1 |
| cashflow_price                 | value                 |    0.1467 |       5.8144 |       0      |              0.1035 |       1.0634 |     0.0988 |           0 |
| low_leverage                   | distress              |    0.116  |       2.04   |       0.2377 |             -0.0197 |      -0.2167 |     0.0888 |           0 |
| small_size                     | risk_size             |    0.0839 |       1.3013 |       0.7404 |              0.1557 |       1.0794 |     0.0532 |           1 |
| momentum_12_1                  | market_behavior       |    0.0751 |       0.6582 |       0.9197 |              0.1436 |       0.5967 |     0.3671 |           1 |
| earnings_yield                 | value                 |    0.0674 |       1.0878 |       0.9091 |             -0.0741 |      -0.6438 |     0.101  |           0 |
| ebitda_ev_yield                | value                 |    0.0513 |       0.6542 |       0.9197 |             -0.0464 |      -0.5922 |     0.1019 |           0 |
| sales_price                    | value                 |    0.051  |       0.797  |       0.9197 |              0.1503 |       1.4447 |     0.0761 |           1 |
| dividend_yield                 | value                 |    0.0395 |       0.4734 |       0.9197 |             -0.0891 |      -0.812  |     0.1123 |           0 |
| momentum_6_1                   | market_behavior       |    0.0279 |       0.4127 |       0.9197 |              0.0466 |       0.2995 |     0.447  |           0 |
| operating_profitability_approx | profitability_quality |    0.0161 |       0.273  |       0.9501 |             -0.0908 |      -1.0744 |     0.096  |           0 |
| short_reversal                 | market_behavior       |   -0.0171 |      -0.4665 |       0.9197 |             -0.0386 |      -0.3602 |     0.8214 |           0 |
| roa_standalone                 | profitability_quality |   -0.0207 |      -0.3172 |       0.9501 |             -0.1159 |      -1.1452 |     0.0658 |           0 |
| piotroski_lite                 | profitability_quality |   -0.026  |      -0.4762 |       0.9197 |             -0.0412 |      -0.4384 |     0.1177 |           0 |
| roe_standalone                 | profitability_quality |   -0.0324 |      -0.4273 |       0.9197 |             -0.1185 |      -1.1682 |     0.0789 |           0 |
| accrual_quality                | profitability_quality |   -0.0376 |      -0.5117 |       0.9197 |              0.0392 |       0.3386 |     0.0968 |           0 |
| conservative_investment        | investment            |   -0.057  |      -0.8597 |       0.9197 |              0.0772 |       0.9042 |     0.1357 |           1 |
| size_log_mcap                  | risk_size             |   -0.0839 |      -1.3013 |       0.7404 |             -0.1564 |      -1.0835 |     0.047  |           0 |
| gross_profitability            | profitability_quality |   -0.1958 |      -3.2706 |       0.0123 |             -0.2175 |      -1.5245 |     0.0963 |           0 |
| beta_high                      | risk_size             |  nan      |       0      |       1      |            nan      |     nan      |   nan      |         nan |
| beta_low                       | risk_size             |  nan      |       0      |       1      |            nan      |     nan      |   nan      |         nan |
| low_total_volatility           | risk_size             |  nan      |       0      |       1      |            nan      |     nan      |   nan      |         nan |
| low_idio_volatility            | risk_size             |  nan      |       0      |       1      |            nan      |     nan      |   nan      |         nan |
