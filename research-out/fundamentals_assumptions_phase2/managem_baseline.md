# Phase 0 Managem Baseline

- Generated at: `2026-06-03T09:41:17.356570+00:00`
- Git commit: `4f902f85728648e12dd29eb2b3466ae189a90a75`
- Symbol: `MNG` (Managem)
- Scenario: `base`
- Engine: `in_memory_recompute_path`
- Import ID: `846f85bd-100b-4322-b4f9-1f9ba5dae904`
- Current price: `17743`

## Key Assumptions

| Field | Value | Provenance |
|---|---:|---|
| `terminal_growth` | `0.025` | `default` |
| `terminal_growth_firm` | `0.01679` | `computed_from_fundamentals` |
| `terminal_growth_equity` | `0.03` | `computed_from_fundamentals` |
| `year1_revenue_growth` | `0.334789` | `projection` |

## Per-Model Fair Values

| Model | Fair value | Current price | Upside | Confidence |
|---|---:|---:|---:|---|
| `ddm` | `414.536` | `17743` | `-0.976637` | `medium` |
| `residual_income` | `-` | `17743` | `-` | `unavailable` |
| `fcff_dcf` | `0` | `17743` | `-1` | `low` |
| `fcfe_dcf` | `659.398` | `17743` | `-0.962836` | `low` |
| `justified_multiples` | `7097.2` | `17743` | `-0.6` | `low` |
| `relative_multiples` | `7097.2` | `17743` | `-0.6` | `medium` |
| `reverse_dcf` | `-` | `17743` | `-` | `medium` |

## Ensemble

| Low | Base | High | Mean | Usable models | Confidence |
|---:|---:|---:|---:|---:|---:|
| `-` | `-` | `-` | `2039.02` | `5` | `0.0503791` |

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
    "terminal_growth": 0.016789990118924094
  },
  "method": "blend(3y revenue CAGR 12.39%, last-year growth 54.57%) fades to terminal 1.68%",
  "name": "revenue_growth",
  "projected_by_year": {
    "2026": 0.33478894674112614,
    "2027": 0.2552892075855756,
    "2028": 0.1757894684300251,
    "2029": 0.0962897292744746,
    "2030": 0.01678999011892407
  },
  "warning": "revenue_growth_diverges_from_history"
}
```
