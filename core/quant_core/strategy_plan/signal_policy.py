"""Signal consensus — aggregate per-family scores into a single consensus."""

from __future__ import annotations

from typing import Any


def compute_consensus(
    per_family_scores: dict[str, float],
    enabled_families: list[str],
) -> dict[str, Any]:
    """Compute weighted consensus across enabled signal families.

    Parameters
    ----------
    per_family_scores : dict[str, float]
        Maps family name → score_pct (e.g. ``{"sma": 42.5, "rsi": -18.0}``).
        Families with missing or failed computation are simply absent.
    enabled_families : list[str]
        Which families the user has toggled on (e.g. ``["sma", "rsi", "macd", "obv"]``).

    Returns
    -------
    dict with keys:
        ``final_consensus``  (float | None)
        ``family_weights``   (dict[str, float])
        ``per_family``       (dict[str, dict])   — score_pct + weight per family
    """
    # Collect scores for enabled families that actually produced a result
    available: dict[str, float] = {
        f: per_family_scores[f]
        for f in enabled_families
        if f in per_family_scores
    }

    if not available:
        return {
            "final_consensus": None,
            "family_weights": {},
            "per_family": {},
        }

    # Equal-weight across available families
    weights = {f: 1.0 / len(available) for f in available}

    # Weighted average
    consensus = sum(available[f] * weights[f] for f in available)

    per_family = {
        f: {
            "score_pct": round(available[f], 2),
            "weight": round(weights[f], 4),
        }
        for f in available
    }

    return {
        "final_consensus": round(consensus, 2),
        "family_weights": {f: round(w, 4) for f, w in weights.items()},
        "per_family": per_family,
    }
