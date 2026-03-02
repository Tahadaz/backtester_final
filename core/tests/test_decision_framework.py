from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_core.decision.regime import classify_regime  # noqa: E402
from quant_core.decision.decision_page import build_decision_page  # noqa: E402
from quant_core.decision.risk import compute_rr_and_invalidation  # noqa: E402
from quant_core.decision.scoring import compute_confidence_score, compute_opportunity_score  # noqa: E402


def _bars_from_close(close: pd.Series) -> pd.DataFrame:
    high = close * 1.01
    low = close * 0.99
    open_px = close.shift(1).fillna(close.iloc[0])
    volume = pd.Series(100_000.0, index=close.index)
    return pd.DataFrame(
        {
            "Open": open_px,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        }
    )


def test_regime_classification_bullish_vs_bearish() -> None:
    idx = pd.date_range("2020-01-01", periods=260, freq="B")
    up_close = pd.Series(np.linspace(100.0, 180.0, num=len(idx)), index=idx)
    down_close = pd.Series(np.linspace(180.0, 100.0, num=len(idx)), index=idx)

    bull = classify_regime(_bars_from_close(up_close))
    bear = classify_regime(_bars_from_close(down_close))

    assert bull["bias"] == 1
    assert bull["score"] > 70
    assert bear["bias"] == -1
    assert bear["score"] < 40


def test_opportunity_and_confidence_scores_are_normalized() -> None:
    idx = pd.date_range("2022-01-01", periods=300, freq="B")
    close = pd.Series(np.linspace(100.0, 140.0, num=len(idx)), index=idx)
    bars = _bars_from_close(close)

    opp = compute_opportunity_score(
        bars=bars,
        strategy_direction=1,
        strategy_kind="ma_cross",
    )

    row = {
        "strategy_kind": "ma_cross",
        "cagr": 0.18,
        "sharpe": 1.4,
        "max_drawdown": -0.18,
        "n_fills": 42,
        "efficiency": 0.12,
        "best_params_json": {"strategy.sma_fast_window": 20, "strategy.sma_slow_window": 80},
    }
    same_rows = [
        {**row, "cagr": 0.17, "best_params_json": {"strategy.sma_fast_window": 18, "strategy.sma_slow_window": 78}},
        {**row, "cagr": 0.19, "best_params_json": {"strategy.sma_fast_window": 19, "strategy.sma_slow_window": 82}},
        {**row, "cagr": 0.16, "best_params_json": {"strategy.sma_fast_window": 21, "strategy.sma_slow_window": 84}},
        {**row, "cagr": 0.15, "best_params_json": {"strategy.sma_fast_window": 22, "strategy.sma_slow_window": 86}},
    ]
    wf_rows = [
        {"strategy_kind": "ma_cross", "objective_value": 0.11, "train_objective_value": 0.14, "stat.cagr": 0.12},
        {"strategy_kind": "ma_cross", "objective_value": 0.09, "train_objective_value": 0.13, "stat.cagr": 0.10},
    ]
    conf = compute_confidence_score(
        row=row,
        same_strategy_rows=same_rows,
        walk_forward_rows=wf_rows,
        returns=[0.01, -0.005, 0.004, -0.003, 0.006, -0.002, 0.007, -0.004, 0.005, -0.006],
        mc_paths=64,
        random_seed=123,
    )

    assert 0.0 <= float(opp["total"]) <= 100.0
    assert 0.0 <= float(conf["total"]) <= 100.0
    assert set(opp["layers"].keys()) == {"regime", "direction", "confirmation", "timing", "risk"}
    assert set(conf["layers"].keys()) == {
        "oos_performance",
        "is_oos_stability",
        "parameter_robustness",
        "drawdown_tail_risk",
        "cost_sensitivity",
    }


