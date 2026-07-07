# Incremental Information Analysis

Generated: 2026-07-06T14:29:58.970220+00:00

## Pairwise Rank Correlations

| left                      | right                |   periods |   mean_rank_corr |
|:--------------------------|:---------------------|----------:|-----------------:|
| classical_characteristics | intrinsic_valuation  |        12 |           0.1969 |
| classical_characteristics | fundamental_momentum |        12 |           0.0993 |
| classical_characteristics | residual_value       |        12 |           0.1842 |
| intrinsic_valuation       | fundamental_momentum |        12 |          -0.2885 |
| intrinsic_valuation       | residual_value       |        12 |           0.0518 |
| fundamental_momentum      | residual_value       |        12 |           0.0443 |

## Incremental Regression

| signal                    |   periods |   mean_coef |   hac_t_stat |   avg_n |
|:--------------------------|----------:|------------:|-------------:|--------:|
| classical_characteristics |        10 |     -0.0013 |      -0.0622 |    45.8 |
| fundamental_momentum      |        10 |      0.0033 |       0.1227 |    45.8 |
| intrinsic_valuation       |        10 |      0.0459 |       4.1786 |    45.8 |
| residual_value            |        10 |      0.02   |       0.6426 |    45.8 |

## Size Neutral IC

| sample              | signal                    | definition                                                                                        | horizon   |   periods |   pairs |   mean_ic |   median_ic |   ic_std |   hit_rate |   hac_t_stat |   pvalue | controls      |
|:--------------------|:--------------------------|:--------------------------------------------------------------------------------------------------|:----------|----------:|--------:|----------:|------------:|---------:|-----------:|-------------:|---------:|:--------------|
| native_size_neutral | classical_characteristics | A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components            | 1m        |        49 |    2520 |    0.0479 |      0.039  |   0.2238 |     0.5714 |       1.4003 |   0.1614 | size_log_mcap |
| native_size_neutral | classical_characteristics | A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components            | 3m        |        47 |    2380 |    0.0537 |      0.0416 |   0.2804 |     0.5745 |       0.8055 |   0.4206 | size_log_mcap |
| native_size_neutral | classical_characteristics | A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components            | 6m        |        44 |    2170 |    0.0869 |      0.0484 |   0.3262 |     0.6591 |       0.8874 |   0.3749 | size_log_mcap |
| native_size_neutral | classical_characteristics | A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components            | 12m       |        38 |    1761 |    0.1979 |      0.2223 |   0.2494 |     0.8158 |       2.3422 |   0.0192 | size_log_mcap |
| native_size_neutral | intrinsic_valuation       | B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions     | 1m        |        13 |     573 |   -0.0421 |     -0.0091 |   0.2255 |     0.4615 |      -0.6663 |   0.5052 | size_log_mcap |
| native_size_neutral | intrinsic_valuation       | B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions     | 3m        |        12 |     521 |   -0.014  |      0.0395 |   0.2394 |     0.5833 |      -0.2599 |   0.795  | size_log_mcap |
| native_size_neutral | intrinsic_valuation       | B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions     | 6m        |        11 |     474 |    0.0404 |      0.1156 |   0.1945 |     0.6364 |       1.1282 |   0.2592 | size_log_mcap |
| native_size_neutral | intrinsic_valuation       | B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions     | 12m       |         9 |     381 |    0.137  |      0.1473 |   0.1445 |     0.7778 |       4.4429 |   0      | size_log_mcap |
| native_size_neutral | fundamental_momentum      | C accounting change/improvement composite; no analyst revisions due lack of true revision history | 1m        |        49 |    2505 |   -0.0081 |     -0.0182 |   0.2323 |     0.3878 |      -0.2816 |   0.7782 | size_log_mcap |
| native_size_neutral | fundamental_momentum      | C accounting change/improvement composite; no analyst revisions due lack of true revision history | 3m        |        47 |    2365 |   -0.0578 |     -0.0393 |   0.1847 |     0.2979 |      -1.6852 |   0.092  | size_log_mcap |
| native_size_neutral | fundamental_momentum      | C accounting change/improvement composite; no analyst revisions due lack of true revision history | 6m        |        44 |    2155 |   -0.0457 |     -0.05   |   0.1886 |     0.3636 |      -1.2494 |   0.2115 | size_log_mcap |
| native_size_neutral | fundamental_momentum      | C accounting change/improvement composite; no analyst revisions due lack of true revision history | 12m       |        38 |    1746 |   -0.119  |     -0.0759 |   0.2457 |     0.2632 |      -1.7629 |   0.0779 | size_log_mcap |
| native_size_neutral | residual_value            | D cheapness residual from log(P/B) explained by ROE, revenue growth, and size                     | 1m        |        36 |    2265 |    0.0662 |      0.0802 |   0.1269 |     0.6667 |       3.0363 |   0.0024 | size_log_mcap |
| native_size_neutral | residual_value            | D cheapness residual from log(P/B) explained by ROE, revenue growth, and size                     | 3m        |        34 |    2131 |    0.0959 |      0.0576 |   0.152  |     0.6765 |       2.4209 |   0.0155 | size_log_mcap |
| native_size_neutral | residual_value            | D cheapness residual from log(P/B) explained by ROE, revenue growth, and size                     | 6m        |        31 |    1930 |    0.1174 |      0.0636 |   0.1541 |     0.7742 |       1.927  |   0.054  | size_log_mcap |
| native_size_neutral | residual_value            | D cheapness residual from log(P/B) explained by ROE, revenue growth, and size                     | 12m       |        25 |    1539 |    0.1278 |      0.0939 |   0.1764 |     0.76   |       1.4461 |   0.1481 | size_log_mcap |
