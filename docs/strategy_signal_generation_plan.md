# Strategy Page — Signal Generation Layer: Detailed Implementation Plan

**Date:** 2026-03-11
**Scope:** Signal Generation sub-layer of the Strategy page, Technical Analysis section, SMA family first. Architecture must generalise to RSI, MACD, OBV.

---

## 1. Guiding Principle

> **The engine does not randomly choose strategy variants. It defines a disciplined, family-specific search space of economically distinct variants, then uses chronology-respecting out-of-sample optimization and robust filtering to determine the representative subset used in the family speedometer.**

This principle must be respected at every layer — in the code, in the comments, and in the UI explanation shown to users.

---

## 2. Methodological Principle for Variant Definition and Selection

### Why arbitrary manual selection is wrong

Manually hand-picking a few SMA windows (e.g. "let's use 20, 50, 200") and calling them representative is:

- **Not justified**: the selection reflects personal habit, not evidence
- **Overfit-prone**: the analyst has implicitly seen which windows performed well historically
- **Not reproducible**: different analysts would produce different "expert" picks
- **Not explainable** to a trading desk or compliance reviewer

### Why a brute-force dense grid is also wrong

Generating a dense grid (e.g. SMA-1 through SMA-300) and voting across all of them:

- Creates massive redundancy: SMA-50 and SMA-51 are nearly identical in signal; their near-duplicate votes corrupt the ensemble
- Inflates the apparent candidate count with near-duplicates
- Makes the methodology look busy without being informative
- Is sensitive to where the grid boundaries are placed, introducing an implicit choice

### The correct approach: structured search space + OOS optimization

1. **Research design step (done once per family):** Define a small, structured universe of signal *archetypes* — economically distinct rule forms — and a disciplined admissible parameter neighborhood for each archetype, scaled by horizon.

2. **Optimization step (run per stock × horizon):** Evaluate each candidate in the structured universe using chronology-respecting out-of-sample (OOS) validation. This determines which candidates are robust on *this stock, for this horizon*, based on evidence — not assumption.

3. **Selection step:** Apply survivor filtering (viability gate + competitive threshold) and redundancy reduction (signal-correlation clustering) to obtain a small representative subset.

4. **Combination step:** Combine the current normalized signals of retained representatives using reliability-weighted averaging.

The key insight: **search-space design is a research problem** (done analytically, once). **Variant selection is an optimization problem** (solved empirically, per stock × horizon).

---

## 3. Product Structure (UI)

The strategy page must always reflect this structure — regardless of methodology changes underneath.

```
/strategy
├── Left sidebar: stock list (from market catalog)
│     └── Search filter
├── Horizon selector: Court terme | Moyen terme | Long terme
└── Right content: Tabs
    ├── Analyse Technique     ← THIS PLAN
    ├── Analyse Fondamentale  (placeholder: "Bientôt disponible")
    ├── Analyse Quantitative  (placeholder)
    └── Stratégie Personnelle (placeholder)
```

### Technical Analysis drill-down flow

```
Level 0: One large aggregate speedometer
         (aggregate = SMA only for now, honest label "SMA uniquement")
         Click → Level 1

Level 1: Four family speedometers
         [ SMA (live) ] [ RSI (N/A) ] [ MACD (N/A) ] [ OBV (N/A) ]
         Click SMA → Level 2
         Click RSI/MACD/OBV → toast "Bientôt disponible"

Level 2: SMA family drill-down
         ┌──────────────────────────────────────────────────┐
         │ ← Retour    SMA — Analyse de famille    [Méthodologie ↗] │
         │                                                        │
         │  Testés: 12   Viables: 7   Représentatifs: 3          │
         │                                                        │
         │  [Speedometer SMA-20]  [Speedometer SMA-50]  [Speedometer SMA-150] │
         │   BUY  w=0.38           BUY  w=0.35           HOLD  w=0.27         │
         │   Click ↓               Click ↓                Click ↓              │
         └──────────────────────────────────────────────────┘

Level 3: Variant detail (Sheet / drawer, slide-in from right)
         - Signal badge + values
         - Plotly line chart: Close (blue) + SMA-N (orange dashed) + current marker
         - Rule text: "Close 124.5 > SMA-50 118.2 → BUY"
         - Robustness card: mean OOS Sharpe, fraction positive windows, n windows
         - Explanation: "Retenu car: Sharpe moyen OOS = 0.65, stable sur 7/8 fenêtres"
```

### Methodology modal (opened from Level 2)

