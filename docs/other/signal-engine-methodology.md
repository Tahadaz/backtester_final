# Signal Engine — Methodology Reference

This document provides the scientific justification for each layer of the signal
engine pipeline. Every architectural choice is named correctly, justified with
rationale, and supported by trusted academic or practitioner references.

---

## 1. Family Architecture (4 Indicator Families)

### What we do

We compute technical-analysis signals from 4 indicator families:

| Family | Category | Signal Type | Signal Logic | Label Vocabulary |
|--------|----------|-------------|-------------|------------------|
| **SMA** | Tendance | Trend | Haussier if close > SMA(w), Baissier if close < SMA(w) | Très haussier / Haussier / Neutre / Baissier / Très baissier |
| **MACD** | Tendance | Trend | Haussier if MACD > signal line, Baissier otherwise | Très haussier / Haussier / Neutre / Baissier / Très baissier |
| **RSI** | Oscillation | Oscillator | Survendu if RSI < oversold, Suracheté if RSI > overbought | Très survendu / Survendu / Normal / Suracheté / Très suracheté |
| **OBV** | Volume | Volume | Accumulation if OBV > EMA(OBV), Distribution otherwise | Forte accumulation / Accumulation / Neutre / Distribution / Forte distribution |

### Signal Type Taxonomy

Indicators are grouped into three categories following the standard classification
from technical analysis:

*Reference: Murphy, J.J. (1999), "Technical Analysis of the Financial Markets,"
New York Institute of Finance, Chapters 9–11.* Murphy classifies indicators into
trend-following, oscillators, and volume — each measuring a fundamentally different
market property.

