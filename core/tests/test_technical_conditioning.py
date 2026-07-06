from __future__ import annotations

import datetime as dt

import pandas as pd

from quant_core.fundamentals.cross_section.technical_conditioning import _assign_sfc_terciles


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
