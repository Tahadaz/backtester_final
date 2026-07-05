"""Long-only portfolio targets from SFC terciles."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SfcPortfolioMember:
    symbol: str
    tercile: str
    sfc: float | None = None
    benchmark_weight: float | None = None


def sfc_direction(tercile: str | None) -> str:
    token = str(tercile or "").strip().lower()
    if token == "top":
        return "long"
    if token == "bottom":
        return "avoid"
    if token == "middle":
        return "neutral"
    return "unavailable"


def build_sfc_target_weights(
    members: list[SfcPortfolioMember],
    *,
    active_cap: float = 0.03,
    default_benchmark_weight: float | None = None,
) -> dict[str, float]:
    """Return long-only target weights; bottom tercile is always zero.

    The active tilt is bounded per name and never creates a negative weight.
    Weights are intentionally rule-based; no fitting or optimizer is used.
    """
    cleaned = [m for m in members if str(m.symbol or "").strip()]
    if not cleaned:
        return {}
    fallback = default_benchmark_weight
    if fallback is None:
        fallback = 1.0 / len(cleaned)
    cap = max(0.0, float(active_cap))

    raw: dict[str, float] = {}
    for member in cleaned:
        symbol = member.symbol.strip().upper()
        base = member.benchmark_weight if member.benchmark_weight is not None else fallback
        base = max(0.0, float(base))
        direction = sfc_direction(member.tercile)
        if direction == "avoid":
            raw[symbol] = 0.0
        elif direction == "long":
            raw[symbol] = base + cap
        elif direction == "neutral":
            raw[symbol] = base
        else:
            raw[symbol] = 0.0

    total = sum(raw.values())
    if total <= 0:
        return {symbol: 0.0 for symbol in raw}
    return {symbol: weight / total for symbol, weight in raw.items()}
