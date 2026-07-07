# Extreme Values And Data Quality Audit

Generated: 2026-07-06T15:49:27.944289+00:00

## Distributions

| signal                         | raw_col                        |   count |   non_finite |      min |     p0_5 |      p1 |      p5 |   median |    p95 |     p99 |   p99_5 |      max |   negative_values |   near_zero_market_cap |   negative_book_equity |   negative_cfo |
|:-------------------------------|:-------------------------------|--------:|-------------:|---------:|---------:|--------:|--------:|---------:|-------:|--------:|--------:|---------:|------------------:|-----------------------:|-----------------------:|---------------:|
| book_to_market                 | book_to_market_raw             |    2845 |            0 | -12.0216 | -10.569  | -9.1331 |  0      |   0.4779 | 3.8547 | 27.0833 | 31.4026 |  41.9349 |               127 |                      0 |                    127 |              0 |
| cashflow_price                 | cashflow_price_raw             |    2628 |            0 |  -4.7316 |  -3.0434 | -1.5756 | -0.2108 |   0.0736 | 0.4078 | 25.5376 | 41.1813 |  41.3331 |               448 |                      0 |                      0 |            448 |
| sales_price                    | sales_price_raw                |    2857 |            0 |   0      |   0      |  0.0003 |  0.0964 |   0.5264 | 5.6946 | 30.9992 | 34.6681 | 263.047  |                 0 |                      0 |                      0 |              0 |
| earnings_yield                 | earnings_yield_raw             |    2857 |            0 |  -2.6695 |  -1.6384 | -1.1031 | -0.1302 |   0.0484 | 0.1233 |  2.7806 |  3.7872 |   4.3568 |               330 |                      0 |                      0 |              0 |
| ebitda_ev_yield                | ebitda_ev_yield_raw            |    2613 |            0 |  -0.4334 |  -0.2415 | -0.1822 | -0.0093 |   0.115  | 3.4242 | 16.0893 | 17.9747 |  28.2154 |               139 |                      0 |                      0 |              0 |
| operating_profitability_approx | operating_profitability_approx |    2754 |            0 |  -2.6686 |  -1.9323 | -1.6831 | -1.2631 |  -0.182  | 2.0995 |  2.389  |  2.402  |   2.4082 |              1622 |                      0 |                      0 |              0 |
| gross_profitability            | gross_profitability_raw        |    2045 |            0 |  -0.1838 |  -0.1838 | -0.0791 | -0.0146 |   0.2076 | 0.5063 |  1.2887 |  1.3077 |   1.3131 |               127 |                      0 |                      0 |              0 |
| conservative_investment        | conservative_investment        |    2820 |            0 |  -2.491  |  -2.4829 | -2.3688 | -1.9203 |   0.1105 | 1.7804 |  2.2982 |  2.4855 |   2.6518 |              1261 |                      0 |                      0 |              0 |
| small_size                     | small_size                     |    2785 |            0 |  -2.9051 |  -2.8089 | -2.5199 | -1.5214 |  -0.0539 | 1.7491 |  2.1903 |  2.3522 |   2.4947 |              1447 |                      0 |                      0 |              0 |
| momentum_12_1                  | momentum_12_1_raw              |    2284 |            0 |  -0.9126 |  -0.3914 | -0.362  | -0.209  |   0.112  | 1.6735 |  4.052  |  5.1037 |   8.3492 |               680 |                      0 |                      0 |              0 |

## Top Extremes

