# Strategy Layer — Review and Backtest Handoff

## What

The Review section is the **readiness gate** of the Strategy page. It operates at two levels:

1. **Per-stock review** — at the bottom of each stock tab, summarizing all configuration choices for that stock
2. **Global review** — aggregating across all stocks, producing the final handoff to Backtest

It answers three questions:

- What is configured?
- What is marked for WFO optimization?
- Is this strategy ready for backtesting?

## Per-Stock Review

Each stock tab ends with a review section that summarizes:

### Configuration Summary

| Section | Summary |
|---------|---------|
| Strategy Type | Trend Following / Mean Reversion |
| Signal Construction | Indicator types + parameters (or "WFO" for flagged params) |
| Entry Rules | Number of entries, config options used, conditions summary |
| Exit Rules | Number of exits, config options used, conditions summary |
| Risk | Stop/target/cooldown/time-stop settings |

### WFO Parameter Count

The review section counts and displays the total number of parameters flagged for WFO optimization for this stock:

```
Signal Construction:  3 WFO parameters (SMA period, MACD fast, OBV ema_period)
Entry Rules:          4 WFO parameters (2 thresholds × 2 entries)
Exit Rules:           2 WFO parameters (2 thresholds × 1 exit)
Risk:                 2 WFO parameters (stop ATR multiplier, cooldown)
                     ────
Total:               11 WFO parameters
```

### WFO Parameter Warnings

The review applies three levels of guidance:

| Total WFO Params | Status | Message |
|-------------------|--------|---------|
| 1–10 | OK | "Parameter count is within safe limits for WFO." |
| 11–15 | Warning | "Elevated parameter count. Ensure sufficient data history. Consider fixing some parameters manually." |
| > 15 | Danger | "High parameter count. Risk of overfitting is substantial. Reduce WFO parameters or extend data history." |

### Pardo's Degrees-of-Freedom Constraint

The total WFO parameter count must be evaluated against available data. Pardo (2008, Ch. 7) recommends:

```
IS_bars >= 10 × max_lookback
```

Where:
- `IS_bars` = number of bars in the in-sample window
- `max_lookback` = the longest lookback period among all indicators

Additionally, the total number of WFO parameters should be considered relative to the IS window size. With Moroccan stocks having 10–15 years of daily data (~2,500–3,750 bars), the practical limits are:

- Short horizon (IS = 252 bars): ~8 WFO parameters safe
- Medium horizon (IS = 504 bars): ~12 WFO parameters safe
- Long horizon (IS = 756 bars): ~15 WFO parameters safe

These are guidelines, not hard limits — but exceeding them significantly increases the risk that WFO finds in-sample patterns that do not generalize.

## What User Chooses vs What WFO Optimizes

This table should be prominently displayed in the review:

| User Chooses (Structure) | WFO Optimizes (Parameters) |
|--------------------------|---------------------------|
| Strategy type (TF / MR) | — |
| Indicator families to use | Indicator parameters (when flagged) |
| Number of entries (Options A–D) | Entry thresholds (when flagged) |
| Entry rule structure (which scores, operators) | Threshold values (when flagged) |
| Entry sizing mode | Sizing values (when flagged) |
| Number of exits (Options A–D) | Exit thresholds (when flagged) |
| Exit rule structure | Threshold values (when flagged) |
| Stop/target mode (ATR-based, etc.) | ATR multiplier, R:R ratio (when flagged) |
| Max position %, max sector % | — (always manual) |

For **Option E**: WFO also determines the number of entry/exit levels, so that shifts from the "user chooses" column to the "WFO optimizes" column.

## Ready / Not-Ready Checklist

The global review produces a readiness checklist:

