# Final Factor Map And Methodology Recommendation

Generated: 2026-07-06T15:07:30.162817+00:00

## Factor Tiers

| signal                         | group                 | tier                             |   mean_ic |   hac_t_stat |   fdr_qvalue |   spread |   sharpe |
|:-------------------------------|:----------------------|:---------------------------------|----------:|-------------:|-------------:|---------:|---------:|
| book_to_market                 | value                 | Tier 1 - strong candidate        |    0.1638 |       2.8134 |       0.0376 |   0.1034 |   0.7591 |
| cashflow_price                 | value                 | Tier 2 - promising but uncertain |    0.1467 |       5.8144 |       0      |   0.1035 |   1.0634 |
| low_leverage                   | distress              | Tier 4 - not supported           |    0.116  |       2.04   |       0.2377 |  -0.0197 |  -0.2167 |
| small_size                     | risk_size             | Tier 2 - promising but uncertain |    0.0839 |       1.3013 |       0.5553 |   0.1557 |   1.0794 |
| beta_high                      | risk_size             | Tier 2 - promising but uncertain |    0.0786 |       0.8596 |       0.7445 |   0.0773 |   0.4513 |
| momentum_12_1                  | market_behavior       | Tier 2 - promising but uncertain |    0.0751 |       0.6582 |       0.7445 |   0.1436 |   0.5967 |
| earnings_yield                 | value                 | Tier 4 - not supported           |    0.0674 |       1.0878 |       0.7071 |  -0.0741 |  -0.6438 |
| ebitda_ev_yield                | value                 | Tier 4 - not supported           |    0.0513 |       0.6542 |       0.7445 |  -0.0464 |  -0.5922 |
| sales_price                    | value                 | Tier 2 - promising but uncertain |    0.051  |       0.797  |       0.7445 |   0.1503 |   1.4447 |
| dividend_yield                 | value                 | Tier 4 - not supported           |    0.0395 |       0.4734 |       0.7445 |  -0.0891 |  -0.812  |
| momentum_6_1                   | market_behavior       | Tier 4 - not supported           |    0.0279 |       0.4127 |       0.7445 |   0.0466 |   0.2995 |
| operating_profitability_approx | profitability_quality | Tier 4 - not supported           |    0.0161 |       0.273  |       0.7849 |  -0.0908 |  -1.0744 |
| short_reversal                 | market_behavior       | Tier 4 - not supported           |   -0.0171 |      -0.4665 |       0.7445 |  -0.0386 |  -0.3602 |
| roa_standalone                 | profitability_quality | Tier 4 - not supported           |   -0.0207 |      -0.3172 |       0.7849 |  -0.1159 |  -1.1452 |
| piotroski_lite                 | profitability_quality | Tier 4 - not supported           |   -0.026  |      -0.4762 |       0.7445 |  -0.0412 |  -0.4384 |
| roe_standalone                 | profitability_quality | Tier 4 - not supported           |   -0.0324 |      -0.4273 |       0.7445 |  -0.1185 |  -1.1682 |
| accrual_quality                | profitability_quality | Tier 4 - not supported           |   -0.0376 |      -0.5117 |       0.7445 |   0.0392 |   0.3386 |
| conservative_investment        | investment            | Tier 4 - not supported           |   -0.057  |      -0.8597 |       0.7445 |   0.0772 |   0.9042 |
| beta_low                       | risk_size             | Tier 4 - not supported           |   -0.0786 |      -0.8596 |       0.7445 |  -0.0802 |  -0.4681 |
| size_log_mcap                  | risk_size             | Tier 4 - not supported           |   -0.0839 |      -1.3013 |       0.5553 |  -0.1564 |  -1.0835 |
| low_total_volatility           | risk_size             | Tier 4 - not supported           |   -0.1297 |      -1.6217 |       0.402  |  -0.1725 |  -1.2436 |
| low_idio_volatility            | risk_size             | Tier 4 - not supported           |   -0.1343 |      -1.8226 |       0.3145 |  -0.1689 |  -1.2321 |
| gross_profitability            | profitability_quality | Tier 4 - not supported           |   -0.1958 |      -3.2706 |       0.0123 |  -0.2175 |  -1.5245 |

