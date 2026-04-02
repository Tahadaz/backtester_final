# 11 — Methodology and Sources

---

## Purpose

This document provides the academic and practitioner justification for every design choice in the backtest layer. Each decision is traced to a specific reference with chapter and page number where applicable. Where we extend beyond the cited literature, the extension is clearly identified and justified.

---

## Primary Source: Pardo (2008)

Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies*. 2nd Edition. Wiley.

This is the foundational reference for the entire WFO implementation. Every major design decision traces to a specific chapter and page.

### Walk-Forward Analysis (Ch.11)

**Design choice:** Use rolling IS optimization + OOS validation as the primary evaluation methodology.

**Justification:** Pardo Ch.11 describes Walk-Forward Analysis as the gold standard for strategy evaluation. The procedure rolls an IS optimization window forward through time, testing each window's optimal parameters on the subsequent OOS window. This detects whether the optimization process itself is robust — not just whether one parameter set works.

**Specific citations:**
- WFA procedure definition: Ch.11, full chapter
- OOS/IS ratio of 25-35%: Ch.11 p.282
- Step = OOS window: Ch.11, RSI CT example
- Majority of walk-forwards profitable: Ch.11 p.289 (RSI CT had 19/30 = 63%)

### Degrees of Freedom Constraint (Ch.6 p.163)

**Design choice:** IS window must contain at least 10x the maximum lookback period (DF > 90%).

**Justification:** Pardo Ch.6 p.163 establishes the Degrees of Freedom constraint. With too few data points relative to parameters, the optimization has insufficient statistical power to distinguish genuine patterns from noise. The 10x multiplier ensures DF > 90%, meaning fewer than 10% of the data's information is consumed by parameter estimation.

**Formula:**
```
DF = 1 - (n_parameters / n_data_points)
IS >= 10 x max_lookback  =>  DF >= 1 - 1/10 = 90%
```

### PROM as Objective Function (Ch.9 p.239)

**Design choice:** Use Pessimistic Return on Margin rather than Sharpe ratio, profit factor, or raw P&L.

**Justification:** Pardo Ch.9 p.239 introduces PROM as the objective function specifically designed for trading strategy optimization. Its square-root adjustment penalizes small trade samples by construction — a property that Sharpe ratio, profit factor, and raw P&L lack.

**Why not Sharpe?** Sharpe ratio = mean/std. With 5 trades, std is unreliable and mean is dominated by noise. PROM explicitly adjusts for sample size.

**Why not profit factor?** Profit factor = gross_wins / gross_losses. It is undefined when there are no losses and has no sample-size adjustment.

**Why not raw P&L?** P&L has no risk adjustment and no sample-size adjustment. A single lucky trade can dominate.

### Neighbor-Averaging (Ch.10 p.235)

**Design choice:** Smooth the PROM landscape before selecting the winner.

**Justification:** Pardo Ch.10 p.235 introduces neighbor-averaging as a technique to select parameter values on plateaus rather than isolated spikes. A parameter on a plateau has robust performance — small changes don't dramatically alter results. An isolated spike likely reflects noise.

**Implementation:** For parameter value p with neighbor radius k:
```
smoothed_PROM(p) = mean(PROM(p-k), ..., PROM(p), ..., PROM(p+k))
```

### Optimization Profile (Ch.10 p.260-268)

**Design choice:** Three quality checks per IS window — statistical significance, distribution, shape.

**Justification:** Pardo Ch.10 p.260-268 describes the optimization profile as a diagnostic tool for IS window quality. The three checks detect:

1. **Statistical significance (>=20% profitable):** If fewer than 20% of parameter sets are profitable, the strategy fundamentally doesn't work in this regime (p.261). Below 5% is catastrophic failure.

2. **Distribution (winner within 1 std dev):** If the winner is an extreme outlier relative to other profitable parameters, it is likely a statistical artifact (p.263).

3. **Shape (smooth landscape):** A smooth landscape (captured by neighbor-averaging) indicates genuine structure rather than noise (p.265-268).

### Step Sizing (Ch.10 p.252)

**Design choice:** Use proportional step sizes (~30-50 candidates per dimension) rather than step=1 for all ranges.

**Justification:** Pardo Ch.10 p.252 warns:

> *"Excessively fine scanning of a parameter range can be a significant contributing factor to overfitting."*

For a range like SMA period 50-250, step=1 produces 201 candidates — far more than needed and increasing the risk of overfitting. Step=5 produces 41 candidates, sufficient to identify the optimal region while avoiding over-scanning.

### Parameter Count (Ch.10 p.249)

**Design choice:** Warn when total WFO parameters exceed 10, hard limit at ~15.

**Justification:** Pardo Ch.10 p.249:

> *"It is always best to have the smallest number of optimizable parameters possible."*

Each additional parameter multiplicatively increases the search space and reduces statistical validity for a given amount of data. With 10-15 years of Moroccan stock data (2,500-3,800 daily bars), the practical limit is approximately 10-15 total WFO parameters.

### Walk-Forward Efficiency (Ch.11)

**Design choice:** WFE >= 50% as the acceptance threshold.

**Justification:** Pardo Ch.11 establishes WFE = annualized OOS / annualized IS as the measure of optimization transfer quality. WFE >= 50% indicates that more than half of the IS performance transfers to OOS — the optimization is finding real patterns, not noise.

Below 50%, the gap between IS and OOS is too large to trust the optimization process. The strategy may work in-sample but consistently underperforms out-of-sample.

---

## Secondary Source: Kelly (1956)

Kelly, J.L. (1956). "A New Interpretation of Information Rate." *Bell System Technical Journal*, 35(4), 917-926.

**Design choice:** Use the Kelly criterion for position sizing, computed from concatenated OOS trades.

**Justification:** Kelly derived the fraction of capital to bet that maximizes the long-term geometric growth rate:

```
f* = W - (1-W) / R
```

Where W = win rate, R = win/loss ratio. This is optimal in the information-theoretic sense — it maximizes the expected logarithm of wealth, which is equivalent to maximizing long-term compound growth.

**Why from OOS trades?** The Kelly inputs (W, R) must be estimated from data. Using IS trades would be circular — the parameters were optimized on IS data, so IS trade statistics are biased upward. OOS trades provide unbiased estimates because the data was never seen during optimization.

---

## Tertiary Source: Thorp (2006)

Thorp, E.O. (2006). "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market." In Zenios, S.A., & Ziemba, W.T. (Eds.), *Handbook of Asset and Liability Management*, Vol. 1. North-Holland.

**Design choice:** Offer half-Kelly as a conservative alternative.

**Justification:** Thorp demonstrates that the Kelly criterion, while theoretically optimal, is aggressive in practice. The full Kelly fraction maximizes growth rate but also maximizes volatility near the optimum. Half-Kelly sacrifices approximately 25% of growth rate (since growth is quadratic near the optimum) while substantially reducing drawdown risk.

For estimated (rather than known) win rates and W/L ratios — which is always the case in trading — half-Kelly provides a more practical recommendation.

---

## Secondary Source: Bailey & López de Prado (2014)

Bailey, D.H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality." *Journal of Portfolio Management*, 40(5), 94-107.

### Monte Carlo Permutation Test

**Design choice:** Shuffle OOS trade returns 10,000 times and compute p-value to test whether strategy performance is distinguishable from random.

**Justification:** The permutation test is the most assumption-free statistical significance test available. It requires no distributional assumptions — only the null hypothesis that the ordering of trades does not matter. If a strategy's performance can be replicated by randomly reordering its own trades, it has no genuine predictive timing.

**Why shuffle returns, not prices?** Shuffling prices destroys the return distribution. Shuffling returns preserves the set of outcomes but randomizes their timing — testing whether the strategy's entry/exit timing adds value.

**Visualization:** Fan chart of 10,000 simulated equity curves with the actual strategy overlaid. Percentile bands (5th, 25th, 50th, 75th, 95th) make the p-value viscerally intuitive — the user sees whether their strategy stands out from noise.

### Deflated Sharpe Ratio (DSR)

**Design choice:** Correct observed Sharpe for (a) multiple testing (N parameter combinations) and (b) non-normality (skewness, kurtosis).

**Justification:** Bailey & López de Prado proved that the expected maximum Sharpe among N independent tests grows as √(2 × ln(N)). With 1,000+ parameter combinations in WFO, the "best" Sharpe is substantially inflated. DSR subtracts this expected inflation and tests whether the residual is significant.

**Formula:**
```
σ(SR) = √[(1 - γ₃ × SR + (γ₄ - 1)/4 × SR²) / T]
SR_benchmark = √(2 × ln(N)) × σ(SR)
DSR = (SR_observed - SR_benchmark) / σ(SR)
```

### Relationship Between the Three Validation Metrics

| Metric | What it validates | What it misses |
|--------|-------------------|----------------|
| WFE | Optimization process transfers IS → OOS | Absolute performance level, multiple testing |
| Monte Carlo | Absolute performance is non-random | Whether the Sharpe is inflated by data mining |
| DSR | Sharpe is significant after multiple-testing correction | Whether OOS performance came from genuine IS → OOS transfer |

All three are complementary. No single metric is sufficient. A strategy must pass all three.

---

## Extension Beyond Literature

### Kelly Sizing from WFO OOS (not in Pardo)