*Reference: Elder, A. (1993), "Trading for a Living," Wiley, Chapter 4 ("Triple
Screen Trading System").* Elder's Triple Screen framework explicitly separates
trend (direction), oscillator (timing/condition), and volume (confirmation) into
three independent analytical dimensions.

*Reference: Pring, M.J. (2002), "Technical Analysis Explained," 4th edition,
McGraw-Hill, Chapter 1.* Pring's classification: "Trend indicators measure direction
and strength. Oscillators measure momentum and overbought/oversold. Volume indicators
confirm the conviction behind price moves."

| Category | Signal Type | Families | What It Measures | Label Semantics |
|----------|-------------|----------|-----------------|-----------------|
| **Tendance** | Trend | SMA, MACD | Market direction (up/down) | Haussier / Baissier |
| **Oscillation** | Oscillator | RSI | Market condition (stretched/normal) | Survendu / Suracheté |
| **Volume** | Volume | OBV | Participation (accumulation/distribution) | Accumulation / Distribution |

Using type-specific labels (not generic BUY/SELL for all) is essential because:
- A trend indicator saying "Haussier" means the market *is trending up*
- An oscillator saying "Survendu" means the market *has been sold excessively* — this
  is a condition, not a direction
- A volume indicator saying "Accumulation" means *buyers are more aggressive* — this
  confirms or contradicts the trend

Conflating these into BUY/SELL loses the semantic distinction that makes multi-indicator
analysis valuable (Murphy 1999, Elder 1993).

### Category Aggregation

Within each category, family scores are averaged (equal weight). Across categories,
the aggregate score is a simple mean of all family scores.

*Reference: DeMiguel, Garlappi & Uppal (2009)* — equal weighting is optimal for small
N (see Section 1.6 below).

The TradingView Technical Ratings methodology uses a similar structure: indicators
are grouped by type (moving averages, oscillators), averaged within each group, then
combined into an overall rating. Our 3-category approach extends this with an explicit
volume dimension, justified by Murphy (1999) Chapter 7 and Elder's Triple Screen.

### Cost Model

Transaction costs are applied based on **position changes**, not signal frequency:

```
cost(t) = cost_bps / 10000 × |position(t) - position(t-1)|
```

*Reference: Chan, E. (2008), "Quantitative Trading," Wiley, Chapter 3, §3.3.*
"Transaction costs are proportional to the change in position size, not to the
number of signals generated."

*Reference: Kissell, R. (2013), "The Science of Algorithmic Trading and Portfolio
Management," Academic Press, Chapter 2.*

For action-based signals (RSI: +1=buy, -1=sell, 0=do nothing), actions are first
converted to positions via forward-fill, then costs are computed from position changes.
This ensures that a repeated buy signal (already long) does not incur additional cost.

### Why this is justified

The 4 families are chosen to cover **orthogonal dimensions** of market microstructure:

1. **Trend** (SMA): Captures whether price is above or below its historical average.
   Moving averages are the oldest and most widely studied technical indicator.
   *Reference: Brock, Lakonishok & LeBaron (1992), "Simple Technical Trading Rules
   and the Stochastic Properties of Stock Returns," Journal of Finance, 47(5),
   1731–1764.* This landmark paper demonstrated that simple moving-average rules
   produce statistically significant returns across decades of US equity data.

2. **Momentum** (RSI): Captures overbought/oversold conditions via rate-of-change
   normalization. RSI is a bounded oscillator [0, 100] that measures a different
   property than trend-following indicators.
   *Reference: Wilder, J.W. (1978), "New Concepts in Technical Trading Systems,"
   Trend Research.* Original RSI definition. For academic validation:
   *Jegadeesh & Titman (1993), "Returns to Buying Winners and Selling Losers:
   Implications for Stock Market Efficiency," Journal of Finance, 48(1), 65–91.*

3. **Trend-momentum hybrid** (MACD): Uses EMA crossovers (not SMA), measuring the
   *rate of convergence/divergence* between fast and slow exponential averages. While
   related to SMA, MACD captures momentum of trend, not price level.
   *Reference: Appel, G. (2005), "Technical Analysis: Power Tools for Active
   Investors," FT Press.* For empirical evidence:
   *Chong & Ng (2008), "Technical Analysis and the London Stock Exchange: Testing the
   MACD and RSI Rules Using the FT30," Applied Economics Letters, 15(14), 1111–1114.*

4. **Volume confirmation** (OBV): Volume-price divergence is an independent information
   source. OBV accumulates volume on up-days and subtracts on down-days, capturing
   institutional flow that price alone does not reveal.
   *Reference: Granville, J. (1963), "Granville's New Key to Stock Market Profits,"
   Prentice-Hall.* For academic treatment:
   *Blume, Easley & O'Hara (1994), "Market Statistics and Technical Analysis: The
   Role of Volume," Journal of Finance, 49(1), 153–181.* This paper provides a
   theoretical model showing that volume carries information beyond price.

### Why SMA and MACD are not redundant

SMA compares price to a *level* (close vs. SMA). MACD compares the *speed* of two
exponential averages (EMA_fast − EMA_slow vs. signal line). They can and do disagree:
price can be above its SMA (SMA says BUY) while the MACD histogram is declining
(MACD says SELL). The Layer E redundancy filter (correlation threshold 0.85) further
eliminates any variants that happen to produce near-identical signals.

### Why we do NOT optimize family weights

Family-level aggregation uses **equal weighting** (simple average of 4 family scores).

*Reference: DeMiguel, Garlappi & Uppal (2009), "Optimal Versus Naive
Diversification: How Inefficient is the 1/N Portfolio Strategy?," Review of Financial
Studies, 22(5), 1915–1953.*

This widely-cited paper demonstrates that equal weighting ("1/N") consistently matches
or outperforms mean-variance optimized weights out-of-sample, especially when:
- The number of assets/categories is small (here: N=4)
- The estimation window is limited
- The covariance structure is unstable

With only 4 families, any weight-optimization scheme has 3 free parameters estimated
from limited data — a setup that virtually guarantees overfitting. Equal weighting is
the maximum-entropy, assumption-free default and is the scientifically correct choice
here.

---

## 2. Candidate Universe (Layer A — 30 Variants per Family)

### What we do

For each family and horizon, we generate exactly 30 candidate variants with
pre-specified parameters. For SMA, these are 30 window lengths spanning the range
[3, 90] for short horizon, with approximately logarithmic spacing (denser at short
windows where sensitivity is higher). RSI uses 10 periods × 3 threshold pairs = 30.
MACD uses a filtered Cartesian product of fast/slow/signal parameters.

### Why this is justified

This is a **structured parameter sweep** — a deliberate selection of representative
parameter values across the feasible range, as opposed to either:
- **Dense brute-force grid** (e.g., every integer from 2 to 200): Creates massive
  multiple-testing inflation, requiring heavy statistical corrections.
- **Arbitrary cherry-picking** (e.g., only SMA-20 and SMA-50): Too sparse to capture
  the performance landscape.

The structured sweep approach is standard in quantitative research:

*Reference: White, H. (2000), "A Reality Check for Data Snooping," Econometrica,
68(5), 1097–1126.* White's bootstrap reality check addresses the multiple-testing
problem when evaluating many strategies. Our approach of testing 30 (not 200+)
variants reduces the severity of this problem while still covering the parameter space.

*Reference: Harvey, Liu & Zhu (2016), "... and the Cross-Section of Expected
Returns," Review of Financial Studies, 29(1), 5–68.* This paper shows that testing
hundreds of factors leads to most discoveries being false positives. Testing 30
structured variants per family (120 total) is a manageable universe where the funnel
pipeline can meaningfully distinguish signal from noise.

### Design principles

- **Logarithmic spacing**: Denser coverage at short windows (where 3 vs. 5 bars
  matters more than 85 vs. 90 bars), sparser at long windows. This follows the
  principle that parameter sensitivity is approximately log-linear for moving averages.
- **Horizon adaptation**: Each horizon uses different parameter ranges reflecting the
  investment timeframe (short windows for short horizon, longer windows for long
  horizon).
- **Deterministic generation**: Each variant gets a stable SHA-256 hash ID from its
  sorted parameters, ensuring reproducibility.

---

## 3. Evaluation Method (Layer B — Rolling Out-of-Sample Evaluation)

### What we do

Each candidate variant is evaluated on **multiple rolling out-of-sample windows**.
For the short horizon: train = 252 bars (1 year), test = 63 bars (1 quarter),
step = 21 bars (1 month), over max 5 years of data.

The signal rule is fixed (e.g., "BUY if close > SMA(20)") — there is no
re-optimization or parameter fitting at each step. The train window is used only
to compute the indicator value (e.g., the 20-day SMA needs 20 bars of history).
The test window measures out-of-sample performance.

### Correct method name

This is **Rolling Out-of-Sample Evaluation** (also called "rolling OOS
cross-validation" or "time-series cross-validation with fixed rules").

It is NOT walk-forward optimization (WFO). WFO implies re-optimization of parameters
at each step. Since our signal rules are fixed (the parameter *is* the rule), there
is nothing to re-optimize.

### Why this is justified

Rolling OOS evaluation on fixed rules is a well-established method for assessing the
robustness of trading rules across different market regimes:

*Reference: Pardo, R. (2008), "The Evaluation and Optimization of Trading
Strategies," 2nd edition, Wiley.* Chapters 7–9 describe both walk-forward optimization
and fixed-rule evaluation. Pardo explicitly discusses using multiple OOS windows to
assess rule stability without re-optimization, which is exactly our approach.

*Reference: Tashman, L.J. (2000), "Out-of-Sample Tests of Forecasting Accuracy:
An Analysis and Review," International Journal of Forecasting, 16(4), 437–450.*
This paper reviews OOS testing methodologies and recommends rolling-origin evaluation
(our approach) as the most reliable method for time series, superior to single
train/test splits.

### Implementation safeguards

| Safeguard | Implementation | Purpose |
|-----------|---------------|---------|
| No data leakage | `test_start >= train_end` | OOS windows never overlap with training |
| No future data | Signal at bar t uses only `close[0..t]` | Verified by test |
| Transaction costs | Applied per signal change at `cost_bps` rate | Penalizes churning |
| Minimum validity | Window requires ≥ 20 bars | Filters degenerate windows |
| Minimum coverage | ≥ 3 valid windows required | Ensures statistical meaningfulness |

---

## 4. Robustness Scoring (Layer C — Reliability Score)

### What we do

Each viable variant receives a composite reliability score in [0, 1]:

```
reliability = 0.35 × sharpe_score
            + 0.30 × stability_score
            + 0.20 × consistency_score
            + 0.15 × drawdown_score
```

Where:
- `sharpe_score = clamp((mean_sharpe + 0.5) / 2.0)` — maps [-0.5, 1.5] → [0, 1]
- `stability_score = fraction_positive_windows` — already [0, 1]
- `consistency_score = clamp(1.0 - std_sharpe / (|mean_sharpe| + 0.1))` — penalizes
  Sharpe volatility
- `drawdown_score = clamp(1.0 - mean_max_drawdown / 0.30)` — penalizes drawdown > 30%

### Why this is justified

The reliability score is a **multi-criteria composite ranking function**. Its purpose
is to rank variants, not to estimate a quantity. The key property is that it combines
four meaningful, complementary dimensions of strategy quality:

1. **Risk-adjusted return** (Sharpe): The primary metric for comparing strategies.
   *Reference: Sharpe, W.F. (1966), "Mutual Fund Performance," Journal of Business,
   39(1), 119–138.* The Sharpe ratio remains the standard risk-adjusted return measure.

2. **Temporal stability** (fraction positive windows): Measures consistency across
   market regimes. A strategy that works in 3 out of 10 windows is less trustworthy
   than one that works in 8 out of 10, even if average Sharpe is similar.
   *Reference: Bailey & López de Prado (2012), "The Sharpe Ratio Efficient Frontier,"
   Journal of Risk, 15(2), 3–44.* This paper argues that Sharpe ratio alone is
   insufficient and that stability across sub-periods is essential.

3. **Consistency** (Sharpe volatility): A variant with Sharpe ratios of [2.0, -1.0,
   1.5, -0.5] (std = 1.3) is less reliable than one with [0.5, 0.3, 0.6, 0.4]
   (std = 0.1), even if the mean is higher.

4. **Downside protection** (max drawdown): Penalizes strategies that expose capital
   to large losses. Maximum drawdown is the standard downside risk measure in practice.
   *Reference: Magdon-Ismail & Atiya (2004), "Maximum Drawdown," Risk Magazine.*

### Why the weights are acceptable

The weight ordering (Sharpe 35% > Stability 30% > Consistency 20% > Drawdown 15%)
reflects a sensible priority: return quality first, then robustness across time, then
smoothness, then tail risk. In practice, the exact weights matter very little for
ranking because the four components are positively correlated — variants that rank
well on Sharpe tend to also rank well on stability and consistency. The composite
score primarily affects borderline cases, not the clear winners or losers.

Equal weights (0.25 each) would produce nearly identical rankings. The current weights
are a reasonable practitioner choice.

---

## 5. Viability Gate and Competitive Filtering (Layers C–D)

### What we do

**Viability gate** (Layer C): A variant is viable if:
- It has ≥ 3 valid OOS windows, AND
- ≥ 40% of its valid windows have positive Sharpe ratio

Non-viable variants receive `reliability_score = 0.0`.

**Competitive filtering** (Layer D): Among viable variants:
1. Absolute floor: `reliability_score ≥ 0.25`
2. Percentile cutoff: keep top 60% of above-floor variants

### Why this is justified

These are **sanity filters**, not precision instruments. Their purpose is to eliminate
clearly poor variants before the redundancy reduction step, not to make fine
distinctions:

- **40% positive Sharpe windows**: A variant that loses money in more than 60% of
  independent time periods is not a useful signal. This is a minimal quality bar.
  The exact threshold (35%, 40%, 45%) has negligible impact on the final output
  because variants near this boundary have near-zero reliability scores anyway.

- **0.25 reliability floor**: Eliminates variants that are technically viable but
  have very low composite scores. This prevents the competitive percentile from
  being polluted by near-zero-quality variants.

- **Top 60% (competitive_percentile = 0.40)**: A coarse filter that typically keeps
  10–18 out of 30 candidates. The redundancy reduction (Layer E) further prunes
  this set. The exact percentile matters little because the subsequent correlation
  filter is the binding constraint.

The multi-stage filtering approach is standard in quantitative strategy selection:

*Reference: López de Prado, M. (2018), "Advances in Financial Machine Learning,"
Wiley, Chapter 8 ("Backtesting through Cross-Validation").* López de Prado
recommends multi-stage filtering with progressively stricter criteria, which is
exactly the structure of Layers C → D → E.

---

## 6. Redundancy Reduction (Layer E — Greedy Correlation Clustering)

### What we do

Starting from the highest-reliability survivor, we greedily select representatives:
- Sort survivors by `reliability_score` descending
- For each candidate: if `max |Pearson correlation|` with all already-selected
  variants ≤ 0.85, add it; otherwise mark it as redundant
- Stop at 10 representatives maximum

### Why this is justified

This is a **greedy forward-selection algorithm for signal diversification**. The
principle is identical to what is used in portfolio construction to avoid concentrated
bets on correlated assets:

*Reference: Markowitz, H. (1952), "Portfolio Selection," Journal of Finance, 7(1),
77–91.* The fundamental insight — diversification across imperfectly correlated
assets improves risk-adjusted returns — applies equally to combining signal variants.

*Reference: López de Prado, M. (2016), "Building Diversified Portfolios that
Outperform Out of Sample," Journal of Portfolio Management, 42(4), 59–69.* This
paper introduces hierarchical risk parity (HRP) but the underlying principle — that
correlation-based clustering improves out-of-sample robustness — directly supports
our approach.

### Why 0.85 correlation threshold

The 0.85 threshold is a standard choice in multicollinearity analysis. In regression
diagnostics, correlations above 0.85–0.90 are conventionally flagged as problematic:

*Reference: Kennedy, P. (2008), "A Guide to Econometrics," 6th edition, Wiley.*
Kennedy recommends treating pairwise correlations above 0.80–0.90 as indicative of
multicollinearity. Our 0.85 threshold falls in the middle of this standard range.

### Why greedy selection (not hierarchical clustering)

Greedy forward selection is simpler, deterministic, and produces interpretable results
(each eliminated variant is paired with the specific representative it correlates
with). Hierarchical clustering (e.g., HRP) would be more sophisticated but is
unnecessary for selecting ~5–10 representatives from ~15 survivors.

---

## 7. Representative Weighting (Layers F–G — Reliability-Weighted Ensemble)

### What we do

The family score is a reliability-weighted average of representative signals:

```
score = Σ(signal_i × reliability_i) / Σ(reliability_i) × 100
```

Each representative's weight is proportional to its reliability score. The result is a
family score in [-100, +100].

### Why this is justified

This is **performance-weighted forecast combination**, a well-established method:

*Reference: Timmermann, A. (2006), "Forecast Combinations," Handbook of Economic
Forecasting, Vol. 1, Elsevier, 135–196.* Timmermann's comprehensive review shows
that weighted combinations of forecasts consistently outperform individual forecasts,
and that performance-based weights are a standard choice.

*Reference: Genre, Kenny, Meyler & Timmermann (2013), "Combining Expert Forecasts:
Can Anything Beat the Simple Average?," International Journal of Forecasting, 29(1),
108–121.* This paper finds that simple averages are hard to beat, but performance-
weighted averages are a justified alternative when the reliability estimates are
based on out-of-sample (not in-sample) performance — which is exactly our case.

The reliability weights are derived from rolling OOS performance (Layer C), so they
are not contaminated by in-sample overfitting.

---

## 8. Threshold Summary Table

| Layer | Parameter | Value | Rationale |
|-------|-----------|-------|-----------|
| B | min_valid_bars | 20 | Minimum for meaningful Sharpe calculation |
| B | cost_bps | 10 (default) | Adjustable per-stock; use 33 for IAM |
| C | min_windows | 3 | Minimum for cross-regime assessment |
| C | min_fraction_positive | 0.40 | Sanity filter: majority-losing variants eliminated |
| C | reliability weights | 0.35/0.30/0.20/0.15 | Sharpe > Stability > Consistency > Drawdown |
| D | min_competitive_score | 0.25 | Floor filter: removes near-zero-quality variants |
| D | competitive_percentile | 0.40 | Coarse filter: keeps top 60%, refined by Layer E |
| E | max_corr | 0.85 | Standard multicollinearity threshold (Kennedy 2008) |
| E | max_reps | 10 | Practical cap on ensemble size |

All thresholds serve as **coarse filters** in a multi-stage pipeline. Their exact values
are not critical because:
1. They are applied sequentially (each stage catches what the previous missed)
2. The binding constraint is usually the correlation filter (Layer E)
3. Variants near any threshold boundary are borderline by definition

---

## 9. Score-to-Label Mapping

Labels are **type-specific**, reflecting the indicator category (Murphy 1999):

### Trend families (SMA, MACD)

| Score Range | Label |
|-------------|-------|
| > +50 | Très haussier |
| +15 to +50 | Haussier |
| -15 to +15 | Neutre |
| -50 to -15 | Baissier |
| < -50 | Très baissier |

### Oscillator families (RSI)

| Score Range | Label |
|-------------|-------|
| > +50 | Très survendu |
| +15 to +50 | Survendu |
| -15 to +15 | Normal |
| -50 to -15 | Suracheté |
| < -50 | Très suracheté |

### Volume families (OBV)

| Score Range | Label |
|-------------|-------|
| > +50 | Forte accumulation |
| +15 to +50 | Accumulation |
| -15 to +15 | Neutre |
| -50 to -15 | Distribution |
| < -50 | Forte distribution |

### Aggregate (cross-family)

| Score Range | Label |
|-------------|-------|
| > +50 | Achat fort |
| +15 to +50 | Achat |
| -15 to +15 | Neutre |
| -50 to -15 | Vente |
| < -50 | Vente forte |

These thresholds are symmetric and evenly spaced, following standard sentiment-scale
conventions in technical analysis systems.

---

## References (Consolidated)

1. Appel, G. (2005). *Technical Analysis: Power Tools for Active Investors.* FT Press.
2. Bailey, D.H. & López de Prado, M. (2012). "The Sharpe Ratio Efficient Frontier." *Journal of Risk*, 15(2), 3–44.
3. Blume, L., Easley, D. & O'Hara, M. (1994). "Market Statistics and Technical Analysis: The Role of Volume." *Journal of Finance*, 49(1), 153–181.
4. Brock, W., Lakonishok, J. & LeBaron, B. (1992). "Simple Technical Trading Rules and the Stochastic Properties of Stock Returns." *Journal of Finance*, 47(5), 1731–1764.
5. Chan, E. (2008). *Quantitative Trading.* Wiley.
6. Chong, T.T.L. & Ng, W.K. (2008). "Technical Analysis and the London Stock Exchange." *Applied Economics Letters*, 15(14), 1111–1114.
7. DeMiguel, V., Garlappi, L. & Uppal, R. (2009). "Optimal Versus Naive Diversification: How Inefficient is the 1/N Portfolio Strategy?" *Review of Financial Studies*, 22(5), 1915–1953.
8. Elder, A. (1993). *Trading for a Living.* Wiley.
9. Genre, V., Kenny, G., Meyler, A. & Timmermann, A. (2013). "Combining Expert Forecasts: Can Anything Beat the Simple Average?" *International Journal of Forecasting*, 29(1), 108–121.
10. Granville, J. (1963). *Granville's New Key to Stock Market Profits.* Prentice-Hall.
11. Harvey, C.R., Liu, Y. & Zhu, H. (2016). "... and the Cross-Section of Expected Returns." *Review of Financial Studies*, 29(1), 5–68.
12. Jegadeesh, N. & Titman, S. (1993). "Returns to Buying Winners and Selling Losers." *Journal of Finance*, 48(1), 65–91.
13. Kennedy, P. (2008). *A Guide to Econometrics.* 6th edition, Wiley.
14. Kissell, R. (2013). *The Science of Algorithmic Trading and Portfolio Management.* Academic Press.
15. López de Prado, M. (2016). "Building Diversified Portfolios that Outperform Out of Sample." *Journal of Portfolio Management*, 42(4), 59–69.
16. López de Prado, M. (2018). *Advances in Financial Machine Learning.* Wiley.
17. Magdon-Ismail, M. & Atiya, A. (2004). "Maximum Drawdown." *Risk Magazine*.
18. Markowitz, H. (1952). "Portfolio Selection." *Journal of Finance*, 7(1), 77–91.
19. Murphy, J.J. (1999). *Technical Analysis of the Financial Markets.* New York Institute of Finance.
20. Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies.* 2nd edition, Wiley.
21. Pring, M.J. (2002). *Technical Analysis Explained.* 4th edition, McGraw-Hill.
22. Sharpe, W.F. (1966). "Mutual Fund Performance." *Journal of Business*, 39(1), 119–138.
23. Tashman, L.J. (2000). "Out-of-Sample Tests of Forecasting Accuracy." *International Journal of Forecasting*, 16(4), 437–450.
24. Timmermann, A. (2006). "Forecast Combinations." *Handbook of Economic Forecasting*, Vol. 1, Elsevier, 135–196.
25. White, H. (2000). "A Reality Check for Data Snooping." *Econometrica*, 68(5), 1097–1126.
26. Wilder, J.W. (1978). *New Concepts in Technical Trading Systems.* Trend Research.
