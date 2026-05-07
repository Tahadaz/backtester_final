# 07 — Layers F+G: Current Signal & Ensemble

**Files**: `core/quant_core/signal_engine/current_signal.py` (Layer F), `core/quant_core/signal_engine/ensemble.py` (Layer G)

---

## Layer F: Current Signal Computation

### Purpose

Layer F computes the live signal for each representative at the current (latest) bar. This is what the user sees — "right now, what does this variant say?"

```python
def compute_current_signals(
    representatives: list[VariantRobustnessSummary],
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
) -> list[VariantCurrentSignal]
```

### Per-Representative Processing

For each representative:

1. **Compute signal array** — same function as Layer B (`compute_signal_array`)
2. **Extract latest signal** — `signal_value = sig_arr[-1]` (last bar)
3. **Compute indicator value** — the raw indicator at the last bar (e.g., SMA value, RSI level)
4. **Assign label** — via `variant_signal_label(family, signal_value)`
5. **Build explanation** — human-readable text explaining why the signal fires

### Type-Specific Labels

```python
def variant_signal_label(family: str, signal_value: float) -> str
```

| Signal Type | Families | Signal = +1 | Signal = -1 | Signal = 0 |
|------------|---------|------------|------------|-----------|
| `trend` | SMA, EMA, EMA Cross, Ichimoku, PSAR | HAUSSIER | BAISSIER | NEUTRE |
| `momentum` | MACD, ROC, TRIX, ADX, TSI | MOMENTUM HAUSSIER | MOMENTUM BAISSIER | NEUTRE |
| `oscillator` | RSI, Stochastic, CCI, MFI, UO | SURVENDU | SURACHETÉ | NORMAL |
| `volume` | OBV, CMF, A/D, VWAP, Force Index | ACCUMULATION | DISTRIBUTION | NEUTRE |

**Design rationale**: Labels match the economic interpretation of each category:
- Trend signals: bullish/bearish direction
- Momentum signals: speed/force of price movement
- Oscillators: overbought/oversold extremes
- Volume: accumulation/distribution pressure

### VariantCurrentSignal Dataclass

```python
@dataclass
class VariantCurrentSignal:
    variant_id: str
    signal: float              # +1.0, -1.0, or 0.0
    signal_label: str          # "HAUSSIER", "SURVENDU", etc.
    reliability_weight: float  # from VariantRobustnessSummary.reliability_score
    current_close: float       # latest bar close
    indicator_value: float | None  # raw indicator at last bar
    explanation: str           # human-readable justification
```

---

## Layer G: Ensemble Combination

### Purpose

Layer G combines all representative signals into a single family score. This is the final output: a number from -100 to +100 representing the consensus view.

### Reliability-Weighted Averaging

```python
def combine_family_signals(
    signals: list[VariantCurrentSignal],
    family: str | None = None,
) -> tuple[float, str, list[dict]]
```

**Formula**:

```
score_raw = Σ(signal_i × reliability_weight_i) / Σ(reliability_weight_i)
score_pct = 100.0 × score_raw    # [-100, +100]
```

**Example**:
```
SMA-20:  signal=+1, weight=0.72  → contributes +0.72
SMA-50:  signal=+1, weight=0.61  → contributes +0.61
SMA-75:  signal=-1, weight=0.52  → contributes -0.52
RSI-14:  signal=+1, weight=0.65  → contributes +0.65
RSI-20:  signal= 0, weight=0.48  → contributes  0.00

score_raw = (0.72 + 0.61 - 0.52 + 0.65 + 0.00) / (0.72 + 0.61 + 0.52 + 0.65 + 0.48)
          = 1.46 / 2.98 = 0.490

score_pct = 49.0%
```

**Why reliability-weighted?** A variant with reliability 0.72 has more predictive power than one with 0.48. Weighting by reliability ensures that higher-quality signals have more influence on the consensus.

### Family-Specific Score Labels

```python
def signal_type_label(score_pct: float, signal_type: str | None) -> str
```

**Trend (SMA, EMA, EMA Cross, Ichimoku, PSAR)**:

| Score Range | Label |
|-------------|-------|
| > 50 | Très haussier |
| 15 to 50 | Haussier |
| -15 to 15 | Neutre |
| -50 to -15 | Baissier |
| < -50 | Très baissier |

**Momentum (MACD, ROC, TRIX, ADX, TSI)**:

| Score Range | Label |
|-------------|-------|
| > 50 | Fort momentum haussier |
| 15 to 50 | Momentum haussier |
| -15 to 15 | Pas de momentum |
| -50 to -15 | Momentum baissier |
| < -50 | Fort momentum baissier |

**Oscillator (RSI, Stochastic, CCI, MFI, UO)**:

