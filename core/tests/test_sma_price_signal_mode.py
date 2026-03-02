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


def test_sma_price_level_mode_respects_allow_short_flag() -> None:
    md, fd = _build_inputs([100.0, 99.0, 98.0, 97.0], [98.0, 98.0, 98.0, 98.0], sma_window=4)

    strat_long_only = PriceAboveSMAStrategy(
        PriceAboveSMAParams(window=4, allow_short=False, signal_mode="level", nan_policy="flat")
    )
    out_long_only = strat_long_only.generate_signals(md, fd, symbols=["IAM"]).signals["IAM"].tolist()
    assert out_long_only[-1] == 0.0

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


def test_sma_price_cross_mode_long_only_blocks_short_cross() -> None:
    md, fd = _build_inputs([99.0, 100.0, 101.0, 99.0], [100.0, 100.0, 100.0, 100.0], sma_window=4)
    strat = PriceAboveSMAStrategy(
        PriceAboveSMAParams(window=4, allow_short=False, signal_mode="cross", nan_policy="flat")
    )
    out = strat.generate_signals(md, fd, symbols=["IAM"]).signals["IAM"].tolist()
    assert out[2] == 1.0
    assert out[3] == 0.0
