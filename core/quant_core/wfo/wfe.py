from __future__ import annotations

from dataclasses import dataclass
from math import prod


@dataclass(frozen=True)
class ReturnWindow:
    is_return: float
    oos_return: float
    is_bars: int
    oos_bars: int


def annualize_returns(returns: list[float], bars: int, *, bars_per_year: int = 252) -> float:
    if bars <= 0:
        raise ValueError("bars must be positive")
    compounded = prod(1.0 + value for value in returns)
    if compounded <= 0:
        return -1.0
    return compounded ** (bars_per_year / bars) - 1.0


def compute_wfe(windows: list[ReturnWindow], *, bars_per_year: int = 252) -> float:
    if not windows:
        return 0.0
    is_annualized = annualize_returns(
        [window.is_return for window in windows],
        sum(window.is_bars for window in windows),
        bars_per_year=bars_per_year,
    )
    if is_annualized <= 0:
        return 0.0
    oos_annualized = annualize_returns(
        [window.oos_return for window in windows],
        sum(window.oos_bars for window in windows),
        bars_per_year=bars_per_year,
    )
    return oos_annualized / is_annualized


def compute_robustness_ratio(oos_returns: list[float]) -> float:
    if not oos_returns:
        return 0.0
    return sum(1 for value in oos_returns if value > 0) / len(oos_returns)


def compute_single_window_dominance(oos_returns: list[float]) -> float:
    magnitudes = [abs(value) for value in oos_returns]
    total = sum(magnitudes)
    if total == 0:
        return 0.0
    return max(magnitudes) / total