Static French prose, honest about implementation maturity:

1. **Espace de recherche structuré** — on définit des archétypes de signaux économiquement distincts par famille, avec des voisinages de paramètres admissibles selon l'horizon.
2. **Évaluation OOS chronologique** — chaque candidat est évalué sur des fenêtres de test successives (walk-forward), sans look-ahead.
3. **Score de robustesse** — Sharpe moyen OOS, stabilité inter-fenêtres, drawdown moyen, fraction de fenêtres positives.
4. **Filtre compétitif** — on retient les variantes qui dépassent un seuil absolu de score ET se situent dans le top N% de la distribution.
5. **Réduction de redondance** — regroupement par corrélation des séries de signaux; on garde un représentant par groupe.
6. **Combinaison pondérée** — score famille = moyenne pondérée des signaux courants normalisés, poids = score de robustesse.

**Note de transparence (displayed in modal):** _"Implémentation actuelle: ensemble OOS robuste avec filtre compétitif. Aucun test MCS ou SPA formel n'est appliqué. L'architecture permet d'y ajouter ces tests ultérieurement."_

---

## 4. Family-Specific Candidate Universe Design

### Principle

For each family, we define:
- **Signal archetypes**: economically distinct rule forms (not just parameter variations of one form)
- **Admissible parameter space**: per archetype, a bounded range scaled by horizon
- **Horizon-aware sizing**: short-term stocks need faster indicators; long-term needs slower ones

This structured universe is defined analytically (as code constants in `candidates.py`), not at runtime. It replaces both manual hand-picking and brute-force grids.

---

### 4A. SMA Family

**Archetypes:**

| Archetype ID | Rule Form | Economic Logic |
|---|---|---|
| `price_vs_sma` | `signal = +1 if close > SMA(w)` | Trend filter: price above its own average |
| `sma_cross` | `signal = +1 if SMA(fast) > SMA(slow)` | Momentum: shorter-term average above longer-term |
| `slope_confirmed` | `signal = +1 if close > SMA(w) AND SMA(w)[t] > SMA(w)[t-k]` | Trend + acceleration confirmation |

**Admissible parameter space per horizon:**

| Horizon | `price_vs_sma` windows | `sma_cross` (fast, slow) pairs | `slope_confirmed` (w, lookback) |
|---|---|---|---|
| Court (3mo) | [5, 10, 15, 20] | [(5,20), (10,30)] | [(20, 5), (10, 3)] |
| Moyen (6mo) | [20, 30, 50, 75] | [(10,50), (20,100)] | [(50, 10), (30, 7)] |
| Long (12mo) | [50, 100, 150, 200] | [(50,150), (100,250)] | [(100, 20), (150, 30)] |

**Design rationale:**
- Windows are *anchor points* covering distinct timescales within each horizon — not a dense grid
- Crossover pairs are chosen to represent meaningfully different signal frequencies
- `slope_confirmed` introduces a second-order trend confirmation (acceleration), a genuinely distinct archetype
- Total candidates per horizon: ~8–12 (economically justifiable, not redundant)

**Important:** These are the *admissible search space*. Which ones survive is determined by OOS optimization on the specific stock × horizon. The engine may retain 2 out of 12 or 5 out of 12 — depending on the data.

---

### 4B. RSI Family (design for future implementation)

**Archetypes:**

| Archetype ID | Rule Form | Economic Logic |
|---|---|---|
| `level_reversal` | `signal = -1 if RSI(p) > 70; +1 if RSI(p) < 30` | Mean reversion from extremes |
| `persistence` | `signal = +1 if RSI(p) > 55 for last k bars` | Momentum persistence (RSI staying elevated) |
| `reversal_confirmation` | `RSI crosses back from extreme + price momentum aligned` | Avoid premature reversal entries |

**Admissible parameter space:** periods [7, 10, 14, 21] × thresholds [25/75, 30/70, 35/65], filtered by horizon.

---

### 4C. MACD Family (design for future implementation)

**Archetypes:**

| Archetype ID | Rule Form | Economic Logic |
|---|---|---|
| `signal_cross` | MACD line crosses signal line | Classic momentum crossover |
| `histogram_momentum` | MACD histogram sign + magnitude threshold | Acceleration of momentum |
| `zero_line_context` | MACD cross filtered by zero-line position | Trend-contextual momentum |

**Admissible parameter space:** canonical (fast, slow, signal) triplets anchored at (12,26,9) and neighbourhood variants scaled by horizon.

