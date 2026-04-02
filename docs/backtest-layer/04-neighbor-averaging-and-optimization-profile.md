# 04 — Neighbor-Averaging and Optimization Profile

**References**: Pardo (2008) Ch.10 p.235 (neighbor-averaging), Ch.10 p.260-268 (optimization profile)

---

## Part 1: Neighbor-Averaging

### Problem

Raw optimization selects the parameter with the highest PROM. But in a noisy landscape, the highest PROM may be an **isolated spike** — a parameter that performed well by accident, surrounded by parameters that performed poorly.

A robust parameter sits on a **plateau**: its neighbors also perform well. If you shift the parameter slightly, performance doesn't collapse. This is the hallmark of a genuine effect rather than a statistical artifact.

### Solution: Smoothed PROM

For each parameter value `p`, compute the smoothed PROM as the mean of `p` and its neighbors:

```
smoothed_PROM(p) = mean(PROM(p-k), PROM(p-k+1), ..., PROM(p), ..., PROM(p+k-1), PROM(p+k))
```

Where `k` is the neighbor radius.

**Select the parameter with the highest `smoothed_PROM`**, not the highest raw PROM.

### Neighbor Radius by Family Dimensionality

| Family | Parameter dimensions | k | Averaging method |
|--------|---------------------|---|------------------|
| **SMA** | 1D (period) | 1 | Mean of 3 values: PROM(p-1), PROM(p), PROM(p+1) |
| **OBV** | 1D (ema_period) | 1 | Mean of 3 values |
| **RSI** | 2D (period, threshold_set) | 1 per axis | Average along each axis independently, then combine |
| **MACD** | 3D (fast, slow, signal) | 1 per axis | Average along each axis independently, then combine |

### 1D Neighbor-Averaging (SMA, OBV)

```python
def neighbor_average_1d(prom_values: dict[int, float], k: int = 1) -> dict[int, float]:
    """
    prom_values: {parameter_value: prom_score}
    Returns: {parameter_value: smoothed_prom_score}
    """
    sorted_params = sorted(prom_values.keys())
    smoothed = {}

    for i, p in enumerate(sorted_params):
        neighbors = []
        for j in range(max(0, i - k), min(len(sorted_params), i + k + 1)):
            neighbors.append(prom_values[sorted_params[j]])
        smoothed[p] = mean(neighbors)

    return smoothed
```

**Example:**

```
SMA periods:  [5,  6,  7,  8,  9,  10, 11, 12]
Raw PROM:     [0.2, 0.3, 0.8, 0.3, 0.4, 0.3, 0.7, 0.6]

Smoothed (k=1):
  p=5:  mean(0.2, 0.3)       = 0.25   (boundary: only right neighbor)
  p=6:  mean(0.2, 0.3, 0.8)  = 0.43
  p=7:  mean(0.3, 0.8, 0.3)  = 0.47   <-- raw winner (0.8) but spike
  p=8:  mean(0.8, 0.3, 0.4)  = 0.50
  p=11: mean(0.3, 0.7, 0.6)  = 0.53   <-- smoothed winner (plateau)
  p=12: mean(0.7, 0.6)       = 0.65   (boundary: only left neighbor)

Raw winner:      p=7  (PROM = 0.8, isolated spike)
Smoothed winner: p=12 (smoothed = 0.65, on a plateau with p=11)
```

Neighbor-averaging shifted the selection from an isolated spike (p=7) to a plateau (p=11-12).

### Multi-Dimensional Neighbor-Averaging (RSI, MACD)

For multi-dimensional parameter spaces, apply neighbor-averaging **along each axis independently**, then combine.

**RSI (2D: period x threshold_set):**

```python
# Step 1: For each threshold_set, smooth across periods (1D)
for ts in threshold_sets:
    smoothed_by_period[ts] = neighbor_average_1d(
        {period: prom[period, ts] for period in periods}
    )

# Step 2: For each period, smooth across threshold_sets (1D)
for p in periods:
    smoothed_by_ts[p] = neighbor_average_1d(
        {ts: prom[p, ts] for ts in threshold_sets}
    )

# Step 3: Combined smoothed PROM = mean of both smoothings
smoothed[p, ts] = (smoothed_by_period[ts][p] + smoothed_by_ts[p][ts]) / 2
```

**MACD (3D: fast x slow x signal):**

Same principle along three axes. The combined smoothed PROM is the mean of three axis-wise smoothings.

