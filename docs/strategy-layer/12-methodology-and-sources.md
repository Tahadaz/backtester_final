# Strategy Layer — Methodology and Sources

## Purpose

This document centralizes the academic and practitioner sources that support the design choices of the Strategy layer. Every significant design decision has an identifiable logical or empirical basis. The references support the chosen direction; they do not remove the need for out-of-sample validation in our own market universe.

---

## 1. Walk-Forward Optimization as the Evaluation Framework

**Design choice**: The strategy layer is designed as input to a WFO engine. Parameters marked for optimization are optimized via walk-forward analysis, not via a single in-sample fit.

**Why WFO, not simple optimization?**

A single in-sample optimization finds the best parameters for historical data — but those parameters may not work going forward. Walk-forward analysis addresses this by:

1. Optimizing on an in-sample (IS) window
2. Testing on an immediately following out-of-sample (OOS) window
3. Rolling forward and repeating
4. Aggregating OOS performance across all windows

This produces performance metrics that reflect genuine forward-looking skill, not curve-fitting.

**Primary reference**: Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies*. Wiley. — Chapter 7: "Walk-Forward Analysis." Pardo's methodology provides the theoretical foundation for:

- IS/OOS window sizing (IS should be 2–4x the OOS window)
- The degrees-of-freedom constraint (IS >= 10 x max_lookback)
- PROM (Pessimistic Return on Margin) as the optimization objective
- The principle that OOS performance is the only valid measure of strategy quality

**The DF constraint in practice**: With Moroccan stocks having 10–15 years of daily data (~2,500–3,750 bars), the practical limit is approximately 15 WFO parameters for long-horizon strategies. Exceeding this limit increases the risk that the optimizer finds IS patterns that do not generalize.

---

## 2. Indicator Family Classification

**Design choice**: Organize indicators into four families — Tendance, Momentum, Oscillation, Volume — following Elder's category-based approach.

**Primary reference**: Elder, A. (1993). *Trading for a Living*. Wiley. — Chapter 4: "Computerized Technical Analysis."

> *"The first rule of using indicators is that you should never use two indicators from the same group. Combining two trend-following indicators... or two oscillators is redundant — they just confirm each other's blind spots."* — Elder (1993)

This principle directly informs the four-family architecture:

| Family | Elder Category | Rationale |
|--------|---------------|-----------|
| Tendance (SMA) | Trend-following | Detects direction |
| Momentum (MACD) | Trend-following (acceleration) | Detects momentum strength |
| Oscillation (RSI) | Oscillator | Detects overextension / mean-reversion potential |
| Volume (OBV) | Volume | Provides non-price confirmation |

**Why SMA, MACD, RSI, and OBV specifically?** Each has decades of practitioner literature and a clear economic interpretation. They are not proprietary or exotic — any quant can reproduce them. Adding more families later (Stochastic, CCI, Williams %R, VWAP, MFI) follows the same principle: each new family must capture a dimension the existing ones cannot.

---

## 3. ATR Normalization

**Design choice**: Three of the four scoring formulas use ATR(14) as a normalizer to enable cross-stock and cross-volatility comparability.

**Primary reference**: Wilder, J.W. (1978). *New Concepts in Technical Trading Systems*. Trend Research. — Chapter: "Average True Range."

Wilder introduced ATR as a measure of "true" price volatility that accounts for gaps. Using ATR as a normalizer:

- Expresses indicator deviations in volatility units, not price units
- Makes a threshold like `trend_score > 2.0` mean "price is 2 ATR above the SMA" regardless of whether the stock trades at 50 MAD or 500 MAD
- Ensures entry/exit rule thresholds transfer meaningfully across stocks in the basket

RSI does not require ATR normalization because it is already a self-normalizing oscillator bounded between 0 and 100 (Wilder 1978, Ch. "Relative Strength Index").

---

## 4. Continuous Scoring vs Binary Signals

