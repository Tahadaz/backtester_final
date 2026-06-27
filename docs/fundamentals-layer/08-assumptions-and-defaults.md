# Assumptions and defaults

The fundamentals engine resolves valuation policy from `DEFAULT_ASSUMPTIONS` in `core/quant_core/fundamentals/valuation.py`, plus database assumption overrides. Brief 34 tightened the rule for numbers: observed data first, derived data second, documented registry assumptions third. Missing operational inputs become peer-median-backed values or `unavailable`, not placeholder constants.

## Current Defaults

Key source defaults:

| Key | Default | Role |
|---|---:|---|
| `risk_free_rate` | 3.5% | BDT 10Y baseline for Moroccan cost of capital |
| `equity_risk_premium` | 6.0% | Moroccan broker-style equity risk premium |
| `country_risk_premium` | 0.0% | Set to zero because the ERP already embeds country risk |
| `cost_of_equity` | 9.5% | Default beta-1 equity discount rate, used only when no stored beta exists |
| `cost_of_equity_floor` | 6.5% | Desk minimum equity return: `risk_free_rate + 0.5 * equity_risk_premium` |
| `cost_of_debt` | 5.5% | Pre-tax MAD debt cost |
| `tax_rate` | 35.0% | Large-group Moroccan effective tax assumption |
| `wacc` | 7.7225% | 70% equity / 30% debt after-tax WACC |
| `terminal_growth` | 2.5% | Long-run Moroccan terminal growth policy |
| `forecast_years` | 5 | Explicit DCF horizon |
| `fade_years` | 5 | RI, DDM, and justified-multiple fade horizon |
| `stable_payout_ratio` | 55% | Registry fallback for invalid/missing payout in equity models |
| `maintenance_capex_pct` | 4% | Registry assumption used only where documented, including mid-cycle maintenance capex context |
| `peer_min_count` | 3 | Minimum same-sector cohort before market fallback |
| `justified_multiple_ratio_mask` | 3 | Enables P/B and P/E legs |
| `relative_multiple_ratio_mask` | 15 | Enables P/E, P/B, P/S, and EV/EBITDA legs |

The source-default cost stack was calibrated to mid-2026 Moroccan broker conventions. Display-facing revalues use the stored `fundamental_beta_history` beta for each symbol: `cost_of_equity = max(risk_free_rate + beta * equity_risk_premium, cost_of_equity_floor, risk_free_rate)`. A missing beta falls back to the documented registry beta `1.0` with `beta_source="default_beta"` and an audit warning. Database overrides can still set desk, sector, or symbol-specific rates, but the default floor is the defensive-beta 0.5 CAPM floor, not the beta-1 default CoE.

For DDM, residual income, and justified multiples, ROE is recomputed on group basis from verified raw lines: `RNPG / average group equity`. Stored `ROE` ratios are treated as observed diagnostics, not model inputs.

## Projection Drivers

Operational projection drivers do not use silent constants in model bodies:

| Driver | Resolution order |
|---|---|
| revenue growth | own observed history, then sector peer median, else unavailable |
| EBIT margin | own observed history, then sector peer median, else unavailable |
| depreciation/amortization percent | own observed history, then sector peer median, else unavailable |
| capex percent | own observed history, then sector peer median, else unavailable |
| working-capital percent | own observed history, then sector peer median, else unavailable |
| payout ratio | own observed history/snapshot, then sector peer median, else unavailable |

Peer medians are observed data from the live comparison cohort, grouped by `stock_master.sector` when the cohort is large enough. An unavailable driver sets the projection confidence cap to unavailable and makes dependent valuation models return unavailable.

## Cyclical Normalization

For cyclical or commodity-linked issuers, the engine uses mid-cycle observed history where possible:

- EBIT margin and maintenance-capex intensity can use a 5-year median.
- ROE/EBITDA normalization feeds RI, justified multiples, and relative EV/EBITDA where applicable.
- Eligibility uses `stock_master.sector` plus a small BVC registry for ambiguous materials/energy names in sectors such as `BTP`.

If there is not enough history, the model records a mid-cycle-unavailable warning instead of inventing a normal margin.

## Ensemble Policy

Brief 34 ensemble policy values are registry assumptions with metadata:

| Key | Default | Meaning |
|---|---:|---|
| `ensemble_outlier_mad_k` | 3.0 | MAD-based cross-model outlier threshold |
| `ensemble_small_sample_floor_to_median` | 0.25 | broad lower median-relative guardrail for fewer than four candidates |
| `ensemble_small_sample_ceiling_to_median` | 4.0 | broad upper median-relative guardrail for fewer than four candidates |
| `ensemble_confidence_weight_coverage` | 35% | contribution of survivor count |
| `ensemble_confidence_weight_agreement` | 35% | contribution of robust model agreement |
| `ensemble_confidence_weight_data_quality` | 30% | contribution of observed-input quality |
| `ensemble_confidence_target_models` | 5 | full-coverage survivor count |

Base model weights, relative-family caps, capex-heavy weighting knobs, and price-anchored implied-price clamps are retired.

## Rating Policy

Research overlay recommendations are derived from the base scenario:

| Key | Default | Meaning |
|---|---:|---|
| `rating_agreement_min` | 0.40 | minimum model agreement |
| `rating_confidence_min` | 0.45 | minimum ensemble confidence |
| `rating_buy_excess_return` | 10% | BUY threshold over cost of equity |
| `rating_accumulate_excess_return` | 3% | ACCUMULATE threshold over cost of equity |
| `rating_reduce_excess_return` | -3% | REDUCE threshold over cost of equity |
| `rating_sell_excess_return` | -10% | SELL threshold over cost of equity |

The ladder uses:

```text
expected_total_return = target / current_price - 1 + forward_dividend_yield
excess_return = expected_total_return - cost_of_equity
```

If a symbol lacks at least three usable models, sufficient confidence, sufficient agreement, or a usable cost of equity, the recommendation is `NR`.

## Override Hierarchy

Assumptions are resolved in this order:

1. Current per-symbol scenario override in `fundamental_assumption_override`.
2. Symbol-scoped `fundamental_assumption_set`.
3. Sector-scoped `fundamental_assumption_set`.
4. Desk/global assumption set.
5. Scenario defaults.
6. Source defaults in `DEFAULT_ASSUMPTIONS`.

Scenario probabilities are normalized after merge. Cost of equity and WACC can be recomputed from live beta/capital-structure inputs in the API service path and persisted into valuation inputs for audit.

Display-facing recompute paths resolve the active assumptions for bear, base, and bull in one atomic trio refresh. The three ensembles share one `computed_at` vintage; if a later read sees mixed vintages or an unordered trio, bear/bull are suppressed and `scenario_trio_stale=true` is returned until the trio is recomputed.

## See also

- [06-valuation-models.md](06-valuation-models.md)
- [07-ensemble-and-confidence.md](07-ensemble-and-confidence.md)
- [12-known-issues-and-limitations.md](12-known-issues-and-limitations.md)
