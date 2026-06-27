from __future__ import annotations

import datetime as dt
import uuid

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.db import get_db
from services.api.app.routers import fundamentals as fundamentals_router
from services.api.app.services.fundamentals import run_and_persist_fundamental_signal_backtest


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


def _prices(symbol_index: int) -> pd.Series:
    dates = pd.date_range("2024-01-31", periods=4, freq="ME")
    values = [100.0 + symbol_index, 102.0 + symbol_index, 104.0 + symbol_index, 106.0 + symbol_index]
    return pd.Series(values, index=dates)


def test_signal_backtest_persists_fixture_result() -> None:
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    for table in (
        models.StockMaster.__table__,
        models.MarketDataStore.__table__,
        models.FundamentalImport.__table__,
        models.FundamentalLatestSnapshot.__table__,
        models.FundamentalEnsembleResult.__table__,
        models.FundamentalSignalBacktest.__table__,
    ):
        table.create(engine)
    db = SessionLocal()
    try:
        run = models.FundamentalImport(
            filename="pit.xlsx",
            source_hash="pit",
            status="succeeded",
            company_count=5,
            symbol_count=5,
            annual_metric_count=0,
            latest_snapshot_count=5,
            completed_at=dt.datetime(2024, 1, 15, tzinfo=dt.timezone.utc),
            source_universe="masi",
        )
        db.add(run)
        db.flush()
        symbols = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        for index, symbol in enumerate(symbols):
            db.add(models.StockMaster(symbol=symbol, display_name=symbol, market_region="masi"))
            db.add(
                models.MarketDataStore(
                    symbol=symbol,
                    timeframe="1D",
                    object_key=f"prices/{symbol}.parquet",
                    asset_class="equity",
                    adv_20d=1_000_000.0 + index,
                )
            )
            db.add(
                models.FundamentalLatestSnapshot(
                    import_id=run.id,
                    symbol=symbol,
                    company_name=symbol,
                    latest_statement_year=2023,
                    metrics_json={},
                    scores_json={"overall": 50.0 + index},
                    diagnostics_json={},
                    coverage_json={},
                    model_eligibility_json={},
                    source_json={},
                    as_of_date=dt.date(2024, 1, 20),
                )
            )
            db.add(
                models.FundamentalEnsembleResult(
                    import_id=run.id,
                    symbol=symbol,
                    scenario="base",
                    fair_value_base=100.0 + index,
                    current_price=90.0,
                    upside_pct=0.05 * (index + 1),
                    confidence_score=0.7,
                    usable_model_count=3,
                    excluded_model_count=0,
                    model_weights_json={},
                    warnings_json=[],
                )
            )
        db.commit()

        def loader(object_key: str) -> pd.Series:
            symbol = object_key.split("/")[-1].split(".")[0]
            return _prices(symbols.index(symbol))

        row = run_and_persist_fundamental_signal_backtest(
            db,
            signal="upside_pct",
            universe="custom",
            symbols=symbols,
            start=dt.date(2024, 1, 1),
            end=dt.date(2024, 4, 30),
            transaction_cost_bps=0.0,
            price_loader=loader,
        )
        db.commit()

        assert row.status == "succeeded"
        assert row.quintile_returns_json
        assert row.ic_json["rank_ic"] is not None
        assert row.equity_curve_json
        assert row.params_json["symbols"] == symbols
    finally:
        db.close()
        engine.dispose()


