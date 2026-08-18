# Brief: store-first PIT portfolio backtest — remove the "Pré-calculer le PIT" gate

**Audience:** implementing agent with repo access, no access to prior discussion. Everything needed is in this document. Implement phase by phase, running each phase's verification before moving on.

## Problem

Commit `5f76ff3` added the point-in-time (PIT) portfolio backtest to the Signals → Portefeuille tab, but gated it behind a "Pré-calculer le PIT" button: the user must trigger a long materialization job and wait (polling, 24h job timeout) before "Backtest rapide" unblocks. The gate is enforced twice:

- UI: `frontend/components/signals/portfolio-backtest-panel.tsx:1503` — `disabled={!coverage?.available ...}` on "Backtest rapide".
- API: `services/api/app/routers/historical_portfolio_backtest.py:38-46` — HTTP 409 `pit_store_coverage_required` when `opportunity_store_coverage` says the requested window isn't covered.

## Target behavior

1. The PIT opportunity store is seeded once with the **last 3 years** and kept fresh by the existing weekly cron, made **self-healing** (fills from the last covered date, not a fixed 21-day window).
2. "Backtest rapide" is always enabled (valid dates, no run in flight). If the requested range has a coverage gap (e.g., end date = today before Monday's cron), the backtest launch **transparently materializes just the gap first, then runs** — one chained flow, no 409, no user-visible two-step.
3. The manual "Pré-calculer/Actualiser le PIT" control survives only inside a collapsed advanced `<details>` section.

## Architecture facts (verified — trust these anchors, re-check line numbers if drifted)

- **Store**: `historical_trade_opportunity` table (`services/api/app/models.py:2003-2032`), unique `(decision_date, symbol, horizon, variant)`. Written by `materialize_historical_opportunities(materialization_run_id)` in `services/worker/tasks/historical_portfolio_backtest.py:239-349` — it **deletes only the `[start,end]` (± symbols) slice then re-inserts** (window-scoped replace-slice; idempotent, safe to call repeatedly with different/overlapping windows).
- **Run tracking**: `historical_opportunity_materialization_run` (`models.py:1976-2000`) with `status/config_json/progress_json/coverage_json`; polled via `GET /strategy/signal/historical-portfolio-backtests/materializations/{id}`.
- **Coverage**: `opportunity_store_coverage(db, config)` in `services/api/app/services/historical_opportunity_store.py:16-59`. It derives coverage from **succeeded materialization runs' config windows** (current `METHODOLOGY_VERSION`, symbol-scope matched), merges overlapping/adjacent intervals (gap ≤ 1 day bridges), and returns `{available, intervals: [{start, end}], materialization_run_ids, ...}`. Coverage from multiple runs composes correctly as long as windows touch/overlap.
- **Backtest**: `execute_historical_portfolio_backtest(run_id)` (same worker file, lines 352-587) **only reads the store, never recomputes**. It re-checks coverage at lines 373-376 and raises if missing (belt-and-suspenders).
- **Weekly cron**: `weekly_pit_opportunity_materialization` in `services/api/app/services/scheduler_registry.py:173-181` (cron `0 6 * * mon`, queue `score_history`), dispatched by `_dispatch_pit_opportunity_materialization` in `services/worker/tasks/scheduler_dispatch.py:492-518`, which currently builds a fixed `today-21d → today` all-symbols window and enqueues the same materialization task via `_queue("score_history")`.
- **On-demand trigger**: admin endpoint `POST /ops/scheduler/run/{schedule_id}` (`services/api/app/routers/ops.py:215-223`) runs `dispatch_schedule(schedule_id, trigger_source="manual")` synchronously — for this schedule kind that only creates run rows and enqueues RQ jobs (cheap). This is how the one-time seed is triggered; no new endpoint needed.
- **RQ**: installed rq is 2.7.x — `Queue.enqueue(..., depends_on=job)` is supported (no existing usage in the repo; it's a new but standard pattern). `materialize_historical_opportunities` commits its rows before returning, and RQ starts a dependent job only after the parent finishes, so the dependent backtest job always sees the committed rows (single Postgres, no replicas — no race).
- **Failure semantics**: `materialize_historical_opportunities` catches all exceptions, marks its run row `failed`, and returns without re-raising — so the RQ job finishes "successfully" and a `depends_on` backtest still fires. That's acceptable: the backtest's own coverage recheck (373-376) then fails it. Phase 1 step 4 makes that failure message self-explanatory.
- **Cost model**: `_load_inputs` (worker file, 170-213) loads the full price/score history regardless of window size; only the decision-date count scales with the window. The 8 variants come from `TECHNICAL_SIGNAL_MODE_NAMES` (`core/quant_core/signal_engine/modes.py`); cost ≈ decision weeks × 3 horizons × 8 variants × symbols.
- **Frontend panel**: `frontend/components/signals/portfolio-backtest-panel.tsx`, component `PortfolioBacktestPanel` (line 1384). Coverage fetch effect 1396-1403; materialization poll effect 1405-1420 (3s); backtest status poll 1422-1442; `launch()` 1444-1457; `materialize()` 1459-1466; PIT button 1502; "Backtest rapide" 1503; coverage sentence 1506; materialization progress text 1507; legacy `<details>` pattern at 1561. API client fns in `frontend/lib/api.ts:7543-7594`.

---

## Phase 1 — Backend: transparent gap-fill chaining on backtest creation

Files: `services/api/app/services/historical_opportunity_store.py`, `services/api/app/routers/historical_portfolio_backtest.py`, `services/api/app/schemas/historical_portfolio_backtest.py`, `services/api/tests/test_historical_portfolio_backtest_api.py`.

1. **Gap helper** in `historical_opportunity_store.py`, next to `opportunity_store_coverage` — pure function over the coverage dict (no DB query):

   ```python
   def missing_coverage_ranges(coverage: dict[str, Any], requested_start: date, requested_end: date) -> list[tuple[date, date]]:
       """Sub-ranges of [requested_start, requested_end] not covered by coverage['intervals'] (already merged, sorted)."""
   ```

   Walk a cursor from `requested_start` across the merged intervals; emit `[cursor, interval_start-1d]` for each hole and a trailing `[cursor, requested_end]` if the cursor never reaches the end.

2. **Router `create_historical_portfolio_backtest`** (`historical_portfolio_backtest.py:32-76`) — replace the 409 block (lines 38-46) with:
   - `missing = missing_coverage_ranges(coverage, body.start_date, body.end_date)`.
   - If `missing`: collapse to one convex-hull window `gap_start = min(starts)`, `gap_end = max(ends)`. (Re-materializing a few covered days inside the hull is idempotent and cheap; do not build multi-range chains.)
   - **Dedup in-flight**: mirror the pattern at lines 95-100 — if a `queued`/`running` `HistoricalOpportunityMaterializationRun` (same `METHODOLOGY_VERSION`) exists whose config window ⊇ `[gap_start, gap_end]` and whose symbol scope matches (stored `symbols` empty = all, or requested ⊆ stored), reuse it: fetch its RQ job via `rq.job.Job.fetch(row.rq_job_id, connection=queue.connection)` as the dependency instead of enqueueing a duplicate.
   - Else create a new `HistoricalOpportunityMaterializationRun` (`status="queued"`, `config_json={"start_date": gap_start.isoformat(), "end_date": gap_end.isoformat(), "symbols": normalized_config.get("symbols") or []}` — match the shape `/materializations` writes) and enqueue `materialize_historical_opportunities` on `get_queue()` with `job_timeout="24h"`, storing `rq_job_id` (same commit pattern as lines 101-119).
   - Enqueue the backtest job with `depends_on=<gap job>` when a gap run exists; otherwise keep the current single-enqueue fast path untouched (zero added latency when covered).
   - Set `row.diagnostics_json = {"stage": "queued", "gap_materialization_run_id": str(gap_run.id)}` when chained (currently `diagnostics_json={}` at line 57) so `GET /{run_id}` surfaces the link while the backtest job sits deferred.
   - Return the gap run id in the create response.
   - The dedup-vs-last-25-succeeded loop (lines 48-54) stays as-is: after a gap fill, `coverage["materialization_run_ids"]` changes, so no stale cached run can false-match.

3. **Schema**: add `materialization_run_id: str | None = None` to `HistoricalPortfolioRunCreated` in `schemas/historical_portfolio_backtest.py`.

4. **Failure debuggability** in `execute_historical_portfolio_backtest` (worker file, 373-376): when the coverage recheck fails, query the most recent `failed` `HistoricalOpportunityMaterializationRun` overlapping `[start, end]` and append its `error_message` to the raised error, so a silently-failed gap-fill explains the backtest failure.

5. **Tests** (`services/api/tests/test_historical_portfolio_backtest_api.py`):
   - Rewrite `test_backtest_fails_fast_when_pit_store_is_missing` (currently asserts 409) → assert 202, `materialization_run_id` in the response, a new materialization row scoped to the gap window, and two enqueue calls where the second carries `depends_on` referencing the first job. Extend the `_Queue` test double (lines ~21-23) to record `(args, kwargs)` per call.
   - Add a covered-fast-path test: coverage available → single enqueue, no `depends_on`, `materialization_run_id is None`.

**Verify:** `pytest services/api/tests/test_historical_portfolio_backtest_api.py -q`.

## Phase 2 — Self-healing weekly cron + one-time 3-year chunked seed

Files: `services/worker/tasks/scheduler_dispatch.py` (`_dispatch_pit_opportunity_materialization`, 492-518), `services/worker/tests/test_scheduler_dispatch.py`.

1. Replace the fixed `today-21d → today` window with a coverage probe (reuse `opportunity_store_coverage` with a wide probe window, e.g. `1990-01-01 → today`, `symbols: []`; take `max(interval ends)` as `last_covered_end`):
   - **Store empty (`last_covered_end is None`) → seed mode**: chunk `[today - 3y, today]` into 90-day windows. For each chunk create its own `HistoricalOpportunityMaterializationRun` row and enqueue `materialize_historical_opportunities` on `_queue("score_history")` with `job_timeout="24h"`, chaining chunks sequentially via `depends_on=<previous chunk's job>`. Return `{"mode": "seed_chunked", "enqueued_jobs": N, "materialization_run_ids": [...], "window_start": ..., "window_end": ...}`.
   - **Store non-empty → incremental mode**: single window `max(last_covered_end - 7d, today - 3y) → today`. Return `{"mode": "incremental", ...}` with the run/job ids and window.
2. Constants at module level: `PIT_SEED_LOOKBACK_DAYS = 365 * 3`, `PIT_SEED_CHUNK_DAYS = 90`, `PIT_COVERAGE_OVERLAP_DAYS = 7`.
3. Rationale to preserve in a short comment: chunking makes coverage usable incrementally (each chunk's run flips `succeeded` independently) and a late failure doesn't discard earlier chunks; sequential `depends_on` chaining keeps DB/CPU load flat. Each 90-day chunk ≈ 13 weekly decision dates ≈ 4× the old 21-day cron job — safely inside the 24h timeout.
4. **Tests** (`test_scheduler_dispatch.py`, mock the queue like the existing `test_dispatch_stale_wfo_enqueues_both...` pattern):
   - Empty store → expected chunk count (`ceil((365*3+1)/90)` windows covering exactly `[today-3y, today]` with no gaps/overlap-misses), chained `depends_on`.
   - Non-empty store (seed a succeeded run row with a `config_json` window) → single incremental window derived from coverage, not 21 days.

**Verify:** `pytest services/worker/tests/test_scheduler_dispatch.py -q`.

## Phase 3 — Frontend: remove the gate, demote manual refresh

Files: `frontend/lib/api.ts` (~7543-7594), `frontend/components/signals/portfolio-backtest-panel.tsx`.

1. `api.ts`: add `materialization_run_id?: string | null` to `createHistoricalPortfolioBacktest`'s return type.
2. Panel (`PortfolioBacktestPanel`):
   - `launch()` (1444-1457): if the create response has `materialization_run_id`, fetch it via `getHistoricalOpportunityMaterialization` and `setMaterialization(...)`. The existing materialization poll effect (1405-1420) and progress text (1507) then display "Pré-calcul … (X%)" automatically for auto gap-fills — no new polling code.
   - "Backtest rapide" (1503): drop `!coverage?.available` from `disabled` — enabled whenever both dates are set and no backtest run is queued/running.
   - Coverage sentence (1506): compute from `coverage.intervals` — when the requested range is covered: `PIT à jour au {maxEnd}`; when gapped: `Couverture PIT : {minStart} → {maxEnd} — le manquant sera calculé automatiquement au lancement` (and when the store is empty: `Store PIT vide — il sera calculé automatiquement au lancement`).
   - Move the "Pré-calculer le PIT"/"Actualiser le PIT" button (1502) and the `materialize()` handler into a collapsed `<details className="text-xs text-muted-foreground"><summary>Avancé : gestion manuelle du store PIT</summary>…</details>` placed after the main controls, following the existing `<details>` pattern at line 1561. Keep its progress/error display working inside the section.

**Verify:** `cd frontend && npm run build` (type check must pass).

## End-to-end verification (after all phases)

1. `docker compose -f infra/docker-compose.yml up -d` (postgres, redis, minio + init, db_migrate, api, workers — workers listen on `runs` and `score_history`).
2. Empty `historical_trade_opportunity` and `historical_opportunity_materialization_run` (fresh-store simulation).
3. Seed: `POST /ops/scheduler/run/weekly_pit_opportunity_materialization` (admin auth as required by `require_admin`) → response `mode == "seed_chunked"` with expected chunk count; worker logs show chunks running sequentially (later chunks deferred in RQ); `POST /strategy/signal/historical-portfolio-backtests/coverage` (start ≈ 3y ago, end today) grows to `available: true`. Re-trigger the schedule → `mode == "incremental"`, small window.
4. Portefeuille tab, end date = today: "Backtest rapide" clickable immediately with no precompute click; network tab shows no 409; if a tail gap existed, inline materialization progress appears, then the backtest completes and results render.
5. Repeat the same request → fast path (`materialization_run_id` null; possibly `reused: true`).
6. Full suites: `pytest services/api/tests -q` and `pytest services/worker/tests -q` must pass.

## Out of scope

- No schema/Alembic changes (no new tables or columns).
- Do not modify `materialize_historical_opportunities` or `execute_historical_portfolio_backtest` beyond Phase 1 step 4's error-message enrichment.
- Do not change the legacy `SnapshotAuditLegacyPanel` or its endpoints.
