# 62 — Codex brief: SFC Portefeuille (fundamental strategy backtest tab)

**Goal**: a "Portefeuille SFC" view — the fundamental analog of the technical Portefeuille tab —
that replays the SFC strategy historically and shows what running it would have produced.

**Read first**: brief 59 (methodology), brief 60 (SFC implementation), doc 61 **including the
Reviewer caveats section** (its wording constraints apply to every number this tab displays),
`core/quant_core/fundamentals/cross_section/ic_study.py::tercile_backtest` (the seed of this
feature), and `services/api/app/routers/strategy_signals/_backtest.py::run_portfolio_backtest`
+ `frontend/components/signals/portfolio-backtest-panel.tsx` (the technical analog whose visual
language we reuse — but NOT its trade-replay mechanics; SFC is a rebalance-replay, not an
event-driven trade stream, and has no Kelly sizing).

---

## 1. Engine — `core/quant_core/fundamentals/cross_section/portfolio_backtest.py`

Pure function over a scored panel (reuse `panel.py` + `pillars.py` + `composite.py` with the
frozen `pmom_6_1` config; never re-open variant selection):

- **Rebalance grid**: monthly or quarterly (parameter), on the panel's as-of dates.
- **At each rebalance**: rank by SFC among names with valid scores and the liquidity screen;
  hold **top tercile, equal-weighted** (v1; bounded MASI-relative weights are Phase 2 of this
  brief, not v1). Bottom/middle terciles → not held. Long-only always. No Kelly.
- **Between rebalances**: buy-and-hold with PIT prices (same close-on-or-before convention as
  the panel; a name with no price on a date carries its last value — count and report staleness).
- **Costs**: one-way turnover × cost_bps × 2 sides at each rebalance (parameter: 33 default,
  75 stress; same formula as `tercile_backtest`).
- **Outputs**: equity curve (strategy, universe equal-weight benchmark, and MASI index if
  loadable from the market-data indices tables); per-rebalance rows (date, holdings in/out,
  turnover, period return, cost drag); summary stats (CAGR, annualized vol, Sharpe, max
  drawdown, hit-rate of rebalance periods, avg turnover, tracking stats vs the equal-weight
  universe); block-bootstrap p-value of the mean active return per period (reuse
  `significance.monte_carlo_luck_test`, block_mean matched to the rebalance overlap).
- **Split annotation**: every equity-curve point and summary is tagged
  `selection` (< 2023-07-31), `proof` (≥ split, ≤ study end), or `live` (> study end / after
  the Phase-2 go-live date). Summary stats are reported **per segment and combined** — the
  proof-segment row is the headline; the combined row is context.
- Look-ahead guards: reuse the panel's assertions; scores at date T use only availability ≤ T.

Tests (`core/tests/test_sfc_portfolio_backtest.py`, synthetic panels): turnover math (full
replacement = 1.0; no change = 0.0), cost drag arithmetic, a rigged panel where the known best
tercile wins, segment tagging around the split date, stale-price counting.

## 2. Persistence + API

- Extend the Phase-2 scheduler job: after each score recompute, run the backtest (monthly grid,
  33 bps) and upsert one snapshot row (`fundamental_sfc_backtest_snapshot`: config_hash,
  params_json, result_json, computed_at; alembic migration chained to current head).
- Router (fundamentals or analytics, match existing conventions):
  - `GET /analytics/sfc-portfolio-backtest` → latest snapshot (params echoed);
  - `POST /analytics/sfc-portfolio-backtest/run` → recompute with body params
    `{rebalance: "monthly"|"quarterly", cost_bps, start_date?, end_date?}` as an RQ job
    (panel building is DB-heavy — do NOT compute synchronously in the request; follow the
    existing backtest job/batch-status pattern), with a `GET .../status` poll.

## 3. UI — "Portefeuille SFC"

Placement: a sub-view inside the dashboard **Fondamental** mode (next to the SFC ranking),
reusing the visual components of `portfolio-backtest-panel.tsx` (equity chart, stat tiles,
period table). Requirements:

- Equity curve with the **selection/proof/live segments visually distinguished** (shading +
  legend) — never an unbroken curve implying uniform evidence quality.
- Headline stats from the **proof segment**, labeled "validé sur 2023–2026 (une seule période
  de marché)"; combined stats secondary. Live segment appears once real post-go-live
  rebalances exist.
- Controls: rebalance frequency, cost 33/75 toggle, date range. No Kelly, no side-policy
  control (long-only fixed, with a short explainer tooltip).
- Holdings table for the latest rebalance (name, sector, SFC, pillar chips, weight, in/out
  badge) — this doubles as "what the strategy holds today".
- French labels, correct accents.

## Constraints

- Frozen config only (`pmom_6_1`, config hash surfaced in the UI footer); any config change
  goes through a new IC-study run, not this tab.
- No changes to `edge.py`, the significance gates, or SFC pillar definitions.
- Doc-61 wording rules apply verbatim to all displayed claims.
- One commit per section (engine / persistence+API / UI); repo green each commit
  (pytest core + services, frontend build); `graphify update .` at the end.
- Ambiguities → append `## Open questions` here and stop.
