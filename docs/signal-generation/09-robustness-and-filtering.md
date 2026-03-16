# Signal Generation — Robustness Scoring & Filtering

**Reference:** `docs/strategy_signal_generation_plan.md` (Layers C, D, E)
**Planned implementation:** `core/quant_core/signal_engine/robustness.py`, `survivor.py`, `redundancy.py`

After OOS evaluation, the station must answer: *which signals are genuinely robust, which are noise, and which are redundant copies of each other?* This document describes the three-stage filtering pipeline that transforms raw OOS results into a small, representative subset of trustworthy signals.

---

## The Problem: Too Many "Good" Candidates

Even with a well-designed candidate universe (8–12 per family × horizon) and honest OOS evaluation, you may find 6 out of 12 candidates with positive OOS Sharpe. Should you use all 6?

No. Several issues remain:

1. **Statistical noise:** A positive mean OOS Sharpe from 8 folds could still be noise if the variance is high (e.g., mean = 0.3, std = 1.2 → not reliably positive)
2. **Marginal viability:** A candidate with Sharpe = 0.05 and 45% positive folds is technically "positive" but economically meaningless
3. **Redundancy:** SMA-20 and SMA-25 may both survive OOS filtering, but their signal series are >95% correlated — keeping both adds noise to the ensemble without adding information

The filtering pipeline addresses these three issues in sequence.

---

## Stage 1: Robustness Scoring (Layer C)

### Reliability Score

Each candidate receives a **reliability score** ∈ [0, 1] based on four OOS quality dimensions:

```
reliability_score = w₁ · sharpe_score + w₂ · stability_score + w₃ · consistency_score + w₄ · drawdown_score
```

| Component | Formula | Weight | What it measures |
|-----------|---------|--------|-----------------|
| `sharpe_score` | `clamp((mean_sharpe + 0.5) / 2.0)` | 0.35 | Average risk-adjusted return across OOS windows |
| `stability_score` | `fraction_positive_windows` | 0.30 | How often the signal produces positive OOS returns |
| `consistency_score` | `clamp(1 - std_sharpe / (\|mean_sharpe\| + 0.1))` | 0.20 | Stability of performance across windows |
| `drawdown_score` | `clamp(1 - mean_max_drawdown / 0.30)` | 0.15 | Average worst drawdown severity |

Where `clamp(x) = max(0, min(1, x))`.

### Component interpretation

**Sharpe score (w=0.35):** Maps mean OOS Sharpe from [-0.5, 1.5] to [0, 1]. A mean Sharpe of 0.5 → score = 0.5; Sharpe of 1.0 → score = 0.75. This is the primary quality metric — does the signal generate risk-adjusted returns?

**Stability score (w=0.30):** Fraction of OOS windows with positive return. A signal that works in 7/8 folds (0.875) gets a high stability score. A signal that works in 4/8 folds (0.50) gets a mediocre one. This penalizes signals that are spectacular in one regime but fail in others.

**Consistency score (w=0.20):** Measures the coefficient of variation of OOS Sharpe ratios. If mean Sharpe is 0.6 and std is 0.3, consistency = 1 - 0.3/0.7 ≈ 0.57. High consistency means the signal performs similarly across different market conditions.

**Drawdown score (w=0.15):** Penalizes signals with large average drawdowns. A signal with mean max drawdown of 15% scores 0.50; one with 5% scores 0.83. This prevents selecting signals that produce good average returns but with intolerable peak-to-trough losses.

### Viability gate (hard floor)

Before computing the weighted score, a binary viability check:

```python
is_viable = (n_valid_windows >= min_windows) and (fraction_positive_windows >= 0.40)
```

If `is_viable = False`, the reliability score is forced to 0.0 regardless of the component scores. This prevents a signal with only 2 OOS windows from receiving a high score due to lucky variance.

**Defaults:** `min_windows = 3`, `fraction_positive_threshold = 0.40`

### Mathematical properties

The reliability score is:
- **Bounded:** Always in [0, 1]
- **Monotone:** Higher OOS quality → higher score (within each component)
- **Transparent:** Each component is interpretable and the weights are explicit
- **Not a statistical test:** This is a pragmatic composite score, not a p-value. It does not control for multiple testing.

---

## Stage 2: Survivor Filtering (Layer D)

### Two-stage filter

```python
def filter_survivors(
    summaries: list[VariantRobustnessSummary],
    *,
    competitive_percentile: float = 0.40,
    min_competitive_score: float = 0.25,
) -> list[VariantRobustnessSummary]:
```

**Stage 2a — Viability gate:**
Remove all candidates where `is_viable = False` (reliability_score = 0.0). These failed the hard floor in Layer C.

