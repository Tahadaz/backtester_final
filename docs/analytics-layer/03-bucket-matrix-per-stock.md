# Par Action — Bucket Matrix Methodology

## What the Matrix Shows

The per-stock matrix is a grid with:
- **5 rows** — one per signal bucket (strong sell → strong buy)
- **N columns** — one per forward-return horizon (trading days)

Each cell answers: *"Historically, when the signal score was in this bucket, what happened to the price over the next N days?"*

---

## Step 1 — Score Aggregation

The composite signal score for a bar is the mean of the selected category scores:

```
score(t) = mean( score_tendance(t), score_momentum(t), score_oscillation(t), score_volume(t) )
```

Each category score is in `[−100, +100]`. The composite is also in `[−100, +100]`. Users can restrict to a subset of categories via the category checkboxes — the mean is then taken over only the selected categories.

**Implementation**: `core/quant_core/research/score_history.py` — `aggregate_subset()`

---

## Step 2 — Bucket Classification

Each bar's composite score is assigned to one of 5 buckets:

| Bucket | Score range | Interpretation |
|---|---|---|
| `strong_sell` | score < −50 | Strong bearish signal |
| `sell` | −50 ≤ score < −15 | Moderate bearish signal |
| `hold` | −15 ≤ score ≤ +15 | Neutral / no conviction |
| `buy` | +15 < score ≤ +50 | Moderate bullish signal |
| `strong_buy` | score > +50 | Strong bullish signal |

Thresholds `[−50, −15, +15, +50]` divide the `[−100, +100]` range into 5 equal-sized zones of width 35 (with the two extreme zones unbounded).

**Implementation**: `core/quant_core/research/score_history.py` — `_bucket_for(score)`

---

## Step 3 — Forward Return Computation

For each bar `t` and forward horizon `h`:

$$\text{forward\_return}(t, h) = \frac{\text{price}(t+h) - \text{price}(t)}{\text{price}(t)}$$

This is `pandas.Series.pct_change(h).shift(-h)` — a percentage return over the next `h` trading days using close prices.

The last `h` bars have no forward return (shifted out) and are dropped before statistics are computed.

**Default forward horizons evaluated**: `[1, 2, 3, 4, 5, 6, 10, 15, 21, 30, 60, 120, 200]` trading days.

---

## Step 4 — Mean Forward Return (the main "%" in each cell)

For all bars assigned to bucket `b` with a valid forward return at horizon `h`:

$$\bar{r}_{b,h} = \frac{1}{N_{b,h}} \sum_{t \in \text{bucket } b} \text{forward\_return}(t, h)$$

**Interpretation**:
- A `buy` cell showing **+3%** means: historically, when the signal was bullish, the stock gained an average of 3% over that horizon.
- A `sell` cell showing **−2%** means: when the signal was bearish, the stock lost an average of 2%.
- A cell close to **0%** means the signal had no predictive value at that horizon.

**Minimum observations**: cells with fewer than 5 observations (`N < 5`) are shown as `—` (not enough data).

**Implementation**: `core/quant_core/research/score_history.py` — `bucketed_forward_returns()`, lines 249–250.

---

## Step 5 — Bootstrap Confidence Interval on the Mean Return

A 95% confidence interval on the mean return is computed via **Politis-Romano (1994) stationary bootstrap**.

### Why stationary bootstrap, not standard bootstrap?

Forward returns overlap: if you compute a 10-day forward return starting on day 1 and again on day 2, those two returns share 9 days of price data. They are autocorrelated. Standard iid bootstrap would destroy this correlation structure and produce overconfident (too narrow) confidence intervals.

The stationary bootstrap resamples *blocks* of consecutive observations, where block lengths are geometrically distributed (random length, random start). This preserves serial correlation up to the expected block length.

### Parameters used

| Parameter | Value | Meaning |
|---|---|---|
| `block_prob` | 0.05 | Probability of ending a block each step → expected block length = 1/0.05 = **20 bars** |
| `n_bootstrap` | 300 | Number of bootstrap resamples |
| `alpha` | 0.05 | 95% confidence interval (2.5th and 97.5th percentiles) |

### Formula

For bootstrap resample `b`:
1. Draw a random starting index.
2. Draw a block length from `Geometric(0.05)` → mean length 20 bars.
3. Copy that block into the resample (wrapping around if needed).
4. Repeat until resample has `T` bars.
5. Compute `mean(resample)`.

Repeat 300 times, take the 2.5th and 97.5th percentiles of the 300 bootstrap means.

$$\text{CI}_{95\%} = \left[ \text{percentile}_{2.5}(\bar{r}^*_1, \ldots, \bar{r}^*_{300}),\ \text{percentile}_{97.5}(\bar{r}^*_1, \ldots, \bar{r}^*_{300}) \right]$$

### How to read the CI

