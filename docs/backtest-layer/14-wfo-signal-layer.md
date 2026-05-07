# 14 — WFO Signal Layer

**Purpose:** Produce WFO-optimized signals for the signal page dashboard, complementing the existing A→G signal engine. While the signal engine filters and ensembles fixed-param variants by OOS reliability, the WFO signal layer optimizes indicator parameters and ensemble weights through Walk-Forward Analysis, then delivers a comparable signal score per family and a global consensus.

---

## Two Signal Columns, Same Dashboard

The signal page displays two parallel signal columns for each stock × horizon:

| | Signal Engine (A→G) | WFO Signal Layer |
|---|---|---|
| **Per-family** | 30 fixed-param variants → filter → ensemble | WFO-optimized ensemble (best 3-5 across all indicators in family) |
| **Global** | Aggregate of family scores | Consensus of WFO family signals, S/R-modulated |
| **Params** | Fixed per variant, filtered by OOS reliability | Optimized per window, validated by WFE ≥ 50% |
| **Compute** | Real-time (sub-second) | Batch (weekly), results cached |
| **Strength** | Fast, always fresh | Statistically validated, parameter-robust |

Agreement between the two columns = high confidence. Divergence = investigate further.

---

## Per-Family WFO Signal

### Unit of work

For each family (e.g., trend = {SMA, EMA, EMA_cross, Ichimoku, PSAR}), WFO treats **all indicators in the family as candidates in the same pool**. It does not run separate WFOs per indicator — it runs one WFO across the full family.

### What WFO optimizes

