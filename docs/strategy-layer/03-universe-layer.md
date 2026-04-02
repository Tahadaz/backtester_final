# Strategy Layer — Universe Layer

## What

The Universe layer decides **which stocks belong to the strategy** and how capital is allocated across them. Its final products are:

- a **selected basket of symbols**
- a **capital and allocation configuration**

Each stock in the basket then gets its own per-stock strategy tab for detailed configuration.

The target flow is:

```text
filters → candidate list → manual selection → saved basket → per-stock strategy tabs
```

## Why

A multi-stock strategy cannot be defined only by "the best signal today." It needs:

- coherent filtering rules
- an explicit basket
- the ability for the user to override mechanically generated candidates
- a clear capital allocation scheme

That combination matters. Filters provide discipline; manual selection provides control; per-stock tabs provide precision.

## How

### Step 1 — Apply filters

The v1 filters are:

- `sector`
- `minimum history`
- `signal threshold`
- `minimum_avg_daily_volume`

These filters are intentionally simple:

- sector: reflects a mandate or sector bias
- minimum history: avoids mixing thin-history names with long-history names
- signal threshold: removes names with no minimum conviction
- minimum average daily volume: prevents the strategy from including names that are too illiquid to trade realistically

On the Casablanca Stock Exchange, this liquidity gate is not optional. Some names trade at very low daily volume, and including them in the basket would make simulated fills largely fictional. A basic volume filter is therefore a survival requirement for any systematic strategy.

### Step 2 — Build candidate list

The candidate list should expose at least:

- `symbol`
- `name`
- `sector`
- `signal score`
- `average daily volume`
- `selected status`

The goal is to make selection readable, not to recreate a complex screening workstation.

### Step 3 — Manual selection

The user chooses which names actually belong to the strategy.

This step is necessary because:

- a strategy may want to keep a stock despite a temporarily neutral score
- a mechanical filter can surface several highly similar names
- the final basket decision has a business dimension, not just an algorithmic one

### Step 4 — Persist both basket and filter snapshot

Two separate things must be saved:

- `selected_symbols`
- `filters_snapshot`

Why keep both?

- the basket says "what I decided to include"
- the snapshot says "under what filtering context I made that decision"

Without the snapshot, the basket loses explainability.

### Step 5 — Per-stock strategy tabs

Each stock in the saved basket receives its own strategy tab below the portfolio section. The tab contains the 6 configuration sections described in [02-strategy-domain-and-page-architecture.md](./02-strategy-domain-and-page-architecture.md):

1. Strategy Type
2. Signal Construction
3. Entry Rules
4. Exit Rules
5. Risk
6. Review

This is where the strategy becomes per-stock. The universe layer creates the basket; the per-stock tabs configure the strategy for each name.

## Capital and Allocation

The portfolio section also includes:

- **Account equity** — total capital available for the strategy
- **Allocation method** — how capital is distributed across basket stocks:
  - Equal Weight: `weight_i = 1 / N`
  - Inverse Volatility: `raw_weight_i ∝ 1 / (ATR_i / Price_i)`, then normalized
  - Signal-Weighted: `raw_weight_i ∝ |signal_score_i|`, then normalized
  - WFO-optimized: optimizer determines weights (adds to WFO parameter count)

These are portfolio-level decisions that remain constant across per-stock tabs.

## Inputs

- stock catalog
- sector metadata
- signal score per symbol
- bar availability / minimum history check
- volume data from OHLCV history
- current universe config from the draft

## Outputs

- eligible and ineligible candidate list
- selected basket
- basket summary
- filter snapshot ready for persistence
- per-stock strategy tab structure

## Edge Cases

### Empty candidate list

If the filters return zero candidates:

- the section should show that state explicitly
- the current basket should not be destroyed automatically
- the user should be able to loosen filters

### Missing signal score

If a symbol has no score:

- it should remain visible if it exists in the catalog
- it should be marked as ineligible or unavailable
- it must not receive an invented default score

### Missing volume data

If a symbol has missing or unusable volume data:

- it should remain visible if it exists in the catalog
- it should be marked as ineligible
- it must not be silently included in the basket

### Missing sector

If a stock has no sector:

- it should remain visible as `Unknown`
- it must not be silently removed

### Basket / filter mismatch

If the basket contains a stock that no longer passes the current filters:

- the stock may remain in the saved basket
- the UI should show that it is outside the current criteria
- the page must not delete it implicitly

## Fallback

- no candidates: show an empty state and explain how to relax filters
- no sector: bucket as `Unknown`
- no score: show `unavailable` or `ineligible`
- no usable volume data: show `ineligible`

## Why This Is Not a Ranking Engine

Universe is not a ranking layer for three reasons:

1. the final strategy may use several stocks at the same time
2. pure ranking pushes the design toward a narrow "top pick" mindset
3. entry/exit rules and sizing need a basket, not just a winner

The core responsibility of this layer is **basket composition**, not podium selection.

## v1 Limits

- no multi-objective ranking
- no basket-scoring optimizer
- basic liquidity filter only (no bid-ask spread estimation, market impact modeling, or deeper fill realism)

## Cross-Links

- The basket feeds the per-stock strategy tabs: see [04-strategy-type-layer.md](./04-strategy-type-layer.md) through [08-risk-layer.md](./08-risk-layer.md)
- Capital and allocation interact with per-stock sizing in [06-entry-rules-layer.md](./06-entry-rules-layer.md)
- The "Apply to all" template feature is described in [02-strategy-domain-and-page-architecture.md](./02-strategy-domain-and-page-architecture.md)
