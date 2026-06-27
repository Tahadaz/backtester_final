from __future__ import annotations

import datetime as dt
import os
import uuid

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
        models.MarketDataStore.__table__,
        models.StockMaster.__table__,
        models.FundamentalImport.__table__,
        models.FundamentalSourceDocument.__table__,
        models.FundamentalAnnualMetric.__table__,
        models.FundamentalPeriodMetric.__table__,
        models.FundamentalLatestSnapshot.__table__,
        models.FundamentalQualityIssue.__table__,
        models.FundamentalAssumptionSet.__table__,
        models.FundamentalAssumptionOverride.__table__,
        models.FundamentalMetricOverride.__table__,
        models.FundamentalBetaHistory.__table__,
        models.FundamentalValuationResult.__table__,
        models.FundamentalEnsembleResult.__table__,
        models.FundamentalProjection.__table__,
        models.FundamentalIntegrityReport.__table__,
        models.FundamentalThesis.__table__,
        models.FundamentalCatalyst.__table__,
        models.FundamentalPillarScoreHistory.__table__,
        models.SignalEngineGlobalResult.__table__,
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


def _seed_snapshot(
    SessionLocal,
    *,
    symbol: str = "AAA",
    values: dict[str, float] | None = None,
    vintages: dict[str, dt.datetime] | None = None,
) -> uuid.UUID:
    if values is None:
        values = {"bear": 90.0, "base": 110.0, "bull": 130.0}
    run_ts = dt.datetime(2026, 6, 5, 12, 0, tzinfo=dt.timezone.utc)
    if vintages is None:
        vintages = {scenario: run_ts for scenario in fundamentals_router.VALUATION_SCENARIOS}
    db = SessionLocal()
    try:
        db.add(models.StockMaster(symbol=symbol, display_name="Alpha", sector="Industrials", market_region="masi", is_active=True))
        run = models.FundamentalImport(
            filename=f"{symbol.lower()}-fundamentals.xlsx",
            source_hash=f"{symbol.lower()}-hash",
            status="succeeded",
            company_count=1,
            symbol_count=1,
            latest_snapshot_count=1,
            completed_at=run_ts,
        )
        db.add(run)
        db.flush()
        db.add(
            models.FundamentalLatestSnapshot(
                import_id=run.id,
                symbol=symbol,
                company_name="Alpha",
                latest_statement_year=2025,
                metrics_json={"Current_Price": 80.0, "MarketCap_Calc": 800.0},
                scores_json={"overall": 75.0, "value": 70.0, "quality": 80.0},
                diagnostics_json={},
                coverage_json={},
                model_eligibility_json={},
                source_json={"currency": "MAD"},
            )
        )
        for scenario, value in values.items():
            db.add(
                models.FundamentalEnsembleResult(
                    import_id=run.id,
                    symbol=symbol,
                    scenario=scenario,
                    fair_value_low=value * 0.9,
                    fair_value_base=value,
                    fair_value_high=value * 1.1,
                    current_price=80.0,
                    upside_pct=value / 80.0 - 1.0,
                    confidence_score=0.8,
                    usable_model_count=4,
                    excluded_model_count=0,
                    model_weights_json={"residual_income": 1.0},
                    warnings_json=["all_required_inputs_observed"],
                    currency="MAD",
                    model_dispersion_cv=0.05,
                    computed_at=vintages[scenario],
                )
            )
            db.add(
                models.FundamentalValuationResult(
                    import_id=run.id,
                    symbol=symbol,
                    scenario=scenario,
                    model="residual_income",
                    fair_value=value,
                    current_price=80.0,
                    upside_pct=value / 80.0 - 1.0,
                    confidence="high",
                    confidence_score=0.8,
                    weight=1.0,
                    family="intrinsic",
                    methodology="test",
                    currency="MAD",
                    inputs_json={"cost_of_equity": 0.10, "dividend_yield": 0.0},
                    outputs_json={},
                    warnings_json=["all_required_inputs_observed"],
                    computed_at=vintages[scenario],
                )
            )
        db.commit()
        return run.id
    finally:
        db.close()


