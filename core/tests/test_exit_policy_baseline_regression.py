"""Regression test: Policy A must reproduce stored pnl_return exactly.

Uses synthetic fixtures so no DB connection is required.
Invariant: simulate_A(path).effective_return == path.pnl_return for every path.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.quant_core.research.exit_policy.paths import TradePath, reconstruct_trade_paths
from core.quant_core.research.exit_policy.policies import simulate_A
from core.quant_core.research.exit_policy.portfolio import run_policy_portfolio


def _ohlcv(
    n_bars: int = 30,
    *,
    start: str = "2023-01-01",
    base_price: float = 100.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Synthetic daily OHLCV."""
    rng = np.random.default_rng(seed)
    closes = base_price * np.cumprod(1 + rng.normal(0, 0.01, n_bars))
    highs = closes * (1 + rng.uniform(0, 0.02, n_bars))
    lows = closes * (1 - rng.uniform(0, 0.02, n_bars))
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    dates = pd.date_range(start, periods=n_bars, freq="B")
    return pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": 0.0}, index=dates)


def _trade(
    open_date: str,
    close_date: str,
    *,
    open_price: float = 100.0,
    close_price: float = 102.0,
    pnl_return: float = 0.02,
    direction: float = 1.0,
) -> dict:
    return {
        "open_date": open_date,
        "close_date": close_date,
        "open_price": open_price,
        "close_price": close_price,
        "pnl_return": pnl_return,
        "direction": direction,
    }


class TestPolicyABaseline:
    """Policy A must return stored pnl_return unchanged (regression anchor)."""

    def test_single_long_trade(self):
        ohlcv = _ohlcv(30)
        trades = [_trade("2023-01-02", "2023-01-09", pnl_return=0.03)]
        paths = reconstruct_trade_paths(trades, ohlcv, symbol="TEST", compute_sr=False)
        assert len(paths) == 1
        result = simulate_A(paths[0])
        assert result.effective_return == pytest.approx(paths[0].pnl_return)
        assert result.exit_reason == "signal_exit"
        assert result.exit_date == paths[0].close_date

    def test_negative_return_preserved(self):
        ohlcv = _ohlcv(30)
        trades = [_trade("2023-01-02", "2023-01-06", pnl_return=-0.04)]
        paths = reconstruct_trade_paths(trades, ohlcv, symbol="TEST", compute_sr=False)
        assert paths
        result = simulate_A(paths[0])
        assert result.effective_return == pytest.approx(-0.04)

    def test_multiple_trades_all_preserved(self):
        ohlcv = _ohlcv(60)
        trade_defs = [
            _trade("2023-01-02", "2023-01-06", pnl_return=0.02),
            _trade("2023-01-09", "2023-01-13", pnl_return=-0.015),
            _trade("2023-01-16", "2023-01-20", pnl_return=0.035),
        ]
        paths = reconstruct_trade_paths(trade_defs, ohlcv, symbol="TEST", compute_sr=False)
        for path, trade_def in zip(paths, trade_defs):
            result = simulate_A(path)
            assert result.effective_return == pytest.approx(trade_def["pnl_return"]), (
                f"Policy A changed pnl_return for trade {trade_def['open_date']}"
            )

    def test_short_trade_preserved(self):
        ohlcv = _ohlcv(30)
        trades = [_trade("2023-01-02", "2023-01-09", pnl_return=0.025, direction=-1.0)]
        paths = reconstruct_trade_paths(trades, ohlcv, symbol="TEST", compute_sr=False)
        assert paths
        result = simulate_A(paths[0])
        assert result.effective_return == pytest.approx(0.025)

    def test_portfolio_sim_with_policy_a(self):
        """Portfolio sim with Policy A: equity grows by compounding stored returns."""
        ohlcv = _ohlcv(80)
        trade_defs = [
            _trade("2023-01-02", "2023-01-06", pnl_return=0.03),
            _trade("2023-01-09", "2023-01-13", pnl_return=-0.02),
            _trade("2023-01-16", "2023-01-20", pnl_return=0.04),
            _trade("2023-01-23", "2023-01-27", pnl_return=0.01),
            _trade("2023-01-30", "2023-02-03", pnl_return=-0.015),
        ]
        paths = reconstruct_trade_paths(trade_defs, ohlcv, symbol="TEST", compute_sr=False)
        assert len(paths) == len(trade_defs)

        result = run_policy_portfolio(paths, simulate_A)
        assert "equity" in result
        assert "metrics" in result
        assert len(result["equity"]) == len(paths) + 1  # starts at 1.0
        assert result["equity"][0] == pytest.approx(1.0)
        # Equity should compound up/down with each trade
        assert result["metrics"]["n_trades"] == len(paths)


class TestPathReconstruction:
    """Reconstruction guards: trades outside OHLCV window are dropped."""

    def test_trade_before_ohlcv_window_is_dropped(self):
        ohlcv = _ohlcv(30, start="2023-03-01")
        trades = [_trade("2023-01-02", "2023-01-06", pnl_return=0.02)]
        paths = reconstruct_trade_paths(trades, ohlcv, symbol="TEST", compute_sr=False)
        assert len(paths) == 0

    def test_valid_trade_in_ohlcv_window_is_kept(self):
        ohlcv = _ohlcv(60, start="2023-01-01")
        trades = [_trade("2023-01-02", "2023-01-06", pnl_return=0.02)]
        paths = reconstruct_trade_paths(trades, ohlcv, symbol="TEST", compute_sr=False)
        assert len(paths) == 1

    def test_atr_is_non_negative(self):
        ohlcv = _ohlcv(60, start="2023-01-01")
        trades = [_trade("2023-02-01", "2023-02-06", pnl_return=0.02)]
        paths = reconstruct_trade_paths(trades, ohlcv, symbol="TEST", compute_sr=False)
        assert paths
        assert paths[0].atr_entry >= 0.0

    def test_mae_is_negative_or_zero_for_long(self):
        ohlcv = _ohlcv(60, start="2023-01-01")
        trades = [_trade("2023-01-02", "2023-01-09", pnl_return=0.02)]
        paths = reconstruct_trade_paths(trades, ohlcv, symbol="TEST", compute_sr=False)
        assert paths
        assert paths[0].mae <= 0.0  # adverse excursion is non-positive for longs

    def test_mfe_is_non_negative_for_long(self):
        ohlcv = _ohlcv(60, start="2023-01-01")
        trades = [_trade("2023-01-02", "2023-01-09", pnl_return=0.02)]
        paths = reconstruct_trade_paths(trades, ohlcv, symbol="TEST", compute_sr=False)
        assert paths
        assert paths[0].mfe >= 0.0
