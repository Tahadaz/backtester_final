from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_core.wfo.date_resolution import resolve_wfo_start_end_dates  # noqa: E402


def _bars(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({"Close": range(len(index))}, index=index)


def test_latest_end_date_policy_uses_last_bar() -> None:
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-05"])
    out = resolve_wfo_start_end_dates(
        _bars(idx),
        horizon="short",
        start_date=None,
        end_date=None,
        end_date_policy="latest",
    )
    assert out["resolved_end_date"].isoformat() == "2024-01-05"


def test_fixed_end_date_aligns_to_previous_bar() -> None:
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-05"])
    out = resolve_wfo_start_end_dates(
        _bars(idx),
        horizon="short",
        start_date=None,
        end_date=pd.Timestamp("2024-01-04").date(),
        end_date_policy="fixed",
    )
    assert out["resolved_end_date"].isoformat() == "2024-01-03"
    assert out["alignment_notes"]["end_aligned"] is True
    assert out["alignment_notes"]["end_alignment"] == "prev"


def test_provided_start_date_aligns_to_next_bar() -> None:
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-05"])
    out = resolve_wfo_start_end_dates(
        _bars(idx),
        horizon="short",
        start_date=pd.Timestamp("2024-01-04").date(),
        end_date=pd.Timestamp("2024-01-05").date(),
        end_date_policy="fixed",
    )
    assert out["resolved_start_date"].isoformat() == "2024-01-05"
    assert out["alignment_notes"]["start_aligned"] is True
    assert out["alignment_notes"]["start_alignment"] == "next"


def test_fixed_policy_requires_end_date() -> None:
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-05"])
    with pytest.raises(ValueError, match="end_date is required when end_date_policy='fixed'"):
        resolve_wfo_start_end_dates(
            _bars(idx),
            horizon="short",
            start_date=None,
            end_date=None,
            end_date_policy="fixed",
        )


def test_horizon_start_uses_bar_count_lookback_not_calendar_days() -> None:
    idx = pd.date_range("2015-01-01", periods=3000, freq="B")
    bars = _bars(idx)
    out = resolve_wfo_start_end_dates(
        bars,
        horizon="short",  # 5 * 252 = 1260 bars
        start_date=None,
        end_date=None,
        end_date_policy="latest",
    )

    end_idx = len(idx) - 1
    expected_start_idx = end_idx - (5 * 252)
    assert out["resolved_start_date"] == idx[expected_start_idx].date()
    assert out["resolved_end_date"] == idx[end_idx].date()


def test_start_after_end_raises_error() -> None:
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-05"])
    with pytest.raises(ValueError, match="after resolved end_date"):
        resolve_wfo_start_end_dates(
            _bars(idx),
            horizon="short",
            start_date=pd.Timestamp("2024-01-04").date(),  # aligns to 2024-01-05
            end_date=pd.Timestamp("2024-01-03").date(),
            end_date_policy="fixed",
        )
