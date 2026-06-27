from __future__ import annotations

import types

import pandas as pd

from services.api.app.routers import analytics


def test_macro_backtest_replay_builds_factor_chart_ledger_and_equity() -> None:
    dates = pd.bdate_range("2026-01-01", periods=7)
    stock_prices = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 103.0, 102.0],
            "Close": [100.0, 102.0, 103.0, 104.0, 103.0, 101.0, 100.0],
        },
        index=dates,
    )
    stock_close = stock_prices["Close"]
    factor = pd.Series([20.0, 19.0, 18.5, 21.0, 22.0, 21.5, 20.0], index=dates)
    signal = pd.Series([0.0, 1.0, 1.0, 0.0, -1.0, -1.0, 0.0], index=dates)
    forward_returns = stock_close.pct_change(fill_method=None).shift(-1)
    spec = types.SimpleNamespace(factor_id="VIX", signal_name="vix_zscore", requires=("VIX",))

    replay = analytics._build_macro_backtest_replay(
        stock_prices=stock_prices,
        close_col="Close",
        open_col="Open",
        stock_close=stock_close,
        aligned_factors={"VIX": factor},
        signal=signal,
        spec=spec,
        forward_returns=forward_returns,
        return_method="close_to_close",
        cost_bps=0.0,
    )

    assert replay is not None
    assert replay["factor_id"] == "VIX"
    assert replay["dates"][0] == "2026-01-01"
    assert len(replay["stock_close"]) == len(replay["equity"])
    assert len(replay["factor_close"]) == len(replay["equity"])
    assert replay["trade_ledger"]
    assert [row["side"] for row in replay["trade_ledger"][:4]] == ["ACHAT", "VENTE", "VENTE", "ACHAT"]
    assert replay["trade_ledger"][0]["factor_value"] == 19.0
    assert replay["equity"][-1] is not None
    assert replay["drawdown"][-1] is not None
