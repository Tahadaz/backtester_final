# Methodology & Research Sources

## Phase 1 Overview

Phase 1 evaluates six pre-registered macroeconomic factor signals on Moroccan-listed equities. The research question is: **Do pure factor-based trading rules generate positive risk-adjusted returns above transaction costs, after multiple-testing adjustment?**

## Research Question & Null Hypothesis

**Null Hypothesis (H₀)**: The six factor rules have zero conditional alpha after costs and multiple-testing correction.

**Alternative Hypothesis (H₁)**: At least one signal exhibits a significant positive Sharpe ratio (DSR > 0, PSR > 0) and passes FDR filtering at q=0.10.

## Methodology Summary

### Data & Universe
- **Stock universe**: 8 seed symbols (ATW, BCP, BMCE, IAM, CDM, ADDH, COSU, WAA) with auto-expansion to all MASI stocks satisfying min_bars=252 and min_price_mad=5.0.
- **Macro factors**: 6 series (VIX, DXY, BRENT, SP500, US10Y, EURUSD) daily-frequency or better.
- **Time span**: Full available history per stock (typically 5–15 years).

### Evaluation Framework
- **Signal pipeline**: Each factor rule → {-1, 0, +1} output aligned to stock returns via `align_factor_to_target(lag_rule="precede_open", max_staleness=3)`.
- **Statistical battery**: IC (Spearman, with Newey-West t-stat), hit rate (Wilson CI), conditional-return t-stat, Sharpe, Sortino, MaxDD, DSR, PSR, bootstrap CI.
- **Risk adjustment**: PnL computed after spread (0 bps), commission (33 bps per action = 66 bps round-trip), and position turnover.

### Multiple-Testing Correction
- **Method**: Benjamini-Hochberg FDR at q=0.10 across all (signal, stock, horizon) conditional-return p-values.
- **Rationale**: Controls false-discovery rate (proportion of false positives among rejections) rather than family-wise error rate, balancing discovery power with Type I risk.

### Integrity Protocol
- **Pre-registration**: All rule specs, parameters, and costs frozen in `docs/research/phase1_pre_registration.yaml` with git commit timestamp before any evaluation.
- **No post-hoc tuning**: Rule thresholds, windows, universe members, and costs are locked. Divergence requires a new pre-registration.
- **Null reporting**: Signals that fail FDR or show negative Sharpe are documented as honest nulls, not hidden.

## Sources

### Academic References

| Signal | Citation | Key Insight |
|--------|----------|------------|
| VIX z-score | Ilmanen (2011), Ch. 15 | Volatility mean-reversion; risk-on/off gate |
| DXY momentum | Hau & Rey (2006) | Dollar weakness → EM tailwind; carry channel |
| Brent direction | (channel-only) | Commodity prices → input costs for materials/mining |
| SP500 + VIX confirmation | Ilmanen (2011), Ch. 15 | Dual validation: momentum + low volatility |
| US10Y shock | Campbell & Shiller (1988) | Yield moves → duration shocks for rate-sensitive sectors |
| EURUSD momentum | (regional peg context) | MAD peg anchors: EUR 60%, USD 40% |

### Data Sources
- **Equity OHLCV**: Parquet store (`{symbol}.parquet` in configured data path).
- **Macro factors**: Time series via macro ingestion pipeline (`POST /analytics/macro/ingest-all`).
- **Sector mapping**: `StockMaster.sector` for channel-filter validation.

## Evaluation Outputs

### Per-Signal, Per-Stock Metrics

For each (signal, stock) pair, we compute:

- **IC (Information Coefficient)**: Spearman rank correlation between signal and forward returns.
- **IC decay**: IC stability across rolling 63-day windows.
- **Hit rate**: Fraction of non-zero signal days with same-sign forward return (Wilson CI).
- **Conditional return t-stat**: Newey-West t-stat on the cross-sectional mean return conditioned on signal value.
- **Sharpe ratio (gross)**: √252 × mean(return) / std(return).
- **Sharpe ratio (net)**: Sharpe after subtracting 33 bps per position change (Moroccan market costs).
- **Sortino**: Like Sharpe but penalizing downside volatility only.
- **Max DD, Calmar ratio**: Peak-to-trough and return / max DD.
- **DSR (Deflated Sharpe Ratio)**: Adjusted for historical backtest overfitting (Harvey et al. 2016).
- **PSR (Probabilistic Sharpe Ratio)**: Bayesian posterior probability that Sharpe > 0.
- **Bootstrap CI**: 500-sample block bootstrap on Sharpe (90% confidence interval).

### FDR Filtering

Signals are ranked by conditional-return p-value across all (signal, stock, horizon) triples. Benjamini-Hochberg FDR control at q=0.10 determines the rejection threshold. Signals below the threshold are marked `fdr_pass=true`; others are `fdr_pass=false`.

### Channel-Filter Application

Signals with non-empty `channel_filter` are marked `applicable=false` for stocks outside the channel. Their metrics are zeroed in the output, and the frontend renders them muted/strikethrough so the operator sees the logic was correctly applied.

## Horizon Analysis

Evaluation is performed at five horizons (h ∈ {1, 2, 3, 5, 10} days forward). This captures both intraday/day-trading interpretations and medium-term mean-reversion patterns. Results are reported per horizon and aggregated for phase-level conclusions.

## Out of Scope (Phase 2+)

- **Live trading integration**: Phase 1 is research-panel-only; operational wiring is Phase 2.
- **Conditional composition**: Combining factor signals with TA signals is Phase 2 and requires separate pre-registration.
- **Regime models**: HMM or Bayesian regime switching deferred.
- **Optimization**: Portfolio weighting, horizon selection, and rebalancing frequency are Phase 2 activities.

## References

- Campbell, J. Y. & Shiller, R. J. (1988). "Stock Prices, Earnings, and Expected Dividends." *Journal of Finance*, 43(3), 661–676.
- Hau, H. & Rey, H. (2006). "Exchange Rates, Equity Prices, and Capital Flows." *Journal of Finance*, 61(1), 271–302.
- Ilmanen, A. (2011). *Expected Returns: An Investor's Guide to Harvesting Market Rewards*. Wiley.
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). "...and the Cross-Section of Expected Returns." *Review of Financial Studies*, 29(1), 5–68.
