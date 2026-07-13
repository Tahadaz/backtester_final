# Paper-Trading Desk — Implementation Plan

**Status: planned 2026-07-12, not yet implemented.**

## Context

Three pre-registered studies (2026-07-11/12: trend/WFO gating, value+momentum v1,
v2 confirmation) all concluded that the app's single validated edge is the B/M
six-vintage value strategy (Sharpe 1.62, IR 1.23 vs MASI, 51 months). The missing
piece between that validated backtest and something tradeable is not another
signal — it is the **operating program**: automated simulated execution against
live market data, with pre-registered monitoring and kill-switch rules.

No order-execution API exists for the CSE (verified 2026-07-12: e-bourse.ma is
web-only educational sim, no broker APIs among the 17 sociétés de bourse). The
desk therefore lives **inside the app** as the system of record; e-bourse.ma is
an optional human-entered mirror (~5-10 orders/month from a generated ticket;
note e-bourse simulates zero fees and enforces a hard 10% position cap with
3-day auto-liquidation, so the mirror needs the caps toggle on and will look
slightly flattered vs the cost-loaded desk).

Why this is not "just the backtest again": (1) PIT discipline enforced by
physics — every live month is data the strategy could not have been tuned on
(the 51-month backtest window is partially spent after three studies);
(2) it tests the *pipeline* (scheduler, late fundamentals, suspensions, stale
quotes) — historically where this app's real bugs lived (silent S3 empty-success,
statsmodels crash-loop, WFO staleness); (3) it measures real implementation
shortfall vs the flat 33bps assumption; (4) it is the only honest forward test
for the thin-history WFO layer. Expectation-setting: 6-12 months of paper
results cannot statistically *confirm* the edge — the desk's power is catching
failures (bugs, slippage, decay), not proving success.

## Books

| Book | Source of targets | Cadence | Budget |
|---|---|---|---|
| `value_core` | value strategy snapshot `current_holdings` (target_weight per symbol) | monthly, after `weekly_value_strategy_refresh` (Sat 20:45 UTC) | 80% of desk capital (100% if satellite disabled) |
| `wfo_satellite` (optional, off by default) | `signal_best_evidence_snapshot` actionable LONG signals (weekly horizon), entry/stop/target from evidence payload | weekly, after Monday's best-evidence snapshot | fixed 20% cap, fixed fractional sizing per position |

Caps toggle per book: sector_cap 0.30 / max_name 0.10 (reuse
`dashboard_portfolio._apply_sector_caps` semantics; required ON for the
e-bourse mirror).

## Architecture (reuse-first)

- **Tables**: reuse `DashboardPortfolio` (config), `desk_portfolio_position`,
  `desk_portfolio_fill`. Add `desk_order` (book_id, symbol, side, target_weight,
  qty, order_state pending|partial|filled|expired|cancelled, created_at,
  filled_at, limit_price nullable, slice_plan_json) and `desk_nav_history`
  (book_id, date, nav, cash, gross_exposure, benchmark_nav) via one Alembic
  migration.
- **Costs**: `core/quant_core/portfolio.py::CostModel` (brokerage + commission
  de bourse + TVA 10%) — NOT the research 33bps flat; record both so shortfall
  vs research assumption is measurable.
- **Fills**: daily fill-simulator job after `daily_market_refresh`: fill pending
  orders at the day's close from `market_data_store` (CSE data reality: open
  unreliable, close canonical), with **ADV participation cap** — max
  `min(order_qty, 20% × adv_20d/close)` shares/day; oversize orders slice across
  days (state `partial`); orders unfilled after 10 sessions expire with alert.
  A suspended/no-bar symbol simply doesn't fill that day (mirrors reality).
- **Order generation**: target weights → current positions diff; skip moves
  < 0.25% of NAV (churn floor); sells before buys; cash buffer 2%.
- **Scheduler**: two new `ScheduleSpec`s (`desk_rebalance_value` monthly-after-
  snapshot; `desk_fill_simulator` daily post-refresh) + dispatch branches in
  `scheduler_dispatch.py`, worker tasks under `services/worker/tasks/desk.py`,
  job-status via `SignalEngineBatchJob` rows (established pattern).
- **API**: new router `services/api/app/routers/desk.py` (`/desk/books`,
  `/desk/{book}/positions|orders|nav|ticket|events`), admin-only mutation
  endpoints (create book, toggle satellite, acknowledge kill-switch).
- **Ticket export**: `/desk/{book}/ticket` returns the pending order list
  (symbol, side, qty, last close, limit guidance) as JSON + CSV — the e-bourse
  mirror input.

## Monitoring & kill-switch (pre-registered — decide BEFORE go-live, never after)

Computed daily into `desk_nav_history`, surfaced in UI:

- **K1 (hard freeze)**: book drawdown > backtest maxDD + 5pts (value_core:
  −13.9% − 5 → freeze below −18.9%). Freezes new buys, alerts; manual ack to
  resume.
- **K2 (review)**: rolling 12m IR vs MASI below the 5th percentile of the
  block-bootstrap distribution of 12m IRs from the 51-month backtest
  (precompute the threshold once at go-live; store in book config).
- **K3 (exec-integrity)**: monthly realized shortfall (fill price vs signal-date
  close, incl. costs) > 150bps annualized over 3 months → data/execution bug
  hunt, not a strategy signal.
- **Expectation cone**: NAV chart overlays the bootstrap 5-95% cone of backtest
  monthly net returns from the value study, rebased at go-live.

## UI

New "Desk" tab on the Signals page (pattern: `signals-view-layout.tsx` +
`portfolio-backtest-panel.tsx`): NAV vs cone + MASI, positions table with
target-vs-actual drift, order ticket panel (copy/CSV for e-bourse), fills
ledger, kill-switch status banner, satellite sleeve sub-view.

## Implementation phases (Sonnet implements, orchestrator reviews)

1. **Migration + models + book config API** — tables, book CRUD, no jobs yet.
   Verify: alembic upgrade/downgrade clean, CRUD via curl.
2. **Order generation + fill simulator (value_core)** — pure functions in
   `core/quant_core/desk/` (order diff, ADV slicing, CostModel application)
   with unit tests (churn floor, slicing, partial fills, suspension, expiry);
   worker jobs + scheduler entries. Verify: E2E in Docker — seed book, force
   rebalance, force fills across 3 simulated days, inspect fills/NAV rows.
3. **Monitoring + kill-switches** — nav history job, K1-K3 evaluation,
   precomputed K2 threshold script, alert wiring (existing ops alert path).
   Unit tests for each rule boundary.
4. **Ticket export + Desk UI** — API endpoints + frontend tab. Verify with
   real snapshot data end-to-end.
5. **WFO satellite (only after 1-4 stable)** — weekly entries from
   best-evidence longs, stop/target lifecycle in fill simulator, budget cap.
6. **Go-live checklist**: freeze kill-switch params in book config, record
   go-live date, first mirror ticket into e-bourse manually.

## Risks / decisions taken

- Fill realism on illiquid names is the weakest simulation link — mitigated by
  ADV slicing + K3, and honestly disclosed: paper fills at close are optimistic
  vs real spreads. The desk measures *relative* discipline, not exact P&L.
- Monthly cadence means slow feedback; do not shorten the strategy's horizon to
  make the desk more entertaining.
- e-bourse mirror is optional and manual by design (ToS + fragility; monthly
  cadence doesn't justify browser automation).