**Design choice**: Indicators produce continuous scores, not binary buy/sell signals. This enables graduated entry and exit at multiple conviction levels.

**Why continuous?**

Binary signals force a single threshold: above = buy, below = sell. This creates problems:

- No concept of "strong buy" vs "weak buy"
- No ability to scale into positions gradually
- Entry and exit become all-or-nothing decisions

Continuous scoring allows:

- Multiple entry levels at different conviction thresholds
- Partial exits as conviction weakens
- Score-based sizing (stronger signal = larger position)

This aligns with practitioner wisdom: "the best trades are entered gradually and exited gradually" — a principle reflected in the multi-level entry/exit architecture.

**Supporting reference**: Murphy, J.J. (1999). *Technical Analysis of the Financial Markets*. NYIF. — Murphy's treatment of moving averages, MACD, and RSI all describe these indicators as producing ranges of signal strength, not just binary crossovers.

---

## 5. Moving Averages (SMA, EMA, DEMA)

**Design choice**: SMA as the v1 trend indicator, with EMA and DEMA as planned additions.

**Primary reference**: Murphy, J.J. (1999). *Technical Analysis of the Financial Markets*. NYIF. — Chapters 9–10: "Moving Averages."

Murphy documents the price-vs-moving-average crossover as the most widely used trend identification technique. SMA is chosen as the v1 indicator because:

- It is the simplest and most robust moving average
- It has no exotic parameters beyond the lookback period
- It is universally understood by practitioners

**Scoring formula**: `trend_score = (Price - SMA(period)) / ATR(14)` — a normalized distance from the moving average. Positive when price is above (bullish trend), negative when below (bearish trend), magnitude in ATR units.

---

## 6. MACD

**Design choice**: MACD histogram as the v1 momentum indicator.

**Primary reference**: Appel, G. (2005). *Technical Analysis: Power Tools for Active Investors*. FT Press. — Chapter: "MACD."

Appel designed MACD to capture momentum as the convergence/divergence of two exponential moving averages. The histogram (MACD line minus signal line) provides a continuous measure of momentum strength.

**Scoring formula**: `momentum_score = MACD_histogram(fast, slow, signal) / ATR(14)` — ATR-normalized for cross-stock comparability. Standard defaults: fast=12, slow=26, signal=9.

---

## 7. RSI

**Design choice**: RSI as the v1 oscillation indicator, bounded [0, 100].

**Primary reference**: Wilder, J.W. (1978). *New Concepts in Technical Trading Systems*. Trend Research. — Chapter: "Relative Strength Index."

RSI measures the ratio of average gains to average losses over a lookback period. It naturally identifies overextension:

- RSI < 30: oversold — potential mean-reversion buy
- RSI > 70: overbought — potential mean-reversion sell or trend filter

**Scoring formula**: `oscillation_score = RSI(period)` — used directly as the score (already bounded and self-normalizing). Standard default: period=14.

---

## 8. OBV

**Design choice**: OBV as the v1 volume indicator, providing non-price confirmation.

**Primary reference**: Granville, J. (1963). *Granville's New Key to Stock Market Profits*. Prentice-Hall.

Granville's On-Balance Volume accumulates volume directionally: volume on up-days is added, volume on down-days is subtracted. The resulting cumulative line provides insight into whether volume "supports" price movement.

**Scoring formula**: `volume_score = (OBV - OBV_EMA(period)) / OBV_EMA(period)` — a percentage deviation of OBV from its own exponential moving average. Positive when volume flow is accumulating faster than average.

**Supporting reference**: Blume, L., Easley, D., O'Hara, M. (1994). "Market Statistics and Technical Analysis: The Role of Volume." *Journal of Finance*. — Provides theoretical support for volume as an information signal.

---

## 9. Kelly Criterion for Position Sizing

**Design choice**: Kelly criterion as the basis for WFO-derived position sizing (Options B and D).

**Primary reference**: Kelly, J.L. (1956). "A New Interpretation of Information Rate." *Bell System Technical Journal*.

