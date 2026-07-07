# Redundancy And Incremental Analysis

Generated: 2026-07-06T15:07:30.156171+00:00

## Pairwise Rank Correlations

| left                           | right                          |   periods |   mean_rank_corr |
|:-------------------------------|:-------------------------------|----------:|-----------------:|
| low_total_volatility           | low_idio_volatility            |        71 |           0.9706 |
| operating_profitability_approx | roe_standalone                 |        77 |           0.776  |
| roe_standalone                 | roa_standalone                 |        77 |           0.7363 |
| operating_profitability_approx | roa_standalone                 |        77 |           0.7236 |
| size_log_mcap                  | low_idio_volatility            |        63 |           0.6759 |
| size_log_mcap                  | low_total_volatility           |        63 |           0.6354 |
| momentum_12_1                  | momentum_6_1                   |        64 |           0.6234 |
| gross_profitability            | roa_standalone                 |        51 |           0.6028 |
| cashflow_price                 | accrual_quality                |        51 |           0.5964 |
| sales_price                    | small_size                     |        63 |           0.5679 |
| beta_low                       | low_total_volatility           |        71 |           0.5519 |
| book_to_market                 | sales_price                    |        63 |           0.4441 |
| beta_low                       | low_idio_volatility            |        71 |           0.4363 |
| ebitda_ev_yield                | low_leverage                   |        77 |           0.4248 |
| earnings_yield                 | dividend_yield                 |        63 |           0.4205 |
| ebitda_ev_yield                | gross_profitability            |        51 |           0.4129 |
| gross_profitability            | low_total_volatility           |        51 |           0.381  |
| book_to_market                 | small_size                     |        63 |           0.3794 |
| operating_profitability_approx | gross_profitability            |        51 |           0.367  |
| gross_profitability            | low_idio_volatility            |        51 |           0.3653 |
| gross_profitability            | beta_low                       |        51 |           0.3641 |
| gross_profitability            | roe_standalone                 |        51 |           0.3567 |
| size_log_mcap                  | roa_standalone                 |        63 |           0.3524 |
| size_log_mcap                  | piotroski_lite                 |        63 |           0.3493 |
| earnings_yield                 | piotroski_lite                 |        63 |           0.3346 |
| roa_standalone                 | piotroski_lite                 |        77 |           0.3191 |
| cashflow_price                 | piotroski_lite                 |        51 |           0.3173 |
| piotroski_lite                 | low_idio_volatility            |        71 |           0.3156 |
| size_log_mcap                  | roe_standalone                 |        63 |           0.3114 |
| roa_standalone                 | low_idio_volatility            |        71 |           0.3067 |
| size_log_mcap                  | gross_profitability            |        51 |           0.3003 |
| piotroski_lite                 | low_total_volatility           |        71 |           0.2968 |
| book_to_market                 | low_leverage                   |        63 |           0.2953 |
| momentum_12_1                  | beta_high                      |        64 |           0.2864 |
| earnings_yield                 | gross_profitability            |        51 |           0.2787 |
| roa_standalone                 | low_total_volatility           |        71 |           0.262  |
| earnings_yield                 | roa_standalone                 |        63 |           0.2609 |
| cashflow_price                 | sales_price                    |        51 |           0.2585 |
| earnings_yield                 | book_to_market                 |        63 |           0.2437 |
| earnings_yield                 | momentum_12_1                  |        63 |           0.2388 |
| earnings_yield                 | ebitda_ev_yield                |        63 |           0.2335 |
| gross_profitability            | accrual_quality                |        51 |           0.2333 |
| dividend_yield                 | gross_profitability            |        51 |           0.2311 |
| sales_price                    | beta_high                      |        63 |           0.2276 |
| ebitda_ev_yield                | momentum_12_1                  |        64 |           0.2272 |
| earnings_yield                 | low_leverage                   |        63 |           0.2272 |
| size_log_mcap                  | operating_profitability_approx |        63 |           0.2248 |
| roe_standalone                 | piotroski_lite                 |        77 |           0.2247 |
| ebitda_ev_yield                | roa_standalone                 |        77 |           0.2238 |
| accrual_quality                | piotroski_lite                 |        51 |           0.2233 |
| roe_standalone                 | low_idio_volatility            |        71 |           0.2182 |
| operating_profitability_approx | piotroski_lite                 |        77 |           0.2086 |
| small_size                     | momentum_12_1                  |        63 |           0.2058 |
| momentum_6_1                   | beta_high                      |        70 |           0.2052 |
| book_to_market                 | momentum_12_1                  |        63 |           0.2004 |
| dividend_yield                 | low_leverage                   |        63 |           0.1928 |
| sales_price                    | low_leverage                   |        63 |           0.1924 |
| piotroski_lite                 | low_leverage                   |        77 |           0.1883 |
| gross_profitability            | piotroski_lite                 |        51 |           0.1877 |
| earnings_yield                 | roe_standalone                 |        63 |           0.187  |
| ebitda_ev_yield                | momentum_6_1                   |        70 |           0.1856 |
| dividend_yield                 | roe_standalone                 |        63 |           0.1776 |
| roe_standalone                 | low_total_volatility           |        71 |           0.1736 |
| book_to_market                 | momentum_6_1                   |        63 |           0.1734 |
| small_size                     | beta_high                      |        63 |           0.1713 |
| size_log_mcap                  | beta_low                       |        63 |           0.1713 |
| earnings_yield                 | momentum_6_1                   |        63 |           0.1682 |
| ebitda_ev_yield                | piotroski_lite                 |        77 |           0.1589 |
| sales_price                    | momentum_12_1                  |        63 |           0.1559 |
| dividend_yield                 | roa_standalone                 |        63 |           0.1412 |
| cashflow_price                 | momentum_12_1                  |        51 |           0.1412 |
| dividend_yield                 | momentum_12_1                  |        63 |           0.14   |
| book_to_market                 | cashflow_price                 |        51 |           0.1396 |
| roe_standalone                 | accrual_quality                |        51 |           0.1388 |
| sales_price                    | ebitda_ev_yield                |        63 |           0.1365 |
| operating_profitability_approx | low_idio_volatility            |        71 |           0.1352 |
| roa_standalone                 | conservative_investment        |        75 |           0.1347 |
| dividend_yield                 | sales_price                    |        63 |           0.1338 |
| dividend_yield                 | beta_low                       |        63 |           0.1335 |
| earnings_yield                 | operating_profitability_approx |        63 |           0.1325 |
| dividend_yield                 | operating_profitability_approx |        63 |           0.1324 |
| ebitda_ev_yield                | small_size                     |        63 |           0.1319 |
| small_size                     | momentum_6_1                   |        63 |           0.1272 |
| roe_standalone                 | conservative_investment        |        75 |           0.1265 |
| roa_standalone                 | accrual_quality                |        51 |           0.1255 |
| cashflow_price                 | beta_high                      |        51 |           0.1246 |
| ebitda_ev_yield                | operating_profitability_approx |        77 |           0.1233 |
| earnings_yield                 | beta_low                       |        63 |           0.1226 |
| accrual_quality                | conservative_investment        |        51 |           0.1217 |
| low_leverage                   | momentum_12_1                  |        64 |           0.1215 |
| piotroski_lite                 | beta_low                       |        71 |           0.1205 |
| earnings_yield                 | low_total_volatility           |        63 |           0.1202 |
| ebitda_ev_yield                | beta_high                      |        71 |           0.1199 |
| earnings_yield                 | cashflow_price                 |        51 |           0.1118 |
| earnings_yield                 | low_idio_volatility            |        63 |           0.1055 |
| low_leverage                   | momentum_6_1                   |        70 |           0.1032 |
| dividend_yield                 | ebitda_ev_yield                |        63 |           0.1011 |
| roa_standalone                 | beta_low                       |        71 |           0.0998 |
| size_log_mcap                  | accrual_quality                |        51 |           0.0971 |
| operating_profitability_approx | low_total_volatility           |        71 |           0.0956 |
| book_to_market                 | beta_high                      |        63 |           0.0944 |
| cashflow_price                 | momentum_6_1                   |        51 |           0.0943 |
| cashflow_price                 | small_size                     |        51 |           0.0932 |
| gross_profitability            | low_leverage                   |        51 |           0.0932 |
| sales_price                    | momentum_6_1                   |        63 |           0.0896 |
| earnings_yield                 | size_log_mcap                  |        63 |           0.0881 |
| dividend_yield                 | small_size                     |        63 |           0.0833 |
| operating_profitability_approx | conservative_investment        |        75 |           0.0818 |
| cashflow_price                 | ebitda_ev_yield                |        51 |           0.0788 |
| piotroski_lite                 | momentum_12_1                  |        64 |           0.077  |
| ebitda_ev_yield                | roe_standalone                 |        77 |           0.0689 |
| short_reversal                 | beta_low                       |        71 |           0.0677 |
| earnings_yield                 | sales_price                    |        63 |           0.0676 |
| book_to_market                 | ebitda_ev_yield                |        63 |           0.0649 |
| short_reversal                 | low_total_volatility           |        71 |           0.0607 |
| ebitda_ev_yield                | accrual_quality                |        51 |           0.0587 |
| short_reversal                 | low_idio_volatility            |        71 |           0.0569 |
| book_to_market                 | dividend_yield                 |        63 |           0.0565 |
| dividend_yield                 | cashflow_price                 |        51 |           0.0564 |
| dividend_yield                 | low_total_volatility           |        63 |           0.0525 |

