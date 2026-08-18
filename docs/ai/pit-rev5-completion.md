# Implementation brief — PIT Portefeuille Rev 5 completion (post-implementation gap closure)

**Audience:** implementing agent (Codex) with repo access, no prior discussion. Implement tasks in order; run each task's blocking tests before moving on.

**Parent contract:** `docs/ai/pit-portfolio-tab-v2.md` (Rev 5). That contract is implemented and test-green; this brief closes the gaps found by a 2026-07-20 audit of the delivered code. It does **not** revisit ratified Rev 5 decisions and does **not** introduce any statistical-methodology change (those remain deferred to Rev 6).

## Already done — do not redo

These were fixed on 2026-07-20 and are live in the working tree:

- `opportunity_store_coverage` (`services/api/app/services/historical_opportunity_store.py`) compared symbol lists literally, so a request with empty `symbols` (= whole universe) never matched a materialization storing the 77 resolved symbols; coverage always read empty and every launch re-materialized. Empty now means "resolved universe" on both sides. The same defect in the router's in-flight reuse check is fixed too.
- `_resolve_scope` (`services/api/app/routers/historical_portfolio_backtest.py`) now clamps the requested window to the **MASI index trading calendar** as well as to OOS score history, and returns 422 `window_outside_supported_coverage` when the window falls entirely outside. Rationale: the weekly decision grid is built from MASI bars (`_load_weekly_masi_calendar`), and `market_data_store` holds MASI only from **2023-06-02**, while equities reach back to 2000 and OOS score history to 2001. Windows before 2023-06-02 previously produced zero decision dates silently.
- Launching a backtest no longer auto-enqueues a gap fill. Uncovered dates return **409 `pit_coverage_incomplete`** with `missing_ranges`; `POST /materializations` materializes **only the missing sub-ranges**, split into chained 90-day chunks. The panel renders a banner inviting precalculation of exactly those ranges. This supersedes the auto-gap-fill behaviour of `docs/ai/pit-store-first-portfolio-backtest.md`.

## Measured cost baseline (use instead of re-measuring)

Full v5 rebuild over the seedable range 2023-06-02 → 2026-07-10 = 13 × 90-day chunks, 77 symbols. Per chunk, from `progress_json.stage_elapsed_seconds`:

| stage | seconds | under advisory lock |
|---|---|---|
| `initial_input_load` | 14.3 | no |
| `initial_source_hash` | 23.4 | no |
| `grid_computation` | 342.5 | no |
| `final_input_reload_and_hash` | 34.9 | **yes** |
| `final_transaction` | 1.9 | **yes** |

≈ 7–9 min per chunk; ~100 min sequential, ~15 min with chunks running concurrently. Only ~9 % of wall time is serialized, and the commit-time guards are window-scoped (delete filters `methodology_version` + `decision_date BETWEEN start AND end`, `historical_portfolio_backtest.py:765-773`; `_has_newer_successful_overlap` requires date-window overlap, `:649`), so disjoint chunks are safe to run in parallel.

---

## Task 1 — Fold-window OOS selection is silently discarded (correctness)

`core/quant_core/signal_ranking.py:160-196` (`_historical_oos`). Both branches assign `selection_windows` (`:176` for the `OosSample` input, `:184` for the explicit-date input), and then `:185-192` unconditionally recompute the selection sample as the first ⌊2n/3⌋ chronological dates of `proof.dates`, overwriting it.

Per the parent contract Phase 3.3, the ⌊2n/3⌋ split is the **documented PIT substitute used only when explicit dates are supplied**; when an `OosSample` is given (the live dashboard path) the fold windows must be honoured. As written, the live path never uses fold-scoped selection, which undermines the blocking live-equivalence guarantee.

**Change:** apply the ⌊2n/3⌋ substitute only in the `else` branch. In the `OosSample` branch, build the selection sample from `value.windows` (clipped to `< as_of`, as already done at `:163-174`) and the dates falling inside those windows.

**Blocking tests** (extend `core/tests/test_signal_ranking.py`):
- `OosSample` input with fold windows ⇒ the returned selection sample's windows equal the clipped input fold windows, not a single synthesized `(first, last)` window.
- Explicit-date-tuple input ⇒ unchanged ⌊2n/3⌋ behaviour (regression guard).
- Both inputs ⇒ every selection and proof date is strictly `< as_of`.
- Golden-fixture and determinism tests still pass unchanged.

## Task 2 — `suspected_defect` is unreachable in the snapshot audit (governance)

`core/quant_core/historical_portfolio.py:723-727` computes `mismatch_reason` as:

```
None if shown == rebuilt
else "missing_reconstructable_input" if rebuilt is None
else "documented_substitute_divergence"
```

`suspected_defect` never appears anywhere in the codebase (only in docs). Worse, `documented_substitute_divergence` is the catch-all `else`, so a genuine reconstruction defect is silently labelled an expected, documented divergence. Per the parent contract's Fidelity contract, `suspected_defect` is the class that feeds back into the **blocking** category; it currently cannot fire.

