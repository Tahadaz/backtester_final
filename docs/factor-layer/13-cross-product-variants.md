# 13 - Cross-Product Variants (Factor x TA)

This document defines the production Factor x TA runtime: composition semantics, naming, factor-selection gating, alignment, persistence, and replay behavior.

## Core Semantics

A Factor x TA variant is one existing TA variant AND one pre-registered macro condition.

```text
conditioned_signal[t] = ta_signal[t]  when factor_condition[t] is true
                        0.0           otherwise
```

`0.0` means HOLD/no new action. It does not invert the TA signal and it does not force an exit by itself. Existing long-only event positions remain governed by the downstream position builder, so a macro gate blocks entries without turning factor state flips into forced exits.

Implementation:
- Conditions: `core/quant_core/research/factors/conditions.py:evaluate_condition`
- Composition: `core/quant_core/research/factors/conditioned_variants.py:compose_and_signal`
- Core pipeline: `core/quant_core/signal_engine/factor_x_ta.py`

## Architecture

Factor x TA is additive. Native TA keeps using the normal `legacy` and `expanded` variants.

Runtime flow:
1. Worker/API loads stock OHLCV.
2. Worker loads pre-registered factor conditions.
3. Factor selection resolves the active top factors for `(symbol, horizon)`.
4. Stock factor config can further disable tickers.
5. Channel tags remove sector-irrelevant conditions.
6. Macro factor series are date-aligned to the stock calendar with `precede_open`.
7. For each `{TA variant, factor condition}` pair, the worker precomputes the AND-composed signal.
8. Signal Engine/WFO consume that signal via `precomputed_signal`; native Layers B-G remain family-agnostic.

The core signal module does not query the database. Runtime selection, data loading, and alignment belong to worker/API orchestration.

## Naming and Persistence

| Field | Value |
|---|---|
| `variant` | `factor_x_ta` |
| `family` | `{ta_family}@fx`, for example `sma@fx` |
| `archetype` | Same as native TA |
| `params` | Native TA params plus `factor_condition_id` |
| `variant_id` | Hash of the extended params/family |
| `description` | Native TA description plus `@{condition_id}` |
| `factor_condition` | Serialized condition metadata required for replay |

Signal Engine persists one row per `{symbol, family@fx, horizon, factor_x_ta}` in `signal_engine_family_result`.

WFO persists one row per `{symbol, category, horizon, factor_x_ta}` in `wfo_signal_summary`; fold diagnostics are stored in `folds_json`.

## Alignment Contract

All production Factor x TA factor arrays must be aligned before entering the core pipeline:

```text
align_factor_to_target(stock_close, factor_close, lag_rule="precede_open", max_staleness=3)
```

This means a macro close from day `t-1` is the earliest value available for a MASI decision on day `t`. Missing or stale factor observations become `NaN`; condition evaluation treats those positions as false.

Length-based trimming/padding is not an alignment mechanism. It is only allowed after date alignment, when the stock and factor arrays already share the same target index.

## Gating Rules

Three gates apply before the cross-product is generated:

- **Selection gate**: `stock_factor_relevance` valid rows are authoritative when available. If the query succeeds and returns no factors, the runtime returns `no_signal`.
- **Config gate**: `stock_factor_config.enabled=false` removes that factor for the stock.
- **Channel gate**: `channel_tags.yaml` restricts sector-specific factors. Missing tags, empty lists, or `all` mean unrestricted.

If the factor-selection schema is unavailable in local/dev environments, the worker falls back to stock factor config and logs a warning.

## Replay and Backtest

Persisted representatives are not enough to replay Factor x TA. The replay layer must:
1. Reconstruct `FactorConditionMeta` from representative JSON.
2. Reload and date-align the referenced factor series to the backtest stock window.
3. Recompute the native TA signal.
4. Reapply `compose_and_signal`.

If a representative has `family` ending in `@fx` but no precomputed AND signal can be rebuilt, the replay path fails that representative instead of silently testing native TA.

## Valid Empty Outcomes

`no_signal` is valid when:
- No selected/active factor conditions exist.
- Required factor series are not ingested or cannot be aligned.
- Cross-product variants produce no precomputed signals.
- No representative survives OOS/WFO filtering.

These states are not equivalent to crashes. They should be visible in persisted result rows and in the UI as empty-but-completed outcomes.

## Verification

Relevant tests:
- `core/tests/test_signal_engine_factor_x_ta.py`
- `core/tests/test_conditioned_variants.py`
- `core/tests/test_alignment.py`
- `core/tests/test_signal_backtest_mc.py`
- `services/worker/tests/test_factor_x_ta_batch.py`
