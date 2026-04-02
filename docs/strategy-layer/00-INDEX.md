# Strategy Layer — Architecture Documentation

> **Station mandate:** Transform evaluated signals into actionable, WFO-ready trading strategies — per-stock configurations that define universe, indicator construction, entry rules, exit rules, and risk parameters — ready for walk-forward optimization and backtesting.

*The fundamental insight driving this architecture: a signal is a finding; a strategy is a system. The signal layer discovers which indicators carry predictive power. The strategy layer decides how to use them — what to trade, when to enter, when to exit, how much to risk. These are different responsibilities and must not be collapsed into one page.*

---

## Documents

| # | File | Scope |
|---|------|-------|
| 01 | [overview-and-design-philosophy.md](./01-overview-and-design-philosophy.md) | Product philosophy, trading-desk UI principles, distinction between signals/strategy/backtest pages |
| 02 | [strategy-domain-and-page-architecture.md](./02-strategy-domain-and-page-architecture.md) | Saved-strategy model, portfolio-level header, per-stock tabs, left rail, status model |
| 03 | [universe-layer.md](./03-universe-layer.md) | Universe + capital + allocation: filters, basket composition, per-stock strategy tabs |
| 04 | [strategy-type-layer.md](./04-strategy-type-layer.md) | Two strategy types (Trend Following / Mean Reversion), label semantics, indicator role guidance |
| 05 | [signal-construction-layer.md](./05-signal-construction-layer.md) | Per-family indicator selection, continuous scoring formulas, ATR normalization, 3 construction modes |
| 06 | [entry-rules-layer.md](./06-entry-rules-layer.md) | Entry rule list, rule + sizing parameters, 5 configuration options (A–E), WFO integration |
| 07 | [exit-rules-layer.md](./07-exit-rules-layer.md) | Exit rule list, partial/full position reduction, 5 configuration options, entry-exit relationship |
| 08 | [risk-layer.md](./08-risk-layer.md) | Stop loss, take profit, cooldown, time stop, max position %, max sector % — global safety net |
| 09 | [review-and-backtest-handoff.md](./09-review-and-backtest-handoff.md) | Per-stock review, WFO parameter count, DF constraint warnings, readiness checklist, handoff |
| 10 | [api-data-flow-and-frontend-contracts.md](./10-api-data-flow-and-frontend-contracts.md) | Strategy definition schema, per-stock config, WFO flags, API endpoints, frontend state |
| 11 | [implementation-roadmap.md](./11-implementation-roadmap.md) | Phase 1 dependency, Phase 2 implementation order, success criteria, verification |
| 12 | [methodology-and-sources.md](./12-methodology-and-sources.md) | Academic justification for every design choice, full bibliography |

---

## The Strategy Construction Flow

The strategy page processes each stock through six sequential configuration sections:

```
Section 1  STRATEGY TYPE              Trend Following or Mean Reversion (label + role guidance)
  ↓
Section 2  SIGNAL CONSTRUCTION        Choose indicator types, set parameters or mark for WFO
  ↓
Section 3  ENTRY RULES                Define entry conditions + sizing per entry level
  ↓
Section 4  EXIT RULES                 Define exit conditions + exposure reduction per exit level
  ↓
Section 5  RISK                       Stop loss, take profit, cooldown, time stop, position limits
  ↓
Section 6  REVIEW                     Summary, WFO parameter count, readiness gate
```

Above all per-stock sections sits the **portfolio level**: Universe + Capital + Allocation — which defines the basket and stays constant across stocks.

**Each section has a clear responsibility:**

| Section | What it decides | What it does NOT decide |
|---------|----------------|------------------------|
| Strategy Type | Organizational label for the strategy approach | Indicator parameters, entry/exit thresholds |
| Signal Construction | Which indicators, which parameters (or WFO scan ranges) | When to enter or exit |
| Entry Rules | Conditions to open positions + exposure per entry | When to close positions |
| Exit Rules | Conditions to reduce/close positions + reduction per exit | Initial entry logic |
| Risk | Global safety parameters (stops, cooldown, limits) | Signal construction, entry/exit logic |
| Review | Readiness assessment, WFO parameter count | Actual backtesting or optimization |

---

## What This Station Does NOT Do

- **Backtest execution** — running walk-forward optimization, computing equity curves, evaluating performance metrics. That belongs to the backtest layer.
- **WFO optimization** — the strategy layer *flags* parameters for WFO and *defines scan ranges*, but the actual optimization is performed by the backtest engine.
- **Signal research** — discovering which indicators have predictive power. The signal layer already did that. Strategy consumes the findings.
- **Order routing or execution** — market microstructure, slippage modeling, fill simulation. That is backtest infrastructure.

A strategy is a **structured configuration** — a complete specification of what to trade, when, and how much. WFO then evaluates and optimizes that specification. This station produces specifications.

---

## Key Design Principles

1. **Per-stock configuration** — Each stock in the basket gets its own strategy tab with its own indicator choices, entry/exit rules, and risk parameters. Markets are heterogeneous; a single configuration cannot serve all stocks equally.

2. **5 configuration options (A–E)** — From fully manual to fully WFO-optimized. The user controls how much freedom they delegate to the optimizer. This is not a binary choice between "manual" and "automatic."

3. **Continuous scoring, not binary signals** — Indicators produce continuous scores (normalized by ATR where appropriate), not just buy/sell signals. This enables graduated entry and exit at multiple conviction levels.

4. **WFO-aware from the start** — Every parameter that can be optimized carries an explicit WFO flag. The strategy definition is designed to be a WFO input, not retrofitted for it.

5. **Same indicators, different strategies** — The same four indicator families serve both trend following and mean reversion strategies. The difference is not which indicators are used, but how their scores map to entry and exit conditions.

6. **Transparency** — The review section shows every parameter choice, flags which ones are marked for WFO, counts total optimization parameters, and warns when the parameter count risks overfitting given available data.

---

## The 4 Indicator Families

| Family | Category (FR) | Indicator (v1) | Scoring Formula | Future Additions |
|--------|---------------|----------------|-----------------|------------------|
| **Tendance** | Tendance | SMA | (Price - SMA) / ATR | EMA, DEMA |
| **Momentum** | Momentum | MACD | MACD_histogram / ATR | Stochastic, CCI |
| **Oscillation** | Oscillation | RSI | RSI value (0–100) | Williams %R |
| **Volume** | Volume | OBV | (OBV - OBV_EMA) / OBV_EMA | VWAP, MFI |

Each family captures a dimension the others cannot (Elder 1993). ATR normalization enables cross-stock and cross-volatility comparability (Wilder 1978).

---

## Key References

- Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies*. Wiley.
- Elder, A. (1993). *Trading for a Living*. Wiley.
- Wilder, J.W. (1978). *New Concepts in Technical Trading Systems*. Trend Research.
- Appel, G. (2005). *Technical Analysis: Power Tools for Active Investors*. FT Press.
- Murphy, J.J. (1999). *Technical Analysis of the Financial Markets*. NYIF.
- Granville, J. (1963). *Granville's New Key to Stock Market Profits*. Prentice-Hall.
- Kelly, J.L. (1956). "A New Interpretation of Information Rate." *Bell System Technical Journal*.
- Thorp, E.O. (2006). "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market."
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
- Chan, E. (2008). *Quantitative Trading*. Wiley.
