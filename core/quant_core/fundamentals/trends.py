from __future__ import annotations

from math import isfinite
from typing import Any


PILLAR_KEYS = ("value", "quality", "growth", "risk", "cash_flow", "health")
TREND_MIN_ROWS = 3
TREND_MAX_ROWS = 4
ON_TRACK_MIN_SCORE = 70.0
BEHIND_MAX_SCORE = 40.0
ON_TRACK_MIN_SLOPE = -2.0
BEHIND_MAX_SLOPE = -5.0


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _pillar_value(row: dict[str, Any], pillar: str) -> float | None:
    return _num(row.get(f"{pillar}_score") if f"{pillar}_score" in row else row.get(pillar))


def _slope(values: list[float]) -> float:
    n = len(values)
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom <= 0:
        return 0.0
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values)) / denom


def classify_pillar_trend(history: list[dict[str, Any]], pillar: str) -> str:
    if pillar not in PILLAR_KEYS:
        raise ValueError(f"unknown pillar: {pillar}")
    newest_first = [_pillar_value(row, pillar) for row in history]
    values = [value for value in newest_first if value is not None][:TREND_MAX_ROWS]
    if len(values) < TREND_MIN_ROWS:
        return "insufficient_data"
    chronological = list(reversed(values))
    latest_score = chronological[-1]
    slope = _slope(chronological)
    if latest_score >= ON_TRACK_MIN_SCORE and slope >= ON_TRACK_MIN_SLOPE:
        return "on_track"
    if slope <= BEHIND_MAX_SLOPE or latest_score < BEHIND_MAX_SCORE:
        return "behind"
    return "watch"


def classify_all_pillar_trends(history: list[dict[str, Any]]) -> dict[str, str]:
    return {pillar: classify_pillar_trend(history, pillar) for pillar in PILLAR_KEYS}
