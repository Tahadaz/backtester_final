# Market Alpha Attribution

Generated: 2026-07-06T15:49:27.968290+00:00

## Raw Market Attribution

| strategy                            |   periods |   alpha |   alpha_hac_t |    beta |     r2 |   resid_vol |
|:------------------------------------|----------:|--------:|--------------:|--------:|-------:|------------:|
| bm_top_bottom                       |        44 |  0.1161 |        2.9434 | -0.0999 | 0.0073 |      0.192  |
| cfp_top_bottom                      |        44 |  0.076  |        3.6971 |  0.2161 | 0.0673 |      0.133  |
| bm_long_top                         |        44 |  0.0606 |        2.8842 |  1.0753 | 0.7396 |      0.1051 |
| cfp_long_top                        |        44 |  0.05   |        5.1563 |  1.28   | 0.9067 |      0.0679 |
| arch_book_to_market                 |        44 |  0.1161 |        2.9434 | -0.0999 | 0.0073 |      0.192  |
| arch_cashflow_price                 |        44 |  0.076  |        3.6971 |  0.2161 | 0.0673 |      0.133  |
| arch_value_equal_rank               |        44 |  0.0897 |        3.281  |  0.009  | 0.0001 |      0.122  |
| arch_value_intersection_top_tercile |        44 |  0.0336 |        0.8965 | -0.4655 | 0.0852 |      0.2492 |
| arch_value_bm_confirmed             |        31 |  0.1857 |        1.5901 | -0.9819 | 0.1855 |      0.2819 |
| arch_value_cfp_confirmed            |        31 |  0.0931 |        2.6544 | -0.2502 | 0.0176 |      0.2103 |
| arch_value_orthogonal_combo         |        44 |  0.111  |        3.1088 | -0.095  | 0.0089 |      0.1651 |
| arch_separate_sleeves_50_50         |        44 |  0.0958 |        4.6487 |  0.0602 | 0.0123 |      0.089  |

## Risk-Free Caveat

No historical Moroccan risk-free series was available in the saved artifacts; alpha is raw return alpha versus equal-weight universe forward return.
