# Factor Layer - Document Index

**Station mandate**: evaluate whether macro factors improve MASI equity signals under a no-look-ahead, horizon-aware, out-of-sample framework. The layer now covers pure factor research and the production Factor x TA runtime.

**Status**: Phase 0 and Phase 1 are complete. Phase 2 Factor x TA is implemented and stabilized as an additive runtime variant (`factor_x_ta`) for Signal Engine, WFO, factor diagnostics, and signal backtest/Monte Carlo replay.

---

## Document Map

| # | Document | Status | Description |
|---|---|---|---|
| 01 | [01-overview-and-research-question.md](01-overview-and-research-question.md) | Done | Research question, null hypothesis, scope, what this layer does and does not do |
| 02 | [02-literature-and-methodology.md](02-literature-and-methodology.md) | Done | Citation-backed methodology: BH-FDR, Newey-West, DSR/PSR, Harvey-Liu-Zhu, Grinold-Kahn |
| 03 | [03-universe-and-factor-selection.md](03-universe-and-factor-selection.md) | Pending | MASI shortlist, auto-expand rules, factor universe, economic channels |
| 04 | [04-calendar-alignment.md](04-calendar-alignment.md) | Done | Session timing, `precede_open` lag rule, staleness guard, no-look-ahead tests |
| 05 | [05-statistical-battery.md](05-statistical-battery.md) | Done | Formal metric definitions: IC, hit rate, DSR, PSR, BH-FDR, Sharpe, Sortino, drawdown |
| 06 | [06-descriptive-relevance-study.md](06-descriptive-relevance-study.md) | Done | Phase 0.9 descriptive factor relevance and channel validation |
| 07 | [07-phase1-factor-strategies.md](07-phase1-factor-strategies.md) | Done | Pre-registered factor-only rule specs |
| 08 | [08-api-data-flow-and-frontend-contracts.md](08-api-data-flow-and-frontend-contracts.md) | Done | Analytics API/data-flow/frontend contracts |
| 10 | [10-methodology-and-sources.md](10-methodology-and-sources.md) | Done | Deliverable summary of factor methodology and sources |
| 11 | [11-pre-registration.md](11-pre-registration.md) | Done | Pre-registration protocol and integrity rules |
| 12 | [12-phase2-scoping-note.md](12-phase2-scoping-note.md) | Done | Factor x TA scoping and evidence gates |
| 13 | [13-cross-product-variants.md](13-cross-product-variants.md) | Done | Production Factor x TA semantics, architecture, alignment, replay contract |
| 14 | [14-phase2-implementation-roadmap.md](14-phase2-implementation-roadmap.md) | Done | Implemented Phase 2 roadmap and stabilization notes |
| 15 | [15-phase2-pre-registration.md](15-phase2-pre-registration.md) | Done | Phase 2 pre-registration |
| 16 | [16-phase2-results.md](16-phase2-results.md) | In progress | Phase 2 empirical results |
| 17 | [17-factor-selection-runtime-contract.md](17-factor-selection-runtime-contract.md) | Done | Per-stock/horizon factor selection schema, monitoring, invalidation, UI contract |

---

## Current Runtime Architecture

- **Data layer**: macro factors live in `market_data_store` and are loaded through the same OHLCV loader as equities.
- **Factor selection layer**: `stock_factor_relevance` stores active top factors per `(symbol, selection_horizon)` where selection horizons are `short | mid | long`.
- **Runtime horizon adapter**: Signal Engine/WFO APIs use `weekly | monthly | quarterly`; the adapter maps them to `short | mid | long` for selection lookup.
- **Signal Engine variant**: `variant='factor_x_ta'` persists family rows as `{ta_family}@fx` in `signal_engine_family_result`.
- **WFO variant**: `variant='factor_x_ta'` persists category rows in `wfo_signal_summary`, including fold metadata.
- **Replay/backtest**: signal backtest and Monte Carlo rebuild the same Factor x TA AND-composed signal from persisted representatives and aligned factor arrays.

## Cross-layer Dependencies

- **Signal-generation layer** consumes `VariantDef.factor_condition` and `evaluate_variant_oos(..., precomputed_signal=...)`.
- **Backtest layer** consumes persisted `factor_condition` metadata and must not replay Factor x TA as native TA.
- **Dashboard and Signal UI** use `factor_x_ta` as a variant selector and read the shared persisted result tables.
- **Analytics layer** remains the read-only diagnostics surface for factor relevance and predictive ability.

## What This Layer Does Not Do

- It does not mutate native TA variants or change the native Signal Engine/WFO paths.
- It does not add fundamental data.
- It does not guarantee a macro factor is useful for every stock; empty selected sets and no-survivor states are valid `no_signal` outcomes.
