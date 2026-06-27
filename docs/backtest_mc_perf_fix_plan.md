# Plan — Fix slow / 503-timeout signal evidence + technical tab (`/backtest-mc`)

## Context / symptom
Clicking a stock and opening the Technical tab (stitched OOS chart) hangs for ~2 min, then:
```
503 {"error":"Upstream API unavailable","detail":"Upstream request timed out after 120000ms",
     "target":".../strategy/backtest-mc?symbol=CMT&horizon=weekly&variant=expanded_ta_simple&cooldown_bars=0"}
```

## Root cause
`GET /strategy/backtest-mc` (`services/api/app/routers/strategy_signals.py:8329`,
`get_signal_backtest_results`) does heavy compute **in-band** — i.e. inside the read
request, blocking it until done:

1. On cache miss (no precomputed directional-chart row) it calls
   `_materialize_signal_backtest_for_api` (`:8374` → `:8301`), which runs the **worker**
   function `compute_signal_backtest_for_symbol(..., n_paths=2000, side_policy="long_short")`
   synchronously: full WFO replay + 2000-path block-bootstrap Monte Carlo. Minutes of CPU →
   gateway kills it at 120 s → 503. Symbols/variants never batch-precomputed (e.g. CMT) hit
   this every time; precomputed ones are fast (why it's intermittent).
2. For every returned `source == "wfo"` row, `_sr_overlay_for_position_series` (`:8470`,
   defined `:7109`) runs a **full nested support × resistance grid** of overlay sims
   (`:7157`–`:7161`) live on each request — adds seconds even on a cache hit.

The async path already exists and is unused by the heavy callers:
`POST /backtest-mc/trigger` (`:5236`) → `enqueue_signal_backtest_for_symbol`, and
`fetchSignalBacktestResultsWithBootstrap` (`frontend/lib/api.ts:5529`) which triggers + polls
`/backtest-mc/batch-status`.

> "In-band" is not a task to add — it is the thing being removed. Fix 1 = move the compute
> out-of-band (to the worker queue). Fix 3 = stop recomputing the SR overlay grid on every GET.

---

## Fix 1 — make `GET /backtest-mc` read-only (compute out-of-band)

### 1a. Backend: stop synchronous materialization
File: `services/api/app/routers/strategy_signals.py`, `get_signal_backtest_results` (`:8329`).

- **Delete** the `if not _signal_backtest_rows_have_directional_chart(rows): ... _materialize_signal_backtest_for_api(...)` block (`:8372`–`:8391`) and the re-query that follows it.
- Replace the cache-miss behavior: if `rows` is empty **or** no directional chart row exists
  (`not _signal_backtest_rows_have_directional_chart(rows)`), enqueue the job and return `404`
  immediately:
  ```python
  from services.worker.tasks.signal_enqueue import enqueue_signal_backtest_for_symbol
  try:
      enqueue_signal_backtest_for_symbol(
          symbol, horizon, variant=variant,
          mc_config={"method": "block_bootstrap", "n_paths": 2000,
                     "side_policy": "long_short", "cooldown_bars": cooldown},
          triggered_by="api_read_miss",
      )
  except Exception:
      logger.warning("Failed to enqueue backtest-mc on read miss for %s/%s/%s",
                     symbol, horizon, variant, exc_info=True)
  raise HTTPException(
      status_code=404,
      detail=f"No backtest results for {symbol}/{horizon}/{variant}; computation queued.",
  )
  ```
  - **Critical:** the detail string MUST contain the lowercase substring `"no backtest results"`
    so the frontend bootstrap recognizes it (`frontend/lib/api.ts:5526`). Do not phrase it as
    "No stored or materializable backtest results" (current string does NOT match).
  - Enqueue is idempotent-ish; double-trigger (frontend bootstrap also triggers) is harmless but
    avoid spamming — relying on the frontend trigger alone is also acceptable. Keep the server-side
    enqueue so non-bootstrap callers still make progress.
- `_materialize_signal_backtest_for_api` (`:8301`) becomes unused → delete it (and its only
  import of `compute_signal_backtest_for_symbol`). Leave `compute_signal_backtest_for_symbol`
  itself (the worker still uses it).

### 1b. Frontend: switch the two synchronous callers to the bootstrap variant
The Technical/quant tab callers use the plain `fetchSignalBacktestResults` (blocks, no
trigger+poll). Point them at `fetchSignalBacktestResultsWithBootstrap` so they trigger and poll
with a loading state instead of one long hanging request:

- `frontend/components/strategy/signal-technique-dashboard.tsx:742`
- `frontend/components/signals/backtest-mc-panel.tsx:746`

Verify each call site passes the same `variant / source / scope / selectedDirection /
cooldownBars` opts. Keep their existing loading UI; the bootstrap returns once the worker
persists the row. (`signal-quantitative-view.tsx:1508` already uses the bootstrap — use it as the
reference pattern.)

### 1c. Robustness: broaden the bootstrap matcher (defense in depth)
File: `frontend/lib/api.ts:5523` `_shouldBootstrapSignalBacktestResults`.
Relax the message check from `includes("no backtest results")` to `includes("backtest results")`
so future wording changes don't silently break auto-trigger. (Still gated on `status === 404`.)

### Fix 1 acceptance
- First open of a never-computed symbol (e.g. CMT/weekly/expanded_ta_simple) returns `404` in
  <1 s, UI shows "computing…", then renders once the worker finishes — no 503.
- No call to `compute_signal_backtest_for_symbol` from within the API request path
  (grep the router for it → only the deleted helper referenced it).

---

## Fix 3 — stop recomputing the SR overlay grid on every GET

Primary approach: compute the SR overlay **once in the worker** during materialization and persist
it on the row; `GET` just reads it.

### 3a. Schema: add a column
- `services/api/app/models.py`, `SignalBacktestRun` (`:1851`): add
  `sr_overlay_json = Column(JSONB, nullable=True)` near the other JSONB outputs (~`:1906`).
- New Alembic migration under `services/api/alembic/versions/` (down_revision = current head;
  check with `alembic heads`): `add_sr_overlay_json_to_signal_backtest_run`, `add_column` /
  `drop_column` of `signal_backtest_run.sr_overlay_json` (JSONB, nullable).

### 3b. Worker: populate it for wfo rows
- In `services/worker/tasks/signal_backtest_batch.py` (`compute_signal_backtest_for_symbol`,
  `:153`), where a `source == "wfo"` row's metrics/position are finalized before persist, compute
  the overlay once and store it on the row.
- Reuse the same logic as `_sr_overlay_for_position_series`
  (`services/api/app/routers/strategy_signals.py:7109`). To avoid duplication, extract that
  function + its helpers (`_sr_overlay_context_payload`, `_sr_simulate_signal_overlay`,
  `_sr_overlay_uplift`, `_sr_overlay_empty`, etc.) into a shared module, e.g.
  `core/quant_core/signal_engine/sr_overlay.py`, and import it from both the router and the worker.
  (If extraction is too large for one pass, the worker may import the helper directly from the
  router module as an interim step — note the tech debt.)
- Persist the baseline (no direction filter, `side_policy` = the row's own policy) overlay.

### 3c. API: read persisted overlay, fall back to live only for the rare path
- In `get_signal_backtest_results` (`:8469`–`:8486`): when `direction_filter is None` and
  `row.sr_overlay_json` is present, use it directly instead of calling
  `_sr_overlay_for_position_series`.
- Keep the live call ONLY when `direction_filter` is set (short/long-filtered view changes
  `side_policy`/position, so the persisted baseline overlay doesn't apply) OR when
  `sr_overlay_json` is null (legacy rows not yet recomputed). This bounds the expensive grid to a
  non-default, opt-in code path.

### Fix 3 acceptance
- Default GET on a precomputed wfo symbol does **zero** SR-overlay grid simulation
  (reads `sr_overlay_json`); response is materially faster (measure before/after with one symbol).
- Direction-filtered GET still returns a correct overlay (live path) — unchanged output.
- New rows written by the worker have `sr_overlay_json` populated; legacy rows still render via
  fallback.

---

## Test / verification
- Backend unit: `services/api/tests/test_signal_backtest_api.py` — add a case asserting GET on a
  missing tuple returns 404 with a detail containing `"no backtest results"` and does NOT block
  (no synchronous compute). Mock/spy `enqueue_signal_backtest_for_symbol` is called.
- Worker unit: assert `compute_signal_backtest_for_symbol` writes `sr_overlay_json` for a wfo row.
- Migration: `alembic upgrade head` then `downgrade -1` round-trips cleanly.
- Frontend: type-check (`npm run -s tsc` / build); manually confirm Technical tab shows a loading
  state then renders for a fresh symbol instead of hanging.
- Full suite: `python -m pytest services/api/tests -q` and `core/tests` relevant subset.

## Out of scope (note, don't do)
- Lowering `n_paths` for correctness reasons — keep 2000 in the worker; the fix is *where* it runs,
  not *how heavy* it is.
- Touching the gateway 120 s timeout — once compute is out-of-band, GETs return in <1 s and the
  timeout is irrelevant.

## Suggested commit split
1. Fix 1 backend (router read-only + enqueue) + matcher broadening.
2. Fix 1 frontend (two callers → bootstrap).
3. Fix 3 schema + migration + worker populate + shared sr_overlay module.
4. Fix 3 API read-from-persisted + tests.
