# Methodology and Sources

## Academic References

### Spearman Rank Correlation (Information Coefficient)

**Grinold, R. C. & Kahn, R. N. (2000).** *Active Portfolio Management*, 2nd ed. McGraw-Hill.
- Chapter 6 defines the Information Coefficient (IC) as the rank correlation between signal forecasts and realized returns. Establishes IC = 0.05 as a practical threshold for meaningful predictive ability.
- The IC × Breadth = IR relationship (fundamental law of active management) is derived here.

---

### Newey-West HAC Standard Errors

**Newey, W. K. & West, K. D. (1987).** "A Simple Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix." *Econometrica*, 55(3), 703–708.
- Introduces the HAC variance estimator used for the IC t-statistic. Essential when forward return windows overlap (e.g. 10-day returns computed daily have 9-day overlap → autocorrelation in the IC series).

**Andrews, D. W. K. (1991).** "Heteroskedasticity and Autocorrelation Consistent Covariance Matrix Estimation." *Econometrica*, 59(3), 817–858.
- Data-driven bandwidth selection rule used in the implementation: $L = \lfloor 4 \cdot (T/100)^{2/9} \rfloor$. The bandwidth in this codebase is `max(h, Andrews_rule)`, ensuring at least `h` lags for a horizon-`h` return.

---

### Wilson Score Confidence Interval (Hit Rate)

**Wilson, E. B. (1927).** "Probable Inference, the Law of Succession, and Statistical Inference." *Journal of the American Statistical Association*, 22(158), 209–212.
- Original derivation of the score interval for binomial proportions. More accurate than normal approximation for small N or extreme proportions.

**Online explainer**: https://www.econometrics.blog/post/the-wilson-confidence-interval-for-a-proportion/
- Clear derivation and comparison with Clopper-Pearson and normal approximation. Shows why Wilson is preferred for small samples.

**Implementation**: `core/quant_core/research/stats/hit_rate.py` — `wilson_ci(k, n, alpha=0.05)`

---

### Stationary Bootstrap Confidence Interval (Mean Forward Return)

**Politis, D. N. & Romano, J. P. (1994).** "The Stationary Bootstrap." *Journal of the American Statistical Association*, 89(428), 1303–1313.
- Introduces the block bootstrap where block lengths are geometrically distributed (ensuring stationarity of the bootstrap distribution). Preferred over fixed-block bootstrap for financial time series where autocorrelation length is unknown.
- Used here to compute 95% CI on bucket-level mean forward returns. Block prob = 0.05 → expected block length = 20 bars.

**Implementation**: `core/quant_core/research/stats/robustness.py` — `stationary_bootstrap_ci()`

---

### Deflated Sharpe Ratio and Probabilistic Sharpe Ratio

**Bailey, D. H. & López de Prado, M. (2014).** "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality." *Journal of Portfolio Management*, 40(5), 94–107.
- DSR and PSR are used in the backtest layer and factor evaluation (not the TA analytics page directly). Cross-referenced here for completeness.

---

### Multiple Testing Correction

**Benjamini, Y. & Hochberg, Y. (1995).** "Controlling the False Discovery Rate: A Practical and Powerful Approach to Multiple Testing." *Journal of the Royal Statistical Society, Series B*, 57(1), 289–300.
- BH-FDR correction at q = 0.10 applied in the factor layer evaluation. Not directly used in the TA analytics page.

**Harvey, C. R., Liu, Y. & Zhu, H. (2016).** "…and the Cross-Section of Expected Returns." *Review of Financial Studies*, 29(1), 5–68.
- Expected maximum Sharpe ratio under multiple testing. Motivates skepticism of high observed IC for signals with many evaluated variants.

---

## Recommended Reading

For a deeper understanding of the methodology underlying this analytics page:

**López de Prado, M. (2018).** *Advances in Financial Machine Learning*. Wiley.
- Chapter 3 (labeling): forward return construction, fixed-horizon vs. triple-barrier.
- Chapter 8 (feature importance): why IC matters more than hit rate.
- Chapter 11 (backtest statistics): combinatorial purged cross-validation, why overlapping windows need HAC correction.

**Aronson, D. R. (2007).** *Evidence-Based Technical Analysis*. Wiley.
- Rigorous statistical treatment of TA signal evaluation. Covers bootstrap hypothesis testing, data snooping bias (why you need to correct for the number of signals tested), and why naive backtests lie.
- Directly relevant to interpreting the bucket matrix: Chapter 6 explains why hit rates near 50% are expected by chance and how bootstrap tests correct for this.

**Chan, E. P. (2013).** *Algorithmic Trading: Winning Strategies and Their Rationale*. Wiley.
- Practical guide to TA signal evaluation. Chapters on signal IC, position sizing from IC (Kelly criterion), and why a 40% hit rate with a 2:1 win/loss ratio beats a 60% hit rate with a 1:1 ratio.

---

## Implementation File Map

| Concept | File | Function |
|---|---|---|
| Spearman IC | `core/quant_core/research/stats/ic.py` | `_spearman_corr()` |
| Newey-West HAC variance | `core/quant_core/research/stats/ic.py` | `_newey_west_var()` |
| IC table (all horizons) | `core/quant_core/research/score_history.py` | `ic_table()` |
| Wilson CI | `core/quant_core/research/stats/hit_rate.py` | `wilson_ci()` |
| Stationary bootstrap CI | `core/quant_core/research/stats/robustness.py` | `stationary_bootstrap_ci()` |
| Bucket classification | `core/quant_core/research/score_history.py` | `_bucket_for()` |
| Bucketed forward returns | `core/quant_core/research/score_history.py` | `bucketed_forward_returns()` |
| Category aggregation | `core/quant_core/research/score_history.py` | `aggregate_subset()` |
| Monotonicity score Δ | `services/api/app/routers/analytics.py` | `get_category_combinations()` |
| Per-stock matrix endpoint | `services/api/app/routers/analytics.py` | `get_predictive_ability()` |
| Leaderboard endpoint | `services/api/app/routers/analytics.py` | `get_predictive_ability_leaderboard()` |
| Score history population | `core/quant_core/research/score_history.py` | `build_engine_category_series()`, `build_wfo_category_series()` |
