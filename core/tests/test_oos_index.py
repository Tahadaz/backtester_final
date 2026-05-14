"""Unit tests for core.quant_core.research.oos_index.

Synthetic inputs only - no DB access. Covers OOS index resolution edge cases:
bar-index-only folds, optional date bounds, and empty winner_variant_id.
"""
from __future__ import annotations

import pandas as pd
import pytest

from core.quant_core.research.oos_index import (
    OosSample,
    OosWindow,
    oos_sample_for,
    oos_sample_for_signal_engine,
    oos_windows_from_wfo,
)


def _bidx(start: str, n: int) -> pd.DatetimeIndex:
    return pd.date_range(start=start, periods=n, freq="B")


# ---------------------------------------------------------------------------
# WFO folds parsing
# ---------------------------------------------------------------------------

def test_wfo_folds_simple():
    """Two non-overlapping windows resolved via OHLCV index."""
    idx = _bidx("2024-01-01", 300)
    folds = [
        {"index": 0, "oos_start": 200, "oos_end": 232,
         "winner_variant_id": "sv_a", "winner_description": "SMA-20"},
        {"index": 1, "oos_start": 232, "oos_end": 264,
         "winner_variant_id": "sv_b", "winner_description": "RSI-14"},
    ]
    windows = oos_windows_from_wfo(folds, ohlcv_index=idx)
    assert len(windows) == 2
    assert windows[0] == OosWindow(
        fold_id=0,
        start=pd.Timestamp(idx[200]),
        end=pd.Timestamp(idx[231]),
        winner_variant_id="sv_a",
    )
    assert windows[1].fold_id == 1
    assert windows[1].start == pd.Timestamp(idx[232])
    assert windows[1].end == pd.Timestamp(idx[263])
    assert windows[1].winner_variant_id == "sv_b"


def test_wfo_folds_overlapping():
    """Overlapping windows: each fold preserved separately, date union dedups."""
    idx = _bidx("2024-01-01", 300)
    folds = [
        {"index": 0, "oos_start": 200, "oos_end": 240, "winner_variant_id": "sv_a"},
        {"index": 1, "oos_start": 220, "oos_end": 260, "winner_variant_id": "sv_b"},
    ]

    def wfo_loader(_symbol, _horizon):
        return {"folds_json": folds}

    sample = oos_sample_for(
        symbol="AAA",
        horizon="weekly",
        source="wfo",
        wfo_loader=wfo_loader,
        ohlcv_index_loader=lambda _s: idx,
    )
    assert len(sample.windows) == 2  # both windows kept separately
    assert sample.windows[0].fold_id == 0
    assert sample.windows[1].fold_id == 1

    # Date union covers idx[200..259] inclusive without duplicates
    expected = idx[200:260]
    assert len(sample.dates) == len(expected)
    assert (sample.dates == expected).all()
    assert sample.score_mode == "fold_scoped_winner"


def test_wfo_folds_missing_field():
    """Defensive parser: missing/invalid fields don't raise."""
    idx = _bidx("2024-01-01", 300)
    folds = [
        # Valid bar-index fold
        {"index": 0, "oos_start": 200, "oos_end": 232, "winner_variant_id": "sv_a"},
        # Empty-string winner_variant_id → None (per finding §3)
        {"index": 1, "oos_start": 232, "oos_end": 264, "winner_variant_id": ""},
        # Missing required oos_end → dropped
        {"index": 2, "oos_start": 264, "winner_variant_id": "sv_c"},
        # Inverted bounds → dropped
        {"index": 3, "oos_start": 280, "oos_end": 270, "winner_variant_id": "sv_d"},
        # Non-mapping garbage → dropped
        "not a dict",
        # Out-of-range bar indices → dropped
        {"index": 5, "oos_start": 290, "oos_end": 999, "winner_variant_id": "sv_e"},
    ]
    windows = oos_windows_from_wfo(folds, ohlcv_index=idx)
    assert len(windows) == 2
    assert windows[0].winner_variant_id == "sv_a"
    assert windows[1].winner_variant_id is None  # empty string → None