- **CI entirely positive** (e.g. `[+0.3%, +2%]`): the positive mean return is statistically credible at 95%. The signal has genuine positive edge at this horizon.
- **CI crossing zero** (e.g. `[−0.2%, +11%]`): cannot rule out zero mean return. Directionally promising but statistically immature. Trust depends on N — if N is small, the CI will tighten with more data.
- **CI entirely negative** for a `buy` cell: the signal is inverted at this horizon. Consider reversing or discarding it.

**Implementation**: `core/quant_core/research/stats/robustness.py` — `stationary_bootstrap_ci()`

**Citation**: Politis, D. N. & Romano, J. P. (1994). "The Stationary Bootstrap." *Journal of the American Statistical Association*, 89(428), 1303–1313.

---

## Step 6 — Hit Rate (the small "%" below the mean return)

Hit rate measures directional accuracy — what fraction of signals fired in the correct direction.

### Definition by bucket

The definition of "correct" differs by bucket, because each bucket has a different directional expectation:

| Bucket | Definition of a hit |
|---|---|
| `strong_buy` | `forward_return > 0` (price went up — any gain counts) |
| `buy` | `forward_return > 0` |
| `hold` | `|forward_return| < std(forward_returns)` (price stayed range-bound, within 1σ) |
| `sell` | `forward_return < 0` (price went down — any loss counts) |
| `strong_sell` | `forward_return < 0` |

For the `hold` bucket: if `std = 0` (perfectly flat returns, extremely rare), hits default to 0.

```python
# Implementation (score_history.py:254-259):
if b in ("buy", "strong_buy"):
    hits = np.sum(r > 0)
elif b in ("sell", "strong_sell"):
    hits = np.sum(r < 0)
else:  # "hold"
    hits = np.sum(np.abs(r) < std) if std > 0 else 0

hit_rate = hits / N
```

### Interpretation

- **50% hit rate** on a directional bucket (buy/sell) = coin flip = no directional edge.
- **60%+ hit rate** = the signal is directionally correct more often than not.
- **40% hit rate + positive mean return** = asymmetric payoff — wins are bigger than losses. This is the classic trend-following profile. Hit rate alone does not determine edge.
- **Hold hit rate near 70%** = signal correctly identifies low-volatility periods 70% of the time.

**Implementation**: `core/quant_core/research/score_history.py` — `bucketed_forward_returns()`, lines 254–260.

---

## Step 7 — Wilson Confidence Interval on Hit Rate

The 95% Wilson score interval is computed for the hit rate.

### Why Wilson, not normal approximation?

The standard normal approximation `p ± 1.96 × sqrt(p(1-p)/N)` breaks down for small N or extreme proportions (near 0 or 1) — it can produce intervals outside `[0, 1]` and is systematically overconfident. Wilson (1927) provides a more accurate interval that is always within `[0, 1]`.

### Formula

$$p_\text{low}, p_\text{high} = \frac{1}{1 + z^2/N} \left( \hat{p} + \frac{z^2}{2N} \mp z \sqrt{\frac{\hat{p}(1-\hat{p})}{N} + \frac{z^2}{4N^2}} \right)$$

Where:
- $\hat{p} = \text{hits} / N$ — observed hit rate
- $z = 1.96$ — 97.5th percentile of the standard normal (for 95% CI)
- $N$ — number of observations in the bucket

**Implementation**: `core/quant_core/research/stats/hit_rate.py` — `wilson_ci(k, n, alpha=0.05)`

**Citations**:
- Wilson, E. B. (1927). "Probable Inference, the Law of Succession, and Statistical Inference." *Journal of the American Statistical Association*, 22(158), 209–212.
- Online explainer: https://www.econometrics.blog/post/the-wilson-confidence-interval-for-a-proportion/

---

## Reading a Cell — Complete Example

A cell in the `buy` bucket at forward horizon 5 days showing:

```
+3.2%
61% · n=87
```

Means:
- **+3.2%**: historically, when the composite score was in `(+15, +50]`, the stock returned on average +3.2% over the next 5 days.
- **Bootstrap CI** (shown in tooltip): e.g. `[+0.8%, +5.6%]` — entirely positive, so statistically credible.
- **61%**: 61% of those 87 signals were followed by a positive 5-day return.
- **n=87**: 87 observations — enough to be meaningful (Wilson CI will be tight).

If the CI crossed zero: the +3.2% is directionally promising but statistically unconfirmed. You would need more data or a longer history to trust it.

---

## Minimum Thresholds

| Threshold | Value | Where applied |
|---|---|---|
| Minimum observations to show any cell | 5 | Cells with N < 5 show `—` |
| Minimum observations for bootstrap CI | 10 | `stationary_bootstrap_ci` returns NaN for N < 10 |
| Minimum aligned observations for the whole matrix | 20 | `bucketed_forward_returns` returns empty if fewer than 20 aligned bars |
