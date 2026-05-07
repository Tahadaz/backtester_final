# Literature and Methodology

All key metrics and choices are cited so the deliverable survives supervisor review.

---

## Multiple Testing & Sharpe Haircut

**Harvey, Liu & Zhu (2016)** — *"…and the Cross-Section of Expected Returns"*, *Review of Financial Studies*.

Canonical t > 3 bar after data-mining correction for cross-sectional factor claims. We apply this as the Harvey-Liu expected-maximum-Sharpe formula used in the DSR denominator: the maximum expected Sharpe from N independent trials is:

```
E[SR_max(N)] = (1 - γ_euler) * Φ⁻¹(1 - 1/N) + γ_euler * Φ⁻¹(1 - 1/(N·e))
```

where γ_euler ≈ 0.5772 is the Euler-Mascheroni constant and Φ⁻¹ is the inverse standard normal.

**Application here**: `n_variants` parameter in `evaluate_signal()` is the number of variants tested for that stock × signal family; DSR corrects the headline Sharpe accordingly.

---

## Deflated / Probabilistic Sharpe

**Bailey & López de Prado (2014)** — *"The Deflated Sharpe Ratio"*, *Journal of Portfolio Management*.

**PSR (Probabilistic Sharpe Ratio)**: probability that the true Sharpe exceeds a benchmark SR\*, accounting for estimation error, skewness, and kurtosis of returns:

```
PSR(SR*) = Φ[ √(T-1) · (ŜR - SR*) / √(1 - γ₃·ŜR + (γ₄-1)/4 · ŜR²) ]
```

where ŜR is the estimated Sharpe, γ₃ / γ₄ are skewness / excess kurtosis of returns, T is the number of observations.

**DSR (Deflated Sharpe Ratio)**: PSR with SR\* = E[SR_max(N)] from Harvey-Liu. Accounts for multiple testing.

**Application here**: every `SignalEvaluationReport` includes PSR (at SR\*=0) and DSR (at SR\*=E[SR_max(n_variants)]).

---

## Information Coefficient

**Grinold & Kahn** — *Active Portfolio Management*, 2nd ed. (2000), Ch. 6.

IC = Spearman rank correlation of signal vs N-day forward return. Spearman is preferred over Pearson for heavy-tailed return distributions (MASI daily returns exhibit significant excess kurtosis).

IC decay curve: IC at horizons N ∈ {1, 2, 3, 5, 10}. Decay speed is evidence of signal quality — fast decay (IC collapses by horizon 3) suggests noise-driven persistence.

**Application here**: `rank_ic()` in `stats/ic.py`; IC CI via Fisher z-transform.

---

## FDR Control

**Benjamini & Hochberg (1995)** — *Journal of the Royal Statistical Society Series B*.

BH procedure controls the expected proportion of false discoveries at level q:
1. Sort p-values: p_(1) ≤ p_(2) ≤ … ≤ p_(m)
2. Find largest k such that p_(k) ≤ (k/m) · q
3. Reject all H₀₍ᵢ₎ for i ≤ k

Applied at q = 0.10 within each stock × horizon × signal-family cell.

**Application here**: `benjamini_hochberg()` in `stats/fdr.py`; any positive-IC result is FDR-flagged until it survives BH correction across the full test matrix.

---

## Autocorrelation-Robust Standard Errors

**Newey & West (1987)** — *Econometrica*.

Daily financial returns are autocorrelated. OLS standard errors are biased downward without a HAC correction. The Newey-West estimator:

```
Var_NW(x̄) = γ₀/T + (2/T) · Σ_{k=1}^{L} (1 - k/(L+1)) · γₖ
```

where γₖ = sample autocovariance at lag k, L = bandwidth (default: 4·(T/100)^(2/9)).

**Application here**: conditional-return t-statistic in `evaluate_signal()` uses NW SE via `_newey_west_var()` in `stats/ic.py`.

---

## Frontier / EM Integration

**Bekaert & Harvey (1995, 2002, 2003)**; **Pukthuanthong & Roll (2009)**.

MASI is a frontier market with partial integration to global risk factors. Integration is time-varying: higher during risk-off episodes (VIX spikes), lower during local idiosyncratic phases. This motivates the subsample stability check by VIX tercile in the robustness battery.

**Application here**: robustness report includes subsample breakdown by VIX tercile when VIX factor data is available.

---

## Regime Switching

**Hamilton (1989)**; **Ang & Bekaert (2002)**.

Cited as background for why static unconditional regression may miss regime-dependent factor exposures. Phase 0 uses a simplified VIX-tercile split rather than a full Hamilton regime model. Phase 2 (deferred) may revisit HMM approaches if Phase 0–1 evidence justifies it.

---

## Risk-On / Risk-Off Gating

**Ilmanen (2011)** — *Expected Returns*, Ch. 15.

VIX z-score and SP500 momentum are literature-backed risk-appetite proxies. The specific rules used in Phase 1 (VIX z20 < −1 → long; z20 > +2 → flat/short) are taken directly from Ilmanen's gating framework.

---

## Walk-Forward / Purged CV

**López de Prado (2018)** — *Advances in Financial ML*, Ch. 7, 8, 11.

Standard k-fold CV leaks information through label overlap (forward returns span multiple days). The existing WFO pipeline already implements walk-forward splits with embargo. The analytics harness reuses the same OOS windows — it never evaluates on in-sample data.

**Application here**: `evaluate_signal()` operates on the OOS portion of the signal series produced by the existing WFO pipeline. No additional purging is needed because the signal input is already OOS.

---

## Stationary Bootstrap CI

**Politis & Romano (1994)** — *Journal of the American Statistical Association*.

The stationary bootstrap resamples blocks of data with geometrically-distributed block lengths, preserving the time-series autocorrelation structure. Used to construct CI on Sharpe and IC that are robust to non-stationarity.

**Application here**: `stationary_bootstrap_ci()` in `stats/robustness.py`; parameter p = 1/expected_block_length (default: 1/20 for daily data).
