from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_core.pipeline import build_walk_forward_period_entries  # noqa: E402


def test_walk_forward_periods_rolling_windows() -> None:
    rows = build_walk_forward_period_entries(
        start="2020-01-01",
        end="2020-12-31",
        train_value=6,
        train_unit="months",
        test_value=3,
        test_unit="months",
        step_value=3,
        step_unit="months",
        anchored=False,
    )

    assert len(rows) == 2
    assert rows[0]["train_start"] == "2020-01-01"
    assert rows[0]["train_end"] == "2020-06-30"
    assert rows[0]["test_start"] == "2020-07-01"
    assert rows[0]["test_end"] == "2020-09-30"
    assert rows[1]["train_start"] == "2020-04-01"
    assert rows[1]["test_start"] == "2020-10-01"


def test_walk_forward_periods_anchored_windows() -> None:
    rows = build_walk_forward_period_entries(
        start="2020-01-01",
        end="2020-12-31",
        train_value=6,
        train_unit="months",
        test_value=3,
        test_unit="months",
        step_value=3,
        step_unit="months",
        anchored=True,
    )

    assert len(rows) == 2
    assert rows[0]["train_start"] == "2020-01-01"
    assert rows[1]["train_start"] == "2020-01-01"
    assert rows[1]["train_end"] == "2020-09-30"


def test_walk_forward_periods_reject_invalid_window() -> None:
    with pytest.raises(ValueError):
        build_walk_forward_period_entries(
            start="2020-01-01",
            end="2020-02-01",
            train_value=6,
            train_unit="months",
            test_value=1,
            test_unit="months",
            step_value=1,
            step_unit="months",
            anchored=False,
        )
