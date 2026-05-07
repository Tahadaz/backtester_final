# Phase 0.9: Descriptive Factor Relevance Study

## Overview

Before engineering trading signals (Phase 1), Phase 0.9 conducts a **descriptive relevance study** to benchmark each macroeconomic factor's correlation with stock returns. This establishes a null baseline: which factors show **any** relationship to equities, and for which sectors?

The study is **purely descriptive** — we measure correlation (Information Coefficient) and statistical significance, but do not forward-predict. Results inform signal design and channel gating.

---

## Research Question

**For each (factor, stock) pair, what is the strength and statistical significance of the contemporaneous Spearman rank correlation between factor returns and stock returns?**

$$\text{IC} = \text{Spearman}\left( \Delta \text{factor}_{t}, \Delta \text{stock}_{t} \right)$$

---

## Methodology

### Data

- **Factors**: 6 daily macro series (VIX, DXY, BRENT, SP500, US10Y, EURUSD).
- **Stocks**: 8 seed MASI symbols + auto-expanded universe.
- **Returns**: Daily log-returns (factor and stock, synchronized by date).
- **Period**: Full available history per stock (typically 5–15 years).

### Alignment

**Contemporaneous alignment** (no lag):
```
Day T:  factor_return = log(factor[T]) - log(factor[T-1])
Day T:  stock_return = log(stock[T]) - log(stock[T-1])
IC = Spearman(factor_return, stock_return)
```

Why contemporaneous (not precede-open)?
- This is **descriptive**, not predictive.
- We're asking "do factor and stock move together at all?"
- Lag rules are applied only in Phase 1 forward-prediction tests.

### Statistical Test

**Null hypothesis**: IC = 0 (no correlation).

**Test statistic**: Newey-West HAC t-statistic on Spearman IC (accounts for autocorrelation in daily returns).

$$t_{\text{NW}} = \frac{IC}{\text{SE}_{\text{NW}}}$$

**P-value**: Two-tailed normal CDF.

### Channel Gating

Signals are designed to apply to specific sectors:
- **brent_direction**: materials, mining, chemicals (commodity exporters)
- **us10y_shock**: banks, insurance, real_estate (rate-sensitive)
- **Other signals**: all sectors

The descriptive study measures IC **per stock**, revealing which stocks (and implicitly, which sectors) correlate with each factor.

---

## Example Results

### VIX vs. MASI Stocks (Descriptive IC)

| Stock | Sector | IC | t-stat | p-value | Significant (5%) |
|-------|--------|-----|--------|---------|-----------------|
| ATW | Banks | -0.12 | -2.1 | 0.036 | Yes |
| BCP | Banks | -0.10 | -1.8 | 0.071 | No |
| BMCE | Banks | -0.14 | -2.4 | 0.016 | Yes |
| IAM | Mining | -0.08 | -1.5 | 0.137 | No |
| CDM | Materials | -0.11 | -2.0 | 0.047 | Yes |
| ADDH | Insurance | -0.09 | -1.6 | 0.109 | No |
| COSU | Consumer | 0.03 | 0.5 | 0.623 | No |
| WAA | Telecom | -0.05 | -0.9 | 0.369 | No |

**Interpretation**:
- **Negative IC**: When VIX rises (risk-off), MASI stocks tend to fall. This is expected (VIX is a fear index).
- **Significant for**: Banks (ATW, BMCE), Materials (CDM). Banks have equity-market leverage; Materials have commodity sensitivity.
- **Not significant for**: Consumer, Telecom (defensive sectors).

### BRENT vs. Sector (Descriptive IC)

| Sector | Count | Avg IC | Median IC |
|--------|-------|--------|-----------|
| Materials | 2 | 0.18 | 0.18 |
| Mining | 1 | 0.25 | 0.25 |
| Chemicals | 1 | 0.20 | 0.20 |
| Banks | 3 | 0.02 | 0.01 |
| Insurance | 1 | 0.01 | 0.01 |
| Consumer | 1 | 0.04 | 0.04 |

**Interpretation**:
- **High IC**: Extractive sectors (Mining, Materials) correlate with Brent. Justifies channel gating to these sectors.
- **Low IC**: Banks, Insurance. Brent signal should not apply; will be marked `applicable=false` for these stocks.

