# Signal Generation — Philosophy & Research Principles

---

## 1. Signals Are Not Strategies

A **signal** is a measurable quantity derived from market data that has some informational content about future price behavior. A **strategy** is a complete decision system that includes position sizing, risk management, execution, and capital allocation.

This distinction matters because:

- **A signal can be useful in many contexts.** The finding "price above its 50-day SMA historically precedes positive 20-day returns in this market" can be used for:
  - Trend-following entries
  - Execution timing (delay selling when trend is up)
  - Risk monitoring (reduce exposure when signal turns bearish)
  - Market regime detection (trending vs mean-reverting)
  - Ensemble voting (one input among many)

- **A strategy bakes in assumptions that signals don't.** Position sizing, transaction costs, rebalancing frequency, capital constraints — these are separate engineering decisions that shouldn't pollute signal evaluation.

- **Evaluating signals as strategies causes overfitting.** When you optimize a "strategy" (signal + sizing + timing + costs) as a monolith, the optimizer finds parameter combinations that exploit noise in the backtest rather than genuine signal content.

> *"A common error is to believe that feature analysts develop strategies. Instead, feature analysts collect and catalogue libraries of findings that can be useful to a multiplicity of stations."*
> — López de Prado, *AFML* (2018), Ch. 1

### In this codebase

The signal generation layer (this documentation) produces `SignalFrame` objects: time-indexed arrays of {+1, 0, -1} values per symbol. These are **intent signals** — they express directional conviction, not trade orders.

The portfolio layer (`portfolio.py`) separately interprets these intents under constraints (costs, volume, cooldown, position limits). The optimization layer searches for parameter combinations where signal intent translates into economic value after costs.

---

## 2. The Multiple Testing Problem

### Why it matters

If you test 100 random signal variations, roughly 5 will appear "significant" at the 5% level by pure chance. This is the **multiple comparisons problem** (Bonferroni, 1936) and it is the single largest source of false discoveries in quantitative finance.

> *"Most of the empirical research in finance is likely false."*
> — Harvey, Liu & Zhu (2016), "... and the Cross-Section of Expected Returns"

### How this codebase addresses it

1. **Structured candidate universe** — We don't randomly sample parameters. We define economically distinct archetypes (e.g., price-vs-SMA vs SMA-crossover) and disciplined parameter neighborhoods. See [08-candidate-universe.md](./08-candidate-universe.md).

2. **Chronology-respecting evaluation** — All optimization uses walk-forward validation: train on past, test on future. No look-ahead bias. See [07-walk-forward-validation.md](./07-walk-forward-validation.md).

3. **Redundancy filtering** — Near-duplicate signals (SMA-50 and SMA-51 generate nearly identical signals) are clustered and deduplicated before evaluation. This reduces the effective number of independent tests.

4. **Survival gates** — Signals must pass minimum economic viability thresholds (positive PnL, minimum trade count, Sharpe > 0) before being considered. This removes noise-driven "winners."

### What this codebase does NOT yet do (planned)

- **Deflated Sharpe Ratio** (Bailey & López de Prado, 2014) — adjusts Sharpe for the number of trials attempted
- **Combinatorial Purged Cross-Validation (CPCV)** — multiple OOS paths to estimate variance of performance
- **Feature importance via MDI/MDA** — which features actually contribute to signal quality

---

## 3. Information-Theoretic Foundations

### What makes a signal "informative"?

A signal `s(t)` has predictive power over a target variable `y(t+h)` (e.g., h-bar forward return) if and only if:

```
I(s(t); y(t+h)) > 0
```

where `I` is **mutual information** — the reduction in uncertainty about `y` given knowledge of `s`.

In practice, we approximate this through:
- **Directional accuracy**: does `sign(s(t))` predict `sign(y(t+h))`?
- **Rank correlation**: does the magnitude of `s(t)` predict the magnitude of `y(t+h)`?
- **Economic significance**: does acting on `s(t)` produce positive PnL after costs?

### Signal vs noise

A noisy signal still has value if:
1. The information ratio (signal-to-noise) is positive
2. The signal can be observed frequently enough to compound
3. Transaction costs don't exceed the per-observation alpha

In our context (daily Moroccan equities):
- **Observation frequency:** ~250 bars/year
- **Transaction costs:** ~40-80 bps round-trip (Casablanca commission + slippage)
- **Required edge per trade:** at least > round-trip costs / win probability

This means weak signals can be profitable if they generate enough trades with even a slight edge.

---

## 4. The Indicator → Signal → Intent Pipeline

