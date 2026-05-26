from __future__ import annotations

import numpy as np
import pandas as pd

from quant_core.stat_arb import (
    StatArbConfig,
    StatArbPairResult,
    apply_fdr_and_status,
    evaluate_pair,
)


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2022-01-03", periods=n, freq="B")


def test_cointegration_pair_estimates_spread_and_chart() -> None:
    rng = np.random.default_rng(42)
    n = 260
    idx = _dates(n)
    x = 100.0 + np.cumsum(rng.normal(0.0, 0.4, n))
    spread = np.zeros(n)
    for i in range(1, n):
        spread[i] = 0.82 * spread[i - 1] + rng.normal(0.0, 0.45)
    y = 12.0 + 1.35 * x + spread

    cfg = StatArbConfig(
        min_obs=120,
        train_bars=80,
        oos_bars=30,
        step_bars=30,
        min_folds=1,
        entry_z=1.0,
        exit_z=0.25,
        cost_bps_per_side=0.0,
        slippage_bps_per_side=0.0,
        borrow_bps_annual=0.0,
    )
    result = evaluate_pair(
        "AAA",
        pd.Series(y, index=idx),
        "BBB",
        pd.Series(x, index=idx),
        archetype="same_bar_cointegration",
        config=cfg,
    )

    assert result.status == "pending"
    assert result.n_folds > 0
    assert result.hedge_ratio is not None
    assert abs(result.hedge_ratio - 1.35) < 0.2
    assert result.chart["dates"]
    assert len(result.chart["zscore"]) == len(result.chart["dates"])


def test_fdr_marks_actionable_and_enforces_drawdown_gate() -> None:
    cfg = StatArbConfig(min_folds=3, fdr_q=0.10, min_profitable_fold_ratio=0.60)
    good = StatArbPairResult(
        pair_id="pair-good",
        symbol_y="AAA",
        symbol_x="BBB",
        horizon="short",
        archetype="lead_lag_continuation",
        lag_bars=1,
        action_type="buy_buy",
        current_signal="buy_buy",
        direction="buy_buy",
        validation_status="pending",
        status="pending",
        n_obs=300,
        n_folds=3,
        raw_pvalue=0.001,
        oos_sharpe=1.4,
        oos_return=0.12,
        max_drawdown=-0.05,
        profitable_fold_ratio=0.67,
    )
    bad_drawdown = StatArbPairResult(
        pair_id="pair-bad",
        symbol_y="CCC",
        symbol_x="DDD",
        horizon="short",
        archetype="lead_lag_continuation",
        lag_bars=1,
        action_type="buy_buy",
        current_signal="buy_buy",
        direction="buy_buy",
        validation_status="pending",
        status="pending",
        n_obs=300,
        n_folds=3,
        raw_pvalue=0.001,
        oos_sharpe=1.4,
        oos_return=0.12,
        max_drawdown=-0.35,
        profitable_fold_ratio=0.67,
    )

    out = {row.pair_id: row for row in apply_fdr_and_status([good, bad_drawdown], cfg)}

    assert out["pair-good"].status == "actionable"
    assert out["pair-good"].validation_status == "pass"
    assert out["pair-bad"].status == "rejected"
    assert "drawdown_gate" in out["pair-bad"].warnings


def test_lead_lag_buy_buy_detects_positive_relation() -> None:
    rng = np.random.default_rng(7)
    n = 260
    idx = _dates(n)
    x_ret = rng.normal(0.0002, 0.01, n)
    y_ret = np.zeros(n)
    y_ret[0] = rng.normal(0.0002, 0.004)
    for i in range(1, n):
        y_ret[i] = 0.0004 + 0.75 * x_ret[i - 1] + rng.normal(0.0, 0.003)
    x = 100.0 * np.cumprod(1.0 + x_ret)
    y = 80.0 * np.cumprod(1.0 + y_ret)

    cfg = StatArbConfig(
        min_obs=120,
        train_bars=80,
        oos_bars=30,
        step_bars=30,
        min_folds=1,
        lag_bars=1,
        cost_bps_per_side=0.0,
        slippage_bps_per_side=0.0,
        borrow_bps_annual=0.0,
    )
    result = evaluate_pair(
        "TARGET",
        pd.Series(y, index=idx),
        "LEADER",
        pd.Series(x, index=idx),
        archetype="lead_lag_continuation",
        config=cfg,
    )

    assert result.status == "pending"
    assert result.n_folds > 0
    assert result.metrics["lead_lag_beta"] > 0
    assert result.oos_return is not None
    assert "target_return" in result.chart