---

### 4D. OBV Family (design for future implementation)

**Archetypes:**

| Archetype ID | Rule Form | Economic Logic |
|---|---|---|
| `trend_confirmation` | OBV above its own SMA | Volume trend confirms price direction |
| `breakout` | OBV exceeds rolling max, price also breaking | Volume-confirmed breakout |
| `divergence` | Price rising but OBV falling (or vice versa) | Warning signal: divergence |

---

## 5. Backend Architecture

### Overview: Seven Layers (A → G) + API Layer (H)

```
A  Candidate universe generation   (candidates.py)
B  OOS evaluation                  (oos_eval.py)
C  Robustness scoring              (robustness.py)
D  Survivor filtering              (survivor.py)
E  Redundancy reduction            (redundancy.py)
F  Current signal computation      (current_signal.py)
G  Ensemble combination            (ensemble.py)
H  API outputs                     (strategy_signals.py)
```

New package location: `core/quant_core/signal_engine/`

---

### Layer A — Candidate Universe Generation (`candidates.py`)

```python
# The structured universe is defined as code constants — not computed at runtime.
# Parameters represent search-space anchors for each archetype × horizon.
# Which variants survive is determined by OOS evaluation (Layer B), not by this layer.

def generate_sma_candidates(horizon: str) -> list[VariantDef]:
    """
    Returns the admissible candidate universe for the SMA family.
    Covers 3 archetypes × horizon-scaled parameter neighborhoods.
    Typically 8-12 candidates per horizon.
    Each candidate gets a deterministic variant_id via compute_trial_id().
    """
```

No random selection. No brute-force grid. The function is deterministic and auditable.

---

### Layer B — OOS Evaluation (`oos_eval.py`)

```python
def evaluate_variant_oos(
    close: pd.Series,
    variant: VariantDef,
    *,
    horizon: str = "medium",
    cost_bps: float = 10.0,
) -> list[OOSWindowResult]:
    """
    Chronology-respecting rolling walk-forward evaluation.

    For each step (no look-ahead; test always follows train):
      - Train window: compute indicator in-sample
      - Test window: apply rule, compute bar-by-bar returns net of costs
      - Collect OOS metrics: Sharpe, max_drawdown, win_rate, n_trades, n_bars

    Window sizes by horizon:
      Court:  train=252 bars, test=63 bars,  step=21 bars
      Moyen:  train=504 bars, test=126 bars, step=42 bars
      Long:   train=756 bars, test=252 bars, step=63 bars

    Signal rule (for SMA price_vs_sma archetype):
      signal[t] = +1 if close[t] > sma_w[t] else -1
    Bar return (when position held):
      r[t] = signal[t] * (close[t+1] / close[t] - 1) - cost_bps/10000 * |signal[t] - signal[t-1]|

    Minimum required: at least 3 valid OOS windows (else returns empty list).
    """
```

**Reuses:** `sharpe_ratio()` from `core.quant_core.significance`

---

### Layer C — Robustness Scoring (`robustness.py`)

```python
def score_variant_robustness(
    oos_results: list[OOSWindowResult],
    *,
    min_windows: int = 3,
) -> VariantRobustnessSummary:
    """
    Reliability score = transparent weighted combination of OOS quality metrics.

    Component scores (each normalized to [0, 1]):
      sharpe_score     = clamp( (mean_sharpe - (-0.5)) / (1.5 - (-0.5)) )   weight=0.35
      stability_score  = fraction_positive_windows                            weight=0.30
      consistency_score = clamp( 1 - std_sharpe / (|mean_sharpe| + 0.1) )   weight=0.20
      drawdown_score   = clamp( 1 - mean_max_drawdown / 0.30 )               weight=0.15

    Viability gate (hard floor — if not met, reliability_score = 0.0):
      - n_valid_windows >= min_windows
      - fraction_positive_windows >= 0.40

    Final score: clamp(weighted_sum, 0.0, 1.0)

    This scoring is transparent, bounded, monotonic in quality,
    and avoids over-sensitivity to one spectacular OOS window.
    It is a pragmatic robustness score — not a formal statistical test.
    """
```

---

### Layer D — Survivor Filtering (`survivor.py`)

