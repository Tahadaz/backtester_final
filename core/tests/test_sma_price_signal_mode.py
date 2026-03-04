from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_core.data import MarketData  # noqa: E402
from quant_core.indicators import FeaturesData  # noqa: E402
from quant_core.strategy import PriceAboveSMAParams, PriceAboveSMAStrategy  # noqa: E402


def _build_inputs(close_values: list[float], sma_values: list[float], *, sma_window: int) -> tuple[MarketData, FeaturesData]:
    idx = pd.date_range("2025-01-01", periods=len(close_values), freq="D", tz="UTC")
    close = pd.Series(close_values, index=idx, dtype="float64")
    bars = pd.DataFrame(
        {
            "Open": close,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 100_000.0,
        },
        index=idx,
    )
    feats = pd.DataFrame({f"sma_{sma_window}": pd.Series(sma_values, index=idx, dtype="float64")}, index=idx)

    md = MarketData(bars={"IAM": bars}, source="test", timezone="UTC", interval="1d")
    fd = FeaturesData(features={"IAM": feats}, source="test", timezone="UTC", interval="1d")
    return md, fd


def test_sma_price_level_mode_emits_exit_signal_regardless_of_allow_short() -> None:
    # -1.0 is an EXIT signal (close long), not a SHORT signal.
    # allow_short only controls whether the portfolio opens a short position after exit.
    # Both long-only and short-allowed strategies must emit -1.0 when price < SMA.
    md, fd = _build_inputs([100.0, 99.0, 98.0, 97.0], [98.0, 98.0, 98.0, 98.0], sma_window=4)

    strat_long_only = PriceAboveSMAStrategy(
        PriceAboveSMAParams(window=4, allow_short=False, signal_mode="level", nan_policy="flat")
    )
    out_long_only = strat_long_only.generate_signals(md, fd, symbols=["IAM"]).signals["IAM"].tolist()
    assert out_long_only[-1] == -1.0  # exit signal, not short

    strat_with_short = PriceAboveSMAStrategy(
        PriceAboveSMAParams(window=4, allow_short=True, signal_mode="level", nan_policy="flat")
    )
    out_with_short = strat_with_short.generate_signals(md, fd, symbols=["IAM"]).signals["IAM"].tolist()
    assert out_with_short[-1] == -1.0


def test_sma_price_cross_mode_emits_event_signals_only() -> None:
    md, fd = _build_inputs([99.0, 100.0, 101.0, 99.0, 98.0], [100.0, 100.0, 100.0, 100.0, 100.0], sma_window=5)

    strat_cross = PriceAboveSMAStrategy(
        PriceAboveSMAParams(window=5, allow_short=True, signal_mode="cross", nan_policy="flat")
    )
    out = strat_cross.generate_signals(md, fd, symbols=["IAM"]).signals["IAM"].tolist()

    assert out[0] == 0.0
    assert out[1] == 0.0
    assert out[2] == 1.0
    assert out[3] == -1.0
    assert out[4] == 0.0


def test_sma_price_cross_mode_long_only_emits_exit_on_down_cross() -> None:
    # -1.0 is EXIT intent regardless of allow_short; allow_short only affects portfolio
    # execution (whether a short position is opened after the exit).
    md, fd = _build_inputs([99.0, 100.0, 101.0, 99.0], [100.0, 100.0, 100.0, 100.0], sma_window=4)
    strat = PriceAboveSMAStrategy(
        PriceAboveSMAParams(window=4, allow_short=False, signal_mode="cross", nan_policy="flat")
    )
    out = strat.generate_signals(md, fd, symbols=["IAM"]).signals["IAM"].tolist()
    assert out[2] == 1.0
    assert out[3] == -1.0  # down-cross emits exit signal even in long-only mode
