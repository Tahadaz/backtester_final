# 04 — Layer C: Robustness Scoring

**File**: `core/quant_core/signal_engine/robustness.py`

---

## Purpose

Layer C scores each variant's robustness by combining multiple OOS metrics into a single reliability score. This multi-metric approach prevents the gaming that occurs when variants are ranked by a single statistic (e.g., "highest Sharpe wins").

> *"Any metric that becomes a target ceases to be a good metric."* — Goodhart's Law, applied to backtesting

---

## Viability Gate

Before computing the reliability score, every variant must pass a viability gate:

```python
is_viable = (n_valid_windows >= min_windows) AND (fraction_positive_windows >= 0.40)
```

**Default**: `min_windows = 3`

**Interpretation**:
- **≥3 valid windows**: We need enough data points for the aggregate statistics to be meaningful. With only 1–2 windows, mean Sharpe has no statistical significance.
- **≥40% positive windows**: At least 40% of OOS windows must have positive Sharpe. A signal that works in only 1 of 5 windows is likely noise — its in-sample-selected window is a false positive.

**If the gate fails**: `reliability_score = 0.0`, `is_viable = False`. The variant is excluded from all subsequent layers.

---

## Component Scores

Each component maps a raw metric to [0, 1]:

### 1. Sharpe Score (35% weight)

```python
sharpe_score = clamp((mean_sharpe + 0.5) / 2.0, 0, 1)
```

**Mapping**: mean_sharpe ∈ [-0.5, 1.5] → [0, 1]
- mean_sharpe = -0.5 → score = 0.0 (terrible)
- mean_sharpe = 0.0 → score = 0.25 (break-even)
- mean_sharpe = 0.5 → score = 0.50 (decent)
- mean_sharpe = 1.5 → score = 1.0 (exceptional)

**Why 35%?** Sharpe is the single most important metric for signal quality — it measures return per unit of risk. But it's not sufficient alone (a high-Sharpe signal with 1 good window and 4 bad ones is unreliable).

### 2. Stability Score (30% weight)

```python
stability_score = fraction_positive_windows
```

**Mapping**: Already ∈ [0, 1].
- 40% positive windows → score = 0.40 (minimum viable)
- 70% positive windows → score = 0.70 (good)
- 100% positive windows → score = 1.00 (excellent)

**Why 30%?** Consistency across time periods is crucial. A signal that works half the time is too unreliable for ensemble use. High stability indicates the signal captures a persistent market feature, not a temporary regime.

### 3. Consistency Score (20% weight)

```python
consistency_score = clamp(1.0 - std_sharpe / (|mean_sharpe| + 0.1), 0, 1)
```

**Interpretation**: Penalizes signals where Sharpe varies wildly between windows. If std_sharpe >> mean_sharpe, the signal is inconsistent — some windows are great, others are terrible.

The `+ 0.1` in the denominator prevents division-by-zero when mean_sharpe ≈ 0.

**Why 20%?** Consistency supplements stability. A signal can have 60% positive windows (decent stability) but with Sharpe swinging from -2 to +3 (poor consistency). Consistency rewards signals with predictable performance.

### 4. Drawdown Score (15% weight)

```python
drawdown_score = clamp(1.0 - mean_max_drawdown / 0.30, 0, 1)
```

**Mapping**: mean_max_drawdown ∈ [0, 0.30] → [1, 0]
- 0% drawdown → score = 1.0 (no loss)
- 15% drawdown → score = 0.50 (moderate)
- 30%+ drawdown → score = 0.0 (unacceptable)

**Why 15%?** Drawdown is important for risk but is partially captured by Sharpe. A separate 15% weight ensures that high-return, high-drawdown signals are penalized, but it doesn't dominate the score.

**The 0.30 threshold**: A 30% drawdown is the maximum acceptable loss for most institutional mandates. Beyond this, the signal is too dangerous regardless of its return.

---

## Reliability Score (Weighted Composite)

```python
reliability_score = clamp(
    0.35 × sharpe_score
    + 0.30 × stability_score
    + 0.20 × consistency_score
    + 0.15 × drawdown_score,
    0.0, 1.0
)
```

### Weight Rationale

| Component | Weight | Rationale |
|-----------|--------|-----------|
| Sharpe | 35% | Absolute return quality — the primary measure of predictive power |
| Stability | 30% | Consistency across time — prevents cherry-picking good windows |
| Consistency | 20% | Low variance of Sharpe — signals should be predictable |
| Drawdown | 15% | Risk control — signals shouldn't produce catastrophic losses |

These weights sum to 100% and were chosen to balance return quality (65% via Sharpe + Stability) against risk control (35% via Consistency + Drawdown).