```python
def filter_survivors(
    summaries: list[VariantRobustnessSummary],
    *,
    competitive_percentile: float = 0.40,
    min_competitive_score: float = 0.25,
) -> list[VariantRobustnessSummary]:
    """
    Two-stage filter (named accurately — NOT formal MCS or SPA):

    Stage 1 — Viability gate:
      Keep only variants where is_viable = True (set by robustness.py)

    Stage 2 — Competitive filter:
      Keep variants where:
        reliability_score >= min_competitive_score  (absolute floor)
        AND percentile rank of reliability_score >= competitive_percentile

    This retains variants that are both absolutely competitive
    and relatively competitive within the candidate pool.

    methodology_label = "competitive_oos_filter"  (not "MCS")
    The architecture allows plugging in a formal SPA/MCS test later.
    """
```

---

### Layer E — Redundancy Reduction (`redundancy.py`)

```python
def reduce_redundancy(
    survivors: list[VariantRobustnessSummary],
    close: pd.Series,
    *,
    max_signal_correlation: float = 0.85,
    max_representatives: int = 6,
) -> list[VariantRobustnessSummary]:
    """
    Correlation-based greedy clustering on OOS signal series.

    1. Compute full-history signal series for each survivor:
         signal_series[t] = +1 if close[t] > sma_w[t] else -1
    2. Sort survivors by reliability_score descending
    3. Greedy selection:
         - Start with the best survivor (highest reliability)
         - For each remaining: keep only if
             max(|Pearson correlation| with any already-kept) <= max_signal_correlation
    4. Cap at max_representatives

    Result: a small set of variants that are both high-quality (reliability)
    and genuinely distinct (low mutual correlation) — a representative subset.

    This is signal-level redundancy reduction, not parameter-distance filtering.
    """
```

---

### Layer F — Current Signal (`current_signal.py`)

```python
def compute_current_signal(
    close: pd.Series,
    variant: VariantDef,
    reliability_weight: float,
) -> VariantCurrentSignal:
    """
    Compute the latest directional signal for a single variant.

    signal = +1.0 if close[-1] > indicator[-1]
           = -1.0 if close[-1] < indicator[-1]
           =  0.0 if equal or insufficient data

    Also computes human-readable explanation:
      "Close 124.5 > SMA-50 118.2 → BUY"

    The signal is kept binary (+1/-1/0) for interpretability.
    Grading comes from the reliability weight, not from signal magnitude.
    """
```

---

### Layer G — Ensemble Combination (`ensemble.py`)

```python
def combine_family_signals(
    representatives: list[VariantRobustnessSummary],
    current_signals: dict[str, VariantCurrentSignal],
) -> tuple[float, list[dict]]:
    """
    Weighted combination formula:

      family_score_raw = sum(w_i * s_i) / sum(w_i)
      family_score_pct = 100.0 * family_score_raw

    where:
      w_i = reliability_weight (from Layer C)
      s_i = current normalized signal (from Layer F), in {-1.0, 0.0, +1.0}

    Also computes per-variant:
      normalized_weight_i     = w_i / sum(w_j)
      weighted_contribution_i = normalized_weight_i * s_i

    These are exposed in the API response for UI drill-down.

    Note: the speedometer/gauge is a PRESENTATION object — it maps
    family_score_pct ∈ [-100, +100] to a needle angle.
    The optimization object is the reliability_weight derived from OOS evaluation.
    """

def run_sma_ensemble(
    close: pd.Series,
    *,
    symbol: str,
    horizon: str = "medium",
    timeframe: str = "1D",
    cost_bps: float = 10.0,
) -> FamilyCombinedSignal:
    """
    Full pipeline entry point: A → B → C → D → E → F → G.
    Called by the API layer.
    """
```

---

### Domain Objects (`domain.py`)

