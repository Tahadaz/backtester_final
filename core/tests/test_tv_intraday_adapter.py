from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

pytest.importorskip("tvDatafeed")

from tvDatafeed import Interval  # noqa: E402

from core.quant_core.tv_intraday_adapter import TradingViewIntradayAdapter  # noqa: E402


def _fake_hist_frame(symbol: str, n: int = 10) -> pd.DataFrame:
    idx = pd.date_range("2026-06-01", periods=n, freq="h", tz=None)
    return pd.DataFrame(
        {
            "symbol": [f"CSEMA:{symbol}"] * n,
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "volume": [1000 + i for i in range(n)],
        },
        index=idx,
    )


def test_load_impl_maps_interval_and_calls_get_hist():
    mock_tv_instance = MagicMock()
    mock_tv_instance.get_hist.side_effect = lambda **kwargs: _fake_hist_frame(kwargs["symbol"])

    with patch(
        "core.quant_core.tv_intraday_adapter.TvDatafeed",
        return_value=mock_tv_instance,
    ) as mock_tv_cls:
        adapter = TradingViewIntradayAdapter(exchange="CSEMA")
        out = adapter._load_impl(["ATW", "IAM"], None, None, "1h", n_bars=5000)

    # One anonymous session created, reused across both symbols.
    mock_tv_cls.assert_called_once_with()
    assert mock_tv_instance.get_hist.call_count == 2

    for call in mock_tv_instance.get_hist.call_args_list:
        assert call.kwargs["exchange"] == "CSEMA"
        assert call.kwargs["interval"] == Interval.in_1_hour
        assert call.kwargs["n_bars"] == 5000

    assert set(out.keys()) == {"ATW", "IAM"}
    for df in out.values():
        assert not df.empty
        assert "close" in df.columns


def test_load_roundtrips_through_standardize_and_validate():
    """Full .load() path (which runs _standardize_ohlcv + _validate_ohlcv) should
    succeed cleanly against the raw lowercase tvdatafeed-style columns."""
    mock_tv_instance = MagicMock()
    mock_tv_instance.get_hist.side_effect = lambda **kwargs: _fake_hist_frame(kwargs["symbol"])

    with patch(
        "core.quant_core.tv_intraday_adapter.TvDatafeed",
        return_value=mock_tv_instance,
    ):
        adapter = TradingViewIntradayAdapter(exchange="CSEMA", timezone="UTC")
        market_data = adapter.load(symbols=["ATW"], interval="1h", n_bars=100)

    df = market_data.get("ATW")
    assert list(df.columns[:5]) == ["Open", "High", "Low", "Close", "Volume"]
    assert df.index.is_monotonic_increasing
    assert df.index.tz is not None
    assert (df["High"] >= df["Low"]).all()


def test_load_impl_skips_symbol_on_exception_without_crashing_batch():
    mock_tv_instance = MagicMock()

    def _side_effect(**kwargs):
        if kwargs["symbol"] == "BOOM":
            raise RuntimeError("simulated network failure")
        return _fake_hist_frame(kwargs["symbol"])

    mock_tv_instance.get_hist.side_effect = _side_effect

    with patch(
        "core.quant_core.tv_intraday_adapter.TvDatafeed",
        return_value=mock_tv_instance,
    ):
        adapter = TradingViewIntradayAdapter(exchange="CSEMA")
        out = adapter._load_impl(["ATW", "BOOM", "IAM"], None, None, "1h", n_bars=5000)

    assert set(out.keys()) == {"ATW", "IAM"}


def test_unsupported_interval_raises():
    mock_tv_instance = MagicMock()
    with patch(
        "core.quant_core.tv_intraday_adapter.TvDatafeed",
        return_value=mock_tv_instance,
    ):
        adapter = TradingViewIntradayAdapter(exchange="CSEMA")
        with pytest.raises(ValueError):
            adapter._load_impl(["ATW"], None, None, "5m", n_bars=100)
