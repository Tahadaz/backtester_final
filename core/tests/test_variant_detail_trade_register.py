import numpy as np
import pandas as pd
import pytest

from core.quant_core.signal_engine import variant_detail as variant_detail_module
from core.quant_core.signal_engine.domain import OOSWindowResult, VariantDef
from core.quant_core.signal_engine.variant_detail import (
    compute_variant_detail,
    _extract_trade_register,
    _trade_performance_summary,
)
from core.quant_core.signal_engine.rsi_semantics import (
    actions_to_positions,
    alternate_rsi_actions,
    rsi_window_marker_indices,
)


def _window(*, start: int = 0, end: int, idx: int = 0) -> OOSWindowResult:
    return OOSWindowResult(
        window_index=idx,
        train_start=0,
        train_end=0,
        test_start=start,
        test_end=end,
        n_trades=0,
        mean_return_net=0.0,
        sharpe=0.0,
        max_drawdown=0.0,
        fraction_positive_bars=0.0,
        n_bars=end - start,
        is_valid=True,
    )


def _rsi_variant() -> VariantDef:
    return VariantDef(
        variant_id="test_rsi_variant",
        family="rsi",
        archetype="rsi_level",
        params={"period": 14, "oversold": 30, "overbought": 70},
        description="RSI test variant",
    )


def _marker_counts(fig: dict) -> tuple[int, int]:
    buy = sum(len(trace.get("x", [])) for trace in fig["data"] if trace.get("name") == "BUY")
    sell = sum(len(trace.get("x", [])) for trace in fig["data"] if trace.get("name") == "SELL")
    return buy, sell


def test_trade_register_executes_on_next_open_and_tracks_running_cash() -> None:
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    sig = np.array([1.0, 1.0, 0.0, 0.0], dtype=float)
    close = np.array([90.0, 91.0, 92.0, 93.0], dtype=float)
    open_prices = np.array([100.0, 101.0, 102.0, 103.0], dtype=float)

    trades, window_cash_starts = _extract_trade_register(
        sig,
        close,
        open_prices,
        dates,
        [_window(end=4)],
        cost_bps=0.0,
    )

    assert len(trades) == 2
    assert window_cash_starts == {0: 0.0}

    open_fill = trades[0]
    close_fill = trades[1]

    assert open_fill["date"] == "2024-01-02"
    assert open_fill["side"] == "ACHAT"
    assert open_fill["open_t_plus_1"] == pytest.approx(101.0)
    assert open_fill["prix_execution"] == pytest.approx(101.0)
    assert open_fill["close_du_jour"] == pytest.approx(91.0)
    assert open_fill["cmp"] == pytest.approx(101.0)
    assert open_fill["cash_cumulee"] == pytest.approx(-101.0)
    assert open_fill["tresorerie"] == pytest.approx(-101.0)
    assert open_fill["pnl_realise"] == pytest.approx(0.0)
    assert open_fill["pnl_realise_cumule"] == pytest.approx(0.0)
    assert open_fill["return_cumule"] == pytest.approx((91.0 / 90.0) - 1.0)
    assert open_fill["pnl_latent"] == pytest.approx(-10.0)

    assert close_fill["date"] == "2024-01-04"
    assert close_fill["side"] == "VENTE"
    assert close_fill["open_t_plus_1"] == pytest.approx(103.0)
    assert close_fill["prix_execution"] == pytest.approx(103.0)
    assert close_fill["cmp"] == pytest.approx(101.0)
    assert close_fill["tresorerie"] == pytest.approx(2.0)
    assert close_fill["pnl_realise"] == pytest.approx(2.0)
    assert close_fill["pnl_realise_cumule"] == pytest.approx(2.0)
    assert close_fill["return_cumule"] == pytest.approx((92.0 / 90.0) - 1.0)


def test_compute_variant_signal_array_blocks_repeated_sell_after_neutral() -> None:
    raw_sig = np.array([0.0, -1.0, 0.0, -1.0, 0.0], dtype=float)

    sig = alternate_rsi_actions(raw_sig)

    np.testing.assert_array_equal(sig, np.array([0.0, -1.0, 0.0, 0.0, 0.0], dtype=float))


def test_compute_variant_signal_array_blocks_repeated_buy_after_neutral() -> None:
    raw_sig = np.array([0.0, 1.0, 0.0, 1.0, 0.0], dtype=float)

    sig = alternate_rsi_actions(raw_sig)

    np.testing.assert_array_equal(sig, np.array([0.0, 1.0, 0.0, 0.0, 0.0], dtype=float))


