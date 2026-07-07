# B/M Vs CF/P Final Comparison

Generated: 2026-07-06T15:49:27.970873+00:00

## Pairwise Common

| sample          | signal         | definition   | horizon   |   periods |   pairs |   mean_ic |   median_ic |   ic_std |   hit_rate |   hac_t_stat |   pvalue |   top_bottom_spread |   net_sharpe |   max_drawdown |   turnover |
|:----------------|:---------------|:-------------|:----------|----------:|--------:|----------:|------------:|---------:|-----------:|-------------:|---------:|--------------------:|-------------:|---------------:|-----------:|
| pairwise_common | book_to_market | B/M          | 6m        |        44 |    2139 |    0.1979 |      0.2105 |   0.2328 |     0.7955 |       2.8668 |   0.0041 |              0.1023 |       0.7403 |        -0.8745 |     0.0685 |
| pairwise_common | cashflow_price | CF/P         | 6m        |        44 |    2139 |    0.1467 |      0.1329 |   0.1379 |     0.8864 |       5.8144 |   0      |              0.1035 |       1.0634 |        -0.6233 |     0.0988 |

## Correlation

| left           | right          |   periods |   mean_rank_corr |
|:---------------|:---------------|----------:|-----------------:|
| book_to_market | cashflow_price |        51 |           0.1396 |