def test_default_universe_revalue_recomputes_atomic_scenario_trios(monkeypatch) -> None:
    monkeypatch.setattr("services.api.app.auth.settings.ADMIN_API_KEY", "admin-secret")
    monkeypatch.setattr(fundamentals_router, "_sync_fundamental_signal_rows", lambda db, symbols: {"total": len(symbols)})
    app, engine, SessionLocal = _client_and_session()
    try:
        for symbol in ("AAA", "BBB"):
            _seed_snapshot(SessionLocal, symbol=symbol, values={}, vintages={})

        calls: list[tuple[str, tuple[str, ...]]] = []

        def fake_all_scenarios(db, *, import_id, symbol, scenarios=fundamentals_router.VALUATION_SCENARIOS, overrides_loader=None):
            del overrides_loader
            calls.append((symbol, tuple(scenarios)))
            run_ts = dt.datetime(2026, 6, 5, 13, len(calls), tzinfo=dt.timezone.utc)
            for idx, scenario in enumerate(scenarios, start=1):
                db.add(
                    models.FundamentalEnsembleResult(
                        import_id=import_id,
                        symbol=symbol,
                        scenario=scenario,
                        fair_value_base=100.0 + idx,
                        current_price=80.0,
                        upside_pct=0.25,
                        confidence_score=0.8,
                        usable_model_count=3,
                        excluded_model_count=0,
                        model_weights_json={"residual_income": 1.0},
                        warnings_json=["all_required_inputs_observed"],
                        computed_at=run_ts,
                    )
                )
            return []

        monkeypatch.setattr(fundamentals_router, "recompute_symbol_valuations_all_scenarios", fake_all_scenarios)
        with TestClient(app) as client:
            response = client.post("/fundamentals/recompute", headers={"x-admin-api-key": "admin-secret"})
        assert response.status_code == 200
        assert {symbol for symbol, _scenarios in calls} == {"AAA", "BBB"}
        assert all(scenarios == tuple(fundamentals_router.VALUATION_SCENARIOS) for _symbol, scenarios in calls)

        db = SessionLocal()
        try:
            for symbol in ("AAA", "BBB"):
                rows = (
                    db.query(models.FundamentalEnsembleResult)
                    .filter(models.FundamentalEnsembleResult.symbol == symbol)
                    .all()
                )
                assert {row.scenario for row in rows} == set(fundamentals_router.VALUATION_SCENARIOS)
                assert len({row.computed_at for row in rows}) == 1
        finally:
            db.close()
    finally:
        engine.dispose()


def test_mismatched_scenario_vintages_are_served_base_only_with_stale_flag(monkeypatch) -> None:
    app, engine, SessionLocal = _client_and_session()
    try:
        base_ts = dt.datetime(2026, 6, 5, 12, 0, tzinfo=dt.timezone.utc)
        old_ts = dt.datetime(2026, 6, 4, 12, 0, tzinfo=dt.timezone.utc)
        _seed_snapshot(
            SessionLocal,
            values={"bear": 130.0, "base": 100.0, "bull": 150.0},
            vintages={"bear": old_ts, "base": base_ts, "bull": old_ts},
        )
        monkeypatch.setattr(fundamentals_router, "_ensure_latest_symbol_valuations", lambda *args, **kwargs: None)

        with TestClient(app) as client:
            response = client.get("/fundamentals/stocks/AAA?scenario=bull")
        assert response.status_code == 200
        payload = response.json()
        assert payload["scenario_trio_stale"] is True
        assert payload["viewed_scenario"] == "base"
        assert set(payload["ensembles"]) == {"base"}
        assert payload["ensemble"]["scenario"] == "base"
        assert payload["ensemble"]["fair_value_base"] == 100.0
        assert payload["target_price"] == 100.0
        assert "bear" not in payload["ensembles"]
        assert "bull" not in payload["ensembles"]
    finally:
        engine.dispose()


def test_scenario_ordering_invariant_is_part_of_trio_coherence() -> None:
    run_ts = dt.datetime(2026, 6, 5, 12, 0, tzinfo=dt.timezone.utc)
    ordered = {
        scenario: models.FundamentalEnsembleResult(symbol="AAA", scenario=scenario, fair_value_base=value, computed_at=run_ts)
        for scenario, value in {"bear": 90.0, "base": 100.0, "bull": 120.0}.items()
    }
    unordered = {
        scenario: models.FundamentalEnsembleResult(symbol="AAA", scenario=scenario, fair_value_base=value, computed_at=run_ts)
        for scenario, value in {"bear": 110.0, "base": 100.0, "bull": 120.0}.items()
    }

    assert fundamentals_router._scenario_rows_are_coherent(ordered) is True
    assert fundamentals_router._scenario_rows_are_coherent(unordered) is False


def test_headline_target_stays_base_anchored_when_viewing_bull() -> None:
    app, engine, SessionLocal = _client_and_session()
    try:
        _seed_snapshot(SessionLocal, values={"bear": 90.0, "base": 110.0, "bull": 150.0})
        with TestClient(app) as client:
            response = client.get("/fundamentals/stocks/AAA?scenario=bull")
        assert response.status_code == 200
        payload = response.json()
        assert payload["scenario_trio_stale"] is False
        assert payload["viewed_scenario"] == "bull"
        assert payload["ensemble"]["scenario"] == "bull"
        assert payload["ensemble"]["fair_value_base"] == 150.0
        assert payload["target_price"] == 110.0
    finally:
        engine.dispose()