| signal                         | symbol   | as_of_date   |    value |   market_cap_raw |   book_to_market_raw |   cashflow_price_raw |   sales_price_raw | sector             | is_financial   |
|:-------------------------------|:---------|:-------------|---------:|-----------------:|---------------------:|---------------------:|------------------:|:-------------------|:---------------|
| book_to_market                 | REB      | 2025-09-30   |  41.9349 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| book_to_market                 | REB      | 2025-06-30   |  41.9349 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| book_to_market                 | REB      | 2025-12-31   |  41.9349 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| book_to_market                 | REB      | 2026-01-31   |  41.9349 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| book_to_market                 | REB      | 2025-04-30   |  41.9349 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| book_to_market                 | REB      | 2025-11-30   |  41.9349 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| book_to_market                 | REB      | 2025-07-31   |  41.9349 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| book_to_market                 | REB      | 2025-08-31   |  41.9349 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| book_to_market                 | REB      | 2025-05-31   |  41.9349 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| book_to_market                 | REB      | 2025-10-31   |  41.9349 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| cashflow_price                 | SAH      | 2023-07-31   |  41.3331 |      2.64896e+08 |              19.0255 |              41.3331 |           22.5094 | Assurances         | True           |
| cashflow_price                 | SAH      | 2023-09-30   |  41.3331 |      2.64896e+08 |              19.0255 |              41.3331 |           22.5094 | Assurances         | True           |
| cashflow_price                 | SAH      | 2023-08-31   |  41.3331 |      2.64896e+08 |              19.0255 |              41.3331 |           22.5094 | Assurances         | True           |
| cashflow_price                 | SAH      | 2023-12-31   |  41.3331 |      2.64896e+08 |              19.0255 |              41.3331 |           22.5094 | Assurances         | True           |
| cashflow_price                 | SAH      | 2023-11-30   |  41.3331 |      2.64896e+08 |              19.0255 |              41.3331 |           22.5094 | Assurances         | True           |
| cashflow_price                 | SAH      | 2023-10-31   |  41.3331 |      2.64896e+08 |              19.0255 |              41.3331 |           22.5094 | Assurances         | True           |
| cashflow_price                 | SAH      | 2023-04-30   |  41.3331 |      2.64896e+08 |              19.0255 |              41.3331 |           22.5094 | Assurances         | True           |
| cashflow_price                 | SAH      | 2023-05-31   |  41.3331 |      2.64896e+08 |              19.0255 |              41.3331 |           22.5094 | Assurances         | True           |
| cashflow_price                 | SAH      | 2023-06-30   |  41.3331 |      2.64896e+08 |              19.0255 |              41.3331 |           22.5094 | Assurances         | True           |
| cashflow_price                 | SAH      | 2024-02-29   |  41.3331 |      2.64896e+08 |              19.0255 |              41.3331 |           22.5094 | Assurances         | True           |
| sales_price                    | REB      | 2026-02-28   | 263.047  |      1.26607e+07 |              25.2138 |               0.0229 |          263.047  | Mines              | False          |
| sales_price                    | SAH      | 2025-08-31   |  36.4948 |      1.82437e+08 |              31.4026 |              41.1813 |           36.4948 | Assurances         | True           |
| sales_price                    | SAH      | 2025-05-31   |  36.4948 |      1.82437e+08 |              31.4026 |              41.1813 |           36.4948 | Assurances         | True           |
| sales_price                    | SAH      | 2025-07-31   |  36.4948 |      1.82437e+08 |              31.4026 |              41.1813 |           36.4948 | Assurances         | True           |
| sales_price                    | SAH      | 2025-06-30   |  36.4948 |      1.82437e+08 |              31.4026 |              41.1813 |           36.4948 | Assurances         | True           |
| sales_price                    | SAH      | 2026-02-28   |  36.4948 |      1.82437e+08 |              31.4026 |              41.1813 |           36.4948 | Assurances         | True           |
| sales_price                    | SAH      | 2025-10-31   |  36.4948 |      1.82437e+08 |              31.4026 |              41.1813 |           36.4948 | Assurances         | True           |
| sales_price                    | SAH      | 2025-03-31   |  36.4948 |      1.82437e+08 |              31.4026 |              41.1813 |           36.4948 | Assurances         | True           |
| sales_price                    | SAH      | 2025-12-31   |  36.4948 |      1.82437e+08 |              31.4026 |              41.1813 |           36.4948 | Assurances         | True           |
| sales_price                    | SAH      | 2025-11-30   |  36.4948 |      1.82437e+08 |              31.4026 |              41.1813 |           36.4948 | Assurances         | True           |
| earnings_yield                 | REB      | 2025-11-30   |   4.3568 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| earnings_yield                 | REB      | 2025-04-30   |   4.3568 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| earnings_yield                 | REB      | 2025-05-31   |   4.3568 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| earnings_yield                 | REB      | 2025-08-31   |   4.3568 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| earnings_yield                 | REB      | 2025-10-31   |   4.3568 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| earnings_yield                 | REB      | 2025-06-30   |   4.3568 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| earnings_yield                 | REB      | 2025-09-30   |   4.3568 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| earnings_yield                 | REB      | 2025-07-31   |   4.3568 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| earnings_yield                 | REB      | 2025-12-31   |   4.3568 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| earnings_yield                 | REB      | 2026-01-31   |   4.3568 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| ebitda_ev_yield                | SBM      | 2023-05-31   |  28.2154 |      6.786e+09   |               0.2303 |               0.0831 |            0.4288 | Boissons           | False          |
| ebitda_ev_yield                | SBM      | 2023-04-30   |  28.2154 |      6.786e+09   |               0.2303 |               0.0831 |            0.4288 | Boissons           | False          |
| ebitda_ev_yield                | SBM      | 2023-07-31   |  28.2154 |      6.786e+09   |               0.2303 |               0.0831 |            0.4288 | Boissons           | False          |
| ebitda_ev_yield                | SBM      | 2023-06-30   |  28.2154 |      6.786e+09   |               0.2303 |               0.0831 |            0.4288 | Boissons           | False          |
| ebitda_ev_yield                | SBM      | 2023-12-31   |  28.2154 |      6.786e+09   |               0.2303 |               0.0831 |            0.4288 | Boissons           | False          |
| ebitda_ev_yield                | SBM      | 2023-11-30   |  28.2154 |      6.786e+09   |               0.2303 |               0.0831 |            0.4288 | Boissons           | False          |
| ebitda_ev_yield                | SBM      | 2023-10-31   |  28.2154 |      6.786e+09   |               0.2303 |               0.0831 |            0.4288 | Boissons           | False          |
| ebitda_ev_yield                | SBM      | 2024-02-29   |  28.2154 |      6.786e+09   |               0.2303 |               0.0831 |            0.4288 | Boissons           | False          |
| ebitda_ev_yield                | SBM      | 2023-09-30   |  28.2154 |      6.786e+09   |               0.2303 |               0.0831 |            0.4288 | Boissons           | False          |
| ebitda_ev_yield                | SBM      | 2023-08-31   |  28.2154 |      6.786e+09   |               0.2303 |               0.0831 |            0.4288 | Boissons           | False          |
| operating_profitability_approx | MDP      | 2026-03-31   |  -2.6686 |      1.12372e+08 |               0.3662 |               0.1113 |            0.7868 | Autre              | False          |
| operating_profitability_approx | M2M      | 2023-12-31   |  -2.5368 |      5.11e+08    |               0.3366 |               0.0007 |            0.1211 | Informatique       | False          |
| operating_profitability_approx | M2M      | 2024-01-31   |  -2.5368 |      5.11e+08    |               0.3366 |               0.0007 |            0.1211 | Informatique       | False          |
| operating_profitability_approx | M2M      | 2023-07-31   |  -2.5282 |      5.11e+08    |               0.3366 |               0.0007 |            0.1211 | Informatique       | False          |
| operating_profitability_approx | M2M      | 2024-02-29   |  -2.5183 |      5.11e+08    |               0.3366 |               0.0007 |            0.1211 | Informatique       | False          |
| operating_profitability_approx | M2M      | 2023-08-31   |  -2.5101 |      5.11e+08    |               0.3366 |               0.0007 |            0.1211 | Informatique       | False          |
| operating_profitability_approx | M2M      | 2023-09-30   |  -2.5101 |      5.11e+08    |               0.3366 |               0.0007 |            0.1211 | Informatique       | False          |
| operating_profitability_approx | M2M      | 2023-10-31   |  -2.5101 |      5.11e+08    |               0.3366 |               0.0007 |            0.1211 | Informatique       | False          |
| operating_profitability_approx | M2M      | 2023-11-30   |  -2.5101 |      5.11e+08    |               0.3366 |               0.0007 |            0.1211 | Informatique       | False          |
| operating_profitability_approx | M2M      | 2023-04-30   |  -2.4683 |      5.11e+08    |               0.3366 |               0.0007 |            0.1211 | Informatique       | False          |
| gross_profitability            | REB      | 2023-09-30   |   1.3131 |      2e+07       |               1.2    |               0.011  |           19.6236 | Mines              | False          |
| gross_profitability            | REB      | 2023-08-31   |   1.3131 |      2e+07       |               1.2    |               0.011  |           19.6236 | Mines              | False          |
| gross_profitability            | REB      | 2023-11-30   |   1.3131 |      2e+07       |               1.2    |               0.011  |           19.6236 | Mines              | False          |
| gross_profitability            | REB      | 2023-06-30   |   1.3131 |      2e+07       |               1.2    |               0.011  |           19.6236 | Mines              | False          |
| gross_profitability            | REB      | 2023-05-31   |   1.3131 |      2e+07       |               1.2    |               0.011  |           19.6236 | Mines              | False          |
| gross_profitability            | REB      | 2024-01-31   |   1.3131 |      2e+07       |               1.2    |               0.011  |           19.6236 | Mines              | False          |
| gross_profitability            | REB      | 2023-04-30   |   1.3131 |      2e+07       |               1.2    |               0.011  |           19.6236 | Mines              | False          |
| gross_profitability            | REB      | 2023-07-31   |   1.3131 |      2e+07       |               1.2    |               0.011  |           19.6236 | Mines              | False          |
| gross_profitability            | REB      | 2023-10-31   |   1.3131 |      2e+07       |               1.2    |               0.011  |           19.6236 | Mines              | False          |
| gross_profitability            | REB      | 2024-02-29   |   1.3131 |      2e+07       |               1.2    |               0.011  |           19.6236 | Mines              | False          |
| conservative_investment        | ATW      | 2025-11-30   |   2.6518 |      1.0927e+11  |               0.6635 |               0.3296 |            0.2784 | Banques            | True           |
| conservative_investment        | ZDJ      | 2025-04-30   |   2.6281 |      5.8e+07     |               1.9643 |              -0.115  |           12.1324 | Mines              | False          |
| conservative_investment        | ZDJ      | 2025-06-30   |   2.6281 |      5.8e+07     |               1.9643 |              -0.115  |           12.1324 | Mines              | False          |
| conservative_investment        | ZDJ      | 2025-05-31   |   2.6281 |      5.8e+07     |               1.9643 |              -0.115  |           12.1324 | Mines              | False          |
| conservative_investment        | REB      | 2025-04-30   |   2.6281 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| conservative_investment        | REB      | 2025-05-31   |   2.6281 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| conservative_investment        | REB      | 2025-06-30   |   2.6281 |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| conservative_investment        | REB      | 2025-03-31   |   2.6281 |      1.26607e+07 |               1.9596 |               0.0229 |           30.9992 | Mines              | False          |
| conservative_investment        | ZDJ      | 2025-03-31   |   2.6281 |      5.8e+07     |               1.9643 |              -0.115  |           12.1324 | Mines              | False          |
| conservative_investment        | REB      | 2025-08-31   |   2.608  |      1.26607e+07 |              41.9349 |               0.0229 |           30.9992 | Mines              | False          |
| small_size                     | IAM      | 2024-08-31   |  -2.9051 |      7.43055e+13 |               0.0003 |               0.0002 |            0.0005 | Télécommunications | False          |
| small_size                     | IAM      | 2024-09-30   |  -2.9015 |      7.43055e+13 |               0.0003 |               0.0002 |            0.0005 | Télécommunications | False          |
| small_size                     | IAM      | 2024-04-30   |  -2.8985 |      7.43055e+13 |               0.0003 |               0.0002 |            0.0005 | Télécommunications | False          |
| small_size                     | IAM      | 2024-10-31   |  -2.8979 |      7.43055e+13 |               0.0003 |               0.0002 |            0.0005 | Télécommunications | False          |
| small_size                     | IAM      | 2024-05-31   |  -2.8976 |      7.43055e+13 |               0.0003 |               0.0002 |            0.0005 | Télécommunications | False          |
| small_size                     | IAM      | 2024-06-30   |  -2.8963 |      7.43055e+13 |               0.0003 |               0.0002 |            0.0005 | Télécommunications | False          |
| small_size                     | IAM      | 2024-11-30   |  -2.8947 |      7.43055e+13 |               0.0003 |               0.0002 |            0.0005 | Télécommunications | False          |
| small_size                     | IAM      | 2024-07-31   |  -2.89   |      7.43055e+13 |               0.0003 |               0.0002 |            0.0005 | Télécommunications | False          |
| small_size                     | IAM      | 2024-03-31   |  -2.879  |      7.43055e+13 |               0.0003 |               0.0002 |            0.0005 | Télécommunications | False          |
| small_size                     | IAM      | 2026-04-30   |  -2.8522 |      1.07569e+14 |               0.0002 |               0.0002 |            0.0003 | Télécommunications | False          |
| momentum_12_1                  | STR      | 2025-07-31   |   8.3492 |      3.22991e+07 |             -10.569  |               1.5189 |            3.6224 | Industrie          | False          |
| momentum_12_1                  | SNA      | 2025-11-30   |   7.1782 |      1.82437e+08 |              -0.6179 |               0.1495 |            1.833  | Distribution       | False          |
| momentum_12_1                  | SNA      | 2025-09-30   |   6.5854 |      1.82437e+08 |              -0.6179 |               0.1495 |            1.833  | Distribution       | False          |
| momentum_12_1                  | SNA      | 2025-10-31   |   6.4538 |      1.82437e+08 |              -0.6179 |               0.1495 |            1.833  | Distribution       | False          |
| momentum_12_1                  | SNA      | 2025-08-31   |   6.4143 |      1.82437e+08 |              -0.6179 |               0.1495 |            1.833  | Distribution       | False          |
| momentum_12_1                  | SNA      | 2025-12-31   |   5.8526 |      1.82437e+08 |              -0.6179 |               0.1495 |            1.833  | Distribution       | False          |
| momentum_12_1                  | JET      | 2025-01-31   |   5.7908 |      6.18022e+08 |               1.7313 |              -0.0637 |            3.6002 | BTP                | False          |
| momentum_12_1                  | JET      | 2025-03-31   |   5.5789 |      1.28755e+09 |               0.9157 |               0.1438 |            2.4318 | BTP                | False          |
| momentum_12_1                  | STR      | 2025-11-30   |   5.5212 |      3.22991e+07 |             -10.569  |               1.5189 |            3.6224 | Industrie          | False          |
| momentum_12_1                  | JET      | 2025-02-28   |   5.2817 |      6.18022e+08 |               1.7313 |              -0.0637 |            3.6002 | BTP                | False          |

## Conclusion

No automatic deletions were applied. Negative CFO and negative earnings are preserved as economic states; CF/P production should exclude financial firms unless CFO comparability is explicitly approved.