def test_wfo_folds_no_index_no_dates_returns_empty():
    """Bar-index-only folds with no OHLCV index → cannot resolve, returns []."""
    folds = [{"index": 0, "oos_start": 200, "oos_end": 232}]
    assert oos_windows_from_wfo(folds, ohlcv_index=None) == []


def test_wfo_folds_prefers_json_dates_when_present():
    """If `oos_*_date` keys are present, use them. (Forward-compat per finding.)"""
    idx = _bidx("2024-01-01", 300)
    folds = [{
        "index": 0,
        "oos_start": 0, "oos_end": 999,  # would explode without the date keys
        "oos_start_date": "2024-06-03",
        "oos_end_date": "2024-07-15",   # exclusive in writer convention
        "winner_variant_id": "sv_a",
    }]
    windows = oos_windows_from_wfo(folds, ohlcv_index=idx)
    assert len(windows) == 1
    assert windows[0].start == pd.Timestamp("2024-06-03")
    # exclusive → inclusive: previous business day in the index
    pos = idx.searchsorted(pd.Timestamp("2024-07-15"), side="left")
    assert windows[0].end == pd.Timestamp(idx[pos - 1])


def test_wfo_folds_prefers_absolute_indices_over_stale_dates():
    idx = _bidx("2024-01-01", 300)
    folds = [{
        "index": 0,
        "oos_start": 0,
        "oos_end": 20,
        "oos_start_abs_idx": 200,
        "oos_end_abs_idx": 232,
        "oos_start_date": "2005-11-29",
        "oos_end_date": "2006-02-02",
        "winner_variant_id": "sv_a",
    }]

    windows = oos_windows_from_wfo(folds, ohlcv_index=idx)

    assert len(windows) == 1
    assert windows[0].start == pd.Timestamp(idx[200])
    assert windows[0].end == pd.Timestamp(idx[231])


def test_wfo_folds_normalize_aware_json_dates_to_naive_index():
    """Production folds may carry UTC timestamps while OHLCV indexes are naive."""
    idx = _bidx("2024-01-01", 300)
    folds = [{
        "index": 0,
        "oos_start": 0, "oos_end": 999,
        "oos_start_date": "2024-06-03T00:00:00+00:00",
        "oos_end_date": "2024-07-15T00:00:00+00:00",
        "winner_variant_id": "sv_a",
    }]

    windows = oos_windows_from_wfo(folds, ohlcv_index=idx)

    assert len(windows) == 1
    assert windows[0].start == pd.Timestamp("2024-06-03")
    assert windows[0].start.tzinfo is None
    assert windows[0].end.tzinfo is None


# ---------------------------------------------------------------------------
# Signal-engine terminal holdout
# ---------------------------------------------------------------------------

def test_signal_engine_filters_is_rows():
    """is_oos=True wins when present; the IS row is excluded."""
    rows = [
        {"date": pd.Timestamp("2024-06-03"), "is_oos": True},
        {"date": pd.Timestamp("2024-06-04"), "is_oos": True},
        {"date": pd.Timestamp("2024-06-05"), "is_oos": False},
    ]
    sample = oos_sample_for_signal_engine(rows, horizon="weekly", holdout_bars=10)
    assert sample.score_mode == "terminal_holdout"
    assert len(sample.dates) == 2
    assert pd.Timestamp("2024-06-05") not in sample.dates
    assert sample.windows[0].start == pd.Timestamp("2024-06-03")
    assert sample.windows[0].end == pd.Timestamp("2024-06-04")
    assert sample.windows[0].fold_id is None
    assert sample.windows[0].winner_variant_id is None


