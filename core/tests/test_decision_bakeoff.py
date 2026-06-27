from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_core.research.decision_bakeoff import (  # noqa: E402
    BakeoffConfig,
    FIXED_THRESHOLDS,
    label_scores,
    purged_walk_forward_splits,
    run_bakeoff,
    topsis_closeness,
)


def test_fixed_threshold_labels_match_current_buckets() -> None:
    scores = np.array([-80.0, -50.0, -49.9, -15.0, 0.0, 15.0, 15.1, 50.0, 50.1])
    labels = label_scores(scores, FIXED_THRESHOLDS).tolist()

    assert labels == [
        "strong_sell",
        "sell",
        "sell",
        "hold",
        "hold",
        "hold",
        "buy",
        "buy",
        "strong_buy",
    ]


def test_topsis_closeness_prefers_benefit_high_and_cost_low() -> None:
    matrix = np.array(
        [
            [1.0, 10.0],
            [10.0, 1.0],
            [5.0, 5.0],
        ]
    )
    closeness = topsis_closeness(matrix, weights=[0.5, 0.5], benefit=[True, False])

    assert closeness[1] > closeness[2] > closeness[0]


def test_purged_walk_forward_splits_have_embargo_gap() -> None:
    idx = pd.date_range("2024-01-01", periods=160, freq="B")
    frame = pd.DataFrame({"date": idx, "value": np.arange(len(idx))})
    splits = purged_walk_forward_splits(
        frame,
        n_splits=3,
        min_train_dates=60,
        min_test_dates=20,
        embargo=5,
    )

    assert splits
    for window in splits:
        assert window.train_end < window.test_start
        gap = len(pd.bdate_range(window.train_end, window.test_start)) - 2
        assert gap >= 5
        train_dates = set(frame.loc[window.train_index, "date"])
        test_dates = set(frame.loc[window.test_index, "date"])
        assert train_dates.isdisjoint(test_dates)


def _synthetic_inputs(n: int = 260) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(123)
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    latent = np.sin(np.linspace(0.0, 16.0, n)) + rng.normal(0.0, 0.2, n)
    categories = ("tendance", "momentum", "oscillation", "volume")

    rows = []
    for cat_idx, category in enumerate(categories):
        score = np.clip(latent * 55.0 + rng.normal(0.0, 8.0 + cat_idx, n), -100.0, 100.0)
        for date, val in zip(dates, score):
            rows.append(
                {
                    "date": date,
                    "symbol": "AAA",
                    "source": "engine:test",
                    "category": category,
                    "horizon": "weekly",
                    "score_pct": val,
                    "is_oos": True,
                }
            )
    score_history = pd.DataFrame(rows)

    returns = np.zeros(n)
    returns[:-1] = np.clip(latent[:-1] * 0.006 + rng.normal(0.0, 0.004, n - 1), -0.04, 0.04)
    close = 100.0 * np.cumprod(1.0 + returns)
    prices = pd.DataFrame({"date": dates, "symbol": "AAA", "close": close})
    return score_history, prices


def test_run_bakeoff_produces_offline_metrics_for_multiple_methods() -> None:
    score_history, prices = _synthetic_inputs()
    config = BakeoffConfig(
        source="engine:test",
        horizon="weekly",
        symbols=("AAA",),
        fwd_horizons=(1,),
        n_splits=3,
        min_train_dates=80,
        min_test_dates=30,
        min_action_obs=4,
        cost_bps=5.0,
        use_oos_only=True,
    )

    result = run_bakeoff(score_history, prices, config)

    assert not result.metrics.empty
    assert not result.predictions.empty
    assert not result.thresholds.empty
    assert "baseline_fixed" in set(result.metrics["method"])
    assert "topsis_category" in set(result.metrics["method"])
    assert "threshold_optimized" in set(result.metrics["method"])
    assert result.predictions["decision_score"].between(-100.0, 100.0).all()
    assert "Offline research run only" in result.summary_markdown()