```
Raw OHLCV bars
    │
    │ Indicator computation (pure math, no decisions)
    ▼
Feature values  (SMA=105.2, RSI=42.1, MACD=+0.3)
    │
    │ Decision rules (strategy adapter logic)
    ▼
Signal intent  (+1 = bullish, 0 = neutral, -1 = bearish)
    │
    │ Portfolio interpretation (costs, constraints, sizing)
    ▼
Trade orders  (buy 100 shares ATW at market open tomorrow)
    │
    │ Execution (fills, slippage, settlement)
    ▼
Position changes → PnL → Performance metrics
```

Each layer is **independent and substitutable**:
- Change the indicator computation → same decision rules produce different signals
- Change the decision rule → same indicators produce different signals
- Change the portfolio interpretation → same signals produce different trades
- Change the execution model → same trades produce different PnL

This separation is essential for:
- **Attribution**: which layer contributed to performance?
- **Debugging**: where did the backtest go wrong?
- **Research**: test a new indicator without changing everything else

---

## 5. Design Principles for Signal Research

### Principle 1: Economic motivation first

Every signal must have an economic rationale — a story for *why* it should predict future returns. Pure data-mining (finding patterns without theory) produces spurious results.

Examples of valid economic rationales:
- **Trend-following (SMA crossover):** Behavioral finance literature (Barberis, Shleifer & Vishny 1998) shows underreaction to news causes momentum. SMA detects persistent drift.
- **Mean reversion (RSI extremes):** Overreaction literature (De Bondt & Thaler 1985) shows extreme moves partially reverse. RSI identifies extremes.
- **Volume confirmation (OBV):** Volume-price divergence signals informed trading (Llorente et al. 2002). OBV detects accumulation/distribution.

### Principle 2: Out-of-sample or it didn't happen

In-sample performance is not evidence. The only valid measure of signal quality is **chronological out-of-sample performance** — train on the past, test on a future period that was never seen during training.

### Principle 3: Parsimony over complexity

Simpler signals with fewer parameters are more likely to generalize. Each additional parameter is an additional degree of freedom for overfitting.

| Signal | Parameters | Overfitting risk |
|--------|-----------|-----------------|
| Close > SMA(50) | 1 | Low |
| SMA(fast) > SMA(slow) | 2 | Low-Medium |
| RSI(period) < threshold | 2 | Low-Medium |
| Stochastic + VWAP + multiple thresholds | 6+ | High |
| Ichimoku cloud (tenkan, kijun, senkou_b, shift) | 4 | Medium-High |

### Principle 4: Signals degrade

All signals have a **half-life** — as more participants discover and trade on a pattern, the edge diminishes. This is the **adaptive markets hypothesis** (Lo, 2004).

Implications:
- Regularly re-evaluate signal performance on recent data
- Don't assume historical performance persists indefinitely
- Prefer robust signals (work across regimes) over fragile ones (work only in specific conditions)

### Principle 5: Ensemble over selection

Instead of picking the "best" signal, combine multiple uncorrelated signals into an ensemble. This:
- Reduces variance of the combined signal
- Is more robust to regime changes
- Exploits the wisdom-of-crowds effect

The signal generation plan (see [08-candidate-universe.md](./08-candidate-universe.md)) is designed to produce a diverse set of representative variants that can be ensembled.

---

## References

1. López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
2. López de Prado, M. (2020). *Machine Learning for Asset Managers*. Cambridge University Press.
3. Harvey, C.R., Liu, Y., Zhu, H. (2016). "... and the Cross-Section of Expected Returns." *Review of Financial Studies*, 29(1), 5–68.
4. Bailey, D.H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio." *Journal of Portfolio Management*, 40(5), 94–107.
5. White, H. (2000). "A Reality Check for Data Snooping." *Econometrica*, 68(5), 1097–1126.
6. Barberis, N., Shleifer, A., Vishny, R. (1998). "A Model of Investor Sentiment." *Journal of Financial Economics*, 49(3), 307–343.
7. De Bondt, W.F.M. & Thaler, R.H. (1985). "Does the Stock Market Overreact?" *Journal of Finance*, 40(3), 793–805.
8. Lo, A.W. (2004). "The Adaptive Markets Hypothesis." *Journal of Portfolio Management*, 30(5), 15–29.
9. Llorente, G., Michaely, R., Saar, G., Wang, J. (2002). "Dynamic Volume-Return Relation of Individual Stocks." *Review of Financial Studies*, 15(4), 1005–1047.