def test_signal_engine_terminal_fallback_when_no_marker():
    """No is_oos=True anywhere → fall back to last `holdout_bars` distinct dates."""
    rows = [{"date": d, "is_oos": False} for d in _bidx("2024-01-01", 100)]
    sample = oos_sample_for_signal_engine(rows, horizon="weekly", holdout_bars=20)
    assert len(sample.dates) == 20
    assert sample.dates[0] == pd.Timestamp(_bidx("2024-01-01", 100)[-20])
    assert sample.dates[-1] == pd.Timestamp(_bidx("2024-01-01", 100)[-1])


def test_signal_engine_empty_input():
    sample = oos_sample_for_signal_engine([], horizon="monthly", holdout_bars=20)
    assert len(sample.dates) == 0
    assert sample.windows == ()
    assert sample.score_mode == "terminal_holdout"


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------

def test_oos_sample_for_wfo_via_loader():
    idx = _bidx("2024-01-01", 300)
    folds = [{"index": 0, "oos_start": 200, "oos_end": 232, "winner_variant_id": "sv_a"}]

    sample = oos_sample_for(
        symbol="AAA",
        horizon="weekly",
        source="wfo",
        wfo_loader=lambda _s, _h: {"folds_json": folds},
        ohlcv_index_loader=lambda _s: idx,
    )
    assert isinstance(sample, OosSample)
    assert sample.source == "wfo"
    assert sample.horizon == "weekly"
    assert sample.score_mode == "fold_scoped_winner"
    assert len(sample.windows) == 1


def test_oos_sample_for_signal_engine_via_loader():
    rows = [
        {"date": pd.Timestamp("2024-06-03"), "is_oos": True},
        {"date": pd.Timestamp("2024-06-04"), "is_oos": True},
    ]
    sample = oos_sample_for(
        symbol="AAA",
        horizon="weekly",
        source="signal_engine",
        score_history_loader=lambda _s, _h: rows,
        holdout_bars=30,
    )
    assert sample.source == "signal_engine"
    assert sample.score_mode == "terminal_holdout"
    assert len(sample.dates) == 2


def test_oos_date_index_union_when_sources_combined():
    """Integration shape: independent samples for the same symbol, two sources,
    combined date sets. Mirrors how the Edge consumer concatenates samples."""
    idx = _bidx("2024-01-01", 300)
    wfo_folds = [{"index": 0, "oos_start": 200, "oos_end": 220, "winner_variant_id": "sv_a"}]
    se_rows = [
        {"date": pd.Timestamp(idx[210]), "is_oos": True},
        {"date": pd.Timestamp(idx[280]), "is_oos": True},
    ]
    wfo = oos_sample_for(
        symbol="AAA", horizon="weekly", source="wfo",
        wfo_loader=lambda _s, _h: {"folds_json": wfo_folds},
        ohlcv_index_loader=lambda _s: idx,
    )
    se = oos_sample_for(
        symbol="AAA", horizon="weekly", source="signal_engine",
        score_history_loader=lambda _s, _h: se_rows,
        holdout_bars=10,
    )
    combined = pd.DatetimeIndex(sorted(set(wfo.dates).union(set(se.dates))))
    # WFO covers idx[200..219] (20 days), plus idx[210] (already in WFO) and
    # idx[280] (new). Union: 20 + 1 = 21 unique dates.
    assert len(combined) == 21
    assert pd.Timestamp(idx[280]) in combined
    assert pd.Timestamp(idx[219]) in combined


def test_oos_sample_for_unknown_source_raises():
    with pytest.raises(ValueError):
        oos_sample_for(symbol="AAA", horizon="weekly", source="nope")  # type: ignore[arg-type]


def test_oos_sample_for_wfo_requires_loader():
    with pytest.raises(ValueError):
        oos_sample_for(symbol="AAA", horizon="weekly", source="wfo")


def test_oos_sample_for_signal_engine_requires_loader():
    with pytest.raises(ValueError):
        oos_sample_for(symbol="AAA", horizon="weekly", source="signal_engine")
