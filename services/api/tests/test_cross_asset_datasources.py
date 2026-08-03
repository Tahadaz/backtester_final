from datetime import date

import pandas as pd
import pytest

from services.api.app.services.cross_asset.datasources import FRED_RATE_SERIES, FX_PAIRS, assemble_fx_panel, assemble_rates_panel


def _spot_loader(tickers, start, end):
    index = pd.date_range(start, periods=8)
    return {ticker: pd.Series([1.0 + i * 0.001 for i in range(8)], index=index) for ticker in tickers}


def _rate_loader(series_id, key, start, end):
    assert key == "test-key"
    index = pd.date_range(start, periods=6)
    known = list(FRED_RATE_SERIES.values()) + ["DGS2", "DGS5", "DGS10", "DGS30"]
    offset = known.index(series_id) / 1000
    return pd.Series(0.03 + offset, index=index)


def test_mocked_yfinance_and_fred_assemble_without_forward_fill_and_surface_staleness():
    result = assemble_fx_panel(
        start=date(2025, 1, 1),
        end=date(2025, 1, 10),
        fred_api_key="test-key",
        spot_loader=_spot_loader,
        rate_loader=_rate_loader,
    )
    assert set(result.panel.columns.get_level_values(0)) == set(FX_PAIRS)
    assert result.panel[("EURUSD", "r_base")].isna().sum() == 2
    assert any("no forward-fill" in warning for warning in result.warnings)
    assert result.staleness_days["rate:EUR"] == 4
    assert result.panel.xs("carry", axis=1, level=1).max(axis=1).dropna().le(0.5).all()


def test_missing_fred_key_fails_loudly(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FRED_API_KEY is required"):
        assemble_fx_panel(spot_loader=_spot_loader, rate_loader=_rate_loader)


def test_dgs_rates_panel_is_decimal_unfilled_and_model_labelled():
    result = assemble_rates_panel(start=date(2025, 1, 1), end=date(2025, 1, 10), fred_api_key="test-key", rate_loader=_rate_loader)
    assert ("DGS10", "par_yield") in result.panel
    assert result.panel[("DGS10", "par_yield")].isna().sum() == 0
    assert any("Duration-approximated" in warning for warning in result.warnings)
