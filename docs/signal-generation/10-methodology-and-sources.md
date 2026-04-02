# 10 — Methodology & Academic Sources

---

## Design Choice Justifications

Every significant design choice in the signal engine has an academic or practitioner justification. This document maps each choice to its source.

---

### 1. Walk-Forward OOS Evaluation (Layer B)

**Choice**: Evaluate signals on rolling OOS windows where the model has never seen the test data.

**Why not simple train/test split?**
A single split is fragile — the split point determines the result. Walk-forward uses multiple windows, each providing an independent OOS evaluation.

**Why not cross-validation?**
Standard k-fold CV violates temporal order — future data leaks into training folds. Walk-forward respects chronology: every test window comes strictly after its training window.

**Sources**:
- Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies*. Wiley. — Chapter 7: "Walk-Forward Analysis"
- Bailey, D.H. & López de Prado, M. (2012). "The Sharpe Ratio Efficient Frontier." *Journal of Risk*. — Why single-split Sharpe is unreliable

---

### 2. Structured Candidate Universe (Layer A)

**Choice**: 30 fixed parameter points per family, chosen from practitioner conventions.

**Why not random search?**
Random search over parameter space maximizes the multiple testing problem. 1,000 random trials guarantee finding "significant" results by chance.

**Why not exhaustive grid search?**
Exhaustive search tests every integer (e.g., SMA-1 through SMA-500). Most of these are economically meaningless (SMA-1 is just price; SMA-500 is a 2-year average that barely moves).

**Why 30?**
Balances coverage against multiple testing cost. With 30 candidates and a 5% base rate, ~1.5 false positives expected. The viability gate (40% positive windows over ≥3 windows) is much stricter than 5%.

**Sources**:
- Harvey, C.R., Liu, Y., Zhu, H. (2016). "... and the Cross-Section of Expected Returns." *Review of Financial Studies*. — 316 published factors; most are false discoveries from extensive testing
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Ch. 8: "Feature Importance" — structured feature testing vs data-mining

---

### 3. Multi-Metric Reliability Score (Layer C)

**Choice**: Weighted composite of 4 components (Sharpe 35%, Stability 30%, Consistency 20%, Drawdown 15%) rather than ranking by Sharpe alone.

**Why not just Sharpe?**
A variant can have high mean Sharpe because it performed exceptionally in 1 of 5 windows (+3.0) and poorly in the rest (-0.5 each). Mean = 0.5, but this is not a reliable signal.

**Why these 4 components?**
They capture orthogonal aspects of signal quality:
- Sharpe: absolute return quality
- Stability: fraction of time it works
- Consistency: predictability of quality
- Drawdown: risk of catastrophic loss

**Why these weights?**
Return metrics (Sharpe + Stability = 65%) dominate because the primary question is "does this signal predict returns?" Risk metrics (Consistency + Drawdown = 35%) provide a safety check.

**Sources**:
- Bailey, D.H., Borwein, J.M., López de Prado, M., Zhu, Q.J. (2014). "Pseudo-Mathematics and Financial Charlatanism." *Notices of the AMS*. — Single-metric ranking leads to false discoveries
- White, H. (2000). "A Reality Check for Data Snooping." *Econometrica*. — Multiple testing correction via joint hypothesis testing

---

### 4. Redundancy Reduction via Correlation (Layer E)

**Choice**: Greedy selection by reliability, eliminating variants with |Pearson r| > 0.85 vs any selected representative.

**Why correlation-based?**
Two variants with r = 0.95 provide essentially the same information. Including both double-counts the signal, biasing the ensemble toward that particular pattern.

**Why greedy (not optimal)?**
Optimal subset selection (minimize total correlation while maximizing total reliability) is NP-hard. Greedy by reliability is efficient and produces good results in practice.

**Why 0.85 threshold?**
At r² = 0.72 (r = 0.85), two signals share 72% of variance. They are measuring the same underlying feature with minor noise differences.

**Sources**:
- López de Prado, M. (2020). *Machine Learning for Asset Managers*. Ch. 6: "Feature Importance" — remove features with high pairwise correlation before model fitting
- Dietterich, T. (2000). "Ensemble Methods in Machine Learning." *MCS 2000*. — Ensemble diversity is key to variance reduction

---

### 5. Reliability-Weighted Ensemble (Layer G)

**Choice**: Weighted average of representative signals, with reliability score as weight.

