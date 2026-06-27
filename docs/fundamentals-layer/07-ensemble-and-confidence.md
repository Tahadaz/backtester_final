# Ensemble and confidence

After the valuation models run, the engine collapses usable non-diagnostic model outputs into one fair-value range. Brief 34 removed base model weights, family caps, proxy weight caps, and price-anchored implied-price clamps from the ensemble.

## Number Discipline

Every number used by the ensemble must be one of three classes:

| Class | Meaning | Examples |
|---|---|---|
| Observed | Reported in the snapshot/history or peer cohort | current price, shares, FCF history, sector peer medians |
| Derived | Computed from observed rows by a deterministic formula | WACC, cost of equity, trailing averages, mid-cycle medians |
| Registry assumption | Explicit in `DEFAULT_ASSUMPTIONS` with metadata | outlier MAD k, confidence weights, rating thresholds |

Missing operational drivers do not receive placeholder constants. The projection layer tries observed history, then same-sector peer medians from `stock_master.sector`, then emits an unavailable warning. Dependent valuation models return `fair_value=None` when required drivers are unavailable.

## Survivor Set

Reverse DCF is always diagnostic and never enters the ensemble. A non-diagnostic model survives only when:

- `fair_value` is finite and positive.
- `current_price` is present.
- `confidence` is one of `high`, `medium`, or `low`.
- No structural gate marks the result unusable, such as non-positive equity value, `g >= r`, or an invalid dividend-yield input.

Every unavailable model still persists with `confidence="unavailable"` and a human-readable warning reason.

## Method Classes

The ensemble treats intrinsic valuation and market-relative valuation as two co-equal method classes:

| Class | Models | Role |
|---|---|---|
| Intrinsic | `fcff_dcf`, `fcfe_dcf`, `ddm`, `residual_income`, `justified_multiples` | Own-fundamentals valuation driven by cash flow, dividends, book value, ROE, cost of capital, and growth. |
| Market / relative | `relative_multiples` | Peer-multiple market reality check. |

`justified_multiples` is in the intrinsic class for ensemble rejection because it is derived from ROE / cost of equity / growth, even though its output family remains relative for display taxonomy.

## Outlier Rejection

The ensemble applies robust outlier rejection within each method class only:

```text
for each method class:
  center = median(class candidate fair values)
  if class_candidate_count >= 3:
    keep values inside center +/- ensemble_outlier_mad_k * 1.4826 * MAD
  else:
    keep the class values unless a structural availability gate already removed them
```

The default `ensemble_outlier_mad_k` is a registry policy value. A coherent `relative_multiples` value is not rejected merely because it differs from a tight intrinsic cluster. Structural gates still run first: non-positive values, invalid `g >= r` paths, and severe model-quality warnings remain unavailable rather than being blended.

## Combiner

Surviving models receive equal inclusion weight, while the headline reconciles method classes:

```text
intrinsic_rep = median(surviving intrinsic fair values), if any
market_rep = median(surviving market fair values), if any
fair_value_base = median(available method-class representatives)
fair_value_mean = mean(surviving fair values)        # diagnostic
model_weights[model] = 1 / surviving_model_count
```

With both classes present, the headline is the midpoint of the intrinsic representative and the market representative. This gives comps a voice without making it the sole answer. The low/high model-dispersion band is Q1/Q3 when at least four models survive, otherwise min/max of survivors. The Monte Carlo band is still persisted and recentered on the method-class headline for display.

## Headline Review Gate

The ensemble never clamps to market price. Instead, it withholds a headline for review when both conditions hold:

```text
abs(upside) breaches the registry review bounds
and model coverage or method-class agreement is weak
```

Default registry bounds are `headline_review_upside_ceiling = +150%` and `headline_review_downside_floor = -95%`. Coverage reuses the ensemble confidence target model count; method-class agreement is the robust agreement score across the available class representatives. A genuine extreme where intrinsic and market classes agree can still publish. A thin or method-conflicted extreme returns no headline fair value / upside and carries a `headline_review_required_extreme_*` warning, so the API recommendation routes to NR/review.

## Confidence

Ensemble confidence is additive, not a weighted-model average and not multiplied by a dispersion floor:

```text
coverage = min(1, usable_model_count / ensemble_confidence_target_models)
agreement = 1 - robust_model_dispersion_cv
data_quality = mean(observed_input_fraction per survivor)

confidence_score =
    coverage_weight * coverage
  + agreement_weight * agreement
  + data_quality_weight * data_quality
```

Default registry weights are 35% coverage, 35% agreement, and 30% data quality. Proxy warnings, peer-median inputs, unavailable-driver warnings, and integrity warnings reduce observed-input quality. Sector never grants a confidence floor by itself.

## Rating Gate

The API derives the research-ticket recommendation from the base ensemble only. Bear and bull scenarios remain detail views.

Ratings require:

- at least 3 usable valuation models,
- confidence >= `rating_confidence_min`,
- agreement >= `rating_agreement_min`,
- target, current price, and cost of equity.

The ladder compares expected total return with required return:

```text
expected_total_return = target / current_price - 1 + forward_dividend_yield
excess_return = expected_total_return - cost_of_equity
```

| Excess return | Rating |
|---:|---|
| `> rating_buy_excess_return` | BUY |
| `>= rating_accumulate_excess_return` | ACCUMULATE |
| `>= rating_reduce_excess_return` | HOLD |
| `>= rating_sell_excess_return` | REDUCE |
| below sell threshold | SELL |

If any gate fails, the recommendation is `NR`.

## Scenario Coherence

Display-facing valuation refreshes compute bear, base, and bull together from one snapshot and persist the trio with one shared `computed_at` vintage. The API serves the scenario band only when all three rows share that vintage and satisfy `bear <= base <= bull` where all three fair values are numeric.

If the stored trio is incomplete, mixed-vintage, or unordered, the read path returns the base scenario only and sets `scenario_trio_stale=true`. The headline recommendation and target remain base-anchored throughout.

## Debug Checklist

1. Check unavailable model warnings first; missing inputs should read as unavailable, not zero.
2. Inspect `model_weights_json`; survivors should have equal weights.
3. Inspect `warnings_json` for `<model>_excluded_cross_model_outlier`; rejection should be within method class, not because comps differs from intrinsic.
4. Compare `fair_value_base` with `fair_value_mean`; large gaps can mean the class-representative headline is reconciling a market/intrinsic disagreement.
5. For no-rating cases, check usable model count, confidence, agreement, and cost-of-equity availability.

## See also

- [06-valuation-models.md](06-valuation-models.md)
- [08-assumptions-and-defaults.md](08-assumptions-and-defaults.md)
- [12-known-issues-and-limitations.md](12-known-issues-and-limitations.md)
