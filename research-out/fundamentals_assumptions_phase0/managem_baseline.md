# Phase 0 Managem Baseline

- Generated at: `2026-06-03T13:43:31.768619+00:00`
- Git commit: `d8f2650e7765cee1c7fd2160ba54d8262cfa9a41`
- Symbol: `MNG` (Managem)
- Scenario: `base`
- Engine: `in_memory_recompute_path`
- Import ID: `46bd54cb-7a48-440e-8a5b-647079665837`
- Current price: `17743`

## Key Assumptions

| Field | Value | Provenance |
|---|---:|---|
| `terminal_growth` | `0.025` | `default` |
| `terminal_growth_firm` | `0.035` | `computed_from_fundamentals` |
| `terminal_growth_equity` | `0.035` | `computed_from_fundamentals` |
| `year1_revenue_growth` | `0.334789` | `projection` |

## Per-Model Fair Values

| Model | Fair value | Current price | Upside | Confidence |
|---|---:|---:|---:|---|
| `ddm` | `955.356` | `17743` | `-0.946156` | `medium` |
| `residual_income` | `3584.93` | `17743` | `-0.797952` | `low` |
| `fcff_dcf` | `3977.25` | `17743` | `-0.775841` | `low` |
| `fcfe_dcf` | `4383.79` | `17743` | `-0.752928` | `low` |
| `justified_multiples` | `12022.5` | `17743` | `-0.322411` | `low` |
| `relative_multiples` | `10615.4` | `17743` | `-0.401712` | `low` |
| `reverse_dcf` | `-` | `17743` | `-` | `medium` |

## Ensemble

| Low | Base | High | Mean | Usable models | Confidence |
|---:|---:|---:|---:|---:|---:|
| `-` | `-` | `-` | `8125.65` | `6` | `0.0418791` |

## Revenue Growth Driver

```json
{
  "anchor_value": 0.12392017399786281,
  "divergence": 0.21086877274326332,
  "historical_series": [
    {
      "value": 0.2994018429703078,
      "year": 2022
    },
    {
      "value": -0.22162319080993653,
      "year": 2023
    },
    {
      "value": 0.18005754169108634,
      "year": 2024
    },
    {
      "value": 0.5456577194843895,
      "year": 2025
    }
  ],
  "inputs": {
    "blend_weight_cagr": 0.5,
    "blend_weight_last_year": 0.5,
    "cagr_3y": 0.12392017399786281,
    "growth_bound_method": "winsorized_peak_yoy_90th_percentile",
    "historical_growth_upper_bound": 0.5456577194843895,
    "last_year_growth": 0.5456577194843895,
    "terminal_growth": 0.035
  },
  "method": "blend(3y revenue CAGR 12.39%, last-year growth 54.57%) fades to terminal 3.50%",
  "name": "revenue_growth",
  "projected_by_year": {
    "2026": 0.33478894674112614,
    "2027": 0.2598417100558446,
    "2028": 0.18489447337056308,
    "2029": 0.10994723668528156,
    "2030": 0.03500000000000003
  },
  "warning": "revenue_growth_diverges_from_history"
}
```
