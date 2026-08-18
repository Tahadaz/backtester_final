"""Named instrument sets over the security master.

These names are what the Bloomberg bridge, the strategy specs and the frontend
all address instruments by, so that adding an asset class means adding a value
here rather than a new code path (cross-asset program guardrail #7).
"""

from __future__ import annotations

from .security_master import REGISTRY, SecurityMasterEntry, by_asset_class


G10_FX = tuple(entry.canonical_id for entry in by_asset_class("fx"))
SOVEREIGN_RATES = tuple(entry.canonical_id for entry in by_asset_class("rates"))
CREDIT = tuple(entry.canonical_id for entry in by_asset_class("credit"))
COMMODITIES = tuple(entry.canonical_id for entry in by_asset_class("commodity"))
EQUITY_INDEX = tuple(entry.canonical_id for entry in by_asset_class("equity_index"))
GLOBAL_ALL = tuple(entry.canonical_id for entry in REGISTRY)

UNIVERSES: dict[str, tuple[str, ...]] = {
    "g10_fx": G10_FX,
    "sovereign_rates": SOVEREIGN_RATES,
    "credit": CREDIT,
    "commodities": COMMODITIES,
    "equity_index": EQUITY_INDEX,
    "global_all": GLOBAL_ALL,
}

UNIVERSE_NAMES: tuple[str, ...] = tuple(UNIVERSES)


def resolve(name: str) -> tuple[str, ...]:
    """Canonical ids for a named universe. Raises KeyError on an unknown name."""
    key = str(name or "").strip().lower()
    try:
        return UNIVERSES[key]
    except KeyError:
        raise KeyError(f"unknown universe {name!r}; known: {UNIVERSE_NAMES}") from None


def entries(name: str) -> tuple[SecurityMasterEntry, ...]:
    """Full entries for a named universe, in registry order."""
    from .security_master import get

    return tuple(get(cid) for cid in resolve(name))


def is_global_universe(name: str) -> bool:
    return str(name or "").strip().lower() in UNIVERSES
