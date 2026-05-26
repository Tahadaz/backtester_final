from __future__ import annotations

from quant_core.fundamentals.trends import classify_pillar_trend


def test_insufficient_data_with_two_rows() -> None:
    assert classify_pillar_trend([{"quality_score": 80}, {"quality_score": 78}], "quality") == "insufficient_data"


def test_on_track_high_and_flat() -> None:
    rows = [{"quality_score": 75}, {"quality_score": 76}, {"quality_score": 77}]
    assert classify_pillar_trend(rows, "quality") == "on_track"


def test_behind_steep_decline() -> None:
    rows = [{"quality_score": 50}, {"quality_score": 60}, {"quality_score": 70}, {"quality_score": 80}]
    assert classify_pillar_trend(rows, "quality") == "behind"


def test_behind_low_score_regardless_of_slope() -> None:
    rows = [{"quality_score": 35}, {"quality_score": 35}, {"quality_score": 35}]
    assert classify_pillar_trend(rows, "quality") == "behind"


def test_watch_middle_case() -> None:
    rows = [{"quality_score": 60}, {"quality_score": 63}, {"quality_score": 66}]
    assert classify_pillar_trend(rows, "quality") == "watch"
