from __future__ import annotations

import datetime as dt

import pandas as pd

import scripts.purge_bad_market_date as purge_mod


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.update_calls = 0
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, statement, params=None):
        sql = str(statement).lower()
        if "select symbol, timeframe, object_key" in sql:
            return _FakeMappingsResult(self.rows)
        if "update market_data_store" in sql:
            self.update_calls += 1
            return _FakeMappingsResult([])
        raise AssertionError(f"Unexpected SQL: {statement}")

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class _FakeS3:
    def __init__(self):
        self.copy_calls: list[dict] = []

    def copy_object(self, **kwargs):
        self.copy_calls.append(kwargs)


def _sample_frame() -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        [
            dt.datetime(2026, 4, 9, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 4, 10, tzinfo=dt.timezone.utc),
        ]
    )
    return pd.DataFrame(
        {
            "Open": [1.0, 2.0],
            "High": [1.1, 2.1],
            "Low": [0.9, 1.9],
            "Close": [1.0, 2.0],
            "Volume": [100.0, 200.0],
        },
        index=idx,
    )


def test_purge_bad_market_date_dry_run(monkeypatch) -> None:
    db = _FakeDB(
        rows=[
            {
                "symbol": "ATW",
                "timeframe": "1D",
                "object_key": "market_data/ATW/1D.parquet",
                "source_provider": "bourse_direct",
                "data_as_of": dt.date(2026, 4, 10),
            }
        ]
    )
    fake_s3 = _FakeS3()
    writes: list[dict] = []

    monkeypatch.setattr(purge_mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(purge_mod, "s3_client", lambda: fake_s3)
    monkeypatch.setattr(purge_mod, "load_ohlcv_from_store", lambda **_kwargs: _sample_frame())
    monkeypatch.setattr(purge_mod, "put_bytes", lambda **kwargs: writes.append(kwargs))

    report = purge_mod.purge_bad_market_date(
        target_date=dt.date(2026, 4, 10),
        apply_changes=False,
    )

    assert report["summary"]["targets"] == 1
    assert report["summary"]["affected"] == 1
    assert report["summary"]["removed_rows"] == 1
    assert report["summary"]["backups_created"] == 0
    assert report["summary"]["writes"] == 0
    assert db.update_calls == 0
    assert len(fake_s3.copy_calls) == 0
    assert writes == []
    assert db.closed is True


def test_purge_bad_market_date_apply_creates_backup_and_updates(monkeypatch) -> None:
    db = _FakeDB(
        rows=[
            {
                "symbol": "ATW",
                "timeframe": "1D",
                "object_key": "market_data/ATW/1D.parquet",
                "source_provider": "bourse_direct",
                "data_as_of": dt.date(2026, 4, 10),
            }
        ]
    )
    fake_s3 = _FakeS3()
    writes: list[dict] = []

    monkeypatch.setattr(purge_mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(purge_mod, "s3_client", lambda: fake_s3)
    monkeypatch.setattr(purge_mod, "load_ohlcv_from_store", lambda **_kwargs: _sample_frame())
    monkeypatch.setattr(purge_mod, "put_bytes", lambda **kwargs: writes.append(kwargs))

    report = purge_mod.purge_bad_market_date(
        target_date=dt.date(2026, 4, 10),
        apply_changes=True,
    )

    assert report["summary"]["targets"] == 1
    assert report["summary"]["affected"] == 1
    assert report["summary"]["removed_rows"] == 1
    assert report["summary"]["backups_created"] == 1
    assert report["summary"]["writes"] == 1
    assert db.update_calls == 1
    assert db.committed is True
    assert len(fake_s3.copy_calls) == 1
    assert len(writes) == 1
    assert db.closed is True
