# 05 — Layer D: Survivor Filtering

**File**: `core/quant_core/signal_engine/survivor.py` (referenced in `ensemble.py` pipeline)

---

## Purpose

Layer D reduces the candidate pool from "all scored variants" to "competitive survivors" using a two-stage filter. This is where the pipeline eliminates noise — variants that passed the viability gate but don't rank well enough to contribute to the ensemble.

---

## Two-Stage Filter

```python
def filter_survivors(
    summaries: list[VariantRobustnessSummary],
    *,
    competitive_percentile: float = 0.40,
    min_competitive_score: float = 0.25,
) -> list[VariantRobustnessSummary]
```

### Stage 1: Viability Gate

Keep only variants with `is_viable = True`.

This removes variants that already failed in Layer C (fewer than 3 valid windows or fewer than 40% positive Sharpe windows). In practice, this eliminates 30–70% of candidates.

### Stage 2a: Absolute Floor

Keep only variants with `reliability_score >= 0.25`.

**Rationale**: A reliability score of 0.25 is very low — it means the variant barely performs above random. Setting this as a hard floor prevents extremely weak signals from entering the ensemble, even if they happen to be in the "top 60%" of a weak cohort.

If no variant passes this floor, the pipeline returns an empty list → neutral signal.

### Stage 2b: Competitive Percentile

Sort remaining variants by reliability score (descending). Keep the top `(1 - competitive_percentile)` fraction.

**Default**: `competitive_percentile = 0.40` → keep top 60%.

**Minimum**: Always keep at least 1 variant.

### Example

```
30 candidates generated (Layer A)
→ 18 viable (passed viability gate in Layer C)
→ 15 above 0.25 floor (Stage 2a)
→ 9 kept (top 60% of 15, Stage 2b)
→ 9 survivors proceed to Layer E
```

---

## Why Two Stages?

**The absolute floor (Stage 2a)** prevents "best of a bad lot" selection. If all 30 candidates perform poorly (e.g., on a symbol with no trend), the floor ensures we don't pick the least-bad ones and present them as viable signals.

**The percentile filter (Stage 2b)** provides relative ranking within the cohort. Among strong candidates, we still want to keep only the better half — this reduces redundancy and computational cost in Layer E.

Together, these ensure:
- No variant enters the ensemble without meeting a minimum quality standard
- The ensemble is composed of the better-performing subset
- The filter adapts to cohort strength (strict when many are strong, lenient when few pass)

---

## Frontend Display

The pipeline stepper component shows this layer as "Viables → Compétitifs":

```
Testées (30) → Viables (18) → Compétitifs (9) → Représentatifs (5)
             -12              -9                -4
```

The tooltip text explains:
> "Filtre percentile : seul le top 60% par score de fiabilité sont gardés. Score minimum absolu : 0.25."

---

## Edge Cases

| Scenario | Result |
|----------|--------|
| 0 viable variants | Empty list → neutral signal |
| All viable below 0.25 | Empty list → neutral signal |
| Only 1 viable above 0.25 | That 1 variant survives |
| 2 viable above 0.25 | Top 60% of 2 = at least 1 survives |
