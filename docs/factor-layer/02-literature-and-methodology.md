# Literature and Methodology

All key metrics and choices are cited so the deliverable survives supervisor review.

---

## Multiple Testing and Sharpe Haircut

**Harvey, Liu and Zhu (2016)**, "and the Cross-Section of Expected Returns", *Review of Financial Studies*.

Canonical factor claims need a higher bar after data-mining correction. The platform uses the Harvey-Liu expected-maximum-Sharpe idea inside the DSR denominator: the maximum expected Sharpe from `N` independent trials rises with the size of the search space.

Application:
- `n_variants` in signal evaluation is the number of variants tested for that stock, horizon, and signal family.
- Factor x TA has its own trial universe and must not be evaluated as if only one hand-picked rule was tried.

---

## Deflated and Probabilistic Sharpe

**Bailey and Lopez de Prado (2014)**, "The Deflated Sharpe Ratio", *Journal of Portfolio Management*.

PSR estimates the probability that the true Sharpe exceeds a benchmark after accounting for sample size, skewness, and kurtosis. DSR uses a multiple-testing-adjusted benchmark Sharpe.

Application:
- Native TA and Factor x TA comparisons must report multiple-testing-aware performance.
- A high raw Sharpe is not enough if it does not survive the registered search-space correction.

---

## Information Coefficient

**Grinold and Kahn (2000)**, *Active Portfolio Management*, 2nd ed., Ch. 6.

IC is the rank correlation between a signal and forward returns. Spearman IC is preferred for MASI daily returns because rank correlation is less fragile under heavy tails.

Application:
- Factor selection uses horizon-aware IC diagnostics.
- Selected macro factors are stored per stock and selection horizon before Factor x TA variants are generated.

---

## FDR Control

**Benjamini and Hochberg (1995)**, *Journal of the Royal Statistical Society Series B*.

BH-FDR controls the expected proportion of false discoveries among rejected hypotheses.

Application:
- FDR is applied inside the registered stock/horizon/factor search.
- Native TA and Factor x TA claims should be interpreted as separate, documented universes rather than a post-hoc mixed pool.

---

## Autocorrelation-Robust Standard Errors

**Newey and West (1987)**, *Econometrica*.

Daily financial returns are autocorrelated, so naive standard errors are too optimistic. Newey-West HAC standard errors reduce this bias.

Application:
- Factor IC t-statistics and conditional-return diagnostics use HAC-style inference.

---

## Frontier and EM Integration

**Bekaert and Harvey (1995, 2002, 2003)**; **Pukthuanthong and Roll (2009)**.

MASI is a frontier market with partial and time-varying integration to global risk factors. This motivates macro variables such as VIX, SP500, DXY, EURUSD, Brent, and US10Y as candidate state variables.

Application:
- Channel tags encode economically plausible exposure paths.
- No factor is assumed useful for every stock; empty selected sets are valid outcomes.

---

## Regime Switching

**Hamilton (1989)**; **Ang and Bekaert (2002)**.

These papers explain why static unconditional regressions can miss regime-dependent exposures. The implemented Factor x TA runtime uses explicit pre-registered gates, not an HMM. HMM-style regime switching remains future research if simpler gates justify the added complexity.

---

## Risk-On / Risk-Off Gating

**Ilmanen (2011)**, *Expected Returns*, Ch. 15.

VIX z-scores and SP500 momentum are risk-appetite proxies. Factor x TA uses these as gates on existing TA signals, with date alignment handled before condition evaluation.

Application:
- `VIX z20 < -1` and `VIX z20 > +2` are pre-registered factor conditions.
- The factor gate controls when a TA signal may fire; it does not become an independent trading system inside Factor x TA.

---

## Walk-Forward and Purged CV

**Lopez de Prado (2018)**, *Advances in Financial ML*, Ch. 7, 8, 11.

Standard k-fold CV leaks information when labels overlap. The existing WFO pipeline uses walk-forward splits and the Factor x TA WFO path evaluates precomputed AND-composed signals inside the same framework.

Application:
- WFO Factor x TA persists fold diagnostics in `wfo_signal_summary.folds_json`.
- Signal backtest/MC replay consumes persisted representatives and rebuilds the same factor-gated signal.

---

## Stationary Bootstrap CI

**Politis and Romano (1994)**, *Journal of the American Statistical Association*.

The stationary bootstrap preserves time-series autocorrelation by resampling variable-length blocks.

Application:
- Incremental claims should compare Factor x TA against the native TA baseline with bootstrap confidence intervals, not only point estimates.
