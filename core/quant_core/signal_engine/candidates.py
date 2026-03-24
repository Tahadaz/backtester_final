"""Layer A — Structured candidate universe generation.

The candidate universe is defined as code constants, not computed at runtime.
Each family registers a generator via @register_family.  Adding RSI/MACD/OBV
requires only a new generator function — no infrastructure changes.
"""

from __future__ import annotations

from typing import Callable

from .domain import VALID_HORIZONS, VariantDef
from ._hashing import compute_variant_id

# ---------------------------------------------------------------------------
# Family-agnostic registry
# ---------------------------------------------------------------------------

_CANDIDATE_GENERATORS: dict[str, Callable[[str], list[VariantDef]]] = {}


def register_family(family: str):
    """Decorator: register a candidate generator for *family*."""
    def _wrap(fn: Callable[[str], list[VariantDef]]):
        _CANDIDATE_GENERATORS[family] = fn
        return fn
    return _wrap


def generate_candidates(family: str, horizon: str) -> list[VariantDef]:
    """Public entry: return the admissible candidate universe for *family* × *horizon*."""
    if horizon not in VALID_HORIZONS:
        raise ValueError(f"Unknown horizon {horizon!r}; expected one of {sorted(VALID_HORIZONS)}")
    gen = _CANDIDATE_GENERATORS.get(family)
    if gen is None:
        raise ValueError(f"No candidate generator registered for family {family!r}")
    return gen(horizon)


def variant_min_history(variant: VariantDef) -> int:
    """Minimum bars needed before a variant's signal is reasonably warmed."""
    p = variant.params
    arch = variant.archetype

    if arch == "price_vs_sma":
        return int(p["window"])
    if arch == "sma_cross":
        return int(p["slow"])
    if arch == "slope_confirmed":
        return int(p["window"]) + int(p.get("slope_lookback", 1))
    if arch == "rsi_level":
        return int(p["period"]) + 1
    if arch == "macd_cross":
        return int(p["slow"]) + int(p["signal"])
    if arch == "obv_trend":
        return int(p["ema_period"])
    return 1


def filter_candidates_for_history(candidates: list[VariantDef], max_history: int) -> list[VariantDef]:
    """Keep candidates whose warmup fits inside the provided bar budget."""
    if max_history <= 0:
        return []
    return [c for c in candidates if variant_min_history(c) <= max_history]


# ---------------------------------------------------------------------------
# SMA family — price vs SMA
# ---------------------------------------------------------------------------

_SMA_PRICE_VS_SMA: dict[str, list[int]] = {
    "short":  [3, 5, 7, 8, 10, 12, 13, 15, 17, 18, 20, 22, 25, 28, 30, 33, 35, 38, 40, 42, 45, 48, 50, 55, 60, 65, 70, 75, 80, 90],
    "medium": [10, 15, 18, 20, 25, 28, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120, 130, 140, 150, 160, 175, 190, 200, 225, 250],
    "long":   [20, 30, 40, 50, 60, 75, 85, 100, 110, 120, 125, 130, 140, 150, 160, 170, 175, 190, 200, 210, 225, 240, 250, 270, 280, 300, 325, 350, 375, 400],
}


def _make_variant(family: str, archetype: str, params: dict, horizon: str) -> VariantDef:
    """Build a VariantDef with a deterministic variant_id."""
    hash_params = {"archetype": archetype, **params}
    variant_id = compute_variant_id(family, hash_params)
    desc_parts = []
    if archetype == "price_vs_sma":
        desc_parts.append(f"SMA-{params['window']} Price-Level")
    elif archetype == "rsi_level":
        desc_parts.append(f"RSI-{params['period']} ({params['oversold']}/{params['overbought']})")
    elif archetype == "macd_cross":
        desc_parts.append(f"MACD({params['fast']},{params['slow']},{params['signal']})")
    elif archetype == "obv_trend":
        desc_parts.append(f"OBV-EMA-{params['ema_period']}")
    desc_parts.append(f"({horizon})")
    return VariantDef(
        variant_id=variant_id,
        family=family,
        archetype=archetype,
        params=params,
        description=" ".join(desc_parts),
    )


