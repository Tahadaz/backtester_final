# Signal Generation — Candidate Universe Design

**Reference:** `docs/strategy_signal_generation_plan.md` (Sections 2, 4)
**Planned implementation:** `core/quant_core/signal_engine/candidates.py`

The candidate universe defines *what the optimization searches over*. This is a research design problem — arguably the most important step in the signal generation pipeline, because no amount of OOS validation can rescue a poorly designed search space.

---

## Why Search Space Design Matters

### The two failure modes

**Failure mode 1: Hand-picking ("expert" selection)**
```
Analyst: "Let's use SMA-20, SMA-50, and SMA-200. These are standard."
```

Problems:
- **Not justified** — the selection reflects personal habit, not evidence
- **Implicitly overfit** — the analyst has seen which windows performed well historically (in papers, in experience)
- **Not reproducible** — different analysts produce different "standard" picks
- **Not auditable** — a compliance reviewer cannot verify the selection process

**Failure mode 2: Dense grid ("brute force")**
```
Search: SMA-1, SMA-2, SMA-3, ..., SMA-300
```

Problems:
- **Massive redundancy** — SMA-50 and SMA-51 produce nearly identical signals (correlation > 0.99)
- **Inflated candidate count** — 300 candidates when perhaps 10 are genuinely distinct
- **Multiple testing penalty** — more candidates → higher probability of spurious "winners"
- **Boundary sensitivity** — results depend on where the grid starts and stops

### The correct approach: structured archetypes

Define a small set of **economically distinct signal archetypes** — different decision rules, not just different parameters — and a **bounded parameter neighborhood** for each, scaled by investment horizon.

This is a research design choice, made once per signal family, documented and auditable.

**References:**
- López de Prado, M. (2020). *Machine Learning for Asset Managers*. Cambridge. Chapter 4: "Optimal Clustering."
- Harvey, C.R., Liu, Y., Zhu, H. (2016). "... and the Cross-Section of Expected Returns." *Review of Financial Studies*, 29(1), 5–68. — Shows that most of 316 published factors are false discoveries.

---

## Archetype Concept

An **archetype** is an economically distinct rule form within a signal family. Two signals belong to different archetypes if they express fundamentally different market hypotheses, even within the same indicator family.

### Example: SMA family has 3 archetypes

| Archetype | Rule Form | Economic Hypothesis |
|-----------|-----------|-------------------|
| `price_vs_sma` | `signal = +1 if Close > SMA(w)` | **Trend filter:** price above its average implies upward drift |
| `sma_cross` | `signal = +1 if SMA(fast) > SMA(slow)` | **Momentum:** short-term trend exceeding long-term trend |
| `slope_confirmed` | `signal = +1 if Close > SMA(w) AND SMA(w)[t] > SMA(w)[t-k]` | **Trend + acceleration:** not just above average, but average itself is rising |

These are *genuinely different hypotheses*:
- `price_vs_sma` asks: "Is the price above its mean?"
- `sma_cross` asks: "Is the short-term mean rising faster than the long-term mean?"
- `slope_confirmed` asks: "Is the price above a rising mean?" (conjunction of two conditions)

A dense grid of SMA windows within a single archetype is redundancy. Multiple archetypes within a family is diversity.

---

## Horizon-Aware Parameter Neighborhoods

Parameters are scaled by investment horizon because the appropriate indicator timescale depends on the holding period:

- **Short-term (Court terme, ~3 months):** Fast indicators (5–20 bar windows) capture short-lived momentum
- **Medium-term (Moyen terme, ~6 months):** Medium indicators (20–100 bar windows) capture intermediate trends
- **Long-term (Long terme, ~12 months):** Slow indicators (50–250 bar windows) capture secular trends

### SMA Family — Parameter Space

#### `price_vs_sma` archetype

| Horizon | Admissible Windows | Count | Rationale |
|---------|-------------------|-------|-----------|
| Court | [5, 10, 15, 20] | 4 | Short-term momentum indicators |
| Moyen | [20, 30, 50, 75] | 4 | Intermediate trend filters |
| Long | [50, 100, 150, 200] | 4 | Long-term secular trend |

#### `sma_cross` archetype

| Horizon | (fast, slow) Pairs | Count | Rationale |
|---------|--------------------|-------|-----------|
| Court | [(5, 20), (10, 30)] | 2 | Fast crossovers for short-term momentum |
| Moyen | [(10, 50), (20, 100)] | 2 | Standard dual-MA trend following |
| Long | [(50, 150), (100, 250)] | 2 | Long-cycle momentum detection |

#### `slope_confirmed` archetype

| Horizon | (window, lookback) | Count | Rationale |
|---------|-------------------|-------|-----------|
| Court | [(20, 5), (10, 3)] | 2 | Short-term trend + acceleration |
| Moyen | [(50, 10), (30, 7)] | 2 | Medium-term acceleration confirmation |
| Long | [(100, 20), (150, 30)] | 2 | Long-term acceleration filter |

**Total per horizon: 8–12 candidates.** Enough to cover the economically meaningful parameter space without redundancy.

---

## RSI Family — Archetype Design (Planned)

