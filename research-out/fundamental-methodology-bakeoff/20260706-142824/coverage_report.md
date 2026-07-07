# Coverage Report

Generated: 2026-07-06T14:29:58.952785+00:00

## Coverage

| sample   | signal                     | definition                                                                                         |   observations |   dates |   symbols |   avg_names_per_date |   financial_obs |   nonfinancial_obs |   sectors |
|:---------|:---------------------------|:---------------------------------------------------------------------------------------------------|---------------:|--------:|----------:|---------------------:|----------------:|-------------------:|----------:|
| native   | classical_characteristics  | A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components             |           2809 |      63 |        71 |              44.5873 |             566 |               2243 |        19 |
| native   | intrinsic_valuation        | B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions      |            608 |      17 |        58 |              35.7647 |              97 |                511 |        18 |
| native   | fundamental_momentum       | C accounting change/improvement composite; no analyst revisions due lack of true revision history  |           2856 |      75 |        71 |              38.08   |             566 |               2290 |        19 |
| native   | residual_value             | D cheapness residual from log(P/B) explained by ROE, revenue growth, and size                      |           2404 |      38 |        67 |              63.2632 |             527 |               1877 |        19 |
| native   | book_to_market             | A1 PIT book equity / PIT market cap                                                                |           2622 |      63 |        67 |              41.619  |             566 |               2056 |        19 |
| native   | profitability              | A3 profitability approximation: financial ROE, non-financial operating profit/book or ROA fallback |           2881 |      77 |        71 |              37.4156 |             566 |               2315 |        19 |
| native   | investment_conservative    | A4 negative asset growth for non-financials                                                        |           2053 |      51 |        54 |              40.2549 |               0 |               2053 |        16 |
| native   | op_margin_change           | C delta operating margin                                                                           |           2499 |      50 |        68 |              49.98   |             425 |               2074 |        19 |
| native   | roe_change                 | C delta ROE                                                                                        |           2670 |      75 |        68 |              35.6    |             566 |               2104 |        19 |
| native   | roa_change                 | C delta ROA                                                                                        |           2820 |      75 |        71 |              37.6    |             566 |               2254 |        19 |
| native   | cashflow_conversion_change | C delta CFO/net-income conversion                                                                  |           2156 |      39 |        65 |              55.2821 |             518 |               1638 |        19 |
| native   | revenue_growth             | C latest revenue growth                                                                            |           2856 |      75 |        71 |              38.08   |             566 |               2290 |        19 |
| native   | earnings_growth            | C latest positive-base earnings growth                                                             |           2534 |      75 |        67 |              33.7867 |             566 |               1968 |        19 |
| native   | sfc_custom_v2              | Legacy benchmark current SFC core score                                                            |           2782 |      63 |        71 |              44.1587 |             527 |               2255 |        19 |
| common   | classical_characteristics  | A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components             |            560 |      12 |        57 |              46.6667 |              82 |                478 |        18 |
| common   | intrinsic_valuation        | B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions      |            560 |      12 |        57 |              46.6667 |              82 |                478 |        18 |
| common   | fundamental_momentum       | C accounting change/improvement composite; no analyst revisions due lack of true revision history  |            560 |      12 |        57 |              46.6667 |              82 |                478 |        18 |
| common   | residual_value             | D cheapness residual from log(P/B) explained by ROE, revenue growth, and size                      |            560 |      12 |        57 |              46.6667 |              82 |                478 |        18 |

## Publication Availability

|   total_metric_values | shares                                                                               | counts                                                       |
|----------------------:|:-------------------------------------------------------------------------------------|:-------------------------------------------------------------|
|               4637169 | {'fallback_annual_90d': 0.8799295432191494, 'publication_date': 0.12007045678085056} | {'fallback_annual_90d': 4080382, 'publication_date': 556787} |
