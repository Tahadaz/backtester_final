from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_core.plots import plot_price_indicators_trades_line  # noqa: E402
from quant_core.results import ResultsAnalyzer  # noqa: E402


def _bars() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=12, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "Open": np.linspace(100.0, 111.0, len(idx)),
            "High": np.linspace(101.0, 112.0, len(idx)),
            "Low": np.linspace(99.0, 110.0, len(idx)),
            "Close": np.linspace(100.5, 111.5, len(idx)),
            "Volume": np.full(len(idx), 100_000),
        },
        index=idx,
    )


def _marker_counts(fig) -> tuple[int, int]:
    buy = sum(len(t.x) for t in fig.data if getattr(t, "name", "") == "BUY")
    sell = sum(len(t.x) for t in fig.data if getattr(t, "name", "") == "SELL")
    return buy, sell


def _marker_x(fig, side: str) -> list[pd.Timestamp]:
    out: list[pd.Timestamp] = []
    for t in fig.data:
        if getattr(t, "name", "") != side:
            continue
        out.extend(pd.Timestamp(x) for x in list(t.x))
    return out


def _as_utc(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def test_trade_markers_render_from_raw_fills_schema() -> None:
    bars = _bars()
    idx = bars.index
    trades = pd.DataFrame(
        {
            "timestamp": [idx[2], idx[5], idx[9]],
            "symbol": ["AAA", "AAA", "AAA"],
            "qty": [10, -4, -6],
            "price": [102.0, 105.0, 109.0],
        }
    )

    fig = plot_price_indicators_trades_line(bars, trades=trades)
    buy, sell = _marker_counts(fig)
    assert buy == 1
    assert sell == 2


def test_trade_markers_case_a_exact_bar_timestamp_match() -> None:
    bars = _bars()
    idx = bars.index
    trades = pd.DataFrame(
        {
            "timestamp": [idx[2], idx[6]],
            "signal": ["BUY", "SELL"],
            "price": [102.0, 107.0],
        }
    )

    fig = plot_price_indicators_trades_line(bars, trades=trades)
    buy, sell = _marker_counts(fig)
    assert buy == 1
    assert sell == 1


def test_trade_markers_case_b_intraday_trades_keep_trade_timestamp_x() -> None:
    bars = _bars()
    idx = bars.index
    buy_ts = idx[3] + pd.Timedelta(hours=11)
    sell_ts = idx[7] + pd.Timedelta(hours=15)
    trades = pd.DataFrame(
        {
            "timestamp": [buy_ts, sell_ts],
            "trade_side": ["BUY", "SELL"],
            "price": [np.nan, np.nan],
        }
    )

    fig = plot_price_indicators_trades_line(bars, trades=trades)
    buy, sell = _marker_counts(fig)
    assert buy == 1
    assert sell == 1

    buy_x = _marker_x(fig, "BUY")
    sell_x = _marker_x(fig, "SELL")
    assert len(buy_x) == 1
    assert len(sell_x) == 1
    assert _as_utc(buy_x[0]) == buy_ts.tz_convert("UTC")
    assert _as_utc(sell_x[0]) == sell_ts.tz_convert("UTC")


def test_trade_markers_case_c_outside_range_price_present_still_renders() -> None:
    bars = _bars()
    idx = bars.index
    priced_trade_ts = idx[-1] + pd.Timedelta(days=1)
    missing_price_far_ts = idx[-1] + pd.Timedelta(days=10)
    trades = pd.DataFrame(
        {
            "timestamp": [priced_trade_ts, missing_price_far_ts],
            "direction": ["BUY", "SELL"],
            "price": [114.5, np.nan],
        }
    )

    fig = plot_price_indicators_trades_line(bars, trades=trades)
    buy, sell = _marker_counts(fig)
    assert buy == 1
    assert sell == 0

    buy_x = _marker_x(fig, "BUY")
    assert len(buy_x) == 1
    assert _as_utc(buy_x[0]) == priced_trade_ts.tz_convert("UTC")


def test_trade_markers_accept_epoch_millis_timestamp_values() -> None:
    bars = _bars()
    idx = bars.index
    trades = pd.DataFrame(
        {
            "timestamp": [
                int(idx[2].timestamp() * 1000.0),
                int(idx[7].timestamp() * 1000.0),
            ],
            "side": ["BUY", "SELL"],
            "price": [102.0, 107.0],
        }
    )

    fig = plot_price_indicators_trades_line(bars, trades=trades)
    buy, sell = _marker_counts(fig)
    assert buy == 1
    assert sell == 1


def test_trade_markers_accept_epoch_seconds_string_timestamp_values() -> None:
    bars = _bars()
    idx = bars.index
    trades = pd.DataFrame(
        {
            "timestamp": [
                str(int(idx[1].timestamp())),
                str(int(idx[8].timestamp())),
            ],
            "trade_side": ["BUY", "SELL"],
            "price": [101.0, 108.0],
        }
    )

    fig = plot_price_indicators_trades_line(bars, trades=trades)
    buy, sell = _marker_counts(fig)
    assert buy == 1
    assert sell == 1


def test_trades_table_keeps_timestamp_for_epoch_inputs() -> None:
    analyzer = ResultsAnalyzer()
    trades = pd.DataFrame(
        {
            "timestamp": ["1704067200", 1704153600000],
            "symbol": ["AAA", "AAA"],
            "qty": [1, -1],
            "price": [100.0, 101.0],
            "cost": [0.0, 0.0],
        }
    )

    out = analyzer._prepare_trades_table(trades, initial_cash=10_000.0)
    assert not out.empty
    assert "timestamp" in out.columns
    years = pd.to_datetime(out["timestamp"], errors="coerce").dt.year.dropna().tolist()
    assert years and min(years) >= 2020


def test_trade_markers_render_from_presentation_schema_aliases() -> None:
    bars = _bars()
    idx = bars.index
    trades = pd.DataFrame(
        {
            "timestamp": [idx[1].tz_convert(None), idx[6].tz_convert(None), idx[8].tz_convert(None)],
            "symbol": ["AAA", "AAA", "AAA"],
            "side": ["BUY", "SELL", "SELL"],
            "quantite": [5, -2, -3],
            "prix_execution_open_jour": [101.0, 106.0, 108.0],
        }
    )

    fig = plot_price_indicators_trades_line(bars, trades=trades)
    buy, sell = _marker_counts(fig)
    assert buy == 1
    assert sell == 2


def test_trade_markers_render_when_timestamp_is_index() -> None:
    bars = _bars()
    idx = bars.index
    trades = pd.DataFrame(
        {
            "side": ["BUY", "SELL"],
            "quantite": [4, -4],
            "close_du_jour": [103.0, 108.0],
        },
        index=[idx[3].tz_convert(None), idx[10].tz_convert(None)],
    )

    fig = plot_price_indicators_trades_line(bars, trades=trades)
    buy, sell = _marker_counts(fig)
    assert buy == 1
    assert sell == 1


def test_trade_markers_render_from_round_trip_trade_ledger_schema() -> None:
    bars = _bars()
    idx = bars.index
    trades = pd.DataFrame(
        {
            "entry_time": [idx[1], idx[6]],
            "exit_time": [idx[4], idx[9]],
            "side": ["LONG", "SHORT"],
            "entry_price": [101.0, 107.0],
            "exit_price": [104.0, 103.0],
            "qty": [5.0, 3.0],
        }
    )

    fig = plot_price_indicators_trades_line(bars, trades=trades)
    buy, sell = _marker_counts(fig)
    assert buy == 2
    assert sell == 2


def test_plot_drops_empty_bars_and_sets_missing_date_breaks() -> None:
    idx = pd.to_datetime(
        ["2024-01-02", "2024-01-03", "2024-01-05", "2024-01-08"],
        utc=True,
    )
    bars = pd.DataFrame(
        {
            "Open": [100.0, np.nan, 102.0, 103.0],
            "High": [101.0, np.nan, 103.0, 104.0],
            "Low": [99.0, np.nan, 101.0, 102.0],
            "Close": [100.5, np.nan, 102.5, 103.5],
            "Volume": [100_000, 0, 120_000, 110_000],
        },
        index=idx,
    )

    fig = plot_price_indicators_trades_line(bars, trades=pd.DataFrame())

    price = next((t for t in fig.data if getattr(t, "name", "") == "Price"), None)
    assert price is not None
    price_x = [pd.Timestamp(x) for x in price.x]
    assert len(price_x) == 3
    assert idx[1] not in price_x

    breaks = list(getattr(fig.layout.xaxis, "rangebreaks", []) or [])
    assert breaks

    values: list[str] = []
    for br in breaks:
        vals = getattr(br, "values", None)
        if vals is None and isinstance(br, dict):
            vals = br.get("values")
        for v in list(vals or []):
            values.append(str(v))

    assert any(v.startswith("2024-01-04") for v in values)
