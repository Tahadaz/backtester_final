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


USER_A = {"x-app-user-id": "user-a", "x-app-user-email": "a@example.com"}
USER_B = {"x-app-user-id": "user-b", "x-app-user-email": "b@example.com"}


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

    models.StockMaster.__table__.create(engine)
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

    listed_initial = client.get("/dashboard/indices", headers=USER_A)
    assert listed_initial.status_code == 200
    assert listed_initial.json() == []

    created = client.post(
        "/dashboard/indices",
        headers=USER_A,
        json={
            "name": "Banques Leaders",
            "symbols": [" bcp ", "ATW", "bcp"],
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["name"] == "Banques Leaders"
    assert payload["symbols"] == ["BCP", "ATW"]
    assert payload["component_shares"] == {}
    assert payload["components"] == []
    assert payload["is_weighted_complete"] is False
    created_id = payload["id"]

    duplicate = client.post(
        "/dashboard/indices",
        headers=USER_A,
        json={
            "name": "banques leaders",
            "symbols": ["IAM"],
        },
    )
    assert duplicate.status_code == 409

    same_name_other_user = client.post(
        "/dashboard/indices",
        headers=USER_B,
        json={
            "name": "banques leaders",
            "symbols": ["IAM"],
        },
    )
    assert same_name_other_user.status_code == 201

    updated = client.put(
        f"/dashboard/indices/{created_id}",
        headers=USER_A,
        json={
            "name": "Top Banques",
            "components": [
                {"symbol": "att", "shares": 10},
                {"symbol": " atw ", "shares": 5},
                {"symbol": "IAM", "shares": 2},
            ],
        },
    )
    assert updated.status_code == 200
    updated_payload = updated.json()
    assert updated_payload["name"] == "Top Banques"
    assert updated_payload["symbols"] == ["ATT", "ATW", "IAM"]
    assert updated_payload["component_shares"] == {"ATT": 10, "ATW": 5, "IAM": 2}
    assert updated_payload["components"] == [
        {"symbol": "ATT", "shares": 10},
        {"symbol": "ATW", "shares": 5},
        {"symbol": "IAM", "shares": 2},
    ]
    assert updated_payload["is_weighted_complete"] is True

    other_user_update = client.put(
        f"/dashboard/indices/{created_id}",
        headers=USER_B,
        json={"name": "Stolen", "components": [{"symbol": "IAM", "shares": 1}]},
    )
    assert other_user_update.status_code == 404

    listed_after_update = client.get("/dashboard/indices", headers=USER_A)
    assert listed_after_update.status_code == 200
    rows = listed_after_update.json()
    assert len(rows) == 1
    assert rows[0]["id"] == created_id

    other_user_delete = client.delete(f"/dashboard/indices/{created_id}", headers=USER_B)
    assert other_user_delete.status_code == 404

    deleted = client.delete(f"/dashboard/indices/{created_id}", headers=USER_A)
    assert deleted.status_code == 204

    listed_final = client.get("/dashboard/indices", headers=USER_A)
    assert listed_final.status_code == 200
    assert listed_final.json() == []


def test_dashboard_indices_reject_empty_symbols(client_and_session) -> None:
    client, _SessionLocal = client_and_session

    created = client.post(
        "/dashboard/indices",
        headers=USER_A,
        json={
            "name": "Indice Vide",
            "symbols": [" ", ""],
        },
    )
    assert created.status_code == 422


def test_dashboard_indices_reject_invalid_components(client_and_session) -> None:
    client, _SessionLocal = client_and_session

    duplicate = client.post(
        "/dashboard/indices",
        headers=USER_A,
        json={
            "name": "Doublon",
            "components": [
                {"symbol": "IAM", "shares": 10},
                {"symbol": " iam ", "shares": 5},
            ],
        },
    )
    assert duplicate.status_code == 422

    zero_shares = client.post(
        "/dashboard/indices",
        headers=USER_A,
        json={"name": "Zero", "components": [{"symbol": "IAM", "shares": 0}]},
    )
    assert zero_shares.status_code == 422

    fractional_shares = client.post(
        "/dashboard/indices",
        headers=USER_A,
        json={"name": "Fraction", "components": [{"symbol": "IAM", "shares": 1.5}]},
    )
    assert fractional_shares.status_code == 422


def test_dashboard_indices_can_use_available_stock_shares(client_and_session) -> None:
    client, SessionLocal = client_and_session
    db = SessionLocal()
    try:
        db.add_all(
            [
                models.StockMaster(symbol="IAM", display_name="Maroc Telecom", shares_outstanding=879_095_340),
                models.StockMaster(symbol="ATW", display_name="Attijariwafa Bank", shares_outstanding=215_140_839),
                models.StockMaster(symbol="BCP", display_name="Banque Centrale Populaire", shares_outstanding=203_312_473),
                models.StockMaster(symbol="AAA", display_name="Outside MASI", shares_outstanding=10_000),
            ]
        )
        db.commit()
    finally:
        db.close()

    created = client.post(
        "/dashboard/indices",
        headers=USER_A,
        json={"name": "MASI shares", "use_available_shares": True},
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["symbols"] == ["ATW", "BCP", "IAM"]
    assert payload["component_shares"] == {
        "ATW": 215_140_839,
        "BCP": 203_312_473,
        "IAM": 879_095_340,
    }
    assert payload["components"] == [
        {"symbol": "ATW", "shares": 215_140_839},
        {"symbol": "BCP", "shares": 203_312_473},
        {"symbol": "IAM", "shares": 879_095_340},
    ]
    assert payload["is_weighted_complete"] is True


def test_dashboard_indices_can_include_portfolio_edge(client_and_session, monkeypatch) -> None:
    client, _SessionLocal = client_and_session
    created = client.post(
        "/dashboard/indices",
        headers=USER_A,
        json={
            "name": "Indice Test",
            "components": [
                {"symbol": "AAA", "shares": 8},
                {"symbol": "BBB", "shares": 4},
            ],
        },
    )
    assert created.status_code == 201

    calls = []

    def fake_edge(_db, horizon, symbols, **_kwargs):
        calls.append((horizon, symbols))
        return {
            "label": "Portfolio auto",
            "triage": "watch",
            "active_count": 2,
            "total_count": 2,
            "long_count": 1,
            "short_count": 1,
            "n": 42,
            "action_expected_return_net": 0.012,
            "hit_rate": 0.57,
        }

    monkeypatch.setattr(
        dashboard_indices_router,
        "build_dashboard_portfolio_edge_for_symbols",
        fake_edge,
    )

    listed = client.get("/dashboard/indices?include_edge=true&horizon=medium", headers=USER_A)
    assert listed.status_code == 200
    rows = listed.json()
    assert rows[0]["portfolio_edge"]["n"] == 42
    assert rows[0]["portfolio_edge"]["active_count"] == 2
    assert calls == [("monthly", ["AAA", "BBB"])]

