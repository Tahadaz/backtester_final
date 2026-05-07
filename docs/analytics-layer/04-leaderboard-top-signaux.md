# Top Signaux — Leaderboard Methodology

## What the Leaderboard Shows

The leaderboard ranks every `(symbol × source)` pair by **mean Information Coefficient (IC)** across the forward horizons of the selected engine horizon. It answers: *which signals, for which stocks, have the most consistent historical predictive ability?*

---

## Step 1 — Score Aggregation

For each `(symbol, source)` pair, the composite score is the mean across **all 4 categories** (tendance, momentum, oscillation, volume):

```
score(t) = mean( score_tendance(t), score_momentum(t), score_oscillation(t), score_volume(t) )
```

**Known limitation**: the leaderboard endpoint currently hardcodes all 4 categories and does not accept a `categories` filter parameter. The per-stock matrix (`GET /analytics/predictive-ability`) does support category filtering. The leaderboard will always reflect the full 4-category composite regardless of any category selection in the UI.

**Implementation**: `services/api/app/routers/analytics.py` — `get_predictive_ability_leaderboard()`, line 1277:
```python
score = aggregate_subset(series_by_cat, _VALID_CATEGORIES)
# _VALID_CATEGORIES = ["tendance", "momentum", "oscillation", "volume"]
```

---

## Step 2 — Spearman Information Coefficient

For each forward horizon `h`, the IC is the **Spearman rank correlation** between the composite score and the `h`-day forward return:

$$IC_h = \text{Spearman}\left( \text{score}(t),\ \frac{P(t+h) - P(t)}{P(t)} \right)$$

### Why Spearman, not Pearson?

Spearman operates on *ranks* rather than raw values. This makes it:
- Robust to outlier returns (a single extreme crash does not dominate)
- Invariant to monotone transformations of the score (e.g. whether scores are linearly or nonlinearly distributed)
- Consistent with Grinold & Kahn's definition of IC as a rank correlation measure

### Computation

```python
# Rank both series (pandas .rank() handles ties by averaging)
rank_s = score.rank()
rank_r = forward_returns.rank()

# Pearson correlation on ranks = Spearman correlation
IC = cov(rank_s, rank_r) / (std(rank_s) × std(rank_r))
```

**Interpretation**:
- `IC = 0.0`: no rank relationship — signal does not predict returns
- `IC = 0.05`: modest predictive ability (typical for real TA signals)
- `IC = 0.10`: strong predictive ability (rare, usually overfitted)
- `IC < 0`: inverted signal — high scores predict negative returns
- Practical threshold: `|IC| > 0.03` with `|t| > 2` is considered meaningful

**Implementation**: `core/quant_core/research/stats/ic.py` — `_spearman_corr()`

**Citation**: Grinold, R. C. & Kahn, R. N. (2000). *Active Portfolio Management*, 2nd ed. Ch. 6 — IC as the cross-sectional rank correlation between forecasts and outcomes.

---

## Step 3 — Newey-West HAC t-statistic

Raw IC computed at horizon `h` is biased when forward returns overlap: the 10-day return at day `t` shares 9 days with the 10-day return at day `t+1`. These overlapping windows produce autocorrelated IC estimates, making the standard error too small and the t-statistic too large.

The **Newey-West HAC (Heteroskedasticity and Autocorrelation Consistent)** t-statistic corrects for this.

### Construction

The per-bar rank-product series is constructed:

$$z_t = \frac{\text{rank}(\text{score}_t) - \bar{r}_s}{\text{std}(\text{rank\_score})} \times \frac{\text{rank}(\text{return}_t) - \bar{r}_r}{\text{std}(\text{rank\_return})}$$

The mean of `z_t` ≈ IC. The Newey-West variance of this mean absorbs autocorrelation:

$$\text{Var}_\text{NW}(\bar{z}) = \frac{\gamma_0}{T} + \frac{2}{T} \sum_{k=1}^{L} \left(1 - \frac{k}{L+1}\right) \gamma_k$$

Where:
- $\gamma_k = \frac{1}{T} \sum_t z_t z_{t-k}$ — sample autocovariance at lag $k$
- $L$ — bandwidth (number of lags included)
- The Bartlett kernel weight $\left(1 - \frac{k}{L+1}\right)$ down-weights distant lags

**Bandwidth selection**:

$$L = \max\!\left(h,\ \left\lfloor 4 \cdot \left(\frac{T}{100}\right)^{2/9} \right\rfloor \right)$$

Using `h` (the forward horizon) as a minimum ensures at minimum `h` lags are included — exactly the number of overlapping observations. The second term is Andrews' (1991) data-driven rule.

**t-statistic**:

$$t_\text{NW} = \frac{IC}{\sqrt{\text{Var}_\text{NW}(\bar{z})}}$$

**Interpretation**:
- `|t| > 2.0`: significant at approximately 95% (two-tailed)
- `|t| > 1.65`: significant at approximately 90%
- `|t| < 1.65`: not statistically significant — IC may be noise

**Implementation**: `core/quant_core/research/stats/ic.py` — `_newey_west_var()`

**Citations**:
- Newey, W. K. & West, K. D. (1987). "A Simple Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix." *Econometrica*, 55(3), 703–708.
- Andrews, D. W. K. (1991). "Heteroskedasticity and Autocorrelation Consistent Covariance Matrix Estimation." *Econometrica*, 59(3), 817–858.

---

## Step 4 — mean_ic (the leaderboard sort key)

The leaderboard sorts by `mean_ic` — the average IC across all valid forward horizons for the engine horizon group:

| Engine horizon | Forward horizons | mean_ic |
|---|---|---|
| short | [1, 2, 3, 4, 5] | mean(IC₁, IC₂, IC₃, IC₄, IC₅) |
| medium | [6, 10, 15, 21] | mean(IC₆, IC₁₀, IC₁₅, IC₂₁) |
| long | [30, 60, 120, 200] | mean(IC₃₀, IC₆₀, IC₁₂₀, IC₂₀₀) |

Horizons where IC is `None` (fewer than 20 observations) are excluded from the mean. A row with no valid IC at any horizon is excluded from the leaderboard entirely.

---

## Step 5 — N (the observation count)

`N` on the leaderboard row is the number of aligned `(score, price)` observations used across all IC calculations for this `(symbol, source)` pair. It is the count of rows in `signal_score_history` after date alignment with the price series.

A low `N` (< 100) means the IC estimate has wide uncertainty even if the value looks large. The NW t-stat will also be low for small N.

---

## Visual Encoding

| Element | Encoding |
|---|---|
| Row background color | Green (positive IC) / Red (negative IC) |
| Color opacity | Scales with `|mean_ic|` — full opacity at `|IC| = 0.20` |
| Sort order | Descending `mean_ic` by default |

A row at the top with dark green = high positive IC across the horizon group = strongest predictive signal in the universe. A row with dark red = inverted signal (consider reversing).

---

## Known Limitation — Category Filter

The leaderboard does not accept a `categories` query parameter. It always aggregates across all 4 categories (`tendance`, `momentum`, `oscillation`, `volume`). Changing the category checkboxes in the UI has no effect on the leaderboard ranking.

The per-stock matrix (`GET /analytics/predictive-ability`) correctly supports the `categories` parameter and will re-compute on category changes.

Fixing this would require: adding `categories: Optional[str]` to `get_predictive_ability_leaderboard()`, parsing and validating it, passing to `aggregate_subset()`, and adding the category set to the cache key.
