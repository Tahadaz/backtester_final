# Backtest Layer — Architecture Documentation

> **Station mandate:** Evaluate fully defined trading strategies through Walk-Forward Analysis (WFA), producing statistically validated parameter sets and OOS-derived sizing — the final gate before any strategy is considered viable. This station implements pure Pardo methodology: rolling in-sample optimization with out-of-sample validation, PROM as objective function, neighbor-averaging for robustness, and Walk-Forward Efficiency as the acceptance criterion.

*The fundamental insight driving this architecture: a strategy that "works" in-sample has not been tested — it has been fitted. Only a strategy whose optimized parameters consistently transfer to unseen data carries genuine predictive value. Walk-Forward Analysis is not one of several options for establishing this — it is the standard methodology (Pardo 2008).*

---

## Documents

| # | File | Scope |
|---|------|-------|
| 01 | [overview-and-design-philosophy.md](./01-overview-and-design-philosophy.md) | Backtest page as evaluation station, WFO mode detection, non-WFO mode, current state |
| 02 | [wfo-methodology.md](./02-wfo-methodology.md) | Core WFA pipeline: variant generation, feasible configurations, rolling optimization, WFE selection |
| 03 | [prom-and-objective-function.md](./03-prom-and-objective-function.md) | PROM formula, natural small-sample penalty, cost adjustment, why PROM over alternatives |
| 04 | [neighbor-averaging-and-optimization-profile.md](./04-neighbor-averaging-and-optimization-profile.md) | Parameter smoothing, plateau detection, optimization profile checks, IS window rejection |
| 05 | [walk-forward-efficiency.md](./05-walk-forward-efficiency.md) | WFE computation, 50% threshold, robustness checks, configuration selection, Full-WFO mode |
| 06 | [option-e-auto-discovery.md](./06-option-e-auto-discovery.md) | Option E for entries/exits, level count optimization, PROM penalty, parameter count limits |
| 07 | [sizing-from-oos.md](./07-sizing-from-oos.md) | Kelly criterion from concatenated OOS trades, win rate and W/L ratio derivation |
| 08 | [statistical-validation.md](./08-statistical-validation.md) | Monte Carlo permutation test (p-value + equity curve fan chart) and Deflated Sharpe Ratio (multiple testing correction) |
| 09 | [test-period-validation.md](./09-test-period-validation.md) | Pure out-of-sample test on held-out data, equity curve, strongest validation available |
| 10 | [api-data-flow-and-frontend-contracts.md](./10-api-data-flow-and-frontend-contracts.md) | Request/response schemas, per-window endpoints, caching, progress reporting |
| 11 | [implementation-roadmap.md](./11-implementation-roadmap.md) | Dependencies, implementation order, success criteria, verification steps |
| 12 | [methodology-and-sources.md](./12-methodology-and-sources.md) | Pardo citations, Bailey & López de Prado (DSR, PBO), Kelly/Thorp references, honest limitations |
| 13 | [strict-pardo-window-policy-adr.md](./13-strict-pardo-window-policy-adr.md) | ADR: strict fold-driven window sizing, DF constraints, fallback policy |
| 14 | [wfo-signal-layer.md](./14-wfo-signal-layer.md) | WFO-optimized signals for the signal page: per-family ensemble optimization, global consensus, S/R modulation |

---

## The WFO Pipeline

The backtest layer processes each (stock, family, horizon) tuple through a Walk-Forward Analysis pipeline:

```
STEP 1   VARIANT GENERATION        All parameter combinations within horizon ranges
  |
STEP 2   CONFIGURATION SEARCH      Feasible (IS, OOS) window sizes given data length
  |
STEP 3   ROLLING WALK-FORWARD      Per configuration: roll IS+OOS through data
  |        |
  |        +-- IS WINDOW            Run all combos -> PROM -> neighbor-average -> profile check -> winner
  |        |
  |        +-- OOS WINDOW           Test IS winner on unseen data
  |
STEP 4   WFE SELECTION             Best configuration with WFE >= 50%
  |
STEP 5   ROBUSTNESS CHECK          Majority of OOS windows must be profitable
  |
STEP 6   PARAMETER EXTRACTION      Winner = last IS window's best parameter set
  |
STEP 7   SIZING FROM OOS           Kelly fraction from concatenated OOS trades
  |
STEP 8   STATISTICAL VALIDATION    Monte Carlo permutation test + Deflated Sharpe Ratio
  |
STEP 9   TEST PERIOD               Remaining data = pure out-of-sample validation
```