## Recommendation

Preliminary rule: promote B/M from benchmark to primary standalone fundamental signal if it remains Tier 1. Use other Tier 1/Tier 2 signals only as separate sleeves when incremental regressions and orthogonalized IC support them. Do not create an equal-weight composite from weak or redundant characteristics.

## Final Interpretation

The expanded established-characteristic study does **not** support a broad equal-weight fundamental composite. The Moroccan evidence remains value-led.

### Main Findings

1. **B/M is the cleanest primary fundamental characteristic.**
   - Native 6m IC: `0.164`
   - HAC t-stat: `2.81`
   - BH-FDR q-value: `0.038`
   - Hit rate: `76.8%`
   - 6m top-bottom net spread: `10.3%`
   - Sharpe: `0.76`
   - Bucket monotonicity: bottom `9.0%`, middle `9.7%`, top `19.2%`

2. **CF/P is the strongest complementary value signal, not just a clone of B/M.**
   - Native 6m IC: `0.147`
   - HAC t-stat: `5.81`
   - BH-FDR q-value: effectively zero
   - 6m net spread: `10.4%`
   - Sharpe: `1.06`
   - Rank correlation with B/M: only `0.14`
   - Orthogonalized to B/M + size + liquidity: 6m IC `0.086`, HAC t `3.90`
   - Value-family incremental regression coefficient: `0.081`, HAC t `5.29`

3. **Sales-to-price is economically strong but statistically less clean.**
   - Native 6m IC: `0.051`, HAC t `0.80`
   - Net spread: `15.0%`, Sharpe `1.44`
   - Monotonic buckets: bottom `5.9%`, middle `13.0%`, top `19.3%`
   - Incremental value-family coefficient: `0.046`, HAC t `1.99`
   - Treat as promising, not core until confirmed.

4. **Profitability and quality do not work as standalone long-only return predictors in this sample.**
   - Operating profitability, ROE, ROA, Piotroski-lite, and gross profitability are weak or negative.
   - Gross profitability is significantly negative, not positive.
   - Accrual quality has weak native IC, but becomes positive after B/M + size + liquidity residualization; treat this as exploratory, not production-ready.

5. **Investment is not supported as an IC signal, but its portfolio spread remains interesting.**
   - Conservative investment native IC: `-0.057`
   - Net spread: `7.7%`, Sharpe `0.90`
   - Buckets are monotonic, but rank IC is wrong-signed.
   - This is a portfolio-tail effect, not a robust stock-ranking characteristic.

6. **Momentum is useful as an external benchmark, not a fundamental replacement.**
   - 12-1 momentum native IC: `0.075`, HAC t `0.66`
   - Net spread: `14.4%`, Sharpe `0.60`, high turnover `36.7%`
   - Common-sample IC is strong, but native evidence is weaker and implementation costs are higher.

7. **Small size is a real confound and possible sleeve, not a clean fundamental alpha.**
   - Small-size IC: `0.084`, HAC t `1.30`
   - Net spread: `15.6%`, Sharpe `1.08`
   - Incremental risk-family regression coefficient: `0.068`, HAC t `3.83`
   - This may be a liquidity/capacity premium; use as control and exposure limit before using as alpha.

8. **Beta/volatility results reject the low-risk anomaly in this sample.**
   - High beta has positive but weak native evidence.
   - Low volatility and low idiosyncratic volatility are wrong-signed.
   - Do not use low-risk as a Moroccan stock-selection signal from this sample.

### Architecture Recommendation

The app should not present one monolithic “fundamental score.” It should use separate, interpretable sleeves:

1. **Core Value Sleeve:** B/M.
2. **Cash-Flow Value Sleeve:** CF/P, kept separate because it is not highly redundant with B/M and survives orthogonalization.
3. **Secondary Watchlist Signals:** sales-to-price, small-size, 12-1 momentum, conservative investment tail portfolio.
4. **Diagnostics Only:** profitability, ROE, ROA, gross profitability, Piotroski-lite, dividend yield, E/P, EV/EBITDA, beta/volatility.

