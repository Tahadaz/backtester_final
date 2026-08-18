# Implementation brief: fix Analyse Fondamentale page latency (recompute out of the request path)

Self-contained brief. Everything you need is in this file plus the referenced source files. No other docs are required.

## Problem

The "Analyse Fondamentale" page (frontend tab `fundamental`, view `frontend/components/strategy/fundamental/index.tsx`) sometimes takes minutes to load, and individual stock views sometimes take even longer. Root cause: the two read endpoints that back the page run the **full valuation engine synchronously inside the HTTP request** whenever cached ensemble rows are missing, stale, or incoherent.

### Trace

1. `GET /fundamentals/universe` — handler `get_fundamental_universe`, `services/api/app/routers/fundamentals.py:2170`.
   - Loops over every covered symbol (~73) and calls `_ensure_latest_symbol_valuations` per symbol at `routers/fundamentals.py:2215` (helper defined at `:1059`).
   - `_ensure_latest_symbol_valuations` recomputes when: any of the 3 scenario ensemble rows (bear/base/bull) is missing; a row is stale per `_stale_valuation_ensemble` (`:1106` — `withheld_*` warnings or null `fair_value_base` with non-null dispersion); or the scenario trio is incoherent per `_scenario_rows_are_coherent` (`:402`).
   - The recompute is `recompute_symbol_valuations_all_scenarios` (`services/api/app/services/fundamentals.py:4922`) + `db.commit()` per symbol: full valuation context load, tie-out report, consensus + model-forecast views, projections for every horizon, ensemble, and Monte-Carlo sensitivity grids (`compute_default_sensitivity_grids`, called at `services/fundamentals.py:4846`) — ×3 scenarios. First request after an import, assumption edit, or deploy pays this for every affected symbol before responding.
   - Additionally, the warm path has an N+1 pattern: per-row `_headline_overlay` → `derive_research_overlay` (`services/fundamentals.py:557`) issues several queries per symbol (rating inputs, latest data verification, data cutoff, revision direction, horizon predictions) — roughly 5 queries × 73 rows per request.

2. `GET /fundamentals/stocks/{symbol}` — handler `get_fundamental_stock_detail`, `routers/fundamentals.py:2614`.
   - Same `_ensure_latest_symbol_valuations` recompute-if-stale for the one symbol at `:2665`, including the Monte-Carlo sensitivity grids — even though the frontend fetches grids lazily from the dedicated `GET /fundamentals/stocks/{symbol}/sensitivity` endpoint only when the valuation tab is open.

There is an existing fallback that can serve the latest previously-persisted rows without recomputing: `_latest_available_valuation_bundle` (`routers/fundamentals.py:967`, already used at `:2136`, `:2245`, `:3497`).

Background-job infrastructure already exists: RQ. See `services/api/app/scheduler.py` (`q.enqueue(...)` pattern, e.g. `:48`, `:67`) and `services/api/app/routers/factor_signals.py:577-630` (enqueue-from-endpoint pattern with worker tasks in `services/worker/tasks/`).

## Changes

### Phase 1 — move recompute out of the request path (the actual fix)