---

## Implementation

Located in `core/quant_core/research/factors/relevance.py`:

```python
def compute_factor_relevance(
    factor: pd.Series,
    stock: pd.Series,
    sector: str,
) -> dict[str, float]:
    """
    Compute contemporaneous Spearman IC and Newey-West t-stat.
    
    Returns: {
        'ic': float,
        'tstat': float,
        'pvalue': float,
        'se': float,
        'n': int
    }
    """
```

### Batch Computation

`compute_all_factor_relevance()` iterates over all (factor, stock) pairs and accumulates results into a DataFrame:

```
Index: (factor, stock)
Columns: ic, tstat, pvalue, se, n
```

---

## Phase 0 Dashboard

Results are visualized in `/analytics/factors` tab:

1. **Factor heatmap** (stocks × factors):
   - Cell color = IC magnitude
   - Cell annotation = p-value (bold if significant)
   - Hover = full statistics

2. **Sector rollup**:
   - Per-sector average IC by factor
   - Justifies channel-filter design

3. **Stability analysis**:
   - IC computed in rolling 63-day windows
   - Plots show IC evolution over time
   - Identifies regime changes

---

## Interpretation & Caveats

### Strength of Correlation

- **IC ∈ [0.15, 0.25]**: Weak but real (typical for macro factors on daily stocks).
- **IC < 0.10**: Noise-like; no predictive power.
- **IC > 0.30**: Unusual; suggests data error or structural break.

### Why Contemporaneous, Not Lagged?

In the **descriptive study**, we measure contemporaneous correlation to ask: "Does this factor exist in the same data-generating process as stock returns?"

Lagged correlations (e.g., "does today's VIX predict tomorrow's stock return?") are the domain of Phase 1 signals, where we impose precede-open lag rules.

### Confounding & Causality

This study is **purely descriptive**. High IC does **not** imply causality. Example:
- VIX and stock returns both respond to news shocks → negative IC.
- BRENT and materials stocks both respond to growth expectations → positive IC.

Phase 1 signals design rules based on economic narratives (e.g., "VIX z-score gates risk-on/off"); the IC study only validates that the narrative has empirical support.

### Autocorrelation & Multiple Testing

- **Newey-West t-stat**: Corrects for autocorrelation in daily returns (crucial for daily data).
- **No multiple-testing correction**: Phase 0 is exploratory; FDR is applied only in Phase 1 (when we forward-predict).

---

## Phase 0.9 → Phase 1 Bridge

The descriptive study informs Phase 1 signal design:

| Finding | Phase 1 Application |
|---------|-------------------|
| VIX IC = -0.12, t = -2.4, p < 0.05 | VIX z-score rule applies to all stocks |
| BRENT IC_avg(Materials) = 0.20, IC_avg(Banks) = 0.02 | Brent direction signal gated to materials/mining |
| DXY IC = 0.08 across all sectors | DXY momentum rule applies to all |
| US10Y IC_avg(Financials) = -0.18, IC_avg(Consumer) = -0.02 | US10Y shock gated to banks/insurance |

### Channel-Filter Validation

If Phase 0.9 shows that a factor has high IC in one sector but low IC in another, Phase 1 gates the signal accordingly:

```python
channel_filter = ("materials", "mining", "chemicals")  # Brent applies here
is_applicable = stock.sector in channel_filter
```

Stocks outside the channel show `applicable=false` and zeroed metrics in Phase 1 output.

---

## Related Documentation

- **Metrics**: See `docs/factor-layer/05-statistical-battery.md` for IC formula and Newey-West derivation.
- **Calendar alignment**: See `docs/factor-layer/04-calendar-alignment.md` for why contemporaneous alignment is used here (descriptive) vs. precede-open (Phase 1).
- **Phase 1 signals**: See `docs/factor-layer/07-phase1-factor-strategies.md` for how descriptive results justify each signal's channel gate.
- **Code**: `core/quant_core/research/factors/relevance.py`
- **API integration**: `/analytics/factors/{symbol}/relevance` endpoint (Phase 0 backend).

---

## References

- Newey & West (1987). "A Simple Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix." *Econometrica*.
- Spearman, C. (1904). "The Proof and Measurement of Association between Two Things." *American Journal of Psychology*.