**Why not equal weights?**
A variant with reliability 0.72 has demonstrated stronger and more consistent OOS performance than one with 0.45. Equal weighting would give them the same influence, diluting the quality signal.

**Why not select the best?**
Selecting "the best" variant is a form of overfitting to the evaluation metric. Even with OOS evaluation, the best-performing variant in this particular data sample may not be the best going forward.

**Sources**:
- Breiman, L. (1996). "Bagging Predictors." *Machine Learning*. — Averaging reduces variance
- Dietterich, T. (2000). "Ensemble Methods in Machine Learning." — Why ensemble outperforms best individual
- López de Prado, M. (2018). Ch. 6 — Portfolio of strategies vs single best strategy

---

### 6. Transaction Cost Model

**Choice**: Proportional cost on position changes, default 10 bps per leg.

**Why proportional (not fixed)?**
Proportional costs scale with position size, matching real-world brokerage structures. Fixed costs would disproportionately penalize small trades.

**Why 10 bps default?**
Conservative estimate for Moroccan equities:
- Brokerage commission: ~5-15 bps (varies by broker/volume)
- Spread: ~5-20 bps (varies by liquidity)
- Market impact: negligible for retail sizes

10 bps per leg (20 bps round trip) is a reasonable middle estimate.

**Sources**:
- Chan, E. (2008). *Quantitative Trading*. Ch. 2: "The Cost of Trading" — realistic cost modeling is essential for backtesting validity

---

### 7. Indicator Selection

**Choice**: Decompose trend following into 4 orthogonal dimensions, each captured by a classical indicator family.

| Pillar | Family | What It Detects | Visual Encoding |
|--------|--------|----------------|-----------------|
| **Direction** | SMA | Is price trending up or down? | SMA curves on price chart |
| **Acceleration** | MACD | Is the trend strengthening or weakening? | Arrows at crossover points |
| **Exhaustion** | RSI | Has price stretched too far? | Overbought/oversold bands (0-100 axis) |
| **Confirmation** | OBV | Does volume confirm the move? | Colored volume bars |

**Why these four?**
Each captures a dimension the others cannot:
- SMA sees direction but not speed â€” MACD fills this gap
- SMA and MACD are trend-following â€” RSI provides mean-reversion counterbalance
- All three are price-based â€” OBV adds volume as an independent information source

This decomposition follows Elder's "Triple Screen" principle (Elder 1993): use indicators from different categories to avoid redundant confirmation.

> *"The first rule of using indicators is that you should never use two indicators from the same group. Combining two trend-following indicators... or two oscillators is redundant â€” they just confirm each other's blind spots."* â€” Alexander Elder (1993), *Trading for a Living*

| Family | Category | Justification |
|--------|----------|---------------|
| SMA | Trend | The simplest and most robust trend indicator. Price > MA indicates uptrend. Used by practitioners for decades (Murphy 1999). |
| MACD | Momentum | Captures trend acceleration via short/long EMA difference. More responsive than SMA to momentum changes (Appel 2005). |
| RSI | Oscillator | Measures relative strength of recent gains vs losses. Captures mean-reversion at extremes (Wilder 1978). |
| OBV | Volume | Accumulates volume directionally. Provides independent (non-price) confirmation of trends (Granville 1963). |

**Why not more families?**
Each additional family adds 30 candidates to the multiple testing burden. We start with 4 well-established families and will add more only if there is clear economic justification.

**Planned additions** (not yet implemented):
- Bollinger Bands — volatility-based mean-reversion
- Ichimoku — Japanese cloud-based trend/support/resistance
- Stochastic VWAP — volume-weighted price oscillator

---

### 8. Horizon-Aware Parameter Scaling

**Choice**: Different parameter grids for short/medium/long horizons.

**Why?**
A 5-day SMA is appropriate for a short-term trader but meaningless for a long-term investor. Conversely, a 400-day SMA captures multi-year trends but is too slow for short-term signals.

The train/test window sizes also scale with horizon:
- Short: 252/63 bars (1 year train, 3 months test)
- Medium: 504/126 bars (2 years train, 6 months test)
- Long: 756/252 bars (3 years train, 1 year test)

**Sources**:
- Murphy (1999) — Different timeframes require different indicator settings
- Pardo (2008) — Walk-forward window size should match the intended holding period

---

## Honest Limitations

### What This Engine Cannot Do (Yet)

