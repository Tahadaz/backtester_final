"""Domain objects for the signal generation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.quant_core.horizons import HORIZON_PARAMS, VALID_HORIZONS

# ---------------------------------------------------------------------------
# Horizon-aware parameter caps (A.1.d)
# Prevents slow-warmup indicators from appearing in short/medium horizon searches.
# Keys map family → the single "governing" param that determines warmup length.
# ---------------------------------------------------------------------------

#: Maximum allowed value for the governing parameter of each family × horizon.
#  short  — enforces that warmup stays inside a typical 3-month data window
#  medium — filters oversized MAs from medium-horizon universe (SMA/EMA > 50 excluded)
#  long   — set at grid maximums; effectively no filtering for long-horizon searches
HORIZON_PARAM_CAP: dict[str, dict[str, int]] = {
    "short":  {"sma": 20,  "ema": 20,  "rsi": 14, "macd_slow": 20,  "stoch": 14, "obv_ema": 20,  "ichimoku_kijun": 26},
    "medium": {"sma": 50,  "ema": 50,  "rsi": 28, "macd_slow": 45,  "stoch": 28, "obv_ema": 80,  "ichimoku_kijun": 40},
    "long":   {"sma": 250, "ema": 250, "rsi": 50, "macd_slow": 100, "stoch": 50, "obv_ema": 250, "ichimoku_kijun": 80},
}
# Canonical horizon aliases share the same caps as their base horizon.
for _alias, _base in (("weekly", "short"), ("monthly", "medium"), ("quarterly", "long")):
    HORIZON_PARAM_CAP[_alias] = HORIZON_PARAM_CAP[_base]


def cap_param_grid(values: list[int], cap: int) -> list[int]:
    """Return *values* filtered to those ≤ *cap*.

    Raises ValueError if the result is empty — the caller must ensure the
    underlying grid contains at least one value within the cap before calling.
    """
    result = [v for v in values if v <= cap]
    if not result:
        raise ValueError(
            f"cap_param_grid: no values in {values} are ≤ cap={cap}"
        )
    return result


# ---------------------------------------------------------------------------
# Signal type taxonomy (Murphy 1999, Elder 1993, Pring 2002)
# ---------------------------------------------------------------------------

FAMILY_SIGNAL_TYPE: dict[str, str] = {
    # Trend
    "sma": "trend",
    "ema": "trend",
    "ema_cross": "trend",
    "ichimoku": "trend",
    "psar": "trend",
    # Momentum
    "macd": "momentum",
    "roc": "momentum",
    "trix": "momentum",
    "adx": "momentum",
    "tsi": "momentum",
    # Oscillator
    "rsi": "oscillator",
    "stochastic": "oscillator",
    "cci": "oscillator",
    "mfi": "oscillator",
    "uo": "oscillator",
    # Volume
    "obv": "volume",
    "cmf": "volume",
    "ad": "volume",
    "vwap": "volume",
    "fi": "volume",
}

CATEGORY_FAMILIES: dict[str, list[str]] = {
    "tendance": ["sma", "ema", "ema_cross", "ichimoku", "psar"],
    "momentum": ["macd", "roc", "trix", "adx", "tsi"],
    "oscillation": ["rsi", "stochastic", "cci", "mfi", "uo"],
    "volume": ["obv", "cmf", "ad", "vwap", "fi"],
}

LEGACY_CATEGORY_FAMILIES: dict[str, list[str]] = {
    "tendance": ["sma"],
    "momentum": ["macd"],
    "oscillation": ["rsi"],
    "volume": ["obv"],
}

VARIANT_FAMILIES: dict[str, dict[str, list[str]]] = {
    "legacy": LEGACY_CATEGORY_FAMILIES,
    "expanded": CATEGORY_FAMILIES,
}

ALL_FAMILIES: tuple[str, ...] = tuple(
    family
    for category in ("tendance", "momentum", "oscillation", "volume")
    for family in CATEGORY_FAMILIES[category]
)


def signal_type_label(signal_type: str, score_pct: float) -> str:
    """Map (signal_type, score) to type-specific French label."""
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
    if signal_type == "momentum":
        if score_pct > 50:
            return "Fort momentum haussier"
        if score_pct > 15:
            return "Momentum haussier"
        if score_pct >= -15:
            return "Pas de momentum"
        if score_pct >= -50:
            return "Momentum baissier"
        return "Fort momentum baissier"
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
    # Factor-conditioned variants have family="{ta_family}@fx"; strip suffix.
    base_family = family.split("@")[0] if "@" in family else family
    st = FAMILY_SIGNAL_TYPE.get(base_family, "trend")
    if st == "trend":
        if signal_val > 0:
            return "HAUSSIER"
        if signal_val < 0:
            return "BAISSIER"
        return "NEUTRE"
    if st == "momentum":
        if signal_val > 0:
            return "MOMENTUM HAUSSIER"
        if signal_val < 0:
            return "MOMENTUM BAISSIER"
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


_POSITIVE_LABELS = {
    "HAUSSIER",
    "MOMENTUM HAUSSIER",
    "SURVENDU",
    "ACCUMULATION",
    "BUY",
}
_NEGATIVE_LABELS = {
    "BAISSIER",
    "MOMENTUM BAISSIER",
    "SURACHETÉ",
    "DISTRIBUTION",
    "SELL",
}


def label_to_signal_value(label: str) -> float:
    """Reverse-map type-specific label to numeric signal value."""
    if label in _POSITIVE_LABELS:
        return 1.0
    if label in _NEGATIVE_LABELS:
        return -1.0
    return 0.0


# ---------------------------------------------------------------------------
# Layer A - Candidate definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactorConditionMeta:
    """Metadata for a factor-based conditioning rule used in Phase 2 cross-product variants.

    A factor-conditioned TA variant fires its underlying signal only when this
    condition evaluates to True on the same evaluation date (AND composition,
    with calendar-aware lag applied upstream — see research/alignment.py).
    """

    condition_id: str    # e.g. "vix_z20_below_neg1"
    factor_ticker: str   # e.g. "^VIX"
    form: str            # "zscore" | "momentum" | "change" | "level" | "direction"
    lookback: int        # bars for rolling window (1 for "direction")
    threshold: float     # comparison threshold (0.0 for momentum/direction)
    direction: str       # "below" | "above"


@dataclass(frozen=True)
class VariantDef:
    """A single signal variant in the candidate universe."""

    variant_id: str
    family: str
    archetype: str
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    # Phase 2: optional factor condition; None for native TA variants.
    # compare=False, hash=False so existing variant_id-based identity is unchanged.
    factor_condition: FactorConditionMeta | None = field(
        default=None, compare=False, hash=False
    )


# ---------------------------------------------------------------------------
# Layer B - OOS window result
# ---------------------------------------------------------------------------


@dataclass
class OOSWindowResult:
    """Metrics from a single out-of-sample evaluation window."""

    window_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    n_trades: int
    mean_return_net: float
    sharpe: float
    max_drawdown: float
    fraction_positive_bars: float
    n_bars: int
    is_valid: bool
    total_return: float = 0.0
    cagr: float = 0.0
    pnl: float = 0.0


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
# Layer C - Robustness summary
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
    reliability_score: float
    is_viable: bool
    sharpe_score: float = 0.0
    stability_score: float = 0.0
    consistency_score: float = 0.0
    drawdown_score: float = 0.0
    cagr: float = 0.0
    total_pnl: float = 0.0


# ---------------------------------------------------------------------------
# Layer F - Current signal
# ---------------------------------------------------------------------------


@dataclass
class VariantCurrentSignal:
    """Current-bar signal for a single variant."""

    variant_id: str
    signal: float
    signal_label: str
    reliability_weight: float
    current_close: float
    indicator_value: float | None
    explanation: str


# ---------------------------------------------------------------------------
# Layer G - Family combined output
# ---------------------------------------------------------------------------


@dataclass
class FamilyCombinedSignal:
    """Full pipeline output for one family x symbol x horizon."""

    family: str
    symbol: str
    horizon: str
    timeframe: str
    family_score_pct: float
    family_signal_label: str
    tested_count: int
    viable_count: int
    competitive_count: int
    representative_count: int
    representatives: list[dict[str, Any]] = field(default_factory=list)
    fallback_variants: list[dict[str, Any]] = field(default_factory=list)
    score_explanation: str = ""
    methodology_status: str = "robust_oos_ensemble"
    methodology_mode: str = "robust_oos_ensemble"
    available_bars: int = 0
    nominal_window: MethodologyWindow = field(default_factory=lambda: MethodologyWindow(0, 0, 0))
    effective_window: MethodologyWindow = field(default_factory=lambda: MethodologyWindow(0, 0, 0))
    warning_message: str = ""
    is_provisional: bool = False
    as_of: str = ""
    latest_close: float | None = None
    best_variant_id: str = ""
    signal_type: str = "trend"
    category: str = "tendance"


# ---------------------------------------------------------------------------
# Pipeline detail (full intermediate data for variant detail endpoint)
# ---------------------------------------------------------------------------


@dataclass
class EnsemblePipelineDetail:
    """Full intermediate data from an A->G pipeline run."""

    signal: FamilyCombinedSignal
    all_summaries: list[VariantRobustnessSummary]
    oos_windows: dict[str, list[OOSWindowResult]]
    survivor_ids: set[str]
    representative_ids: set[str]
    current_signal_labels: dict[str, str] = field(default_factory=dict)
    redundancy_info: dict[str, tuple[str, float]] = field(default_factory=dict)
    correlation_matrix: dict[str, dict[str, float]] = field(default_factory=dict)
    fallback_variant_ids: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Layer H - Regime detection result
# ---------------------------------------------------------------------------


@dataclass
class RegimeResult:
    """Result of OOS-validated regime detection via Kaufman Efficiency Ratio."""

    regime_active: bool
    regime_label: str
    regime_weights: dict[str, float]
    er_value: float | None
    improvement: float
    tercile_bounds: tuple[float, float]
    window_results: list[dict[str, Any]]
    n_families: int
