"""WFO global consensus signal with S/R modulation.

Aggregates per-category WFO results into a single global score,
then applies S/R proximity modulation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from core.quant_core.signal_engine.domain import signal_type_label
from core.quant_core.signal_engine.wfo_signal import WfoCategoryResult


# ---------------------------------------------------------------------------
# S/R Modulation
# ---------------------------------------------------------------------------

@dataclass
class SRModulationParams:
    """Parameters for S/R modulation (WFO-optimizable in Phase 2)."""
    near_threshold_atr: float = 1.5
    boost_factor: float = 1.15
    dampen_factor: float = 0.85
    far_threshold_atr: float = 4.0

    # WFO scan ranges (reserved for Phase 2)
    SCAN_NEAR   = [0.5, 1.0, 1.5, 2.0, 2.5]
    SCAN_BOOST  = [1.05, 1.10, 1.15, 1.20, 1.30]
    SCAN_DAMPEN = [0.70, 0.80, 0.85, 0.90, 0.95]


def compute_sr_modifier(
    close: float,
    support: float | None,
    resistance: float | None,
    atr: float,
    signal_direction: float,
    params: SRModulationParams,
) -> float:
    """Compute the S/R proximity modifier for the global signal.

    Returns a multiplier in [0.5, 1.5].

    Logic:
    - Close near support  + bullish signal → boost  (support confirms buy)
    - Close near support  + bearish signal → dampen (support contradicts sell)
    - Close near resistance + bearish signal → boost  (resistance confirms sell)
    - Close near resistance + bullish signal → dampen (resistance contradicts buy)
    - Near both or far from both → no modulation
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
# Global consensus result
# ---------------------------------------------------------------------------

@dataclass
class WfoGlobalResult:
    """Result of the global WFO consensus signal."""
    symbol: str
    horizon: str
    status: str
    global_score_pct: float
    raw_score_pct: float
    signal_label: str
    recommendation: str                      # "achat_fort" | "achat" | "neutre" | "vente" | "vente_forte"
    weights: dict[str, float]               # {"tendance": 0.35, ...}
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

    Phase 1: simple weighted average where weights are proportional to
    each category's composite score.  Family-weight WFO optimization is
    deferred to Phase 2.
    """
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

    raw_score = sum(weights[cat] * r.score_pct for cat, r in succeeded.items())

    # S/R modulation
    signal_direction = 1.0 if raw_score > 0 else (-1.0 if raw_score < 0 else 0.0)
    sr_params = SRModulationParams()
    modifier = compute_sr_modifier(
        float(close[-1]), support, resistance, atr, signal_direction, sr_params
    )
    global_score = max(-100.0, min(100.0, raw_score * modifier))

    label = signal_type_label("aggregate", global_score)
    recommendation = _score_to_recommendation(global_score)

    best_cat = max(succeeded, key=lambda c: succeeded[c].composite_score)
    categories_viable = sum(
        1 for r in succeeded.values() if r.robustness_grade in ("A", "B", "C")
    )

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