1. **Deflated Sharpe Ratio** — We do not adjust the Sharpe ratio for the number of trials tested. This means our reported Sharpe is upward-biased. Bailey & López de Prado (2012) provide a correction formula; implementation is planned.

2. **Combinatorially Purged Cross-Validation (CPCV)** — Our walk-forward windows are sequential, not combinatorial. CPCV (López de Prado 2018, Ch. 12) would provide more evaluation points with less data leakage.

3. **Feature Importance** — We treat all 4 families as equal categories. Mean Decrease Accuracy or SHAP values could identify which families genuinely contribute vs add noise.

4. **Regime Detection** — The engine doesn't distinguish between trending and ranging markets. A trend indicator in a ranging market will perform poorly; the engine reports this via low stability but doesn't adapt.

5. **Non-Linear Signals** — All 4 indicators are linear transformations. Non-linear interactions (e.g., RSI extreme + volume spike) are not captured.

6. **Correlation with External Factors** — We don't test whether our signals are explained by well-known risk factors (market, size, value). Some of our "alpha" may be factor exposure.

### What Could Go Wrong

- **Survivorship bias in data**: If our OHLCV data excludes delisted stocks, our signals are biased toward survivors
- **Non-stationarity**: Market microstructure changes over time; signals calibrated on old regimes may not work on new ones
- **Liquidity**: Our cost model assumes constant costs; in practice, illiquid Moroccan stocks may have much higher effective costs
- **Currency effects**: For non-MAD denominated analysis, currency risk adds noise

We are transparent about these limitations because honest methodology is more valuable than false confidence.

---

## Sensitivity Analysis Tool

**Script**: `scripts/signal_engine_sensitivity.py`

A standalone CLI tool that validates the pipeline's threshold stability. This is how we answer the question: "if we change a threshold by 20%, does the output change dramatically?"

### How It Works

```
1. Load OHLCV data (CSV or Excel)
2. Run baseline: full A→G pipeline for all 4 families with default ThresholdSet
3. For each threshold parameter:
   a. Perturb by -20%, run full pipeline, compute Δscore per family
   b. Perturb by +20%, run full pipeline, compute Δscore per family
   c. Classify max Δ as STABLE (<5), MODERATE (5-15), or SENSITIVE (≥15)
4. Print structured report
```

### ThresholdSet

All tuneable parameters in one frozen dataclass:

| Parameter | Default | What It Controls |
|-----------|---------|-----------------|
| `min_fraction_positive` | 0.40 | Viability gate (Layer C) |
| `min_competitive_score` | 0.25 | Absolute floor (Layer D) |
| `competitive_percentile` | 0.40 | Fraction eliminated (Layer D) |
| `max_corr` | 0.85 | Redundancy threshold (Layer E) |
| `cost_bps` | 33.0 | Transaction cost (Layer B) |

### Interpretation

- **STABLE**: Changing the threshold by 20% moves the score by less than 5 points. The pipeline's conclusion (buy/sell/neutral) is the same regardless. This is the desired outcome.
- **MODERATE**: Score moves 5–15 points. The direction might change (e.g., "Achat" → "Neutre"). The threshold matters but the current value is reasonable.
- **SENSITIVE**: Score moves ≥15 points. The pipeline is fragile with respect to this parameter. Either the threshold needs better calibration or the signal is genuinely weak for this symbol/horizon.

### Usage

```bash
# Default: IAM.xlsx, short horizon, 33 bps cost
python scripts/signal_engine_sensitivity.py

# Custom data and parameters
python scripts/signal_engine_sensitivity.py --csv data/BCP.xlsx --horizon medium --cost-bps 20 --lookback-years 10
```

---

## Test Coverage

**Files**: `core/tests/test_signal_engine.py` (548 lines, 15 test classes), `core/tests/test_variant_detail_trade_register.py` (174 lines, 5 tests)

The test suite validates every layer of the pipeline using **synthetic data** (no DB, S3, or API required):

### Layer-by-Layer Tests