```python
@dataclass(frozen=True)
class VariantDef:
    variant_id: str      # deterministic: compute_trial_id(family, params)
    family: str          # "sma" | "rsi" | "macd" | "obv"
    archetype: str       # "price_vs_sma" | "sma_cross" | "slope_confirmed" | ...
    params: dict         # {"window": 50} or {"fast": 20, "slow": 100}
    description: str     # "SMA-50 Price-Cross (Moyen terme)"

@dataclass
class OOSWindowResult:
    window_index: int
    train_start: str; train_end: str
    test_start: str;  test_end: str
    n_trades: int
    mean_return_net: float    # net of costs, per bar
    sharpe: float
    max_drawdown: float
    fraction_positive_bars: float
    n_bars: int
    is_valid: bool

@dataclass
class VariantRobustnessSummary:
    variant: VariantDef
    n_oos_windows: int; n_valid_windows: int
    mean_sharpe: float; std_sharpe: float
    median_sharpe: float; fraction_positive_windows: float
    mean_max_drawdown: float
    reliability_score: float   # [0, 1]
    is_viable: bool

@dataclass
class VariantCurrentSignal:
    variant_id: str
    signal: float              # +1.0 | -1.0 | 0.0
    signal_label: str          # "BUY" | "SELL" | "HOLD"
    reliability_weight: float
    current_close: float
    indicator_value: float | None
    explanation: str           # "Close 124.5 > SMA-50 118.2 → BUY"

@dataclass
class FamilyCombinedSignal:
    family: str; symbol: str; horizon: str; timeframe: str
    family_score_pct: float      # -100 to +100
    family_signal_label: str
    tested_count: int
    viable_count: int
    competitive_count: int
    representative_count: int
    representatives: list[dict]  # merged VariantRobustnessSummary + VariantCurrentSignal
    score_explanation: str       # human-readable: "3 variants retained: SMA-20 BUY, SMA-50 BUY, SMA-150 HOLD"
    methodology_status: str      # "robust_oos_ensemble" | "provisional"
    as_of: str
```

---

### Layer H — API (`strategy_signals.py`)

**Endpoint 1: SMA ensemble**
```
POST /strategy/signal/sma-ensemble
Body: { "symbol": "AAA", "horizon": "medium", "timeframe": "1D" }
```
Calls `run_sma_ensemble()`. Returns full `FamilyCombinedSignal`.

**Endpoint 2: Price history + SMA overlay**
```
GET /strategy/signal/price-history/{symbol}
Query: window=50, limit=200, timeframe=1D
```
Response: `{ symbol, window, timeframe, current_close, current_sma, current_signal, series: [{date, close, sma}, ...] }`
Used for the Level 3 Plotly line chart.

---

### Shared data loading: `services/api/app/market_data_utils.py`

Extract from `market_data.py` (no logic change — refactor only):
- `_load_close_series_from_store(object_key)`
- `_load_close_series_from_dataset(dataset_row, symbol)`
- `_find_latest_dataset_for_symbol(db, symbol)`
- `_dataset_object_key(dataset_row)`
- `_dataset_has_symbol(dataset_row, symbol)`
- `_normalize_symbols(raw)` / `_normalize_windows(raw)`

Both `market_data.py` and `strategy_signals.py` import from here.

---

## 6. Speedometer: Presentation Object, Not Optimization Object

The speedometer gauge is explicitly a UI presentation component. Its needle angle is derived from `family_score_pct`, which is itself derived from the weighted combination of current signals (Layer G). The optimization happens entirely in Layers A–F. The UI must never be confused with the model.

```
OOS optimization  →  reliability weights  →  weighted combination  →  family_score_pct  →  needle angle
(Layers A-C)          (Layer C output)        (Layer G)                 (Layer G output)    (UI only)
```

---

## 7. What Is Rigorous vs Provisional

| Aspect | Status | Notes |
|---|---|---|
| Structured search space (archetypes + admissible params) | **Rigorous** | Analytically designed, auditable |
| Chronology-respecting OOS evaluation | **Rigorous** | No look-ahead, rolling walk-forward |
| Robustness scoring (multi-component) | **Pragmatic** | Transparent weights; not a formal test |
| Survivor filtering | **Pragmatic** | Competitive percentile filter; not formal SPA/MCS |
| Redundancy reduction (signal correlation) | **Rigorous** | Well-defined greedy clustering algorithm |
| Weighted ensemble combination | **Rigorous** | Standard forecast combination theory |
| Formal SPA (White Reality Check) | **Not implemented** | Architecture allows future plug-in |
| Formal MCS (Hansen-Lunde-Nason) | **Not implemented** | Architecture allows future plug-in |

---

## 8. Files to Create

