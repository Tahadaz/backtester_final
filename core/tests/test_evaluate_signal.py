"""Smoke tests for evaluate_signal harness."""
import math

import numpy as np
import pandas as pd
import pytest

from quant_core.research.evaluate import evaluate_signal
from quant_core.research.domain import SignalEvaluationReport


def _make_synthetic(n: int = 500, seed: int = 42):
    rng = np.random.default_rng(seed)
    prices = pd.Series(100 + np.cumsum(rng.normal(0, 1, n)), name="close")
    signal = pd.Series(rng.choice([-1.0, 0.0, 1.0], size=n), name="signal")
    return signal, prices


class TestEvaluateSignal:
    def test_returns_report_instance(self):
        signal, prices = _make_synthetic(300)
        report = evaluate_signal(signal, prices, signal_id="test", symbol="TST")
        assert isinstance(report, SignalEvaluationReport)

    def test_all_horizons_populated(self):
        signal, prices = _make_synthetic(400)
        report = evaluate_signal(signal, prices)
        assert report.ic_curve.horizons == [1, 2, 3, 5, 10]
        assert len(report.ic_curve.ic_values) == 5
        assert len(report.ic_curve.n_obs) == 5

    def test_portfolio_fields_present(self):
        signal, prices = _make_synthetic(300)
        report = evaluate_signal(signal, prices)
        p = report.portfolio
        assert hasattr(p, "sharpe")
        assert hasattr(p, "max_drawdown")
        assert hasattr(p, "after_cost_sharpe")
        assert hasattr(p, "n_trades")

    def test_robustness_fields_present(self):
        signal, prices = _make_synthetic(300)
        report = evaluate_signal(signal, prices, n_variants=5)
        r = report.robustness
        assert hasattr(r, "psr")
        assert hasattr(r, "dsr")
        assert r.n_variants == 5

    def test_hit_rate_in_range(self):
        signal, prices = _make_synthetic(300)
        report = evaluate_signal(signal, prices)
        if not math.isnan(report.hit_rate_h1):
            assert 0.0 <= report.hit_rate_h1 <= 1.0

    def test_to_dict_serializable(self):
        signal, prices = _make_synthetic(300)
        report = evaluate_signal(signal, prices)
        d = report.to_dict()
        assert "ic_curve" in d
        assert "portfolio" in d
        assert "robustness" in d

    def test_perfect_signal_has_high_hit_rate(self):
        rng = np.random.default_rng(0)
        n = 500
        returns = rng.normal(0.001, 0.01, n)
        prices = pd.Series(100 * np.cumprod(1 + returns))
        # Perfect signal: signal[t] = sign of tomorrow's return (look-ahead, for test only)
        # prices.pct_change(1).shift(-1)[t] ≈ returns[t+1]
        fwd_signs = np.sign(np.roll(returns, -1))
        fwd_signs[-1] = 0
        signal = pd.Series(fwd_signs)
        report = evaluate_signal(signal, prices, signal_id="perfect", symbol="TST")
        if not math.isnan(report.hit_rate_h1):
            assert report.hit_rate_h1 > 0.8

    def test_custom_horizons(self):
        signal, prices = _make_synthetic(400)
        report = evaluate_signal(signal, prices, horizons=[1, 5])
        assert report.horizons == [1, 5]
        assert len(report.ic_curve.ic_values) == 2

    def test_short_series_does_not_crash(self):
        signal = pd.Series([1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
        prices = pd.Series([100.0, 101.0, 99.0, 100.5, 98.0, 99.5, 101.0, 100.0])
        report = evaluate_signal(signal, prices)
        assert isinstance(report, SignalEvaluationReport)
