# Final Factor Map And Methodology Recommendation

Generated: 2026-07-06T19:46:08.593286+00:00

## Factor Tiers

| signal                         | group                 | tier                             |   mean_ic |   hac_t_stat |   fdr_qvalue |   spread |   sharpe |
|:-------------------------------|:----------------------|:---------------------------------|----------:|-------------:|-------------:|---------:|---------:|
| book_to_market                 | value                 | Tier 1 - strong candidate        |    0.1702 |       3.4507 |       0.0064 |   0.1754 |   1.7149 |
| cashflow_price                 | value                 | Tier 2 - promising but uncertain |    0.1354 |       4.9354 |       0      |   0.1262 |   0.9958 |
| low_leverage                   | distress              | Tier 4 - not supported           |    0.103  |       1.8852 |       0.3145 |  -0.0111 |  -0.1217 |
| small_size                     | risk_size             | Tier 2 - promising but uncertain |    0.0839 |       1.3013 |       0.5553 |   0.1557 |   1.0794 |
| beta_high                      | risk_size             | Tier 2 - promising but uncertain |    0.0786 |       0.8596 |       0.7475 |   0.0773 |   0.4513 |
| momentum_12_1                  | market_behavior       | Tier 2 - promising but uncertain |    0.0751 |       0.6582 |       0.8449 |   0.1436 |   0.5967 |
| earnings_yield                 | value                 | Tier 4 - not supported           |    0.0694 |       1.2276 |       0.5612 |  -0.072  |  -0.6653 |
| ebitda_ev_yield                | value                 | Tier 4 - not supported           |    0.0322 |       0.4277 |       0.8449 |  -0.0464 |  -0.5922 |
| momentum_6_1                   | market_behavior       | Tier 4 - not supported           |    0.0279 |       0.4127 |       0.8449 |   0.0466 |   0.2995 |
| dividend_yield                 | value                 | Tier 4 - not supported           |    0.0204 |       0.2781 |       0.8449 |  -0.0891 |  -0.812  |
| sales_price                    | value                 | Tier 4 - not supported           |    0.0175 |       0.2428 |       0.8449 |   0.1417 |   1.3761 |
| piotroski_lite                 | profitability_quality | Tier 4 - not supported           |   -0.0101 |      -0.1851 |       0.8532 |  -0.0313 |  -0.3368 |
| short_reversal                 | market_behavior       | Tier 4 - not supported           |   -0.0171 |      -0.4665 |       0.8449 |  -0.0386 |  -0.3602 |
| operating_profitability_approx | profitability_quality | Tier 4 - not supported           |   -0.0194 |      -0.2707 |       0.8449 |  -0.1083 |  -1.2579 |
| roa_standalone                 | profitability_quality | Tier 4 - not supported           |   -0.0205 |      -0.3153 |       0.8449 |  -0.1159 |  -1.1452 |
| roe_standalone                 | profitability_quality | Tier 4 - not supported           |   -0.0324 |      -0.4273 |       0.8449 |  -0.1185 |  -1.1682 |
| accrual_quality                | profitability_quality | Tier 4 - not supported           |   -0.039  |      -0.5344 |       0.8449 |   0.032  |   0.2807 |
| beta_low                       | risk_size             | Tier 4 - not supported           |   -0.0786 |      -0.8596 |       0.7475 |  -0.0802 |  -0.4681 |
| size_log_mcap                  | risk_size             | Tier 4 - not supported           |   -0.0839 |      -1.3013 |       0.5553 |  -0.1564 |  -1.0835 |
| conservative_investment        | investment            | Tier 4 - not supported           |   -0.0844 |      -1.1496 |       0.5757 |   0.0756 |   0.9779 |
| low_total_volatility           | risk_size             | Tier 4 - not supported           |   -0.1297 |      -1.6217 |       0.402  |  -0.1725 |  -1.2436 |
| low_idio_volatility            | risk_size             | Tier 4 - not supported           |   -0.1343 |      -1.8226 |       0.3145 |  -0.1689 |  -1.2321 |
| gross_profitability            | profitability_quality | Tier 4 - not supported           |   -0.1752 |      -2.6846 |       0.0557 |  -0.2098 |  -1.4899 |

## Recommendation

