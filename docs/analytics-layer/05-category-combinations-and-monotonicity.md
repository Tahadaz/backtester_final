# Category Combinations and Monotonicity Score

## What the Panel Shows

Below the bucket matrix, the **category combinations panel** ranks every possible non-empty subset of the 4 signal categories by a **monotonicity score Δ** at one selected forward horizon.

It answers: *which combination of signal categories best separates strong buy signals from strong sell signals?*

---

## Motivation

The composite score averages all 4 categories equally. But some categories may be noise — including them dilutes the predictive categories and hurts edge. The combinations panel helps identify the minimal, most predictive category subset.

For example: if `tendance + momentum` has Δ = +6% but all 4 categories has Δ = +2%, then `oscillation` and `volume` are actively hurting the signal for this stock at this horizon.

---

## Monotonicity Score Δ

$$\Delta = \bar{r}_\text{strong\_buy} - \bar{r}_\text{strong\_sell}$$

Where:
- $\bar{r}_\text{strong\_buy}$ = mean forward return when score > +50
- $\bar{r}_\text{strong\_sell}$ = mean forward return when score < −50

Both computed at the selected forward horizon `h` using the composite score of the given category subset.

**Interpretation**:
- **High positive Δ** (e.g. +8%): strong buys gain much more than strong sells lose — excellent separation between extremes. The signal correctly identifies both bullish and bearish regimes.
- **Δ ≈ 0**: no separation — strong buys and strong sells have similar average returns. The extreme signal values carry no information.
- **Negative Δ**: strong buys underperform strong sells — the signal is inverted at the extremes.

**Why extremes only?** The strong buy / strong sell buckets represent the highest-conviction signal events. If a signal has genuine edge, it should be most visible at these extremes. A signal that shows edge in the moderate buckets but not the extremes is typically noisy.

**Implementation**: `services/api/app/routers/analytics.py` — `get_category_combinations()`, line 1192:
```python
mono = (sb_mean - ss_mean) if (sb_mean is not None and ss_mean is not None) else None
```

---

## Subset Enumeration

All $2^4 - 1 = 15$ non-empty subsets of the 4 categories are evaluated:

```
Size 1 (4 subsets):
  [tendance], [momentum], [oscillation], [volume]

Size 2 (6 subsets):
  [tendance, momentum], [tendance, oscillation], [tendance, volume],
  [momentum, oscillation], [momentum, volume], [oscillation, volume]

Size 3 (4 subsets):
  [tendance, momentum, oscillation], [tendance, momentum, volume],
  [tendance, oscillation, volume], [momentum, oscillation, volume]

Size 4 (1 subset):
  [tendance, momentum, oscillation, volume]  ← the default composite
```

For each subset, the composite score is recomputed as the mean of the selected category scores, then `bucketed_forward_returns` is called at the chosen forward horizon.

**Performance**: to keep latency acceptable, the combinations endpoint uses `n_bootstrap=50` (vs 300 for the main matrix). This means the CI on bucket means is less precise here — the Δ score itself does not use bootstrap, so this does not affect the ranking.

---

## Panel Display

Each row in the panel shows:
- **Category badges** — the subset
- **Δ = X.XX%** — the monotonicity score (green = positive, red = negative)
- **SB n=N · SS n=N** — observation counts in strong buy and strong sell buckets

Rows are sorted descending by Δ. Clicking a row updates the category selection checkboxes and refreshes the main bucket matrix with that subset.

---

## How to Use This Panel

1. **Find the highest-Δ row**: this is the category combination with the best strong-buy vs. strong-sell separation at the selected horizon.
2. **Click it**: the main matrix updates to show that combination. Check whether the CI on the mean returns is tight (positive — not crossing zero).
3. **Compare to the full 4-category row**: if Δ drops significantly when going from a 2-category to a 4-category subset, the extra categories are adding noise.
4. **Check N** (`SB n=` and `SS n=`): if there are fewer than 20 strong-buy or strong-sell observations, Δ is unreliable regardless of its value.
5. **Forward horizon matters**: Δ can be large at short horizons (1–5 days) but shrink at longer horizons. Check whether the winning subset is consistent across horizons by switching the horizon selector.

---

## Limitations

- Δ uses only the strong buy / strong sell means. A subset could have high Δ but poor moderate-bucket performance — always also check the full bucket matrix for the selected subset.
- With only a few hundred bars of history, strong buy and strong sell observations can be rare. N < 10 in either extreme bucket makes Δ meaningless.
- The combinations endpoint uses `n_bootstrap=50` for speed — the main matrix (300 resamples) provides more reliable CIs.
