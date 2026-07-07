# Third Factor Admission Test

Generated: 2026-07-06T15:49:27.973624+00:00

## Challengers

| challenger                     |   periods |   mean_coef |   hac_t_stat |
|:-------------------------------|----------:|------------:|-------------:|
| operating_profitability_approx |        31 |      0.0581 |       3.4775 |
| conservative_investment        |        31 |      0.0177 |       2.0241 |
| sales_price                    |        33 |      0.0364 |       1.2184 |
| small_size                     |        33 |      0.0524 |       2.1091 |
| momentum_12_1                  |        22 |      0.0649 |       2.714  |
| accrual_quality                |        33 |      0.0643 |       2.0619 |
| ebitda_ev_yield                |        33 |     -0.0226 |      -1.0842 |

## Pairwise Correlations

| left                           | right                          |   periods |   mean_rank_corr |
|:-------------------------------|:-------------------------------|----------:|-----------------:|
| book_to_market                 | cashflow_price                 |        51 |           0.1396 |
| book_to_market                 | operating_profitability_approx |        63 |          -0.6956 |
| book_to_market                 | conservative_investment        |        63 |          -0.0702 |
| book_to_market                 | sales_price                    |        63 |           0.4441 |
| book_to_market                 | small_size                     |        63 |           0.3794 |
| book_to_market                 | momentum_12_1                  |        63 |           0.2004 |
| book_to_market                 | accrual_quality                |        51 |          -0.2633 |
| book_to_market                 | ebitda_ev_yield                |        63 |           0.0649 |
| cashflow_price                 | operating_profitability_approx |        51 |          -0.1152 |
| cashflow_price                 | conservative_investment        |        51 |          -0.005  |
| cashflow_price                 | sales_price                    |        51 |           0.2585 |
| cashflow_price                 | small_size                     |        51 |           0.0932 |
| cashflow_price                 | momentum_12_1                  |        51 |           0.1412 |
| cashflow_price                 | accrual_quality                |        51 |           0.5964 |
| cashflow_price                 | ebitda_ev_yield                |        51 |           0.0788 |
| operating_profitability_approx | conservative_investment        |        75 |           0.0818 |
| operating_profitability_approx | sales_price                    |        63 |          -0.2376 |
| operating_profitability_approx | small_size                     |        63 |          -0.2248 |
| operating_profitability_approx | momentum_12_1                  |        64 |          -0.0474 |
| operating_profitability_approx | accrual_quality                |        51 |           0.029  |
| operating_profitability_approx | ebitda_ev_yield                |        77 |           0.1233 |
| conservative_investment        | sales_price                    |        63 |          -0.1791 |
| conservative_investment        | small_size                     |        63 |          -0.0441 |
| conservative_investment        | momentum_12_1                  |        64 |          -0.0168 |
| conservative_investment        | accrual_quality                |        51 |           0.1217 |
| conservative_investment        | ebitda_ev_yield                |        75 |          -0.288  |
| sales_price                    | small_size                     |        63 |           0.5679 |
| sales_price                    | momentum_12_1                  |        63 |           0.1559 |
| sales_price                    | accrual_quality                |        51 |          -0.0144 |
| sales_price                    | ebitda_ev_yield                |        63 |           0.1365 |
| small_size                     | momentum_12_1                  |        63 |           0.2058 |
| small_size                     | accrual_quality                |        51 |          -0.0971 |
| small_size                     | ebitda_ev_yield                |        63 |           0.1319 |
| momentum_12_1                  | accrual_quality                |        51 |          -0.0917 |
| momentum_12_1                  | ebitda_ev_yield                |        64 |           0.2272 |
| accrual_quality                | ebitda_ev_yield                |        51 |           0.0587 |

## Decision Rule

Admit no third factor unless it is stable standalone, incremental beyond B/M+CF/P+size+liquidity, and harvestable.
