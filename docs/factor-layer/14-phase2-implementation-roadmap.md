# 14 - Phase 2 Implementation Roadmap

This roadmap records the implemented Factor x TA runtime and the stabilization checks that keep it functional.

## Status

| Step | Description | Status |
|---|---|---|
| 2.0 | Doc skeleton and scoping | Done |
| 2.1 | Architectural smoke test for Layers B-G | Done |
| 2.2 | Factor condition library | Done |
| 2.3 | AND-composition library and naming | Done |
| 2.4 | Pre-registration YAML | Done |
| 2.5 | `FactorConditionMeta`, `VariantDef.factor_condition`, `precomputed_signal` bypass, candidate cross-product | Done |
| 2.6 | `stock_factor_config` migration | Done |
| 2.7 | Dedicated Signal Engine worker path, `variant='factor_x_ta'` | Done |
| 2.8 | Factor x TA API endpoints | Done |
| 2.9 | Signal-page Factor x TA view and factor state diagnostics | Done |
| 2.10 | Analytics source selector support | Done |
| 2.11 | WFO Factor x TA path | Done |
| 2.12 | Stabilization: canonical horizons, date alignment, replay/backtest, WFO folds | Done |

## Implemented Runtime

Signal Engine:
- Entrypoint: `services/worker/tasks/factor_x_ta_batch.py:compute_factor_x_ta_for_symbol`
- Variant key: `factor_x_ta`
- Result rows: `signal_engine_family_result` and `signal_engine_global_result`
- Families: `{base_family}@fx`

WFO:
- Entrypoint: `services/worker/tasks/wfo_factor_x_ta_batch.py:compute_wfo_factor_x_ta_for_symbol`
- Result rows: `wfo_signal_summary` and `wfo_global_signal`
- Category-level representatives are selected from factor-conditioned variants.

Replay/backtest:
- Entrypoint: `services/worker/tasks/signal_backtest_batch.py`
- Rebuilds AND-composed Factor x TA signals from persisted `factor_condition` metadata.
- Refuses to replay `@fx` representatives as native TA when the factor gate cannot be rebuilt.

## Stabilization Requirements

- Runtime APIs use canonical horizons: `weekly | monthly | quarterly`.
- Factor selection storage uses selection horizons: `short | mid | long`.
- The adapter maps `weekly -> short`, `monthly -> mid`, and `quarterly -> long`.
- Factor arrays are aligned by date with `precede_open` and `max_staleness=3`.
- `tags: [all]`, missing tags, and empty channel lists mean unrestricted.
- Empty selected factor sets are authoritative and produce `no_signal`.
- WFO Factor x TA persists `folds_json` and clears stale row data on failed/no-signal states.

## Acceptance Tests

Required focused checks:

```powershell
python -m pytest core/tests/test_signal_engine_factor_x_ta.py core/tests/test_conditioned_variants.py core/tests/test_alignment.py -q
python -m pytest core/tests/test_signal_backtest_mc.py services/worker/tests/test_signal_backtest_batch.py -q
python -m pytest services/worker/tests/test_factor_x_ta_batch.py services/worker/tests/test_signal_engine_batch.py services/worker/tests/test_wfo_signal_batch.py -q
python -m pytest services/api/tests/test_factor_selection_state.py services/api/tests/test_wfo_signals_api.py -q
```

## Remaining Empirical Work

The runtime is functional, but the research claim still depends on empirical results:
- Run full Factor x TA recompute for the active stock universe.
- Compare native TA vs Factor x TA by stock/horizon.
- Publish the final empirical write-up in `16-phase2-results.md`.
