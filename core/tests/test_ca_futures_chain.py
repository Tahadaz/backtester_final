from datetime import date

import pandas as pd

from quant_core.cross_asset.futures_chain import build_futures_chain
from quant_core.cross_asset.instruments import FuturesContract


def _contract(symbol, expiry, first_notice, rule):
    return FuturesContract(symbol=symbol, asset_class="commodity", currency="USD", quote_convention="USD/contract", root="GC", expiry=expiry, first_notice=first_notice, roll_rule=rule, tick_size=0.1)


def test_first_notice_and_n_day_rules_never_hold_into_delivery():
    dates = pd.date_range("2025-01-01", "2025-01-12")
    contracts = [
        _contract("GCF25", date(2025, 1, 15), date(2025, 1, 10), "first_notice"),
        _contract("GCG25", date(2025, 2, 15), date(2025, 2, 10), "n_days_before_expiry:5"),
    ]
    result = build_futures_chain(contracts, dates)
    assert result.held_contract.loc["2025-01-09"] == "GCF25"
    assert result.held_contract.loc["2025-01-10"] == "GCG25"
    assert date(2025, 1, 10) in result.roll_dates


def test_volume_crossover_rolls_and_contract_gap_is_explicit():
    dates = pd.date_range("2025-01-06", periods=5)
    contracts = [
        _contract("CLF25", date(2025, 1, 20), date(2025, 1, 15), "volume_crossover"),
        _contract("CLG25", date(2025, 2, 20), date(2025, 2, 15), "first_notice"),
    ]
    volumes = pd.DataFrame({"CLF25": [100, 90, 80, 70, 60], "CLG25": [50, 70, 90, 100, 110]}, index=dates)
    prices = pd.DataFrame({"CLF25": [70, 71, 72, 73, 74], "CLG25": [71, 72, None, 74, 75]}, index=dates)
    result = build_futures_chain(contracts, dates, prices=prices, volumes=volumes)
    assert result.held_contract.iloc[1] == "CLF25"
    assert pd.isna(result.held_contract.iloc[2])
    assert result.held_contract.iloc[3] == "CLG25"
    assert any("gap left missing" in warning for warning in result.warnings)
