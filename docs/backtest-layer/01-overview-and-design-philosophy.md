# 01 — Overview and Design Philosophy

---

## Purpose

The backtest page is the **evaluation station** of the platform — not a configuration station. Strategy definition (indicator selection, entry/exit rules, risk parameters, sizing preferences) happens on the strategy page (Phase 2). The backtest page takes a fully defined strategy and subjects it to rigorous statistical testing.

This distinction matters because it enforces a clean separation of concerns:

| Station | Responsibility | User action |
|---------|---------------|-------------|
| Signal page | Explore indicators, view signal quality | Understand what indicators are saying |
| Strategy page | Define trading rules, flag parameters for WFO | Design a strategy |
| **Backtest page** | **Evaluate the strategy through WFA** | **Discover whether it works** |

---

## Current State

The backtest page currently provides:

- **Strategy selector** — choose a saved strategy definition
- **Date range** — start and end dates for the backtest period
- **Cost model** — configurable transaction costs:
  - Brokerage fees
  - Commission
  - Slippage estimate
  - TVA (Moroccan value-added tax on financial services)
- **Volume gate** — minimum daily volume to consider a stock tradeable
- **Cooldown** — minimum bars between position changes

Results display: general metrics, sizing calibration, per-stock breakdown with trade ledger.

---

## WFO Mode Detection

When a strategy has parameters marked for WFO optimization (set on the strategy page), the backtest page detects this and enables WFO mode.

**Detection logic:**

```
strategy = load_strategy(strategy_id)

wfo_params = [p for p in strategy.all_parameters if p.optimize == True]

if len(wfo_params) > 0:
    mode = "WFO"
    # Add WFO configuration controls
    # Display WFO results sections
else:
    mode = "STANDARD"
    # Standard backtest with manual parameters
```

### WFO Configuration Controls (added when WFO mode detected)

| Control | Description | Constraints |
|---------|-------------|-------------|
| **WFO start date** | When the rolling walk-forward begins | Must leave sufficient data for IS + OOS windows |
| **Horizon** | Short / Medium / Long | Determines parameter ranges, lookback requirements, window sizes |
| **Test period** | Data after WFO period ends | Pure out-of-sample; never seen by optimization |

The WFO start date, combined with the strategy's horizon, determines how many walk-forward windows are feasible. The system computes this automatically and displays it before execution begins.

---

## Non-WFO Mode

When no parameters are flagged for WFO, the backtest page operates in **standard mode**: a single backtest run with the manually specified parameters. This mode is fully supported and unchanged from the current implementation.

Standard mode is useful for:
- Quick evaluation of a strategy idea before investing compute in WFO
- Strategies where the user has strong domain knowledge about parameter values
- Strategies with very few parameters that don't warrant full optimization
- Debugging and development

---

## Results Display Sections

### WFO Mode Results

When WFO mode is active, results are organized in three sections:

**Section 1 — WFO Results**
- Walk-Forward Efficiency (WFE) for the winning configuration
- Per-window detail table (analogous to Pardo Table 11.1):
  - IS window dates, IS PROM, IS parameter set
  - OOS window dates, OOS return, OOS profitable (yes/no)
- Optimization profile per IS window (% profitable, distribution check, shape check)
- Parameter evolution chart: how the optimal parameter drifts across IS windows
- Robustness assessment: n profitable OOS windows / total OOS windows

**Section 2 — Statistical Validation**
- Monte Carlo permutation test: p-value + equity curve fan chart (10,000 simulations, actual strategy overlaid on randomized curves with percentile bands)
- Deflated Sharpe Ratio: observed Sharpe corrected for multiple testing and non-normality
- Combined pass/fail assessment (all three metrics — WFE, Monte Carlo, DSR — must pass)

**Section 3 — Sizing Results**
- Win rate (from concatenated OOS trades)
- Average win / average loss ratio
- Kelly fraction
- These values replace the manually-input sizing values from the strategy page

**Section 4 — Test Period Results**
- Standard backtest metrics on data after the WFO period:
  - Equity curve
  - P&L
  - Sharpe ratio
  - Maximum drawdown
  - Trade ledger with entry/exit dates, prices, returns
- This data was never seen by any part of the optimization process

### Standard Mode Results

Unchanged from current implementation: general metrics, sizing calibration, per-stock breakdown with trade ledger.

---

## Design Philosophy

### Trust the process, not a single result

A single backtest result is a point estimate — it tells you what happened with one parameter set on one specific data window. Walk-Forward Analysis produces a **distribution of results** across multiple windows, revealing whether the optimization process itself is sound.

The question shifts from "Did this parameter set work?" to "Does optimizing this strategy reliably produce parameters that work on unseen data?"

### The backtest page evaluates; it does not configure

Every parameter, rule, and structural choice arrives from the strategy page. The backtest page's only degrees of freedom are:
- WFO start date (how much data to use)
- Cost model (transaction cost assumptions)
- Volume gate and cooldown (execution constraints)

This prevents the backtest page from becoming a secondary optimization surface. If users could tweak strategy parameters on the backtest page, they would effectively be running uncontrolled optimization — exactly what WFO is designed to prevent.

### Transparency over black boxes

Every intermediate result is visible:
- All IS windows with their optimization profiles
- All OOS windows with their returns
- The parameter evolution across windows
- The WFE computation with its components
- The Kelly sizing derivation from OOS trade statistics

The user can inspect any step of the process and understand why a strategy was accepted or rejected. There are no hidden heuristics.