| File | Purpose |
|---|---|
| `core/quant_core/signal_engine/__init__.py` | Package marker |
| `core/quant_core/signal_engine/domain.py` | All dataclasses |
| `core/quant_core/signal_engine/candidates.py` | Layer A: structured candidate universe |
| `core/quant_core/signal_engine/oos_eval.py` | Layer B: rolling OOS evaluation |
| `core/quant_core/signal_engine/robustness.py` | Layer C: reliability scoring |
| `core/quant_core/signal_engine/survivor.py` | Layer D: survivor filtering |
| `core/quant_core/signal_engine/redundancy.py` | Layer E: redundancy reduction |
| `core/quant_core/signal_engine/current_signal.py` | Layer F: current bar signal |
| `core/quant_core/signal_engine/ensemble.py` | Layer G: combination + pipeline |
| `services/api/app/market_data_utils.py` | Shared data loading helpers |
| `services/api/app/routers/strategy_signals.py` | New API router (2 endpoints) |
| `services/api/app/schemas/strategy_signals.py` | Pydantic output schemas |
| `core/tests/test_signal_engine.py` | 10+ unit tests |
| `app/strategy/page.tsx` | Frontend: strategy page |
| `components/strategy/speedometer.tsx` | Frontend: SVG gauge component |
| `components/strategy/technical-analysis-panel.tsx` | Frontend: drill-down orchestrator |
| `components/strategy/sma-drill-down.tsx` | Frontend: Level 2+3 SMA detail |
| `components/strategy/methodology-modal.tsx` | Frontend: methodology explanation |
| `docs/strategy_signal_generation_plan.md` | This document |

## 9. Files to Modify

| File | Change |
|---|---|
| `services/api/app/routers/market_data.py` | Import helpers from `market_data_utils` (refactor only) |
| `services/api/app/main.py` | Register `strategy_signals` router |
| `components/app-header.tsx` | Add `{ href: "/strategy", label: "Stratégie", icon: TrendingUp }` |
| `lib/api.ts` | Add `SmaEnsembleResponseSchema`, `fetchSmaEnsemble()`, `PriceHistoryResponseSchema`, `fetchPriceHistory()` |

---

## 10. Existing Code Reused

| Utility | Location | Purpose |
|---|---|---|
| `compute_trial_id(family, params)` | `core/quant_core/wfo_utils.py` | Deterministic variant_id hashing |
| `sharpe_ratio(returns)` | `core/quant_core/significance.py` | OOS Sharpe per window in Layer B |
| `_load_close_series_from_store()` | `market_data.py` → `market_data_utils.py` | Price series loading |
| `_find_latest_dataset_for_symbol()` | same | Fallback to uploaded datasets |
| `PlotlyChart` | `components/run/plotly-chart.tsx` | Level 3 price + SMA line chart |
| `SignalBadge` | `components/signal-badge.tsx` | Signal labels |
| `signalType()`, `signalLabel()` | `lib/format.ts` | Signal type → CSS / label |
| `useMarketCatalog()` | `hooks/use-api.ts` | Sidebar stock list |
| shadcn/ui primitives | `components/ui/` | `Tabs`, `Sheet`, `Dialog`, `Card`, `Badge`, `Skeleton`, `Tooltip` |

---

## 11. Tests (`core/tests/test_signal_engine.py`)

1. `test_reliability_score_bounds` — always in [0, 1]
2. `test_reliability_score_monotone` — higher Sharpe + stability → higher score
3. `test_viability_gate` — fraction_positive < 0.4 → score = 0, is_viable = False
4. `test_family_score_formula` — weighted mean numerically exact
5. `test_redundancy_identical_variants` — 5 identical SMA-50 variants → keep 1
6. `test_redundancy_distinct_variants` — 3 uncorrelated variants → keep all 3
7. `test_edge_no_viable_variants` — returns methodology_status="provisional", score=0
8. `test_edge_single_survivor` — normalized_weight = 1.0, works correctly
9. `test_edge_all_neutral_signals` — family_score_pct = 0.0
10. `test_edge_insufficient_history` — fewer bars than required → graceful return, no crash
11. `test_candidate_universe_horizons` — each horizon returns non-empty, deduplicated candidates
12. `test_oos_chronology_respected` — no future bar used in any test window

---

## 12. Verification Checklist

1. `python -m pytest core/tests/test_signal_engine.py -v` — all 12 tests pass
2. `npx tsc --noEmit` — zero TypeScript errors
3. Navigate `/strategy` → stock list loads from catalog
4. Select stock + horizon → big speedometer renders with live SMA ensemble score
5. Click aggregate → 4 family gauges; SMA is live, others show "N/A / Bientôt disponible"
6. Click SMA family gauge → drill-down grid shows representative speedometers with counts (Testés / Viables / Représentatifs)
7. Click "Méthodologie" → modal opens with honest methodology prose + transparency note
8. Click a representative speedometer → Sheet opens, price history loads, Plotly line chart renders (close blue + SMA orange)
9. Back navigation works at each level (Level 2 → Level 1 → Level 0)
10. Edge: stock with no data → methodology_status="provisional", all scores = 0, UI shows graceful empty state
