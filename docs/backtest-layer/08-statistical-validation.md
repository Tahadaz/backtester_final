# 08 — Statistical Validation: Monte Carlo Permutation Test & Deflated Sharpe Ratio

---

## Purpose

WFE validates whether the optimization process transfers from in-sample to out-of-sample. But two questions remain unanswered:

1. **Is the strategy's OOS performance statistically distinguishable from random?** A strategy could achieve WFE >= 50% by chance if the OOS returns happen to align with IS returns without genuine predictive power.

2. **Is the Sharpe ratio inflated by multiple testing?** When you test hundreds or thousands of parameter combinations, some will produce good OOS results purely by chance. The raw Sharpe ratio does not account for how many alternatives were tried.

This document describes two institutional-grade statistical tests applied **after** the WFO pipeline completes, using the existing OOS trade data. Both are post-processing steps — they require no additional backtesting.

---

## Monte Carlo Permutation Test

### What It Does

Takes the sequence of OOS trades from the winning WFO configuration and asks: "If I randomly shuffled the order of returns many times, how often would I get a result as good or better than the actual strategy?"

This produces a **p-value** — the probability of observing the strategy's performance (or better) under the null hypothesis that the trade returns are randomly ordered.

### Procedure

```python
def monte_carlo_permutation_test(
    oos_trades: list[Trade],
    n_simulations: int = 10_000,
    metric: str = "total_return"
) -> MonteCarloResult:
    """
    Permutation test on concatenated OOS trades from winning WFO config.

    1. Compute actual strategy metric from the real trade sequence
    2. Shuffle trade returns 10,000 times
    3. For each shuffle, recompute the metric
    4. p-value = fraction of shuffles that achieved >= actual metric
    """
    actual_returns = [t.net_return for t in oos_trades]
    actual_metric = compute_metric(actual_returns, metric)

    # Store all simulated equity curves for visualization
    simulated_curves = []
    n_exceed = 0

    for _ in range(n_simulations):
        shuffled = np.random.permutation(actual_returns)
        sim_metric = compute_metric(shuffled, metric)
        sim_curve = compute_equity_curve(shuffled)
        simulated_curves.append(sim_curve)

        if sim_metric >= actual_metric:
            n_exceed += 1

    p_value = (n_exceed + 1) / (n_simulations + 1)  # +1 to avoid p=0

    return MonteCarloResult(
        p_value=p_value,
        actual_metric=actual_metric,
        simulated_curves=simulated_curves,
        actual_curve=compute_equity_curve(actual_returns),
        percentiles=compute_percentile_bands(simulated_curves)
    )
```

### What Gets Shuffled

The **net returns** of individual OOS trades are permuted. This preserves the distribution of returns (same mean, same variance, same set of values) but destroys the time ordering. If the strategy's performance depends on the specific sequence of trades (i.e., it has genuine predictive timing), shuffling will degrade it.

**What is preserved:** Total number of trades, set of individual returns, aggregate statistics (mean, std).

**What is destroyed:** Time ordering, serial correlation, any genuine market-timing signal.

### Acceptance Threshold

| p-value | Interpretation | Action |
|---------|---------------|--------|
| < 0.01 | Highly significant | Strong evidence the strategy is not random |
| 0.01 - 0.05 | Significant | Accept — strategy performance unlikely due to chance |
| 0.05 - 0.10 | Marginal | Warning — weak statistical evidence |
| > 0.10 | Not significant | Reject — cannot distinguish from random |

**Required: p < 0.05** for a strategy to pass statistical validation.

### Visualization: Equity Curve Fan Chart

This is the key visual output. The chart displays:

```
         Strategy Equity Curve (Fan Chart)
         ──────────────────────────────────

  Equity │
         │                           ╱ actual strategy (bold blue)
         │                        ╱╱
         │                     ╱╱╱
         │               ╱╱╱╱╱╱╱╱╱   95th percentile band
         │          ╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱
         │     ╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱  simulated curves (gray, transparent)
         │ ╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱
    1.0  │──────────────────────────────
         │ ╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲  5th percentile band
         │     ╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲╲
         └────────────────────────────── Trade index
```

**Components:**

1. **Gray band (all 10,000 simulated equity curves)** — drawn as individual semi-transparent lines, creating a "cloud" showing where random trade orderings end up
2. **Percentile bands** — shaded regions at 5th, 25th, 50th (median), 75th, 95th percentiles of the simulated final equity values
3. **Actual strategy equity curve** — bold colored line overlaid on the fan chart
4. **Final equity distribution** — histogram or density plot on the right margin showing where the actual strategy's final equity sits in the distribution of simulated final equities

**Interpretation:**
- If the bold strategy line is **above the 95th percentile band**: the strategy is clearly an outlier — strong evidence of genuine predictive power (p < 0.05)
- If the bold line is **within the cloud**: the strategy cannot be distinguished from random — no evidence of genuine signal
- If the bold line is **below the median**: the strategy is actually worse than random trade ordering

This visualization makes the p-value viscerally intuitive. The user doesn't need to understand permutation testing — they can simply see whether their strategy stands out from the noise.

---

## Deflated Sharpe Ratio (DSR)

### What It Does

Corrects the observed Sharpe ratio for two sources of inflation:

1. **Multiple testing (selection bias):** When you test N parameter combinations, the best one's Sharpe ratio is biased upward. The more combinations tried, the larger the bias.