Do not force a composite unless a future frozen protocol shows that B/M + CF/P + one or two independent sleeves improves both IC and portfolio economics without introducing unstable exposures.

## Top Leaderboard Rows

| signal                         | group                 |   mean_ic |   hac_t_stat |   fdr_qvalue |   top_bottom_spread |   net_sharpe |   turnover | monotonic   |
|:-------------------------------|:----------------------|----------:|-------------:|-------------:|--------------------:|-------------:|-----------:|:------------|
| book_to_market                 | value                 |    0.1638 |       2.8134 |       0.0376 |              0.1034 |       0.7591 |     0.0685 | True        |
| cashflow_price                 | value                 |    0.1467 |       5.8144 |       0      |              0.1035 |       1.0634 |     0.0988 | False       |
| low_leverage                   | distress              |    0.116  |       2.04   |       0.2377 |             -0.0197 |      -0.2167 |     0.0888 | False       |
| small_size                     | risk_size             |    0.0839 |       1.3013 |       0.5553 |              0.1557 |       1.0794 |     0.0532 | True        |
| beta_high                      | risk_size             |    0.0786 |       0.8596 |       0.7445 |              0.0773 |       0.4513 |     0.2314 | False       |
| momentum_12_1                  | market_behavior       |    0.0751 |       0.6582 |       0.7445 |              0.1436 |       0.5967 |     0.3671 | True        |
| earnings_yield                 | value                 |    0.0674 |       1.0878 |       0.7071 |             -0.0741 |      -0.6438 |     0.101  | False       |
| ebitda_ev_yield                | value                 |    0.0513 |       0.6542 |       0.7445 |             -0.0464 |      -0.5922 |     0.1019 | False       |
| sales_price                    | value                 |    0.051  |       0.797  |       0.7445 |              0.1503 |       1.4447 |     0.0761 | True        |
| dividend_yield                 | value                 |    0.0395 |       0.4734 |       0.7445 |             -0.0891 |      -0.812  |     0.1123 | False       |
| momentum_6_1                   | market_behavior       |    0.0279 |       0.4127 |       0.7445 |              0.0466 |       0.2995 |     0.447  | False       |
| operating_profitability_approx | profitability_quality |    0.0161 |       0.273  |       0.7849 |             -0.0908 |      -1.0744 |     0.096  | False       |
| short_reversal                 | market_behavior       |   -0.0171 |      -0.4665 |       0.7445 |             -0.0386 |      -0.3602 |     0.8214 | False       |
| roa_standalone                 | profitability_quality |   -0.0207 |      -0.3172 |       0.7849 |             -0.1159 |      -1.1452 |     0.0658 | False       |
| piotroski_lite                 | profitability_quality |   -0.026  |      -0.4762 |       0.7445 |             -0.0412 |      -0.4384 |     0.1177 | False       |
| roe_standalone                 | profitability_quality |   -0.0324 |      -0.4273 |       0.7445 |             -0.1185 |      -1.1682 |     0.0789 | False       |
| accrual_quality                | profitability_quality |   -0.0376 |      -0.5117 |       0.7445 |              0.0392 |       0.3386 |     0.0968 | False       |
| conservative_investment        | investment            |   -0.057  |      -0.8597 |       0.7445 |              0.0772 |       0.9042 |     0.1357 | True        |
| beta_low                       | risk_size             |   -0.0786 |      -0.8596 |       0.7445 |             -0.0802 |      -0.4681 |     0.1994 | False       |
| size_log_mcap                  | risk_size             |   -0.0839 |      -1.3013 |       0.5553 |             -0.1564 |      -1.0835 |     0.047  | False       |
| low_total_volatility           | risk_size             |   -0.1297 |      -1.6217 |       0.402  |             -0.1725 |      -1.2436 |     0.1858 | False       |
| low_idio_volatility            | risk_size             |   -0.1343 |      -1.8226 |       0.3145 |             -0.1689 |      -1.2321 |     0.1552 | False       |
| gross_profitability            | profitability_quality |   -0.1958 |      -3.2706 |       0.0123 |             -0.2175 |      -1.5245 |     0.0963 | False       |
