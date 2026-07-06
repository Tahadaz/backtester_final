from __future__ import annotations

import datetime as dt

import pandas as pd

from quant_core.fundamentals.cross_section.technical_conditioning import (
    NEUTRAL_VERDICT,
    _assign_sfc_terciles,
    _conditioning_verdict,
)


def test_assign_sfc_terciles_balances_full_buckets_and_orders_descending() -> None:
    rows = []
    for as_of in (dt.date(2026, 1, 31), dt.date(2026, 2, 28)):
        for rank in range(9):
            rows.append(
                {
                    "as_of_date": as_of,
                    "symbol": f"S{rank}",
                    "sfc": float(9 - rank),
                }
            )
    out = _assign_sfc_terciles(pd.DataFrame(rows))

    for as_of, sub in out.groupby("as_of_date"):
        counts = sub["sfc_tercile"].value_counts().to_dict()
        assert counts["top"] == 3
        assert counts["middle"] == 3
        assert counts["bottom"] == 3
        ordered = sub.sort_values(["sfc", "symbol"], ascending=[False, True])["sfc_tercile"].tolist()
        assert ordered[:3] == ["top", "top", "top"]
        assert ordered[3:6] == ["middle", "middle", "middle"]
        assert ordered[6:] == ["bottom", "bottom", "bottom"]


def test_assign_sfc_terciles_keeps_middle_non_empty_for_four_names() -> None:
    frame = pd.DataFrame(
        {
            "as_of_date": [dt.date(2026, 1, 31)] * 4,
            "symbol": ["AAA", "BBB", "CCC", "DDD"],
            "sfc": [4.0, 3.0, 2.0, 1.0],
        }
    )
    out = _assign_sfc_terciles(frame)
    ordered = out.sort_values(["sfc", "symbol"], ascending=[False, True])["sfc_tercile"].tolist()

    assert ordered == ["top", "top", "middle", "bottom"]


def test_assign_sfc_terciles_marks_nan_rows_uncovered_and_partitions_covered() -> None:
    frame = pd.DataFrame(
        {
            "as_of_date": [dt.date(2026, 1, 31)] * 6,
            "symbol": ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"],
            "sfc": [5.0, 4.0, 3.0, 2.0, None, None],
        }
    )
    out = _assign_sfc_terciles(frame)

    uncovered = out[out["sfc_tercile"] == "uncovered"]
    covered = out[out["sfc_tercile"] != "uncovered"]
    counts = covered["sfc_tercile"].value_counts().to_dict()

    assert uncovered["symbol"].tolist() == ["EEE", "FFF"]
    assert counts["top"] + counts["middle"] + counts["bottom"] == len(covered)


def test_conditioning_verdict_stays_neutral_when_only_one_event_horizon_clears_threshold() -> None:
    conditioned = pd.DataFrame(
        [
            {"tercile": "top", "horizon": "3m", "mean_ic": 0.13, "nw_t_stat": 2.4},
            {"tercile": "top", "horizon": "6m", "mean_ic": 0.14, "nw_t_stat": 2.1},
            {"tercile": "top", "horizon": "12m", "mean_ic": 0.05, "nw_t_stat": 0.8},
            {"tercile": "middle", "horizon": "3m", "mean_ic": 0.12, "nw_t_stat": 3.0},
            {"tercile": "middle", "horizon": "6m", "mean_ic": 0.21, "nw_t_stat": 3.2},
            {"tercile": "middle", "horizon": "12m", "mean_ic": 0.26, "nw_t_stat": 5.7},
            {"tercile": "bottom", "horizon": "3m", "mean_ic": 0.11, "nw_t_stat": 2.5},
            {"tercile": "bottom", "horizon": "6m", "mean_ic": 0.08, "nw_t_stat": 1.3},
            {"tercile": "bottom", "horizon": "12m", "mean_ic": 0.14, "nw_t_stat": 3.1},
        ]
    )
    decomposition = pd.DataFrame(
        [
            {"subset": "non_bottom_sfc", "horizon": "3m", "mean_ic": 0.12, "nw_t_stat": 1.8},
            {"subset": "non_bottom_sfc", "horizon": "6m", "mean_ic": 0.16, "nw_t_stat": 1.9},
            {"subset": "non_bottom_sfc", "horizon": "12m", "mean_ic": 0.14, "nw_t_stat": 1.7},
        ]
    )
    event_window = pd.DataFrame(
        [
            {"subset": "top_event_dates", "horizon": "3m", "mean_ic": 0.12, "nw_t_stat": 2.21},
            {"subset": "top_event_dates", "horizon": "6m", "mean_ic": 0.13, "nw_t_stat": 1.96},
            {"subset": "top_event_dates", "horizon": "12m", "mean_ic": 0.06, "nw_t_stat": 0.81},
        ]
    )

    assert _conditioning_verdict(conditioned, decomposition, event_window) == NEUTRAL_VERDICT
