from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from quant_core.fundamentals.cross_section.final_model_validation import (
    architecture_bakeoff,
    extreme_audit,
    leave_one_influence,
    market_alpha_table,
    rank_transform,
    strategy_period_returns,
    transform_by_date,
    winsorize_series,
)
from quant_core.fundamentals.cross_section.pillars import mad_winsorized_z


def _frame() -> pd.DataFrame:
    rows = []
    dates = [dt.date(2021, 1, 31), dt.date(2021, 2, 28), dt.date(2021, 3, 31)]
    for d_i, d in enumerate(dates):
        for i in range(12):
            rows.append(
                {
                    "symbol": f"S{i:02d}",
                    "as_of_date": d,
                    "book_to_market_raw": 1.0 + i,
                    "cashflow_price_raw": -0.5 if i == 0 else 0.5 + i,
                    "book_to_market": float(i),
                    "cashflow_price": float(i) if i != 0 else -5.0,
                    "size_log_mcap": float(20 - i),
                    "adv20": float(1000 + i),
                    "market_cap_raw": float(100 + i),
                    "sales_price_raw": float(i),
                    "is_financial": i % 5 == 0,
                    "sector": "Bank" if i % 5 == 0 else "Industrial",
                    "fwd_return_1m": i / 400.0 + d_i / 400.0,
                    "fwd_return_3m": i / 200.0 + d_i / 200.0,
                    "fwd_return_6m": i / 100.0 + d_i / 100.0,
                    "fwd_return_12m": i / 50.0 + d_i / 50.0,
                }
            )
    return pd.DataFrame(rows)


def test_winsorization_behavior() -> None:
    s = pd.Series([1.0, 2.0, 3.0, 1000.0])
    out = winsorize_series(s, 0.25, 0.75)
    assert out.max() < 1000.0
    assert out.min() > 1.0


def test_rank_and_mad_transformations() -> None:
    s = pd.Series([10.0, 20.0, 30.0])
    assert rank_transform(s).tolist() == pytest.approx([1 / 3, 2 / 3, 1.0])
    mad = mad_winsorized_z(pd.Series([1.0, 2.0, 3.0, 1000.0]))
    assert abs(float(mad.mean())) < 1e-12


def test_negative_cfo_and_denominator_audit_counts() -> None:
    audit, extremes = extreme_audit(_frame(), ["cashflow_price", "book_to_market"])
    cfp = audit[audit["signal"] == "cashflow_price"].iloc[0]
    assert int(cfp["negative_cfo"]) == 3
    assert not extremes.empty


def test_transform_by_date_preserves_no_lookahead_shape() -> None:
    frame = _frame()
    out = transform_by_date(frame, "book_to_market_raw", "rank")
    assert len(out) == len(frame)
    assert out.notna().all()


def test_leave_one_stock_logic() -> None:
    frame = _frame()
    out = leave_one_influence(frame, "book_to_market", by="symbol", horizon="6m")
    assert set(out["by"]) == {"symbol"}
    assert out["excluded"].nunique() == 12


def test_market_attribution_calculates_alpha_beta() -> None:
    df = pd.DataFrame({"return": [0.02, 0.03, 0.01, 0.04, 0.02, 0.05, 0.01, 0.03], "market_return": [0.01, 0.02, 0.0, 0.03, 0.01, 0.04, 0.0, 0.02]})
    out = market_alpha_table({"x": df})
    assert out.loc[0, "periods"] == 8
    assert np.isfinite(out.loc[0, "alpha"])


def test_architecture_signals_and_sleeves() -> None:
    frame = _frame()
    arch, series = architecture_bakeoff(frame, horizon="6m", cost_bps=0.0)
    assert "separate_sleeves_50_50" in set(arch["signal"])
    assert "separate_sleeves_50_50" in series
    assert not strategy_period_returns(frame, "book_to_market", horizon="6m", cost_bps=0.0).empty