| Test Class | Layer | What It Validates |
|------------|-------|-------------------|
| `TestCandidates` | A | 30 candidates per (family, horizon), unique IDs, deterministic generation |
| `TestSignalContract` | B | Signal length = close length, values ∈ {-1, 0, +1}, warmup bars = 0.0 |
| `TestOOSEval` | B | ≥3 valid windows on 1500-bar uptrend, no train/test overlap, no look-ahead bias |
| `TestRobustnessAndFiltering` | C+D | Reliability score ∈ [0, 1], viability gate enforced, survivors exclude non-viable |
| `TestRedundancyAndEnsemble` | E+G | Identical signals collapse to 1, score range [-100, +100], family-specific labels |
| `TestOOSReturnMetrics` | B | total_return, cagr, pnl fields present and consistent (pnl = 100K × total_return) |
| `TestMultiFamilyCandidates` | A | RSI, MACD, OBV: 30 candidates each, unique IDs, deterministic |
| `TestMultiFamilySignalContract` | B | All families: signal contract enforced, OBV uses volume, RSI respects oversold/overbought |
| `TestMultiFamilyEnsemble` | A→G | End-to-end pipeline for each family on synthetic data |
| `TestHorizonMaxYears` | Config | max_years present, max_bars > min_bars, engine truncates long data correctly |
| `TestCooldown` | B | cooldown=0 = no-op, cooldown suppresses flips, returns copy, reduces trade count |
| `TestCostModel` | B | Position-change basis: no double-cost on repeated signals, full-reversal = 2× cost |
| `TestSignalTypeLabels` | Domain | All label functions: trend, oscillator, volume, aggregate, variant-level |

### No-Look-Ahead Verification

The `test_oos_no_future_data` test verifies causality:
```python
# Compute signal on close[:t+1] (partial data up to bar t)
# Verify it matches full-array signal at bar t
# If they differ, the indicator uses future data — test FAILS
```

This is run at bars 15, 50, 100, 150, 190 — covering warmup, middle, and near-end of the series.

### Trade Register Tests

| Test | What It Validates |
|------|-------------------|
| `test_trade_register_execution_on_next_open` | Signal at bar t → execution at bar t+1 open |
| `test_position_holding` | Open position held until close signal; cash tracks correctly |
| `test_position_flip` | Long→Short: realizes long P&L, opens short at new CMP |
| `test_short_trading` | Short positions: cash received on open, paid on close |
| `test_trade_performance_summary` | Win rate, profit factor computed from realized P&L only |

---

## Full Bibliography

| Author(s) | Year | Title | Use in Engine |
|-----------|------|-------|---------------|
| Appel, G. | 2005 | *Technical Analysis: Power Tools for Active Investors* | MACD indicator design |
| Bailey, D.H. & López de Prado, M. | 2012 | "The Sharpe Ratio Efficient Frontier" | Sharpe reliability concerns |
| Bailey, D.H. et al. | 2014 | "Pseudo-Mathematics and Financial Charlatanism" | Multiple testing awareness |
| Blume, L., Easley, D., O'Hara, M. | 1994 | "Market Statistics and Technical Analysis" | Volume as information |
| Breiman, L. | 1996 | "Bagging Predictors" | Ensemble averaging |
| Chan, E. | 2008 | *Quantitative Trading* | Transaction cost model |
| Dietterich, T. | 2000 | "Ensemble Methods in Machine Learning" | Ensemble diversity |
| Elder, A. | 1993 | *Trading for a Living* | Indicator classification |
| Granville, J. | 1963 | *Granville's New Key to Stock Market Profits* | OBV indicator |
| Harvey, C.R. et al. | 2016 | "... and the Cross-Section of Expected Returns" | Multiple testing in finance |
| Jegadeesh, N. & Titman, S. | 1993 | "Returns to Buying Winners and Selling Losers" | Momentum as economic phenomenon |
| López de Prado, M. | 2018 | *Advances in Financial Machine Learning* | Signal station concept, OOS methods |
| López de Prado, M. | 2020 | *Machine Learning for Asset Managers* | Feature importance, redundancy |
| Markowitz, H. | 1952 | "Portfolio Selection" | Diversification principle |
| Murphy, J.J. | 1999 | *Technical Analysis of the Financial Markets* | Indicator taxonomy, SMA |
| Pardo, R. | 2008 | *The Evaluation and Optimization of Trading Strategies* | Walk-forward analysis |
| Poterba, J. & Summers, L. | 1988 | "Mean Reversion in Stock Prices" | Mean-reversion evidence |
| White, H. | 2000 | "A Reality Check for Data Snooping" | Bootstrap multiple testing |
| Wilder, J.W. | 1978 | *New Concepts in Technical Trading Systems* | RSI indicator |
