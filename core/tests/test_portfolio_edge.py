import math

import numpy as np
import pandas as pd

from core.quant_core.research.portfolio_edge import (
    PortfolioEdgeMember,
    build_portfolio_edge_payload,
)


def _prices(dates: pd.DatetimeIndex, step_return: float) -> pd.Series:
    values = 100.0 * np.power(1.0 + step_return, np.arange(len(dates)))
    return pd.Series(values, index=dates)


def _member(
    symbol: str,
    *,
    bucket: str,
    direction: str,
    score_value: float,
    step_return: float,
    dates: pd.DatetimeIndex,
    selection_dates: pd.DatetimeIndex | None = None,
    proof_dates: pd.DatetimeIndex | None = None,
) -> PortfolioEdgeMember:
    return PortfolioEdgeMember(
        symbol=symbol,
        bucket=bucket,
        direction=direction,  # type: ignore[arg-type]
        score_series=pd.Series(score_value, index=dates),
        prices=_prices(dates, step_return),
        selection_oos_dates=selection_dates if selection_dates is not None else dates[:-1],
        proof_oos_dates=proof_dates if proof_dates is not None else dates[:-1],
    )


def test_portfolio_edge_equal_weights_active_long_and_short_returns() -> None:
    dates = pd.bdate_range("2024-01-01", periods=90)
    payload = build_portfolio_edge_payload(
        members=[
            _member("AAA", bucket="strong_buy", direction="long", score_value=80.0, step_return=0.02, dates=dates),
            _member("BBB", bucket="strong_sell", direction="short", score_value=-80.0, step_return=-0.04, dates=dates),
        ],
        horizon="monthly",
        total_count=2,
        fwd_horizon_bars=1,
        holding_period_candidates=(1,),
        cost_bps_per_side=0.0,
        return_calc_method="close_to_close",
    )

    assert payload["active_count"] == 2
    assert payload["long_count"] == 1
    assert payload["short_count"] == 1
    assert payload["n"] == 60
    assert math.isclose(payload["action_expected_return_net"], 0.03, rel_tol=1e-9)
    assert payload["hit_rate"] == 1.0


def test_portfolio_edge_excludes_non_actionable_members_from_active_weight() -> None:
    dates = pd.bdate_range("2024-01-01", periods=70)
    payload = build_portfolio_edge_payload(
        members=[
            _member("AAA", bucket="buy", direction="long", score_value=30.0, step_return=0.01, dates=dates),
            _member("BBB", bucket="hold", direction="none", score_value=0.0, step_return=-0.20, dates=dates),
        ],
        horizon="weekly",
        total_count=2,
        fwd_horizon_bars=1,
        holding_period_candidates=(1,),
        cost_bps_per_side=0.0,
        return_calc_method="close_to_close",
    )

    assert payload["active_count"] == 1
    assert payload["total_count"] == 2
    assert math.isclose(payload["action_expected_return_net"], 0.01, rel_tol=1e-9)
    assert payload["hit_rate"] == 1.0


def test_portfolio_edge_reports_proof_over_all_proof_dates() -> None:
    dates = pd.bdate_range("2024-01-01", periods=80)
    payload = build_portfolio_edge_payload(
        members=[
            _member(
                "AAA",
                bucket="buy",
                direction="long",
                score_value=30.0,
                step_return=0.01,
                dates=dates,
                selection_dates=dates[:8],
                proof_dates=dates[:50],
            ),
        ],
        horizon="weekly",
        total_count=1,
        fwd_horizon_bars=1,
        holding_period_candidates=(1,),
        cost_bps_per_side=0.0,
        return_calc_method="close_to_close",
    )

    assert payload["selection_n"] == 8
    assert payload["n"] == 50
    assert payload["window_start"] == dates[0].date().isoformat()
    assert payload["window_end"] == dates[49].date().isoformat()
    assert math.isclose(payload["action_expected_return_net"], 0.01, rel_tol=1e-9)
