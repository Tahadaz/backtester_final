import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")

from core.quant_core.research.stats.regression import market_model
from services.api.app.routers.strategy_signals._evidence import (
    _evidence_max_drawdown,
    _evidence_mean,
    _evidence_stitched_backtest,
    _evidence_trade_distribution_metrics,
    _evidence_trade_sharpe,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "evidence_metrics_golden.json"


def _assert_metric_equal(actual, expected) -> None:
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        assert actual == expected
    else:
        assert actual == pytest.approx(expected, abs=1e-9)


def test_golden_fixture_python_metrics_parity() -> None:
    # Change a formula -> regenerate this fixture and update BOTH sides.
    fixture = json.loads(FIXTURE.read_text())
    inputs = fixture["inputs"]
    expected = fixture["expected"]
    gross_returns = inputs["gross_returns"]
    net_returns = inputs["net_returns"]
    stock_returns = inputs["stock_returns"]
    equity = inputs["equity"]
    dates = inputs["dates"]

    metrics = {
        "total_return": equity[-1] - 1.0,
        "cagr": (1.0 + (equity[-1] - 1.0)) ** (1.0 / (len(dates) / 252.0)) - 1.0,
        "sharpe": _evidence_trade_sharpe(net_returns, dates),
        "max_drawdown": _evidence_max_drawdown(equity),
        "win_rate": sum(1 for value in gross_returns if value > 0.0) / len(gross_returns),
        "hit_rate": sum(1 for value in gross_returns if value > 0.0) / len(gross_returns),
        "n_trades": len(net_returns),
        "expected_return_gross": _evidence_mean(gross_returns),
        "expected_return_net": _evidence_mean(net_returns),
        "stock_expected_return": _evidence_mean(stock_returns),
    }
    metrics.update(
        _evidence_trade_distribution_metrics(
            net_returns,
            equity,
            dates=dates,
            benchmark_returns=inputs["benchmark_returns"],
            benchmark_symbol=inputs["benchmark_symbol"],
        )
    )

    assert "expectancy_net" not in metrics
    assert set(expected) <= set(metrics)
    for key, value in expected.items():
        _assert_metric_equal(metrics[key], value)


def test_trade_distribution_metrics_mixed_returns() -> None:
    metrics = _evidence_trade_distribution_metrics(
        [0.10, -0.05, 0.02, -0.01],
        [1.0, 1.02, 1.00, 1.04, 1.01, 1.05],
        dates=["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"],
        min_sample_n=4,
    )

    assert metrics["profit_factor_net"] == pytest.approx(2.0)
    assert metrics["avg_win_net"] == pytest.approx(0.06)
    assert metrics["avg_loss_net"] == pytest.approx(-0.03)
    assert metrics["payoff_ratio_net"] == pytest.approx(2.0)
    assert "expectancy_net" not in metrics
    assert metrics["median_return_net"] == pytest.approx(0.005)
    assert metrics["p05_return_net"] == pytest.approx(-0.044)
    assert metrics["p95_return_net"] == pytest.approx(0.088)
    assert metrics["sortino"] is not None
    assert metrics["sharpe_path"] is not None
    assert metrics["annualized_volatility"] is not None
    assert metrics["downside_volatility"] is not None
    assert metrics["alpha_reason"] == "benchmark_unavailable"
    assert metrics["sample_start"] == "2024-01-01"
    assert metrics["sample_end"] == "2024-01-08"
    assert metrics["sample_days"] == 6
    assert metrics["min_sample_pass"] is True
    assert metrics["metric_basis"] == "stitched_wfo_oos"


def test_market_model_perfect_correlation_stream() -> None:
    benchmark = [None] + [0.01, -0.005, 0.006, -0.002, 0.004] * 8
    strategy = [0.0] + [0.0005 + 2.0 * value for value in benchmark[1:]]

    result = market_model(strategy, benchmark, min_obs=20)

    assert result["alpha_reason"] == "ok"
    assert result["beta"] == pytest.approx(2.0)
    assert result["alpha_annualized"] == pytest.approx(0.126)
    assert result["alpha_r2"] == pytest.approx(1.0)
    assert result["alpha_n_obs"] == 40


def test_market_model_flat_equity_reports_insufficient_overlap() -> None:
    benchmark = [None] + [0.01, -0.005, 0.006, -0.002, 0.004] * 8
    strategy = [0.0 for _ in benchmark]

    result = market_model(strategy, benchmark, min_obs=20)

    assert result["beta"] is None
    assert result["alpha_annualized"] is None
    assert result["alpha_r2"] is None
    assert result["alpha_n_obs"] == 40
    assert result["alpha_reason"] == "insufficient_overlap"


def test_benchmark_unavailable_sets_alpha_reason_without_exception() -> None:
    metrics = _evidence_trade_distribution_metrics(
        [0.03] * 35,
        [1.0 + i * 0.001 for i in range(36)],
        dates=[f"2024-01-{(i % 28) + 1:02d}" for i in range(36)],
        benchmark_returns=None,
    )

    assert metrics["beta"] is None
    assert metrics["alpha_annualized"] is None
    assert metrics["alpha_r2"] is None
    assert metrics["alpha_n_obs"] == 0
    assert metrics["alpha_reason"] == "benchmark_unavailable"


def test_trade_distribution_metrics_all_wins_and_empty_losses() -> None:
    metrics = _evidence_trade_distribution_metrics(
        [0.03, 0.02],
        [1.0, 1.03, 1.05],
        dates=["2024-01-01", "2024-01-02", "2024-01-03"],
        min_sample_n=30,
    )

    assert metrics["profit_factor_net"] is None
    assert metrics["avg_win_net"] == pytest.approx(0.025)
    assert metrics["avg_loss_net"] is None
    assert metrics["payoff_ratio_net"] is None
    assert metrics["min_sample_pass"] is False


def test_trade_distribution_metrics_empty_sample() -> None:
    metrics = _evidence_trade_distribution_metrics([], [], dates=[], min_sample_n=1)

    assert metrics["profit_factor_net"] is None
    assert "expectancy_net" not in metrics
    assert metrics["median_return_net"] is None
    assert metrics["sortino"] is None
    assert metrics["sample_start"] is None
    assert metrics["sample_end"] is None
    assert metrics["sample_days"] == 0
    assert metrics["min_sample_pass"] is False


def test_trade_sharpe_frequency_annualization() -> None:
    values = [0.03, -0.01, 0.02, 0.04]
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    mean = sum(values) / len(values)
    expected = mean / 0.021602468994692867 * ((len(values) / (len(dates) / 252.0)) ** 0.5)

    assert _evidence_trade_sharpe(values, dates) == pytest.approx(expected)


def test_stitched_backtest_exposes_institutional_metric_keys() -> None:
    payload = _evidence_stitched_backtest(
        dates=["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
        close=[100.0, 104.0, 102.0, 106.0],
        open_prices=[100.0, 101.0, 103.0, 104.0],
        high=[101.0, 105.0, 104.0, 107.0],
        low=[99.0, 100.0, 101.0, 103.0],
        trades=[
            {
                "trade_id": "t1",
                "direction": "long",
                "signal_date": "2024-01-01",
                "entry_date": "2024-01-02",
                "exit_date": "2024-01-03",
                "entry_price": 101.0,
                "exit_price": 103.0,
                "action_return_gross": 0.03,
                "action_return_net": 0.02,
                "stock_return": 0.03,
            },
            {
                "trade_id": "t2",
                "direction": "long",
                "signal_date": "2024-01-02",
                "entry_date": "2024-01-03",
                "exit_date": "2024-01-04",
                "entry_price": 103.0,
                "exit_price": 104.0,
                "action_return_gross": -0.01,
                "action_return_net": -0.02,
                "stock_return": -0.01,
            },
        ],
        bucket="buy",
        direction="long",
        score_mode="fold_scoped_winner",
        cost_bps=0.0,
    )

    metrics = payload["metrics"]
    assert metrics["profit_factor_net"] == pytest.approx(1.0)
    assert metrics["avg_win_net"] == pytest.approx(0.02)
    assert metrics["avg_loss_net"] == pytest.approx(-0.02)
    assert metrics["payoff_ratio_net"] == pytest.approx(1.0)
    assert "expectancy_net" not in metrics
    assert metrics["alpha_reason"] == "benchmark_unavailable"
    assert metrics["metric_basis"] == "stitched_wfo_oos"
    assert metrics["sample_start"] == "2024-01-01"
    assert metrics["sample_end"] == "2024-01-04"
    assert metrics["sample_days"] == 4
    assert metrics["min_sample_pass"] is False
