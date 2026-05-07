from __future__ import annotations

import os

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")

from services.api.app import models
from services.api.app.db import get_db
from services.api.app.main import create_app
from services.api.app.routers import market_data as market_data_router


@pytest.fixture()
def client_and_session(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    models.MarketDataStore.__table__.create(engine)

    app = create_app()

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client, SessionLocal, monkeypatch

    app.dependency_overrides.clear()
    engine.dispose()


def test_availability_calendar_classifies_zero_and_missing_volume_as_no_trading(client_and_session) -> None:
    client, SessionLocal, monkeypatch = client_and_session
    frame = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [1200.0, 0.0, "-"],
        },
        index=pd.to_datetime(["2026-04-01", "2026-04-02", "2026-04-03"], utc=True),
    )
    monkeypatch.setattr(market_data_router, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: frame)

    with SessionLocal() as db:
        db.add(
            models.MarketDataStore(
                symbol="AFI",
                timeframe="1D",
                object_key="market_data/AFI/1D.parquet",
                row_count=len(frame),
            )
        )
        db.commit()

    response = client.get("/market-data/stocks/AFI/availability-calendar")

    assert response.status_code == 200
    payload = response.json()
    states_by_date = {day["date"]: day["state"] for day in payload["days"]}
    assert states_by_date["2026-04-01"] == "present_data"
    assert states_by_date["2026-04-02"] == "no_trading_day"
    assert states_by_date["2026-04-03"] == "no_trading_day"
    assert payload["present_days"] == 1
    assert payload["no_trading_days"] == 2
    assert payload["partial_days"] == 0
    assert payload["missing_expected_days"] == 0


def test_availability_calendar_keeps_missing_session_separate_from_no_trading(client_and_session) -> None:
    client, SessionLocal, monkeypatch = client_and_session
    frame = pd.DataFrame(
        {
            "Open": [100.0, 102.0],
            "High": [101.0, 103.0],
            "Low": [99.0, 101.0],
            "Close": [100.5, 102.5],
            "Volume": [1200.0, 1500.0],
        },
        index=pd.to_datetime(["2026-04-01", "2026-04-03"], utc=True),
    )
    monkeypatch.setattr(market_data_router, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: frame)

    with SessionLocal() as db:
        db.add(
            models.MarketDataStore(
                symbol="AFI",
                timeframe="1D",
                object_key="market_data/AFI/1D.parquet",
                row_count=len(frame),
            )
        )
        db.commit()

    response = client.get("/market-data/stocks/AFI/availability-calendar")

    assert response.status_code == 200
    payload = response.json()
    states_by_date = {day["date"]: day["state"] for day in payload["days"]}
    assert states_by_date["2026-04-02"] == "missing_expected_day"
    assert payload["missing_expected_days"] == 1
    assert payload["no_trading_days"] == 0