**Each step has a clear methodological justification:**

| Step | Problem it solves | Reference |
|------|-------------------|-----------|
| 1 | Structured search prevents data-mining | Pardo (2008) Ch.10 p.252 |
| 2 | IS >= 10 x max_lookback ensures statistical validity (DF > 90%) | Pardo (2008) Ch.6 p.163 |
| 3 | Rolling windows detect regime changes and parameter instability | Pardo (2008) Ch.11 |
| 4 | WFE measures optimization transfer quality | Pardo (2008) Ch.11 |
| 5 | Majority profitable prevents single-window luck | Pardo (2008) Ch.11 p.289 |
| 6 | Most recent IS window reflects current market regime | Pardo (2008) Ch.11 |
| 7 | OOS-derived sizing eliminates manual guessing | Kelly (1956), Thorp (2006) |
| 8 | Monte Carlo tests statistical significance; DSR corrects for multiple testing | Bailey & López de Prado (2014) |
| 9 | Held-out test period is the strongest validation available | Pardo (2008) Ch.11 |

---

## What This Station Does NOT Do

- **Strategy definition** — entry/exit rules, indicator selection, risk parameters are defined on the strategy page (Phase 2). The backtest layer evaluates strategies; it does not create them.
- **Signal research** — indicator exploration, candidate generation, OOS signal evaluation belong to the signal-generation layer. The backtest layer uses indicators as components of a full strategy, not as standalone signals.
- **Portfolio construction** — capital allocation across stocks is configured on the strategy page. The backtest layer evaluates one SavedStrategy at a time. When `allocation_method = WFO-optimized`, the portfolio weights become part of the WFO parameter set and are optimized alongside per-stock parameters — this is not separate portfolio construction but part of the strategy's own optimization surface.
- **Real-time execution** — order routing, market microstructure, live position management are outside scope.

The backtest layer is an **evaluation station**: it takes a fully defined strategy, subjects it to rigorous Walk-Forward Analysis, and produces a verdict — viable or not viable — backed by statistical evidence.

---

## Key Design Principles

1. **Pure Pardo methodology, no shortcuts** — Every component of the WFA pipeline follows Pardo (2008) with specific chapter and page citations. Where we extend beyond Pardo (Kelly sizing from OOS), the extension is clearly identified and justified.

2. **Trust the process, not a single result** — A strategy is not validated by one good backtest. It is validated by demonstrating that optimization consistently transfers from in-sample to out-of-sample across multiple rolling windows.

3. **PROM over Sharpe** — The objective function is Pessimistic Return on Margin, which naturally penalizes small trade samples via its square-root adjustment. Sharpe ratio, profit factor, and raw P&L are all susceptible to small-sample distortions that PROM handles by construction.

4. **Neighbor-averaging over raw optimization** — Selecting the parameter with the highest raw PROM risks picking an isolated spike. Neighbor-averaging selects plateau centers — parameters whose neighbors also perform well — which are far more likely to be robust.

5. **WFE >= 50% as the acceptance gate** — If the annualized OOS return is less than half the annualized IS return, the optimization process is not transferring. The strategy is flagged as not viable with diagnostic data, not quietly passed through.

6. **Sizing from data, not from hope** — Win rate and win/loss ratio are outputs of the WFO process (computed from concatenated OOS trades), not manually-guessed inputs. Kelly fraction computed from these values produces position sizing grounded in observed out-of-sample performance.

---

## Key References

- Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies*. 2nd Edition. Wiley.
  - Ch.6: Degrees of freedom, IS window sizing (p.163)
  - Ch.9: PROM formula (p.239)
  - Ch.10: Neighbor-averaging (p.235), optimization profile (p.260-268), step sizing (p.252), parameter count (p.249)
  - Ch.11: Walk-Forward Analysis, WFE, OOS/IS ratio (p.282), robustness (p.289)
- Kelly, J.L. (1956). "A New Interpretation of Information Rate." *Bell System Technical Journal*.
- Thorp, E.O. (2006). "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market." In *Handbook of Asset and Liability Management*.
- Bailey, D.H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio." *Journal of Portfolio Management*, 40(5).
  - Monte Carlo permutation test for statistical significance
  - DSR formula correcting for multiple testing and non-normality
- Chan, E. (2008). *Quantitative Trading*. Wiley.
