from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.db import get_db
from services.api.app.routers import fundamentals as fundamentals_router
from services.api.app.services.fundamentals import make_bulk_overrides_loader


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


def _client_and_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    for table in (
        models.Dataset.__table__,
        models.StockMaster.__table__,
        models.FundamentalImport.__table__,
        models.FundamentalLatestSnapshot.__table__,
        models.FundamentalAssumptionSet.__table__,
        models.FundamentalAssumptionOverride.__table__,
    ):
        table.create(engine)
    app = FastAPI()
    app.include_router(fundamentals_router.router)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return app, engine, SessionLocal


def _seed_stock(SessionLocal) -> None:
    db = SessionLocal()
    try:
        db.add(models.StockMaster(symbol="AAA", display_name="Alpha", sector="Banks", market_region="masi"))
        db.commit()
    finally:
        db.close()


def test_assumption_override_lifecycle(monkeypatch) -> None:
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "admin-secret")
    app, engine, SessionLocal = _client_and_session()
    user_headers = {"x-app-user-id": "analyst-1", "x-app-user-email": "analyst@example.com"}
    admin_user_headers = {**user_headers, "x-admin-api-key": "admin-secret"}
    try:
        _seed_stock(SessionLocal)
        with TestClient(app) as client:
            unauthenticated = client.put(
                "/fundamentals/AAA/assumptions/bull/override",
                headers={"x-admin-api-key": "admin-secret"},
                json={"overrides": {"wacc": 0.10}},
            )
            assert unauthenticated.status_code == 401

            forbidden = client.put(
                "/fundamentals/AAA/assumptions/bull/override",
                headers=user_headers,
                json={"overrides": {"wacc": 0.10}},
            )
            assert forbidden.status_code == 403

            created = client.put(
                "/fundamentals/AAA/assumptions/bull/override",
                headers=admin_user_headers,
                json={"overrides": {"wacc": "0.10"}, "note": "Higher risk", "created_by": "spoofed"},
            )
            assert created.status_code == 200
            payload = created.json()
            assert payload["overrides"] == {"wacc": 0.10}
            assert payload["note"] == "Higher risk"
            assert payload["created_by"] == "analyst@example.com"

            resolved = client.get("/fundamentals/AAA/assumptions/bull")
            assert resolved.status_code == 200
            assert resolved.json()["assumptions"]["wacc"] == 0.10
            assert resolved.json()["provenance"]["wacc"] == "symbol"

            current = client.get("/fundamentals/AAA/assumptions/bull/override")
            assert current.status_code == 200
            assert current.json()["id"] == payload["id"]

            superseding = client.put(
                "/fundamentals/AAA/assumptions/bull/override",
                headers=admin_user_headers,
                json={"overrides": {"wacc": 0.11}, "note": "Superseded"},
            )
            assert superseding.status_code == 200
            assert superseding.json()["id"] != payload["id"]

            db = SessionLocal()
            try:
                current_rows = (
                    db.query(models.FundamentalAssumptionOverride)
                    .filter(
                        models.FundamentalAssumptionOverride.symbol == "AAA",
                        models.FundamentalAssumptionOverride.scenario == "bull",
                        models.FundamentalAssumptionOverride.is_current.is_(True),
                    )
                    .all()
                )
                assert len(current_rows) == 1
                assert current_rows[0].overrides == {"wacc": 0.11}
            finally:
                db.close()

            deleted = client.delete("/fundamentals/AAA/assumptions/bull/override", headers=admin_user_headers)
            assert deleted.status_code == 204
            assert client.get("/fundamentals/AAA/assumptions/bull/override").status_code == 404
            reverted = client.get("/fundamentals/AAA/assumptions/bull").json()
            assert reverted["assumptions"]["wacc"] == 0.07
            assert reverted["provenance"]["wacc"] == "scenario"
    finally:
        engine.dispose()


def test_assumption_override_validation(monkeypatch) -> None:
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "admin-secret")
    app, engine, SessionLocal = _client_and_session()
    headers = {"x-app-user-id": "analyst-1", "x-admin-api-key": "admin-secret"}
    try:
        _seed_stock(SessionLocal)
        with TestClient(app) as client:
            unknown = client.put(
                "/fundamentals/AAA/assumptions/base/override",
                headers=headers,
                json={"overrides": {"foo": 1.0}},
            )
            assert unknown.status_code == 422
            assert "unknown assumption key" in unknown.text

            non_float = client.put(
                "/fundamentals/AAA/assumptions/base/override",
                headers=headers,
                json={"overrides": {"wacc": "not-a-number"}},
            )
            assert non_float.status_code == 422
            assert "finite float" in non_float.text
    finally:
        engine.dispose()


def test_bulk_loader_one_query_for_many_symbols() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    models.FundamentalAssumptionOverride.__table__.create(engine)
    db = SessionLocal()
    try:
        db.add(
            models.FundamentalAssumptionOverride(
                symbol="SYM001",
                scenario="bull",
                overrides={"wacc": 0.10},
                note="test",
                created_by="tester",
                is_current=True,
            )
        )
        db.commit()

        statements: list[str] = []

        def count_select(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = statement.lower()
            if normalized.lstrip().startswith("select") and "fundamental_assumption_override" in normalized:
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", count_select)
        symbols = [f"SYM{index:03d}" for index in range(50)]
        loader = make_bulk_overrides_loader(db, symbols)
        for symbol in symbols:
            for scenario in ("bear", "base", "bull"):
                loader(symbol, scenario)

        assert len(statements) == 1
        assert loader("SYM001", "bull") == {"wacc": 0.10}
    finally:
        db.close()
        engine.dispose()