| Check | Status | Blocking? |
|-------|--------|-----------|
| At least one stock in basket | Required | Yes |
| Each stock has a strategy type selected | Required | Yes |
| Each stock has at least one entry rule | Required | Yes |
| Each stock has exit rules OR risk parameters | Required | Yes |
| Stop loss configured for each stock | Required | Yes |
| WFO parameter count within safe limits | Recommended | No (warning only) |
| Pardo DF constraint satisfied | Recommended | No (warning only) |
| No indicator data issues (sufficient bars) | Required | Yes |
| All families referenced in rules are configured | Required | Yes |

**Blocking** items prevent the strategy from being sent to Backtest. **Warning** items allow the handoff but flag concerns.

## Soft Warnings, Not Hard Blocks

The review philosophy:

- Review surfaces weaknesses without unnecessarily locking the user
- Warnings reduce readiness quality, not editing freedom
- The strategy can be saved with any number of warnings
- The strategy can be sent to Backtest with non-blocking warnings

Examples of non-blocking warnings:

- WFO parameter count above 10
- Sizing based on placeholders rather than OOS metrics
- No exit rules (relying solely on risk parameters)
- R:R ratio of 1.0 or below

## Handoff to Backtest

### Save Before Backtest

The `Open in Backtest` action requires the strategy to be saved first.

Why:

1. Backtest needs a stable identifier or stable payload
2. The user should know exactly which version is being sent
3. It avoids opening Backtest on an implicit, untracked local state

### Handoff Payload

The handoff to Backtest includes the **full strategy definition**:

```ts
type BacktestHandoff = {
  strategy_id: string
  strategy_name: string
  portfolio: PortfolioConfig
  stocks: Record<string, StockStrategyConfig>  // all per-stock configs
  wfo_params: WFOParamManifest                 // which params are flagged for WFO
  total_wfo_param_count: number
  warnings: string[]
}
```

The `wfo_params` manifest explicitly lists every parameter marked for WFO, with its scan range:

```ts
type WFOParamManifest = {
  params: Array<{
    stock: string
    section: string        // "signal_construction" | "entry_rules" | "exit_rules" | "risk"
    param_name: string     // e.g., "sma_period", "entry_1_trend_threshold"
    scan_min: number
    scan_max: number
    scan_step: number
  }>
}
```

### Strategy vs Backtest Responsibility Boundary

| Strategy Owns | Backtest Owns |
|--------------|---------------|
| Business coherence | WFO window configuration (IS/OOS split) |
| Strategy configuration with WFO flags | Walk-forward scheme (anchored, rolling) |
| Readiness assessment | Actual optimization execution |
| Quality warnings | Equity curves, PROM, performance metrics |
| Handoff payload | Run comparison and selection |

## Inputs

- saved draft with all per-stock configurations
- computed WFO parameter counts per section
- data availability per stock (bar count, history length)
- save status

## Outputs

- per-stock review summaries
- global readiness checklist
- WFO parameter manifest
- handoff payload for Backtest

## Edge Cases

### Saved but weak strategy

A strategy can be saved while carrying several warnings. Review should reflect that honestly — the user may be iterating.

### Changed since last save

If the draft has changed since the last save:

- the page should show `modified` status
- the handoff should indicate the need to save again
- `Open in Backtest` should be disabled until saved

### Stock removed after review

If a stock is removed from the basket after the review was computed:

- the global review should recompute automatically
- the WFO parameter count should decrease accordingly

## Cross-Links

- The strategy domain model is defined in [02-strategy-domain-and-page-architecture.md](./02-strategy-domain-and-page-architecture.md)
- WFO parameter contributions come from [05-signal-construction-layer.md](./05-signal-construction-layer.md), [06-entry-rules-layer.md](./06-entry-rules-layer.md), [07-exit-rules-layer.md](./07-exit-rules-layer.md), and [08-risk-layer.md](./08-risk-layer.md)
- API contracts for the handoff: see [10-api-data-flow-and-frontend-contracts.md](./10-api-data-flow-and-frontend-contracts.md)
- Pardo's DF constraint: Pardo (2008, Ch. 7) — see [12-methodology-and-sources.md](./12-methodology-and-sources.md)