## Orthogonalized IC

| sample         | signal                                          | definition                                                                                        | horizon   |   periods |   pairs |   mean_ic |   median_ic |   ic_std |   hit_rate |   hac_t_stat |   pvalue | base_signal                    |
|:---------------|:------------------------------------------------|:--------------------------------------------------------------------------------------------------|:----------|----------:|--------:|----------:|------------:|---------:|-----------:|-------------:|---------:|:-------------------------------|
| orthogonalized | earnings_yield__net_bm                          | Net income / market cap; negative earnings retained; orthogonalized to B/M                        | 6m        |        44 |    2170 |   -0.0277 |     -0.0431 |   0.1638 |     0.4545 |      -1.0503 |   0.2936 | earnings_yield                 |
| orthogonalized | earnings_yield__net_bm_size_liq                 | Net income / market cap; negative earnings retained; orthogonalized to B/M+size+liquidity         | 6m        |        33 |    2036 |   -0.0435 |     -0.0501 |   0.1211 |     0.3636 |      -1.9042 |   0.0569 | earnings_yield                 |
| orthogonalized | dividend_yield__net_bm                          | Dividends / market cap; fallback stored Dividend_Yield; orthogonalized to B/M                     | 6m        |        44 |    2007 |   -0.0268 |     -0.0334 |   0.2358 |     0.3864 |      -0.457  |   0.6477 | dividend_yield                 |
| orthogonalized | dividend_yield__net_bm_size_liq                 | Dividends / market cap; fallback stored Dividend_Yield; orthogonalized to B/M+size+liquidity      | 6m        |        31 |    1862 |   -0.0561 |     -0.0454 |   0.1472 |     0.3548 |      -1.2531 |   0.2102 | dividend_yield                 |
| orthogonalized | cashflow_price__net_bm                          | Operating cash flow / market cap; orthogonalized to B/M                                           | 6m        |        44 |    2139 |    0.0738 |      0.0985 |   0.1693 |     0.7955 |       1.9401 |   0.0524 | cashflow_price                 |
| orthogonalized | cashflow_price__net_bm_size_liq                 | Operating cash flow / market cap; orthogonalized to B/M+size+liquidity                            | 6m        |        33 |    2005 |    0.0859 |      0.0817 |   0.1284 |     0.9091 |       3.8994 |   0.0001 | cashflow_price                 |
| orthogonalized | sales_price__net_bm                             | Revenue / market cap; orthogonalized to B/M                                                       | 6m        |        44 |    2170 |    0.059  |      0.0895 |   0.2199 |     0.6136 |       1.0068 |   0.314  | sales_price                    |
| orthogonalized | sales_price__net_bm_size_liq                    | Revenue / market cap; orthogonalized to B/M+size+liquidity                                        | 6m        |        33 |    2036 |    0.0174 |      0.066  |   0.1526 |     0.6364 |       0.409  |   0.6825 | sales_price                    |
| orthogonalized | ebitda_ev_yield__net_bm                         | EBITDA / enterprise value; orthogonalized to B/M                                                  | 6m        |        44 |    1897 |    0.0126 |      0.0306 |   0.2379 |     0.6591 |       0.2268 |   0.8206 | ebitda_ev_yield                |
| orthogonalized | ebitda_ev_yield__net_bm_size_liq                | EBITDA / enterprise value; orthogonalized to B/M+size+liquidity                                   | 6m        |        33 |    1763 |    0.076  |      0.0851 |   0.1081 |     0.8182 |       3.7448 |   0.0002 | ebitda_ev_yield                |
| orthogonalized | small_size__net_bm                              | -log(MarketCap); orthogonalized to B/M                                                            | 6m        |        44 |    2170 |    0.0623 |      0.0848 |   0.2156 |     0.5455 |       1.0634 |   0.2876 | small_size                     |
| orthogonalized | small_size__net_bm_size_liq                     | -log(MarketCap); orthogonalized to B/M+size+liquidity                                             | 6m        |        33 |    2036 |    0.0725 |      0.081  |   0.214  |     0.6061 |       1.9227 |   0.0545 | small_size                     |
| orthogonalized | size_log_mcap__net_bm                           | log(MarketCap); orthogonalized to B/M                                                             | 6m        |        44 |    2170 |   -0.0623 |     -0.0848 |   0.2156 |     0.4545 |      -1.0634 |   0.2876 | size_log_mcap                  |
| orthogonalized | size_log_mcap__net_bm_size_liq                  | log(MarketCap); orthogonalized to B/M+size+liquidity                                              | 6m        |        33 |    2036 |   -0.0652 |     -0.0907 |   0.2266 |     0.3939 |      -0.9028 |   0.3667 | size_log_mcap                  |
| orthogonalized | operating_profitability_approx__net_bm          | Operating income / book equity; ROE fallback for financials; orthogonalized to B/M                | 6m        |        44 |    2064 |    0.0485 |      0.084  |   0.1871 |     0.6364 |       0.9275 |   0.3536 | operating_profitability_approx |
| orthogonalized | operating_profitability_approx__net_bm_size_liq | Operating income / book equity; ROE fallback for financials; orthogonalized to B/M+size+liquidity | 6m        |        31 |    1919 |    0.0826 |      0.0941 |   0.1059 |     0.7742 |       3.2    |   0.0014 | operating_profitability_approx |
| orthogonalized | gross_profitability__net_bm                     | Gross profit / total assets; orthogonalized to B/M                                                | 6m        |        31 |    1537 |   -0.0985 |     -0.1233 |   0.1663 |     0.1935 |      -2.022  |   0.0432 | gross_profitability            |
| orthogonalized | gross_profitability__net_bm_size_liq            | Gross profit / total assets; orthogonalized to B/M+size+liquidity                                 | 6m        |        31 |    1535 |   -0.0922 |     -0.1387 |   0.1344 |     0.1935 |      -2.3132 |   0.0207 | gross_profitability            |
| orthogonalized | roe_standalone__net_bm                          | Net income / book equity or stored ROE; orthogonalized to B/M                                     | 6m        |        44 |    2170 |   -0.048  |     -0.0431 |   0.1578 |     0.4545 |      -1.0138 |   0.3107 | roe_standalone                 |
| orthogonalized | roe_standalone__net_bm_size_liq                 | Net income / book equity or stored ROE; orthogonalized to B/M+size+liquidity                      | 6m        |        33 |    2036 |    0.0043 |      0.018  |   0.1211 |     0.5758 |       0.1094 |   0.9129 | roe_standalone                 |
| orthogonalized | roa_standalone__net_bm                          | Net income / total assets or stored ROA; orthogonalized to B/M                                    | 6m        |        44 |    2170 |   -0.089  |     -0.0816 |   0.2927 |     0.3409 |      -1.0845 |   0.2781 | roa_standalone                 |
| orthogonalized | roa_standalone__net_bm_size_liq                 | Net income / total assets or stored ROA; orthogonalized to B/M+size+liquidity                     | 6m        |        33 |    2036 |   -0.019  |     -0.0477 |   0.1892 |     0.303  |      -0.4431 |   0.6577 | roa_standalone                 |
| orthogonalized | accrual_quality__net_bm                         | -(Net income - CFO) / assets; orthogonalized to B/M                                               | 6m        |        44 |    2139 |    0.0016 |      0.0421 |   0.2158 |     0.6364 |       0.0264 |   0.9789 | accrual_quality                |
| orthogonalized | accrual_quality__net_bm_size_liq                | -(Net income - CFO) / assets; orthogonalized to B/M+size+liquidity                                | 6m        |        33 |    2005 |    0.0891 |      0.0954 |   0.1074 |     0.7879 |       2.7558 |   0.0059 | accrual_quality                |
| orthogonalized | piotroski_lite__net_bm                          | Existing PIT Piotroski-lite score; orthogonalized to B/M                                          | 6m        |        44 |    2170 |   -0.0732 |     -0.0103 |   0.2074 |     0.4091 |      -1.3729 |   0.1698 | piotroski_lite                 |
| orthogonalized | piotroski_lite__net_bm_size_liq                 | Existing PIT Piotroski-lite score; orthogonalized to B/M+size+liquidity                           | 6m        |        33 |    2036 |   -0.0317 |     -0.0179 |   0.1207 |     0.4242 |      -1.1529 |   0.2489 | piotroski_lite                 |
| orthogonalized | conservative_investment__net_bm                 | -asset growth; orthogonalized to B/M                                                              | 6m        |        32 |    2035 |    0.0481 |      0.0597 |   0.1176 |     0.7188 |       1.5995 |   0.1097 | conservative_investment        |
| orthogonalized | conservative_investment__net_bm_size_liq        | -asset growth; orthogonalized to B/M+size+liquidity                                               | 6m        |        31 |    2012 |    0.0164 |     -0.0048 |   0.1198 |     0.4839 |       0.4922 |   0.6226 | conservative_investment        |
| orthogonalized | low_leverage__net_bm                            | -debt/assets; orthogonalized to B/M                                                               | 6m        |        44 |    2170 |    0.0141 |      0.0206 |   0.2085 |     0.5455 |       0.3502 |   0.7262 | low_leverage                   |
| orthogonalized | low_leverage__net_bm_size_liq                   | -debt/assets; orthogonalized to B/M+size+liquidity                                                | 6m        |        33 |    2036 |    0.0062 |      0.0252 |   0.1256 |     0.5758 |       0.1957 |   0.8448 | low_leverage                   |
| orthogonalized | momentum_12_1__net_bm                           | prior 252 trading-day return skipping 21 days; orthogonalized to B/M                              | 6m        |        44 |    1492 |    0.0568 |      0.113  |   0.3158 |     0.6136 |       0.8258 |   0.4089 | momentum_12_1                  |
| orthogonalized | momentum_12_1__net_bm_size_liq                  | prior 252 trading-day return skipping 21 days; orthogonalized to B/M+size+liquidity               | 6m        |        22 |    1259 |    0.0609 |      0.1338 |   0.1967 |     0.5909 |       0.8349 |   0.4038 | momentum_12_1                  |
| orthogonalized | momentum_6_1__net_bm                            | prior 126 trading-day return skipping 21 days; orthogonalized to B/M                              | 6m        |        44 |    1776 |    0.0356 |      0.0959 |   0.2875 |     0.6818 |       0.5882 |   0.5564 | momentum_6_1                   |
| orthogonalized | momentum_6_1__net_bm_size_liq                   | prior 126 trading-day return skipping 21 days; orthogonalized to B/M+size+liquidity               | 6m        |        24 |    1554 |    0.0494 |      0.0769 |   0.1842 |     0.625  |       0.805  |   0.4208 | momentum_6_1                   |
| orthogonalized | short_reversal__net_bm                          | -prior 21 trading-day return; orthogonalized to B/M                                               | 6m        |        44 |    2048 |   -0.0005 |     -0.0528 |   0.2937 |     0.4545 |      -0.0087 |   0.9931 | short_reversal                 |
| orthogonalized | short_reversal__net_bm_size_liq                 | -prior 21 trading-day return; orthogonalized to B/M+size+liquidity                                | 6m        |        32 |    1909 |   -0.0482 |     -0.0748 |   0.187  |     0.375  |      -1.3454 |   0.1785 | short_reversal                 |
| orthogonalized | beta_high__net_bm                               | market beta over 252 days; orthogonalized to B/M                                                  | 6m        |        44 |    1832 |    0.1116 |      0.1194 |   0.2628 |     0.7045 |       1.5866 |   0.1126 | beta_high                      |
| orthogonalized | beta_high__net_bm_size_liq                      | market beta over 252 days; orthogonalized to B/M+size+liquidity                                   | 6m        |        26 |    1631 |    0.1434 |      0.2108 |   0.2465 |     0.7692 |       1.5996 |   0.1097 | beta_high                      |
| orthogonalized | beta_low__net_bm                                | -market beta over 252 days; orthogonalized to B/M                                                 | 6m        |        44 |    1832 |   -0.1116 |     -0.1194 |   0.2628 |     0.2955 |      -1.5866 |   0.1126 | beta_low                       |
| orthogonalized | beta_low__net_bm_size_liq                       | -market beta over 252 days; orthogonalized to B/M+size+liquidity                                  | 6m        |        26 |    1631 |   -0.1434 |     -0.2108 |   0.2465 |     0.2308 |      -1.5996 |   0.1097 | beta_low                       |
| orthogonalized | low_total_volatility__net_bm                    | -annualized realized volatility; orthogonalized to B/M                                            | 6m        |        44 |    1832 |   -0.1298 |     -0.1427 |   0.183  |     0.2727 |      -2.8566 |   0.0043 | low_total_volatility           |
| orthogonalized | low_total_volatility__net_bm_size_liq           | -annualized realized volatility; orthogonalized to B/M+size+liquidity                             | 6m        |        26 |    1631 |   -0.1199 |     -0.1228 |   0.1775 |     0.1923 |      -2.07   |   0.0385 | low_total_volatility           |
| orthogonalized | low_idio_volatility__net_bm                     | -market-model residual volatility; orthogonalized to B/M                                          | 6m        |        44 |    1832 |   -0.1337 |     -0.1818 |   0.1795 |     0.25   |      -3.202  |   0.0014 | low_idio_volatility            |
| orthogonalized | low_idio_volatility__net_bm_size_liq            | -market-model residual volatility; orthogonalized to B/M+size+liquidity                           | 6m        |        26 |    1631 |   -0.1144 |     -0.1168 |   0.1636 |     0.2692 |      -2.1692 |   0.0301 | low_idio_volatility            |

