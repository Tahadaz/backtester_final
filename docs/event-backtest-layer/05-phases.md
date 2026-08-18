# Phases C1–C4 — Work Packages

Each phase is a self-contained delegation unit per the execution model in [`../alt-data-foundation/00-overview.md`](../alt-data-foundation/00-overview.md#execution-model): goal, files, reuse targets, tests, E2E verification, done-criteria, dependencies. Specs live in the sibling docs — this file is the checklist, not a re-statement of design; on any conflict, the numbered spec doc wins.

---

## C1 — Generic event-study utility

**Goal**: ship `run_event_study` + `EventStudyConfig` + `EventStudyResult` per [01-methodology.md](01-methodology.md), including the thin-trading/stale-bar machinery. This is the layer's only genuinely new statistical primitive.

**Files to create**
- `core/quant_core/research/event_study.py` — config dataclass, result dataclass, `run_event_study`, stale-bar detection, trade-to-trade return computation, event-day snap, three benchmark models, BMP t-stat, block bootstrap.
- `core/tests/test_event_study.py` — synthetic-CAAR recovery, thin-trading fixtures, benchmark-equivalence checks (full test plan in [01-methodology.md](01-methodology.md#test-plan)).

**Files to modify**: none. C1 is pure library code — no DB models, no migration, no router, no scheduler.

**Reuse**
- Price loading convention: callers pass `prices` dicts built from `load_ohlcv_for_symbol` (`services/api/app/routers/analytics.py` usage pattern); `event_study.py` itself stays DB-free (pandas in, dataclass out) like `core/quant_core/wfo/`.
- No reuse of `research/stats/ic.py` — BMP and the block bootstrap are new, self-contained functions inside `event_study.py` (they share nothing with the Newey–West IC machinery).

**E2E verification**: none required beyond pytest (no runtime surface yet). Run `python -m pytest core/tests/test_event_study.py` inside the compose `api` container to confirm the environment (numpy/pandas versions) matches production.

**Done-criteria**
- All tests green, including injected-CAAR recovery within bootstrap CI on both the treated and control halves.
- `EventStudyResult.drop_reasons` populated correctly on the thin-trading fixtures.
- Docstring on `run_event_study` cites this doc folder.

**Dependencies**: none (does not even need the F1 migration — it operates on OHLCV already in `market_data_store`). Can start immediately, in parallel with A1/A2/B1/B2/F1.

---

## C2 — Four event-source adapters

**Goal**: ship `pead_events`, `macro_release_events`, `sentiment_shock_events`, `geopolitical_events` per [02-event-sources.md](02-event-sources.md), each returning the canonical `symbol / event_date / sign? / event_id` DataFrame.

**Files to create**
- `core/quant_core/research/event_sources.py` — all four adapters (each may land in a separate PR as its dependency clears; the module ships with source 1 plus empty-frame stubs for 2–4 that raise nothing and return the canonical empty schema when their tables/inputs are absent).
- `core/tests/test_event_sources.py` — per-adapter fixtures incl. the 18:00-straddle PIT test (see [02-event-sources.md](02-event-sources.md#pit-snapping--tested-per-adapter)); DB-backed tests use the sqlite-compatible model pattern from `services/api/tests/`.

**Files to modify**: none.

**Reuse**
- `FundamentalCatalyst` model (`services/api/app/models.py:1061`) — unchanged; note the earnings-confidence correction in [02-event-sources.md](02-event-sources.md#1-pead--company-events) (`event_date_confidence` is always `'estimated'` for earnings; filter on `event_date <= as_of` instead).
- `macro_release` / `nowcast_value` / `alt_sentiment_daily` models from the F1 migration ([`../alt-data-foundation/01-pit-event-store.md`](../alt-data-foundation/01-pit-event-store.md)).
- `fetch_gdelt_events_window()` from sentiment-layer A1 (`../sentiment-layer/01-data-sources.md`).
- Channel tags for basket fan-out: `FactorSignalSpec.channel_filter` values in `core/quant_core/research/factors/signals.py`.

**E2E verification** (staged): after source 1 lands — compose stack up, `python -c` snippet inside the api container calling `pead_events(db)` against the live DB; assert a non-empty frame with only past-dated earnings/dividend rows and no `is_active=False` rows. Sources 2–4 repeat the same probe as each upstream dependency ships.

**Done-criteria**
- Source 1 returns real rows from the live DB; sources 2–4 return schema-correct empty frames until their upstreams exist (no exceptions).
- PIT-straddle test passes for every adapter.
- No adapter performs the day-0 trading snap (that stays in `event_study.py`).

**Dependencies**: F1 migration for sources 2–3 table models. Cross-plan gating per adapter — **source 1: none (immediate); source 2: macro-nowcast-layer B5; source 3: sentiment-layer A5; source 4: sentiment-layer A1.** C2 is "phase-done" when all four exist, but C3 may begin once source 1 plus the canonical schema are merged.

---

## C3 — Event-conditioned strategy runner

**Goal**: ship `events_to_signal_series` + the replay path + `run_event_wfo` per [03-strategy-runner.md](03-strategy-runner.md).

**Files to create**
- `core/quant_core/research/event_strategy.py` — signal builder (hold/overlap/sign logic), replay-path helper that assembles the `_build_macro_backtest_replay` call, `run_event_wfo` with its `evaluate_window` closure and `(hold_days, threshold)` pool.
- `core/tests/test_event_strategy.py` — overlap-policy divergence, entry-lag (Open[d+1]) assertion, 2×2 WFO pool dominance (full list in [03-strategy-runner.md](03-strategy-runner.md#tests)).

**Files to modify**: none. `_build_macro_backtest_replay` (`services/api/app/routers/analytics.py:762`) is consumed untouched; `run_wfo_engine` / `WalkForwardConfig` / `ParameterRange` (`core/quant_core/wfo/`) are consumed untouched.

**Reuse**
- Execution semantics: `_macro_execution_price_series` (analytics.py:747) + `_next_index_dates` (analytics.py:741) — signal on session t executes at Open[t+1]; the signal series carries no embedded lag.
- WFO integration pattern: the `evaluate_window` closure shape from `core/quant_core/signal_engine/wfo_signal.py` (~line 535) — pool-index-keyed `WindowScoreResult` dicts.
- Test fixture style: `services/api/tests/test_macro_factor_replay.py` (`types.SimpleNamespace` spec, `pd.bdate_range` frames, ledger-side assertions).

**E2E verification**: compose stack up; script inside the api container that runs `pead_events` → `events_to_signal_series` → `_build_macro_backtest_replay` for one liquid symbol (e.g. ATW) at `cost_bps=25`, `return_method="open_to_open"`; assert the returned dict has non-empty `trade_ledger`, monotone `dates`, finite `equity[-1]`; then `run_event_wfo` on the same symbol with `ParameterRange(1, 15, 1)` hold-days and assert `EngineResult.windows` is non-empty with finite `wfe`.

**Done-criteria**
- Replay dict renders through the existing macro-replay response shape with `factor_close` absent/empty tolerated (frontend contract note in [03-strategy-runner.md](03-strategy-runner.md#replay-path--feeds-_build_macro_backtest_replay-unmodified)).
- WFO run produces per-window winner `(hold_days, threshold)` keys and aggregate `wfe` / `robustness_ratio` / `single_window_dominance`.
- Zero diffs under `services/api/app/routers/analytics.py` and `core/quant_core/wfo/`.

**Dependencies**: C1 (result types, day-0 snap) + C2 source 1 (real events for E2E; unit tests need only synthetic frames).

---

## C4 — Pre-registration, FDR, promotion, weekly suite

**Goal**: ship the frozen grid, the two-pass BH policy, the five promotion gates, and the Saturday scheduled suite per [04-multiple-testing.md](04-multiple-testing.md).

**Files to create**
- `core/quant_core/research/event_study_registry.py` — `EventStudyCell`, `REGISTERED_GRID` (60 cells), `REGISTERED_GRID_HASH`, `apply_fdr_policy(results)`, `evaluate_promotion_gates(cell_result, wfo_result)`.
- `services/worker/tasks/run_event_study_suite.py` — grid runner: adapters → `run_event_study` per cell → FDR passes → gates → verdict JSON to S3 `alt_data/studies/event_studies/{grid_hash}/{run_date}.json`.
- `core/tests/test_event_study_registry.py` — grid-hash stability, both FDR passes on constructed p-value sets, each promotion gate individually failing on a boundary fixture (n=29, CI touching 0, opposite-sign halves, OOS Sharpe = 0 at 25 bps).
- `services/worker/tests/test_event_study_dispatch.py` — dispatch-branch routing, mirroring `services/worker/tests/test_scheduler_dispatch.py`.

**Files to modify**
- `services/api/app/services/scheduler_registry.py` — add `"event_study_refresh"` to the `ScheduleKind` `Literal` and the `ScheduleSpec` (`cron="0 6 * * sat"`, `queue="market_refresh"`, `timezone="Africa/Casablanca"`).
- `services/worker/tasks/scheduler_dispatch.py` — dispatch branch for the new kind.

**Reuse**
- `benjamini_hochberg`, `bh_adjusted_pvalues` (`core/quant_core/research/stats/fdr.py`) — verified names, no changes.
- S3 verdict-artifact convention from [`../alt-data-foundation/02-validation-policy.md`](../alt-data-foundation/02-validation-policy.md).
- WFO gate inputs: `EngineResult` from C3's `run_event_wfo` at fixed 25 bps/side.

**E2E verification**: compose stack up (db + redis + worker + MinIO); trigger `event_study_refresh` via the ops endpoint (same path the scheduler tests use); confirm the RQ job completes and the verdict JSON exists in MinIO with the expected `grid_hash` path segment, one entry per grid cell, each carrying raw p / both q values / `n_events` / gate booleans; empty-upstream cells (sources 2–4 pre-dependency) must appear as `n_events=0`, gates-not-evaluated — not as absent keys.

**Done-criteria**
- Grid hash asserted in tests; any grid edit breaks a test by design.
- Verdict artifact schema documented in the module docstring and stable across runs.
- `/sentiment-events` "Études d'événements" panel ([`../alt-data-foundation/03-api-ui.md`](../alt-data-foundation/03-api-ui.md)) can read the artifact fields it needs (raw p, both q, n_events, promotion status) — panel wiring itself is U1 scope, not C4.

**Dependencies**: C1 + C3 (gates need both study results and WFO results); C2 source 1 for a real non-empty suite run. Sources 2–4 flow in automatically once A1/A5/B5 land — no C4 code change required, the suite simply stops seeing empty frames.

---

## Sequencing summary

```
C1 ──────────────► C3 ──► C4
C2.src1 ─────────►(C3 E2E)
C2.src4 ◄─ A1 ─┐
C2.src3 ◄─ A5 ─┼─ arrive whenever ready; no C3/C4 rework
C2.src2 ◄─ B5 ─┘
```

Critical path is C1 → C3 → C4 with only C2 source 1 needed en route; the other three adapters are drop-in data feeds behind a stable schema.
