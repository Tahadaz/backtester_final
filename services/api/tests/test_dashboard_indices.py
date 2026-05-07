from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")

from services.api.app import models
from services.api.app.db import get_db
from services.api.app.routers import dashboard_indices as dashboard_indices_router


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover - sqlite harness
    return "JSON"


@pytest.fixture()
def client_and_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    models.DashboardCustomIndex.__table__.create(engine)

    app = FastAPI()
    app.include_router(dashboard_indices_router.router)

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


def test_dashboard_indices_crud_flow(client_and_session) -> None:
    client, _SessionLocal = client_and_session

    listed_initial = client.get("/dashboard/indices")
    assert listed_initial.status_code == 200
    assert listed_initial.json() == []

    created = client.post(
        "/dashboard/indices",
        json={
            "name": "Banques Leaders",
            "symbols": [" bcp ", "ATW", "bcp"],
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["name"] == "Banques Leaders"
    assert payload["symbols"] == ["BCP", "ATW"]
    created_id = payload["id"]

    duplicate = client.post(
        "/dashboard/indices",
        json={
            "name": "banques leaders",
            "symbols": ["IAM"],
        },
    )
    assert duplicate.status_code == 409

    updated = client.put(
        f"/dashboard/indices/{created_id}",
        json={
            "name": "Top Banques",
            "symbols": ["att", " atw ", "IAM", "IAM"],
        },
    )
    assert updated.status_code == 200
    updated_payload = updated.json()
    assert updated_payload["name"] == "Top Banques"
    assert updated_payload["symbols"] == ["ATT", "ATW", "IAM"]

    listed_after_update = client.get("/dashboard/indices")
    assert listed_after_update.status_code == 200
    rows = listed_after_update.json()
    assert len(rows) == 1
    assert rows[0]["id"] == created_id

    deleted = client.delete(f"/dashboard/indices/{created_id}")
    assert deleted.status_code == 204

    listed_final = client.get("/dashboard/indices")
    assert listed_final.status_code == 200
    assert listed_final.json() == []


def test_dashboard_indices_reject_empty_symbols(client_and_session) -> None:
    client, _SessionLocal = client_and_session

    created = client.post(
        "/dashboard/indices",
        json={
            "name": "Indice Vide",
            "symbols": [" ", ""],
        },
    )
    assert created.status_code == 422