**Stage 2b — Competitive filter:**
Among viable candidates, keep only those satisfying BOTH:
1. `reliability_score >= min_competitive_score` (absolute floor: 0.25)
2. `percentile_rank(reliability_score) >= competitive_percentile` (relative: top 60%)

**Why both conditions?**
- The absolute floor prevents keeping weak signals even when all candidates are weak (if the best candidate has reliability = 0.15, nothing should survive)
- The relative filter prevents keeping too many signals when the candidate pool is strong (if 10 out of 12 pass the absolute floor, only the top 60% survive)

### Example

Given 12 candidates with reliability scores:

```
[0.82, 0.71, 0.65, 0.58, 0.52, 0.45, 0.38, 0.31, 0.22, 0.15, 0.08, 0.00]
```

- Viability gate removes: 0.00 (is_viable = False) → 11 remain
- Absolute floor (0.25) removes: 0.22, 0.15, 0.08 → 8 remain
- Relative filter (top 60% of 8): keeps top 5 → [0.82, 0.71, 0.65, 0.58, 0.52]

**5 survivors** proceed to redundancy reduction.

### Methodology label

The filter is labeled `methodology_label = "competitive_oos_filter"` — NOT "MCS" or "SPA". This is an honest label reflecting that the filter is a pragmatic competitive selection, not a formal statistical procedure.

The architecture explicitly supports plugging in formal tests later:

```
# Future: replace competitive filter with Hansen's Model Confidence Set
# Hansen, P.R., Lunde, A., Nason, J.M. (2011). "The Model Confidence Set." Econometrica.
```

---

## Stage 3: Redundancy Reduction (Layer E)

### The problem

After survivor filtering, remaining candidates may still be highly correlated. Example:

| Candidate | Archetype | Params | Reliability |
|-----------|-----------|--------|-------------|
| SMA-20 price_vs_sma | price_vs_sma | w=20 | 0.82 |
| SMA-25 price_vs_sma | price_vs_sma | w=25 | 0.71 |
| SMA-50 price_vs_sma | price_vs_sma | w=50 | 0.65 |
| SMA-(10,50) cross | sma_cross | f=10, s=50 | 0.58 |
| SMA-(20,100) cross | sma_cross | f=20, s=100 | 0.52 |

SMA-20 and SMA-25 likely have signal correlation > 0.95. Including both in the ensemble adds noise without information.

### Greedy correlation clustering

```python
def reduce_redundancy(
    survivors: list[VariantRobustnessSummary],
    close: pd.Series,
    *,
    max_signal_correlation: float = 0.85,
    max_representatives: int = 6,
) -> list[VariantRobustnessSummary]:
```

**Algorithm:**

1. **Compute signal series** for each survivor over the full history:
   ```python
   signal_series[t] = +1 if close[t] > sma_w[t] else -1  # for price_vs_sma
   ```

2. **Sort survivors** by reliability_score descending

3. **Greedy selection:**
   ```
   selected = [best_survivor]  # Start with highest reliability
   for candidate in remaining_survivors (sorted by reliability):
       if max(|corr(candidate.signal, s.signal)| for s in selected) <= 0.85:
           selected.append(candidate)
       if len(selected) >= max_representatives:
           break
   ```

4. **Output:** A set of representatives that are both high-quality (reliability) and genuinely distinct (low mutual correlation)

### Why signal-level correlation, not parameter distance

Two signals with very different parameters can produce nearly identical signal series (e.g., SMA-49 and SMA-51). Conversely, two signals with similar parameters but different archetypes (e.g., SMA-50 price_vs_sma vs SMA-(20,50) cross) may have quite different signal series. Measuring redundancy at the signal level captures the actual information overlap.

**Reference:**
- López de Prado, M. (2020). *Machine Learning for Asset Managers*. Chapter 4: "Optimal Clustering" — uses correlation-based clustering to group similar features.

### Example result

From the 5 survivors above:

| Step | Candidate | Max corr with selected | Action |
|------|-----------|----------------------|--------|
| 1 | SMA-20 (0.82) | — | Select (first) |
| 2 | SMA-25 (0.71) | corr(SMA-25, SMA-20) = 0.97 | **Reject** (> 0.85) |
| 3 | SMA-50 (0.65) | corr(SMA-50, SMA-20) = 0.72 | Select |
| 4 | Cross(10,50) (0.58) | max(corr with SMA-20, SMA-50) = 0.61 | Select |
| 5 | Cross(20,100) (0.52) | max(corr with selected) = 0.78 | Select |

**4 representatives** — each contributing genuinely distinct information to the ensemble.

---

## Ensemble Combination (Layer G)

The surviving representatives are combined into a family-level signal using reliability-weighted averaging:

### Formula

```
family_score_raw = Σᵢ (wᵢ · sᵢ) / Σᵢ wᵢ
family_score_pct = 100 · family_score_raw
```

