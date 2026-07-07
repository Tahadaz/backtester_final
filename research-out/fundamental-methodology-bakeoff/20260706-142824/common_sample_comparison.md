# Common Sample Comparison

Generated: 2026-07-06T14:29:58.966365+00:00

## Common IC

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

## Common Portfolio

| sample   | signal                    | definition                                                                                        | horizon   |   cost_bps |   periods |   top_bottom_spread |   gross_top_bottom_spread |   net_sharpe |   max_drawdown |   turnover |
|:---------|:--------------------------|:--------------------------------------------------------------------------------------------------|:----------|-----------:|----------:|--------------------:|--------------------------:|-------------:|---------------:|-----------:|
| common   | classical_characteristics | A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components            | 6m        |         33 |        10 |              0.0782 |                    0.081  |       1.3736 |        -0.0791 |     0.4174 |
| common   | intrinsic_valuation       | B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions     | 6m        |         33 |        10 |              0.0577 |                    0.0605 |       0.8509 |        -0.1186 |     0.4227 |
| common   | fundamental_momentum      | C accounting change/improvement composite; no analyst revisions due lack of true revision history | 6m        |         33 |        10 |             -0.0078 |                   -0.0054 |      -0.0803 |        -0.4344 |     0.369  |
| common   | residual_value            | D cheapness residual from log(P/B) explained by ROE, revenue growth, and size                     | 6m        |         33 |        10 |              0.0426 |                    0.0443 |       0.5051 |        -0.2591 |     0.2523 |

## Common Coverage

| sample   | signal                    | definition                                                                                        |   observations |   dates |   symbols |   avg_names_per_date |   financial_obs |   nonfinancial_obs |   sectors |
|:---------|:--------------------------|:--------------------------------------------------------------------------------------------------|---------------:|--------:|----------:|---------------------:|----------------:|-------------------:|----------:|
| common   | classical_characteristics | A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components            |            560 |      12 |        57 |              46.6667 |              82 |                478 |        18 |
| common   | intrinsic_valuation       | B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions     |            560 |      12 |        57 |              46.6667 |              82 |                478 |        18 |
| common   | fundamental_momentum      | C accounting change/improvement composite; no analyst revisions due lack of true revision history |            560 |      12 |        57 |              46.6667 |              82 |                478 |        18 |
| common   | residual_value            | D cheapness residual from log(P/B) explained by ROE, revenue growth, and size                     |            560 |      12 |        57 |              46.6667 |              82 |                478 |        18 |
