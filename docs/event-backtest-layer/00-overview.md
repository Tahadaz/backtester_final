# Event-Based Backtesting — Overview

## Document map

| # | Document | Contents |
|---|---|---|
| 00 | `00-overview.md` (this file) | What this layer adds, the four event types, phase map C1–C4 |
| 01 | [01-methodology.md](01-methodology.md) | `event_study.py` spec: AR/CAR/CAAR, BMP t-stat, block bootstrap, benchmark models, thin-trading handling |
| 02 | [02-event-sources.md](02-event-sources.md) | The four event-source adapters (`event_sources.py`) |
| 03 | [03-strategy-runner.md](03-strategy-runner.md) | `event_strategy.py`: events → signal series, replay integration, WFO integration |
| 04 | [04-multiple-testing.md](04-multiple-testing.md) | Pre-registered grid, BH/FDR policy, promotion gates |
| 05 | [05-phases.md](05-phases.md) | C1–C4 work packages: files, reuse, tests, E2E, done-criteria |

This is Plan C of the alt-data initiative. Shared foundation (PIT event store, validation policy, `/sentiment-events` UI) lives in [`../alt-data-foundation/`](../alt-data-foundation/00-overview.md); sibling plans are [`../sentiment-layer/`](../sentiment-layer/00-overview.md) (Plan A, news sentiment) and [`../macro-nowcast-layer/`](../macro-nowcast-layer/00-overview.md) (Plan B, macro nowcasting). This folder follows the `docs/factor-layer/` numbered-markdown convention (see `docs/factor-layer/00-INDEX.md`).

---

## What event-based backtesting adds

An **event study** measures the abnormal return around a dated, discrete event — not a continuous signal. Given a set of `(symbol, event_date)` pairs, it asks: relative to a benchmark expectation, how did the stock move in the days before/after the event, on average, across all events of this type? The output is an average-abnormal-return curve (AAR by relative day) and its cumulative form (CAAR), with a significance test that accounts for event-induced variance.

This is a fundamentally different research primitive from what the repo already has:

- **What exists today**: `services/api/app/routers/analytics.py::_build_macro_backtest_replay` (signature: `stock_prices`, `close_col`, `open_col`, `stock_close`, `aligned_factors`, `signal`, `spec`, `forward_returns`, `return_method`, `cost_bps`, `signal_threshold`). It consumes a **continuous** `{-1,0,+1}` position signal aligned to every session date, converts it to positions (`position[signal > threshold] = 1.0`, etc.), applies `cost_bps` on each position change, compounds `strategy_returns = position * forward_return - position_change * cost_rate` into an equity curve, tracks drawdown, and emits a trade ledger (`ACHAT`/`VENTE` rows with `prix_execution`, `equity`, `cout`). This is a **replay backtest of a signal that is already defined on every day** — it has no concept of "the 5 days before and 10 days after a sparse, dated event" and no abnormal-return/benchmark-adjustment math. It is the execution/P&L engine this layer reuses, not the event-study engine.
- **What is genuinely new**: there is no generic event-window utility anywhere in the repo — nothing computes AR, CAR, CAAR, a BMP-style significance test, or a thin-trading-aware event-day snap. `core/quant_core/research/event_study.py` (Phase C1, see [01-methodology.md](01-methodology.md)) is that missing primitive.

The two pieces compose: an event-study result answers "is this event type associated with a statistically real abnormal return, and in which direction?" (research question); the event-conditioned strategy runner (Phase C3) turns a validated event type into a signal series and feeds it into the **existing, unmodified** `_build_macro_backtest_replay` to answer "what would trading this look like, net of costs?" (P&L question). Both questions require the multiple-testing discipline in [04-multiple-testing.md](04-multiple-testing.md) before either result is trusted.

## The four v1 event types

| # | Event type | Source | Sign convention | Depends on |
|---|---|---|---|---|
| 1 | Company events / PEAD | `FundamentalCatalyst` (earnings, dividend, ex-dividend) | Post-earnings drift direction from surprise where known, else unsigned | Nothing — available immediately |
| 2 | Macro releases | `macro_release` ⋈ `nowcast_value`, signed by standardized nowcast surprise | `sign(surprise_z)`, filtered `\|z\| ≥ 0.5` | Macro-nowcast-layer **B5** (surprise engine) |
| 3 | Sentiment shocks | `alt_sentiment_daily`, `\|shock_z\| ≥ 2.0 ∧ n_items ≥ 5` | `sign(shock_z)` | Sentiment-layer **A5** (daily aggregates) |
| 4 | Geopolitical | GDELT Events (CAMEO roots 14–20, Goldstein ≤ −5) | Unsigned risk-off (`sign = −1`) | Sentiment-layer **A1** (GDELT connector, Events export) |

Full adapter specs (canonical output schema, filters, PIT snapping) are in [02-event-sources.md](02-event-sources.md).

## Phase map

```
C1 (event_study.py — the generic engine)
  → C2 (event_sources.py — four adapters, staggered availability)
       src 1 (PEAD)          : immediately, reuses FundamentalCatalyst
       src 2 (macro)         : after macro-nowcast-layer B5
       src 3 (sentiment)     : after sentiment-layer A5
       src 4 (geopolitical)  : after sentiment-layer A1
    → C3 (event_strategy.py — signal runner: replay path + WFO path)
       → C4 (event_study_registry.py — pre-registration, FDR, promotion gates)
```

C1 has no cross-plan dependency and can start immediately once `core/quant_core/research/` is available (it always is — no migration needed for C1 itself, since it operates on OHLCV price data already in `market_data_store`). C2's four adapters are independently gated as shown; C2 as a phase is "done" once all four adapters exist, but each adapter can be delegated and merged as soon as its dependency clears. C3 and C4 need only the event-source contract (canonical events DataFrame), not any specific adapter, so they can be built and tested against synthetic/PEAD-only events while later adapters land. Full phase-by-phase work packages, including cross-plan dependency callouts, are in [05-phases.md](05-phases.md).

## Cross-links

- Shared foundation, PIT join rule, table schemas: [`../alt-data-foundation/00-overview.md`](../alt-data-foundation/00-overview.md), [`../alt-data-foundation/01-pit-event-store.md`](../alt-data-foundation/01-pit-event-store.md)
- Sentiment layer (event sources 3 and 4's upstream data): [`../sentiment-layer/`](../sentiment-layer/00-overview.md)
- Macro nowcast layer (event source 2's upstream data): [`../macro-nowcast-layer/`](../macro-nowcast-layer/00-overview.md)
- Existing factor-layer calendar/alignment conventions this layer reuses: `docs/factor-layer/04-calendar-alignment.md`