def test_signal_backtest_falls_back_to_import_timestamp_when_snapshot_as_of_missing() -> None:
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    for table in (
        models.StockMaster.__table__,
        models.MarketDataStore.__table__,
        models.FundamentalImport.__table__,
        models.FundamentalLatestSnapshot.__table__,
        models.FundamentalEnsembleResult.__table__,
        models.FundamentalSignalBacktest.__table__,
    ):
        table.create(engine)
    db = SessionLocal()
    try:
        run = models.FundamentalImport(
            filename="pit-null-asof.xlsx",
            source_hash="pit-null-asof",
            status="succeeded",
            company_count=5,
            symbol_count=5,
            annual_metric_count=0,
            latest_snapshot_count=5,
            completed_at=dt.datetime(2024, 1, 15, tzinfo=dt.timezone.utc),
            source_universe="masi",
        )
        db.add(run)
        db.flush()
        symbols = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        for index, symbol in enumerate(symbols):
            db.add(models.StockMaster(symbol=symbol, display_name=symbol, market_region="masi"))
            db.add(
                models.MarketDataStore(
                    symbol=symbol,
                    timeframe="1D",
                    object_key=f"prices/{symbol}.parquet",
                    asset_class="equity",
                    adv_20d=1_000_000.0 + index,
                )
            )
            db.add(
                models.FundamentalLatestSnapshot(
                    import_id=run.id,
                    symbol=symbol,
                    company_name=symbol,
                    latest_statement_year=2023,
                    metrics_json={},
                    scores_json={"overall": 50.0 + index},
                    diagnostics_json={},
                    coverage_json={},
                    model_eligibility_json={},
                    source_json={},
                    as_of_date=None,
                )
            )
            db.add(
                models.FundamentalEnsembleResult(
                    import_id=run.id,
                    symbol=symbol,
                    scenario="base",
                    fair_value_base=100.0 + index,
                    current_price=90.0,
                    upside_pct=0.05 * (index + 1),
                    confidence_score=0.7,
                    usable_model_count=3,
                    excluded_model_count=0,
                    model_weights_json={},
                    warnings_json=[],
                )
            )
        db.commit()

        def loader(object_key: str) -> pd.Series:
            symbol = object_key.split("/")[-1].split(".")[0]
            return _prices(symbols.index(symbol))

        row = run_and_persist_fundamental_signal_backtest(
            db,
            signal="upside_pct",
            universe="custom",
            symbols=symbols,
            start=dt.date(2024, 1, 1),
            end=dt.date(2024, 4, 30),
            transaction_cost_bps=0.0,
            price_loader=loader,
        )
        db.commit()

        assert row.status == "succeeded"
        assert row.quintile_returns_json
        assert row.ic_json["rank_ic"] is not None
        assert "snapshot_as_of_import_timestamp_fallback" in row.warnings_json
    finally:
        db.close()
        engine.dispose()


def test_signal_backtest_endpoint_persists_and_fetches(monkeypatch) -> None:
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "admin-secret")
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    models.FundamentalSignalBacktest.__table__.create(engine)
    app = FastAPI()
    app.include_router(fundamentals_router.router)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def fake_run(db, **kwargs):
        row = models.FundamentalSignalBacktest(
            run_id=uuid.uuid4(),
            signal=kwargs["signal"],
            universe=kwargs["universe"],
            rebalance="M",
            as_of=dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc),
            status="succeeded",
            quintile_returns_json=[{"quintile": 5, "mean_forward_return": 0.03, "count": 4}],
            ic_json={"rank_ic": 0.42, "ic_decay": [{"horizon_days": 21, "ic": 0.31, "n": 3}]},
            equity_curve_json=[{"date": "2024-02-29", "equity": 1.03, "net_return": 0.03}],
            turnover_json=[{"date": "2024-01-31", "turnover": 1.0}],
            holdings_json=[{"date": "2024-01-31", "top_quintile": ["AAA"]}],
            params_json={"scenario": kwargs["scenario"], "symbols": kwargs["symbols"]},
            warnings_json=[],
        )
        db.add(row)
        db.flush()
        return row

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(fundamentals_router, "run_and_persist_fundamental_signal_backtest", fake_run)
    try:
        with TestClient(app) as client:
            created = client.post(
                "/fundamentals/signal-backtest",
                headers={"x-admin-api-key": "admin-secret"},
                json={"signal": "upside_pct", "universe": "custom", "symbols": ["AAA"], "scenario": "base"},
            )
            assert created.status_code == 200
            payload = created.json()
            assert payload["status"] == "succeeded"
            assert payload["ic"]["rank_ic"] == 0.42
            assert payload["quintile_returns"][0]["quintile"] == 5

            fetched = client.get(f"/fundamentals/signal-backtest/{payload['run_id']}")
            assert fetched.status_code == 200
            assert fetched.json()["holdings"][0]["top_quintile"] == ["AAA"]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_signal_backtest_endpoint_reports_missing_storage(monkeypatch) -> None:
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "admin-secret")
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    app = FastAPI()
    app.include_router(fundamentals_router.router)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/fundamentals/signal-backtest",
                headers={"x-admin-api-key": "admin-secret"},
                json={"signal": "upside_pct", "universe": "custom", "symbols": ["AAA"], "scenario": "base"},
            )
            assert response.status_code == 503
            assert "storage is not ready" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
