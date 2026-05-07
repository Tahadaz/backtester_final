# Statistical Battery: Metrics & Formulas

## Overview

The Phase 1 evaluation computes a comprehensive battery of statistics for each (signal, stock, horizon) combination. This chapter defines each metric formally with formulas, interpretations, and citations.

---

## Information Coefficient (IC)

### Definition

**Information Coefficient** is the rank correlation between the factor signal and forward returns:

$$IC = \text{Spearman}\left( \text{signal}_t, \text{return}_{t+h} \right)$$

Where:
- $\text{signal}_t \in \{-1, 0, +1\}$
- $\text{return}_{t+h}$ = forward return at horizon $h$ (days)
- Spearman = rank-based correlation (robust to outliers)

### Interpretation

- **IC > 0**: Signal and forward returns move together (positive predictability).
- **IC ≈ 0**: No correlation; signal has no linear relation to returns.
- **IC < 0**: Signal and forward returns move opposite (negative predictability or shorting signal).

### Standard Error & t-Statistic

Raw IC is biased under autocorrelated returns. We use **Newey-West heteroskedasticity and autocorrelation consistent (HAC) standard error**:

$$\text{SE}_{\text{NW}} = \sqrt{\frac{\text{Var}(\text{IC})}{n} + 2 \sum_{k=1}^{L} \left(1 - \frac{k}{L+1}\right) \text{Cov}(\text{IC}, \text{IC}_{-k})}$$

**t-statistic**:

$$t_{\text{NW}} = \frac{IC}{\text{SE}_{\text{NW}}}$$

**Lag length**: $L = \lfloor \sqrt{n} \rfloor$ (or user-specified).

### Citation

- Newey, W. K. & West, K. D. (1987). "A Simple Positive Semi-definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix." *Econometrica*, 55(3), 703–708.

### Implementation

`core/quant_core/research/stats/ic.py:compute_ic_newey_west()`

---

## Information Coefficient Decay (IC Stability)

### Definition

Rolling IC computed over **63-day windows**; measures signal stability across market regimes.

$$\text{IC}_{\text{rolling}}(t) = \text{Spearman}\left( \text{signal}_{t-62:t}, \text{return}_{t-62+h:t+h} \right)$$

### Decay Metric

$$\text{IC}_{\text{decay}} = 1 - \frac{\text{mean}(\text{IC}_{\text{rolling}}, \text{recent 30 windows})}{\text{mean}(\text{IC}_{\text{rolling}}, \text{all windows})}$$

- **IC_decay > 0.3**: Signal's recent IC is <70% of historical average; flagged as unstable.
- **IC_decay < 0.1**: Signal is stable across windows.

### Interpretation

Low IC decay suggests genuine signal; high decay suggests the signal was lucky in earlier periods and has degraded (overfitting concern).

---

## Hit Rate

### Definition

**Hit rate** is the fraction of non-zero signal days where forward return has the same sign as the signal:

$$\text{Hit Rate} = \frac{\text{count}(\text{sign}(\text{signal}) \times \text{sign}(\text{return}) > 0)}{\text{count}(\text{signal} \neq 0)}$$

### 90% Confidence Interval (Wilson Score)

Instead of the standard Clopper-Pearson CI, we use **Wilson score interval** (more accurate for small samples):

$$p_{\text{low}}, p_{\text{high}} = \frac{1}{1 + \frac{z^2}{n}} \left[ p + \frac{z^2}{2n} \mp z \sqrt{\frac{p(1-p)}{n} + \frac{z^2}{4n^2}} \right]$$

Where $z = 1.645$ for 90% CI, $n$ = sample size, $p$ = observed hit rate.

### Interpretation

- **Hit rate > 0.5**: Signal has directional edge (likely positive return when signal is non-zero).
- **Hit rate ≈ 0.5**: No directional edge; signal is random.
- **Hit rate < 0.5**: Signal is negated; invert the signal.

### Citation

- Wilson, E. B. (1927). "Probable Inference, the Law of Succession, and Statistical Inference." *Journal of the American Statistical Association*, 22(158), 209–212.
- Online explainer: https://www.econometrics.blog/post/the-wilson-confidence-interval-for-a-proportion/
- See also: [docs/analytics-layer/03-bucket-matrix-per-stock.md](../analytics-layer/03-bucket-matrix-per-stock.md) — asymmetric per-bucket hit rate definition.

### Implementation

`core/quant_core/research/stats/hit_rate.py:compute_hit_rate_with_ci()`

---

## Sharpe Ratio

### Definition (Gross)

$$\text{Sharpe}_{\text{gross}} = \frac{\sqrt{252} \times \text{mean}(\text{return})}{\text{std}(\text{return})}$$

Where:
- 252 = trading days per year (annualization factor)
- return = daily PnL (before costs)

### Definition (Net)

$$\text{Sharpe}_{\text{net}} = \frac{\sqrt{252} \times (\text{mean}(\text{return}) - \text{mean cost})}{\text{std}(\text{return})}$$

Where `mean cost` = $\text{commission} \times \text{turnover}$.

