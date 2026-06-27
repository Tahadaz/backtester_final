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
from services.api.app.routers import fundamentals as fundamentals_router


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

    models.Dataset.__table__.create(engine)
    models.MarketDataStore.__table__.create(engine)
    models.StockMaster.__table__.create(engine)
    models.FundamentalImport.__table__.create(engine)
    models.FundamentalSourceDocument.__table__.create(engine)
    models.FundamentalAnnualMetric.__table__.create(engine)
    models.FundamentalLatestSnapshot.__table__.create(engine)

    app = FastAPI()
    app.include_router(fundamentals_router.router)

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


def _seed_fundamentals(SessionLocal) -> None:
    db = SessionLocal()
    try:
        run = models.FundamentalImport(
            filename="fundamentals.xlsx",
            source_hash="hash",
            status="succeeded",
            company_count=3,
            symbol_count=3,
            annual_metric_count=0,
            latest_snapshot_count=3,
        )
        db.add(run)
        db.flush()
        db.add_all(
            [
                models.StockMaster(symbol="AAA", display_name="Alpha Bank", sector="Banks", market_region="masi", shares_outstanding=10),
                models.StockMaster(symbol="BBB", display_name="Beta Bank", sector="Banks", market_region="masi", shares_outstanding=10),
                models.StockMaster(symbol="CCC", display_name="Cement Co", sector="Materials", market_region="masi", shares_outstanding=10),
            ]
        )
        db.add_all(
            [
                models.FundamentalLatestSnapshot(
                    id=1,
                    import_id=run.id,
                    symbol="AAA",
                    company_name="Alpha Bank",
                    latest_statement_year=2024,
                    metrics_json={"Current_Price": 10.0, "MarketCap_Calc": 100.0, "PER": 10.0, "Price_to_Book": 1.0},
                    scores_json={},
                    diagnostics_json={},
                    coverage_json={},
                    model_eligibility_json={},
                    source_json={},
                ),
                models.FundamentalLatestSnapshot(
                    id=2,
                    import_id=run.id,
                    symbol="BBB",
                    company_name="Beta Bank",
                    latest_statement_year=2024,
                    metrics_json={"Current_Price": 20.0, "MarketCap_Calc": 200.0, "PER": 20.0, "Price_to_Book": 2.0},
                    scores_json={},
                    diagnostics_json={},
                    coverage_json={},
                    model_eligibility_json={},
                    source_json={},
                ),
                models.FundamentalLatestSnapshot(
                    id=3,
                    import_id=run.id,
                    symbol="CCC",
                    company_name="Cement Co",
                    latest_statement_year=2024,
                    metrics_json={"Current_Price": 30.0, "MarketCap_Calc": 300.0, "PER": 30.0, "Price_to_Book": 3.0},
                    scores_json={},
                    diagnostics_json={},
                    coverage_json={},
                    model_eligibility_json={},
                    source_json={},
                ),
            ]
        )
        db.commit()
    finally:
        db.close()


def test_sector_comparables_show_including_and_peer_only_weights(client_and_session) -> None:
    client, SessionLocal = client_and_session
    _seed_fundamentals(SessionLocal)

    response = client.post(
        "/fundamentals/stocks/AAA/comparables",
        json={"comparator_type": "sector", "metric_keys": ["PER"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["comparator"]["type"] == "sector"
    assert payload["comparator"]["target_in_comparator"] is True
    assert [row["symbol"] for row in payload["peers"]] == ["AAA", "BBB"]
    per = payload["benchmarks"]["PER"]
    assert per["weighted_including_target"] == pytest.approx((10.0 * 100.0 + 20.0 * 200.0) / 300.0)
    assert per["weighted_excluding_target"] == pytest.approx(20.0)
    assert per["median"] == pytest.approx(15.0)


def test_index_comparables_use_component_shares_times_price(client_and_session) -> None:
    client, SessionLocal = client_and_session
    _seed_fundamentals(SessionLocal)

    response = client.post(
        "/fundamentals/stocks/AAA/comparables",
        json={
            "comparator_type": "index",
            "comparator_name": "Manual Banks",
            "components": [
                {"symbol": "AAA", "shares": 5},
                {"symbol": "BBB", "shares": 10},
            ],
            "metric_keys": ["PER"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["comparator"]["type"] == "index"
    assert payload["comparator"]["weight_source"] == "component_shares_x_price"
    per = payload["benchmarks"]["PER"]
    assert per["weighted_including_target"] == pytest.approx((10.0 * 50.0 + 20.0 * 200.0) / 250.0)
    assert per["weighted_excluding_target"] == pytest.approx(20.0)
    weights = {row["symbol"]: row["weights"]["PER"] for row in payload["peers"]}
    assert weights["AAA"] == pytest.approx(50.0 / 250.0)
    assert weights["BBB"] == pytest.approx(200.0 / 250.0)
