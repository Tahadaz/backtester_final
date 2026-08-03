from datetime import date

import pandas as pd
import pytest

from core.quant_core.cross_asset.curve_lab import classify_regime, curve_spreads, dv01_neutral_curve_trade, roll_down_return
from core.quant_core.fixed_income import BondDefinition


def _bond(years):
    return BondDefinition(100, "USD", 0.04, 2, date(2025 + years, 1, 2), "ACT/365F")


def test_dv01_neutral_sizing_reports_residual_and_spread_pnl():
    trade = dv01_neutral_curve_trade(_bond(2), _bond(10), settlement=date(2025, 1, 2), long_ytm=0.04, short_ytm=0.045, long_notional=1_000_000, long_yield_change_bp=-5, short_yield_change_bp=-10)
    assert trade.long_dv01 == pytest.approx(-trade.short_dv01, abs=1e-10)
    assert trade.residual_dv01 == pytest.approx(0.0, abs=1e-10)
    assert trade.total_pnl != 0


def test_roll_down_positive_on_upward_curve_and_spreads():
    assert roll_down_return({2: 0.03, 5: 0.04, 10: 0.05}, maturity_years=5, horizon_years=1, modified_duration=4) > 0
    frame = pd.DataFrame({"DGS2": [0.03], "DGS5": [0.035], "DGS10": [0.045], "DGS30": [0.05]})
    spreads = curve_spreads(frame)
    assert spreads.iloc[0]["2s10s"] == pytest.approx(0.015)
    assert spreads.iloc[0]["5s30s"] == pytest.approx(0.015)


@pytest.mark.parametrize("short_change,long_change,expected", [(-0.02,-0.01,"bull_steepener"),(-0.01,-0.02,"bull_flattener"),(0.01,0.02,"bear_steepener"),(0.02,0.01,"bear_flattener")])
def test_four_regimes(short_change, long_change, expected):
    assert classify_regime(short_change, long_change) == expected
