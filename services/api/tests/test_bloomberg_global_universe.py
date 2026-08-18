"""W1: global universe resolution in the Bloomberg bridge job spec.

The load-bearing test here is the MASI regression -- global support must not
change a single byte of an existing Moroccan job spec.
"""

from __future__ import annotations

import typing

import pytest

from core.quant_core.cross_asset import universes
from core.quant_core.cross_asset.security_master import get as sm_get
from services.api.app.routers.bloomberg_bridge import (
    _build_job_spec,
    _symbol_to_bloomberg_candidates,
)
from services.api.app.schemas.bloomberg import BloombergJobCreateIn, BloombergUniverse


def _spec(**kwargs):
    return _build_job_spec(BloombergJobCreateIn(**kwargs))


# ---------------------------------------------------------------------------
# MASI regression -- the invariant that keeps the Moroccan pipeline untouched
# ---------------------------------------------------------------------------


def test_masi_candidates_are_unchanged():
    assert _symbol_to_bloomberg_candidates("ATW") == ["ATW MA Equity", "ATW MC Equity"]
    assert _symbol_to_bloomberg_candidates("ATW", "masi") == ["ATW MA Equity", "ATW MC Equity"]
    assert _symbol_to_bloomberg_candidates("") == []


def test_masi_job_spec_is_byte_identical_to_the_legacy_shape():
    spec = _spec(universe="selected", symbols=["ATW", "IAM"])
    assert spec["security_candidates"] == [
        {"symbol": "ATW", "candidates": ["ATW MA Equity", "ATW MC Equity"]},
        {"symbol": "IAM", "candidates": ["IAM MA Equity", "IAM MC Equity"]},
    ]
    assert spec["securities"] == ["ATW MA Equity", "IAM MA Equity"]
    assert spec["universe"] == "selected"


@pytest.mark.parametrize("universe", ["masi", "selected", "custom", "bonds"])
def test_short_canonical_ids_do_not_hijack_moroccan_tickers(universe):
    """`C`, `S`, `W`, `G`, `Z`, `US` are registry ids AND plausible tickers.

    Universe-scoped resolution is what stops the registry shadowing them.
    """
    for symbol in ("C", "S", "W", "G", "Z", "US", "CL", "TU"):
        assert _symbol_to_bloomberg_candidates(symbol, universe) == [
            f"{symbol} MA Equity",
            f"{symbol} MC Equity",
        ]


# ---------------------------------------------------------------------------
# Global universes
# ---------------------------------------------------------------------------


def test_schema_literal_matches_the_quant_core_universe_names():
    literal_values = set(typing.get_args(BloombergUniverse))
    assert set(universes.UNIVERSE_NAMES) <= literal_values
    # The Moroccan/ad-hoc values must survive too.
    assert {"masi", "selected", "custom", "bonds"} <= literal_values


def test_global_universe_auto_populates_symbols_from_the_registry():
    spec = _spec(universe="g10_fx")
    assert spec["symbols"] == list(universes.G10_FX)
    assert spec["security_candidates"][0] == {
        "symbol": "EURUSD",
        "candidates": ["EURUSD Curncy", "EUR Curncy"],
    }
    assert spec["securities"][0] == "EURUSD Curncy"


def test_global_all_covers_every_registry_instrument():
    spec = _spec(universe="global_all")
    assert spec["symbols"] == list(universes.GLOBAL_ALL)
    assert len(spec["security_candidates"]) == len(universes.GLOBAL_ALL)
    # Every probed security is the preferred ticker from the master.
    for item in spec["security_candidates"]:
        entry = sm_get(item["symbol"])
        assert item["candidates"] == list(entry.bloomberg_candidates)


@pytest.mark.parametrize("universe", sorted(universes.UNIVERSE_NAMES))
def test_every_global_universe_produces_a_complete_spec(universe):
    spec = _spec(universe=universe)
    assert spec["symbols"], f"{universe} resolved to no symbols"
    assert spec["securities"], f"{universe} resolved to no securities"
    assert len(spec["securities"]) == len(spec["symbols"])
    assert all(item["candidates"] for item in spec["security_candidates"])


def test_explicit_symbols_still_win_over_universe_expansion():
    spec = _spec(universe="commodities", symbols=["CL", "GC"])
    assert spec["symbols"] == ["CL", "GC"]
    assert spec["securities"] == ["CL1 Comdty", "GC1 Comdty"]


def test_unknown_symbol_in_a_global_universe_yields_no_candidates():
    spec = _spec(universe="g10_fx", symbols=["NOTREAL"])
    assert spec["security_candidates"] == [{"symbol": "NOTREAL", "candidates": []}]
    # It must not silently fall back to the Moroccan suffix guess.
    assert spec["securities"] == []
