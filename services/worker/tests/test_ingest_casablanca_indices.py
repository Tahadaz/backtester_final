from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
import services.worker.tasks.ingest_casablanca_indices as ingest_mod


def _item(date: str, close: str, high: str, low: str) -> dict:
    return {
        "attributes": {
            "field_seance_date": date,
            "field_index_value": close,
            "field_index_high_value": high,
            "field_index_low_value": low,
        }
    }


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    """Serves canned JSON:API pages keyed by page[offset]; last page is empty."""

    def __init__(self, pages: dict[int, dict]):
        self.pages = pages
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params))
        offset = int((params or {}).get("page[offset]", 0))
        payload = self.pages.get(offset, {"data": []})
        return _FakeResponse(payload)


# ---------------------------------------------------------------------------
# fetch_index_history
# ---------------------------------------------------------------------------

def test_fetch_index_history_parses_sorts_and_dedupes() -> None:
    page0 = {
        "data": [
            _item("2026-07-08", "16000.50", "16100.00", "15900.00"),
            _item("2026-07-08", "16000.50", "16100.00", "15900.00"),  # duplicate date
            _item("2026-07-07", "15950.25", "16000.00", "15900.00"),
        ]
    }
    session = _FakeSession({0: page0})

    df = ingest_mod.fetch_index_history(session, "512335", page_limit=250)

    assert list(df.index.strftime("%Y-%m-%d")) == ["2026-07-07", "2026-07-08"]
    assert df.loc["2026-07-08", "close"] == 16000.50
    assert df.loc["2026-07-08", "high"] == 16100.00
    assert df.loc["2026-07-07", "low"] == 15900.00


def test_fetch_index_history_stops_pagination_on_empty_page() -> None:
    full_page = {"data": [_item(f"2026-01-{d:02d}", "100.0", "101.0", "99.0") for d in range(1, 3)]}
    session = _FakeSession({0: full_page, 2: {"data": []}})

    df = ingest_mod.fetch_index_history(session, "512335", page_limit=2)

    assert len(df) == 2
    # offset 2 must have been requested (to discover it's empty) and offset 4 never requested
    offsets_called = [int(p["page[offset]"]) for _, p in session.calls]
    assert offsets_called == [0, 2]


def test_fetch_index_history_returns_empty_frame_when_no_data() -> None:
    session = _FakeSession({0: {"data": []}})
    df = ingest_mod.fetch_index_history(session, "512335")
    assert df.empty


# ---------------------------------------------------------------------------
# run_casablanca_index_ingest
# ---------------------------------------------------------------------------

def _make_sqlite_session_local():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _conn_record):
        dbapi_conn.create_function("now", 0, lambda: dt.datetime.utcnow().isoformat())

    for table in (models.MarketDataStore.__table__, models.IndexMaster.__table__):
        table.create(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False), engine


def test_run_casablanca_index_ingest_writes_market_data_store_and_index_master(monkeypatch) -> None:
    TestSessionLocal, engine = _make_sqlite_session_local()
    monkeypatch.setattr(ingest_mod, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(ingest_mod, "_new_session", lambda: object())
    monkeypatch.setattr(ingest_mod, "_save_parquet", lambda object_key, df: None)
    monkeypatch.setattr(ingest_mod, "_try_load_existing_parquet", lambda object_key: None)
    monkeypatch.setattr(ingest_mod.time, "sleep", lambda *_a, **_k: None)

    masi_df = pd.DataFrame(
        {
            "close": [16000.0, 16050.0],
            "high": [16100.0, 16150.0],
            "low": [15900.0, 15950.0],
        },
        index=pd.to_datetime(["2026-07-07", "2026-07-08"]),
    )
    masi_df.index.name = "Date"

    monkeypatch.setattr(
        ingest_mod, "fetch_index_history",
        lambda session, tid, **kw: masi_df if tid == "512335" else pd.DataFrame(columns=["close", "high", "low"]),
    )

    result = ingest_mod.run_casablanca_index_ingest(["MASI"])

    assert result["status"] == "succeeded"
    assert result["indices"]["MASI"]["row_count"] == 2

    db = TestSessionLocal()
    try:
        row = db.query(models.MarketDataStore).filter_by(symbol="MASI", timeframe="1D").first()
        assert row is not None
        assert row.asset_class == "index"
        assert row.source_provider == "casablanca_bourse_api"
        assert row.row_count == 2

        idx_row = db.query(models.IndexMaster).filter_by(symbol="MASI").first()
        assert idx_row is not None
        assert idx_row.display_name == "MASI"
    finally:
        db.close()
        engine.dispose()


def test_run_casablanca_index_ingest_partial_status_on_per_index_failure(monkeypatch) -> None:
    TestSessionLocal, engine = _make_sqlite_session_local()
    monkeypatch.setattr(ingest_mod, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(ingest_mod, "_new_session", lambda: object())
    monkeypatch.setattr(ingest_mod, "_save_parquet", lambda object_key, df: None)
    monkeypatch.setattr(ingest_mod, "_try_load_existing_parquet", lambda object_key: None)
    monkeypatch.setattr(ingest_mod.time, "sleep", lambda *_a, **_k: None)

    good_df = pd.DataFrame(
        {"close": [100.0], "high": [101.0], "low": [99.0]},
        index=pd.to_datetime(["2026-07-08"]),
    )
    good_df.index.name = "Date"

    def _fake_fetch(session, tid, **kw):
        if tid == "512343":
            raise RuntimeError("boom")
        return good_df

    monkeypatch.setattr(ingest_mod, "fetch_index_history", _fake_fetch)

    try:
        result = ingest_mod.run_casablanca_index_ingest(["MASI", "MASI_20"])
    finally:
        engine.dispose()

    assert result["status"] == "partial"
    assert result["indices"]["MASI"]["status"] in {"created", "updated"}
    assert result["indices"]["MASI_20"]["status"] == "error"
    assert "boom" in result["indices"]["MASI_20"]["error"]
