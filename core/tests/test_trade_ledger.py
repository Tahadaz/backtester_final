from __future__ import annotations

import pandas as pd
import pytest

from quant_core.fundamentals.cross_section.live_like_strategy import (
    VINTAGE_LIFE_MONTHS,
    build_trade_ledger,
)


def _monthly_dates(n: int, start="2020-01-31"):
    return [d.date() for d in pd.date_range(start, periods=n, freq="ME")]


def test_single_vintage_produces_matching_buy_and_sell_after_six_months():
    dates = _monthly_dates(8)
    holdings_by_date = {dates[0]: {"AAA": 0.5, "BBB": 0.5}}
    holdings_by_date.update({d: {} for d in dates[1:]})
    ledger = build_trade_ledger(holdings_by_date)
    buys = ledger[ledger["action"] == "BUY"]
    sells = ledger[ledger["action"] == "SELL"]
    assert len(buys) == 2
    assert set(buys["symbol"]) == {"AAA", "BBB"}
    assert buys["date"].iloc[0] == dates[0]
    assert len(sells) == 2
    assert sells["date"].iloc[0] == dates[VINTAGE_LIFE_MONTHS]
    assert set(sells["symbol"]) == {"AAA", "BBB"}


def test_weight_is_one_sixth_of_capital_per_constituent():
    dates = _monthly_dates(2)
    holdings_by_date = {dates[0]: {"AAA": 1.0}, dates[1]: {}}
    ledger = build_trade_ledger(holdings_by_date)
    buy_row = ledger[ledger["action"] == "BUY"].iloc[0]
    assert buy_row["weight"] == pytest.approx(1.0 / VINTAGE_LIFE_MONTHS)


def test_no_holdings_produces_empty_ledger():
    dates = _monthly_dates(3)
    holdings_by_date = {d: {} for d in dates}
    ledger = build_trade_ledger(holdings_by_date)
    assert ledger.empty


def test_continuously_held_name_across_vintages_generates_repeated_buys_and_sells():
    """A symbol re-selected every month generates a new BUY each formation and a SELL each
    expiry -- this is real vintage mechanics (each 6-month tranche is independent), not a bug."""
    dates = _monthly_dates(9)
    holdings_by_date = {d: {"AAA": 1.0} for d in dates}
    ledger = build_trade_ledger(holdings_by_date)
    buys = ledger[ledger["action"] == "BUY"]
    sells = ledger[ledger["action"] == "SELL"]
    assert len(buys) == 9
    # first sell happens at dates[VINTAGE_LIFE_MONTHS] when the first vintage expires
    assert sells["date"].min() == dates[VINTAGE_LIFE_MONTHS]
    assert len(sells) == 9 - VINTAGE_LIFE_MONTHS
