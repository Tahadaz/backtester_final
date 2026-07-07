# Native Coverage Factor Leaderboard

Generated: 2026-07-06T19:46:08.563724+00:00

## 6m Leaderboard

| signal                         | group                 |   periods |   pairs |   mean_ic |   hac_t_stat |   fdr_qvalue |   hit_rate |   top_bottom_spread |   net_sharpe |   turnover | monotonic   |
|:-------------------------------|:----------------------|----------:|--------:|----------:|-------------:|-------------:|-----------:|--------------------:|-------------:|-----------:|:------------|
| book_to_market                 | value                 |        56 |    2148 |    0.1702 |       3.4507 |       0.0064 |     0.75   |              0.1754 |       1.7149 |     0.0552 | True        |
| cashflow_price                 | value                 |        44 |    1676 |    0.1354 |       4.9354 |       0      |     0.8182 |              0.1262 |       0.9958 |     0.1169 | False       |
| low_leverage                   | distress              |        70 |    2379 |    0.103  |       1.8852 |       0.3145 |     0.6571 |             -0.0111 |      -0.1217 |     0.0871 | False       |
| small_size                     | risk_size             |        56 |    2290 |    0.0839 |       1.3013 |       0.5553 |     0.6429 |              0.1557 |       1.0794 |     0.0532 | True        |
| beta_high                      | risk_size             |        64 |    2073 |    0.0786 |       0.8596 |       0.7475 |     0.6562 |              0.0773 |       0.4513 |     0.2314 | False       |
| momentum_12_1                  | market_behavior       |        57 |    1651 |    0.0751 |       0.6582 |       0.8449 |     0.5088 |              0.1436 |       0.5967 |     0.3671 | True        |
| earnings_yield                 | value                 |        56 |    2266 |    0.0694 |       1.2276 |       0.5612 |     0.6429 |             -0.072  |      -0.6653 |     0.0991 | False       |
| ebitda_ev_yield                | value                 |        70 |    2094 |    0.0322 |       0.4277 |       0.8449 |     0.5429 |             -0.0464 |      -0.5922 |     0.1019 | False       |
| momentum_6_1                   | market_behavior       |        63 |    2006 |    0.0279 |       0.4127 |       0.8449 |     0.5079 |              0.0466 |       0.2995 |     0.447  | False       |
| dividend_yield                 | value                 |        56 |    2091 |    0.0204 |       0.2781 |       0.8449 |     0.4286 |             -0.0891 |      -0.812  |     0.1123 | False       |
| sales_price                    | value                 |        56 |    2266 |    0.0175 |       0.2428 |       0.8449 |     0.5893 |              0.1417 |       1.3761 |     0.0916 | True        |
| piotroski_lite                 | profitability_quality |        70 |    2485 |   -0.0101 |      -0.1851 |       0.8532 |     0.5143 |             -0.0313 |      -0.3368 |     0.1204 | False       |
| short_reversal                 | market_behavior       |        69 |    2347 |   -0.0171 |      -0.4665 |       0.8449 |     0.4928 |             -0.0386 |      -0.3602 |     0.8214 | False       |
| operating_profitability_approx | profitability_quality |        70 |    2273 |   -0.0194 |      -0.2707 |       0.8449 |     0.4429 |             -0.1083 |      -1.2579 |     0.0934 | False       |
| roa_standalone                 | profitability_quality |        70 |    2379 |   -0.0205 |      -0.3153 |       0.8449 |     0.4714 |             -0.1159 |      -1.1452 |     0.0658 | False       |
| roe_standalone                 | profitability_quality |        70 |    2379 |   -0.0324 |      -0.4273 |       0.8449 |     0.4286 |             -0.1185 |      -1.1682 |     0.0789 | False       |
| accrual_quality                | profitability_quality |        44 |    2158 |   -0.039  |      -0.5344 |       0.8449 |     0.5682 |              0.032  |       0.2807 |     0.0968 | False       |
| beta_low                       | risk_size             |        64 |    2073 |   -0.0786 |      -0.8596 |       0.7475 |     0.3125 |             -0.0802 |      -0.4681 |     0.1994 | False       |
| size_log_mcap                  | risk_size             |        56 |    2290 |   -0.0839 |      -1.3013 |       0.5553 |     0.3571 |             -0.1564 |      -1.0835 |     0.047  | False       |
| conservative_investment        | investment            |        68 |    2318 |   -0.0844 |      -1.1496 |       0.5757 |     0.5    |              0.0756 |       0.9779 |     0.1478 | True        |
| low_total_volatility           | risk_size             |        64 |    2073 |   -0.1297 |      -1.6217 |       0.402  |     0.3125 |             -0.1725 |      -1.2436 |     0.1858 | False       |
| low_idio_volatility            | risk_size             |        64 |    2073 |   -0.1343 |      -1.8226 |       0.3145 |     0.3125 |             -0.1689 |      -1.2321 |     0.1552 | False       |
| gross_profitability            | profitability_quality |        44 |    1634 |   -0.1752 |      -2.6846 |       0.0557 |     0.1364 |             -0.2098 |      -1.4899 |     0.0918 | False       |

