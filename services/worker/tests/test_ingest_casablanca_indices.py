from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
import services.worker.tasks.ingest_casablanca_indices as ingest_mod


def _frame(dates, closes) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "Close": closes,
            "High": [c + 10 for c in closes],
            "Low": [c - 10 for c in closes],
            "display_name": "MASI",
        },
        index=pd.to_datetime(dates),
    )
    df.index.name = "Date"
    return df


class _FakeAdapter:
    def __init__(self, frames):
        self.frames = frames
        self.requested = []

    def fetch(self, codes, start=None, end=None):
        self.requested.extend(codes)
        return {c: self.frames[c] for c in codes if c in self.frames}


def test_fetch_index_history_returns_empty_for_unmapped_or_missing_symbol() -> None:
    adapter = _FakeAdapter({})
    assert ingest_mod.fetch_index_history("FTSE_CSE_MOROCCO_15", adapter).empty
    assert ingest_mod.fetch_index_history("MASI", adapter).empty


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
    monkeypatch.setattr(ingest_mod, "_save_parquet", lambda object_key, df: None)
    monkeypatch.setattr(ingest_mod, "_try_load_existing_parquet", lambda object_key: None)

    masi_df = _frame(["2026-07-07", "2026-07-08"], [16000.0, 16050.0])
    monkeypatch.setattr(ingest_mod, "BoursenovaIndicesAdapter", lambda: _FakeAdapter({"MASI": masi_df}))

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
    monkeypatch.setattr(ingest_mod, "_save_parquet", lambda object_key, df: None)
    monkeypatch.setattr(ingest_mod, "_try_load_existing_parquet", lambda object_key: None)

    good_df = _frame(["2026-07-08"], [100.0])

    class _Adapter(_FakeAdapter):
        def fetch(self, codes, start=None, end=None):
            if "MASI_20" in codes:
                raise RuntimeError("boom")
            return {c: good_df for c in codes}

    monkeypatch.setattr(ingest_mod, "BoursenovaIndicesAdapter", lambda: _Adapter({}))

    try:
        result = ingest_mod.run_casablanca_index_ingest(["MASI", "MASI_20"])
    finally:
        engine.dispose()

    assert result["status"] == "partial"
    assert result["indices"]["MASI"]["status"] in {"created", "updated"}
    assert result["indices"]["MASI_20"]["status"] == "error"
    assert "boom" in result["indices"]["MASI_20"]["error"]


def test_run_casablanca_index_ingest_skips_symbols_without_boursenova_code(monkeypatch) -> None:
    TestSessionLocal, engine = _make_sqlite_session_local()
    monkeypatch.setattr(ingest_mod, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(ingest_mod, "_save_parquet", lambda object_key, df: None)
    monkeypatch.setattr(ingest_mod, "_try_load_existing_parquet", lambda object_key: None)
    masi_df = _frame(["2026-07-08"], [100.0])
    monkeypatch.setattr(ingest_mod, "BoursenovaIndicesAdapter", lambda: _FakeAdapter({"MASI": masi_df}))
    try:
        result = ingest_mod.run_casablanca_index_ingest(["MASI", "FTSE_CSE_MOROCCO_15"])
    finally:
        engine.dispose()
    assert result["status"] == "succeeded"
    assert result["indices"]["FTSE_CSE_MOROCCO_15"] == {"status": "skipped", "reason": "no_boursenova_code"}