This approach is computationally efficient (linear in parameter count per axis) while capturing plateau structure in each dimension.

---

## Part 2: Optimization Profile

### Problem

Even with neighbor-averaging, an IS window might produce unreliable results if the optimization landscape itself is degenerate. Signs of a degenerate landscape:

- Nearly all parameter sets lose money (the strategy simply doesn't work in this regime)
- One parameter set is wildly profitable while all others fail (likely an artifact)
- The distribution of PROMs is extremely noisy with no discernible structure

### Three Checks Per IS Window

Pardo (Ch.10 p.260-268) defines three checks that constitute an **optimization profile**. All three must pass for the IS window's winner to be used.

#### Check 1: Statistical Significance

**Criterion:** At least 20% of parameter sets must be profitable (PROM > 0).

```python
n_profitable = sum(1 for prom in all_proms if prom > 0)
pct_profitable = n_profitable / len(all_proms)

if pct_profitable < 0.05:
    return ProfileResult(passes=False, reason="catastrophic",
                         detail=f"Only {pct_profitable:.0%} profitable (< 5%)")

if pct_profitable < 0.20:
    return ProfileResult(passes=False, reason="insufficient",
                         detail=f"Only {pct_profitable:.0%} profitable (< 20%)")
```

**Two thresholds:**
- `< 5%` profitable: **catastrophic failure** — the strategy fundamentally doesn't work in this data regime. Strong reject.
- `< 20%` profitable: **insufficient** — too few profitable parameter sets to trust the winner. Soft reject.

**Rationale:** If a strategy concept is sound, it should work across a range of parameters, not just one magic number. Having 20%+ profitable parameter sets indicates that the strategy has genuine alpha in this regime.

#### Check 2: Distribution

**Criterion:** The top parameter's smoothed PROM must be within 1 standard deviation of the mean PROM of profitable parameter sets.

```python
profitable_proms = [p for p in all_proms if p > 0]
mean_profitable = mean(profitable_proms)
std_profitable = std(profitable_proms)

winner_prom = smoothed_prom[winner_params]

if winner_prom > mean_profitable + std_profitable:
    return ProfileResult(passes=False, reason="outlier",
                         detail=f"Winner PROM {winner_prom:.4f} > "
                                f"mean+1std {mean_profitable + std_profitable:.4f}")
```

**Rationale:** If the winner is an extreme outlier relative to other profitable parameter sets, it is likely a statistical artifact. A robust winner should be near the center of the profitable distribution, not an extreme tail observation.

#### Check 3: Shape (Smoothness)

**Criterion:** The optimization landscape should be smooth rather than spiky.

This check is largely handled by neighbor-averaging itself — by smoothing the landscape and selecting from the smoothed version, spiky winners are automatically demoted. However, as an additional diagnostic, we compute the coefficient of variation of PROM across neighbors of the winner:

```python
winner_neighbors = get_neighbors(winner_params, k=2)
neighbor_proms = [prom[n] for n in winner_neighbors]
cv = std(neighbor_proms) / abs(mean(neighbor_proms)) if mean(neighbor_proms) != 0 else inf

if cv > 1.5:
    flag_warning("high_volatility_landscape",
                 f"CV of winner neighborhood = {cv:.2f}")
```

This is a soft warning, not a hard reject. The primary smoothness enforcement comes from neighbor-averaging.

### When Optimization Profile Fails

If an IS window fails the optimization profile:

1. **Flag the window** with diagnostic data (which check failed, with values)
2. **Do not use this window's winner** in the OOS evaluation
3. **The window still counts** toward total walk-forward count (affects robustness ratio)

This means a failed optimization profile is equivalent to a non-profitable OOS window from the robustness perspective. The strategy must overcome this in other windows.

---

## Combined Effect

The neighbor-averaging + optimization profile system acts as a two-layer defense:

```
Layer 1 (neighbor-averaging):  Shifts selection from spikes to plateaus
Layer 2 (optimization profile): Rejects entire IS windows where optimization is unreliable
```

Together, they ensure that the parameter selected from each IS window is:
1. On a plateau (robust to small parameter changes)
2. From a window where optimization produced a meaningful landscape
3. Not an extreme outlier relative to other profitable parameters

This is the foundation that makes WFE (doc 05) a meaningful metric — if the IS winners are poorly selected, WFE measures noise rather than optimization transfer quality.
