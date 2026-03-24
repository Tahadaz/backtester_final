from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")

from services.api.app import models
from services.api.app.db import get_db
from services.api.app.main import create_app


@pytest.fixture()
def client_and_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    for table in (models.StockMaster.__table__, models.ProviderSymbolMap.__table__, models.MarketDataStore.__table__):
        table.create(engine)

    app = create_app()

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client, SessionLocal

    app.dependency_overrides.clear()
    engine.dispose()


def test_add_tracked_masi_stock_uses_canonical_display_name(client_and_session) -> None:
    client, SessionLocal = client_and_session

    response = client.post(
        "/market-data/stocks",
        json={
            "symbol": "ATW",
            "display_name": "User Override",
            "sector": "Wrong Sector",
            "track_source": "bourse_direct",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["symbol"] == "ATW"
    assert payload["display_name"] == "Attijariwafa Bank"
    assert payload["sector"] == "Wrong Sector"

    with SessionLocal() as db:
        stock = db.query(models.StockMaster).filter(models.StockMaster.symbol == "ATW").one()
        assert stock.display_name == "Attijariwafa Bank"


def test_patch_stock_ignores_display_name_mutation_but_updates_allowed_fields(client_and_session) -> None:
    client, SessionLocal = client_and_session

    with SessionLocal() as db:
        db.add(
            models.StockMaster(
                symbol="ATW",
                display_name="Attijariwafa Bank",
                sector="Banques",
                track_source="bourse_direct",
                is_active=True,
            )
        )
        db.commit()

    response = client.patch(
        "/market-data/stocks/ATW",
        json={
            "display_name": "Changed from UI",
            "notes": "canonical-name-lock",
            "sector": "Banques Premium",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "Attijariwafa Bank"
    assert payload["notes"] == "canonical-name-lock"
    assert payload["sector"] == "Banques Premium"

    with SessionLocal() as db:
        stock = db.query(models.StockMaster).filter(models.StockMaster.symbol == "ATW").one()
        assert stock.display_name == "Attijariwafa Bank"
        assert stock.notes == "canonical-name-lock"
        assert stock.sector == "Banques Premium"