where:
- `wᵢ = reliability_score` of representative `i` (from Layer C)
- `sᵢ = current_signal` of representative `i` ∈ {-1, 0, +1} (from Layer F)

### Properties

- `family_score_pct ∈ [-100, +100]`
- If all representatives signal BUY (+1): `family_score_pct = +100`
- If all signal SELL (-1): `family_score_pct = -100`
- If signals disagree, the score reflects the reliability-weighted consensus

### Why reliability weighting

Not all signals are equally trustworthy. A signal with reliability 0.82 should have more influence than one with 0.52. The weighting ensures that the ensemble is dominated by its most robust members.

### Per-representative attribution

For UI drill-down, each representative's contribution is decomposed:

```python
normalized_weight_i = w_i / sum(w_j)           # Fraction of total weight
weighted_contribution_i = normalized_weight_i * s_i  # Signed contribution to family score
```

This makes the ensemble transparent: the user can see exactly why the family score is what it is.

---

## Full Pipeline Summary

```
Layer A: Generate candidates       [8-12 per family × horizon]
    ↓
Layer B: OOS evaluation            [Walk-forward, per candidate]
    ↓
Layer C: Robustness scoring        [reliability_score ∈ [0,1], viability gate]
    ↓
Layer D: Survivor filtering        [Absolute + relative competitive filter]
    ↓
Layer E: Redundancy reduction      [Greedy correlation clustering]
    ↓
Layer F: Current signal            [Latest bar signal for each representative]
    ↓
Layer G: Ensemble combination      [Reliability-weighted average → family_score_pct]
```

Typical attrition:
```
12 candidates → 12 evaluated → 8 viable → 5 survivors → 3 representatives
```

---

## Formal Tests: Current Status and Future Path

### What is implemented

| Mechanism | Type | Formal? |
|-----------|------|---------|
| Walk-forward OOS evaluation | Validation | Yes — no look-ahead, multiple windows |
| Multi-component reliability scoring | Scoring | Pragmatic — transparent but not a statistical test |
| Competitive survivor filtering | Selection | Pragmatic — percentile-based, not p-value based |
| Signal correlation clustering | Deduplication | Rigorous — well-defined algorithm with clear threshold |
| Reliability-weighted ensemble | Combination | Rigorous — standard forecast combination theory |

### What is planned (architecture supports but not yet implemented)

| Test | Reference | Purpose |
|------|-----------|---------|
| White's Reality Check | White (2000), *Econometrica* | Bootstrap test: "Is the best strategy significantly better than a benchmark?" |
| Hansen's SPA test | Hansen (2005), *JBES* | Improvement on White's RC: accounts for asymmetry in the null |
| Model Confidence Set (MCS) | Hansen, Lunde, Nason (2011), *Econometrica* | Identifies the set of models that are statistically indistinguishable from the best |
| Deflated Sharpe Ratio | Bailey & López de Prado (2014), *JPM* | Adjusts Sharpe for number of trials, skewness, kurtosis |

The `methodology_status` field in the API response honestly reports the current state:
- `"robust_oos_ensemble"` — WFO + competitive filter (current)
- `"formal_mcs"` — after MCS implementation (future)
- `"provisional"` — insufficient data for any OOS evaluation

---

## Transparency Note

The following statement is displayed in the methodology modal on the strategy page:

> *"Implémentation actuelle: ensemble OOS robuste avec filtre compétitif. Aucun test MCS ou SPA formel n'est appliqué. L'architecture permet d'y ajouter ces tests ultérieurement."*

Translation: "Current implementation: robust OOS ensemble with competitive filter. No formal MCS or SPA test is applied. The architecture allows adding these tests later."

This transparency is by design. The system is honest about what it does and does not guarantee.

---

## References

- White, H. (2000). "A Reality Check for Data Snooping." *Econometrica*, 68(5), 1097–1126.
- Hansen, P.R. (2005). "A Test for Superior Predictive Ability." *Journal of Business & Economic Statistics*, 23(4), 365–380.
- Hansen, P.R., Lunde, A., Nason, J.M. (2011). "The Model Confidence Set." *Econometrica*, 79(2), 453–497.
- Bailey, D.H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio." *Journal of Portfolio Management*, 40(5), 94–107.
- López de Prado, M. (2020). *Machine Learning for Asset Managers*. Cambridge. Chapter 4: "Optimal Clustering."
- Timmermann, A. (2006). "Forecast Combinations." In *Handbook of Economic Forecasting*, Vol. 1. Elsevier. — Theory behind reliability-weighted forecast combination.
- Bates, J.M. & Granger, C.W.J. (1969). "The Combination of Forecasts." *Operational Research Quarterly*, 20(4), 451–468. — Original proof that combined forecasts outperform individual ones.
