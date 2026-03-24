# 06 — Layer E: Redundancy Reduction

**File**: `core/quant_core/signal_engine/redundancy.py`

---

## Purpose

Layer E eliminates signal redundancy. If two variants produce nearly identical signal arrays, including both in the ensemble would double-count the same information. Redundancy reduction ensures the ensemble contains diverse, independent signals.

> *"Diversification is the only free lunch in finance."* — Markowitz (1952), applied to signal ensembles

---

## Algorithm: Greedy Signal-Correlation Clustering

```python
def reduce_redundancy(
    survivors: list[VariantRobustnessSummary],
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    max_corr: float = 0.85,
    max_reps: int = 10,
) -> tuple[
    list[VariantRobustnessSummary],   # representatives
    dict[str, tuple[str, float]],     # redundancy_info
    dict[str, dict[str, float]],      # correlation_matrix
]
```

### Steps

1. **Sort** survivors by reliability score (descending) — highest-quality first
2. **Compute signal arrays** for all survivors using `compute_signal_array()`
3. **Compute pairwise Pearson correlations** of signal arrays
4. **Greedy selection**:
   - Start with the highest-reliability variant → first representative
   - For each remaining variant (in reliability order):
     - Compute max |corr| with all already-selected representatives
     - If max |corr| ≤ 0.85 → **accept** (add to representatives)
     - If max |corr| > 0.85 → **reject** (mark as redundant, record which representative it correlates with)
5. **Stop** when 10 representatives selected or all survivors screened

### Pearson Correlation Implementation

```python
def _pearson_corr(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 2:
        return 0.0
    if std(a) == 0 or std(b) == 0:
        return 1.0 if array_equal(a, b) else 0.0
    return corrcoef(a, b)[0, 1]
```

**Edge cases**:
- Constant arrays (e.g., always +1): treated as perfectly correlated if identical, uncorrelated if different
- Short arrays (< 2 elements): return 0.0

---

## Why 0.85?

The threshold `|r| > 0.85` was chosen based on:

1. **Statistical significance**: At 0.85, two signals share ~72% of variance (r² = 0.72). They are effectively measuring the same thing.

2. **Practitioner convention**: López de Prado (2020, Ch. 6) recommends removing features with pairwise correlation > 0.7–0.9. We use 0.85 as a moderate choice.

3. **Economic interpretation**: SMA-20 and SMA-22 produce nearly identical signals (r ≈ 0.95) because they respond to the same trends with a 2-bar delay. Including both adds no information. SMA-20 and SMA-50 are more different (r ≈ 0.60) — they capture different trend timescales.

---

## Why Max 10 Representatives?

The cap of 10 representatives prevents ensemble bloat:

1. **Diminishing returns**: After 5–7 diverse signals, adding more provides minimal variance reduction (Dietterich 2000)
2. **Computational cost**: Each representative requires current-signal computation in Layer F
3. **Interpretability**: Users can inspect 10 signals; 50 would be overwhelming
4. **Frontend display**: The representative grid uses 2–3 columns; 10 cards fit well

---

## Outputs

### Representatives
List of selected `VariantRobustnessSummary` objects, sorted by reliability score (descending).

### Redundancy Info
```python
{
    "sv_eliminated_id": ("sv_correlated_with_id", 0.92),
    ...
}
```
For each eliminated variant: which representative it correlates with, and the correlation value. This allows the frontend to show why a variant was removed.

### Correlation Matrix
```python
{
    "sv_id_1": {"sv_id_1": 1.0, "sv_id_2": 0.45, ...},
    "sv_id_2": {"sv_id_1": 0.45, "sv_id_2": 1.0, ...},
    ...
}
```
Full pairwise correlation matrix for all survivors (not just representatives). Used by the variant detail page for the correlation heatmap.

---

## Frontend Display

### Pipeline Stepper
The "Compétitifs → Représentatifs" step shows:
```
Compétitifs (9) → Représentatifs (5)
                -4
```
Tooltip: "Réduction de redondance : sélection gloutonne par score décroissant. Si la corrélation Pearson |r| > 0.85 avec un variant déjà sélectionné, il est éliminé. Maximum 10 représentatifs."

### Variant Comparison Table
Each eliminated variant shows a status badge:
- **Sélectionné** — representative (green)
- **Redondant** — eliminated by correlation (amber), tooltip shows which representative and r value
- **Éliminé** — didn't survive Layer D (gray)
- **Non-viable** — didn't pass Layer C (red)

### Correlation Matrix (Variant Detail Page)
Heatmap showing pairwise correlations among all survivors. Representatives are highlighted. This visualizes why certain variants were eliminated and confirms that representatives are genuinely diverse.

---

## Example

```
Survivors (9 variants, sorted by reliability):

sv_001  SMA-20   reliability=0.72  → SELECTED (first)
sv_002  SMA-25   reliability=0.68  → REDUNDANT (|r|=0.93 with sv_001)
sv_003  RSI-14   reliability=0.65  → SELECTED (|r|=0.32 with sv_001)
sv_004  SMA-50   reliability=0.61  → SELECTED (|r|=0.58 with sv_001, 0.41 with sv_003)
sv_005  SMA-22   reliability=0.59  → REDUNDANT (|r|=0.91 with sv_001)
sv_006  RSI-10   reliability=0.55  → REDUNDANT (|r|=0.88 with sv_003)
sv_007  SMA-75   reliability=0.52  → SELECTED (|r|=0.72 with sv_004, below threshold)
sv_008  RSI-20   reliability=0.48  → SELECTED (|r|=0.78 with sv_003, below threshold)
sv_009  SMA-30   reliability=0.45  → REDUNDANT (|r|=0.89 with sv_001)

Representatives: [sv_001, sv_003, sv_004, sv_007, sv_008]  (5 variants)
Redundant: [sv_002, sv_005, sv_006, sv_009]
```

The greedy algorithm prefers quality (higher reliability selected first) and diversity (correlated variants eliminated). SMA-20/25/22/30 are all highly correlated trend signals; only the best (SMA-20) survives. RSI-14 and RSI-10 capture the same mean-reversion; only RSI-14 survives.
