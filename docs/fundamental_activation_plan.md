# Codex Task — Connect the fundamental upgrade to the live app (ACTIVATION)

## Context
The rigor upgrade (per-stock beta, live WACC, 3-statement projection, PIT, signal backtest, per-model
UI sub-tabs) was implemented and unit-tested, but several pieces are **built-but-not-wired**, so the
running app still behaves like before. This task makes them live. **No new financial methodology is
needed — only activation, two bug fixes, and a UI cleanup.** Reuse existing code; do not re-architect.

Repo: `C:\Users\taha\Downloads\backtester_signal_engine_autoaccept`. Backend-first, then UI.
Betas require only price data (already in `market_data_store`) — independent of the Gemini backfill,
so beta can be activated immediately.

---

## A. Activate per-stock beta  (highest priority — currently inert)

**Problem:** `services/api/app/services/fundamental_beta.py::compute_beta_from_market_data` /
`upsert_beta_history` are referenced **only in tests**. `FundamentalBetaHistory` is empty in the real
app, so `services/api/app/services/fundamentals.py:2148` falls back to `beta = 1.0` for **every** stock
→ flat WACC = 7.86% everywhere → the Beta tile shows provenance `"default"`. The feature is dead.

**Build:**
1. **Universe driver** in `fundamental_beta.py` (or `fundamentals.py`):
   `recompute_universe_betas(db, *, as_of: date | None = None, window_years=2.0, frequency="weekly",
   proxy_symbol="MASI") -> dict` that:
   - resolves symbols via the existing `_signal_backtest_symbols(db, universe="full_masi")`;
   - for each symbol calls the existing `compute_beta_from_market_data(db, symbol, ...)` (it already
     loads stock + `proxy_symbol` daily closes via `load_ohlcv_for_symbol`) → `upsert_beta_history(db, est)`;
   - skips names with insufficient price history; returns a summary `{computed, skipped, liquidity_flagged}`.
   - Confirm the market proxy symbol that actually exists in `market_data_store` (MASI vs MASI_20) and
     use it; make it a parameter.
2. **On-demand endpoint** `POST /fundamentals/recompute-betas` in `routers/fundamentals.py`, guarded
   like the other admin fundamentals endpoints, that runs the driver and returns the summary.
3. **Scheduled worker task** `services/worker/tasks/refresh_fundamental_betas.py` following the exact
   pattern of `refresh_stockanalysis_fundamentals.py`; register it in `scheduler_registry.py` /
   `scheduler_dispatch.py` (e.g. weekly).
4. **Run it** (the endpoint) so `FundamentalBetaHistory` is populated for the universe.

**Acceptance:** after running, `GET` any covered stock shows `assumptions.beta != 1.0` for most names
and `provenance.beta == "beta_history"`; a high-beta and a low-beta name have **different** WACC.

---

## B. Recompute valuations so the app reflects beta + projection

Persisted `FundamentalValuationResult` / `FundamentalEnsembleResult` were computed under β=1.0 and may
predate the projection engine. After A, run a **universe-wide recompute** using the existing
`recompute_symbol_valuations_all_scenarios` (`fundamentals.py:2438`) for every covered symbol so each
stock's stored valuations use its **beta-derived WACC**, the **shared projection** (`build_projection`),
and the **integrity checks**. Add an admin endpoint/worker if one doesn't already cover the full
universe; otherwise reuse the existing recompute route.

**Acceptance:** stored fair values change vs. pre-recompute for high/low-beta names; ensemble
`model_weights` and `cost_of_capital_build_up` are populated; projection integrity surfaces in the
model panels.

---

## C. Fix the two persistence bugs (block the assumptions tab + backtest exhibit)

1. **Signal-backtest `StaleDataError`** — `fundamentals.py::run_and_persist_fundamental_signal_backtest`
   (~1412–1479). It INSERTs a `status="running"` row + `db.flush()` (~1443), then a downstream helper
   leaves the session rolled-back/expired, so the final `db.flush()` (~1477) UPDATEs 0 rows →
   `sqlalchemy.orm.exc.StaleDataError`. Fix: persist resiliently — single end-of-function persist, or
   re-`merge`/re-add after the try/except so both success and failure paths leave exactly one row; the
   `except` path must still persist a `failed` row even if the session was invalidated (`db.rollback()`
   then add fresh). Test: `services/api/tests/test_fundamental_signal_backtest_api.py`.
2. **Assumption-override `InvalidRequestError: Could not refresh instance`** — the
   `PUT /fundamentals/stocks/{symbol}/assumptions/{scenario}/override` write path. It toggles prior
   override `is_current=False`, inserts the new one, commits, then `db.refresh(new)` which fails. Fix:
   don't `refresh()` a possibly-unreloadable instance — re-`SELECT` the current override by
   `(symbol, scenario, is_current=True)` after commit, or build the response from known attributes.
   Test: `services/api/tests/test_fundamentals_assumption_overrides.py`.

---

## D. Finish the UI consolidation (so it visibly differs)

`frontend/components/strategy/signal-fundamental-view.tsx`:
- **Remove the `estimates` and `comparables` entries** from `FUND_TABS` (line ~159). Final top tabs:
  `These · Valorisation · Hypotheses · Qualité & ROE · Backtest`.
- Ensure the **shared operating projection / estimations** content renders in the Valorisation
  **`[Synthèse]`** sub-tab, and the **comparables** view renders as the **`[M. relatif]`** sub-tab
  content (the per-model sub-tabs + `FootballField` already exist at ~3021/3075/3079/3087 — keep them).
- Ensure the **Beta / WACC build-up** (StatTiles ~2721–2723) shows the real value + provenance now that
  A/B populate it.

**Acceptance:** top tab bar has 5 tabs (no standalone Estimations/Comparables); Valorisation shows
`[Synthèse]` + one sub-tab per model; Beta tile reads a real per-stock beta with provenance `beta_history`.

---

## E. Verification (must pass before "done")
- `python -m pytest services/api/tests/ -q` **green on its own** (not bundled with `core/`).
- `cd frontend && npx tsc --noEmit` clean.
- Manual end-to-end (document the steps + results in the PR):
  1. `POST /fundamentals/recompute-betas` → summary shows betas computed.
  2. Universe valuation recompute → a high-beta and low-beta stock show **different WACC and fair value**.
  3. `POST /fundamentals/signal-backtest` → returns a **persisted** result (no 500).
  4. `PUT …/assumptions/{scenario}/override` → **200** with the saved override.
  5. App (dev build) shows 5 top tabs, Valorisation sub-tabs populated, Beta provenance `beta_history`.

## Constraints
- Reuse existing scheduler/worker/endpoint/recompute patterns; minimal new surface area.
- Do **not** run the Gemini mass scrape (separate managed task). Betas/valuations run on existing data.
- The pre-existing `xbbg` Bloomberg-DLL test failures and the stale `MarketUniverseInstrument` args are
  out of scope (env / pre-Codex) — do not let them block this task.
- One commit per section (A–D); update the plan's `## Progress log`.

## Progress log

- 2026-06-01: Activated universe beta recomputation via service driver, admin endpoint, and weekly scheduler task; reused the existing universe valuation recompute route for section B; fixed signal-backtest and assumption-override persistence paths; consolidated the fundamental UI top tabs while keeping estimates/comparables inside Valorisation.
