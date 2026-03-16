"""Domain objects for the signal generation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Horizon parameters (English keys only — French labels belong in UI)
# ---------------------------------------------------------------------------

HORIZON_PARAMS: dict[str, dict[str, int]] = {
    "short":  {"train": 252, "test": 63,  "step": 21},
    "medium": {"train": 504, "test": 126, "step": 42},
    "long":   {"train": 756, "test": 252, "step": 63},
}

VALID_HORIZONS = frozenset(HORIZON_PARAMS)

# ---------------------------------------------------------------------------
# Layer A — Candidate definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VariantDef:
    """A single signal variant in the candidate universe."""
    variant_id: str       # deterministic hash via compute_trial_id
    family: str           # "sma", "rsi", "macd", "obv"
    archetype: str        # e.g. "price_vs_sma", "sma_cross", "slope_confirmed"
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""


# ---------------------------------------------------------------------------
# Layer B — OOS window result
# ---------------------------------------------------------------------------

@dataclass
class OOSWindowResult:
    """Metrics from a single out-of-sample evaluation window."""
    window_index: int
    train_start: int       # bar index (inclusive)
    train_end: int         # bar index (exclusive)
    test_start: int        # bar index (inclusive)
    test_end: int          # bar index (exclusive)
    n_trades: int
    mean_return_net: float
    sharpe: float
    max_drawdown: float
    fraction_positive_bars: float
    n_bars: int
    is_valid: bool


# ---------------------------------------------------------------------------
# Layer C — Robustness summary
# ---------------------------------------------------------------------------

@dataclass
class VariantRobustnessSummary:
    """Aggregated robustness metrics for a variant across OOS windows."""
    variant: VariantDef
    n_oos_windows: int
    n_valid_windows: int
    mean_sharpe: float
    std_sharpe: float
    median_sharpe: float
    fraction_positive_windows: float
    mean_max_drawdown: float
    reliability_score: float   # [0.0, 1.0]
    is_viable: bool


# ---------------------------------------------------------------------------
# Layer F — Current signal
# ---------------------------------------------------------------------------

@dataclass
class VariantCurrentSignal:
    """Current-bar signal for a single variant."""
    variant_id: str
    signal: float              # +1.0, -1.0, or 0.0
    signal_label: str          # "BUY", "SELL", "HOLD"
    reliability_weight: float
    current_close: float
    indicator_value: float | None
    explanation: str


# ---------------------------------------------------------------------------
# Layer G — Family combined output
# ---------------------------------------------------------------------------

@dataclass
class FamilyCombinedSignal:
    """Full pipeline output for one family × symbol × horizon."""
    family: str
    symbol: str
    horizon: str
    timeframe: str
    family_score_pct: float        # -100.0 to +100.0
    family_signal_label: str       # "STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"
    tested_count: int
    viable_count: int
    competitive_count: int
    representative_count: int
    representatives: list[dict[str, Any]] = field(default_factory=list)
    score_explanation: str = ""
    methodology_status: str = "robust_oos_ensemble"  # or "provisional"
    as_of: str = ""
