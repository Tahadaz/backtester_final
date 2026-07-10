from __future__ import annotations

import datetime as dt

from services.api.app.models import WfoSignalSummary
from services.api.app.services import weekly_recompute_policy as policy


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter_by(self, **kwargs):
        rows = [
            row
            for row in self._rows
            if all(getattr(row, key, None) == value for key, value in kwargs.items())
        ]
        return _FakeQuery(rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self, rows_by_model=None):
        self.rows_by_model = {**(rows_by_model or {})}

    def query(self, model):
        return _FakeQuery(self.rows_by_model.get(model, []))


def test_get_sr_wfo_last_full_compute_at_missing_row_returns_none():
    db = _FakeDB({WfoSignalSummary: []})

    result = policy.get_sr_wfo_last_full_compute_at(db, symbol="AAA", horizon="weekly", variant="expanded")

    assert result is None


def test_get_sr_wfo_last_full_compute_at_reads_support_resistance_category_row():
    computed_at = dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)
    row = WfoSignalSummary(
        symbol="AAA",
        horizon="weekly",
        variant="expanded",
        category="support_resistance",
        computed_at=computed_at,
    )
    other_category_row = WfoSignalSummary(
        symbol="AAA",
        horizon="weekly",
        variant="expanded",
        category="tendance",
        computed_at=dt.datetime(2026, 7, 5, tzinfo=dt.timezone.utc),
    )
    db = _FakeDB({WfoSignalSummary: [other_category_row, row]})

    result = policy.get_sr_wfo_last_full_compute_at(db, symbol="AAA", horizon="weekly", variant="expanded")

    assert result == computed_at


def test_iter_sr_wfo_weekly_stale_tuples_flags_missing_and_old_rows_only():
    now = dt.datetime(2026, 7, 10, tzinfo=dt.timezone.utc)
    fresh_row = WfoSignalSummary(
        symbol="AAA",
        horizon="weekly",
        variant="expanded_ta_simple",
        category="support_resistance",
        computed_at=now - dt.timedelta(days=1),
    )
    stale_row = WfoSignalSummary(
        symbol="AAA",
        horizon="monthly",
        variant="expanded_ta_simple",
        category="support_resistance",
        computed_at=now - dt.timedelta(days=10),
    )
    # AAA/quarterly/expanded_ta_simple has no row at all -> missing -> stale.
    db = _FakeDB({WfoSignalSummary: [fresh_row, stale_row]})

    result = policy.iter_sr_wfo_weekly_stale_tuples(
        db,
        symbols=["AAA"],
        horizons=("weekly", "monthly", "quarterly"),
        variants=("expanded",),
        now=now,
    )

    assert ("AAA", "weekly", "expanded_ta_simple") not in result
    assert ("AAA", "monthly", "expanded_ta_simple") in result
    assert ("AAA", "quarterly", "expanded_ta_simple") in result