| Score Range | Label |
|-------------|-------|
| > 50 | Très survendu |
| 15 to 50 | Survendu |
| -15 to 15 | Normal |
| -50 to -15 | Suracheté |
| < -50 | Très suracheté |

**Volume (OBV, CMF, A/D, VWAP, Force Index)**:

| Score Range | Label |
|-------------|-------|
| > 50 | Forte accumulation |
| 15 to 50 | Accumulation |
| -15 to 15 | Neutre |
| -50 to -15 | Distribution |
| < -50 | Forte distribution |

**Aggregate (no family / cross-family)**:

| Score Range | Label |
|-------------|-------|
| > 50 | Achat fort |
| 15 to 50 | Achat |
| -15 to 15 | Neutre |
| -50 to -15 | Vente |
| < -50 | Vente forte |

---

## Signal Type Taxonomy

**File**: `core/quant_core/signal_engine/domain.py`

```python
FAMILY_SIGNAL_TYPE = {
    # Tendance
    "sma": "trend", "ema": "trend", "ema_cross": "trend",
    "ichimoku": "trend", "psar": "trend",
    # Momentum
    "macd": "momentum", "roc": "momentum", "trix": "momentum",
    "adx": "momentum", "tsi": "momentum",
    # Oscillation
    "rsi": "oscillator", "stochastic": "oscillator", "cci": "oscillator",
    "mfi": "oscillator", "uo": "oscillator",
    # Volume
    "obv": "volume", "cmf": "volume", "ad": "volume",
    "vwap": "volume", "fi": "volume",
}

CATEGORY_FAMILIES = {
    "tendance": ["sma", "ema", "ema_cross", "ichimoku", "psar"],
    "momentum": ["macd", "roc", "trix", "adx", "tsi"],
    "oscillation": ["rsi", "stochastic", "cci", "mfi", "uo"],
    "volume": ["obv", "cmf", "ad", "vwap", "fi"],
}
```

This taxonomy is used by:
- The frontend to group families into categories (Tendance, Momentum, Oscillation, Volume)
- The label system to produce type-appropriate labels (4 signal types × 5 label levels)
- The batch scores endpoint to compute per-category scores

**Reference**: Murphy (1999) — technical indicators are classified into trend-following (lagging), momentum (speed), oscillators (mean-reverting), and volume-based (confirming).

---

## Full Pipeline Entry Point

```python
def run_family_ensemble_full(
    family: str,
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    symbol: str,
    horizon: str = "medium",
    timeframe: str = "1D",
    cost_bps: float = 10.0,
    cooldown_bars: int = 0,
) -> EnsemblePipelineDetail
```

### Pipeline Execution (A → G)

```
1. Layer A:  candidates = generate_candidates(family, horizon)        → 30 VariantDef
2. Layer B+C: For each candidate:
               oos_windows = evaluate_variant_oos(close, variant, horizon, cost_bps, cooldown_bars, volume)
               summary = score_variant_robustness(variant, oos_windows)
               → 30 VariantRobustnessSummary + OOS window data
3. Layer D:  survivors = filter_survivors(summaries)                   → N survivors
4. Layer E:  representatives, redundancy_info, corr_matrix = reduce_redundancy(survivors, close, volume)
5. Layer F:  current_signals = compute_current_signals(representatives, close, volume)
6. Layer G:  score_pct, label, rep_details = combine_family_signals(current_signals, family)
```

### EnsemblePipelineDetail

```python
@dataclass
class EnsemblePipelineDetail:
    signal: FamilyCombinedSignal         # final ensemble output
    all_summaries: list[VariantRobustnessSummary]  # all 30 candidates
    oos_windows: dict[str, list[OOSWindowResult]]  # per-variant OOS data
    survivor_ids: set[str]               # variants passing Layer D
    representative_ids: set[str]         # variants passing Layer E
    current_signal_labels: dict[str, str]  # label for every candidate
    redundancy_info: dict[str, tuple[str, float]]  # elimination reasons
    correlation_matrix: dict[str, dict[str, float]]  # pairwise correlations
```

### FamilyCombinedSignal

```python
@dataclass
class FamilyCombinedSignal:
    family: str                    # any of the 20 family IDs
    symbol: str
    horizon: str
    timeframe: str
    family_score_pct: float        # [-100, +100]
    family_signal_label: str       # "Haussier", "Survendu", etc.
    tested_count: int              # 30 (always)
    viable_count: int              # passed viability gate
    competitive_count: int         # passed survivor filter
    representative_count: int      # passed redundancy filter
    representatives: list[dict]    # per-rep: signal, weight, correlation
    score_explanation: str
    methodology_status: str        # "robust_oos_ensemble" or "provisional"
    as_of: str                     # ISO date of last bar
    best_variant_id: str           # highest reliability (fallback)
    signal_type: str               # "trend", "oscillator", "volume"
    category: str                  # "tendance", "oscillation", "volume"
```

