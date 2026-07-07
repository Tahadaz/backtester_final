# Native Coverage Factor Leaderboard

Generated: 2026-07-06T15:07:30.128806+00:00

## 6m Leaderboard

| signal                         | group                 |   periods |   pairs |   mean_ic |   hac_t_stat |   fdr_qvalue |   hit_rate |   top_bottom_spread |   net_sharpe |   turnover | monotonic   |
|:-------------------------------|:----------------------|----------:|--------:|----------:|-------------:|-------------:|-----------:|--------------------:|-------------:|-----------:|:------------|
| book_to_market                 | value                 |        56 |    2254 |    0.1638 |       2.8134 |       0.0376 |     0.7679 |              0.1034 |       0.7591 |     0.0685 | True        |
| cashflow_price                 | value                 |        44 |    2139 |    0.1467 |       5.8144 |       0      |     0.8864 |              0.1035 |       1.0634 |     0.0988 | False       |
| low_leverage                   | distress              |        70 |    2379 |    0.116  |       2.04   |       0.2377 |     0.6714 |             -0.0197 |      -0.2167 |     0.0888 | False       |
| small_size                     | risk_size             |        56 |    2290 |    0.0839 |       1.3013 |       0.5553 |     0.6429 |              0.1557 |       1.0794 |     0.0532 | True        |
| beta_high                      | risk_size             |        64 |    2073 |    0.0786 |       0.8596 |       0.7445 |     0.6562 |              0.0773 |       0.4513 |     0.2314 | False       |
| momentum_12_1                  | market_behavior       |        57 |    1651 |    0.0751 |       0.6582 |       0.7445 |     0.5088 |              0.1436 |       0.5967 |     0.3671 | True        |
| earnings_yield                 | value                 |        56 |    2266 |    0.0674 |       1.0878 |       0.7071 |     0.6071 |             -0.0741 |      -0.6438 |     0.101  | False       |
| ebitda_ev_yield                | value                 |        70 |    2094 |    0.0513 |       0.6542 |       0.7445 |     0.5857 |             -0.0464 |      -0.5922 |     0.1019 | False       |
| sales_price                    | value                 |        56 |    2266 |    0.051  |       0.797  |       0.7445 |     0.625  |              0.1503 |       1.4447 |     0.0761 | True        |
| dividend_yield                 | value                 |        56 |    2091 |    0.0395 |       0.4734 |       0.7445 |     0.4286 |             -0.0891 |      -0.812  |     0.1123 | False       |
| momentum_6_1                   | market_behavior       |        63 |    2006 |    0.0279 |       0.4127 |       0.7445 |     0.5079 |              0.0466 |       0.2995 |     0.447  | False       |
| operating_profitability_approx | profitability_quality |        70 |    2273 |    0.0161 |       0.273  |       0.7849 |     0.4286 |             -0.0908 |      -1.0744 |     0.096  | False       |
| short_reversal                 | market_behavior       |        69 |    2347 |   -0.0171 |      -0.4665 |       0.7445 |     0.4928 |             -0.0386 |      -0.3602 |     0.8214 | False       |
| roa_standalone                 | profitability_quality |        70 |    2379 |   -0.0207 |      -0.3172 |       0.7849 |     0.4714 |             -0.1159 |      -1.1452 |     0.0658 | False       |
| piotroski_lite                 | profitability_quality |        70 |    2485 |   -0.026  |      -0.4762 |       0.7445 |     0.4571 |             -0.0412 |      -0.4384 |     0.1177 | False       |
| roe_standalone                 | profitability_quality |        70 |    2379 |   -0.0324 |      -0.4273 |       0.7445 |     0.4286 |             -0.1185 |      -1.1682 |     0.0789 | False       |
| accrual_quality                | profitability_quality |        44 |    2158 |   -0.0376 |      -0.5117 |       0.7445 |     0.5682 |              0.0392 |       0.3386 |     0.0968 | False       |
| conservative_investment        | investment            |        68 |    2318 |   -0.057  |      -0.8597 |       0.7445 |     0.5147 |              0.0772 |       0.9042 |     0.1357 | True        |
| beta_low                       | risk_size             |        64 |    2073 |   -0.0786 |      -0.8596 |       0.7445 |     0.3125 |             -0.0802 |      -0.4681 |     0.1994 | False       |
| size_log_mcap                  | risk_size             |        56 |    2290 |   -0.0839 |      -1.3013 |       0.5553 |     0.3571 |             -0.1564 |      -1.0835 |     0.047  | False       |
| low_total_volatility           | risk_size             |        64 |    2073 |   -0.1297 |      -1.6217 |       0.402  |     0.3125 |             -0.1725 |      -1.2436 |     0.1858 | False       |
| low_idio_volatility            | risk_size             |        64 |    2073 |   -0.1343 |      -1.8226 |       0.3145 |     0.3125 |             -0.1689 |      -1.2321 |     0.1552 | False       |
| gross_profitability            | profitability_quality |        44 |    1664 |   -0.1958 |      -3.2706 |       0.0123 |     0.1364 |             -0.2175 |      -1.5245 |     0.0963 | False       |

