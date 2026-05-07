# Strategy Layer — Strategy Domain and Page Architecture

## What

The Strategy page is built around one central object: the **saved strategy**. That object must be rich enough to support:

- incremental editing
- explicit saving
- readable status
- per-stock configuration with WFO flags
- computed previews
- Backtest preload handoff

This is not just a local form; it is a proper business entity.

## Why

Without a saved-strategy object:

- the left rail has no durable content
- the `Save` action has no business meaning
- the handoff into Backtest becomes fragile
- the user cannot resume interrupted work cleanly

Persistence is what turns the page into a real workspace.

## Status Model

The strategy has an explicit state:

- `draft`: created but never stabilized
- `modified`: changed since the last clean save
- `saved`: currently clean and persisted
- `archived`: soft archived, hidden from the active list by default

These states tell the user whether the page represents an idea in progress, a finalized version, or old work that has been put aside.

## Top-Level Object

```ts
type StrategyDraft = {
  meta: StrategyMeta
  portfolio: PortfolioConfig
  stocks: Record<string, StockStrategyConfig>
  snapshot: StrategySnapshot | null
}
```

### `meta`

Contains identity and state:

- `id`
- `name`
- `note`
- `status`
- `created_at`
- `updated_at`
- `archived_at | null`

### `portfolio`

Contains portfolio-level configuration that stays constant across stocks:

- `universe` — filters, basket, capital
- `allocation_method` — equal weight, inverse volatility, signal-weighted, or WFO-optimized
- `account_equity`

### `stocks`

Contains per-stock strategy configuration. Each entry is keyed by symbol and contains:

- `strategy_type` — `trend_following` or `mean_reversion`
- `signal_construction` — per-family indicator type + parameters (or WFO scan ranges)
- `entry_rules` — list of entry rule objects (condition + sizing, each with config option A–E)
- `exit_rules` — list of exit rule objects (condition + reduction, each with config option A–E)
- `risk` — stop loss, take profit, cooldown, time stop, max position %, max sector %

Every numeric parameter in `signal_construction`, `entry_rules`, `exit_rules`, and `risk` carries a WFO flag:

```ts
type WFOParam<T> = {
  mode: "manual" | "wfo"
  value: T              // used when mode = "manual"
  scan_min?: T          // active range for the selected strategy horizon
  scan_max?: T
  scan_step?: T
  search_spaces_by_horizon?: {
    short: { scan_min: T; scan_max: T; scan_step: T }
    medium: { scan_min: T; scan_max: T; scan_step: T }
    long: { scan_min: T; scan_max: T; scan_step: T }
  }
}
```

The strategy still carries one strategy-wide `horizon` value. That selector lives in the **Signal Construction** section and determines which preset is surfaced in `scan_min / scan_max / scan_step` for previews, review, handoff, and WFO execution.

### `snapshot`

Contains the latest computed summaries, in read-only form:

- basket summary
- per-stock review summaries
- WFO parameter count
- review warnings

The snapshot is for display, comparison, and left-rail summaries. It is not for reconstructing the editable configuration.

## Page Architecture

### Top Level: Portfolio

The portfolio section sits above all per-stock content and contains:

1. **Universe** — filters, candidate list, manual selection, saved basket
2. **Capital** — account equity, allocation method
3. **Allocation** — how capital is distributed across basket stocks

This section applies to the entire strategy and does not change when switching between stock tabs.

### Per-Stock Tabs

Below the portfolio section, each stock in the basket gets its own tab. Within each tab, 6 configuration sections appear in order:

1. **Strategy Type** — Trend Following or Mean Reversion
2. **Signal Construction** — indicator type, strategy horizon, and parameters per family
3. **Entry Rules** — list of entry conditions + sizing
4. **Exit Rules** — list of exit conditions + exposure reduction
5. **Risk** — stop loss, take profit, cooldown, time stop, position limits
6. **Review** — per-stock summary, WFO parameter count, readiness

### "Apply to All" Template

The user can configure one stock fully and then push that configuration to all other stocks in the basket. This is a convenience feature — after applying, each stock's configuration remains independently editable.

The template operation copies:
- strategy type
- signal construction choices
- entry rules
- exit rules
- risk parameters (except max position % and max sector %, which remain per-stock)

## Structural Roles

### Left Rail

The left rail shows **saved strategies**, not the stock universe.

Each row should show:

- strategy name
- status badge
- number of stocks in basket
- collapsible stock list with per-stock readiness indicator

The rail answers: "Which strategies am I actively working on?"

### Header

The header answers: "Which strategy am I editing, and what are my global actions?"

It contains:

- name (editable)
- short note
- status chip
- `Save`
- `Open in Backtest`
- `Duplicate`
- `Archive`

### Review / Handoff

The review section at the bottom of each stock tab summarizes all choices and flags WFO parameters. A global review aggregates across all stocks and produces the Backtest handoff payload.

## Why Backtest Stays Separate

Backtest should remain a distinct page for three reasons:

1. **Separation of responsibilities** — Strategy builds the trading plan; Backtest configures the WFO evaluation and runs it.

2. **Cognitive load** — Mixing business construction and WFO configuration in one screen would overload the control surface.

3. **Auditability** — The payload sent to Backtest should be explicit, inspectable, and reviewable before launching a run.

## Inputs

- an existing saved strategy or a new draft
- stock catalog and sector data
- signal engine outputs (available indicator types, parameter ranges)
- computed previews by section

## Outputs

- modified draft with per-stock configurations
- refreshed snapshot
- preload payload for Backtest

## Edge Cases

- duplicated strategy with an outdated snapshot
- archived strategy later restored
- stock removed from basket while its tab is active
- empty strategy name
- saved strategy with business warnings

## Fallback

- if the snapshot is missing, the page should still render from the draft with explicit placeholders
- if a stock tab references parameters that cannot be previewed, the UI should show a pending state, not made-up data

## Public Interface Expectations

The backend should expose high-level operations for:

- list strategies
- get strategy
- create strategy
- update strategy
- save strategy
- duplicate strategy
- archive / unarchive strategy

The frontend should treat preview operations as separate from CRUD operations.
