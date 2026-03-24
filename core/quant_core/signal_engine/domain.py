"""Domain objects for the signal generation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Horizon parameters (English keys only — French labels belong in UI)
# ---------------------------------------------------------------------------

HORIZON_PARAMS: dict[str, dict[str, int]] = {
    "short":  {"train": 252, "test": 63,  "step": 63, "max_years": 5},
    "medium": {"train": 504, "test": 126, "step": 126, "max_years": 10},
    "long":   {"train": 756, "test": 252, "step": 252, "max_years": 20},
}

VALID_HORIZONS = frozenset(HORIZON_PARAMS)

# ---------------------------------------------------------------------------
# Signal type taxonomy (Murphy 1999, Elder 1993, Pring 2002)
# ---------------------------------------------------------------------------

FAMILY_SIGNAL_TYPE: dict[str, str] = {
    "sma": "trend",
    "macd": "trend",
    "rsi": "oscillator",
    "obv": "volume",
}

CATEGORY_FAMILIES: dict[str, list[str]] = {
    "tendance": ["sma", "macd"],
    "oscillation": ["rsi"],
    "volume": ["obv"],
}


def signal_type_label(signal_type: str, score_pct: float) -> str:
    """Map (signal_type, score) to type-specific French label.

    Trend → direction (haussier/baissier).
    Oscillator → condition (survendu/suracheté).
    Volume → flow (accumulation/distribution).
    """
    if signal_type == "trend":
        if score_pct > 50:
            return "Très haussier"
        if score_pct > 15:
            return "Haussier"
        if score_pct >= -15:
            return "Neutre"
        if score_pct >= -50:
            return "Baissier"
        return "Très baissier"
    if signal_type == "oscillator":
        if score_pct > 50:
            return "Très survendu"
        if score_pct > 15:
            return "Survendu"
        if score_pct >= -15:
            return "Normal"
        if score_pct >= -50:
            return "Suracheté"
        return "Très suracheté"
    if signal_type == "volume":
        if score_pct > 50:
            return "Forte accumulation"
        if score_pct > 15:
            return "Accumulation"
        if score_pct >= -15:
            return "Neutre"
        if score_pct >= -50:
            return "Distribution"
        return "Forte distribution"
    # fallback (generic aggregate)
    if score_pct > 50:
        return "Achat fort"
    if score_pct > 15:
        return "Achat"
    if score_pct >= -15:
        return "Neutre"
    if score_pct >= -50:
        return "Vente"
    return "Vente forte"


def variant_signal_label(family: str, signal_val: float) -> str:
    """Per-variant current signal label, type-specific."""
    st = FAMILY_SIGNAL_TYPE.get(family, "trend")
    if st == "trend":
        if signal_val > 0:
            return "HAUSSIER"
        if signal_val < 0:
            return "BAISSIER"
        return "NEUTRE"
    if st == "oscillator":
        if signal_val > 0:
            return "SURVENDU"
        if signal_val < 0:
            return "SURACHETÉ"
        return "NORMAL"
    if st == "volume":
        if signal_val > 0:
            return "ACCUMULATION"
        if signal_val < 0:
            return "DISTRIBUTION"
        return "NEUTRE"
    return "BUY" if signal_val > 0 else "SELL" if signal_val < 0 else "HOLD"


_POSITIVE_LABELS = {"HAUSSIER", "SURVENDU", "ACCUMULATION", "BUY"}
_NEGATIVE_LABELS = {"BAISSIER", "SURACHETÉ", "DISTRIBUTION", "SELL"}


def label_to_signal_value(label: str) -> float:
    """Reverse-map type-specific label to numeric signal value."""
    if label in _POSITIVE_LABELS:
        return 1.0
    if label in _NEGATIVE_LABELS:
        return -1.0
    return 0.0


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
    total_return: float = 0.0    # np.prod(1 + oos_returns) - 1
    cagr: float = 0.0            # (1 + total_return)^(252/n_bars) - 1
    pnl: float = 0.0             # 100_000 * total_return


@dataclass(frozen=True)
class MethodologyWindow:
    """Walk-forward window definition used by the signal engine."""
    train: int
    test: int
    step: int
    target_windows: int = 0


@dataclass(frozen=True)
class MethodologyContext:
    """Describes whether the signal used robust, adaptive, or live-only mode."""
    methodology_mode: str
    available_bars: int
    nominal_window: MethodologyWindow
    effective_window: MethodologyWindow
    warning_message: str = ""
    is_provisional: bool = False


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
    sharpe_score: float = 0.0
    stability_score: float = 0.0
    consistency_score: float = 0.0
    drawdown_score: float = 0.0
    cagr: float = 0.0       # mean of window CAGRs
    total_pnl: float = 0.0  # mean of window PnLs


# ---------------------------------------------------------------------------
# Layer F — Current signal
# ---------------------------------------------------------------------------

@dataclass
class VariantCurrentSignal:
    """Current-bar signal for a single variant."""
    variant_id: str
    signal: float              # +1.0, -1.0, or 0.0
    signal_label: str          # type-specific: "HAUSSIER"/"SURVENDU"/"ACCUMULATION" etc.
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
    family_signal_label: str       # type-specific: "Haussier", "Survendu", "Accumulation", etc.
    tested_count: int
    viable_count: int
    competitive_count: int
    representative_count: int
    representatives: list[dict[str, Any]] = field(default_factory=list)
    fallback_variants: list[dict[str, Any]] = field(default_factory=list)
    score_explanation: str = ""
    methodology_status: str = "robust_oos_ensemble"  # or "provisional"
    methodology_mode: str = "robust_oos_ensemble"
    available_bars: int = 0
    nominal_window: MethodologyWindow = field(default_factory=lambda: MethodologyWindow(0, 0, 0))
    effective_window: MethodologyWindow = field(default_factory=lambda: MethodologyWindow(0, 0, 0))
    warning_message: str = ""
    is_provisional: bool = False
    as_of: str = ""
    best_variant_id: str = ""  # highest-reliability variant (for navigation when 0 reps)
    signal_type: str = "trend"     # "trend", "oscillator", "volume"
    category: str = "tendance"     # "tendance", "oscillation", "volume"


# ---------------------------------------------------------------------------
# Pipeline detail (full intermediate data for variant detail endpoint)
# ---------------------------------------------------------------------------

@dataclass
class EnsemblePipelineDetail:
    """Full intermediate data from an A→G pipeline run."""
    signal: FamilyCombinedSignal
    all_summaries: list[VariantRobustnessSummary]
    oos_windows: dict[str, list[OOSWindowResult]]  # variant_id → windows
    survivor_ids: set[str]
    representative_ids: set[str]
    current_signal_labels: dict[str, str] = field(default_factory=dict)       # {variant_id: "BUY"/"SELL"/"HOLD"}
    redundancy_info: dict[str, tuple[str, float]] = field(default_factory=dict)  # {eliminated_id: (corr_with_id, corr_val)}
    correlation_matrix: dict[str, dict[str, float]] = field(default_factory=dict)  # pairwise for survivors
    fallback_variant_ids: set[str] = field(default_factory=set)