@register_family("sma")
def generate_sma_candidates(horizon: str) -> list[VariantDef]:
    """Return 30 SMA price-level candidates for the given horizon."""
    candidates: list[VariantDef] = []

    for w in _SMA_PRICE_VS_SMA[horizon]:
        candidates.append(_make_variant("sma", "price_vs_sma", {"window": w}, horizon))

    return candidates


# ---------------------------------------------------------------------------
# RSI family — RSI level (mean-reversion)
# ---------------------------------------------------------------------------

_RSI_PERIODS: dict[str, list[int]] = {
    "short":  [5, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    "medium": [7, 9, 10, 12, 14, 17, 20, 21, 25, 30],
    "long":   [10, 14, 17, 20, 21, 25, 28, 30, 35, 40],
}
_RSI_THRESHOLDS: list[tuple[int, int]] = [(30, 70), (25, 75), (20, 80)]


@register_family("rsi")
def generate_rsi_candidates(horizon: str) -> list[VariantDef]:
    """Return 30 RSI level candidates for the given horizon (10 periods × 3 thresholds)."""
    candidates: list[VariantDef] = []
    for period in _RSI_PERIODS[horizon]:
        for oversold, overbought in _RSI_THRESHOLDS:
            candidates.append(_make_variant("rsi", "rsi_level", {
                "period": period, "oversold": oversold, "overbought": overbought,
            }, horizon))
    return candidates


# ---------------------------------------------------------------------------
# MACD family — MACD line vs signal line crossover
# ---------------------------------------------------------------------------

_MACD_PARAMS: dict[str, dict[str, list[int]]] = {
    "short":  {"fast": [6, 8, 10, 12, 15], "slow": [16, 20, 26], "signal": [7, 9]},
    "medium": {"fast": [8, 10, 12, 15, 18], "slow": [20, 26, 30], "signal": [7, 9]},
    "long":   {"fast": [10, 12, 15, 18, 20], "slow": [26, 30, 35], "signal": [9, 12]},
}


@register_family("macd")
def generate_macd_candidates(horizon: str) -> list[VariantDef]:
    """Return 30 MACD crossover candidates for the given horizon."""
    candidates: list[VariantDef] = []
    mp = _MACD_PARAMS[horizon]
    for fast in mp["fast"]:
        for slow in mp["slow"]:
            for sig in mp["signal"]:
                if fast < slow:
                    candidates.append(_make_variant("macd", "macd_cross", {
                        "fast": fast, "slow": slow, "signal": sig,
                    }, horizon))
    return candidates


# ---------------------------------------------------------------------------
# OBV family — OBV vs EMA(OBV) trend
# ---------------------------------------------------------------------------

_OBV_EMA_PERIODS: dict[str, list[int]] = {
    "short":  [3, 5, 7, 8, 10, 12, 13, 15, 17, 18, 20, 22, 25, 28, 30, 33, 35, 38, 40, 42, 45, 48, 50, 55, 60, 65, 70, 75, 80, 90],
    "medium": [10, 15, 18, 20, 25, 28, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120, 130, 140, 150, 160, 175, 190, 200, 225, 250],
    "long":   [20, 30, 40, 50, 60, 75, 85, 100, 110, 120, 125, 130, 140, 150, 160, 170, 175, 190, 200, 210, 225, 240, 250, 270, 280, 300, 325, 350, 375, 400],
}


@register_family("obv")
def generate_obv_candidates(horizon: str) -> list[VariantDef]:
    """Return 30 OBV-EMA trend candidates for the given horizon."""
    return [_make_variant("obv", "obv_trend", {"ema_period": p}, horizon)
            for p in _OBV_EMA_PERIODS[horizon]]