| Archetype | Rule Form | Economic Hypothesis |
|-----------|-----------|-------------------|
| `level_reversal` | `+1 if RSI < low; -1 if RSI > high` | Mean reversion from statistical extremes |
| `persistence` | `+1 if RSI > 55 for k consecutive bars` | Momentum persistence — sustained strength implies continuation |
| `reversal_confirmation` | `+1 if RSI crosses back from extreme AND price aligned` | Avoid premature reversal entries |

**Parameter space:** Periods [7, 10, 14, 21] × Thresholds [25/75, 30/70, 35/65], filtered by horizon.

**Design note:** The `persistence` archetype is genuinely different from `level_reversal` — it measures *duration* of an RSI condition, not just its level. This captures a different market dynamic (sustained momentum vs extreme reversal).

---

## MACD Family — Archetype Design (Planned)

| Archetype | Rule Form | Economic Hypothesis |
|-----------|-----------|-------------------|
| `signal_cross` | MACD line crosses signal line | Classic momentum timing via crossover |
| `histogram_momentum` | MACD histogram sign + magnitude > threshold | Acceleration of momentum (second derivative) |
| `zero_line_context` | MACD cross filtered by position relative to zero line | Trend-contextual momentum: bullish crosses above zero are stronger |

**Parameter space:** Canonical triplets anchored at (12, 26, 9) with neighborhood variants scaled by horizon.

---

## OBV Family — Archetype Design (Planned)

| Archetype | Rule Form | Economic Hypothesis |
|-----------|-----------|-------------------|
| `trend_confirmation` | `+1 if OBV > SMA(OBV, span)` | Volume trend confirms price direction |
| `breakout` | `+1 if OBV > rolling_max(OBV, window) AND price breaking` | Volume-confirmed price breakout |
| `divergence` | Price rising but OBV falling → warning | Informed distribution despite price strength |

---

## Candidate Generation as Code

The candidate universe is defined as **code constants**, not computed at runtime. This makes the search space:
- **Deterministic** — same input → same candidates every time
- **Auditable** — a reviewer can read the code and verify the rationale
- **Versioned** — changes to the search space are tracked in git

```python
# Planned: core/quant_core/signal_engine/candidates.py

def generate_sma_candidates(horizon: str) -> list[VariantDef]:
    """
    Returns the admissible candidate universe for the SMA family.
    Covers 3 archetypes × horizon-scaled parameter neighborhoods.
    Typically 8-12 candidates per horizon.
    Each candidate gets a deterministic variant_id via compute_trial_id().
    """
    # No random selection. No brute-force grid.
    # The function is deterministic and auditable.
```

### `VariantDef` dataclass

```python
@dataclass(frozen=True)
class VariantDef:
    variant_id: str      # Deterministic hash: compute_trial_id(family, params)
    family: str          # "sma" | "rsi" | "macd" | "obv"
    archetype: str       # "price_vs_sma" | "sma_cross" | "slope_confirmed" | ...
    params: dict         # {"window": 50} or {"fast": 20, "slow": 100}
    description: str     # "SMA-50 Price-Cross (Moyen terme)"
```

The `variant_id` is a deterministic hash of `(family, archetype, params)`, ensuring that the same logical variant always has the same ID across runs.

---

## Interaction with Optimization Engine

The candidate universe feeds into the optimization engine (see [06-optimization-engine.md](./06-optimization-engine.md)) in two ways:

### Current implementation (WFO optimizer)

The WFO optimizer uses `ParamDef` ranges and generates candidates via grid or random search. The search space is defined by the parameter ranges in the `ParamDef` catalog:

```
ParamDef → _iter_grid() or _iter_random() → candidate_params → _eval_one_trial()
```

### Planned implementation (signal engine)

The signal engine uses structured archetypes instead of parameter ranges:

```
generate_sma_candidates(horizon) → VariantDef list → evaluate_variant_oos() → score_variant_robustness()
```

The key difference: the WFO optimizer searches a continuous parameter space; the signal engine evaluates a discrete, curated set of archetype instances. Both use OOS validation, but the signal engine's search space is designed to minimize redundancy by construction.

---

## Quality Properties of a Good Candidate Universe

A well-designed candidate universe satisfies:

1. **Coverage:** Every economically distinct signal mechanism in the family is represented by at least one archetype
2. **Diversity:** Archetypes within a family test genuinely different hypotheses, not parameter variations of one hypothesis
3. **Bounded size:** Total candidates per family × horizon is O(10), not O(100) or O(1000)
4. **Horizon coherence:** Parameter scales match the investment horizon — no 5-day SMA in a long-term universe
5. **Determinism:** Given a (family, horizon) pair, the candidate set is always the same
6. **Auditability:** Every candidate can be traced to an economic rationale documented in code

---

## References

- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapter 8: "Feature Importance."
- López de Prado, M. (2020). *Machine Learning for Asset Managers*. Cambridge. Chapter 4: "Optimal Clustering."
- Harvey, C.R., Liu, Y., Zhu, H. (2016). "... and the Cross-Section of Expected Returns." *Review of Financial Studies*, 29(1), 5–68.
- Bailey, D.H., Borwein, J.M., López de Prado, M., Zhu, Q.J. (2014). "Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance." *Notices of the AMS*, 61(5), 458–471.
- Faber, M. (2007). "A Quantitative Approach to Tactical Asset Allocation." *Journal of Wealth Management*, 9(4), 69–79.
