# Value Strategy Operations Runbook (2026-07-06)

Operational documentation for the canonical B/M + CF/P value signal and its six-vintage strategy snapshot. A new engineer should be able to operate this from this document alone.

## Architecture (reused, not invented)

This follows the exact same async job architecture already used for the SFC portfolio backtest (`services/api/app/routers/analytics.py` / `services/api/app/services/fundamental_cross_section.py`):

- **Queue**: RQ, `market_refresh` queue (Redis-backed, `services/api/app/queue.py:get_market_refresh_queue()`).
- **Job tracking**: `signal_engine_batch_job` table (`models.SignalEngineBatchJob`), reused with sentinel identity `symbol='__VALUE_STRATEGY__'`, `horizon='vintage6'`, `job_type='value_strategy'` — the same generic job-status table already used for the SFC backtest (`symbol='__SFC_PORTFOLIO__'`, `job_type='fundamental_sfc_backtest'`).
- **Worker task**: `services/worker/tasks/value_strategy.py::recompute_value_strategy` — mirrors `services/worker/tasks/fundamental_cross_section.py::recompute_sfc_portfolio_backtest` line-for-line (start → running, success → succeeded, exception → failed + error_message, always `finally: db.close()`).
- **Snapshot persistence**: `fundamental_value_strategy_snapshot` table (migration `valuestrat20260706`), INSERT-only (no in-place update of a "current" row) — this is what makes concurrent/repeated recomputes safe: a failed attempt never touches a previously-persisted row, and "latest" is simply `max(computed_at)` for the current `config_hash`.
- **Scheduler**: dedicated process `services/worker/scheduler.py`, driven by the single source of truth `services/api/app/services/scheduler_registry.py::SCHEDULE_SPECS`. A new spec `weekly_value_strategy_refresh` was added there, dispatched via `services/worker/tasks/scheduler_dispatch.py::_dispatch_value_strategy_refresh` (added, mirrors `_dispatch_fundamental_cross_section`).

## APIs

| Endpoint | Method | Purpose |
|---|---|---|
| `/value-signal` | GET | Live-computed B/M+CF/P cross-section (fast, no snapshot needed) |
| `/value-signal/{symbol}` | GET | Single-symbol detail |
| `/value-strategy/snapshot` | GET | Latest persisted six-vintage snapshot, with `freshness` state |
| `/value-strategy/recompute` | POST (admin) | Enqueues an async recompute (returns immediately with `job_id`) |
| `/value-strategy/recompute/status` | GET | Last 5 recompute attempts (queued/running/succeeded/failed) |

## Refresh cadence

**Weekly, Saturday 20:45 UTC**, 15 minutes after `weekly_fundamental_cross_section` (20:30 UTC) which itself follows the weekly fundamentals refresh (20:00/19:00 UTC Saturday). Rationale: the underlying B/M/CF/P panel data only meaningfully changes on this weekly fundamentals cadence (confirmed in the prior session's quarterly-data feasibility study — quarterly/interim filings barely move the panel beyond what's already captured weekly); the six-vintage strategy itself reforms monthly, but a weekly snapshot refresh keeps the *displayed* holdings/metrics from silently drifting more than a week behind the data. This is not "recompute every minute" — it is tied to the actual data cadence, per the brief's explicit instruction.

A **manual forced recompute** is always available via `POST /value-strategy/recompute` (used, for example, immediately after a data-quality repair — see `research-out/data-quality-forensic-repair/`).

## Model versioning

`MODEL_VERSION = "Fundamental Value Strategy v1.0"` (`services/api/app/services/value_strategy_snapshot.py`) identifies the **frozen methodology**: canonical B/M, canonical CF/P, the SAH/trusted-universe exclusion policy, the six-vintage architecture, and the 33bps cost policy. This is distinct from:
- `computed_at` — when this particular snapshot ran (a timestamp, changes every recompute).
- `config_hash` — a hash of the runtime config payload, used as the DB lookup key.

Bump `MODEL_VERSION` only when the methodology itself changes (a new canonical definition, a new exclusion). Do not encode timestamps into it.

## Snapshot metadata (Phase 3)

Each snapshot's `result_json` carries: `model_version`, `methodology_version`, `as_of_date` / `signal_as_of_date` / `strategy_as_of_date` (all currently the same — the last vintage-formation date), `data_cutoff` (latest panel date used), `universe_summary` (`total_names`, `eligible_bm_count`, `excluded_count`, `excluded_symbols` — symbol → reason code), `current_holdings`, `strategy_metrics`, `caveats`, `triggered_by`, `batch_id`.

## Staleness policy (Phase 6)

Computed by `snapshot_freshness()` in `value_strategy_snapshot.py`, exposed as `freshness` on the `/value-strategy/snapshot` response:

| State | Condition |
|---|---|
| `fresh` | Latest successful snapshot ≤ 10 days old |
| `aging` | 10–40 days old (covers one missed monthly vintage formation) |
| `stale` | > 40 days old |
| `failed_refresh` | The most recent recompute *attempt* (which may be newer than the last successful snapshot) has status `failed` — the old valid snapshot is still returned and displayed, but flagged |
| `no_snapshot` | Nothing has ever been computed successfully |

Thresholds (`FRESH_MAX_AGE_DAYS=10`, `AGING_MAX_AGE_DAYS=40`) are picked from the actual weekly/monthly cadence above, not an arbitrary wall-clock guess.

## Manual recompute / recovery process

1. `curl -X POST http://localhost:8000/value-strategy/recompute -H "X-Admin-Key: <key>"` (or the Dashboard's "Recalculer" button, `ValueStrategyPanel`).
2. Poll `GET /value-strategy/recompute/status` until the job's status is `succeeded` or `failed`. Typical runtime ~3 minutes (full daily price-history load + six-vintage backtest over ~9 years).
3. If `failed`, `error_message` on the job row has the exception text. The previous valid snapshot remains served as-is (never destroyed) with `freshness.state == "failed_refresh"`.
4. One-off local seed/backfill: `python scripts/seed_value_strategy_snapshot.py` (bypasses the queue, runs synchronously in-process — useful for local dev or CI, not for production operation).

## Known operational dependency: `data/universe/bvc_pit_universe.csv`

This file is gitignored (not version-controlled) and must exist on the host at `data/universe/bvc_pit_universe.csv`. It is now bind-mounted into both the `quant_api` and `quant_worker` containers (`infra/docker-compose.yml`, added 2026-07-06 — previously **not mounted at all**, causing `load_universe()` to fail inside the worker with `FileNotFoundError` the first time this job was actually run end-to-end). If this file is ever missing or the mount is removed, every `/value-signal*` and `/value-strategy/recompute` call will fail identically — check `docker exec <container> ls /repo/data/universe/` first when debugging.

## Worker / scheduler commands (local dev)

```
# Restart the worker (picks up new task modules since services/worker is bind-mounted):
docker restart infra-quant_worker-2

# Restart the API (picks up new routers/services):
docker restart infra-quant_api-1

# Enable the dedicated scheduler process (disabled by default in dev):
# set WORKER_SCHEDULER_ENABLED=1 on the services.worker.scheduler container/process
python -m services.worker.scheduler
```