def test_compute_variant_signal_array_preserves_first_signal_and_opposite_reset() -> None:
    raw_sig = np.array([0.0, -1.0, 0.0, 1.0, 0.0, -1.0], dtype=float)

    sig = alternate_rsi_actions(raw_sig)

    np.testing.assert_array_equal(sig, raw_sig)


def test_rsi_actions_to_positions_keeps_position_through_neutral_bars() -> None:
    actions = np.array([0.0, 1.0, 0.0, 0.0, -1.0, 0.0], dtype=float)

    positions = actions_to_positions(actions)

    np.testing.assert_array_equal(
        positions,
        np.array([0.0, 1.0, 1.0, 1.0, 0.0, 0.0], dtype=float),
    )


def test_rsi_window_marker_indices_adds_carry_in_marker() -> None:
    action_sig = np.array([0.0, 1.0, 0.0, 0.0, 0.0], dtype=float)
    position_sig = actions_to_positions(action_sig)

    buy_idx, sell_idx = rsi_window_marker_indices(
        action_sig,
        position_sig,
        start=2,
        end=4,
    )

    assert buy_idx == [2]
    assert sell_idx == []


def test_rsi_window_marker_indices_keeps_first_bar_action_marker() -> None:
    action_sig = np.array([0.0, 0.0, -1.0, 0.0, 0.0], dtype=float)
    position_sig = actions_to_positions(alternate_rsi_actions(action_sig))

    buy_idx, sell_idx = rsi_window_marker_indices(
        action_sig,
        position_sig,
        start=2,
        end=4,
    )

    assert buy_idx == []
    assert sell_idx == [2]


def test_trade_register_leaves_position_open_at_window_end() -> None:
    dates = pd.date_range("2024-02-01", periods=3, freq="D")
    sig = np.array([1.0, 1.0, 1.0], dtype=float)
    close = np.array([19.0, 20.0, 30.0], dtype=float)
    open_prices = np.array([10.0, 11.0, 12.0], dtype=float)

    trades, window_cash_starts = _extract_trade_register(
        sig,
        close,
        open_prices,
        dates,
        [_window(end=3)],
        cost_bps=0.0,
    )

    assert len(trades) == 2
    assert window_cash_starts == {0: 0.0}

    open_fill = trades[0]
    force_close = trades[1]
    assert open_fill["date"] == "2024-02-02"
    assert open_fill["side"] == "ACHAT"
    assert open_fill["open_t_plus_1"] == pytest.approx(11.0)
    assert open_fill["prix_execution"] == pytest.approx(11.0)
    assert open_fill["cmp"] == pytest.approx(11.0)
    assert open_fill["tresorerie"] == pytest.approx(-11.0)
    assert open_fill["pnl_realise"] == pytest.approx(0.0)
    assert open_fill["pnl_realise_cumule"] == pytest.approx(0.0)
    assert open_fill["return_cumule"] == pytest.approx((20.0 / 19.0) - 1.0)
    assert open_fill["pnl_latent"] == pytest.approx(9.0)

    assert force_close["date"] == "2024-02-03"
    assert force_close["side"] == "VENTE"
    assert force_close["cmp"] == pytest.approx(11.0)
    assert force_close["position"] == pytest.approx(0.0)
    assert force_close["pnl_realise"] == pytest.approx(19.0)
    assert force_close["pnl_realise_cumule"] == pytest.approx(19.0)
    assert force_close["return_cumule"] == pytest.approx((30.0 / 19.0) - 1.0)