## Bucket Monotonicity

| signal                         |   periods |   bottom_return |   middle_return |   top_return |   top_minus_bottom |   avg_names_bottom |   avg_names_top | monotonic   |
|:-------------------------------|----------:|----------------:|----------------:|-------------:|-------------------:|-------------------:|----------------:|:------------|
| earnings_yield                 |        44 |          0.1835 |          0.0769 |       0.117  |            -0.0665 |            16.5227 |         16.8182 | False       |
| book_to_market                 |        44 |          0.0344 |          0.0961 |       0.2004 |             0.166  |            15.6136 |         16.1136 | True        |
| dividend_yield                 |        44 |          0.1615 |          0.0921 |       0.071  |            -0.0904 |            15.1364 |         15.5455 | False       |
| cashflow_price                 |        35 |          0.2126 |          0.1019 |       0.3225 |             0.1099 |            15.4571 |         15.5714 | False       |
| sales_price                    |        44 |          0.0627 |          0.1283 |       0.1908 |             0.1281 |            16.5227 |         16.8182 | True        |
| ebitda_ev_yield                |        44 |          0.1512 |          0.1521 |       0.108  |            -0.0432 |            14.7727 |         15.0455 | False       |
| small_size                     |        56 |          0.0294 |          0.0826 |       0.1955 |             0.1662 |            13.625  |         14.0714 | True        |
| size_log_mcap                  |        56 |          0.183  |          0.0957 |       0.0347 |            -0.1483 |            13.625  |         14.0714 | False       |
| operating_profitability_approx |        44 |          0.158  |          0.1205 |       0.0546 |            -0.1034 |            15.9773 |         16.4545 | False       |
| gross_profitability            |        35 |          0.3262 |          0.2046 |       0.1251 |            -0.201  |            14.8    |         15.2571 | False       |
| roe_standalone                 |        44 |          0.1966 |          0.0989 |       0.0771 |            -0.1194 |            16.8864 |         17.1591 | False       |
| roa_standalone                 |        44 |          0.1733 |          0.1424 |       0.0593 |            -0.114  |            16.8864 |         17.1591 | False       |
| accrual_quality                |        44 |          0.1236 |          0.1044 |       0.1503 |             0.0267 |            16.4545 |         16.6136 | False       |
| piotroski_lite                 |        70 |          0.109  |          0.0989 |       0.0885 |            -0.0206 |            11.7571 |         12.2714 | False       |
| conservative_investment        |        44 |          0.0805 |          0.1288 |       0.1583 |             0.0778 |            16.6136 |         16.8864 | True        |
| low_leverage                   |        44 |          0.104  |          0.1765 |       0.0944 |            -0.0097 |            16.8864 |         17.1591 | False       |
| momentum_12_1                  |        57 |          0.0866 |          0.0895 |       0.2191 |             0.1325 |             9.5263 |         10.1053 | True        |
| momentum_6_1                   |        63 |          0.119  |          0.0907 |       0.1707 |             0.0517 |            10.4921 |         11.0794 | False       |
| short_reversal                 |        69 |          0.1281 |          0.1021 |       0.0923 |            -0.0358 |            11.2754 |         11.7391 | False       |
| beta_high                      |        64 |          0.1069 |          0.0882 |       0.1767 |             0.0698 |            10.6875 |         11.2656 | False       |
| beta_low                       |        64 |          0.1818 |          0.0915 |       0.1031 |            -0.0787 |            10.6875 |         11.2656 | False       |
| low_total_volatility           |        64 |          0.2069 |          0.1147 |       0.059  |            -0.1479 |            10.6875 |         11.2656 | False       |
| low_idio_volatility            |        64 |          0.2091 |          0.1094 |       0.0616 |            -0.1475 |            10.6875 |         11.2656 | False       |
