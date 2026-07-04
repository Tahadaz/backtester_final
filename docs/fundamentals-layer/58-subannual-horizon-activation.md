# Brief 58 — Activate quarterly/semestrial horizons (cross-import period history)

Date: 2026-07-03. Status: approved for implementation.

## Problem

The fundamental analysis UI has horizon buttons (Trimestre / Semestre / Année) backed by
`horizon_predictions`, but quarter/semester are greyed out for virtually every name.
The projection engine (`core/quant_core/fundamentals/projection.py`) fully supports
quarterly/semiannual builds, gated by `available_horizons(period_history)` which requires
>= 3 same-period revenue observations per period index.

## Root cause (verified against the live DB, 2026-07-03)

- `fundamental_period_metric` holds 10,340 quarterly rows (56 symbols) and 47,692
  semiannual rows (69 symbols), fiscal years 2021-2026, ingested by targeted BVC scrapes
  under their own `import_id`s (largest: `fcefad0e-1676-4b4d-8a64-18a465f3e838`).
- Canonical snapshots mostly live in workbook imports with **zero** sub-annual rows
  (e.g. `17fa82d2-…` carries 48 canonical snapshots, 0 sub-annual rows).
- `_load_period_history(db, import_id, symbol)` in
  `services/api/app/services/fundamentals.py` (~line 3057) filters
  `FundamentalPeriodMetric.import_id == import_id`, so valuation recompute sees an empty
  period history → `available_horizons` = `{"year"}` → no sub-annual projections, no
  quarter/semester horizon predictions, greyed-out UI.
- Gate emulation in SQL with normalized labels (S1→H1 etc., matching
  `normalize_period_label`): **47 symbols pass quarterly, 52 pass semiannual** once
  period history is loaded across imports. No new scraping needed.

## Fix — Phase 1: cross-import period history (backend only)

1. `services/api/app/services/fundamentals.py` — make `_load_period_history` load the
   symbol's period rows across **all** imports:
   - Query `FundamentalPeriodMetric` without the `import_id` equality filter (keep the
     optional symbol filter; when `symbol is None` keep behavior scoped to the given
     import to avoid loading the whole table during import-time bulk paths — check all
     call sites and preserve their semantics).
   - Dedupe to one row per key `(symbol, fiscal_year, period_type,
     normalize_period_label(period_type, period_label), metric_name)`.
   - Preference order within a key: row from the requested `import_id` first, then
     non-proxy (`is_proxy = False`) over proxy, then most recent import
     (`fundamental_import.created_at` desc; fall back to row id desc).
   - Reuse the existing dedupe idiom used at ~line 815 (`period_best` keyed the same
     way) rather than inventing a new one.
2. Sweep other API readers of `FundamentalPeriodMetric` that filter by `import_id` and
   feed user-facing period data — notably `services/api/app/routers/fundamentals.py`
   (~lines 1940 and 2571: period-type coverage listing and the period statements/history
   endpoint) — and route them through the shared cross-import loader (or replicate the
   same cross-import + dedupe semantics) so historical quarterly/semestrial statement
   tables also populate. Do NOT touch ingestion/write paths or the BVC scrape tasks.
3. Leave `fundamental_consensus_estimate` annual-only (by design); sub-annual targets
   come from the projection engine via `horizon_predictions`.

## Fix — Phase 2: recompute + verification

4. Add/extend tests:
   - API-level test: two imports, sub-annual rows only in the older import → context
     for the newer import's snapshot exposes them; preference order (current import >
     non-proxy > newest import) covered; S1/H1 label collision dedupes to one row.
   - Existing `services/api/tests/test_fundamental_projection_persistence.py` asserts
     `available_horizons == ["year"]` for an annual-only fixture — must still pass.
5. Recompute valuations for the canonical universe (inside the running
   `infra-quant_api-1` container or via the existing batch/recompute entrypoint —
   locate the existing mechanism, e.g. the admin recompute route or script that loops
   `recompute_symbol_valuations`; do not write a new orchestration layer if one exists).
6. Verify with SQL against `quant` DB (`docker exec infra-quant_postgres-1 psql -U app
   -d quant`):
   - count of canonical snapshots whose `model_eligibility_json->'available_horizons'`
     contains `quarter` (~47 expected) and `semester` (~52 expected);
   - `fundamental_projection` rows with `period_type IN ('quarterly','semiannual')`
     exist for recomputed names;
   - spot-check one symbol's research-detail API payload: `horizon_predictions` has
     `quarter` and `semester` entries with `forward_target`.
7. Frontend: no changes expected — `signal-fundamental-view.tsx` unlocks buttons from
   `horizon_predictions` availability. Confirm via payload, not by editing the UI.

## Constraints

- No commits; leave changes in the working tree (branch `feature/forward-estimate-layer`).
- Don't modify `core/quant_core/fundamentals/projection.py` gating thresholds
  (`MIN_SAME_PERIOD_OBSERVATIONS = 3` stays).
- Keep the diff minimal and idiomatic to the surrounding code.
