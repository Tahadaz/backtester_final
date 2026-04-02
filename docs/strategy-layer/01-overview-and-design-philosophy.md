# Strategy Layer — Overview and Design Philosophy

## What

The `/strategy` page is a **strategy builder for a trading desk**. Its job is to take already-evaluated signals from the signal engine and convert them into:

- a tradable universe with capital allocation
- per-stock strategy configurations (indicator choices, entry rules, exit rules, risk parameters)
- a complete specification ready for walk-forward optimization and backtesting

Put differently: `/signals` produces **findings**, `/strategy` produces a **structured trading plan**, and `/backtest` produces **evaluation and WFO optimization**.

## Why

Even a robust signal engine is not enough to define a strategy. Several decisions remain open:

1. Which stocks should be in the basket, and how should capital be allocated?
2. What type of strategy is this — trend following or mean reversion?
3. Which indicator types and parameters should be used for each stock?
4. At what score thresholds should positions be entered or exited?
5. How much exposure per entry level? How much reduction per exit level?
6. What are the global risk parameters (stops, cooldown, position limits)?
7. Which of these parameters should be manually fixed vs WFO-optimized?

Without this layer, the application stays at the analysis level. With this layer, it becomes a decision system.

## Two Fundamental Strategy Types

The strategy page supports two fundamental approaches to using the same indicators:

### Trend Following

The strategy bets that a detected trend will continue. Entry happens when trend and momentum indicators confirm direction; RSI filters out overextended entries.

### Mean Reversion

The strategy bets that an extreme reading will revert. RSI becomes the primary signal; trend indicators act as filters to avoid fighting strong trends.

The same four indicator families (Tendance, Momentum, Oscillation, Volume) serve both types. The difference is not *which* indicators are used, but *how their scores map to entry and exit conditions*. See [04-strategy-type-layer.md](./04-strategy-type-layer.md) for details.

## Per-Stock Strategy Configuration

This is not a one-size-fits-all system. Each stock in the basket gets its own strategy tab with its own:

- strategy type (Trend Following or Mean Reversion)
- signal construction choices (indicator types, parameters or WFO scan ranges)
- entry rules (conditions + sizing per level)
- exit rules (conditions + exposure reduction per level)
- risk parameters (stop loss, take profit, cooldown, etc.)

Why per-stock? Because a bank stock and a mining stock on the Casablanca exchange may have fundamentally different volatility profiles, mean-reversion tendencies, and trend persistence. Forcing them into the same parameter set introduces unnecessary constraint.

An "Apply to all" template feature lets the user configure one stock and push the configuration to others — but each stock's config remains independently editable afterward.

## 5 Configuration Options (A–E)

Each entry rule and exit rule supports five levels of automation:

| Option | Rule Parameter | Sizing Parameter | User Freedom |
|--------|---------------|-----------------|--------------|
| **A** | Manual | Manual | Full manual control |
| **B** | Manual | Kelly from WFO | Manual rules, optimized sizing |
| **C** | WFO-optimized | Manual | Optimized thresholds, manual sizing |
| **D** | WFO-optimized | Kelly from WFO | Both optimized independently |
| **E** | Full WFO | Full WFO | WFO discovers number of levels, thresholds, and sizing jointly |

This spectrum lets the user control exactly how much freedom they delegate to the optimizer. A discretionary trader may prefer Option A or B. A systematic trader may prefer D or E. The architecture does not force a choice.

## Design Principles

### 1. Trading desk, not research dashboard

The page should not be overly compact. A desk operator needs:

- visual breathing room
- stable reading order
- collapsible sections that still feel readable
- obvious primary actions
- summaries that remain useful even when details are collapsed

An overly dense UI works for research but becomes tiring in a daily operational workflow.

### 2. Operational before analytical

Each section should answer "What should I do?" before "Why does the model think this?"

The design should favor:

- an operational summary first
- explanatory detail below or inside a drawer
- transparency that is available, but not dominant

### 3. Configuration and preview are separate concerns

The page deals with:

- an editable **strategy draft** (the user's choices)
- **computed previews** derived from that draft (what the backend calculates)

This separation is critical. The frontend must not confuse what the user wants to configure with what the backend computes from that configuration.

### 4. Strategy is not Backtest

The Strategy page prepares the strategy. It does not absorb the full responsibility of Backtest.

The logical split is:

| Strategy Page | Backtest Page |
|--------------|---------------|
| Build and save the trading plan | Configure WFO parameters (IS/OOS split, windows) |
| Define which parameters are manual vs WFO | Execute the optimization |
| Review readiness and parameter count | Review equity curves and PROM results |
| Hand off the strategy definition | Evaluate and compare WFO runs |

### 5. WFO-aware from design, not retrofitted

Every configurable parameter in the strategy carries an explicit flag: `manual` or `wfo`. The strategy definition is designed as a WFO input from the start. Parameters marked `wfo` include scan ranges (min, max, step) that define the optimization search space. The strategy page counts these parameters and warns when the total risks overfitting.

## Page Structure

```text
┌ Left Rail: Saved Strategies ┐  ┌ Main Workspace ──────────────────────────────────┐
│ search / new / duplicate    │  │ Header: name, note, status, actions              │
│ strategy list + status      │  │                                                   │
│ expandable stock summary    │  │ Portfolio Level (stays as-is across stocks):      │
│                             │  │   Universe + Capital + Allocation                 │
│                             │  │                                                   │
│                             │  │ Per-Stock Tabs (one tab per basket stock):        │
│                             │  │   1. Strategy Type                                │
│                             │  │   2. Signal Construction                          │
│                             │  │   3. Entry Rules                                  │
│                             │  │   4. Exit Rules                                   │
│                             │  │   5. Risk                                         │
│                             │  │   6. Review                                       │
└─────────────────────────────┘  └──────────────────────────────────────────────────┘
```

## What Stays Where

### Belongs on Strategy

- saved strategy state
- universe basket and capital allocation
- per-stock strategy type selection
- per-stock indicator construction choices
- per-stock entry and exit rules with configuration options
- per-stock risk parameters
- WFO flags and scan ranges for each optimizable parameter
- readiness review and WFO parameter count

### Stays on Signals

- deep transparency on signal variants
- the A → G signal-engine pipeline
- detailed representative drilldowns
- exhaustive per-family methodology
- indicator explorer

### Stays on Backtest

- WFO configuration (IS/OOS window sizes, walk-forward scheme)
- run execution
- equity curves, PROM metrics, performance evaluation
- WFO run comparison

## Inputs

- stock catalog and sector metadata
- signal engine outputs (indicator types, parameter ranges, OOS metrics)
- OHLCV data per symbol
- saved strategy draft

## Outputs

- a coherent, saveable strategy definition
- per-stock configuration with WFO flags
- operational summaries for each section
- a handoff payload ready to preload the Backtest page

## Edge Cases

- empty strategy with no selected stocks
- saved strategy that is no longer aligned with the latest data
- per-stock config that references an indicator type not yet available
- strategy with too many WFO parameters for the available data length

## Fallback

- if a section cannot produce a meaningful calculation, the page should show an explicit state rather than staying silent
- summaries should remain visible even if the detailed calculation is incomplete
- the strategy may still be saved with warnings, as long as the UI clearly separates "configured" from "ready"

## Future Extensions

- additional indicator families beyond the initial four
- multi-strategy portfolio management
- historized snapshots and strategy versioning
- scheduling and monitoring after Backtest