**Change:** classify explicitly. `documented_substitute_divergence` may only be returned when the divergence is attributable to a named Phase-3 substitute; every other mismatch is `suspected_defect`. Introduce an explicit list of named substitutes and match against it rather than defaulting. Add per-reason counts to the returned payload so a report can show the triage split.

**Blocking tests** (`core/tests/test_historical_portfolio.py`):
- Reconstruction missing entirely ⇒ `missing_reconstructable_input`.
- Divergence attributable to a named substitute ⇒ `documented_substitute_divergence`.
- Divergence attributable to neither ⇒ `suspected_defect` (this test must fail against today's code).
- Wilson intervals and match proportions unchanged.

## Task 3 — TP/SL barrier overlay is unreachable from the product

The Phase-5 barrier overlay is implemented in the worker and accepted by the API (`stop_loss_pct`, `take_profit_pct` on `HistoricalPortfolioRunCreate`), but the canonical PIT panel never sends it, so the feature cannot be switched on by any user:

- `frontend/lib/api.ts` — `createHistoricalPortfolioBacktest` request body has no TP/SL fields.
- `frontend/components/signals/portfolio-backtest-panel.tsx` — `PointInTimePortfolioBacktestPanel.launch()` sends only dates, capacity, capital, partial-fills. The only TP/SL wiring (`:640-641`) lives in `SnapshotAuditLegacyPanel`, which was removed from the tab and is unreachable.

**Change:** add optional TP/SL controls to the PIT panel (mirroring the legacy panel's enable-toggle + percent inputs), send them through `createHistoricalPortfolioBacktest`, and render the response's `barrier_scenario` alongside the baseline scenario when present. Validation: `0 < stop_loss_pct < 1`, `0 < take_profit_pct <= 10` (server returns 422 otherwise — surface the message).

**Blocking tests:** `services/api/tests/test_portfolio_backtest_panel.py` — TP/SL round-trips into the persisted run config; a run without TP/SL has no `barrier_scenario`; out-of-range values ⇒ 422. Plus `cd frontend && npm run build` green.

## Task 4 — Materialization cost guard (re-scoped Phase 4 item 0)

The parent contract's Phase-4 gate ("one 90-day benchmark chunk, stop if the projected sequential full rebuild exceeds 7 days") was never implemented. Implement it **re-scoped**: the measured baseline above shows the 7-day threshold can never fire for this methodology version, so a literal implementation would be dead code. What is actually missing is a guard against unbounded single-window rebuilds.

**Change** in `services/worker/tasks/historical_portfolio_backtest.py` and the materializations route:
- Reject at 422 any single materialization request whose window exceeds `MATERIALIZATION_MAX_WINDOW_DAYS` (set to 120) — callers must chunk. The API route already chunks; this guards direct/worker invocation and the scheduler.
- After a chunk succeeds, persist into `progress_json` a `projection` object: measured seconds per decision-date, and the projected total for the caller's full requested range. Log it.
- Keep the existing per-stage timings; they are the input to the projection.

**Blocking tests:** over-long window ⇒ 422 naming the limit; a succeeded chunk carries a `projection` with the per-stage timings; existing materialization tests unchanged.

## Task 5 — Missing blocking tests from the parent contract

Add the blocking tests the parent contract lists that do not exist. Each must fail if its guarantee is removed:

- Migration `b4c8e2f6a913` up/down on a scratch database; v4 backfill produces a schema-complete `decision_json` (every key present); unique-key `(methodology_version, decision_date, symbol, horizon, variant)` enforcement.
- Injected unexpected builder exception ⇒ run `failed` in a separate transaction, `error_message` preserves exception type and message, previous ledger rows unchanged.
- Barrier precedence: same-open short-signal liquidation outranks a TP/SL fill; scheduled-exit cancellation conserves cash (exactly one exit per lot).
- Liquidation counterfactual never alters cash, holdings, equity curve, or canonical statistics.
- Opportunity `input_hash` values are unchanged by run-level TP/SL config.
- `/decisions`: route order (declared before `/{run_id}`), each filter applied independently, and the **v4** `winners_only` semantics (`accepted=true` + `winner_semantics:"v4_legacy_accepted_edge_policy"`).

## Non-goals

No statistical-methodology change of any kind (no PSR/DSR/MinTRL, no BH/FDR, no revised gates) — Rev 6 owns those, and touching them here invalidates the frozen v5 baseline. No `METHODOLOGY_VERSION` bump. No re-materialization of the existing v5 ledger: none of these tasks changes persisted decision values except Task 1, which affects the live dashboard path only (materializer passes explicit date tuples and keeps the ⌊2n/3⌋ branch). No reinstatement of auto gap-fill on launch. No change to `accepted` or any v4 row.

## Acceptance

- `pytest core/tests -q`, `pytest services/api/tests -q`, `pytest services/worker/tests -q`, and `cd frontend && npm run build` all green.
- Tasks 1, 2 and 5 each ship with at least one test that fails against the current code and passes after the change.
- Task 2's report distinguishes the three mismatch classes with per-reason counts; any `suspected_defect` found against the live snapshot table is triaged before release.