## Bucket Monotonicity

| signal                         |   periods |   bottom_return |   middle_return |   top_return |   top_minus_bottom |   avg_names_bottom |   avg_names_top | monotonic   |
|:-------------------------------|----------:|----------------:|----------------:|-------------:|-------------------:|-------------------:|----------------:|:------------|
| earnings_yield                 |        44 |          0.1886 |          0.0759 |       0.1128 |            -0.0757 |            16.5227 |         16.8182 | False       |
| book_to_market                 |        44 |          0.0904 |          0.0969 |       0.1923 |             0.102  |            16.5227 |         16.8182 | True        |
| dividend_yield                 |        44 |          0.1615 |          0.0921 |       0.071  |            -0.0904 |            15.1364 |         15.5455 | False       |
| cashflow_price                 |        44 |          0.1168 |          0.0572 |       0.2045 |             0.0877 |            16.1818 |         16.5227 | False       |
| sales_price                    |        44 |          0.0587 |          0.1303 |       0.1927 |             0.134  |            16.5227 |         16.8182 | True        |
| ebitda_ev_yield                |        44 |          0.1512 |          0.1521 |       0.108  |            -0.0432 |            14.7727 |         15.0455 | False       |
| small_size                     |        56 |          0.0294 |          0.0826 |       0.1955 |             0.1662 |            13.625  |         14.0714 | True        |
| size_log_mcap                  |        56 |          0.183  |          0.0957 |       0.0347 |            -0.1483 |            13.625  |         14.0714 | False       |
| operating_profitability_approx |        44 |          0.1439 |          0.1148 |       0.0703 |            -0.0735 |            15.9773 |         16.4545 | False       |
| gross_profitability            |        35 |          0.3147 |          0.2181 |       0.113  |            -0.2017 |            15.2571 |         15.4571 | False       |
| roe_standalone                 |        44 |          0.1966 |          0.0989 |       0.0771 |            -0.1194 |            16.8864 |         17.1591 | False       |
| roa_standalone                 |        44 |          0.1733 |          0.1424 |       0.0593 |            -0.114  |            16.8864 |         17.1591 | False       |
| accrual_quality                |        44 |          0.1157 |          0.1125 |       0.1503 |             0.0346 |            16.4545 |         16.6136 | False       |
| piotroski_lite                 |        70 |          0.1087 |          0.1057 |       0.0828 |            -0.0259 |            11.7571 |         12.2714 | False       |
| conservative_investment        |        44 |          0.0874 |          0.1137 |       0.1659 |             0.0785 |            16.6136 |         16.8864 | True        |
| low_leverage                   |        44 |          0.1037 |          0.1873 |       0.0843 |            -0.0194 |            16.8864 |         17.1591 | False       |
| momentum_12_1                  |        57 |          0.0866 |          0.0895 |       0.2191 |             0.1325 |             9.5263 |         10.1053 | True        |
| momentum_6_1                   |        63 |          0.119  |          0.0907 |       0.1707 |             0.0517 |            10.4921 |         11.0794 | False       |
| short_reversal                 |        69 |          0.1281 |          0.1021 |       0.0923 |            -0.0358 |            11.2754 |         11.7391 | False       |
| beta_high                      |        64 |          0.1069 |          0.0882 |       0.1767 |             0.0698 |            10.6875 |         11.2656 | False       |
| beta_low                       |        64 |          0.1818 |          0.0915 |       0.1031 |            -0.0787 |            10.6875 |         11.2656 | False       |
| low_total_volatility           |        64 |          0.2069 |          0.1147 |       0.059  |            -0.1479 |            10.6875 |         11.2656 | False       |
| low_idio_volatility            |        64 |          0.2091 |          0.1094 |       0.0616 |            -0.1475 |            10.6875 |         11.2656 | False       |