Preliminary rule: promote B/M from benchmark to primary standalone fundamental signal if it remains Tier 1. Use other Tier 1/Tier 2 signals only as separate sleeves when incremental regressions and orthogonalized IC support them. Do not create an equal-weight composite from weak or redundant characteristics.

## Top Leaderboard Rows

| signal                         | group                 |   mean_ic |   hac_t_stat |   fdr_qvalue |   top_bottom_spread |   net_sharpe |   turnover | monotonic   |
|:-------------------------------|:----------------------|----------:|-------------:|-------------:|--------------------:|-------------:|-----------:|:------------|
| book_to_market                 | value                 |    0.1702 |       3.4507 |       0.0064 |              0.1754 |       1.7149 |     0.0552 | True        |
| cashflow_price                 | value                 |    0.1354 |       4.9354 |       0      |              0.1262 |       0.9958 |     0.1169 | False       |
| low_leverage                   | distress              |    0.103  |       1.8852 |       0.3145 |             -0.0111 |      -0.1217 |     0.0871 | False       |
| small_size                     | risk_size             |    0.0839 |       1.3013 |       0.5553 |              0.1557 |       1.0794 |     0.0532 | True        |
| beta_high                      | risk_size             |    0.0786 |       0.8596 |       0.7475 |              0.0773 |       0.4513 |     0.2314 | False       |
| momentum_12_1                  | market_behavior       |    0.0751 |       0.6582 |       0.8449 |              0.1436 |       0.5967 |     0.3671 | True        |
| earnings_yield                 | value                 |    0.0694 |       1.2276 |       0.5612 |             -0.072  |      -0.6653 |     0.0991 | False       |
| ebitda_ev_yield                | value                 |    0.0322 |       0.4277 |       0.8449 |             -0.0464 |      -0.5922 |     0.1019 | False       |
| momentum_6_1                   | market_behavior       |    0.0279 |       0.4127 |       0.8449 |              0.0466 |       0.2995 |     0.447  | False       |
| dividend_yield                 | value                 |    0.0204 |       0.2781 |       0.8449 |             -0.0891 |      -0.812  |     0.1123 | False       |
| sales_price                    | value                 |    0.0175 |       0.2428 |       0.8449 |              0.1417 |       1.3761 |     0.0916 | True        |
| piotroski_lite                 | profitability_quality |   -0.0101 |      -0.1851 |       0.8532 |             -0.0313 |      -0.3368 |     0.1204 | False       |
| short_reversal                 | market_behavior       |   -0.0171 |      -0.4665 |       0.8449 |             -0.0386 |      -0.3602 |     0.8214 | False       |
| operating_profitability_approx | profitability_quality |   -0.0194 |      -0.2707 |       0.8449 |             -0.1083 |      -1.2579 |     0.0934 | False       |
| roa_standalone                 | profitability_quality |   -0.0205 |      -0.3153 |       0.8449 |             -0.1159 |      -1.1452 |     0.0658 | False       |
| roe_standalone                 | profitability_quality |   -0.0324 |      -0.4273 |       0.8449 |             -0.1185 |      -1.1682 |     0.0789 | False       |
| accrual_quality                | profitability_quality |   -0.039  |      -0.5344 |       0.8449 |              0.032  |       0.2807 |     0.0968 | False       |
| beta_low                       | risk_size             |   -0.0786 |      -0.8596 |       0.7475 |             -0.0802 |      -0.4681 |     0.1994 | False       |
| size_log_mcap                  | risk_size             |   -0.0839 |      -1.3013 |       0.5553 |             -0.1564 |      -1.0835 |     0.047  | False       |
| conservative_investment        | investment            |   -0.0844 |      -1.1496 |       0.5757 |              0.0756 |       0.9779 |     0.1478 | True        |
| low_total_volatility           | risk_size             |   -0.1297 |      -1.6217 |       0.402  |             -0.1725 |      -1.2436 |     0.1858 | False       |
| low_idio_volatility            | risk_size             |   -0.1343 |      -1.8226 |       0.3145 |             -0.1689 |      -1.2321 |     0.1552 | False       |
| gross_profitability            | profitability_quality |   -0.1752 |      -2.6846 |       0.0557 |             -0.2098 |      -1.4899 |     0.0918 | False       |