### Interpretation

- **Sharpe > 1.0**: Defensible; annualized return is 1×+ volatility.
- **Sharpe > 0.5**: Modest; may not survive transaction costs or market frictions.
- **Sharpe < 0**: Consistently losing; signal is harmful.

### Implementation

`core/quant_core/research/stats/portfolio_stats.py:compute_sharpe()`

---

## Sortino Ratio

### Definition

Like Sharpe, but only penalizes **downside volatility**:

$$\text{Sortino} = \frac{\sqrt{252} \times \text{mean}(\text{return})}{\text{std}(\text{return if return} < 0)}$$

### Interpretation

- **Sortino > Sharpe**: Signal has larger upside moves than downside; attractive asymmetry.
- **Sortino ≈ Sharpe**: Symmetric returns; no special downside protection.

### Implementation

`core/quant_core/research/stats/portfolio_stats.py:compute_sortino()`

---

## Maximum Drawdown (MaxDD)

### Definition

$$\text{MaxDD} = \min_t \left( \frac{\text{cumulative\_pnl}(t) - \text{peak}(\text{cumulative\_pnl}(0:t))}{\text{peak}(\text{cumulative\_pnl}(0:t))} \right)$$

### Interpretation

- **MaxDD = -0.20**: Signal lost 20% of peak value at worst.
- **MaxDD > -0.50**: Drawdown is tolerable for many strategies.

### Implementation

`core/quant_core/research/stats/portfolio_stats.py:compute_max_dd()`

---

## Calmar Ratio

### Definition

$$\text{Calmar} = \frac{\sqrt{252} \times \text{mean}(\text{return})}{\text{|MaxDD|}}$$

### Interpretation

- **Calmar > 1.0**: Return exceeds worst drawdown (on annualized basis).
- **Calmar < 0.5**: Drawdown dominates returns.

### Implementation

`core/quant_core/research/stats/portfolio_stats.py:compute_calmar()`

---

## Conditional Return T-Statistic

### Definition

Newey-West t-statistic testing whether **mean return conditioned on non-zero signal** is significantly different from zero:

$$t_{\text{cond}} = \frac{\text{mean}(\text{return} | \text{signal} \neq 0)}{\text{SE}_{\text{NW}}(\text{return} | \text{signal} \neq 0)}$$

### Interpretation

- **|t| > 1.96**: Significant at 5% level (two-tailed).
- **|t| > 1.645**: Significant at 10% level.

This is the **primary test** for FDR correction; p-values are derived from this t-statistic via two-tailed normal CDF.

### Implementation

`core/quant_core/research/stats/portfolio_stats.py:compute_conditional_return_tstat()`

---

## Deflated Sharpe Ratio (DSR)

### Definition

Penalizes Sharpe for **number of trials**, **variance of trial outcomes**, and **backtest duration**:

$$\text{DSR} = \text{Sharpe} \times \left[ 1 - \frac{\gamma_E[\ln(M)]}{S \sqrt{n}} \right]$$

Where:
- $M$ = number of trials (e.g., 6 factor signals)
- $\gamma_E$ = Euler–Mascheroni constant (~0.5772)
- $S$ = Sharpe ratio (raw)
- $n$ = number of observations

### Interpretation

- **DSR > 0.5**: Defensible Sharpe after overfitting penalty.
- **DSR > 0**: More likely genuine than spurious.
- **DSR < 0**: Likely false positive; Sharpe does not survive haircut for multiple comparisons.

### Citation

- Harvey, C. R., Liu, Y., & Zhu, H. (2016). "...and the Cross-Section of Expected Returns." *Review of Financial Studies*, 29(1), 5–68.

### Implementation

`core/quant_core/research/stats/portfolio_stats.py:compute_dsr()`

---

## Probabilistic Sharpe Ratio (PSR)

### Definition

Bayesian posterior probability that **true Sharpe > 0**, given observed sample:

$$\text{PSR} = \Phi\left( \frac{t_{\text{Sharpe}} \sqrt{n}}{\sqrt{1 - \gamma_E / S}} \right)$$

Where:
- $t_{\text{Sharpe}}$ = observed Sharpe ratio
- $\Phi$ = standard normal CDF
- $n$ = observation count
- $\gamma_E$ = skewness/kurtosis penalty (simplified)

### Interpretation

- **PSR > 0.95**: >95% confidence Sharpe > 0 (strong evidence).
- **PSR > 0.80**: >80% confidence (acceptable).
- **PSR < 0.50**: Likely no genuine edge.

### Citation

- Prado, M. L. de (2016). "The Sharpe Ratio Everywhere." In *Advances in Financial Machine Learning*, Ch. 5. Wiley.

### Implementation

`core/quant_core/research/stats/portfolio_stats.py:compute_psr()`

---

## Turnover

### Definition

$$\text{Turnover} = \frac{1}{n} \sum_t \text{|position}(t) - \text{position}(t-1)\text{|}$$

Where position ∈ {-1, 0, +1}. **Maximum turnover = 2.0** (fully reversing every day).

