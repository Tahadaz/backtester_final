# Strategy Layer — API, Data Flow, and Frontend Contracts

## What

This document describes the expected data movement between:

- the saved strategy
- backend previews
- frontend state
- the Backtest handoff

The goal is not to freeze every field name prematurely, but to lock down the **responsibilities and contract boundaries**.

## Core Principle

The frontend handles two different classes of data:

1. **Draft state**
   the editable strategy configuration
2. **Preview state**
   the computed outputs derived from that draft

Failing to separate those two classes creates common bugs:

- overwriting the draft with a preview
- treating a computed result as a user preference
- losing traceability of edits

## Saved Strategy CRUD Surface

The backend should support a high-level CRUD surface for saved strategies:

- list strategies
- get strategy
- create strategy
- update/save strategy
- duplicate strategy
- archive strategy
- unarchive strategy

The left rail depends directly on this contract.

## Saved Strategy Shape

The expected behavioral contract is:

```ts
type StrategyMeta = {
  id: string
  name: string
  note: string
  status: "draft" | "modified" | "saved" | "archived"
  side_policy: "long_only" | "long_short"
  created_at: string
  updated_at: string
}

type StrategyConfig = {
  context: unknown
  universe: unknown
  signal: unknown
  execution: unknown
  sizing: unknown
}

type StrategySnapshot = {
  left_rail_summary?: unknown
  signal_summary?: unknown
  execution_summary?: unknown
  sizing_summary?: unknown
  review_summary?: unknown
}
```

Concrete field details may evolve, but the `meta / config / snapshot` distinction should remain stable.

## Preview Endpoint Families

Each computed layer should have a dedicated preview or a coherent equivalent:

- Universe preview
- Signal preview
- Execution preview
- Sizing preview
- Review preview, if server-computed

Why split previews?

- layers do not always have the same compute cost
- the frontend can refresh sections independently
- the user can modify one layer without invalidating the entire page visually

## Expected Section Contracts

### Universe

Input:

- universe config from the draft
- current horizon
- liquidity filter inputs such as `minimum_avg_daily_volume`

Output:

- candidate list
- candidate liquidity field such as average daily volume
- selected basket summary

### Signal

Input:

- signal config (policy, enabled families)
- focused stock

Output:

- final consensus
- enabled families
- current family weights
- basket signal summary

#### Signal Zone Chart (implemented)

`POST /strategy/signal/zone-chart` — per-bar zone data for candlestick overlay.

Input:
- `symbol`, `horizon`, `enabled_families[]`, `entry_threshold`, `holding_threshold`
- optional: `timeframe` (default `1D`), `cost_bps`, `cooldown_bars`

Output per family:
- `scores: number[]` — per-bar consensus on `[-100, +100]`
- `zones: string[]` — `entry_long | entry_short | hold | flat`
- `representatives: { variant_id, weight, label }[]`
- `indicator: { type, name, ...values } | null`

Output global:
- `bars: { date, open, high, low, close, volume }[]`
- `transitions: { bar_index, date, from_zone, to_zone, family, price }[]`

Indicator shapes returned by the backend:
- `overlay`: `{ type, name, values: number[] }` — drawn on price pane (e.g. SMA)
- `overlay_dual`: `{ type, name, fast: number[], slow: number[] }` — two lines on price pane (e.g. SMA cross)
- `secondary_yaxis`: `{ type, name, ...}` — oscillator data (RSI, MACD, OBV) — not yet rendered on frontend

### Execution

Input:

- execution config
- adjusted consensus per stock
- price data and levels
- side policy

Output:

- focused stock plan
- per-stock statuses
- trade queue summary

### Sizing

Input:

- sizing config
- execution output
- adjusted consensus

Output:

- Kelly panel
- allocation table
- exposure summary
- constraint summary

## Focused Stock Propagation

The focused stock should be treated as shared frontend state across sections.

Rules:

- it is selected from the basket
- it does not modify the basket
- it determines which stock appears in detail inside Signal, Execution, and Sizing
- the remaining names stay visible in aggregated or tabular form

## Left Rail Contract

The left rail needs more than a simple list of strategy names:

- strategy meta
- status
- basket summary
- today's actionable side per stock (`buy / sell / neutral`) or explicit unavailable state

This can come from snapshot data or a dedicated summary endpoint, but the functional contract must be explicit.

## Backtest Preload Contract

The `Open in Backtest` action should send a preload payload containing:

- strategy id
- useful strategy meta
- full strategy config
- optionally useful snapshot data for initial rendering

Backtest should be able to:

- hydrate its form from that payload
- still allow review and edits before launching the run

## Failure Modes

### Partial preview success

The frontend should still be able to render the page even if:

- Universe is available
- Signal is calculable
- Sizing fails temporarily

The contract design should favor section-level independence with local error states.

### Stale snapshot

The snapshot may be older than the current draft.

Consequence:

- the frontend must prefer the draft for editable truth
- the snapshot is a summary, not an authority

## Frontend Responsibilities

- keep draft state locally during editing
- trigger relevant previews
- reflect `modified` status when needed
- clearly separate edited values from computed values

## Backend Responsibilities

- persist the draft
- compute previews
- guarantee business coherence of outputs
- provide a clean preload payload for Backtest

## Cross-Links

- The strategy domain is described in [02-strategy-domain-and-page-architecture.md](./02-strategy-domain-and-page-architecture.md)
- Final handoff behavior is defined in [08-review-and-backtest-handoff.md](./08-review-and-backtest-handoff.md)