2. **Non-normal returns:** Financial returns exhibit skewness and excess kurtosis. The standard Sharpe ratio assumes normality; when returns are fat-tailed or skewed, the standard error of the Sharpe estimate changes.

DSR produces a **test statistic** and corresponding **p-value** that answers: "Is this Sharpe ratio statistically significant after correcting for how many strategies were tried and for non-normality?"

### Formula

From Bailey & López de Prado (2014):

```
DSR = (SR_observed - SR_benchmark) / σ(SR)
```

Where:

```
SR_observed = Sharpe ratio of the winning strategy (from OOS trades)

SR_benchmark = expected maximum Sharpe under null hypothesis
             = √(2 × ln(N)) × σ_SR
             where N = total number of parameter combinations tested across WFO

σ(SR) = standard error of the Sharpe ratio, corrected for non-normality:
       = √[(1 - γ₃ × SR + (γ₄ - 1)/4 × SR²) / T]

γ₃ = skewness of OOS returns
γ₄ = kurtosis of OOS returns
T  = number of OOS trades
```

### Implementation

```python
def deflated_sharpe_ratio(
    oos_returns: np.ndarray,
    n_variants_tested: int,
    risk_free_rate: float = 0.0
) -> DSRResult:
    """
    Compute the Deflated Sharpe Ratio.

    Parameters:
        oos_returns: Array of OOS trade returns
        n_variants_tested: Total parameter combinations tested in WFO
        risk_free_rate: Risk-free rate (default 0 for simplicity)
    """
    T = len(oos_returns)
    sr = (oos_returns.mean() - risk_free_rate) / oos_returns.std()

    # Non-normality correction
    skew = scipy.stats.skew(oos_returns)
    kurt = scipy.stats.kurtosis(oos_returns, fisher=False)  # excess=False -> raw kurtosis

    sr_std = np.sqrt(
        (1 - skew * sr + (kurt - 1) / 4 * sr**2) / T
    )

    # Expected max Sharpe under null (multiple testing correction)
    sr_benchmark = np.sqrt(2 * np.log(n_variants_tested)) * sr_std

    # DSR test statistic
    dsr = (sr - sr_benchmark) / sr_std

    # One-sided p-value (is the observed Sharpe significantly above the benchmark?)
    p_value = 1 - scipy.stats.norm.cdf(dsr)

    return DSRResult(
        observed_sharpe=sr,
        benchmark_sharpe=sr_benchmark,
        dsr_statistic=dsr,
        p_value=p_value,
        skewness=skew,
        kurtosis=kurt,
        n_trades=T,
        n_variants=n_variants_tested,
        significant=p_value < 0.05
    )
```

### Inputs from WFO

| Input | Source |
|-------|--------|
| `oos_returns` | Net returns of concatenated OOS trades (same as Kelly inputs) |
| `n_variants_tested` | `diagnostics.total_variants_tested` from WFO results |
| `risk_free_rate` | 0 or Moroccan treasury rate (configurable) |

### Acceptance

| DSR p-value | Interpretation |
|-------------|---------------|
| < 0.05 | Sharpe is significant after correction — not a multiple-testing artifact |
| >= 0.05 | Sharpe may be inflated by data mining — strategy suspect |

---

## Combined Validation Summary

After WFO completes, the results page shows a **Statistical Validation** panel:

```
┌─────────────────────────────────────────────────────────┐
│  STATISTICAL VALIDATION                                 │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Walk-Forward Efficiency    62%       ✓ Pass (≥ 50%)    │
│  Monte Carlo p-value        0.003    ✓ Pass (< 0.05)   │
│  Deflated Sharpe Ratio      2.14     ✓ Pass (p < 0.05) │
│                                                         │
│  Verdict: STATISTICALLY VALIDATED                       │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  [Monte Carlo Fan Chart]                                │
│  Actual strategy final equity: 95.2nd percentile        │
│  10,000 simulations                                     │
└─────────────────────────────────────────────────────────┘
```

### What Each Metric Catches

| Metric | Failure mode it detects |
|--------|------------------------|
| **WFE ≥ 50%** | Poor IS → OOS transfer (parameter overfitting) |
| **Monte Carlo p < 0.05** | Performance indistinguishable from random (no genuine signal) |
| **DSR p < 0.05** | Sharpe inflated by multiple testing (data mining artifact) |

A strategy must pass **all three** to be considered statistically validated. Each metric is independent — a strategy can pass WFE but fail Monte Carlo (optimization transfers consistently, but the absolute performance level is not significant), or pass Monte Carlo but fail DSR (significant performance, but only because hundreds of parameter combos were tried).

---

## Computational Cost

Both tests are lightweight:

| Test | Input | Computation | Time |
|------|-------|-------------|------|
| Monte Carlo | OOS trade returns (already computed) | 10,000 array shuffles + cumulative sums | < 1 second |
| DSR | OOS trade returns + variant count | Single formula evaluation | Negligible |

Neither test requires additional backtesting. They are pure post-processing on existing WFO outputs.

---

## References

- Bailey, D.H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality." *Journal of Portfolio Management*, 40(5), 94-107.
- Bailey, D.H., Borwein, J.M., López de Prado, M., Zhu, Q.J. (2014). "Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance." *Notices of the AMS*, 61(5), 458-471.
- Evidence Based Technical Analysis (2006). "Monte-Carlo Evaluation of Trading Systems." — Permutation test methodology for trading strategies.
