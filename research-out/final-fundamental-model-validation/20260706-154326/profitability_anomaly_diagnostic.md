# Profitability Anomaly Diagnostic

Generated: 2026-07-06T15:49:27.974935+00:00

## Distribution

| signal                         | raw_col                        |   count |   non_finite |     min |    p0_5 |      p1 |      p5 |   median |    p95 |    p99 |   p99_5 |    max |   negative_values |   near_zero_market_cap |   negative_book_equity |   negative_cfo |
|:-------------------------------|:-------------------------------|--------:|-------------:|--------:|--------:|--------:|--------:|---------:|-------:|-------:|--------:|-------:|------------------:|-----------------------:|-----------------------:|---------------:|
| operating_profitability_approx | operating_profitability_approx |    2754 |            0 | -2.6686 | -1.9323 | -1.6831 | -1.2631 |  -0.182  | 2.0995 | 2.389  |  2.402  | 2.4082 |              1622 |                      0 |                      0 |              0 |
| gross_profitability            | gross_profitability_raw        |    2045 |            0 | -0.1838 | -0.1838 | -0.0791 | -0.0146 |   0.2076 | 0.5063 | 1.2887 |  1.3077 | 1.3131 |               127 |                      0 |                      0 |              0 |

## Conclusion

The profitability results are best classified as accounting-comparability/confounding plus insufficient evidence. Do not flip the sign into a production alpha.

## Diagnostic Classification

Classification: C/D/E - accounting-comparability problem, confounding problem, and insufficient evidence.

Gross profitability is not admitted as a reverse signal. The negative result is surprising relative to the literature prior, but the audit shows substantial distribution asymmetry, limited coverage versus B/M, and likely sector/accounting-definition sensitivity. In this repository it is built from available fields rather than a fully audited canonical gross-profit definition across all Moroccan issuers, so the correct response is demotion, not sign flipping.

Operating profitability is also not admitted. Its raw standalone evidence was weak in the established-characteristic study, while the final gate shows a positive incremental coefficient only after B/M, CF/P, size, and liquidity controls. That pattern is consistent with suppression/confounding, not a clean production-ready profitability premium.

Production implication: show profitability measures only as diagnostics until a separate predeclared profitability study verifies field definitions, sector comparability, non-financial-only behavior, outlier influence, and standalone portfolio economics.
