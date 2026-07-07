from __future__ import annotations

import datetime as dt

import pandas as pd

from quant_core.fundamentals.cross_section.own_history import OwnHistoryConfig, compute_own_history_signals


def test_own_history_requires_min_months_and_distinct_fiscal_years() -> None:
    rows = []
    dates = pd.date_range("2020-01-31", periods=40, freq="ME")
    for idx, as_of in enumerate(dates):
        rows.append(
            {
                "symbol": "AAA",
                "as_of_date": as_of.date(),
                "pillar_val_raw": float(idx),
                "pillar_val": float(idx) / 10.0,
                "history": [type("Row", (), {"statement_year": 2020 + min(idx // 12, 2)})()],
            }
        )
    frame = pd.DataFrame(rows)

    enriched = compute_own_history_signals(
        frame,
        config=OwnHistoryConfig(trailing_months=60, min_months=36, min_fiscal_years=3),
    )

    assert enriched.iloc[10]["own_hist_z"] != enriched.iloc[10]["own_hist_z"]
    assert enriched.iloc[-1]["own_hist_z"] == enriched.iloc[-1]["own_hist_z"]
    assert enriched.iloc[-1]["own_hist_obs"] >= 36
    assert enriched.iloc[-1]["own_hist_fiscal_years"] >= 3