**Applied reference**: Thorp, E.O. (2006). "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market."

Kelly provides a principled answer to: "If I have a measurable edge and measurable unit risk, what fraction of capital is rational?" The formula:

```
f* = (win_rate * avg_win_loss_ratio - (1 - win_rate)) / avg_win_loss_ratio
```

Full Kelly is too aggressive for most real usage because:

- Parameter estimates (win_rate, avg_win_loss_ratio) are uncertain
- Kelly assumes infinite time horizon and no drawdown constraints
- Real traders have finite capital and finite patience

Using fractional Kelly (Half Kelly = 0.5x, Quarter Kelly = 0.25x) addresses these practical limitations while preserving the mathematical structure.

In the strategy layer, Kelly sizing is computed from WFO out-of-sample metrics — ensuring the inputs are not contaminated by in-sample overfitting.

---

## 10. Why 5 Configuration Options

**Design choice**: Offer a spectrum from fully manual (Option A) to fully WFO-optimized (Option E).

**Rationale**: There is no consensus on how much discretion vs optimization is ideal. Different traders operate at different points on this spectrum:

- A portfolio manager with 20 years of Casablanca experience may want full manual control (Option A)
- A quantitative analyst may want full optimization (Option E)
- Most users fall somewhere in between (Options B, C, D)

Forcing a single approach would alienate part of the user base. The 5-option architecture respects this diversity while ensuring that every choice results in a well-defined WFO parameter set.

**Supporting reference**: Pardo (2008), Ch. 3: "Optimization of Trading Strategies" — discusses the tension between parameter freedom and overfitting, arguing for controlled optimization with explicit degrees of freedom.

---

## 11. Why Per-Stock Configuration

**Design choice**: Each stock in the basket gets its own strategy configuration (type, indicators, rules, risk).

**Rationale**: Financial markets are heterogeneous. A bank stock and a mining stock may have fundamentally different:

- Volatility profiles
- Mean-reversion tendencies
- Trend persistence
- Liquidity characteristics

Forcing them into the same parameter set introduces unnecessary constraint. Per-stock configuration allows the strategy to adapt to each instrument's characteristics.

**On the Casablanca Stock Exchange specifically**: The MASI index contains stocks with vastly different trading volumes, volatility regimes, and sector dynamics. A single-configuration approach would be dominated by the most liquid names, poorly serving the rest.

**Supporting references**:
- Hung, C., & Lai, H. (2022). "Information Asymmetry and the Profitability of Technical Analysis." *Journal of Banking & Finance*. — Supports the idea that strategy parameters should vary with market microstructure characteristics.
- Han, Y., Yang, K., & Zhou, G. (2013). "A New Anomaly: The Cross-Sectional Profitability of Technical Analysis." *Journal of Financial and Quantitative Analysis*. — Shows that technical analysis profitability varies across the cross section, supporting per-stock parameter tuning.

---

## 12. PROM as the WFO Objective

**Design choice**: Use PROM (Pessimistic Return on Margin) as the primary WFO optimization objective.

**Primary reference**: Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies*. Wiley. — Chapter 9: "PROM."

PROM adjusts the return on margin by using the lower bound of the confidence interval for profits and the upper bound for losses. This naturally penalizes:

- Strategies that trade too frequently (higher costs)
- Strategies with too many parameters (overfitting produces fragile profits)
- Strategies with inconsistent performance across windows

For Option E (full WFO), PROM is particularly important because it penalizes too many entry/exit levels — each additional level adds transactions, and unless those transactions add genuine value, PROM will prefer the simpler structure.

---

## 13. Two Strategy Types: Trend Following and Mean Reversion

**Design choice**: Support two fundamental strategy types using the same indicators.

**Supporting references**:

- Hong, H., & Stein, J.C. (1999). "A Unified Theory of Underreaction, Momentum Trading, and Overreaction." *Journal of Finance*. — Provides theoretical grounding for the distinction between momentum/trend behavior and overreaction/reversion behavior.

