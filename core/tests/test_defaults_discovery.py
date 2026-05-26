from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import quant_core.analysis.defaults_discovery as defaults_discovery  # noqa: E402
from quant_core.analysis.defaults_discovery import (  # noqa: E402
    aggregate_bucket_defaults,
    discover_sma_defaults_all_horizons,
    discover_sma_defaults,
    validate_buckets,
)


def test_validate_buckets_rejects_overlap() -> None:
    with pytest.raises(ValueError):
        validate_buckets(
            [
                {"bucket_id": "B1", "low": 3, "high": 10},
                {"bucket_id": "B2", "low": 10, "high": 20},
            ]
        )


def test_validate_buckets_rejects_unordered_ranges() -> None:
    with pytest.raises(ValueError):
        validate_buckets(
            [
                {"bucket_id": "B1", "low": 3, "high": 10},
                {"bucket_id": "B2", "low": 11, "high": 20},
                {"bucket_id": "B3", "low": 8, "high": 15},
            ]
        )


def test_aggregate_bucket_defaults_prefers_mode_when_stable() -> None:
    chosen, meta = aggregate_bucket_defaults(
        [12, 12, 12, 13, 14],
        bucket_low=8,
        bucket_high=20,
        mode_threshold=0.20,
        snap_to_nice=False,
    )
    assert chosen == 12
    assert meta["mode_frequency"] >= 0.20
    assert meta["used_mode"] == 1.0


def test_aggregate_bucket_defaults_falls_back_to_median_when_unstable() -> None:
    chosen, meta = aggregate_bucket_defaults(
        [8, 9, 10, 11],
        bucket_low=8,
        bucket_high=12,
        mode_threshold=0.50,
        snap_to_nice=False,
    )
    assert chosen in {9, 10}
    assert meta["used_mode"] == 0.0


def _make_bars(length: int = 160) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=int(length), freq="D")
    close = 100.0 + np.linspace(0.0, 12.0, int(length)) + (0.35 * np.sin(np.arange(int(length), dtype="float64")))
    return pd.DataFrame({"Close": close}, index=idx)


def _tiny_buckets() -> list[dict[str, int | str]]:
    return [
        {"bucket_id": "B1", "low": 2, "high": 4},
        {"bucket_id": "B2", "low": 5, "high": 5},
        {"bucket_id": "B3", "low": 6, "high": 6},
        {"bucket_id": "B4", "low": 7, "high": 7},
        {"bucket_id": "B5", "low": 8, "high": 8},
        {"bucket_id": "B6", "low": 9, "high": 9},
        {"bucket_id": "B7", "low": 10, "high": 10},
        {"bucket_id": "B8", "low": 11, "high": 11},
        {"bucket_id": "B9", "low": 12, "high": 12},
    ]


def test_discover_sma_defaults_rejects_cross_signal_mode() -> None:
    bars = _make_bars()
    with pytest.raises(ValueError, match="Only SMA-price level mode allowed for horizon calibration"):
        discover_sma_defaults(
            bars,
            buckets=_tiny_buckets(),
            train_window=60,
            step_size=20,
            use_test_window=True,
            test_window=20,
            signal_mode="cross",
            snap_to_nice=False,
        )


def test_discover_sma_defaults_horizon_short_sets_meta_windows() -> None:
    bars = _make_bars(length=900)
    result = discover_sma_defaults(
        bars,
        buckets=_tiny_buckets(),
        horizon="short",
        signal_mode="level",
        snap_to_nice=False,
    )
    meta = dict(result.get("meta") or {})
    assert meta.get("horizon") == "short"
    assert int(meta.get("train_window") or 0) == 252
    assert int(meta.get("test_window") or 0) == 63
    assert int(meta.get("step_size") or 0) == 63


def test_discover_sma_defaults_explicit_windows_override_horizon_defaults() -> None:
    bars = _make_bars(length=900)
    result = discover_sma_defaults(
        bars,
        buckets=_tiny_buckets(),
        horizon="short",
        test_window=63,
        signal_mode="level",
        snap_to_nice=False,
    )
    meta = dict(result.get("meta") or {})
    assert meta.get("horizon") == "short"
    assert int(meta.get("test_window") or 0) == 63


