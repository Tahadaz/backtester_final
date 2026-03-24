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
    assert open_fill["prix_execution"] == pytest.approx(101.0)
    assert open_fill["close_du_jour"] == pytest.approx(91.0)
    assert open_fill["tresorerie"] == pytest.approx(-101.0)
    assert open_fill["pnl_realise"] == pytest.approx(0.0)
    assert open_fill["pnl_latent"] == pytest.approx(-10.0)

    assert close_fill["date"] == "2024-01-04"
    assert close_fill["side"] == "VENTE"
    assert close_fill["prix_execution"] == pytest.approx(103.0)
    assert close_fill["tresorerie"] == pytest.approx(2.0)
    assert close_fill["pnl_realise"] == pytest.approx(2.0)


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

    assert len(trades) == 1
    assert window_cash_starts == {0: 0.0}

    open_fill = trades[0]
    assert open_fill["date"] == "2024-02-02"
    assert open_fill["side"] == "ACHAT"
    assert open_fill["prix_execution"] == pytest.approx(11.0)
    assert open_fill["tresorerie"] == pytest.approx(-11.0)
    assert open_fill["pnl_realise"] == pytest.approx(0.0)
    assert open_fill["pnl_latent"] == pytest.approx(9.0)


def test_trade_register_flip_updates_running_cash_and_short_carry() -> None:
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
    flip_fill = trades[1]

    assert open_long["side"] == "ACHAT"
    assert open_long["tresorerie"] == pytest.approx(-102.01)

    assert flip_fill["date"] == "2024-03-03"
    assert flip_fill["side"] == "VENTE"
    assert flip_fill["cout"] == pytest.approx(1.9)
    assert flip_fill["tresorerie"] == pytest.approx(86.09)
    assert flip_fill["pnl_realise"] == pytest.approx(-7.96)
    assert flip_fill["pnl_latent"] == pytest.approx(4.05)


def test_trade_register_short_open_and_cover_use_correct_cash_signs() -> None:
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

    assert len(trades) == 2
    assert window_cash_starts == {0: 0.0}

    short_open = trades[0]
    short_cover = trades[1]

    assert short_open["side"] == "VENTE"
    assert short_open["tresorerie"] == pytest.approx(99.0)
    assert short_open["pnl_latent"] == pytest.approx(-1.0)

    assert short_cover["side"] == "ACHAT"
    assert short_cover["tresorerie"] == pytest.approx(8.1)
    assert short_cover["pnl_realise"] == pytest.approx(8.1)


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