1. **Which indicators** to include (subset selection from the family's 5 indicators)
2. **Indicator parameters** (e.g., SMA period, MACD fast/slow/signal) — horizon-appropriate ranges
3. **Ensemble weights** for the selected indicators

### Output

A WFO family signal comparable to the A→G family signal:
- Score: -100 to +100
- Representative indicators with optimized params and weights
- WFE, robustness ratio, robustness grade (A–F)
- Optimal params from the last IS window (what you'd trade today)

### Methodology

Each IS window:
1. Generate parameter grid across all indicators in the family
2. For each parameter set, compute the indicator signal over the IS period
3. Evaluate signal quality via PROM (applied to a minimal entry/exit strategy)
4. Neighbor-average across the parameter space
5. Select winner, check optimization profile
6. Test winner on OOS window

After rolling all windows:
- Compute WFE, robustness ratio
- Extract last IS window's winner as the current live signal configuration
- Build the family signal from the live configuration applied to current data

### Parameter space per family type

| Family type | Indicators | Key params | Typical grid size |
|-------------|-----------|-----------|------------------|
| Trend | SMA, EMA, EMA_cross, Ichimoku, PSAR | period, cross periods | ~150-300 |
| Momentum | MACD, ROC, TRIX, ADX, TSI | fast/slow/signal periods | ~200-400 |
| Oscillator | RSI, Stochastic, CCI, MFI, UO | period, overbought/oversold thresholds | ~200-400 |
| Volume | OBV, CMF, AD, VWAP, FI | period, smoothing | ~150-300 |

Each indicator contributes its own parameter dimensions. The joint grid is the union (not the product) because only one indicator is active per "slot" in the ensemble.

### Ensemble construction within WFO

Within each IS window, after finding the top-performing indicator+param sets:
1. Rank all parameter sets by smoothed PROM
2. Select top K (3-5) that are sufficiently uncorrelated (|r| < 0.85, same logic as Layer E redundancy)
3. Assign weights proportional to PROM rank
4. The ensemble signal = weighted sum of individual signals, normalized to [-100, +100]

This mirrors the A→G pipeline's redundancy reduction + ensemble, but with WFO-optimized parameters.

---

## Global WFO Signal

### Consensus approach

The global signal is a **weighted consensus** of the 4 per-family WFO signals:

```
global_score = w_trend × trend_score + w_momentum × momentum_score
             + w_oscillation × oscillation_score + w_volume × volume_score
```

The family weights (`w_trend`, `w_momentum`, `w_oscillation`, `w_volume`) are themselves WFO-optimized:
- A separate WFO pass optimizes the 4 weights (constrained to sum to 1.0)
- IS objective: PROM of trading the weighted consensus signal
- This determines which family matters most for each stock × horizon

### S/R Modulation

The raw global score is adjusted based on the close's position relative to S/R levels:

```
modulated_score = global_score × sr_modifier
```

Where `sr_modifier` depends on:
- **Distance to nearest support** (as % of ATR)
- **Distance to nearest resistance** (as % of ATR)
- **Signal direction** (bullish vs bearish)

Rules:
- Close near strong support + bullish signal → boost (modifier > 1.0)
- Close near strong resistance + bullish signal → dampen (modifier < 1.0)
- Close near strong support + bearish signal → dampen
- Close near strong resistance + bearish signal → boost
- Close far from both levels → no modulation (modifier = 1.0)

The modulation parameters (distance thresholds, boost/dampen factors) are WFO-optimized as part of the global signal WFO pass. The S/R levels themselves come from the existing 6-method detection system (MA anchor, score inversion, swing levels, pivot points, quantile extrema, Fibonacci).

### Output

- Global WFO score: -100 to +100 (S/R-modulated)
- Family weights breakdown
- S/R modulation details (which levels, modifier applied)
- Recommendation label: Strong Buy / Buy / Neutral / Sell / Strong Sell

---

## Computation Schedule

WFO signals are **batch-computed weekly** (e.g., Sunday night):

```
For each tracked symbol:
  For each horizon (short, medium, long):
    For each family (trend, momentum, oscillation, volume):
      run_wfo_family_signal(symbol, family, horizon)
    run_wfo_global_signal(symbol, horizon)  # consensus + S/R modulation
```

Results are stored in the database and served instantly on the signal page. The signal page shows `data_as_of` so the user knows the freshness. A manual "Refresh" button allows on-demand recomputation for a specific stock.

### Compute budget

- Per family: ~1-3 min (single family, moderate grid)
- Per stock × horizon: ~5-15 min (4 families + global)
- Per stock (all horizons): ~15-45 min
- Full universe (e.g., 20 stocks): ~5-15 hours (parallelizable across workers)

Weekly batch with worker parallelism is practical.

---

## Comparison View on Dashboard

Both signal columns are displayed side-by-side on the signal page (in both legacy and expanded views):

```
┌────────────────────────┬────────────────────────┐
│   Signal Engine (A→G)  │   WFO Optimized        │
├────────────────────────┼────────────────────────┤
│ Tendance:  +62  BUY    │ Tendance:  +71  BUY    │
│   5 reps, real-time    │   3 reps, optimized    │
│                        │   WFE: 68%  Grade: A   │
├────────────────────────┼────────────────────────┤
│ Momentum:  -15  HOLD   │ Momentum:  -22  SELL   │
│   4 reps, real-time    │   4 reps, optimized    │
│                        │   WFE: 52%  Grade: C   │
├────────────────────────┼────────────────────────┤
│ Oscillation: +28 BUY   │ Oscillation: +35 BUY   │
│   3 reps, real-time    │   3 reps, optimized    │
│                        │   WFE: 61%  Grade: B   │
├────────────────────────┼────────────────────────┤
│ Volume:    +10  HOLD   │ Volume:    +18  BUY    │
│   2 reps, real-time    │   2 reps, optimized    │
│                        │   WFE: 55%  Grade: B   │
├────────────────────────┼────────────────────────┤
│ Global:    +35         │ Global:    +42         │
│ (unweighted aggregate) │ (S/R modulated, +3)    │
│                        │ S: 142.50  R: 158.20   │
└────────────────────────┴────────────────────────┘
```

### Agreement indicators

- Both columns same direction → high confidence badge
- Columns disagree → warning badge, investigate
- WFO grade A/B + agreement → strongest signal

---

## Relationship to Existing WFO (Backtest Page)

The backtest page WFO evaluates **full trading strategies** (indicator + entry/exit rules + risk management) defined by the user on the strategy page. It is the final gate before a strategy is considered viable.

The WFO signal layer evaluates **indicator signal quality** using a minimal standardized trading wrapper. Its purpose is signal research, not strategy validation.

| Aspect | Backtest Page WFO | WFO Signal Layer |
|--------|-------------------|------------------|
| Purpose | Validate a user-defined strategy | Discover optimal indicator signals |
| Strategy | User-configured (entry/exit/risk) | Standardized minimal wrapper |
| Scope | One strategy at a time | All families × all stocks × all horizons |
| Trigger | User-initiated via /new-run | Weekly batch + manual refresh |
| Output | Viable/not viable verdict + sized params | Signal score (-100 to +100) + optimal params |
| S/R | Not integrated | Modulates global signal |

They are complementary: the signal layer discovers *what* to trade; the backtest page validates *how* to trade it.

---

## Phase 2: S/R Parameter Optimization

In a future phase, the WFO signal layer can optimize S/R detection parameters themselves:
- Swing detection geometry (left_bars, right_bars)
- Score inversion thresholds (currently hardcoded at 15/-15)
- ATR multipliers for distance filtering
- Method selection and weighting

This would improve the S/R modulation quality by ensuring the levels used for modulation are themselves WFO-validated for each stock × horizon.

---
---

# Implementation Specification

Everything below is implementation-ready detail for each component. Each section specifies exact file paths, function signatures, data structures, and logic so that a code agent can implement without ambiguity.

---

## 1. Database Models

**File:** `services/api/app/models.py`

Add after the `StrategyBacktestWindow` class (line ~551):

```python
class WfoSignalSummary(Base):
    """Cached WFO signal result for one (symbol, category, horizon) tuple."""
    __tablename__ = "wfo_signal_summary"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    category = Column(String(32), nullable=False)       # "tendance" | "momentum" | "oscillation" | "volume"
    horizon = Column(String(16), nullable=False)         # "short" | "medium" | "long"
    status = Column(String(20), nullable=False, default="pending")  # "pending" | "running" | "succeeded" | "failed"

    # --- WFO results ---
    score_pct = Column(Float, nullable=True)             # -100.0 to +100.0  (ensemble score)
    signal_label = Column(String(60), nullable=True)     # French label from signal_type_label()
    representatives_json = Column(JSONB, nullable=False, default=list)
    # Each element: {
    #   "family": "sma",
    #   "archetype": "price_vs_sma",
    #   "variant_id": "...",
    #   "params": {"window": 47},
    #   "signal": 1.0,
    #   "signal_label": "HAUSSIER",
    #   "normalized_weight": 0.35,
    #   "contribution": 0.35,
    #   "description": "SMA-47 (medium)",
    #   "indicator_value": 148.3,
    #   "explanation": "Close 150.25 > SMA-47 148.30 → HAUSSIER"
    # }

    # --- WFO quality metrics ---
    wfe_pct = Column(Float, nullable=True)
    robustness_ratio = Column(Float, nullable=True)      # 0.0 to 1.0
    total_folds = Column(Integer, nullable=True)
    profitable_folds = Column(Integer, nullable=True)
    mean_oos_sharpe = Column(Float, nullable=True)
    total_oos_pnl = Column(Float, nullable=True)
    worst_fold_drawdown = Column(Float, nullable=True)
    composite_score = Column(Float, nullable=True)       # pre-computed ranking score (0-100)
    robustness_grade = Column(String(2), nullable=True)  # "A" | "B" | "C" | "D" | "F"

    # --- Metadata ---
    computed_at = Column(DateTime(timezone=True), nullable=True)
    data_as_of = Column(Date, nullable=True)             # last bar date in OHLCV when computed
    compute_seconds = Column(Float, nullable=True)       # wall-clock time for this family WFO
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "category", "horizon", name="uq_wfo_signal_summary_sym_cat_hz"),
        Index("ix_wfo_signal_summary_symbol_horizon", "symbol", "horizon"),
        Index("ix_wfo_signal_summary_status", "status"),
    )


class WfoGlobalSignal(Base):
    """Cached WFO global consensus signal for one (symbol, horizon) tuple."""
    __tablename__ = "wfo_global_signal"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    horizon = Column(String(16), nullable=False)
    status = Column(String(20), nullable=False, default="pending")

    # --- Consensus signal ---
    global_score_pct = Column(Float, nullable=True)      # -100 to +100 (after S/R modulation)
    raw_score_pct = Column(Float, nullable=True)          # -100 to +100 (before S/R modulation)
    signal_label = Column(String(60), nullable=True)
    recommendation = Column(String(32), nullable=True)    # "achat_fort" | "achat" | "neutre" | "vente" | "vente_forte"

    # --- Family weights (WFO-optimized, sum to 1.0) ---
    weight_tendance = Column(Float, nullable=True)
    weight_momentum = Column(Float, nullable=True)
    weight_oscillation = Column(Float, nullable=True)
    weight_volume = Column(Float, nullable=True)

    # --- S/R modulation ---
    sr_modifier = Column(Float, nullable=True)            # multiplier applied (e.g., 1.12 or 0.88)
    sr_support_level = Column(Float, nullable=True)
    sr_resistance_level = Column(Float, nullable=True)
    sr_support_method = Column(String(40), nullable=True) # which of the 6 methods provided support
    sr_resistance_method = Column(String(40), nullable=True)
    sr_distance_support_atr = Column(Float, nullable=True)
    sr_distance_resistance_atr = Column(Float, nullable=True)

    # --- Cross-family ranking ---
    best_category = Column(String(32), nullable=True)     # "tendance" | "momentum" | ...
    best_category_score = Column(Float, nullable=True)
    categories_viable = Column(Integer, nullable=True)    # how many categories have grade >= C

    # --- WFO quality for the consensus pass ---
    consensus_wfe_pct = Column(Float, nullable=True)
    consensus_robustness = Column(Float, nullable=True)

    # --- Metadata ---
    computed_at = Column(DateTime(timezone=True), nullable=True)
    data_as_of = Column(Date, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "horizon", name="uq_wfo_global_signal_sym_hz"),
        Index("ix_wfo_global_signal_symbol", "symbol"),
    )
```

**Alembic migration:** Create via `alembic revision --autogenerate -m "add wfo signal summary tables"`.

---

## 2. Candidate Grid Construction

**File:** `core/quant_core/signal_engine/wfo_signal.py` (new)

### Grid construction: union across indicators in a category

The key insight: each indicator in a category has different parameter dimensions. We can't form a Cartesian product across indicators. Instead, we form the **union** of all per-indicator grids. Each grid element is a `VariantDef` (reusing the existing dataclass).

```python
"""WFO signal layer — per-category WFO-optimized signal."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from core.quant_core.signal_engine.candidates import generate_candidates
from core.quant_core.signal_engine.current_signal import build_current_signal
from core.quant_core.signal_engine.domain import (
    CATEGORY_FAMILIES,
    FAMILY_SIGNAL_TYPE,
    HORIZON_PARAMS,
    VALID_HORIZONS,
    VariantDef,
    VariantCurrentSignal,
    signal_type_label,
)
from core.quant_core.signal_engine.oos_eval import compute_signal_array
from core.quant_core.signal_engine.redundancy import reduce_redundancy, _pearson_corr
from core.quant_core.wfo.config import WalkForwardConfig
from core.quant_core.wfo.engine import EngineResult, WindowScoreResult, run_wfo_engine
from core.quant_core.wfo.wfe import compute_robustness_ratio


# ---------------------------------------------------------------------------
# Grid construction
# ---------------------------------------------------------------------------

def build_category_candidate_grid(category: str, horizon: str) -> list[VariantDef]:
    """Build the full candidate pool for a category by unioning all families.

    For category="tendance", this calls generate_candidates() for each of
    [sma, ema, ema_cross, ichimoku, psar] and concatenates the results.
    Each VariantDef already carries its family and archetype, so the WFO
    engine can distinguish them.

    Returns
    -------
    list[VariantDef]
        Typically 100-200 variants depending on category and horizon.
    """
    if category not in CATEGORY_FAMILIES:
        raise ValueError(f"Unknown category {category!r}")
    if horizon not in VALID_HORIZONS:
        raise ValueError(f"Unknown horizon {horizon!r}")

    pool: list[VariantDef] = []
    for family in CATEGORY_FAMILIES[category]:
        try:
            pool.extend(generate_candidates(family, horizon))
        except ValueError:
            pass  # family not yet implemented
    return pool
```

### Why union, not product

Each variant in the pool is a complete signal source (e.g., "SMA with period 47" or "MACD with fast=12, slow=26, signal=9"). The WFO engine evaluates each variant independently on IS data. There is no cross-indicator product — the ensemble is built *after* WFO selects winners, not during the parameter scan.

---

## 3. Minimal Trading Wrapper (PROM Evaluation)

The WFO engine needs a `evaluate_window` callback that takes a `WalkForwardWindow` and returns `WindowScoreResult` (raw_scores, is_returns, oos_returns). For the signal layer, we use a **minimal signal-following strategy**:

```python
# ---------------------------------------------------------------------------
# Minimal trading wrapper for PROM evaluation
# ---------------------------------------------------------------------------

def _evaluate_variant_pnl(
    signal_arr: np.ndarray,
    close: np.ndarray,
    cost_bps: float = 10.0,
) -> float:
    """Simple signal-following P&L: go long when signal > 0, flat otherwise.

    Returns total return (not annualized) net of costs.
    This is intentionally minimal — no stop loss, no take profit, no
    position sizing. The purpose is to evaluate signal quality, not
    strategy quality.
    """
    if len(signal_arr) < 2:
        return 0.0
    returns = np.diff(close) / close[:-1]
    positions = signal_arr[:-1]  # position at bar i determines exposure to return i+1
    gross_pnl = np.sum(positions * returns)
    # Cost: each position change incurs cost_bps
    trades = np.sum(np.abs(np.diff(np.concatenate(([0.0], positions)))))
    cost = trades * cost_bps / 10_000.0
    return float(gross_pnl - cost)


def _compute_prom_for_variant(
    close_is: np.ndarray,
    close_oos: np.ndarray,
    variant: VariantDef,
    full_close: np.ndarray,
    variant_idx_start_is: int,
    variant_idx_start_oos: int,
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    cost_bps: float = 10.0,
) -> tuple[float, float, float]:
    """Compute PROM on IS, total return on IS, total return on OOS.

    Uses compute_signal_array() from oos_eval.py to get the signal series,
    then evaluates P&L via the minimal wrapper.

    Returns (prom, is_return, oos_return).
    """
    from core.quant_core.wfo.prom import compute_prom

    # Compute signal on full data (for warmup), then slice
    sig_full = compute_signal_array(full_close, variant, volume=volume, high=high, low=low)
    sig_is = sig_full[variant_idx_start_is:variant_idx_start_is + len(close_is)]
    sig_oos = sig_full[variant_idx_start_oos:variant_idx_start_oos + len(close_oos)]

    is_return = _evaluate_variant_pnl(sig_is, close_is, cost_bps)
    oos_return = _evaluate_variant_pnl(sig_oos, close_oos, cost_bps)

    # PROM from IS trades
    # Build trade list from position changes
    trades = _extract_trades(sig_is, close_is)
    if len(trades) >= 2:
        prom = compute_prom(trades)
    else:
        prom = is_return  # fallback for very few trades

    return prom, is_return, oos_return


def _extract_trades(signal_arr: np.ndarray, close: np.ndarray) -> list[float]:
    """Extract per-trade returns from signal array.

    A trade starts when signal transitions from 0 to non-zero,
    and ends when signal transitions back to 0 or reverses.
    """
    trades: list[float] = []
    in_trade = False
    entry_price = 0.0
    direction = 0.0

    for i in range(len(signal_arr)):
        if not in_trade and signal_arr[i] != 0:
            in_trade = True
            entry_price = close[i]
            direction = signal_arr[i]
        elif in_trade and (signal_arr[i] == 0 or signal_arr[i] != direction):
            # Close trade
            trade_return = direction * (close[i] - entry_price) / entry_price
            trades.append(trade_return)
            in_trade = False
            # If reversing, open new trade
            if signal_arr[i] != 0 and signal_arr[i] != direction:
                entry_price = close[i]
                direction = signal_arr[i]
                in_trade = True

    # Close open trade at end
    if in_trade and len(close) > 0:
        trade_return = direction * (close[-1] - entry_price) / entry_price
        trades.append(trade_return)

    return trades
```

---

## 4. WFO Engine Integration

```python
# ---------------------------------------------------------------------------
# WFO engine integration
# ---------------------------------------------------------------------------

@dataclass
class WfoCategoryResult:
    """Result of WFO for one category × symbol × horizon."""
    category: str
    symbol: str
    horizon: str
    status: str                                  # "succeeded" | "failed" | "insufficient_data"
    score_pct: float                             # -100 to +100
    signal_label: str
    representatives: list[dict[str, Any]]        # same shape as FamilyCombinedSignal.representatives
    wfe_pct: float
    robustness_ratio: float
    total_folds: int
    profitable_folds: int
    mean_oos_sharpe: float
    total_oos_pnl: float
    worst_fold_drawdown: float
    composite_score: float
    robustness_grade: str
    engine_result: EngineResult | None = None
    error_message: str = ""
    data_as_of: str = ""
    compute_seconds: float = 0.0


def run_wfo_category_signal(
    category: str,
    horizon: str,
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    cost_bps: float = 10.0,
    max_reps: int = 5,
    max_corr: float = 0.85,
) -> WfoCategoryResult:
    """Run WFO for one category and return the optimized signal.

    Steps:
    1. Build candidate grid (union of all families in category)
    2. Determine WFO window config from HORIZON_PARAMS
    3. Call run_wfo_engine() with evaluate_window callback
    4. From each IS window's winner, collect the top K variants
    5. In the last IS window, build the ensemble (top K decorrelated)
    6. Apply ensemble to current data → score

    The evaluate_window callback iterates all candidates, computes
    PROM for each on the IS data, and returns WindowScoreResult.
    """
    import time
    t0 = time.monotonic()

    pool = build_category_candidate_grid(category, horizon)
    if not pool:
        return WfoCategoryResult(
            category=category, symbol="", horizon=horizon,
            status="failed", score_pct=0.0, signal_label="Pas disponible",
            representatives=[], wfe_pct=0.0, robustness_ratio=0.0,
            total_folds=0, profitable_folds=0, mean_oos_sharpe=0.0,
            total_oos_pnl=0.0, worst_fold_drawdown=0.0,
            composite_score=0.0, robustness_grade="F",
            error_message="No candidates for category",
        )

    hp = HORIZON_PARAMS[horizon]
    max_lookback = max(_variant_min_history(v) for v in pool)

    config = WalkForwardConfig(
        train_bars=hp["train"],
        oos_bars=hp["test"],
        step_bars=hp["step"],
    )

    # Check we have enough data
    min_bars = hp["train"] + hp["test"] + max_lookback
    if len(close) < min_bars:
        return WfoCategoryResult(
            category=category, symbol="", horizon=horizon,
            status="insufficient_data", score_pct=0.0,
            signal_label="Pas disponible", representatives=[],
            wfe_pct=0.0, robustness_ratio=0.0,
            total_folds=0, profitable_folds=0, mean_oos_sharpe=0.0,
            total_oos_pnl=0.0, worst_fold_drawdown=0.0,
            composite_score=0.0, robustness_grade="F",
            error_message=f"Need {min_bars} bars, have {len(close)}",
        )

    def evaluate_window(window) -> WindowScoreResult:
        """Evaluate all candidates on one IS+OOS window."""
        raw_scores: dict = {}
        is_returns: dict = {}
        oos_returns: dict = {}

        for i, variant in enumerate(pool):
            prom, is_ret, oos_ret = _compute_prom_for_variant(
                close_is=close[window.train_start:window.train_end],
                close_oos=close[window.oos_start:window.oos_end],
                variant=variant,
                full_close=close,
                variant_idx_start_is=window.train_start,
                variant_idx_start_oos=window.oos_start,
                volume=volume, high=high, low=low,
                cost_bps=cost_bps,
            )
            key = i  # use index as hashable key
            raw_scores[key] = prom
            is_returns[key] = is_ret
            oos_returns[key] = oos_ret

        return WindowScoreResult(
            raw_scores=raw_scores,
            is_returns=is_returns,
            oos_returns=oos_returns,
        )

    engine_result = run_wfo_engine(
        data_length=len(close),
        config=config,
        evaluate_window=evaluate_window,
        max_lookback=max_lookback,
    )

    # --- Build ensemble from last window's top performers ---
    if not engine_result.windows:
        return WfoCategoryResult(
            category=category, symbol="", horizon=horizon,
            status="failed", score_pct=0.0, signal_label="Pas disponible",
            representatives=[], wfe_pct=0.0, robustness_ratio=0.0,
            total_folds=0, profitable_folds=0, mean_oos_sharpe=0.0,
            total_oos_pnl=0.0, worst_fold_drawdown=0.0,
            composite_score=0.0, robustness_grade="F",
            engine_result=engine_result,
            error_message="No WFO windows produced",
        )

    last_window = engine_result.windows[-1]
    smoothed = last_window.smoothed_scores

    # Rank all candidates by smoothed PROM in the last IS window
    ranked_indices = sorted(smoothed.keys(), key=lambda k: smoothed[k], reverse=True)

    # Select top K decorrelated representatives
    # Build signal arrays on recent data for correlation check
    recent_close = close[-252:]  # last year for correlation
    sig_arrays = []
    selected_variants: list[tuple[int, VariantDef, float]] = []

    for idx in ranked_indices:
        if len(selected_variants) >= max_reps:
            break
        variant = pool[idx]
        sig = compute_signal_array(recent_close, variant, volume=volume[-252:] if volume is not None else None,
                                    high=high[-252:] if high is not None else None,
                                    low=low[-252:] if low is not None else None)

        # Check correlation with already selected
        is_redundant = False
        for _, _, _, existing_sig in [(s[0], s[1], s[2], sa) for s, sa in zip(selected_variants, sig_arrays)]:
            if abs(_pearson_corr(sig, existing_sig)) > max_corr:
                is_redundant = True
                break

        if not is_redundant:
            selected_variants.append((idx, variant, smoothed[idx]))
            sig_arrays.append(sig)

    # Assign weights proportional to smoothed PROM (normalize to sum=1)
    if selected_variants:
        total_prom = sum(max(0.01, s[2]) for s in selected_variants)
        weights = [max(0.01, s[2]) / total_prom for s in selected_variants]
    else:
        weights = []

    # Compute ensemble score on current bar
    current_signals: list[VariantCurrentSignal] = []
    for (idx, variant, prom_val), weight in zip(selected_variants, weights):
        cs = build_current_signal(
            variant, close,
            volume=volume, high=high, low=low,
            reliability_weight=weight,
        )
        current_signals.append(cs)

    # Weighted ensemble score
    if current_signals:
        total_w = sum(cs.reliability_weight for cs in current_signals)
        if total_w > 0:
            score_raw = sum(cs.signal * cs.reliability_weight for cs in current_signals) / total_w
        else:
            score_raw = 0.0
        score_pct = 100.0 * score_raw
    else:
        score_pct = 0.0

    # Signal label
    signal_type = FAMILY_SIGNAL_TYPE.get(CATEGORY_FAMILIES[category][0], "trend")
    label = signal_type_label(signal_type, score_pct)

    # Build representatives list (same shape as FamilyCombinedSignal.representatives)
    reps_list: list[dict[str, Any]] = []
    for (idx, variant, prom_val), weight, cs in zip(selected_variants, weights, current_signals):
        reps_list.append({
            "family": variant.family,
            "archetype": variant.archetype,
            "variant_id": variant.variant_id,
            "params": variant.params,
            "signal": cs.signal,
            "signal_label": cs.signal_label,
            "normalized_weight": round(weight, 4),
            "contribution": round(weight * cs.signal, 4),
            "description": variant.description,
            "current_close": cs.current_close,
            "indicator_value": cs.indicator_value,
            "explanation": cs.explanation,
            "wfo_prom": round(prom_val, 6),
        })

    # Compute aggregate metrics
    oos_returns = [w.oos_return for w in engine_result.windows]
    profitable_count = sum(1 for r in oos_returns if r > 0)
    mean_sharpe = float(np.mean([w.oos_return for w in engine_result.windows])) if engine_result.windows else 0.0
    total_pnl = sum(oos_returns)
    worst_dd = min(oos_returns) if oos_returns else 0.0

    composite = compute_composite_score(
        engine_result.wfe, engine_result.robustness_ratio, mean_sharpe, worst_dd
    )
    grade = compute_robustness_grade(engine_result.wfe, engine_result.robustness_ratio)

    elapsed = time.monotonic() - t0

    return WfoCategoryResult(
        category=category, symbol="", horizon=horizon,
        status="succeeded",
        score_pct=round(score_pct, 2),
        signal_label=label,
        representatives=reps_list,
        wfe_pct=round(engine_result.wfe * 100, 2),
        robustness_ratio=round(engine_result.robustness_ratio, 4),
        total_folds=len(engine_result.windows),
        profitable_folds=profitable_count,
        mean_oos_sharpe=round(mean_sharpe, 4),
        total_oos_pnl=round(total_pnl, 4),
        worst_fold_drawdown=round(worst_dd, 4),
        composite_score=round(composite, 2),
        robustness_grade=grade,
        engine_result=engine_result,
        data_as_of="",
        compute_seconds=round(elapsed, 2),
    )
```

---

## 5. Scoring and Grading Functions

```python
# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def compute_robustness_grade(wfe: float, robustness_ratio: float) -> str:
    """Map WFE + robustness to a letter grade.

    A: WFE >= 0.65 AND robustness >= 0.75
    B: WFE >= 0.55 AND robustness >= 0.60
    C: WFE >= 0.50 AND robustness >= 0.50
    D: WFE >= 0.40 OR robustness >= 0.40
    F: everything else
    """
    if wfe >= 0.65 and robustness_ratio >= 0.75:
        return "A"
    if wfe >= 0.55 and robustness_ratio >= 0.60:
        return "B"
    if wfe >= 0.50 and robustness_ratio >= 0.50:
        return "C"
    if wfe >= 0.40 or robustness_ratio >= 0.40:
        return "D"
    return "F"


def compute_composite_score(
    wfe: float,
    robustness_ratio: float,
    mean_oos_sharpe: float,
    worst_fold_drawdown: float,
) -> float:
    """Composite ranking score (0-100) for cross-category comparison.

    Formula:
        0.40 × wfe_norm + 0.30 × robustness_norm + 0.20 × sharpe_norm + 0.10 × dd_norm

    Each component normalized to [0, 1]:
    - wfe_norm = clamp(wfe, 0, 1)
    - robustness_norm = clamp(robustness_ratio, 0, 1)
    - sharpe_norm = clamp(mean_oos_sharpe / 2.0, 0, 1)     (Sharpe 2.0 = perfect)
    - dd_norm = clamp(1.0 - abs(worst_fold_drawdown), 0, 1) (0% drawdown = perfect)
    """
    def clamp01(x: float) -> float:
        return max(0.0, min(1.0, x))

    wfe_n = clamp01(wfe)
    rob_n = clamp01(robustness_ratio)
    sharpe_n = clamp01(mean_oos_sharpe / 2.0)
    dd_n = clamp01(1.0 - abs(worst_fold_drawdown))

    raw = 0.40 * wfe_n + 0.30 * rob_n + 0.20 * sharpe_n + 0.10 * dd_n
    return round(raw * 100, 2)
```

---

## 6. Global Signal + S/R Modulation

**File:** `core/quant_core/signal_engine/wfo_global.py` (new)

```python
"""WFO global consensus signal with S/R modulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from core.quant_core.signal_engine.domain import signal_type_label
from core.quant_core.signal_engine.wfo_signal import WfoCategoryResult, compute_composite_score
from core.quant_core.wfo.config import WalkForwardConfig
from core.quant_core.wfo.engine import WindowScoreResult, run_wfo_engine


# ---------------------------------------------------------------------------
# S/R Modulation
# ---------------------------------------------------------------------------

@dataclass
class SRModulationParams:
    """Parameters for S/R modulation (WFO-optimizable)."""
    near_threshold_atr: float = 1.5       # "near" = within 1.5 ATR of level
    boost_factor: float = 1.15            # boost multiplier when signal aligns with level
    dampen_factor: float = 0.85           # dampen multiplier when signal opposes level
    far_threshold_atr: float = 4.0        # beyond this, no modulation

    # WFO scan ranges (for grid search)
    SCAN_NEAR = [0.5, 1.0, 1.5, 2.0, 2.5]
    SCAN_BOOST = [1.05, 1.10, 1.15, 1.20, 1.30]
    SCAN_DAMPEN = [0.70, 0.80, 0.85, 0.90, 0.95]


def compute_sr_modifier(
    close: float,
    support: float | None,
    resistance: float | None,
    atr: float,
    signal_direction: float,
    params: SRModulationParams,
) -> float:
    """Compute the S/R modifier for the global signal.

    Returns a float multiplier (typically 0.7 to 1.3).
    Clamps output to [0.5, 1.5] to prevent extreme modulation.

    Logic:
    1. Compute distance to support and resistance in ATR units
    2. If close is near support:
       - Bullish signal → boost (support confirms buy)
       - Bearish signal → dampen (support contradicts sell)
    3. If close is near resistance:
       - Bearish signal → boost (resistance confirms sell)
       - Bullish signal → dampen (resistance contradicts buy)
    4. If close is near both (tight range) → no modulation
    5. If far from both → no modulation
    """
    if atr <= 0 or (support is None and resistance is None):
        return 1.0

    modifier = 1.0

    if support is not None and support > 0:
        dist_support = (close - support) / atr
        if 0 < dist_support <= params.near_threshold_atr:
            if signal_direction > 0:
                modifier *= params.boost_factor
            elif signal_direction < 0:
                modifier *= params.dampen_factor

    if resistance is not None and resistance > 0:
        dist_resistance = (resistance - close) / atr
        if 0 < dist_resistance <= params.near_threshold_atr:
            if signal_direction < 0:
                modifier *= params.boost_factor
            elif signal_direction > 0:
                modifier *= params.dampen_factor

    return max(0.5, min(1.5, modifier))


# ---------------------------------------------------------------------------
# Global consensus
# ---------------------------------------------------------------------------

@dataclass
class WfoGlobalResult:
    """Result of the global WFO consensus signal."""
    symbol: str
    horizon: str
    status: str
    global_score_pct: float                  # after S/R modulation
    raw_score_pct: float                     # before S/R modulation
    signal_label: str
    recommendation: str                      # "achat_fort" | "achat" | "neutre" | "vente" | "vente_forte"
    weights: dict[str, float]                # {"tendance": 0.35, "momentum": 0.25, ...}
    sr_modifier: float
    sr_support: float | None
    sr_resistance: float | None
    sr_support_method: str | None
    sr_resistance_method: str | None
    best_category: str
    best_category_score: float
    categories_viable: int
    consensus_wfe_pct: float
    consensus_robustness: float
    error_message: str = ""


def compute_global_wfo_signal(
    category_results: dict[str, WfoCategoryResult],
    close: np.ndarray,
    *,
    support: float | None = None,
    resistance: float | None = None,
    support_method: str | None = None,
    resistance_method: str | None = None,
    atr: float = 0.0,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
) -> WfoGlobalResult:
    """Compute the global WFO consensus from per-category results.

    Phase 1 (this implementation): Simple weighted average with
    weights proportional to composite score. Family weight WFO
    optimization is deferred to a later iteration.

    Phase 2 (future): WFO-optimize the 4 family weights by running
    a separate WFO pass where the parameter grid is the weight space.
    """
    # Filter to succeeded categories
    succeeded = {cat: r for cat, r in category_results.items() if r.status == "succeeded"}

    if not succeeded:
        return WfoGlobalResult(
            symbol="", horizon="", status="failed",
            global_score_pct=0.0, raw_score_pct=0.0,
            signal_label="Pas disponible", recommendation="neutre",
            weights={}, sr_modifier=1.0,
            sr_support=support, sr_resistance=resistance,
            sr_support_method=support_method, sr_resistance_method=resistance_method,
            best_category="", best_category_score=0.0, categories_viable=0,
            consensus_wfe_pct=0.0, consensus_robustness=0.0,
            error_message="No succeeded categories",
        )

    # Weights proportional to composite score
    total_composite = sum(r.composite_score for r in succeeded.values())
    if total_composite <= 0:
        weights = {cat: 1.0 / len(succeeded) for cat in succeeded}
    else:
        weights = {cat: r.composite_score / total_composite for cat, r in succeeded.items()}

    # Weighted consensus
    raw_score = sum(weights[cat] * r.score_pct for cat, r in succeeded.items())

    # S/R modulation
    signal_direction = 1.0 if raw_score > 0 else -1.0 if raw_score < 0 else 0.0
    sr_params = SRModulationParams()  # defaults; WFO-optimized in Phase 2
    modifier = compute_sr_modifier(
        float(close[-1]), support, resistance, atr, signal_direction, sr_params
    )
    global_score = raw_score * modifier

    # Clamp to [-100, +100]
    global_score = max(-100.0, min(100.0, global_score))

    # Label and recommendation
    label = signal_type_label("trend", global_score)
    recommendation = _score_to_recommendation(global_score)

    # Cross-category ranking
    best_cat = max(succeeded, key=lambda c: succeeded[c].composite_score)
    categories_viable = sum(1 for r in succeeded.values() if r.robustness_grade in ("A", "B", "C"))

    # Aggregate WFE/robustness
    avg_wfe = float(np.mean([r.wfe_pct for r in succeeded.values()]))
    avg_rob = float(np.mean([r.robustness_ratio for r in succeeded.values()]))

    return WfoGlobalResult(
        symbol="", horizon="",
        status="succeeded",
        global_score_pct=round(global_score, 2),
        raw_score_pct=round(raw_score, 2),
        signal_label=label,
        recommendation=recommendation,
        weights={cat: round(w, 4) for cat, w in weights.items()},
        sr_modifier=round(modifier, 4),
        sr_support=support,
        sr_resistance=resistance,
        sr_support_method=support_method,
        sr_resistance_method=resistance_method,
        best_category=best_cat,
        best_category_score=succeeded[best_cat].composite_score,
        categories_viable=categories_viable,
        consensus_wfe_pct=round(avg_wfe, 2),
        consensus_robustness=round(avg_rob, 4),
    )


def _score_to_recommendation(score: float) -> str:
    if score > 50:
        return "achat_fort"
    if score > 15:
        return "achat"
    if score >= -15:
        return "neutre"
    if score >= -50:
        return "vente"
    return "vente_forte"
```

---

## 7. Batch Worker Task

**File:** `services/worker/tasks/wfo_signal_batch.py` (new)

```python
"""Weekly batch task: compute WFO signals for all tracked symbols."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from services.api.app.db import SessionLocal
from services.api.app.models import (
    MarketDataStore,
    StockMaster,
    WfoGlobalSignal,
    WfoSignalSummary,
)
from core.quant_core.data import load_ohlcv_from_minio  # existing function
from core.quant_core.signal_engine.domain import CATEGORY_FAMILIES
from core.quant_core.signal_engine.wfo_signal import run_wfo_category_signal
from core.quant_core.signal_engine.wfo_global import compute_global_wfo_signal
from core.quant_core.signal_engine.support_resistance import (
    finalize_support_resistance_methods,
)

logger = logging.getLogger(__name__)

HORIZONS = ("short", "medium", "long")
CATEGORIES = ("tendance", "momentum", "oscillation", "volume")


def run_weekly_wfo_batch() -> dict:
    """Top-level entry point for the weekly WFO batch.

    Called by RQ scheduler or cron.
    Returns summary dict with counts.
    """
    db: Session = SessionLocal()
    try:
        # Get all active symbols
        symbols = [
            row.symbol
            for row in db.query(StockMaster.symbol)
            .filter(StockMaster.is_active.is_(True))
            .all()
        ]
        logger.info("WFO batch: %d symbols to process", len(symbols))

        results = {"total": 0, "succeeded": 0, "failed": 0}

        for symbol in symbols:
            for horizon in HORIZONS:
                try:
                    run_wfo_for_symbol_horizon(db, symbol, horizon)
                    results["succeeded"] += 1
                except Exception:
                    logger.exception("WFO batch failed: %s/%s", symbol, horizon)
                    results["failed"] += 1
                results["total"] += 1

        return results
    finally:
        db.close()


def run_wfo_for_symbol_horizon(db: Session, symbol: str, horizon: str) -> None:
    """Run WFO for all 4 categories + global for one symbol × horizon.

    1. Load OHLCV data
    2. For each category: run_wfo_category_signal()
    3. Compute global consensus + S/R modulation
    4. Upsert results into DB
    """
    logger.info("WFO signal: %s / %s", symbol, horizon)

    # --- Load data ---
    ohlcv = load_ohlcv_from_minio(symbol, timeframe="1D")
    close = ohlcv["close"].values.astype(float)
    volume = ohlcv["volume"].values.astype(float) if "volume" in ohlcv else None
    high = ohlcv["high"].values.astype(float) if "high" in ohlcv else None
    low = ohlcv["low"].values.astype(float) if "low" in ohlcv else None
    data_as_of = ohlcv.index[-1].date() if len(ohlcv) > 0 else None

    # --- Per-category WFO ---
    category_results: dict[str, Any] = {}

    for category in CATEGORIES:
        # Mark as running
        _upsert_summary(db, symbol, category, horizon, status="running")
        db.commit()

        try:
            result = run_wfo_category_signal(
                category, horizon, close,
                volume=volume, high=high, low=low,
            )
            result.symbol = symbol
            result.data_as_of = str(data_as_of) if data_as_of else ""
            category_results[category] = result

            _upsert_summary(db, symbol, category, horizon,
                            status=result.status, result=result, data_as_of=data_as_of)
        except Exception as e:
            logger.exception("WFO category failed: %s/%s/%s", symbol, category, horizon)
            _upsert_summary(db, symbol, category, horizon,
                            status="failed", error_message=str(e))

        db.commit()

    # --- Global consensus ---
    # Get S/R levels from existing system
    support, resistance, support_method, resistance_method, atr = _get_sr_levels(
        close, high, low, volume, horizon
    )

    try:
        global_result = compute_global_wfo_signal(
            category_results, close,
            support=support, resistance=resistance,
            support_method=support_method,
            resistance_method=resistance_method,
            atr=atr, volume=volume, high=high, low=low,
        )
        global_result.symbol = symbol
        global_result.horizon = horizon
        _upsert_global(db, symbol, horizon, global_result, data_as_of)
    except Exception:
        logger.exception("WFO global failed: %s/%s", symbol, horizon)

    db.commit()


def _upsert_summary(
    db: Session,
    symbol: str,
    category: str,
    horizon: str,
    *,
    status: str,
    result=None,
    data_as_of=None,
    error_message: str | None = None,
) -> None:
    """Insert or update a WfoSignalSummary row."""
    row = (
        db.query(WfoSignalSummary)
        .filter_by(symbol=symbol, category=category, horizon=horizon)
        .first()
    )
    if row is None:
        row = WfoSignalSummary(symbol=symbol, category=category, horizon=horizon)
        db.add(row)

    row.status = status
    row.error_message = error_message

    if result is not None and status == "succeeded":
        row.score_pct = result.score_pct
        row.signal_label = result.signal_label
        row.representatives_json = result.representatives
        row.wfe_pct = result.wfe_pct
        row.robustness_ratio = result.robustness_ratio
        row.total_folds = result.total_folds
        row.profitable_folds = result.profitable_folds
        row.mean_oos_sharpe = result.mean_oos_sharpe
        row.total_oos_pnl = result.total_oos_pnl
        row.worst_fold_drawdown = result.worst_fold_drawdown
        row.composite_score = result.composite_score
        row.robustness_grade = result.robustness_grade
        row.computed_at = datetime.now(timezone.utc)
        row.data_as_of = data_as_of
        row.compute_seconds = result.compute_seconds


def _upsert_global(db, symbol, horizon, result, data_as_of):
    """Insert or update a WfoGlobalSignal row."""
    row = (
        db.query(WfoGlobalSignal)
        .filter_by(symbol=symbol, horizon=horizon)
        .first()
    )
    if row is None:
        row = WfoGlobalSignal(symbol=symbol, horizon=horizon)
        db.add(row)

    row.status = result.status
    row.global_score_pct = result.global_score_pct
    row.raw_score_pct = result.raw_score_pct
    row.signal_label = result.signal_label
    row.recommendation = result.recommendation
    row.weight_tendance = result.weights.get("tendance", 0.0)
    row.weight_momentum = result.weights.get("momentum", 0.0)
    row.weight_oscillation = result.weights.get("oscillation", 0.0)
    row.weight_volume = result.weights.get("volume", 0.0)
    row.sr_modifier = result.sr_modifier
    row.sr_support_level = result.sr_support
    row.sr_resistance_level = result.sr_resistance
    row.sr_support_method = result.sr_support_method
    row.sr_resistance_method = result.sr_resistance_method
    row.best_category = result.best_category
    row.best_category_score = result.best_category_score
    row.categories_viable = result.categories_viable
    row.consensus_wfe_pct = result.consensus_wfe_pct
    row.consensus_robustness = result.consensus_robustness
    row.computed_at = datetime.now(timezone.utc)
    row.data_as_of = data_as_of


def _get_sr_levels(close, high, low, volume, horizon):
    """Get S/R levels from the existing detection system.

    Uses the finalized support/resistance from the 6-method system.
    Returns (support, resistance, support_method, resistance_method, atr).
    """
    # Import here to avoid circular deps
    from core.quant_core.strategy_plan.levels import (
        compute_atr,
        detect_swing_levels,
        compute_pivot_points,
        compute_fibonacci_retracement_levels,
    )

    atr_arr = compute_atr(high, low, close, window=20)
    atr = float(atr_arr[-1]) if len(atr_arr) > 0 else 0.0

    # Use swing levels as the primary S/R source (most robust)
    try:
        swing = detect_swing_levels(close, high, low, lookback=120, left_bars=3, right_bars=3)
        support = swing.get("support")
        resistance = swing.get("resistance")
        return support, resistance, "swing_levels", "swing_levels", atr
    except Exception:
        pass

    # Fallback to pivot points
    try:
        pivots = compute_pivot_points(high, low, close)
        return pivots.get("s1"), pivots.get("r1"), "pivot_points", "pivot_points", atr
    except Exception:
        pass

    return None, None, None, None, atr
```

---

## 8. API Endpoints

**File:** `services/api/app/routers/wfo_signals.py` (new)

```python
"""WFO signal layer API endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import WfoGlobalSignal, WfoSignalSummary

router = APIRouter(prefix="/strategy/wfo", tags=["wfo-signals"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class WfoRepresentativeOut(BaseModel):
    family: str
    archetype: str
    variant_id: str
    params: dict[str, Any]
    signal: float
    signal_label: str
    normalized_weight: float
    contribution: float
    description: str
    current_close: float | None = None
    indicator_value: float | None = None
    explanation: str = ""
    wfo_prom: float | None = None


class WfoCategorySummaryOut(BaseModel):
    category: str
    status: str
    score_pct: float | None = None
    signal_label: str | None = None
    representatives: list[WfoRepresentativeOut] = []
    wfe_pct: float | None = None
    robustness_ratio: float | None = None
    total_folds: int | None = None
    profitable_folds: int | None = None
    mean_oos_sharpe: float | None = None
    total_oos_pnl: float | None = None
    worst_fold_drawdown: float | None = None
    composite_score: float | None = None
    robustness_grade: str | None = None
    computed_at: str | None = None
    data_as_of: date | None = None
    compute_seconds: float | None = None


class WfoGlobalSignalOut(BaseModel):
    status: str
    global_score_pct: float | None = None
    raw_score_pct: float | None = None
    signal_label: str | None = None
    recommendation: str | None = None
    weight_tendance: float | None = None
    weight_momentum: float | None = None
    weight_oscillation: float | None = None
    weight_volume: float | None = None
    sr_modifier: float | None = None
    sr_support_level: float | None = None
    sr_resistance_level: float | None = None
    sr_support_method: str | None = None
    sr_resistance_method: str | None = None
    best_category: str | None = None
    best_category_score: float | None = None
    categories_viable: int | None = None
    consensus_wfe_pct: float | None = None
    consensus_robustness: float | None = None
    computed_at: str | None = None
    data_as_of: date | None = None


class WfoSummaryResponse(BaseModel):
    symbol: str
    horizon: str
    categories: dict[str, WfoCategorySummaryOut]   # keyed by category name
    global_signal: WfoGlobalSignalOut | None = None


class WfoTriggerRequest(BaseModel):
    symbol: str
    horizon: str
    categories: list[str] | None = None   # None = all 4


class WfoTriggerResponse(BaseModel):
    triggered: list[str]
    job_id: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=WfoSummaryResponse)
def get_wfo_summary(
    symbol: str = Query(...),
    horizon: str = Query(...),
    db: Session = Depends(get_db),
) -> WfoSummaryResponse:
    """Return cached WFO signal results for a symbol × horizon.

    Fast DB read — no computation. Returns whatever is stored,
    including "pending" status for categories not yet computed.
    """
    rows = (
        db.query(WfoSignalSummary)
        .filter_by(symbol=symbol, horizon=horizon)
        .all()
    )

    categories: dict[str, WfoCategorySummaryOut] = {}
    for row in rows:
        categories[row.category] = WfoCategorySummaryOut(
            category=row.category,
            status=row.status,
            score_pct=row.score_pct,
            signal_label=row.signal_label,
            representatives=[
                WfoRepresentativeOut(**r) for r in (row.representatives_json or [])
            ],
            wfe_pct=row.wfe_pct,
            robustness_ratio=row.robustness_ratio,
            total_folds=row.total_folds,
            profitable_folds=row.profitable_folds,
            mean_oos_sharpe=row.mean_oos_sharpe,
            total_oos_pnl=row.total_oos_pnl,
            worst_fold_drawdown=row.worst_fold_drawdown,
            composite_score=row.composite_score,
            robustness_grade=row.robustness_grade,
            computed_at=str(row.computed_at) if row.computed_at else None,
            data_as_of=row.data_as_of,
            compute_seconds=row.compute_seconds,
        )

    # Add "pending" placeholders for missing categories
    for cat in ("tendance", "momentum", "oscillation", "volume"):
        if cat not in categories:
            categories[cat] = WfoCategorySummaryOut(category=cat, status="pending")

    # Global signal
    global_row = (
        db.query(WfoGlobalSignal)
        .filter_by(symbol=symbol, horizon=horizon)
        .first()
    )
    global_out = None
    if global_row:
        global_out = WfoGlobalSignalOut(
            status=global_row.status,
            global_score_pct=global_row.global_score_pct,
            raw_score_pct=global_row.raw_score_pct,
            signal_label=global_row.signal_label,
            recommendation=global_row.recommendation,
            weight_tendance=global_row.weight_tendance,
            weight_momentum=global_row.weight_momentum,
            weight_oscillation=global_row.weight_oscillation,
            weight_volume=global_row.weight_volume,
            sr_modifier=global_row.sr_modifier,
            sr_support_level=global_row.sr_support_level,
            sr_resistance_level=global_row.sr_resistance_level,
            sr_support_method=global_row.sr_support_method,
            sr_resistance_method=global_row.sr_resistance_method,
            best_category=global_row.best_category,
            best_category_score=global_row.best_category_score,
            categories_viable=global_row.categories_viable,
            consensus_wfe_pct=global_row.consensus_wfe_pct,
            consensus_robustness=global_row.consensus_robustness,
            computed_at=str(global_row.computed_at) if global_row.computed_at else None,
            data_as_of=global_row.data_as_of,
        )

    return WfoSummaryResponse(
        symbol=symbol,
        horizon=horizon,
        categories=categories,
        global_signal=global_out,
    )


@router.post("/trigger", response_model=WfoTriggerResponse)
def trigger_wfo_computation(
    body: WfoTriggerRequest,
    db: Session = Depends(get_db),
) -> WfoTriggerResponse:
    """Enqueue WFO computation for a symbol × horizon.

    Uses RQ to enqueue the job asynchronously.
    """
    from redis import Redis
    from rq import Queue

    from services.worker.tasks.wfo_signal_batch import run_wfo_for_symbol_horizon

    categories = body.categories or ["tendance", "momentum", "oscillation", "volume"]

    redis_conn = Redis()   # use app's Redis connection in production
    q = Queue("wfo_signals", connection=redis_conn)
    job = q.enqueue(
        run_wfo_for_symbol_horizon,
        db_session_factory=None,  # worker creates its own session
        symbol=body.symbol,
        horizon=body.horizon,
        job_timeout="30m",
    )

    return WfoTriggerResponse(triggered=categories, job_id=job.id)
```

**Register in `services/api/app/main.py`:**

```python
from .routers.wfo_signals import router as wfo_signals_router
app.include_router(wfo_signals_router)
```

---

## 9. Frontend Components

### 9.1. API Client Functions

**File:** `frontend/lib/api.ts` — add at the end:

```typescript
// ---------------------------------------------------------------------------
// WFO Signal Layer
// ---------------------------------------------------------------------------

export const WfoRepresentativeSchema = z.object({
  family: z.string(),
  archetype: z.string(),
  variant_id: z.string(),
  params: z.record(z.unknown()),
  signal: z.number(),
  signal_label: z.string(),
  normalized_weight: z.number(),
  contribution: z.number(),
  description: z.string(),
  current_close: z.number().nullable().optional(),
  indicator_value: z.number().nullable().optional(),
  explanation: z.string().default(""),
  wfo_prom: z.number().nullable().optional(),
})
export type WfoRepresentative = z.infer<typeof WfoRepresentativeSchema>

export const WfoCategorySummarySchema = z.object({
  category: z.string(),
  status: z.string(),
  score_pct: z.number().nullable().optional(),
  signal_label: z.string().nullable().optional(),
  representatives: z.array(WfoRepresentativeSchema).default([]),
  wfe_pct: z.number().nullable().optional(),
  robustness_ratio: z.number().nullable().optional(),
  total_folds: z.number().nullable().optional(),
  profitable_folds: z.number().nullable().optional(),
  mean_oos_sharpe: z.number().nullable().optional(),
  total_oos_pnl: z.number().nullable().optional(),
  worst_fold_drawdown: z.number().nullable().optional(),
  composite_score: z.number().nullable().optional(),
  robustness_grade: z.string().nullable().optional(),
  computed_at: z.string().nullable().optional(),
  data_as_of: z.string().nullable().optional(),
  compute_seconds: z.number().nullable().optional(),
})
export type WfoCategorySummary = z.infer<typeof WfoCategorySummarySchema>

export const WfoGlobalSignalSchema = z.object({
  status: z.string(),
  global_score_pct: z.number().nullable().optional(),
  raw_score_pct: z.number().nullable().optional(),
  signal_label: z.string().nullable().optional(),
  recommendation: z.string().nullable().optional(),
  weight_tendance: z.number().nullable().optional(),
  weight_momentum: z.number().nullable().optional(),
  weight_oscillation: z.number().nullable().optional(),
  weight_volume: z.number().nullable().optional(),
  sr_modifier: z.number().nullable().optional(),
  sr_support_level: z.number().nullable().optional(),
  sr_resistance_level: z.number().nullable().optional(),
  sr_support_method: z.string().nullable().optional(),
  sr_resistance_method: z.string().nullable().optional(),
  best_category: z.string().nullable().optional(),
  best_category_score: z.number().nullable().optional(),
  categories_viable: z.number().nullable().optional(),
  consensus_wfe_pct: z.number().nullable().optional(),
  consensus_robustness: z.number().nullable().optional(),
  computed_at: z.string().nullable().optional(),
  data_as_of: z.string().nullable().optional(),
})
export type WfoGlobalSignal = z.infer<typeof WfoGlobalSignalSchema>

export const WfoSummaryResponseSchema = z.object({
  symbol: z.string(),
  horizon: z.string(),
  categories: z.record(WfoCategorySummarySchema),
  global_signal: WfoGlobalSignalSchema.nullable().optional(),
})
export type WfoSummaryResponse = z.infer<typeof WfoSummaryResponseSchema>

export async function fetchWfoSummary(
  symbol: string,
  horizon: string,
): Promise<WfoSummaryResponse> {
  const params = new URLSearchParams({ symbol, horizon })
  const res = await fetch(`${API_BASE}/strategy/wfo/summary?${params}`)
  if (!res.ok) throw new Error(`WFO summary fetch failed: ${res.status}`)
  return WfoSummaryResponseSchema.parse(await res.json())
}

export async function triggerWfoComputation(body: {
  symbol: string
  horizon: string
  categories?: string[]
}): Promise<{ triggered: string[]; job_id: string | null }> {
  const res = await fetch(`${API_BASE}/strategy/wfo/trigger`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`WFO trigger failed: ${res.status}`)
  return res.json()
}
```

### 9.2. Data Hook

**File:** `frontend/hooks/use-wfo-summary.ts` (new)

```typescript
"use client"

import { useEffect, useState } from "react"
import { fetchWfoSummary, type WfoSummaryResponse } from "@/lib/api"

export function useWfoSummary(symbol: string | null, horizon: string) {
  const [data, setData] = useState<WfoSummaryResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!symbol) {
      setData(null)
      return
    }

    let cancelled = false
    setIsLoading(true)
    setError(null)

    fetchWfoSummary(symbol, horizon)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })

    return () => { cancelled = true }
  }, [symbol, horizon])

  return { data, isLoading, error }
}
```

### 9.3. WFO Signal Column Component

**File:** `frontend/components/strategy/wfo-signal-column.tsx` (new)

This component is the main WFO column that renders beside the existing A→G column in `TechnicalAnalysisPanel`. It receives the `WfoSummaryResponse` and renders:

1. **Global WFO card** at top (score, recommendation, S/R levels, modifier)
2. **4 category cards** below (one per category, showing score, grade, reps)
3. **Refresh button** + `data_as_of` label

```typescript
"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { RefreshCw } from "lucide-react"
import { formatNumber } from "@/lib/format"
import { triggerWfoComputation, type WfoSummaryResponse, type WfoCategorySummary } from "@/lib/api"
import { SignalScoreBar } from "./signal-score-bar"

type WfoSignalColumnProps = {
  data: WfoSummaryResponse | null
  isLoading: boolean
  error: string | null
  symbol: string
  horizon: string
  onRefresh?: () => void
}

// Grade → color mapping
const GRADE_COLORS: Record<string, string> = {
  A: "bg-green-500",
  B: "bg-green-400",
  C: "bg-yellow-500",
  D: "bg-orange-500",
  F: "bg-red-500",
}

export function WfoSignalColumn({
  data, isLoading, error, symbol, horizon, onRefresh,
}: WfoSignalColumnProps) {
  // ... render global card + 4 category cards + refresh button
  // Each category card shows:
  //   - Category name + grade badge
  //   - SignalScoreBar with score_pct
  //   - WFE % and robustness %
  //   - Expandable list of representatives
  //   - computed_at / data_as_of

  // Refresh handler
  const handleRefresh = async () => {
    await triggerWfoComputation({ symbol, horizon })
    onRefresh?.()
  }

  // ... full JSX implementation
}
```

### 9.4. Integration into TechnicalAnalysisPanel

**File:** `frontend/components/strategy/technical-analysis-panel.tsx`

Add to imports:
```typescript
import { useWfoSummary } from "@/hooks/use-wfo-summary"
import { WfoSignalColumn } from "./wfo-signal-column"
```

Inside the component, add the hook call:
```typescript
const { data: wfoData, isLoading: wfoLoading, error: wfoError } = useWfoSummary(symbol, horizon)
```

In the JSX, render a two-column layout:
```tsx
<div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
  {/* Existing A→G signal column */}
  <div>
    <h3 className="text-sm font-semibold mb-3">Signal Engine (A→G)</h3>
    {/* ... existing speedometer + 4 category cards ... */}
  </div>

  {/* New WFO signal column */}
  <div>
    <h3 className="text-sm font-semibold mb-3">WFO Optimise</h3>
    <WfoSignalColumn
      data={wfoData}
      isLoading={wfoLoading}
      error={wfoError}
      symbol={symbol}
      horizon={horizon}
    />
  </div>
</div>
```

### 9.5. Agreement Badge

**File:** `frontend/components/strategy/signal-agreement-badge.tsx` (new)

```typescript
type Props = {
  engineScore: number | null    // A→G score
  wfoScore: number | null       // WFO score
  wfoGrade: string | null       // "A" | "B" | "C" | "D" | "F"
}

export function SignalAgreementBadge({ engineScore, wfoScore, wfoGrade }: Props) {
  if (engineScore == null || wfoScore == null) return null

  const sameDirection =
    (engineScore > 15 && wfoScore > 15) ||
    (engineScore < -15 && wfoScore < -15) ||
    (Math.abs(engineScore) <= 15 && Math.abs(wfoScore) <= 15)

  const highConfidence = sameDirection && (wfoGrade === "A" || wfoGrade === "B")

  if (highConfidence) {
    return <Badge variant="default" className="bg-green-600">Forte convergence</Badge>
  }
  if (sameDirection) {
    return <Badge variant="secondary">Convergent</Badge>
  }
  return <Badge variant="destructive">Divergent</Badge>
}
```

### 9.6. Rendering in Both Views

The `WfoSignalColumn` must appear in **both** the legacy and expanded views:

- **Expanded view** (`expanded-signals-view.tsx`): Already uses `TechnicalAnalysisPanel` → WFO column is included automatically via the grid layout change above.

- **Legacy view** (`legacy-signals-view.tsx`): This view also uses `TechnicalAnalysisPanel` (or a similar component). Apply the same two-column grid pattern. If legacy uses a different component, add `useWfoSummary` + `WfoSignalColumn` there too.

Both views receive `symbol` and `horizon` props, which are passed through to `useWfoSummary`.

---

## 10. Verification Plan

1. **Unit tests for grid construction:**
   ```python
   # core/tests/test_wfo_signal.py
   def test_build_category_grid_tendance_medium():
       grid = build_category_candidate_grid("tendance", "medium")
       families = {v.family for v in grid}
       assert families == {"sma", "ema", "ema_cross", "ichimoku", "psar"}
       assert len(grid) >= 100  # union of 5 families × ~30 each, minus overlaps
   ```

2. **Unit tests for scoring:**
   ```python
   def test_robustness_grade():
       assert compute_robustness_grade(0.70, 0.80) == "A"
       assert compute_robustness_grade(0.55, 0.60) == "B"
       assert compute_robustness_grade(0.50, 0.50) == "C"
       assert compute_robustness_grade(0.30, 0.30) == "F"
   ```

3. **Integration test — single category WFO:**
   ```python
   def test_wfo_category_signal_sma():
       close = load_test_ohlcv("ATW")["close"].values
       result = run_wfo_category_signal("tendance", "medium", close)
       assert result.status in ("succeeded", "insufficient_data")
       if result.status == "succeeded":
           assert -100 <= result.score_pct <= 100
           assert len(result.representatives) <= 5
           assert result.robustness_grade in ("A", "B", "C", "D", "F")
   ```

4. **API test:**
   ```python
   def test_wfo_summary_endpoint(client):
       resp = client.get("/strategy/wfo/summary?symbol=ATW&horizon=medium")
       assert resp.status_code == 200
       data = resp.json()
       assert "categories" in data
       assert "tendance" in data["categories"]
   ```

5. **Frontend:** Start dev server, navigate to `/signals?symbol=ATW&horizon=medium`, verify:
   - Two-column layout visible in both legacy and expanded views
   - WFO column shows "pending" status if no data computed yet
   - After triggering refresh, column updates with scores and grades
   - Agreement badges appear between columns

6. **Batch test:** Run `run_weekly_wfo_batch()` for a single symbol, verify all 4 categories + global computed and stored in DB.