## Family Incremental Regressions

| signal                         |   periods |   mean_coef |   hac_t_stat |   avg_n | family                |
|:-------------------------------|----------:|------------:|-------------:|--------:|:----------------------|
| book_to_market                 |        31 |     -0.0045 |      -0.077  | 50.9677 | value                 |
| cashflow_price                 |        31 |      0.081  |       5.2923 | 50.9677 | value                 |
| dividend_yield                 |        31 |     -0.0756 |      -2.2047 | 50.9677 | value                 |
| earnings_yield                 |        31 |     -0.0555 |      -1.5155 | 50.9677 | value                 |
| ebitda_ev_yield                |        31 |     -0.0003 |      -0.0123 | 50.9677 | value                 |
| sales_price                    |        31 |      0.0457 |       1.9858 | 50.9677 | value                 |
| accrual_quality                |        31 |      0.0205 |       1.1398 | 45.5806 | profitability_quality |
| gross_profitability            |        31 |     -0.0553 |      -3.048  | 45.5806 | profitability_quality |
| operating_profitability_approx |        31 |      0.0263 |       1.6136 | 45.5806 | profitability_quality |
| piotroski_lite                 |        31 |     -0.0105 |      -0.495  | 45.5806 | profitability_quality |
| roa_standalone                 |        31 |      0.016  |       0.4195 | 45.5806 | profitability_quality |
| roe_standalone                 |        31 |     -0.0603 |      -1.7192 | 45.5806 | profitability_quality |
| conservative_investment        |        44 |      0.0195 |       1.9058 | 48.7045 | investment            |
| beta_high                      |        40 |      0.1019 |       1.3828 | 44.8    | risk                  |
| beta_low                       |        40 |     -0.1019 |      -1.3828 | 44.8    | risk                  |
| low_idio_volatility            |        40 |     -0.3347 |      -0.4445 | 44.8    | risk                  |
| low_total_volatility           |        40 |      0.4464 |       0.5271 | 44.8    | risk                  |
| small_size                     |        40 |      0.0677 |       3.8312 | 44.8    | risk                  |
| momentum_12_1                  |        56 |      0.0422 |       1.1742 | 28.125  | market_behavior       |
| momentum_6_1                   |        56 |     -0.0122 |      -0.2982 | 28.125  | market_behavior       |
| short_reversal                 |        56 |     -0.0199 |      -1.4199 | 28.125  | market_behavior       |
