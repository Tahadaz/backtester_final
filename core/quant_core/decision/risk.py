from __future__ import annotations

import math
from typing import Any


def _rr_score(rr: float) -> float:
    if rr >= 2.0:
        return 90.0
    if rr >= 1.5:
        return 70.0
    if rr >= 1.0:
        return 50.0
    return 25.0


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def compute_rr_and_invalidation(
    *,
    direction: int,
    entry: float | None,
    stop: float | None,
    target: float | None,
) -> dict[str, Any]:
    entry_f = _safe_float(entry)
    stop_f = _safe_float(stop)
    target_f = _safe_float(target)
    if entry_f is None or stop_f is None or target_f is None or direction == 0:
        return {
            "rr": 0.0,
            "risk_per_share": None,
            "reward_per_share": None,
            "score": 20.0,
            "invalidation": "No directional setup; wait for a trade signal.",
            "levels_valid": False,
            "invalid_reason": "missing_levels_or_neutral_direction",
            "inputs": {"entry": entry_f, "stop": stop_f, "target": target_f, "direction": direction},
            "thresholds": {"high": 2.0, "medium": 1.5, "low": 1.0},
            "explain": "Risk/reward requires non-neutral direction and valid levels.",
        }

    invalid_reason = None
    if direction > 0:
        if target_f <= entry_f:
            invalid_reason = "invalid_long_target_orientation"
        elif stop_f >= entry_f:
            invalid_reason = "invalid_long_stop_orientation"
        if invalid_reason is None:
            risk = max(0.0, entry_f - stop_f)
            reward = max(0.0, target_f - entry_f)
            invalidation = f"Long invalidation: close <= stop ({stop_f:.4f})."
        else:
            risk = 0.0
            reward = 0.0
            invalidation = "Invalid long setup: target must be above entry and stop below entry."
    else:
        if target_f >= entry_f:
            invalid_reason = "invalid_short_target_orientation"
        elif stop_f <= entry_f:
            invalid_reason = "invalid_short_stop_orientation"
        if invalid_reason is None:
            risk = max(0.0, stop_f - entry_f)
            reward = max(0.0, entry_f - target_f)
            invalidation = f"Short invalidation: close >= stop ({stop_f:.4f})."
        else:
            risk = 0.0
            reward = 0.0
            invalidation = "Invalid short setup: target must be below entry and stop above entry."

    if invalid_reason is not None:
        return {
            "rr": 0.0,
            "risk_per_share": risk,
            "reward_per_share": reward,
            "score": 10.0,
            "invalidation": invalidation,
            "levels_valid": False,
            "invalid_reason": invalid_reason,
            "inputs": {"entry": entry_f, "stop": stop_f, "target": target_f, "direction": direction},
            "thresholds": {"high": 2.0, "medium": 1.5, "low": 1.0},
            "explain": f"Invalid risk levels orientation ({invalid_reason}); reward/risk disabled.",
        }

    rr = float(reward / risk) if risk > 0 else 0.0
    rr_score = _rr_score(rr)

    return {
        "rr": rr,
        "risk_per_share": risk,
        "reward_per_share": reward,
        "score": rr_score,
        "invalidation": invalidation,
        "levels_valid": True,
        "invalid_reason": None,
        "inputs": {"entry": entry_f, "stop": stop_f, "target": target_f, "direction": direction},
        "thresholds": {"high": 2.0, "medium": 1.5, "low": 1.0},
        "explain": "Risk score is mapped from reward/risk ratio using fixed thresholds.",
    }