### Cost Impact

$$\text{Cost per day} = \text{Turnover} \times \text{Commission}_{\text{bps}} / 10000$$

For Phase 1: commission = 33 bps per action, so **round-trip cost = 66 bps if position reverses**.

### Implementation

`core/quant_core/research/stats/portfolio_stats.py:compute_turnover()`

---

## Bootstrap Confidence Interval (90%)

### Definition

1. Resample (with replacement) **blocks** of returns (block size ~5 days, preserving autocorrelation).
2. Compute Sharpe for each of 500 bootstrap samples.
3. Extract 5th and 95th percentiles.

$$\text{CI}_{90\%} = [\text{percentile}(\text{bootstrap\_sharpes}, 5), \text{percentile}(\text{bootstrap\_sharpes}, 95)]$$

### Interpretation

- **Narrow CI**: Sharpe estimate is stable; genuine signal likely.
- **Wide CI**: High uncertainty; Sharpe may be a fluke.

### Implementation

`core/quant_core/research/stats/robustness.py:compute_bootstrap_ci()`

---

## Benjamini-Hochberg FDR Correction

### Definition

**False Discovery Rate** (FDR) is the **expected proportion of false rejections among all rejections**:

$$\text{FDR} = E\left[ \frac{\text{# false rejections}}{\text{# total rejections}} \right]$$

**Benjamini-Hochberg procedure**:
1. Rank p-values from smallest to largest: $p_{(1)} \leq p_{(2)} \leq \cdots \leq p_{(m)}$.
2. Find largest $i$ such that $p_{(i)} \leq \frac{i}{m} q$.
3. Reject hypotheses $H_1, \ldots, H_i$.

For Phase 1: $m = 6 \text{ signals} \times 8 \text{ stocks} \times 5 \text{ horizons} = 240$ tests; $q = 0.10$.

### Interpretation

- **FDR-passing signal**: <10% expected false-discovery rate among all passing signals.
- **Multiple comparisons without FDR**: Expect ~6 false positives by chance (0.05 × 120 tests).

### Citation

- Benjamini, Y. & Hochberg, Y. (1995). "Controlling the False Discovery Rate: A Practical and Powerful Approach to Multiple Testing." *Journal of the Royal Statistical Society*, 57(1), 289–300.

### Implementation

`core/quant_core/research/stats/fdr.py:benjamini_hochberg()`

---

## Harvey-Liu Haircut

### Definition

An alternative overfitting penalty, sometimes applied in addition to DSR:

$$\text{Haircut} = 1 - \frac{e^{-1} \gamma_E \ln(M)}{2 S^2 \sqrt{n}}$$

### Interpretation

Stricter than DSR; useful for high-dimensional searches (M >> 1).

### Citation

- Harvey, C. R., Liu, Y., & Zhu, H. (2016), op. cit.

### Implementation

`core/quant_core/research/stats/portfolio_stats.py:compute_harvey_liu_haircut()`

---

## Summary Table

| Metric | Type | Range | Interpretation |
|--------|------|-------|-----------------|
| IC | Correlation | [-1, 1] | Spearman rank correlation + NW t-stat |
| IC Decay | Stability | [0, 1] | 1 = unstable; 0 = stable |
| Hit Rate | Directional | [0, 1] | Fraction of signals correct |
| Sharpe (net) | Risk-adjusted return | ℝ | √252 × return / volatility (after costs) |
| Sortino | Downside-adjusted return | ℝ | Like Sharpe but penalizing downside only |
| MaxDD | Drawdown | [-1, 0] | Worst peak-to-trough loss |
| Calmar | Return / Drawdown | ℝ | Sharpe / \|MaxDD\| |
| Conditional t-stat | Hypothesis test | ℝ | Newey-West t-stat on signal conditional returns |
| DSR | Overfitting-adjusted | [-∞, Sharpe] | Sharpe × [1 - overfitting penalty] |
| PSR | Bayesian confidence | [0, 1] | P(true Sharpe > 0 \| data) |
| Turnover | Rebalancing frequency | [0, 2] | Avg \|Δposition\| per day |
| Bootstrap CI | Robust uncertainty | [CI_low, CI_high] | 90% confidence on Sharpe via resampling |
| FDR (BH) | Multiple testing | [0, q] | False-discovery rate control at q=0.10 |

---

## Implementation Reference

All metrics are implemented in `core/quant_core/research/stats/`:

- `ic.py`: Information Coefficient
- `hit_rate.py`: Hit rate with Wilson CI
- `portfolio_stats.py`: Sharpe, Sortino, MaxDD, Calmar, conditional t-stat, DSR, PSR, turnover, Harvey-Liu
- `robustness.py`: Bootstrap CI
- `fdr.py`: Benjamini-Hochberg FDR

Each function is deterministic and fully tested.

---

## References

- Newey & West (1987), Econometrica
- Wilson (1927), JASA
- Harvey, Liu, & Zhu (2016), RFS
- Prado (2016), Advances in Financial Machine Learning
- Benjamini & Hochberg (1995), JRSS
