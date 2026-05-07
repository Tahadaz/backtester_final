# Decision Module Architecture

## Overview

The decision module is a post-run layer that turns strategy outputs into actionable decision records.
It is intentionally separated from optimization/backtest ranking so existing run and leaderboard behavior stays unchanged.

## Runtime flow

1. `core.quant_core.pipeline.run_pipeline` produces normal outputs (`leaderboard`, `strategy_results`, metrics, artifacts) and now also adds `decision_support`.
2. `services.worker.tasks.execute_run._persist_pipeline_output` calls `_persist_decisions` after normal persistence.
3. `_persist_decisions` selects top candidates per symbol (`TOP_K_DECISIONS`), computes:
   - opportunity score
   - confidence score
   - level/risk payload (entry, stop, target, RR, invalidation)
   - final decision page payload
4. Results are upserted into `strategy_decision` (idempotent by `(run_id, symbol, strategy_kind, trial_id)`).

## Confidence/OOS integration

- Walk-forward OOS context is exposed by pipeline under `decision_support`:
  - `walk_forward_rows`
  - `walk_forward_oos_summary_by_kind`
- Confidence scoring consumes fold rows when available and falls back to OOS summary when fold rows are not present.
- Monte Carlo tail-risk uses `MC_NUM_PATHS`.

## Idempotency

- Worker retry cleanup deletes `strategy_decision` rows before re-persisting outputs.
- Run deletion also deletes `strategy_decision` rows.

## API surface

- `GET /runs/{run_id}/decisions?best_only=true`
- `GET /runs/{run_id}/decisions/{symbol}/{strategy}/{trial_id}`

Both endpoints return typed decision payloads used directly by frontend run details.
