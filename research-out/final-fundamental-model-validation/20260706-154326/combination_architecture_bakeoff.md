# Combination Architecture Bakeoff

Generated: 2026-07-06T15:49:27.978622+00:00

## Architectures

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

## Market Alpha For Architectures

| strategy                            |   periods |   alpha |   alpha_hac_t |    beta |     r2 |   resid_vol |
|:------------------------------------|----------:|--------:|--------------:|--------:|-------:|------------:|
| arch_book_to_market                 |        44 |  0.1161 |        2.9434 | -0.0999 | 0.0073 |      0.192  |
| arch_cashflow_price                 |        44 |  0.076  |        3.6971 |  0.2161 | 0.0673 |      0.133  |
| arch_value_equal_rank               |        44 |  0.0897 |        3.281  |  0.009  | 0.0001 |      0.122  |
| arch_value_intersection_top_tercile |        44 |  0.0336 |        0.8965 | -0.4655 | 0.0852 |      0.2492 |
| arch_value_bm_confirmed             |        31 |  0.1857 |        1.5901 | -0.9819 | 0.1855 |      0.2819 |
| arch_value_cfp_confirmed            |        31 |  0.0931 |        2.6544 | -0.2502 | 0.0176 |      0.2103 |
| arch_value_orthogonal_combo         |        44 |  0.111  |        3.1088 | -0.095  | 0.0089 |      0.1651 |
| arch_separate_sleeves_50_50         |        44 |  0.0958 |        4.6487 |  0.0602 | 0.0123 |      0.089  |