1. Add a keyword arg `recompute_inline: bool = True` to `_ensure_latest_symbol_valuations` (`routers/fundamentals.py:1059`). When `False`, the function must NOT call the recompute path; instead it returns (or exposes to the caller) whether the symbol's rows are missing/stale/incoherent.
2. In `get_fundamental_universe` (`:2170`), call it with `recompute_inline=False`. For symbols flagged stale:
   - Serve the latest previously-persisted rows via the existing `_latest_available_valuation_bundle` fallback (already wired at `:2245`).
   - Add an additive field `valuation_pending: true` on those universe rows in the response payload (schema addition; keep everything else backward-compatible).
   - Enqueue ONE background job carrying the list of stale symbols (dedupe: don't enqueue if an identical job is already queued/running — follow the guard patterns used by existing enqueue endpoints). The worker task lives in `services/worker/tasks/` (new module, e.g. `refresh_fundamental_valuations.py`) and calls `recompute_symbol_valuations_all_scenarios` per symbol with its own DB session, committing per symbol so partial progress persists.
3. In `get_fundamental_stock_detail` (`:2614`), keep inline single-symbol recompute (acceptable latency) but skip the sensitivity-grid computation on this inline path: thread a flag (e.g. `include_sensitivity_grids=False`) from `_ensure_latest_symbol_valuations` → `recompute_symbol_valuations_all_scenarios` → `recompute_symbol_valuations` so `compute_default_sensitivity_grids` (`services/fundamentals.py:4846`) is not executed there. The dedicated `/sensitivity` endpoint (`routers/fundamentals.py`, route `GET /fundamentals/stocks/{symbol}/sensitivity`) must still compute/serve grids as today — verify it does not depend on grids having been persisted by the detail path; if it reads persisted grids, have IT trigger the grid computation on demand instead.
4. The other callers of `_ensure_latest_symbol_valuations` (`:2112`, `:2911`) keep current behavior (`recompute_inline=True`) unless trivially safe to change — do not touch their semantics.

### Phase 2 — kill the warm-path N+1

5. Batch the inputs of `derive_research_overlay` (`services/fundamentals.py:557`): add bulk loaders that fetch rating inputs, latest data-verification rows, data cutoffs, and revision-direction inputs for ALL symbols in a constant number of queries, and pass the prefetched maps into the per-row overlay call from `get_fundamental_universe`. Keep the single-symbol path (used by the detail endpoint) working unchanged.

### Phase 3 — frontend (small, do last)

6. `frontend/components/strategy/fundamental/tabs/estimates-tab.tsx:552-555`: the per-scenario assumptions SWR hooks use defaults; add `revalidateOnFocus: false` and `dedupingInterval: 60_000` to match the page's other hooks.
7. Surface `valuation_pending` in the universe table (e.g. a subtle "calcul en cours…" badge on the row) and have SWR revalidate the universe after a delay when any row is pending (one-shot `setTimeout` + `mutate`, not a polling loop).

## Constraints

- No DB schema migrations unless strictly needed for job bookkeeping; prefer reusing existing job/queue tables.
- Response shapes stay backward-compatible; the only additive change is `valuation_pending`.
- Zod schemas in `frontend/lib/api.ts` (universe row schema near `:7189`) must be updated for the additive field (optional, so old payloads still parse).
- Don't change staleness semantics (`_stale_valuation_ensemble`, `_scenario_rows_are_coherent`) — only WHERE the recompute runs.

## Acceptance criteria

1. With at least one symbol's ensemble rows force-staled (e.g. null out `fair_value_base` and set a dispersion on its base-scenario `FundamentalEnsembleResult` row), `GET /fundamentals/universe` returns in well under 2s, with `valuation_pending: true` on the affected rows and previous values still populated from the fallback bundle.
2. The enqueued worker job recomputes those symbols; a subsequent universe request shows fresh rows and no `valuation_pending`.
3. Warm-path universe response content is byte-identical to before (minus the new optional field), and the request issues a bounded number of SQL queries independent of symbol count for the overlay inputs (verify with SQL echo/logging).
4. `GET /fundamentals/stocks/{symbol}` for a force-staled symbol is measurably faster than before (no Monte-Carlo grids inline) and `GET /fundamentals/stocks/{symbol}/sensitivity` still returns grids.
5. No regression on `/fundamentals/screens/{screen_name}` (it delegates to the universe handler) or the tearsheet/IC-memo endpoints (`routers/fundamentals.py:3471`, `:3478`) which call the detail handler internally.
6. Existing tests pass; add tests for: `recompute_inline=False` returning stale-flags without recomputing, the worker task refreshing a staled symbol, and the detail path not computing grids inline.
