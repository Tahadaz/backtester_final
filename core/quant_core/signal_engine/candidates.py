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


# ---------------------------------------------------------------------------
# SMA family — 3 archetypes × horizon-scaled parameter neighborhoods
# ---------------------------------------------------------------------------

_SMA_PRICE_VS_SMA: dict[str, list[int]] = {
    "short":  [5, 10, 15, 20],
    "medium": [20, 30, 50, 75],
    "long":   [50, 100, 150, 200],
}

_SMA_CROSS: dict[str, list[tuple[int, int]]] = {
    "short":  [(5, 20), (10, 30)],
    "medium": [(10, 50), (20, 100)],
    "long":   [(50, 150), (100, 250)],
}

_SMA_SLOPE_CONFIRMED: dict[str, list[tuple[int, int]]] = {
    "short":  [(10, 3), (20, 5)],
    "medium": [(30, 7), (50, 10)],
    "long":   [(100, 20), (150, 30)],
}


def _make_variant(family: str, archetype: str, params: dict, horizon: str) -> VariantDef:
    """Build a VariantDef with a deterministic variant_id."""
    hash_params = {"archetype": archetype, **params}
    variant_id = compute_variant_id(family, hash_params)
    desc_parts = []
    if archetype == "price_vs_sma":
        desc_parts.append(f"SMA-{params['window']} Price-Level")
    elif archetype == "sma_cross":
        desc_parts.append(f"SMA({params['fast']},{params['slow']}) Cross")
    elif archetype == "slope_confirmed":
        desc_parts.append(f"SMA-{params['window']} Slope-Confirmed(k={params['slope_lookback']})")
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
    """Return 8-12 SMA candidates for the given horizon."""
    candidates: list[VariantDef] = []

    for w in _SMA_PRICE_VS_SMA[horizon]:
        candidates.append(_make_variant("sma", "price_vs_sma", {"window": w}, horizon))

    for fast, slow in _SMA_CROSS[horizon]:
        candidates.append(_make_variant("sma", "sma_cross", {"fast": fast, "slow": slow}, horizon))

    for w, k in _SMA_SLOPE_CONFIRMED[horizon]:
        candidates.append(_make_variant("sma", "slope_confirmed", {"window": w, "slope_lookback": k}, horizon))

    return candidates