def test_compute_variant_detail_rsi_suppresses_repeated_sell_fills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = pd.date_range("2024-02-01", periods=5, freq="D")
    close = np.array([100.0, 99.0, 98.0, 97.0, 96.0], dtype=float)
    ohlcv = pd.DataFrame(
        {
            "Open": close,
            "High": close,
            "Low": close,
            "Close": close,
            "Volume": np.ones(len(close), dtype=float),
        },
        index=dates,
    )
    action_sig = np.array([0.0, -1.0, 0.0, 0.0, 0.0], dtype=float)

    monkeypatch.setattr(variant_detail_module, "compute_rsi_variant_actions", lambda *args, **kwargs: action_sig)
    monkeypatch.setattr(variant_detail_module, "compute_rsi_variant_positions", lambda *args, **kwargs: actions_to_positions(action_sig))
    monkeypatch.setattr(variant_detail_module, "_plot_oos_equity_and_drawdown", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(variant_detail_module, "_plot_single_window_equity_dd", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(variant_detail_module, "_plot_single_window", lambda *args, **kwargs: {"data": [], "layout": {}})

    detail = compute_variant_detail(
        ohlcv,
        close,
        _rsi_variant(),
        [_window(end=5)],
        volume=ohlcv["Volume"].to_numpy(),
        cost_bps=0.0,
        cooldown_bars=0,
    )

    assert detail["trade_ledger"] == []


def test_compute_variant_detail_rsi_keeps_long_through_neutral_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = pd.date_range("2024-02-10", periods=4, freq="D")
    close = np.array([100.0, 101.0, 102.0, 103.0], dtype=float)
    ohlcv = pd.DataFrame(
        {
            "Open": close,
            "High": close,
            "Low": close,
            "Close": close,
            "Volume": np.ones(len(close), dtype=float),
        },
        index=dates,
    )
    action_sig = np.array([0.0, 1.0, 0.0, 0.0], dtype=float)

    monkeypatch.setattr(variant_detail_module, "compute_rsi_variant_actions", lambda *args, **kwargs: action_sig)
    monkeypatch.setattr(variant_detail_module, "compute_rsi_variant_positions", lambda *args, **kwargs: actions_to_positions(action_sig))
    monkeypatch.setattr(variant_detail_module, "_plot_oos_equity_and_drawdown", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(variant_detail_module, "_plot_single_window_equity_dd", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(variant_detail_module, "_plot_single_window", lambda *args, **kwargs: {"data": [], "layout": {}})

    detail = compute_variant_detail(
        ohlcv,
        close,
        _rsi_variant(),
        [_window(end=4)],
        volume=ohlcv["Volume"].to_numpy(),
        cost_bps=0.0,
        cooldown_bars=0,
    )

    assert [row["side"] for row in detail["trade_ledger"]] == ["ACHAT", "VENTE"]
    assert detail["trade_ledger"][0]["position"] == pytest.approx(1.0)
    assert detail["trade_ledger"][1]["date"] == "2024-02-13"


def test_compute_variant_detail_rsi_keeps_short_through_neutral_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = pd.date_range("2024-02-20", periods=4, freq="D")
    close = np.array([100.0, 99.0, 98.0, 97.0], dtype=float)
    ohlcv = pd.DataFrame(
        {
            "Open": close,
            "High": close,
            "Low": close,
            "Close": close,
            "Volume": np.ones(len(close), dtype=float),
        },
        index=dates,
    )
    action_sig = np.array([0.0, -1.0, 0.0, 0.0], dtype=float)

    monkeypatch.setattr(variant_detail_module, "compute_rsi_variant_actions", lambda *args, **kwargs: action_sig)
    monkeypatch.setattr(variant_detail_module, "compute_rsi_variant_positions", lambda *args, **kwargs: actions_to_positions(action_sig))
    monkeypatch.setattr(variant_detail_module, "_plot_oos_equity_and_drawdown", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(variant_detail_module, "_plot_single_window_equity_dd", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(variant_detail_module, "_plot_single_window", lambda *args, **kwargs: {"data": [], "layout": {}})

    detail = compute_variant_detail(
        ohlcv,
        close,
        _rsi_variant(),
        [_window(end=4)],
        volume=ohlcv["Volume"].to_numpy(),
        cost_bps=0.0,
        cooldown_bars=0,
    )

    assert detail["trade_ledger"] == []


def test_compute_variant_detail_rsi_reverses_on_opposite_nonzero_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = pd.date_range("2024-03-10", periods=5, freq="D")
    close = np.array([100.0, 101.0, 102.0, 101.0, 100.0], dtype=float)
    ohlcv = pd.DataFrame(
        {
            "Open": close,
            "High": close,
            "Low": close,
            "Close": close,
            "Volume": np.ones(len(close), dtype=float),
        },
        index=dates,
    )
    action_sig = np.array([0.0, 1.0, 0.0, -1.0, 0.0], dtype=float)

    monkeypatch.setattr(variant_detail_module, "compute_rsi_variant_actions", lambda *args, **kwargs: action_sig)
    monkeypatch.setattr(variant_detail_module, "compute_rsi_variant_positions", lambda *args, **kwargs: actions_to_positions(action_sig))
    monkeypatch.setattr(variant_detail_module, "_plot_oos_equity_and_drawdown", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(variant_detail_module, "_plot_single_window_equity_dd", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(variant_detail_module, "_plot_single_window", lambda *args, **kwargs: {"data": [], "layout": {}})

    detail = compute_variant_detail(
        ohlcv,
        close,
        _rsi_variant(),
        [_window(end=5)],
        volume=ohlcv["Volume"].to_numpy(),
        cost_bps=0.0,
        cooldown_bars=0,
    )

    assert [row["side"] for row in detail["trade_ledger"]] == ["ACHAT", "VENTE"]
    assert [row["position"] for row in detail["trade_ledger"]] == pytest.approx([1.0, 0.0])


def test_compute_variant_detail_rsi_plot_marks_only_one_repeated_sell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = pd.date_range("2024-03-01", periods=5, freq="D")
    close = np.array([100.0, 99.0, 98.0, 97.0, 96.0], dtype=float)
    ohlcv = pd.DataFrame(
        {
            "Open": close,
            "High": close,
            "Low": close,
            "Close": close,
            "Volume": np.ones(len(close), dtype=float),
        },
        index=dates,
    )
    action_sig = np.array([0.0, -1.0, 0.0, 0.0, 0.0], dtype=float)

    monkeypatch.setattr(variant_detail_module, "compute_rsi_variant_actions", lambda *args, **kwargs: action_sig)
    monkeypatch.setattr(variant_detail_module, "compute_rsi_variant_positions", lambda *args, **kwargs: actions_to_positions(action_sig))
    monkeypatch.setattr(variant_detail_module, "_plot_oos_equity_and_drawdown", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(variant_detail_module, "_plot_single_window_equity_dd", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(variant_detail_module, "_plot_single_window", lambda *args, **kwargs: {"data": [], "layout": {}})

    detail = compute_variant_detail(
        ohlcv,
        close,
        _rsi_variant(),
        [_window(end=5)],
        volume=ohlcv["Volume"].to_numpy(),
        cost_bps=0.0,
        cooldown_bars=0,
    )

    buy_count, sell_count = _marker_counts(detail["plots"]["price_indicator_signal"])

    assert buy_count == 0
    assert sell_count == 1


def test_compute_variant_detail_rsi_window_plot_marks_first_bar_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = pd.date_range("2024-03-01", periods=6, freq="D")
    close = np.array([100.0, 101.0, 99.0, 98.0, 97.0, 96.0], dtype=float)
    ohlcv = pd.DataFrame(
        {
            "Open": close,
            "High": close,
            "Low": close,
            "Close": close,
            "Volume": np.ones(len(close), dtype=float),
        },
        index=dates,
    )
    action_sig = np.array([0.0, 0.0, -1.0, 0.0, 0.0, 0.0], dtype=float)

    monkeypatch.setattr(variant_detail_module, "compute_rsi_variant_actions", lambda *args, **kwargs: action_sig)
    monkeypatch.setattr(variant_detail_module, "compute_rsi_variant_positions", lambda *args, **kwargs: actions_to_positions(action_sig))
    monkeypatch.setattr(variant_detail_module, "_plot_oos_equity_and_drawdown", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(variant_detail_module, "_plot_single_window_equity_dd", lambda *args, **kwargs: (None, None))

    detail = compute_variant_detail(
        ohlcv,
        close,
        _rsi_variant(),
        [_window(start=2, end=5)],
        volume=ohlcv["Volume"].to_numpy(),
        cost_bps=0.0,
        cooldown_bars=0,
    )

    buy_count, sell_count = _marker_counts(detail["per_window"][0]["plot"])

    assert buy_count == 0
    assert sell_count == 1
    sell_trace = next(trace for trace in detail["per_window"][0]["plot"]["data"] if trace.get("name") == "SELL")
    assert sell_trace["x"] == ["2024-03-03"]


def test_compute_variant_detail_rsi_window_plot_adds_carry_in_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = pd.date_range("2024-03-10", periods=6, freq="D")
    close = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], dtype=float)
    ohlcv = pd.DataFrame(
        {
            "Open": close,
            "High": close,
            "Low": close,
            "Close": close,
            "Volume": np.ones(len(close), dtype=float),
        },
        index=dates,
    )
    action_sig = np.array([0.0, 1.0, 0.0, 0.0, 0.0, 0.0], dtype=float)

    monkeypatch.setattr(variant_detail_module, "compute_rsi_variant_actions", lambda *args, **kwargs: action_sig)
    monkeypatch.setattr(variant_detail_module, "compute_rsi_variant_positions", lambda *args, **kwargs: actions_to_positions(action_sig))
    monkeypatch.setattr(variant_detail_module, "_plot_oos_equity_and_drawdown", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(variant_detail_module, "_plot_single_window_equity_dd", lambda *args, **kwargs: (None, None))

    detail = compute_variant_detail(
        ohlcv,
        close,
        _rsi_variant(),
        [_window(start=2, end=5)],
        volume=ohlcv["Volume"].to_numpy(),
        cost_bps=0.0,
        cooldown_bars=0,
    )

    buy_count, sell_count = _marker_counts(detail["per_window"][0]["plot"])

    assert buy_count == 1
    assert sell_count == 0
    buy_trace = next(trace for trace in detail["per_window"][0]["plot"]["data"] if trace.get("name") == "BUY")
    assert buy_trace["x"] == ["2024-03-12"]


def test_trade_register_sell_signal_closes_long_without_opening_short() -> None:
    dates = pd.date_range("2024-03-01", periods=3, freq="D")
    sig = np.array([1.0, -1.0, -1.0], dtype=float)
    close = np.array([100.0, 100.0, 90.0], dtype=float)
    open_prices = np.array([100.0, 101.0, 95.0], dtype=float)

    trades, window_cash_starts = _extract_trade_register(
        sig,
        close,
        open_prices,
        dates,
        [_window(end=3)],
        cost_bps=100.0,
    )

    assert len(trades) == 2
    assert window_cash_starts == {0: 0.0}

    open_long = trades[0]
    close_fill = trades[1]

    assert open_long["side"] == "ACHAT"
    assert open_long["cmp"] == pytest.approx(102.01)
    assert open_long["tresorerie"] == pytest.approx(-102.01)
    assert open_long["return_cumule"] == pytest.approx(-0.01)

    assert close_fill["date"] == "2024-03-03"
    assert close_fill["side"] == "VENTE"
    assert close_fill["cmp"] == pytest.approx(102.01)
    assert close_fill["cout"] == pytest.approx(0.95)
    assert close_fill["position"] == pytest.approx(0.0)
    assert close_fill["tresorerie"] == pytest.approx(-7.96)
    assert close_fill["pnl_realise"] == pytest.approx(-7.96)
    assert close_fill["pnl_realise_cumule"] == pytest.approx(-7.96)
    assert close_fill["return_cumule"] == pytest.approx(-0.0199)
    assert close_fill["pnl_latent"] == pytest.approx(0.0)


def test_trade_register_ignores_sell_signal_while_flat() -> None:
    dates = pd.date_range("2024-04-01", periods=4, freq="D")
    sig = np.array([-1.0, -1.0, 0.0, 0.0], dtype=float)
    close = np.array([100.0, 100.0, 95.0, 95.0], dtype=float)
    open_prices = np.array([100.0, 100.0, 90.0, 90.0], dtype=float)

    trades, window_cash_starts = _extract_trade_register(
        sig,
        close,
        open_prices,
        dates,
        [_window(end=4)],
        cost_bps=100.0,
    )

    assert len(trades) == 0
    assert window_cash_starts == {0: 0.0}


def test_trade_performance_summary_uses_realized_pnl_metrics() -> None:
    trades = [
        {"pnl_realise": 0.0, "cout": 1.0},
        {"pnl_realise": 5.0, "cout": 2.0},
        {"pnl_realise": -2.0, "cout": 3.0},
    ]

    summary = _trade_performance_summary(trades)
    metrics = {str(row["metric"]): row["value"] for row in summary}

    assert "avg_win_pnl" in metrics
    assert "avg_loss_pnl" in metrics
    assert "total_pnl_realise" in metrics
    assert "avg_win_return" not in metrics
    assert "avg_bars_held" not in metrics

    assert metrics["total_fills"] == 3
    assert metrics["closing_fills"] == 2
    assert metrics["win_rate"] == pytest.approx(50.0)
    assert metrics["avg_win_pnl"] == pytest.approx(5.0)
    assert metrics["avg_loss_pnl"] == pytest.approx(-2.0)
    assert metrics["total_pnl_realise"] == pytest.approx(3.0)
    assert metrics["total_cost"] == pytest.approx(6.0)
    assert metrics["profit_factor"] == pytest.approx(2.5)


def test_trade_register_continues_tresorerie_across_windows_in_all_periods_view() -> None:
    dates = pd.date_range("2024-05-01", periods=8, freq="D")
    sig = np.array([1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0], dtype=float)
    close = np.array([39.0, 40.0, 40.0, 41.0, 19.0, 20.0, 20.0, 21.0], dtype=float)
    open_prices = np.array([39.0, 40.0, 40.0, 41.0, 19.0, 20.0, 20.0, 21.0], dtype=float)

    trades, window_cash_starts = _extract_trade_register(
        sig,
        close,
        open_prices,
        dates,
        [_window(start=0, end=4, idx=0), _window(start=4, end=8, idx=1)],
        cost_bps=0.0,
    )

    assert window_cash_starts == {0: 0.0, 1: 1.0}
    assert [row["tresorerie"] for row in trades] == pytest.approx([-40.0, 1.0, -19.0, 2.0])
    assert [row["pnl_realise_cumule"] for row in trades] == pytest.approx([0.0, 1.0, 1.0, 2.0])
    assert [row["return_cumule"] for row in trades] == pytest.approx([0.025641, 0.025641, 0.052632, 0.052632], abs=1e-6)


def test_compute_variant_detail_rebases_tresorerie_for_selected_window(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.date_range("2024-06-01", periods=8, freq="D")
    close = np.array([39.0, 40.0, 40.0, 41.0, 19.0, 20.0, 20.0, 21.0], dtype=float)
    ohlcv = pd.DataFrame(
        {
            "Open": close,
            "High": close,
            "Low": close,
            "Close": close,
            "Volume": np.ones(len(close), dtype=float),
        },
        index=dates,
    )
    sig = np.array([1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0], dtype=float)
    variant = VariantDef(
        variant_id="price_vs_sma_2",
        family="sma",
        archetype="price_vs_sma",
        params={"window": 2},
        description="test variant",
    )
    windows = [_window(start=0, end=4, idx=0), _window(start=4, end=8, idx=1)]

    monkeypatch.setattr(variant_detail_module, "compute_signal_array", lambda *args, **kwargs: sig)
    monkeypatch.setattr(variant_detail_module, "apply_cooldown", lambda values, _cooldown: values)
    monkeypatch.setattr(variant_detail_module, "_plot_price_indicator_signal", lambda *args, **kwargs: {"data": [], "layout": {}})
    monkeypatch.setattr(variant_detail_module, "_plot_oos_equity_and_drawdown", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(variant_detail_module, "_plot_single_window_equity_dd", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(variant_detail_module, "_plot_single_window", lambda *args, **kwargs: {"data": [], "layout": {}})

    detail = compute_variant_detail(
        ohlcv,
        close,
        variant,
        windows,
        volume=ohlcv["Volume"].to_numpy(),
        cost_bps=0.0,
        cooldown_bars=0,
    )

    assert [row["tresorerie"] for row in detail["trade_ledger"]] == pytest.approx([-40.0, 1.0, -19.0, 2.0])
    assert [row["tresorerie"] for row in detail["per_window"][0]["trades"]] == pytest.approx([-40.0, 1.0])
    assert [row["tresorerie"] for row in detail["per_window"][1]["trades"]] == pytest.approx([-20.0, 1.0])
    assert [row["pnl_realise_cumule"] for row in detail["trade_ledger"]] == pytest.approx([0.0, 1.0, 1.0, 2.0])
    assert [row["pnl_realise_cumule"] for row in detail["per_window"][0]["trades"]] == pytest.approx([0.0, 1.0])
    assert [row["pnl_realise_cumule"] for row in detail["per_window"][1]["trades"]] == pytest.approx([0.0, 1.0])
    assert [row["return_cumule"] for row in detail["trade_ledger"]] == pytest.approx([0.025641, 0.025641, 0.052632, 0.052632], abs=1e-6)
    assert [row["return_cumule"] for row in detail["per_window"][0]["trades"]] == pytest.approx([0.025641, 0.025641], abs=1e-6)
    assert [row["return_cumule"] for row in detail["per_window"][1]["trades"]] == pytest.approx([0.052632, 0.052632], abs=1e-6)
