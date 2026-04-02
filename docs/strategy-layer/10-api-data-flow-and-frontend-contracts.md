# Strategy Layer — API, Data Flow, and Frontend Contracts

## What

This document describes the expected data movement between:

- the saved strategy
- backend previews
- frontend state
- the Backtest handoff

The goal is to lock down the **responsibilities and contract boundaries** while leaving room for field-level evolution.

## Core Principle

The frontend handles two different classes of data:

1. **Draft state** — the editable strategy configuration
2. **Preview state** — the computed outputs derived from that draft

Failing to separate those two classes creates common bugs:

- overwriting the draft with a preview
- treating a computed result as a user preference
- losing traceability of edits

## Strategy Definition Schema

### Full Saved Strategy

```ts
type SavedStrategy = {
  meta: StrategyMeta
  portfolio: PortfolioConfig
  stocks: Record<string, StockStrategyConfig>
  snapshot: StrategySnapshot | null
}

type StrategyMeta = {
  id: string
  name: string
  note: string
  status: "draft" | "modified" | "saved" | "archived"
  created_at: string
  updated_at: string
  archived_at: string | null
}

type PortfolioConfig = {
  universe: {
    filters: {
      sector: string | null
      min_history_bars: number
      signal_threshold: number
      min_avg_daily_volume: number
    }
    basket: string[]                    // selected symbols
    filters_snapshot: object            // frozen filter state at save time
  }
  account_equity: number
  allocation_method: "equal_weight" | "inverse_volatility" | "signal_weighted" | "wfo"
}
```

### Per-Stock Strategy Configuration

```ts
type StockStrategyConfig = {
  strategy_type: "trend_following" | "mean_reversion"
  
  signal_construction: {
    tendance: FamilyConfig
    momentum: FamilyConfig
    oscillation: FamilyConfig
    volume: FamilyConfig
  }
  
  entry_rules: EntryRule[]
  exit_rules: ExitRule[]
  risk: RiskConfig
}

type FamilyConfig = {
  enabled: boolean
  indicator_type: string              // e.g., "sma", "ema", "macd", "rsi", "obv"
  params: Record<string, WFOParam<number>>
}

type WFOParam<T> = {
  mode: "manual" | "wfo"
  value: T                            // used when mode = "manual"
  scan_min?: T                        // used when mode = "wfo"
  scan_max?: T                        // used when mode = "wfo"
  scan_step?: T                       // used when mode = "wfo"
}

type EntryRule = {
  id: string
  label: string
  config_option: "A" | "B" | "C" | "D" | "E"
  rule: {
    expression: string                // e.g., "trend_score > 2.0 AND momentum_score > 1.0"
    thresholds: Record<string, WFOParam<number>>
  }
  sizing: {
    mode: "manual" | "kelly_wfo" | "wfo"
    value?: number                    // manual exposure %
    kelly_modifier?: number           // for kelly_wfo mode
  }
}

type ExitRule = {
  id: string
  label: string
  config_option: "A" | "B" | "C" | "D" | "E"
  rule: {
    expression: string
    thresholds: Record<string, WFOParam<number>>
  }
  sizing: {
    mode: "manual" | "kelly_wfo" | "wfo"
    value?: number                    // manual reduction %
  }
}

type RiskConfig = {
  stop_loss: {
    mode: "manual_pct" | "atr_based" | "wfo"
    manual_pct?: number
    atr_multiplier?: WFOParam<number>
  }
  take_profit: {
    mode: "manual_pct" | "rr_target" | "wfo"
    manual_pct?: number
    rr_ratio?: WFOParam<number>
  }
  cooldown: WFOParam<number>          // bars
  time_stop: WFOParam<number>         // bars
  max_position_pct: number            // always manual
  max_sector_pct: number              // always manual
}
```

### Strategy Snapshot

```ts
type StrategySnapshot = {
  basket_summary: {
    count: number
    symbols: string[]
    sectors: Record<string, number>
  }
  per_stock_summaries: Record<string, {
    strategy_type: string
    wfo_param_count: number
    entry_rule_count: number
    exit_rule_count: number
    readiness: "ready" | "warning" | "blocking"
    warnings: string[]
  }>
  total_wfo_param_count: number
  global_warnings: string[]
  readiness: "ready" | "warning" | "blocking"
}
```

## WFO Flags

Every `WFOParam<T>` field in the strategy definition carries an explicit `mode` flag:

- `"manual"` — the `value` field is the parameter value; WFO does not touch it
- `"wfo"` — the `scan_min`, `scan_max`, `scan_step` fields define the search space for WFO

The backend counts all `mode: "wfo"` parameters to produce the `total_wfo_param_count`. This count is displayed in the review section and included in the backtest handoff.

## API Endpoints

### Strategy CRUD

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/strategies` | List all strategies (with optional status filter) |
| `POST` | `/strategies` | Create a new strategy |
| `GET` | `/strategies/{id}` | Get a strategy by ID |
| `PUT` | `/strategies/{id}` | Update/save a strategy |
| `POST` | `/strategies/{id}/duplicate` | Duplicate a strategy |
| `PATCH` | `/strategies/{id}/archive` | Archive/unarchive a strategy |

### Preview Endpoints

Each configuration section has a dedicated preview endpoint:

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/strategy/universe/preview` | Candidate list from filters |
| `POST` | `/strategy/signal-construction/preview` | Score preview for a stock with given indicator config |
| `POST` | `/strategy/entry-rules/preview` | Entry trigger preview on historical data |
| `POST` | `/strategy/exit-rules/preview` | Exit trigger preview on historical data |
| `POST` | `/strategy/risk/preview` | Stop/target/cooldown preview for a stock |
| `POST` | `/strategy/review` | Readiness checklist and WFO param count |

Why split previews:

- layers do not always have the same compute cost
- the frontend can refresh sections independently
- the user can modify one layer without invalidating the entire page visually

### Backtest Handoff

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/strategy/{id}/handoff` | Generate backtest handoff payload |

The handoff endpoint validates the strategy, counts WFO parameters, generates warnings, and produces the `BacktestHandoff` object described in [09-review-and-backtest-handoff.md](./09-review-and-backtest-handoff.md).

## Frontend State Management

### Draft State

The frontend maintains a local draft that mirrors the `SavedStrategy` structure. Edits are applied locally before being persisted.

Key rules:

- the draft is the single source of truth for user intent
- previews are derived from the draft but never overwrite it
- the `modified` status is set whenever the local draft diverges from the last saved version

### Section-Level Independence

Each section (Signal Construction, Entry Rules, Exit Rules, Risk) manages its own slice of the draft and its own preview state. This enables:

- independent refresh of previews
- section-level error states without blocking other sections
- parallel editing (user can jump between sections)

### Per-Stock Tab State

The active stock tab is a UI cursor. Switching tabs:

- saves any pending edits to the draft (in memory)
- loads the target stock's configuration
- refreshes previews for the new stock

### Computed Previews

What the backend derives from the strategy draft:

| Preview | Inputs | Output |
|---------|--------|--------|
| Universe candidates | Filters + catalog | Candidate list with eligibility |
| Score preview | Indicator config + OHLCV | Current scores, history, distribution |
| Entry preview | Entry rules + scores + OHLCV | Historical entry triggers |
| Exit preview | Exit rules + scores + OHLCV | Historical exit triggers |
| Risk preview | Risk config + ATR + entry price | Stop/target prices, cooldown windows |
| Review | All config | Readiness checklist, WFO param count |

## Failure Modes

### Partial preview success

The frontend should still render the page even if some previews fail:

- Universe is available
- Signal Construction preview succeeds
- Entry Rules preview fails temporarily

Each section should handle its own error state independently.

### Stale snapshot

The snapshot may be older than the current draft. The frontend must prefer the draft for editable truth. The snapshot is a summary for display, not an authority.

### Missing stock data

If a stock in the basket has no OHLCV data:

- that stock's per-stock tab should show a data availability warning
- previews for that stock return error states
- the review should flag it as blocking

## Backend Responsibilities

- persist the draft atomically
- compute previews per section
- guarantee business coherence of outputs
- count WFO parameters and generate warnings
- produce the handoff payload for Backtest

## Frontend Responsibilities

- keep draft state locally during editing
- trigger relevant previews on config changes
- reflect `modified` status when the draft diverges from saved state
- clearly separate edited values from computed values
- never allow a preview result to overwrite user configuration

## Cross-Links

- The strategy domain is described in [02-strategy-domain-and-page-architecture.md](./02-strategy-domain-and-page-architecture.md)
- Review and handoff behavior: [09-review-and-backtest-handoff.md](./09-review-and-backtest-handoff.md)
- Per-stock config sections: [04-strategy-type-layer.md](./04-strategy-type-layer.md) through [08-risk-layer.md](./08-risk-layer.md)