def test_discover_sma_defaults_all_horizons_returns_switchable_payload() -> None:
    bars = _make_bars(length=1100)
    result = discover_sma_defaults_all_horizons(
        bars,
        buckets=_tiny_buckets(),
        primary_horizon="medium",
        signal_mode="level",
        snap_to_nice=False,
    )

    assert result.get("active_horizon") == "medium"
    assert result.get("meta", {}).get("active_horizon") == "medium"
    horizons = result.get("horizons")
    assert isinstance(horizons, dict)
    for token in ("short", "medium", "long"):
        assert token in horizons
        assert isinstance(horizons[token], dict)
        assert len(list(horizons[token].get("defaults") or [])) == 9
    defaults_by_horizon = result.get("defaults_by_horizon")
    assert isinstance(defaults_by_horizon, dict)
    assert len(list(defaults_by_horizon.get("medium") or [])) == 9


def test_discover_sma_defaults_grid_results_has_multiple_n_per_bucket_window() -> None:
    bars = _make_bars()
    result = discover_sma_defaults(
        bars,
        buckets=_tiny_buckets(),
        train_window=60,
        step_size=20,
        use_test_window=True,
        test_window=20,
        signal_mode="level",
        snap_to_nice=False,
    )
    rows = [r for r in result["grid_results"] if int(r["window_index"]) == 0 and str(r["bucket_id"]) == "B1"]
    assert len(rows) == 3
    assert len({int(r["n"]) for r in rows}) == 3
    assert len(result["grid_results"]) > len(result["walk_forward_winners"])


def test_discover_sma_defaults_uses_train_selection_when_test_window_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = _make_bars()

    def fake_eval(
        bars_slice: pd.DataFrame,
        *,
        n: int,
        allow_short: bool,
        signal_mode: str,
        score_drawdown_weight: float,
        score_turnover_weight: float,
        use_net_after_costs: bool,
        cost_rate: float,
        **kwargs: object,
    ) -> dict[str, float]:
        _ = (allow_short, signal_mode, score_drawdown_weight, score_turnover_weight, use_net_after_costs, cost_rate, kwargs)
        is_test = len(bars_slice) < 60
        if is_test:
            score = 100.0 - abs(float(n) - 3.0) * 10.0
        else:
            score = 50.0 - abs(float(n) - 2.0) * 5.0
        return {
            "score": float(score),
            "sharpe": float(score / 100.0),
            "max_drawdown": float(abs(float(n) - 3.0) / 10.0),
            "turnover": float(n) / 1000.0,
            "net_sharpe": float(score / 100.0),
            "total_return": float(score / 1000.0),
            "net_total_return": float(score / 1000.0),
            "sample_count": float(len(bars_slice)),
        }

    monkeypatch.setattr(defaults_discovery, "_evaluate_sma_window", fake_eval)

    result = discover_sma_defaults(
        bars,
        buckets=_tiny_buckets(),
        train_window=60,
        step_size=20,
        use_test_window=True,
        test_window=20,
        signal_mode="level",
        snap_to_nice=False,
    )
    b1_report = next(r for r in result["bucket_reports"] if str(r["bucket_id"]) == "B1")
    assert int(b1_report["chosen_default_n"]) == 2
    assert str(b1_report.get("selection_basis")) == "train"
    b1_ranking = next(r for r in result["bucket_global_rankings"] if str(r["bucket_id"]) == "B1")
    assert int(b1_ranking["rows"][0]["n"]) == 2


def test_discover_sma_defaults_defaults_are_strictly_increasing() -> None:
    bars = _make_bars()
    result = discover_sma_defaults(
        bars,
        buckets=_tiny_buckets(),
        train_window=60,
        step_size=20,
        use_test_window=True,
        test_window=20,
        signal_mode="level",
        snap_to_nice=False,
    )
    defaults = [int(x) for x in result["defaults"]]
    assert all(a < b for a, b in zip(defaults, defaults[1:]))
