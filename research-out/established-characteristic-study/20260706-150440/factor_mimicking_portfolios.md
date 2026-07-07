# Canonical Factor-Mimicking Portfolio Diagnostics

Generated: 2026-07-06T15:07:30.157931+00:00

## Diagnostics

| sample       | signal                         | definition                        | horizon   |   cost_bps |   periods |   top_bottom_spread |   gross_top_bottom_spread |   net_sharpe |   max_drawdown |   turnover | factor_portfolio                  |
|:-------------|:-------------------------------|:----------------------------------|:----------|-----------:|----------:|--------------------:|--------------------------:|-------------:|---------------:|-----------:|:----------------------------------|
| factor_mimic | small_size                     | SMB_small_minus_big               | 6m        |         33 |        56 |              0.1557 |                    0.1561 |       1.0794 |        -0.6192 |     0.0532 | SMB_small_minus_big               |
| factor_mimic | book_to_market                 | HML_high_minus_low_bm             | 6m        |         33 |        44 |              0.1034 |                    0.1039 |       0.7591 |        -0.8644 |     0.0685 | HML_high_minus_low_bm             |
| factor_mimic | operating_profitability_approx | RMW_robust_minus_weak_op_prof     | 6m        |         33 |        44 |             -0.0908 |                   -0.0902 |      -1.0744 |        -0.9925 |     0.096  | RMW_robust_minus_weak_op_prof     |
| factor_mimic | conservative_investment        | CMA_conservative_minus_aggressive | 6m        |         33 |        44 |              0.0772 |                    0.0781 |       0.9042 |        -0.3526 |     0.1357 | CMA_conservative_minus_aggressive |
| factor_mimic | momentum_12_1                  | MOM_winner_minus_loser_12_1       | 6m        |         33 |        57 |              0.1436 |                    0.146  |       0.5967 |        -0.9152 |     0.3671 | MOM_winner_minus_loser_12_1       |

## Construction Caveat

These are tercile approximations, not full FF 2x3 independent sorts. Morocco breadth is too small for high-dimensional canonical sorts.