def test_confidence_uses_walk_forward_summary_when_rows_missing() -> None:
    row = {
        "strategy_kind": "ma_cross",
        "cagr": 0.12,
        "sharpe": 1.1,
        "max_drawdown": -0.2,
        "n_fills": 28,
        "efficiency": 0.08,
        "best_params_json": {"strategy.sma_fast_window": 20, "strategy.sma_slow_window": 80},
    }
    summary = {
        "n_folds": 6,
        "objective_mean": 0.09,
        "objective_median": 0.08,
        "is_oos_gap_median": 0.12,
        "cagr": 0.11,
        "sharpe": 1.0,
    }
    conf = compute_confidence_score(
        row=row,
        same_strategy_rows=[row],
        walk_forward_rows=[],
        walk_forward_summary=summary,
        returns=[0.01, -0.004, 0.005, -0.003, 0.006, -0.002, 0.004, -0.001],
        mc_paths=32,
        random_seed=7,
    )

    assert 0.0 <= float(conf["total"]) <= 100.0
    oos_inputs = conf["layers"]["oos_performance"]["inputs"]
    stability_inputs = conf["layers"]["is_oos_stability"]["inputs"]
    assert oos_inputs["source"] == "walk_forward_summary"
    assert int(oos_inputs["n_folds"]) == 6
    assert float(stability_inputs["median_is_oos_gap_ratio"]) == pytest.approx(0.12)


def test_opportunity_confirmation_neutral_direction_uses_baseline() -> None:
    idx = pd.date_range("2023-01-01", periods=280, freq="B")
    close = pd.Series(np.linspace(100.0, 150.0, num=len(idx)), index=idx)
    bars = _bars_from_close(close)

    opp = compute_opportunity_score(
        bars=bars,
        strategy_direction=0,
        strategy_kind="ma_cross",
    )
    confirmation = opp["layers"]["confirmation"]
    inputs = confirmation["inputs"]

    assert float(confirmation["score"]) == pytest.approx(50.0)
    assert inputs["applied_check_set"] == "neutral_none"
    assert inputs["applied_checks"] == []
    assert "neutral direction -> no directional confirmation" in str(confirmation["explain"])


def test_bearish_regime_with_short_direction_uses_short_confirmations() -> None:
    idx = pd.date_range("2020-01-01", periods=280, freq="B")
    close = pd.Series(np.linspace(220.0, 120.0, num=len(idx)), index=idx)
    bars = _bars_from_close(close)

    opp = compute_opportunity_score(
        bars=bars,
        strategy_direction=-1,
        strategy_kind="ma_cross",
    )
    conf_inputs = opp["layers"]["confirmation"]["inputs"]

    assert conf_inputs["applied_check_set"] == "short"
    assert conf_inputs["policy"]["regime_bucket"] == "bearish"
    assert conf_inputs["policy"]["counter_regime"] is False


def test_bullish_regime_with_short_direction_is_penalized_or_stricter() -> None:
    idx = pd.date_range("2020-01-01", periods=280, freq="B")
    close = pd.Series(np.linspace(120.0, 220.0, num=len(idx)), index=idx)
    bars = _bars_from_close(close)

    opp = compute_opportunity_score(
        bars=bars,
        strategy_direction=-1,
        strategy_kind="ma_cross",
    )
    conf_inputs = opp["layers"]["confirmation"]["inputs"]
    policy = conf_inputs["policy"]

    assert conf_inputs["applied_check_set"] == "short"
    assert policy["regime_bucket"] == "bullish"
    assert policy["counter_regime"] is True
    assert int(conf_inputs["required"]) > int(policy["base_required"]) or float(policy["score_penalty"]) > 0.0


def test_regime_insufficient_history_label() -> None:
    idx = pd.date_range("2024-01-01", periods=120, freq="B")
    close = pd.Series(np.linspace(100.0, 110.0, num=len(idx)), index=idx)
    regime = classify_regime(_bars_from_close(close))

    assert regime["label"] == "insufficient_history"
    assert float(regime["score"]) == pytest.approx(50.0)


def test_invalid_rr_orientation_forces_no_trade_with_reason() -> None:
    risk_payload = compute_rr_and_invalidation(
        direction=1,
        entry=100.0,
        stop=105.0,
        target=99.0,
    )
    page = build_decision_page(
        symbol="IAM",
        strategy_kind="ma_cross",
        trial_id="trial_invalid_rr",
        strategy_direction=1,
        levels={"support": 95.0, "resistance": 110.0, "entry": 100.0, "stop": 105.0, "target": 99.0},
        risk_payload=risk_payload,
        opportunity={"total": 85.0, "layers": {}, "trigger_snapshot": {"rsi14": 56.2, "macd_hist": 0.12}},
        confidence={"total": 80.0, "layers": {}},
        extra_explain={},
    )

    assert page.status == "no_trade"
    assert page.explain["risk_validation"]["levels_valid"] is False
    assert "invalid_long_target_orientation" in str(page.explain["risk_validation"]["invalid_reason"])