### Edge Cases

| Scenario | Result |
|----------|--------|
| Insufficient data (< train + test + 1 bars) | Neutral signal, status = "provisional" |
| No survivors (all non-viable or below floor) | Neutral signal, best_variant_id set |
| No representatives (extremely rare) | Neutral signal, best_variant_id set |
| All signals agree (score = ±100) | Label = "Très haussier" / "Vente forte" |

---

## Aggregate Cross-Family Scoring

The batch scores endpoint computes an **aggregate score** across all 4 families for each symbol. This is what powers the stock sidebar's signal badges.

### Computation

For each symbol, the batch endpoint:

1. Runs `run_family_ensemble_full()` for each of the 20 families (or subset of enabled families)
2. Computes **per-category** scores by averaging family scores within each category:
   - Tendance = mean(SMA, EMA, EMA Cross, Ichimoku, PSAR scores)
   - Momentum = mean(MACD, ROC, TRIX, ADX, TSI scores)
   - Oscillation = mean(RSI, Stochastic, CCI, MFI, UO scores)
   - Volume = mean(OBV, CMF, A/D, VWAP, Force Index scores)
3. Computes **aggregate score** = mean of all 4 category scores (equal weight across categories)
4. Assigns aggregate label via `signal_type_label(None, aggregate_score_pct)` → "Achat fort" / "Achat" / "Neutre" / "Vente" / "Vente forte"

### Why Equal Weights Across Categories?

All 4 categories contribute equally to the aggregate. This is a deliberate choice:
- We have no *a priori* reason to believe trend signals are more informative than volume signals for Moroccan equities
- Feature importance analysis (planned) would provide empirical weights
- Equal weighting is the maximally uninformative prior — it makes the fewest assumptions
- Within each category, all 5 families also contribute equally

### Category Grouping Rationale

The 4 categories (Tendance, Momentum, Oscillation, Volume) group families by **signal type** (Murphy 1999, Elder 1993):
- **Tendance**: trend-following indicators — direction of market
- **Momentum**: speed/acceleration indicators — force of price movement
- **Oscillation**: mean-reversion indicators — statistical extremes
- **Volume**: confirmation indicators — buying/selling pressure

This grouping ensures the frontend can display a balanced view: four independent perspectives on the same market condition. The redundancy reduction (Layer E) within each family ensures that the 5 indicators per category contribute complementary, not redundant, information.

---

## Dual Horizon System

Two horizon configurations coexist in the codebase:

### Signal Engine Horizons (`core/quant_core/signal_engine/domain.py`)

```python
HORIZON_PARAMS = {
    "short":  {"train": 252, "test": 63,  "step": 63,  "max_years": 5},
    "medium": {"train": 504, "test": 126, "step": 126, "max_years": 10},
    "long":   {"train": 756, "test": 252, "step": 252, "max_years": 20},
}
```

Used by: the signal engine pipeline (Layers A–G). These control OOS window sizes and data truncation.

### WFO Research Horizons (`core/quant_core/research/horizon.py`)

```python
PRESETS = {
    TradingHorizon.SHORT:  HorizonConfig(train_window=252, test_window=63,  step_size=63),
    TradingHorizon.MEDIUM: HorizonConfig(train_window=504, test_window=126, step_size=126),
    TradingHorizon.LONG:   HorizonConfig(train_window=756, test_window=252, step_size=252),
}
```

Used by: the WFO backtest engine (`optimize.py`, `pipeline.py`). Supports overrides via spec_json.

The values are identical by design — the signal engine's OOS evaluation uses the same window geometry as the backtest engine's WFO. This ensures consistency: a signal validated at "medium" horizon in the signal engine corresponds to the same temporal scale as a "medium" WFO backtest.

### Horizon Parameter Rationale

| Horizon | Train | Test | Step | Max Years | Rationale |
|---------|-------|------|------|-----------|-----------|
| Short | 252 (1yr) | 63 (3mo) | 63 | 5 | Short-term signals: 1 year of warmup, quarterly evaluation windows, 5 years of history |
| Medium | 504 (2yr) | 126 (6mo) | 126 | 10 | Medium-term: 2 years warmup, semi-annual evaluation, 10 years history |
| Long | 756 (3yr) | 252 (1yr) | 252 | 20 | Long-term: 3 years warmup, annual evaluation, 20 years history |

**Step = Test**: Windows don't overlap. Each bar appears in exactly one test window. This prevents correlated evaluation across windows (Pardo 2008).

**Max Years**: Caps how far back the engine looks. Ancient market data (pre-2005 for Morocco) may reflect a different market microstructure and bias the evaluation.
