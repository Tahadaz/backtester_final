"""W1 ship-gate tests for the global security master."""

import ast
import pathlib
from datetime import date

import pytest

from quant_core.cross_asset import security_master as sm
from quant_core.cross_asset import universes
from quant_core.cross_asset.instruments import FuturesContract, FxPair


FUTURES_CLASSES = {"rates", "commodity", "equity_index"}


def test_registry_has_no_duplicate_canonical_ids():
    ids = [entry.canonical_id for entry in sm.REGISTRY]
    assert len(ids) == len(set(ids))


def test_registry_size_is_within_the_declared_cap():
    # G8: no access constraint means the discipline is liquidity/data quality.
    # The plan caps the starting universe at 40-60 instruments.
    assert 40 <= len(sm.REGISTRY) <= 60


@pytest.mark.parametrize("entry", sm.REGISTRY, ids=lambda e: e.canonical_id)
def test_every_entry_resolves_bloomberg_and_declares_a_free_path(entry):
    assert entry.bloomberg_candidates, f"{entry.canonical_id} has no Bloomberg candidate"
    assert all(str(t).strip() for t in entry.bloomberg_candidates)
    # G9: a free path, or an explicit reason there is none.
    if entry.free_proxy is None:
        assert entry.free_proxy_note, f"{entry.canonical_id} must state why it has no free proxy"
    else:
        assert entry.free_proxy_source != "none"


@pytest.mark.parametrize("entry", sm.REGISTRY, ids=lambda e: e.canonical_id)
def test_every_entry_carries_engine_metadata_and_regime_boundary(entry):
    assert entry.asset_class
    assert entry.currency
    assert entry.point_value > 0
    # G11: the regime boundary is data, not an accident of what downloaded.
    assert isinstance(entry.history_start, date)
    assert entry.history_note.strip()


@pytest.mark.parametrize(
    "entry", [e for e in sm.REGISTRY if e.asset_class in FUTURES_CLASSES], ids=lambda e: e.canonical_id
)
def test_futures_entries_carry_a_roll_rule_the_engine_accepts(entry):
    assert entry.roll_rule is not None, f"{entry.canonical_id} is a future with no roll rule"
    # Construct the real engine object: FuturesContract.__post_init__ is the
    # authority on which roll rules are valid, so this cannot drift.
    contract = FuturesContract(
        symbol=entry.canonical_id,
        asset_class=entry.asset_class,
        currency=entry.currency,
        quote_convention=entry.quote_convention,
        point_value=entry.point_value,
        root=entry.canonical_id,
        roll_rule=entry.roll_rule,
        tick_size=entry.tick_size or 0.01,
    )
    assert contract.roll_rule == entry.roll_rule


@pytest.mark.parametrize("entry", sm.by_asset_class("fx"), ids=lambda e: e.canonical_id)
def test_fx_entries_construct_a_valid_fx_pair(entry):
    pair = FxPair(
        symbol=entry.canonical_id,
        asset_class="fx",
        currency=entry.currency,
        quote_convention=entry.quote_convention,
        base_ccy=entry.base_ccy,
        quote_ccy=entry.quote_ccy,
    )
    assert pair.base_ccy and pair.quote_ccy


def test_fx_canonical_ids_match_the_existing_fx_vertical():
    # Kept byte-identical to FX_PAIRS in
    # services/api/app/services/cross_asset/datasources.py:11 so the shipped FX
    # vertical resolves through the registry without changing its data.
    expected = {
        "EURUSD": "EURUSD=X",
        "USDJPY": "JPY=X",
        "GBPUSD": "GBPUSD=X",
        "USDCHF": "CHF=X",
        "AUDUSD": "AUDUSD=X",
        "USDCAD": "CAD=X",
        "NZDUSD": "NZDUSD=X",
        "USDNOK": "NOK=X",
        "USDSEK": "SEK=X",
    }
    assert sm.free_proxy_map(list(expected)) == expected


def test_lookup_helpers():
    assert sm.get("eurusd").canonical_id == "EURUSD"
    assert sm.get(" TY ").canonical_id == "TY"
    assert sm.find("NOPE") is None
    with pytest.raises(KeyError):
        sm.get("NOPE")


def test_instruments_without_free_path_are_enumerable():
    dark = sm.instruments_without_free_path()
    # G9 requires knowing exactly what goes dark without Bloomberg.
    assert all(entry.free_proxy is None for entry in dark)
    assert all(entry.free_proxy_note for entry in dark)


def test_unverified_entries_are_flagged_for_live_sizing():
    unverified = sm.unverified_for_live_sizing()
    # Nothing is terminal-confirmed yet, so every entry must be flagged until
    # the W1 discovery report lands.
    assert len(unverified) == len(sm.REGISTRY)


def test_credit_is_marked_as_the_entitlement_risk():
    credit = sm.by_asset_class("credit")
    assert credit
    assert all("entitlement_risk" in entry.tags for entry in credit)
    assert all(not entry.bloomberg_verified for entry in credit)


def test_named_universes_resolve_and_cover_the_registry():
    assert set(universes.GLOBAL_ALL) == {entry.canonical_id for entry in sm.REGISTRY}
    covered = (
        set(universes.G10_FX)
        | set(universes.SOVEREIGN_RATES)
        | set(universes.CREDIT)
        | set(universes.COMMODITIES)
        | set(universes.EQUITY_INDEX)
    )
    assert covered == set(universes.GLOBAL_ALL)
    assert universes.resolve("g10_fx") == universes.G10_FX
    assert universes.is_global_universe("global_all")
    assert not universes.is_global_universe("masi")
    with pytest.raises(KeyError):
        universes.resolve("nope")


def test_universe_entries_are_registry_objects():
    assert universes.entries("credit") == sm.by_asset_class("credit")


def test_security_master_is_import_pure():
    """No SQLAlchemy, no FastAPI, no network client -- it is imported everywhere."""
    source = pathlib.Path(sm.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    forbidden = {"sqlalchemy", "fastapi", "requests", "httpx", "yfinance", "pandas", "numpy"}
    assert not (imported & forbidden), f"security_master must stay pure; found {imported & forbidden}"


def test_validation_rejects_malformed_entries():
    base = dict(
        canonical_id="XX",
        asset_class="commodity",
        description="test",
        currency="USD",
        history_start=date(2000, 1, 1),
        history_note="test",
        bloomberg_candidates=("XX1 Comdty",),
        free_proxy="XX=F",
        free_proxy_source="yfinance",
        free_proxy_note="test",
    )
    sm.SecurityMasterEntry(**base)  # sanity: the baseline is valid

    with pytest.raises(ValueError, match="Bloomberg candidate"):
        sm.SecurityMasterEntry(**{**base, "bloomberg_candidates": ()})
    with pytest.raises(ValueError, match="history_note"):
        sm.SecurityMasterEntry(**{**base, "history_note": ""})
    with pytest.raises(ValueError, match="free_proxy_note"):
        sm.SecurityMasterEntry(**{**base, "free_proxy": None, "free_proxy_note": ""})
    with pytest.raises(ValueError, match="free_proxy_source"):
        sm.SecurityMasterEntry(**{**base, "free_proxy_source": "none"})
    with pytest.raises(ValueError, match="roll_rule"):
        sm.SecurityMasterEntry(**{**base, "roll_rule": "whenever"})
    with pytest.raises(ValueError, match="point_value"):
        sm.SecurityMasterEntry(**{**base, "point_value": 0.0})
    with pytest.raises(ValueError, match="base_ccy"):
        sm.SecurityMasterEntry(**{**base, "asset_class": "fx"})
