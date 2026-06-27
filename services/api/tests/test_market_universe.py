from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from services.api.app.services.market_universe import (
    MarketUniverseInstrument,
    dashboard_group_label,
    is_masi_dashboard_member,
    list_market_catalog,
    list_signal_universe_symbols,
)


class _FakeMappingResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, stmt, *_args, **_kwargs):
        statement = str(stmt)
        self.executed.append(statement)
        if "ORDER BY symbol ASC" in statement:
            return _FakeMappingResult(self._rows)
        return _FakeMappingResult([])


def _row(
    symbol: str,
    *,
    display_name: str | None = None,
    sector: str | None = None,
    asset_type: str | None = "equity",
    market_region: str | None = None,
    asset_class: str = "equity",
    has_canonical_data: bool = True,
):
    return {
        "symbol": symbol,
        "display_name": display_name or symbol,
        "isin": None,
        "sector": sector,
        "is_active": True,
        "track_source": "yahoo",
        "bourse_url": None,
        "shares_outstanding": None,
        "shares_as_of": None,
        "shares_source": None,
        "shares_updated_at": None,
        "notes": None,
        "asset_type": asset_type,
        "market_region": market_region,
        "start_ts": dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc),
        "end_ts": dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        "row_count": 250 if has_canonical_data else None,
        "source_provider": "yahoo",
        "data_as_of": dt.date(2026, 1, 1) if has_canonical_data else None,
        "is_tracked": True,
        "has_canonical_data": has_canonical_data,
        "asset_class": asset_class,
    }


def test_signal_universe_contains_all_data_backed_catalog_asset_classes():
    db = _FakeDB(
        [
            _row("ATW", sector="Banks", market_region="masi"),
            _row("BTC-USD", display_name="Bitcoin", asset_type="crypto", asset_class="factor"),
            _row("EURUSD", display_name="EUR/USD", asset_type="forex", asset_class="factor"),
            _row("MAJ", display_name="MAJ"),
            _row("MASI", display_name="MASI Index", market_region="masi", asset_class="index"),
            _row("NODATA", has_canonical_data=False),
            _row("SPY", display_name="SPY", market_region="us"),
            _row("VIX", display_name="VIX", asset_type="equity", market_region="us", asset_class="factor"),
            _row("XAUUSD", display_name="Gold", asset_type="commodity", asset_class="factor"),
        ]
    )

    all_catalog_symbols = [row.symbol for row in list_market_catalog(db, include_without_data=True)]
    signal_symbols = list_signal_universe_symbols(db)

    assert all_catalog_symbols == ["ATW", "BTC-USD", "EURUSD", "MASI", "NODATA", "SPY", "VIX", "XAUUSD"]
    assert signal_symbols == ["ATW", "BTC-USD", "EURUSD", "MASI", "SPY", "VIX", "XAUUSD"]


def test_dashboard_group_and_masi_membership_use_taxonomy_not_stock_master_only():
    masi_equity = MarketUniverseInstrument(
        symbol="ATW",
        display_name="Attijariwafa Bank",
        isin=None,
        sector="Banks",
        is_active=True,
        track_source="bourse_direct",
        bourse_url=None,
        notes=None,
        asset_type="equity",
        market_region="masi",
        asset_class="equity",
    )
    us_factor = MarketUniverseInstrument(
        symbol="VIX",
        display_name="VIX",
        isin=None,
        sector=None,
        is_active=True,
        track_source="yahoo",
        bourse_url=None,
        notes=None,
        asset_type="equity",
        market_region="us",
        asset_class="factor",
    )
    commodity = SimpleNamespace(sector=None, asset_class="factor", asset_type="commodity", market_region=None)

    assert dashboard_group_label(masi_equity) == "Banks"
    assert dashboard_group_label(us_factor) == "US Equity"
    assert dashboard_group_label(commodity) == "Commodity"
    assert is_masi_dashboard_member(masi_equity)
    assert not is_masi_dashboard_member(us_factor)
    assert not is_masi_dashboard_member({"asset_class": "index", "asset_type": "equity", "market_region": "masi"})