- Poterba, J., & Summers, L. (1988). "Mean Reversion in Stock Prices: Evidence and Implications." *Journal of Financial Economics*. — Provides evidence that stock prices exhibit mean-reversion at certain horizons.

- Jegadeesh, N., & Titman, S. (1993). "Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency." *Journal of Finance*. — Seminal momentum paper supporting the trend-following approach.

These references support the core architectural insight: the same indicators can serve both strategies, because the underlying market dynamics (trend persistence vs mean reversion) coexist and alternate.

---

## Bibliography

| Author(s) | Year | Title | Use in Strategy Layer |
|-----------|------|-------|----------------------|
| Appel, G. | 2005 | *Technical Analysis: Power Tools for Active Investors* | MACD scoring formula |
| Blume, L., Easley, D., O'Hara, M. | 1994 | "Market Statistics and Technical Analysis: The Role of Volume" | OBV as information signal |
| Elder, A. | 1993 | *Trading for a Living* | Indicator family classification |
| Granville, J. | 1963 | *Granville's New Key to Stock Market Profits* | OBV indicator |
| Han, Y., Yang, K., Zhou, G. | 2013 | "A New Anomaly: The Cross-Sectional Profitability of Technical Analysis" | Per-stock configuration |
| Hong, H., Stein, J.C. | 1999 | "A Unified Theory of Underreaction, Momentum Trading, and Overreaction" | Two strategy types |
| Hung, C., Lai, H. | 2022 | "Information Asymmetry and the Profitability of Technical Analysis" | Per-stock configuration, Casablanca relevance |
| Jegadeesh, N., Titman, S. | 1993 | "Returns to Buying Winners and Selling Losers" | Trend following support |
| Kaufman, P.J. | 1995 | *Trading Systems and Methods* | Deterioration-based exit |
| Kelly, J.L. | 1956 | "A New Interpretation of Information Rate" | Kelly sizing formula |
| Murphy, J.J. | 1999 | *Technical Analysis of the Financial Markets* | SMA, indicator taxonomy |
| Pardo, R. | 2008 | *The Evaluation and Optimization of Trading Strategies* | WFO methodology, PROM, DF constraint |
| Poterba, J., Summers, L. | 1988 | "Mean Reversion in Stock Prices" | Mean reversion strategy type |
| Thorp, E.O. | 2006 | "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market" | Fractional Kelly sizing |
| Wilder, J.W. | 1978 | *New Concepts in Technical Trading Systems* | ATR normalization, RSI |

---

## How These Sources Should Be Used

The sources above justify structural choices:

- organizing indicators into distinct families (Elder 1993)
- normalizing with ATR for cross-stock comparability (Wilder 1978)
- using continuous scoring for graduated entry/exit (Murphy 1999)
- sizing with Kelly criterion (Kelly 1956, Thorp 2006)
- evaluating via walk-forward optimization (Pardo 2008)
- supporting two fundamental strategy types (Hong & Stein 1999, Poterba & Summers 1988)
- configuring per-stock rather than one-size-fits-all (Han et al. 2013, Hung & Lai 2022)

They do not guarantee that any specific strategy will be profitable. That determination comes from the WFO evaluation in the backtest layer.

## Cross-Links

- WFO methodology informs the review section: [09-review-and-backtest-handoff.md](./09-review-and-backtest-handoff.md)
- ATR normalization is applied in: [05-signal-construction-layer.md](./05-signal-construction-layer.md)
- Kelly sizing is used in entry/exit rules: [06-entry-rules-layer.md](./06-entry-rules-layer.md) and [07-exit-rules-layer.md](./07-exit-rules-layer.md)
- Deterioration-based exit: [07-exit-rules-layer.md](./07-exit-rules-layer.md)
- Indicator families: [05-signal-construction-layer.md](./05-signal-construction-layer.md)
