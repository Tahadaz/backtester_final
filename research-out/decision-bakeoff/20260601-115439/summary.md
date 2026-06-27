# TA Decision Bake-Off

Offline research run only. No application scoring behavior was changed.

## Configuration

- source: `wfo:expanded_ta_simple`
- horizon: `monthly`
- symbols: `all`
- forward horizons: `6,10,15,21`
- cost bps: `10.0`
- OOS-only rows: `True`

## Method Ranking

| rank | method | mean utility | delta vs baseline | mean IC | hit rate | coverage | folds |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | `threshold_optimized` | 0.006023 | 0.001932 | 0.0341 | 0.527 | 0.847 | 5 |
| 2 | `baseline_fixed` | 0.004091 | 0.000000 | 0.0341 | 0.520 | 0.917 | 5 |
| 3 | `isotonic_calibrated` | 0.003105 | -0.000986 | 0.0265 | 0.501 | 0.932 | 5 |
| 4 | `topsis_action` | 0.003038 | -0.001053 | 0.0368 | 0.521 | 0.537 | 5 |
| 5 | `topsis_category` | 0.001571 | -0.002520 | 0.0461 | 0.498 | 0.920 | 5 |
| 6 | `ridge_linear` | 0.000411 | -0.003680 | 0.0371 | 0.495 | 0.851 | 5 |
| 7 | `ahp_topsis_prior` | -0.000375 | -0.004467 | 0.0446 | 0.485 | 0.919 | 5 |

## Recommendation

`threshold_optimized` won this offline run. Consider app changes only after repeating on a broader sample and confirming stability.
