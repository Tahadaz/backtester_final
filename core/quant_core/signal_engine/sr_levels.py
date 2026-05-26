from __future__ import annotations

from typing import Any, Mapping

import numpy as np


PIVOT_LINE_ORDER: tuple[str, ...] = ("S3", "S2", "S1", "P", "R1", "R2", "R3")
PIVOT_METHOD_ORDER: tuple[str, ...] = (
    "pivot_points",
    "fibonacci_pivot",
    "camarilla",
    "woodie",
    "dm",
)


def finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not np.isfinite(out):
        return None
    return out


def round_level(value: Any, digits: int = 6) -> float | None:
    out = finite_float(value)
    if out is None:
        return None
    return round(out, digits)


def normalize_line_id(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    return token.replace(" ", "_").replace("/", "_").upper()


def compute_pivot_family_levels(
    method_id: str,
    *,
    prev_high: float,
    prev_low: float,
    prev_close: float,
    prev_open: float | None = None,
) -> dict[str, float]:
    """Return line-aware pivot levels for the requested pivot family.

    Output keys are uppercase line ids: P, S1..S3, R1..R3 when that family can
    validly compute them. DeMark intentionally exposes only P/S1/R1.
    """
    high = finite_float(prev_high)
    low = finite_float(prev_low)
    close = finite_float(prev_close)
    open_ = finite_float(prev_open)
    if high is None or low is None or close is None:
        return {}
    if high < low:
        high, low = low, high
    rng = high - low
    if rng < 0:
        return {}

    method = str(method_id or "").strip().lower()
    levels: dict[str, float] = {}

    if method in {"pivot_points", "classic", "classic_pivot"}:
        p = (high + low + close) / 3.0
        levels = {
            "P": p,
            "S1": 2.0 * p - high,
            "S2": p - rng,
            "S3": low - 2.0 * (high - p),
            "R1": 2.0 * p - low,
            "R2": p + rng,
            "R3": high + 2.0 * (p - low),
        }
    elif method in {"fibonacci_pivot", "fib_pivot"}:
        p = (high + low + close) / 3.0
        levels = {
            "P": p,
            "S1": p - 0.382 * rng,
            "S2": p - 0.618 * rng,
            "S3": p - 1.000 * rng,
            "R1": p + 0.382 * rng,
            "R2": p + 0.618 * rng,
            "R3": p + 1.000 * rng,
        }
    elif method == "camarilla":
        factor = 1.1 * rng
        levels = {
            "P": (high + low + close) / 3.0,
            "S1": close - factor / 12.0,
            "S2": close - factor / 6.0,
            "S3": close - factor / 4.0,
            "R1": close + factor / 12.0,
            "R2": close + factor / 6.0,
            "R3": close + factor / 4.0,
        }
    elif method == "woodie":
        p = (high + low + 2.0 * close) / 4.0
        levels = {
            "P": p,
            "S1": 2.0 * p - high,
            "S2": p - rng,
            "S3": low - 2.0 * (high - p),
            "R1": 2.0 * p - low,
            "R2": p + rng,
            "R3": high + 2.0 * (p - low),
        }
    elif method in {"dm", "demark", "demark_pivot"}:
        if open_ is None:
            return {}
        if close < open_:
            x = high + 2.0 * low + close
        elif close > open_:
            x = 2.0 * high + low + close
        else:
            x = high + low + 2.0 * close
        levels = {
            "P": x / 4.0,
            "S1": x / 2.0 - high,
            "R1": x / 2.0 - low,
        }

    ordered = {
        line: round(float(levels[line]), 6)
        for line in PIVOT_LINE_ORDER
        if line in levels and finite_float(levels[line]) is not None
    }
    return ordered


def split_support_resistance_lines(
    levels: Mapping[str, Any],
    reference_price: float,
) -> tuple[dict[str, float], dict[str, float]]:
    """Split arbitrary line levels into valid support and resistance maps."""
    ref = finite_float(reference_price)
    if ref is None:
        return {}, {}
    support: dict[str, float] = {}
    resistance: dict[str, float] = {}
    for raw_line, raw_value in levels.items():
        line = normalize_line_id(raw_line)
        value = round_level(raw_value, 6)
        if not line or value is None:
            continue
        if value <= ref:
            support[line] = value
        if value >= ref:
            resistance[line] = value
    return support, resistance


def nearest_support_resistance_from_lines(
    levels: Mapping[str, Any],
    reference_price: float,
) -> tuple[float | None, float | None, str | None, str | None]:
    support, resistance = split_support_resistance_lines(levels, reference_price)
    support_line: str | None = None
    resistance_line: str | None = None
    support_value: float | None = None
    resistance_value: float | None = None
    if support:
        support_line, support_value = max(support.items(), key=lambda item: item[1])
    if resistance:
        resistance_line, resistance_value = min(resistance.items(), key=lambda item: item[1])
    return support_value, resistance_value, support_line, resistance_line
