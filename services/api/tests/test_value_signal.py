from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from services.api.app.services.value_signal import (
    TRUSTED_UNIVERSE_EXCLUSIONS,
    _exclusion_reasons,
    _is_missing,
    value_signal_row_to_dict,
)
from core.quant_core.fundamentals.cross_section.live_like_strategy import eligibility_mask


def _panel(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df = eligibility_mask(df)
    df["exclusion_reasons"] = df.apply(_exclusion_reasons, axis=1)
    return df


def test_is_missing_handles_nan_not_just_none():
    """Regression test: pandas stores missing floats as NaN, not None -- an earlier version
    of this code used `is None` and silently failed to flag NaN values as missing."""
    assert _is_missing(np.nan)
    assert _is_missing(None)
    assert not _is_missing(0.0)
    assert not _is_missing(1.5)


def test_financial_sector_cfp_exclusion_reason_surfaces():
    panel = _panel(
        [
            {
                "symbol": "ATW",
                "as_of_date": dt.date(2026, 7, 6),
                "close": 100.0,
                "market_cap_raw": 1e9,
                "book_to_market_raw": 0.5,
                "cashflow_price_raw": None,  # excluded because is_financial
                "is_financial": True,
                "_book_equity": 5e8,
            }
        ]
    )
    row = panel.iloc[0]
    reasons = _exclusion_reasons(row)
    assert any("bank/insurance" in r for r in reasons)
    d = value_signal_row_to_dict(row)
    assert d["cfp_applicable"] is False
    assert d["eligible_cfp"] is False
    assert d["eligible_bm"] is True


def test_negative_book_equity_exclusion_reason_surfaces():
    panel = _panel(
        [
            {
                "symbol": "SNA",
                "as_of_date": dt.date(2026, 7, 6),
                "close": 50.0,
                "market_cap_raw": 2e8,
                "book_to_market_raw": None,  # excluded: negative book equity
                "cashflow_price_raw": 0.1,
                "is_financial": False,
                "_book_equity": -1e7,
            }
        ]
    )
    row = panel.iloc[0]
    reasons = _exclusion_reasons(row)
    assert any("Negative book equity" in r for r in reasons)
    d = value_signal_row_to_dict(row)
    assert d["eligible_bm"] is False
    assert d["eligible_cfp"] is True


def test_sah_is_excluded_from_trusted_universe_with_reason():
    assert "SAH" in TRUSTED_UNIVERSE_EXCLUSIONS
    panel = _panel(
        [
            {
                "symbol": "SAH",
                "as_of_date": dt.date(2026, 7, 6),
                "close": 2765.0,
                "market_cap_raw": 1.1e10,
                "book_to_market_raw": 0.2,
                "cashflow_price_raw": None,
                "is_financial": True,
                "_book_equity": 2e9,
            }
        ]
    )
    row = panel.iloc[0]
    d = value_signal_row_to_dict(row)
    assert d["eligible_universe"] is False
    assert d["eligible_bm"] is False
    assert any("SAH" in r for r in d["exclusion_reasons"])
    # Raw value is still surfaced (not hidden as a false zero), only trust is flagged.
    assert d["bm_raw"] == pytest.approx(0.2)


def test_eligible_row_has_no_exclusion_reasons():
    panel = _panel(
        [
            {
                "symbol": "REB",
                "as_of_date": dt.date(2026, 7, 6),
                "close": 95.0,
                "market_cap_raw": 1.7e7,
                "book_to_market_raw": 1.5,
                "cashflow_price_raw": 0.03,
                "is_financial": False,
                "_book_equity": 2.5e7,
            }
        ]
    )
    row = panel.iloc[0]
    assert _exclusion_reasons(row) == []
    d = value_signal_row_to_dict(row)
    assert d["eligible_bm"] is True
    assert d["eligible_cfp"] is True
    assert d["exclusion_reasons"] == []


def test_missing_price_produces_exclusion_reason():
    panel = _panel(
        [
            {
                "symbol": "XYZ",
                "close": None,
                "market_cap_raw": None,
                "book_to_market_raw": None,
                "cashflow_price_raw": None,
                "is_financial": False,
                "_book_equity": None,
            }
        ]
    )
    row = panel.iloc[0]
    reasons = _exclusion_reasons(row)
    assert any("price" in r for r in reasons)
    assert any("market cap" in r for r in reasons)