Pardo does not discuss position sizing. He focuses on parameter optimization and validation. Our addition of Kelly sizing from concatenated OOS trades is an extension that:

1. Uses only OOS data (no data snooping)
2. Does not modify the WFO pipeline (additive)
3. Follows standard practice (Kelly 1956, Thorp 2006)
4. Solves the "a calibrer" problem on the strategy page

**Potential concern:** The OOS trades come from different IS windows with different optimal parameters. Is it valid to concatenate them? Yes — each OOS window uses the best parameter for its preceding IS window, which is exactly how the strategy would be traded live (re-optimize periodically, trade with current optimal). The concatenated OOS trades represent the strategy's live trading performance under the WFO regime.

### Test Period (implicit in Pardo)

Pardo discusses reserving data for testing but does not formalize a "test period" as a distinct evaluation phase. Our implementation makes this explicit: data after the WFO period is a held-out test set that validates the entire WFO process, including configuration selection.

### Continuous Indicator Scoring (not in Pardo)

Pardo uses raw indicator values (RSI level, MA crossover). Our ATR-normalized continuous scores are a transformation that makes scores comparable across stocks with different price levels and volatilities. This does not violate any Pardo principle — entry/exit rules still operate on scores the same way Pardo's rules operate on raw values.

---

## Honest Limitations

### Data Length

Moroccan stocks have approximately 10-15 years of daily data. This limits:
- **Long horizon WFO:** IS windows of 10+ years leave little data for OOS and test period
- **Parameter count:** Fewer data points means fewer parameters can be reliably optimized
- **Walk-forward count:** Fewer windows means less statistical power for WFE

**Mitigation:** The system warns when data is insufficient and constrains parameter count.

### Transaction Cost Estimation

The cost model (brokerage + commission + slippage + TVA) is an estimate. Actual costs vary by broker, order size, and market conditions. Slippage in particular is difficult to model accurately for a market with limited liquidity like the Casablanca Stock Exchange.

**Mitigation:** Costs are configurable. Users should test sensitivity by running WFO with different cost assumptions.

### Regime Non-Stationarity

WFA assumes that the optimization process that worked in the past will continue to work. If the market undergoes a structural regime change (e.g., new regulation, major economic shift), past WFO results may not predict future performance.

**Mitigation:** The test period provides one check against this. The parameter evolution chart shows whether optimal parameters are drifting, which may indicate regime change.

### Multiple Testing Across Strategies

Running WFO on many strategies and selecting the one with the best WFE introduces a multiple testing problem at the strategy level. WFO validates individual strategies but does not account for how many strategies were tested before finding one that "works."

**Mitigation:** DSR corrects the Sharpe ratio for the number of parameter combinations tried within a single WFO run. Monte Carlo permutation testing provides an independent statistical significance check. However, neither accounts for how many *different strategies* (different indicator families, different rule structures) the user tested before finding one that passes. This remains a limitation — the user must exercise judgment about how many strategies they've tried.

### Kelly Fraction Estimation Uncertainty

Kelly's formula assumes known W and R. We estimate these from finite OOS trades. With 30-50 trades, the estimation error is substantial. Fractional Kelly (half-Kelly) partially addresses this, but does not eliminate the uncertainty.

**Mitigation:** Display confidence intervals alongside point estimates. Recommend half-Kelly when trade count is low.

---

## Full Bibliography

1. Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies*. 2nd Edition. Wiley.
2. Bailey, D.H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality." *Journal of Portfolio Management*, 40(5), 94-107.
3. Bailey, D.H., Borwein, J.M., López de Prado, M., Zhu, Q.J. (2014). "Pseudo-Mathematics and Financial Charlatanism." *Notices of the AMS*, 61(5), 458-471.
4. Arian, H.R., Norouzi M., D., Seco, L.A. (2024). "Backtest Overfitting in the Machine Learning Era: A Comparison of Out-of-Sample Testing Methods in a Synthetic Controlled Environment." *Knowledge-Based Systems*, 305.
5. Kelly, J.L. (1956). "A New Interpretation of Information Rate." *Bell System Technical Journal*, 35(4), 917-926.
6. Thorp, E.O. (2006). "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market." In *Handbook of Asset and Liability Management*, Vol. 1. North-Holland.
7. Vince, R. (1990). *Portfolio Management Formulas*. Wiley.
8. López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
9. Chan, E. (2008). *Quantitative Trading*. Wiley.
10. Murphy, J.J. (1999). *Technical Analysis of the Financial Markets*. NYIF.
11. Elder, A. (1993). *Trading for a Living*. Wiley.
12. Wilder, J.W. (1978). *New Concepts in Technical Trading Systems*. Trend Research.
13. Appel, G. (2005). *Technical Analysis: Power Tools for Active Investors*. FT Press.
