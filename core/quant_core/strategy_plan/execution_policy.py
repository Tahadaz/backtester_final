"""Execution-horizon policy for level detection and trade geometry."""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_EXECUTION_HOLDING_BARS: dict[str, int] = {
    "short": 10,
    "medium": 30,
    "long": 60,
}


@dataclass(frozen=True)
class ExecutionHorizonPolicy:
    horizon: str
    timeframe: str
    holding_bars: int
    structural_lookback: int
    swing_left_bars: int
    swing_right_bars: int
    max_levels: int
    max_level_distance_atr: float


def default_execution_holding_bars(horizon: str) -> int:
    """Return the deterministic default execution holding horizon."""
    return DEFAULT_EXECUTION_HOLDING_BARS.get(horizon, DEFAULT_EXECUTION_HOLDING_BARS["medium"])


def resolve_execution_holding_bars(
    horizon: str,
    holding_bars: int | None = None,
) -> int:
    """Resolve explicit override or deterministic horizon default."""
    if holding_bars is None:
        return default_execution_holding_bars(horizon)
    return max(2, int(holding_bars))


def build_execution_horizon_policy(
    horizon: str,
    *,
    timeframe: str = "1D",
    holding_bars: int | None = None,
) -> ExecutionHorizonPolicy:
    """Build a deterministic execution policy from holding bars."""
    resolved_holding_bars = resolve_execution_holding_bars(horizon, holding_bars)

    structural_lookback = min(252, max(30, resolved_holding_bars * 4))

    if resolved_holding_bars <= 15:
        swing_bars = 2
        max_levels = 4
    elif resolved_holding_bars <= 45:
        swing_bars = 3
        max_levels = 6
    else:
        swing_bars = 5
        max_levels = 8

    max_level_distance_atr = min(12.0, max(4.0, 2.0 + resolved_holding_bars / 5.0))

    return ExecutionHorizonPolicy(
        horizon=horizon,
        timeframe=timeframe,
        holding_bars=resolved_holding_bars,
        structural_lookback=structural_lookback,
        swing_left_bars=swing_bars,
        swing_right_bars=swing_bars,
        max_levels=max_levels,
        max_level_distance_atr=max_level_distance_atr,
    )
