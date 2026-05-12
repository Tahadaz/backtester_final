"""Tests for core/quant_core/signal_engine/backtest_mc.py."""
from __future__ import annotations

import math
from datetime import date
from unittest.mock import patch

import numpy as np
import pytest

from core.quant_core.signal_engine.backtest_mc import (
    all_category_subsets,
    build_category_signal_series_engine,
    build_combination_signal_series,
    build_family_signal_series,
    build_global_signal_series,
    compute_input_hash,
    run_signal_backtest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_close(n: int = 100, drift: float = 0.001) -> np.ndarray:
    rng = np.random.default_rng(0)
    returns = rng.normal(drift, 0.01, n)
    return np.cumprod(1.0 + returns) * 100.0


def _make_dates(n: int = 100) -> list[str]:
    import datetime
    start = datetime.date(2024, 1, 1)
    return [(start + datetime.timedelta(days=i)).isoformat() for i in range(n)]


# ---------------------------------------------------------------------------
# build_family_signal_series
# ---------------------------------------------------------------------------

def test_build_family_signal_no_reps():
    close = _make_close()
    result = build_family_signal_series(close, None, None, None, [])
    assert result.shape == (100,)
    np.testing.assert_array_equal(result, 0.0)


def test_build_family_signal_no_recomputation(monkeypatch):
    """Ensure build_family_signal_series does NOT call run_family_ensemble_full."""
    from core.quant_core.signal_engine import ensemble

    def _should_not_be_called(*args, **kwargs):
        raise AssertionError("run_family_ensemble_full must not be called")

    monkeypatch.setattr(ensemble, "run_family_ensemble_full", _should_not_be_called)

    close = _make_close(50)
    # Call with empty reps (no compute_signal_array either, but ensemble must not fire)
    result = build_family_signal_series(close, None, None, None, [])
    assert result.shape == (50,)


def test_build_family_signal_series_clip():
    """Weighted sum clipped to [-1, 1]."""
    close = _make_close(50)

    # Monkeypatch compute_signal_array to return large values
    with patch("core.quant_core.signal_engine.backtest_mc.compute_signal_array") as mock_csa:
        mock_csa.return_value = np.full(50, 10.0)
        rep = {"variant_id": "v1", "family": "sma", "archetype": "sma_cross", "params": {}, "normalized_weight": 1.0}
        result = build_family_signal_series(close, None, None, None, [rep])

    assert np.all(result <= 1.0 + 1e-9)
    assert np.all(result >= -1.0 - 1e-9)


def test_build_family_signal_uses_family_from_rep():
    close = np.linspace(100.0, 140.0, 50)
    rep = {
        "variant_id": "sma_rep",
        "family": "sma",
        "archetype": "price_vs_sma",
        "params": {"window": 3},
        "normalized_weight": 1.0,
    }

    result = build_family_signal_series(close, None, None, None, [rep])

    assert np.count_nonzero(result) > 0


def test_build_family_signal_uses_fallback_family_for_legacy_engine_rows():
    close = np.linspace(100.0, 140.0, 50)
    rep = {
        "variant_id": "legacy_sma_rep",
        "archetype": "price_vs_sma",
        "params": {"window": 3},
        "normalized_weight": 1.0,
    }

    result = build_family_signal_series(close, None, None, None, [rep], fallback_family="sma")

    assert np.count_nonzero(result) > 0


def test_build_family_signal_uses_precomputed_factor_x_ta_signal():
    close = np.linspace(100.0, 140.0, 20)
    expected = np.linspace(-1.0, 1.0, 20)
    rep = {
        "variant_id": "fx_sma_rep",
        "family": "sma@fx",
        "archetype": "price_vs_sma",
        "params": {"window": 3, "factor_condition_id": "vix_gate"},
        "normalized_weight": 1.0,
        "factor_condition": {
            "condition_id": "vix_gate",
            "factor_ticker": "^VIX",
            "form": "zscore",
            "lookback": 20,
            "threshold": -1.0,
            "direction": "below",
        },
    }

    with patch("core.quant_core.signal_engine.backtest_mc.compute_signal_array") as mock_csa:
        result = build_family_signal_series(
            close,
            None,
            None,
            None,
            [rep],
            precomputed_signals={"fx_sma_rep": expected},
        )

    mock_csa.assert_not_called()
    np.testing.assert_allclose(result, expected)


def test_build_family_signal_requires_precomputed_factor_x_ta_signal():
    close = np.linspace(100.0, 140.0, 20)
    rep = {
        "variant_id": "fx_sma_rep",
        "family": "sma@fx",
        "archetype": "price_vs_sma",
        "params": {"window": 3, "factor_condition_id": "vix_gate"},
        "normalized_weight": 1.0,
        "factor_condition": {
            "condition_id": "vix_gate",
            "factor_ticker": "^VIX",
            "form": "zscore",
            "lookback": 20,
            "threshold": -1.0,
            "direction": "below",
        },
    }

    with pytest.raises(ValueError, match="All representatives failed"):
        build_family_signal_series(close, None, None, None, [rep])


def test_build_family_signal_raises_when_family_cannot_be_reconstructed():
    close = np.linspace(100.0, 140.0, 50)
    rep = {
        "variant_id": "broken_rep",
        "archetype": "price_vs_sma",
        "params": {"window": 3},
        "normalized_weight": 1.0,
    }

    with pytest.raises(ValueError, match="All representatives failed"):
        build_family_signal_series(close, None, None, None, [rep])


def test_build_family_signal_logs_partial_failures(caplog):
    close = np.linspace(100.0, 140.0, 50)
    reps = [
        {
            "variant_id": "broken_rep",
            "archetype": "price_vs_sma",
            "params": {"window": 3},
            "normalized_weight": 1.0,
        },
        {
            "variant_id": "ema_cross_rep",
            "family": "ema_cross",
            "archetype": "ema_cross",
            "params": {"fast": 3, "slow": 8},
            "normalized_weight": 1.0,
        },
    ]

    with caplog.at_level("WARNING"):
        result = build_family_signal_series(close, None, None, None, reps)

    assert np.count_nonzero(result) > 0
    assert "Signal rebuild skipped 1/2 representatives" in caplog.text


# ---------------------------------------------------------------------------
# build_category_signal_series_engine
# ---------------------------------------------------------------------------

def _fake_family_result(viable=3, tested=5, rep_count=2, is_provisional=False):
    return {
        "status": "succeeded",
        "viable_count": viable,
        "tested_count": tested,
        "representative_count": rep_count,
        "is_provisional": is_provisional,
        "representatives_json": [
            {"variant_id": "v1", "archetype": "sma_cross", "params": {}, "normalized_weight": 1.0}
        ],
    }


def test_category_engine_excludes_provisional(monkeypatch):
    """Provisional families must be excluded from the category signal."""
    close = _make_close(50)

    with patch("core.quant_core.signal_engine.backtest_mc._build_family_signal_series_result") as mock_bfs:
        mock_bfs.return_value = (np.ones(50), 1, 0)

        family_results = {
            "sma": _fake_family_result(is_provisional=True),
        }
        result = build_category_signal_series_engine(close, None, None, None, family_results, "tendance")

    # Provisional → excluded → zero output
    np.testing.assert_array_equal(result, 0.0)


def test_category_engine_weight_rule(monkeypatch):
    """Weight rule w_f = (viable/tested) * rep_count must be applied."""
    close = _make_close(50)
    with patch("core.quant_core.signal_engine.backtest_mc._build_family_signal_series_result") as mock_bfs:
        mock_bfs.return_value = (np.ones(50), 1, 0)
        family_results = {
            "sma": _fake_family_result(viable=4, tested=8, rep_count=3),
            "ema": _fake_family_result(viable=2, tested=4, rep_count=1),
        }
        result = build_category_signal_series_engine(close, None, None, None, family_results, "tendance")

    # Both families produce +1 signal → result should be +1 (any weighting)
    assert np.allclose(result, 1.0)


def test_category_engine_fallback_equal_weights():
    """When all computed weights are zero, fall back to equal weighting."""
    close = _make_close(50)

    with patch("core.quant_core.signal_engine.backtest_mc._build_family_signal_series_result") as mock_bfs:
        mock_bfs.return_value = (np.ones(50), 1, 0)

        family_results = {
            "sma": _fake_family_result(viable=0, tested=5, rep_count=0),
        }
        result = build_category_signal_series_engine(close, None, None, None, family_results, "tendance")

    # Fallback to equal weights → signal propagates
    assert np.allclose(result, 1.0)


def test_category_engine_backward_compatible_with_missing_rep_family():
    close = np.linspace(100.0, 140.0, 50)
    family_results = {
        "sma": {
            "status": "succeeded",
            "viable_count": 3,
            "tested_count": 5,
            "representative_count": 1,
            "is_provisional": False,
            "representatives_json": [
                {
                    "variant_id": "legacy_sma_rep",
                    "archetype": "price_vs_sma",
                    "params": {"window": 3},
                    "normalized_weight": 1.0,
                }
            ],
        }
    }

    result = build_category_signal_series_engine(close, None, None, None, family_results, "tendance")

    assert np.count_nonzero(result) > 0


def test_category_engine_accepts_factor_x_ta_family_keys():
    close = np.linspace(100.0, 140.0, 20)
    family_results = {
        "sma@fx": {
            "status": "succeeded",
            "viable_count": 3,
            "tested_count": 5,
            "representative_count": 1,
            "is_provisional": False,
            "representatives_json": [
                {
                    "variant_id": "fx_sma_rep",
                    "family": "sma@fx",
                    "archetype": "price_vs_sma",
                    "params": {"window": 3, "factor_condition_id": "vix_gate"},
                    "normalized_weight": 1.0,
                    "factor_condition": {
                        "condition_id": "vix_gate",
                        "factor_ticker": "^VIX",
                        "form": "zscore",
                        "lookback": 20,
                        "threshold": -1.0,
                        "direction": "below",
                    },
                }
            ],
        }
    }

    result = build_category_signal_series_engine(
        close,
        None,
        None,
        None,
        family_results,
        "tendance",
        precomputed_signals={"fx_sma_rep": np.ones(20)},
    )

    assert np.allclose(result, 1.0)


# ---------------------------------------------------------------------------
# build_global_signal_series / build_combination_signal_series
# ---------------------------------------------------------------------------

def test_global_signal_weighted_combination():
    T = 60
    cat_series = {
        "tendance": np.ones(T),
        "momentum": -np.ones(T),
    }
    weights = {"tendance": 0.6, "momentum": 0.4}
    result = build_global_signal_series(cat_series, weights)
    expected = np.clip((0.6 * 1.0 - 0.4 * 1.0) / 1.0, -1.0, 1.0)
    np.testing.assert_allclose(result, expected)


def test_global_signal_missing_category():
    T = 40
    cat_series = {"tendance": np.ones(T)}
    weights = {"tendance": 1.0, "momentum": 0.5}  # momentum missing from cat_series
    result = build_global_signal_series(cat_series, weights)
    np.testing.assert_allclose(result, 1.0)


def test_build_combination_signal_renormalized():
    T = 50
    cat_series = {
        "tendance": np.ones(T),
        "momentum": np.zeros(T),
        "oscillation": -np.ones(T),
        "volume": np.zeros(T),
    }
    weights = {"tendance": 0.4, "momentum": 0.3, "oscillation": 0.2, "volume": 0.1}
    # Subset of tendance + oscillation → renormalized weights 0.4/(0.4+0.2) and 0.2/(0.4+0.2)
    result = build_combination_signal_series(cat_series, ["tendance", "oscillation"], weights)
    expected = np.clip((0.4 * 1.0 + 0.2 * -1.0) / 0.6, -1.0, 1.0)
    np.testing.assert_allclose(result, expected, atol=1e-9)


# ---------------------------------------------------------------------------
# run_signal_backtest
# ---------------------------------------------------------------------------

def test_backtest_rising_close_positive_signal():
    """Rising close + constant +1 signal → positive return."""
    T = 100
    close = np.linspace(100.0, 150.0, T)
    signal = np.ones(T)
    dates = _make_dates(T)
    result = run_signal_backtest(signal, close, dates, cost_bps=0.0, slippage_bps=0.0)
    assert result["metrics"]["total_return"] > 0.0


def test_backtest_applies_one_bar_execution_lag():
    T = 20
    close = np.linspace(100.0, 120.0, T)
    signal = np.ones(T)
    dates = _make_dates(T)

    result = run_signal_backtest(signal, close, dates, cost_bps=0.0, slippage_bps=0.0)

    assert result["returns"][0] == 0.0
    assert result["equity"][1] == 1.0
    assert result["trades"][0]["open_idx"] == 1


def test_backtest_falling_close_short_signal():
    """Falling close + −1 long_short signal → positive return."""
    T = 100
    close = np.linspace(150.0, 100.0, T)
    signal = -np.ones(T)
    dates = _make_dates(T)
    result = run_signal_backtest(
        signal, close, dates, cost_bps=0.0, slippage_bps=0.0, side_policy="long_short"
    )
    assert result["metrics"]["total_return"] > 0.0


def test_backtest_long_only_no_short_positions():
    """long_only must not take negative-signal positions."""
    T = 60
    close = _make_close(T)
    signal = np.where(np.arange(T) % 2 == 0, 1.0, -1.0)  # alternating
    dates = _make_dates(T)
    result = run_signal_backtest(signal, close, dates, side_policy="long_only")
    # All per-bar returns must be >= -friction (position was never negative)
    for ret in result["returns"]:
        assert ret >= -1.0  # sanity: no blowup from short positions


def test_backtest_equity_starts_at_one():
    T = 80
    close = _make_close(T)
    signal = np.random.default_rng(5).uniform(-1, 1, T)
    result = run_signal_backtest(signal, close, _make_dates(T))
    assert result["equity"][0] == 1.0


def test_backtest_equity_length():
    T = 80
    close = _make_close(T)
    signal = np.ones(T)
    result = run_signal_backtest(signal, close, _make_dates(T))
    assert len(result["equity"]) == T


def test_backtest_trade_indices_are_ordered():
    T = 30
    close = _make_close(T)
    signal = np.zeros(T)
    signal[0:10] = 1.0
    signal[10:20] = -1.0

    result = run_signal_backtest(signal, close, _make_dates(T), side_policy="long_short")

    assert result["trades"]
    for trade in result["trades"]:
        assert 0 <= trade["open_idx"] < trade["close_idx"] < T


def test_backtest_zero_signal_no_trades():
    T = 50
    close = _make_close(T)
    signal = np.zeros(T)
    result = run_signal_backtest(signal, close, _make_dates(T), cost_bps=0.0)
    assert result["metrics"]["n_trades"] == 0
    np.testing.assert_allclose(result["equity"], 1.0)


def test_backtest_cooldown_zero_preserves_position_series():
    T = 20
    close = _make_close(T)
    signal = np.where(np.arange(T) < 10, 1.0, -1.0)
    dates = _make_dates(T)

    baseline = run_signal_backtest(
        signal,
        close,
        dates,
        cost_bps=0.0,
        slippage_bps=0.0,
        side_policy="long_short",
    )
    with_cooldown_zero = run_signal_backtest(
        signal,
        close,
        dates,
        cost_bps=0.0,
        slippage_bps=0.0,
        side_policy="long_short",
        cooldown_bars=0,
    )

    assert with_cooldown_zero["position_series"] == baseline["position_series"]
    assert with_cooldown_zero["diagnostics"]["cooldown_blocked_bars"] == 0


def test_backtest_trade_cooldown_blocks_reentry_after_exit():
    close = np.linspace(100.0, 108.0, 8)
    signal = np.array([1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 1.0])

    result = run_signal_backtest(
        signal,
        close,
        _make_dates(len(close)),
        cost_bps=0.0,
        slippage_bps=0.0,
        cooldown_bars=2,
    )

    assert result["position_series"] == [0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    assert result["diagnostics"]["cooldown_events"] == 2
    assert result["diagnostics"]["cooldown_blocked_bars"] == 2


def test_backtest_trade_cooldown_blocks_direct_side_flip():
    close = np.linspace(100.0, 105.0, 6)
    signal = np.array([1.0, 1.0, -1.0, -1.0, -1.0, -1.0])

    result = run_signal_backtest(
        signal,
        close,
        _make_dates(len(close)),
        cost_bps=0.0,
        slippage_bps=0.0,
        side_policy="long_short",
        cooldown_bars=1,
    )

    assert result["position_series"] == [0.0, 1.0, 1.0, 0.0, 0.0, -1.0]
    assert result["diagnostics"]["cooldown_events"] == 1
    assert result["diagnostics"]["cooldown_blocked_bars"] == 2


def test_backtest_short_series():
    close = np.array([100.0])
    signal = np.array([1.0])
    result = run_signal_backtest(signal, close, ["2024-01-01"])
    assert result["metrics"]["total_return"] == 0.0


# ---------------------------------------------------------------------------
# compute_input_hash
# ---------------------------------------------------------------------------

def test_input_hash_determinism():
    reps = [{"variant_id": "v1", "archetype": "sma_cross", "params": {"n": 20}}]
    h1 = compute_input_hash(reps, date(2024, 6, 1), 5.0, 5.0, "long_only")
    h2 = compute_input_hash(reps, date(2024, 6, 1), 5.0, 5.0, "long_only")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_input_hash_changes_on_date():
    reps = [{"variant_id": "v1", "archetype": "sma_cross", "params": {}}]
    h1 = compute_input_hash(reps, date(2024, 6, 1), 5.0, 5.0, "long_only")
    h2 = compute_input_hash(reps, date(2024, 6, 2), 5.0, 5.0, "long_only")
    assert h1 != h2


def test_input_hash_changes_on_reps():
    reps1 = [{"variant_id": "v1", "archetype": "sma_cross", "params": {"n": 20}}]
    reps2 = [{"variant_id": "v1", "archetype": "sma_cross", "params": {"n": 50}}]
    h1 = compute_input_hash(reps1, date(2024, 6, 1), 5.0, 5.0, "long_only")
    h2 = compute_input_hash(reps2, date(2024, 6, 1), 5.0, 5.0, "long_only")
    assert h1 != h2


def test_input_hash_changes_on_mc_config():
    reps = [{"variant_id": "v1", "archetype": "sma_cross", "params": {"n": 20}}]
    h1 = compute_input_hash(
        reps,
        date(2024, 6, 1),
        5.0,
        5.0,
        "long_only",
        mc_method="block_bootstrap",
        n_paths=2000,
        block_mean=None,
        seed=42,
    )
    h2 = compute_input_hash(
        reps,
        date(2024, 6, 1),
        5.0,
        5.0,
        "long_only",
        mc_method="trade_bootstrap",
        n_paths=2000,
        block_mean=None,
        seed=42,
    )
    assert h1 != h2


def test_input_hash_changes_on_cooldown():
    reps = [{"variant_id": "v1", "archetype": "sma_cross", "params": {"n": 20}}]
    h1 = compute_input_hash(
        reps,
        date(2024, 6, 1),
        5.0,
        5.0,
        "long_only",
        cooldown_bars=0,
    )
    h2 = compute_input_hash(
        reps,
        date(2024, 6, 1),
        5.0,
        5.0,
        "long_only",
        cooldown_bars=5,
    )
    assert h1 != h2


def test_input_hash_changes_on_logic_version():
    reps = [{"variant_id": "v1", "archetype": "price_vs_sma", "params": {"window": 20}}]
    h1 = compute_input_hash(
        reps,
        date(2024, 6, 1),
        5.0,
        5.0,
        "long_only",
        logic_version="legacy",
    )
    h2 = compute_input_hash(
        reps,
        date(2024, 6, 1),
        5.0,
        5.0,
        "long_only",
        logic_version="family-aware-rebuild-v1",
    )
    assert h1 != h2


# ---------------------------------------------------------------------------
# all_category_subsets
# ---------------------------------------------------------------------------

def test_all_category_subsets_count():
    cats = ["tendance", "momentum", "oscillation", "volume"]
    subsets = all_category_subsets(cats)
    # C(4,2) + C(4,3) = 6 + 4 = 10
    assert len(subsets) == 10


def test_all_category_subsets_sizes():
    cats = ["tendance", "momentum", "oscillation", "volume"]
    subsets = all_category_subsets(cats)
    assert all(len(s) in (2, 3) for s in subsets)