---

## VariantRobustnessSummary Dataclass

```python
@dataclass
class VariantRobustnessSummary:
    variant: VariantDef
    n_oos_windows: int           # total windows generated
    n_valid_windows: int         # windows with ≥20 bars
    mean_sharpe: float
    std_sharpe: float
    median_sharpe: float
    fraction_positive_windows: float
    mean_max_drawdown: float
    reliability_score: float     # [0.0, 1.0]
    is_viable: bool
    sharpe_score: float          # component [0, 1]
    stability_score: float
    consistency_score: float
    drawdown_score: float
    cagr: float                  # mean across windows
    total_pnl: float             # mean across windows
```

---

## Threshold Sensitivity Analysis

**Script**: `scripts/signal_engine_sensitivity.py`

The threshold values (viability gate 0.40, floor 0.25, percentile 0.40, correlation 0.85, cost 33 bps) were not chosen arbitrarily. They were validated using a formal sensitivity analysis that perturbs each threshold ±20% and measures the impact on the final family scores.

### ThresholdSet (All Tuneable Parameters)

```python
@dataclass
class ThresholdSet:
    min_fraction_positive: float = 0.40   # Viability gate: % positive OOS windows
    min_competitive_score: float = 0.25   # Absolute floor for reliability score
    competitive_percentile: float = 0.40  # Fraction eliminated in Layer D
    max_corr: float = 0.85               # Redundancy threshold (Layer E)
    cost_bps: float = 33.0               # Transaction cost for Moroccan equities
```

### Methodology

For each threshold parameter, the analysis:

1. **Baseline run**: Execute the full A→G pipeline for all 4 families with default thresholds
2. **Perturbation**: Change one threshold at a time by ±20% (all others held constant)
3. **Re-run**: Execute the full pipeline with the perturbed threshold
4. **Measure delta**: `Δ = perturbed_score - baseline_score` per family
5. **Classify**:
   - |Δ| < 5 points → **STABLE** — threshold is robust, exact value doesn't matter much
   - 5 ≤ |Δ| < 15 points → **MODERATE** — threshold matters somewhat, current value reasonable
   - |Δ| ≥ 15 points → **SENSITIVE** — threshold is fragile, investigate further

### Why This Matters

If a threshold is classified as SENSITIVE, it means the pipeline's output depends heavily on the exact value chosen — which would undermine the claim of robust signal evaluation. Conversely, STABLE thresholds confirm that the pipeline produces consistent results across a reasonable range of parameter choices.

### Rationale for Specific Values

| Threshold | Value | Justification |
|-----------|-------|---------------|
| `min_fraction_positive` | 0.40 | At 40%, a signal must work in at least 2 of 5 windows. Below 0.30, random noise passes. Above 0.50, too many genuine signals are eliminated. 0.40 balances false positives vs false negatives. |
| `min_competitive_score` | 0.25 | A reliability score of 0.25 corresponds to roughly: Sharpe ≈ 0 + moderate stability + moderate consistency. Below this, the signal is barely distinguishable from noise. |
| `competitive_percentile` | 0.40 | Keep top 60%. This removes the bottom 40% — weak-but-viable signals that would dilute the ensemble. More aggressive (keep 40%) risks losing genuine signals. |
| `max_corr` | 0.85 | At r² = 0.72, two signals share most of their information. More permissive (0.95) allows near-duplicates. More strict (0.70) eliminates signals that are genuinely different but share some structure. |
| `cost_bps` | 33 | Conservative estimate for Moroccan equities (Casablanca Stock Exchange): brokerage ~10-15 bps + spread ~10-20 bps + slippage ~5 bps. The 10 bps engine default is for sensitivity analysis; 33 bps is the realistic cost used in the sensitivity script. |

### Running the Sensitivity Analysis

```bash
python scripts/signal_engine_sensitivity.py --csv path/to/IAM.xlsx --horizon short --cost-bps 33
python scripts/signal_engine_sensitivity.py --horizon medium --lookback-years 10
```

The script loads OHLCV data, runs baseline + all perturbations, and prints a structured report with per-family deltas and STABLE/MODERATE/SENSITIVE classifications.

---

## What the Frontend Shows

The Fiabilité (Reliability) tab in the variant detail page displays:

1. **Large reliability score** (percentage)
2. **Viable / Non-viable** badge
3. **Decomposition card** with 4 progress bars:
   - Sharpe (35%) — score from mean Sharpe
   - Stabilité (30%) — score from % positive windows
   - Consistance (20%) — score from Sharpe std dev
   - Drawdown (15%) — score from mean max DD
4. **OOS metrics grid**: mean/median/std Sharpe, % positive windows, mean max DD
