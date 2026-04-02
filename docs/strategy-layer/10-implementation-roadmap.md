# Strategy Layer — Implementation Roadmap

## Summary

Implementation should follow an order that respects business dependencies. The Strategy page is not just a collection of UI components; it is a chain of decisions.

The recommended order is:

1. docs and domain model — **done**
2. saved strategies + header + left rail — **done**
3. Universe — **done**
4. Signal — **done** (zone chart, consensus, family toggles, batch scores, regime consensus)
5. Execution — **done** (levels, statuses, trade geometry preview)
6. Sizing — **done** (Kelly, allocation, constraints)
7. Review + Backtest handoff — **partial** (review section exists, backtest preload not yet wired)

---

## Phase 1 — Docs and Domain Model ✓

### Goal

Establish the shared language and the saved-strategy business model.

### Deliverables

- `docs/strategy-layer/` documentation set ✓
- central saved-strategy type ✓
- strategy status model ✓
- baseline CRUD surface ✓

### What was built

- 11 documentation files covering all layers
- `saved_strategy` DB table with `config_json` (alembic migration `g7h8i9j0k1l2`)
- Backend CRUD: `GET/POST /strategies`, `GET/PUT /strategies/{id}`, `POST /strategies/{id}/duplicate`, `PATCH /strategies/{id}/archive`
- Frontend: `useStrategies` SWR hook, `createStrategy`, `updateStrategy`, `duplicateStrategy`, `archiveStrategy` API functions

---

## Phase 2 — Saved Strategies, Header, and Left Rail ✓

### Goal

Give the page a durable workspace structure.

### What was built

- `StrategyRail` component: lists saved strategies with status badges, create/duplicate/archive actions
- `StrategyHeader` component: editable name, note, side policy toggle (`long_only`/`long_short`), horizon selector, save/duplicate/archive buttons
- Pipeline stepper bar showing progression through the 4 layers (Universe → Signal → Execution → Sizing)
- All CRUD flows functional end-to-end

---

## Phase 3 — Universe ✓

### Goal

Enable composition of the strategy basket.

### What was built

- `POST /strategy/universe` endpoint: sector filter, min signal threshold, liquidity filter, returns candidates with scores
- `UniverseSection` component: candidate table with signal scores, sector badges, selection checkboxes
- `UniverseSidebar` component: stock sidebar for focused stock selection from basket
- Basket persists in `config_json.universe.basket` and `sector_filter`

---

## Phase 4 — Signal ✓

### Goal

Turn signal-engine outputs into a configurable strategy consensus.

### What was built

**Backend:**
- `POST /strategy/signal-consensus` — aggregate consensus for focused stock
- `POST /strategy/signal/batch-scores` — multi-symbol signal scoring for universe table
- `POST /strategy/signal/regime-consensus` — regime-aware consensus
- `POST /strategy/signal/zone-chart` — per-bar family scores, zones, transitions, indicator data for candlestick overlay
- `compute_family_score_timeseries()` in `core/quant_core/signal_engine/ensemble.py` — weights representative variants by reliability score

**Frontend:**
- `SignalSection` component: consensus bar, family toggles with per-family score bars, signal zone chart
- `SignalZoneChart` component (lightweight-charts v5): candlestick chart with per-family zone bands (support/resistance/hold), indicator overlay lines, entry/exit arrow markers
- `SignalScoreBar` component: visual score indicator
- SWR hooks: `useSignalConsensus`, `useSignalZoneChart`

---

## Phase 5 — Execution ✓

### Goal

Convert consensus into concrete trade plans.

### What was built

- `POST /strategy/execution` endpoint: computes levels, entry zone, stop/target, trade statuses, R:R
- `POST /strategy/levels` endpoint: swing levels + pivots + confluence
- `ExecutionSection` component: trade status display, entry/hold/exit logic configuration, levels table
- `LevelsSection` component: support/resistance levels with confluence badges
- Execution parameters (entry_threshold, holding_threshold, atr_multiplier, buffer_pct, min_rr) editable in the strategy config and persisted

---

## Phase 6 — Sizing ✓

### Goal

Produce individual and portfolio position sizing.

### What was built

- `POST /strategy/sizing` endpoint: Kelly ceiling, allocation methods (equal_weight, inverse_vol, signal_weighted), position/sector constraints
- `SizingSection` component: allocation table, Kelly panel, exposure summary, constraint display
- Sizing parameters (account_equity, kelly_modifier, allocation_method, max_position_pct, max_sector_pct) editable and persisted

---

## Phase 7 — Review and Backtest Handoff (partial)

### Goal

Close the construction workflow with a readiness gate and a clean preload into Backtest.

### What was built

- `ReviewSection` component: readiness checklist summarizing config completeness across all layers
- Non-blocking warnings for missing basket, disabled families, unfavorable R:R

### Not yet implemented

- `Open in Backtest` action with full config preload
- Backtest page hydration from strategy payload
- Save → open in backtest integration flow

---

## Final Acceptance Expectations

The project can be considered ready when:

- the strategy exists as a stable saved object
- each section has an operational summary and readable detail
- dependencies between layers are coherent
- the left rail and header provide a real desk workflow
- the Backtest handoff is explicit and reversible
