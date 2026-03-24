# 01 — Philosophy & Research Principles

---

## 1. Signals Are Not Strategies

This distinction is not semantic — it is the architectural foundation of the entire signal engine.

| | Signal | Strategy |
|---|--------|----------|
| **What it is** | A measured relationship between an indicator and future returns | A complete system that acts on signals |
| **Output** | Directional intent: +1 (buy), -1 (sell), 0 (hold) | Trade orders with sizing, timing, risk limits |
| **Scope** | One indicator, one parameter set, one time horizon | Multiple signals, portfolio construction, execution |
| **Evaluation** | OOS Sharpe, stability, drawdown, per-window | P&L, risk-adjusted returns, operational metrics |
| **Analogy** | A thermometer reading | A decision to turn on the heating |

> *"The first step in the investment process is to transform raw data into informative features... This is the most important step, because all subsequent ML algorithms will work with these features."* — López de Prado (2018), Chapter 2

The signal engine produces `VariantCurrentSignal` objects — evaluated, cost-adjusted, robustness-filtered signals. It does **not** produce trade orders, position sizes, or portfolio weights. Those are downstream responsibilities.

---

## 2. The Multiple Testing Problem

### The Core Issue

If you test 100 random indicator configurations on the same historical data, roughly 5 will appear statistically significant at the 5% level — **by pure chance**. This is the multiple testing problem (Harvey et al. 2016, Bailey et al. 2014).

In our context: we test 30 variants per family across multiple OOS windows. Without correction, the "best" variant is likely a lucky outlier, not a genuinely predictive signal.

### How This Engine Addresses It

The defense is not a single technique — it is the entire pipeline architecture:

| Layer | Defense | Mechanism |
|-------|---------|-----------|
| A (Candidates) | **Structured search** | 30 candidates per family, economically motivated parameter grid — not random search. Each parameter point has a practitioner rationale. |
| B (OOS Eval) | **Out-of-sample evaluation** | Walk-forward windows ensure the model never trains on test data. In-sample performance is never reported. |
| C (Robustness) | **Multi-metric scoring** | 4-component reliability score prevents gaming a single metric. A variant must be good on Sharpe AND stability AND consistency AND drawdown. |
| D (Survivors) | **Viability gate** | ≥40% of windows must have positive Sharpe AND ≥3 valid windows. Random noise rarely passes both. |
| E (Redundancy) | **Correlation filter** | Correlated variants (|r| > 0.85) are collapsed. This prevents the same signal counting multiple times. |
| G (Ensemble) | **Averaging** | Combining survivors via weighted average reduces variance — a noisy single signal gets diluted. |

### What This Engine Does NOT Yet Do

- **Deflated Sharpe Ratio** (Bailey & López de Prado 2012) — adjusts Sharpe for number of trials. Planned.
- **Combinatorially Purged Cross-Validation (CPCV)** (López de Prado 2018, Ch. 12) — leakage-free CV. Planned.
- **Feature importance ranking** (López de Prado 2020, Ch. 6) — identifies which indicators genuinely contribute. Planned.

We are honest about these limitations. The current pipeline reduces multiple testing bias substantially but does not eliminate it.

---

## 3. Information-Theoretic Foundation

### When Does a Signal Have Power?

A signal `s(t)` has predictive power for future returns `y(t+h)` if and only if:

```
I(s(t); y(t+h)) > 0
```

where `I` is mutual information. In plain English: knowing the signal tells you something about future returns that you didn't already know.

### Practical Proxies

We cannot compute mutual information directly (it requires density estimation in high dimensions). Instead, we use practical proxies:

| Metric | What It Measures | How We Use It |
|--------|-----------------|---------------|
| **OOS Sharpe** | Risk-adjusted return predictability | Core of the reliability score (35% weight) |
| **Fraction positive windows** | Consistency across time regimes | Stability score (30% weight) |
| **Sharpe std dev** | Stability of the Sharpe estimate | Consistency score (20% weight) |
| **Max drawdown** | Tail risk of acting on the signal | Drawdown score (15% weight) |

### The Cost Hurdle

A signal with genuine information content may still be **unprofitable** after transaction costs. The minimum edge required is approximately:

```
edge_min ≈ round_trip_cost / win_probability
```

For our default of 10 bps per leg (20 bps round trip) and 50% win rate, `edge_min ≈ 0.004` — the signal must predict at least 0.4% per trade to break even. This is why transaction costs are deducted at every position change in Layer B.

> *"Transaction costs are the silent killer of trading strategies."* — Chan (2008), Chapter 2

---

## 4. Design Principles

### Principle 1: Economic Motivation First

Every indicator family in the engine has a decades-old economic rationale:

| Family | Economic Rationale | Reference |
|--------|-------------------|-----------|
| SMA | Trend-following: prices exhibit momentum due to behavioral biases (anchoring, herding) and institutional flows | Murphy (1999), Jegadeesh & Titman (1993) |
| RSI | Mean-reversion: extreme relative strength tends to revert due to liquidity provision and overreaction correction | Wilder (1978), Poterba & Summers (1988) |
| MACD | Momentum: convergence/divergence of short vs long EMA captures acceleration in trend | Appel (2005) |
| OBV | Volume confirmation: price moves on high volume are more likely to persist | Granville (1963), Blume et al. (1994) |

We do not include indicators without clear economic justification (no "indicator of the week" from data-mining).

### Principle 2: Out-of-Sample or It Didn't Happen

No in-sample metric is shown to the user or used in any filtering step. Every number comes from test windows the model never trained on.

> *"An investment strategy that has not been validated out-of-sample is like a pharmaceutical drug that has not been through clinical trials."* — Pardo (2008), Chapter 1

### Principle 3: Parsimony Over Complexity

- 4 families, not 40
- 1 archetype per family, not 5
- 30 parameter points, not 300
- Linear indicators, not neural networks

Each additional degree of freedom increases the risk of overfitting. We add complexity only when there is clear economic justification.

### Principle 4: Signals Degrade

No signal works forever. Markets adapt, regimes change, and alpha decays.

> *"All alphas have a half-life."* — López de Prado (2018), Chapter 1

This is why:
- We evaluate across **multiple** OOS windows (not just one)
- We measure **stability** (fraction of positive windows) — a signal that works in 2 of 10 windows is likely decaying
- We cap history via `max_years` — ancient data may be misleading

### Principle 5: Ensemble Over Selection

Rather than picking "the best" variant — which is a form of overfitting to the evaluation metric — we combine all surviving representatives via reliability-weighted averaging.

> *"Ensemble methods can reduce the variance of an estimator without increasing bias."* — Breiman (1996)

The ensemble score represents the consensus view of all non-redundant, viable, OOS-validated variants. This is more robust than any single variant.

---

## 5. What "Robust" Means in This Context

A signal is robust if it:

1. **Generalizes** — works on data it has never seen (OOS evaluation)
2. **Persists** — works across multiple time windows (stability score)
3. **Is consistent** — Sharpe doesn't swing wildly between windows (consistency score)
4. **Is safe** — doesn't produce catastrophic drawdowns (drawdown score)
5. **Is distinct** — isn't just a copy of another signal (redundancy filter)
6. **Is economically viable** — survives after transaction costs (cost-adjusted returns)

A signal that fails any of these is either noise, a duplicate, or too risky to act on. The pipeline removes them systematically.
