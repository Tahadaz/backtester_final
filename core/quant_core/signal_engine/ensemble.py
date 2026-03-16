"""Layer G — Ensemble combination + full pipeline entry point.

run_sma_ensemble() orchestrates layers A → B → C → D → E → F → G.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import numpy as np

from .candidates import generate_candidates
from .current_signal import compute_current_signals
from .domain import (
    HORIZON_PARAMS,
    VALID_HORIZONS,
    FamilyCombinedSignal,
    VariantCurrentSignal,
)
from .oos_eval import evaluate_variant_oos
from .redundancy import reduce_redundancy
from .robustness import score_variant_robustness
from .survivor import filter_survivors

# ---------------------------------------------------------------------------
# Layer G — Combine representative signals
# ---------------------------------------------------------------------------


def combine_family_signals(
    signals: list[VariantCurrentSignal],
) -> tuple[float, str, list[dict[str, Any]]]:
    """Reliability-weighted ensemble → (family_score_pct, label, per_rep)."""
    if not signals:
        return 0.0, "NEUTRAL", []

    total_weight = sum(s.reliability_weight for s in signals)
    if total_weight <= 0:
        return 0.0, "NEUTRAL", []

    score_raw = sum(s.signal * s.reliability_weight for s in signals) / total_weight
    score_pct = 100.0 * score_raw

    label = _score_to_label(score_pct)

    per_rep: list[dict[str, Any]] = []
    for s in signals:
        nw = s.reliability_weight / total_weight
        per_rep.append({
            "variant_id": s.variant_id,
            "signal": s.signal,
            "signal_label": s.signal_label,
            "reliability_weight": s.reliability_weight,
            "normalized_weight": round(nw, 4),
            "contribution": round(nw * s.signal, 4),
            "current_close": s.current_close,
            "indicator_value": s.indicator_value,
            "explanation": s.explanation,
        })

    return score_pct, label, per_rep


def _score_to_label(score_pct: float) -> str:
    if score_pct > 50:
        return "STRONG BUY"
    if score_pct > 15:
        return "BUY"
    if score_pct >= -15:
        return "NEUTRAL"
    if score_pct >= -50:
        return "SELL"
    return "STRONG SELL"


# ---------------------------------------------------------------------------
# Full pipeline entry point
# ---------------------------------------------------------------------------


def run_sma_ensemble(
    close: np.ndarray,
    *,
    symbol: str,
    horizon: str = "medium",
    timeframe: str = "1D",
    cost_bps: float = 10.0,
) -> FamilyCombinedSignal:
    """Full A→G pipeline for the SMA family."""
    if horizon not in VALID_HORIZONS:
        raise ValueError(f"Unknown horizon {horizon!r}")

    now_str = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Check minimum data requirements
    hp = HORIZON_PARAMS[horizon]
    min_bars = hp["train"] + hp["test"] + 1
    if len(close) < min_bars:
        return FamilyCombinedSignal(
            family="sma",
            symbol=symbol,
            horizon=horizon,
            timeframe=timeframe,
            family_score_pct=0.0,
            family_signal_label="NEUTRAL",
            tested_count=0,
            viable_count=0,
            competitive_count=0,
            representative_count=0,
            representatives=[],
            score_explanation=f"Insufficient data: {len(close)} bars < {min_bars} required",
            methodology_status="provisional",
            as_of=now_str,
        )

    # Layer A: candidates
    candidates = generate_candidates("sma", horizon)
    tested_count = len(candidates)

    # Layer B + C: OOS evaluation + robustness scoring
    summaries = []
    for c in candidates:
        windows = evaluate_variant_oos(close, c, horizon, cost_bps)
        summary = score_variant_robustness(c, windows)
        summaries.append(summary)

    viable_count = sum(1 for s in summaries if s.is_viable)

    # Layer D: survivor filtering
    survivors = filter_survivors(summaries)
    competitive_count = len(survivors)

    # Edge: no survivors
    if not survivors:
        return FamilyCombinedSignal(
            family="sma",
            symbol=symbol,
            horizon=horizon,
            timeframe=timeframe,
            family_score_pct=0.0,
            family_signal_label="NEUTRAL",
            tested_count=tested_count,
            viable_count=viable_count,
            competitive_count=0,
            representative_count=0,
            representatives=[],
            score_explanation="No variants survived competitive filtering",
            methodology_status="robust_oos_ensemble",
            as_of=now_str,
        )

    # Layer E: redundancy reduction
    representatives = reduce_redundancy(survivors, close)
    representative_count = len(representatives)

    # Layer F: current signals
    current_signals = compute_current_signals(representatives, close)

    # Layer G: ensemble combination
    score_pct, label, per_rep = combine_family_signals(current_signals)

    # Score explanation
    rep_strs = [
        f"{r['explanation']}" for r in per_rep
    ]
    explanation = (
        f"{representative_count} representative(s): "
        + "; ".join(rep_strs)
    )

    return FamilyCombinedSignal(
        family="sma",
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        family_score_pct=round(score_pct, 2),
        family_signal_label=label,
        tested_count=tested_count,
        viable_count=viable_count,
        competitive_count=competitive_count,
        representative_count=representative_count,
        representatives=per_rep,
        score_explanation=explanation,
        methodology_status="robust_oos_ensemble",
        as_of=now_str,
    )
