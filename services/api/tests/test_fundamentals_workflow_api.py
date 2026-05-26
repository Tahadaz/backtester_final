from __future__ import annotations

import datetime as dt
import os

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
        models.FundamentalAnnualMetric.__table__,
        models.FundamentalPeriodMetric.__table__,
        models.FundamentalLatestSnapshot.__table__,
        models.FundamentalQualityIssue.__table__,
        models.FundamentalAssumptionSet.__table__,
        models.FundamentalAssumptionOverride.__table__,
        models.FundamentalValuationResult.__table__,
        models.FundamentalEnsembleResult.__table__,
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


def _seed(SessionLocal):
    db = SessionLocal()
    try:
        run = models.FundamentalImport(
            filename="fundamentals.xlsx",
            source_hash="hash",
            status="succeeded",
            company_count=1,
            symbol_count=1,
            annual_metric_count=3,
            latest_snapshot_count=1,
            completed_at=dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc),
        )
        db.add(run)
        db.flush()
        db.add(models.StockMaster(symbol="AAA", display_name="Alpha", sector="Banks", market_region="masi"))
        db.add(
            models.FundamentalLatestSnapshot(
                id=1,
                import_id=run.id,
                symbol="AAA",
                company_name="Alpha",
                latest_statement_year=2024,
                metrics_json={"Current_Price": 100.0, "PER": 10.0, "Price_to_Book": 1.0, "MarketCap_Calc": 1000.0},
                scores_json={"overall": 72.0, "quality": 80.0, "value": 65.0},
                diagnostics_json={},
                coverage_json={},
                model_eligibility_json={},
                source_json={"currency": "MAD"},
            )
        )
        db.add_all(
            [
                models.FundamentalPeriodMetric(
                    id=1,
                    import_id=run.id,
                    symbol="AAA",
                    company_name="Alpha",
                    fiscal_year=2024,
                    period_type="annual",
                    period_label="FY",
                    metric_name="Total_Equity",
                    metric_value=400.0,
                    raw_metric_name="Capitaux_Propres_2024",
                ),
                models.FundamentalPeriodMetric(
                    id=2,
                    import_id=run.id,
                    symbol="AAA",
                    company_name="Alpha",
                    fiscal_year=2024,
                    period_type="quarterly",
                    period_label="Q2",
                    period_end_date=dt.date(2024, 6, 30),
                    metric_name="Resultat_net",
                    metric_value=42.0,
                    raw_metric_name="Resultat_net_2024",
                    document_title="Q2 statement",
                ),
            ]
        )
        db.add(
            models.FundamentalEnsembleResult(
                id=1,
                import_id=run.id,
                symbol="AAA",
                scenario="base",
                fair_value_low=90.0,
                fair_value_base=120.0,
                fair_value_high=140.0,
                current_price=100.0,
                upside_pct=0.20,
                confidence_score=0.7,
                usable_model_count=3,
                excluded_model_count=1,
                model_weights_json={"fcff_dcf": 1.0},
                warnings_json=[],
                currency="MAD",
            )
        )
        db.add(
            models.FundamentalIntegrityReport(
                import_id=run.id,
                symbol="AAA",
                statement_year=2024,
                overall_status="pass",
                confidence_haircut=0.0,
                checks_json=[
                    {
                        "name": "bs_balance",
                        "status": "pass",
                        "delta": 0.0,
                        "rel_delta": 0.0,
                        "inputs": {"Total_Assets": 100.0, "Total_Liabilities": 60.0, "Total_Equity": 40.0},
                    }
                ],
            )
        )
        history_runs = [run]
        for idx in range(1, 3):
            old_run = models.FundamentalImport(
                filename=f"fundamentals_{idx}.xlsx",
                source_hash=f"hash{idx}",
                status="succeeded",
                company_count=1,
                symbol_count=1,
                annual_metric_count=0,
                latest_snapshot_count=0,
                completed_at=dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc) - dt.timedelta(days=idx),
            )
            db.add(old_run)
            db.flush()
            history_runs.append(old_run)
        for idx, value in enumerate([80.0, 79.0, 78.0]):
            db.add(
                models.FundamentalPillarScoreHistory(
                    import_id=history_runs[idx].id,
                    symbol="AAA",
                    as_of=dt.date(2024 - idx, 12, 31),
                    quality_score=value,
                    value_score=60.0,
                    growth_score=55.0,
                    risk_score=65.0,
                    cash_flow_score=70.0,
                    health_score=75.0,
                    overall_score=72.0,
                    pillar_coverage_json={},
                )
            )
        db.commit()
    finally:
        db.close()


def _seed_auto_scenarios(SessionLocal):
    db = SessionLocal()
    try:
        run = models.FundamentalImport(
            filename="auto.xlsx",
            source_hash="auto-hash",
            status="succeeded",
            company_count=1,
            symbol_count=1,
            annual_metric_count=0,
            latest_snapshot_count=1,
            completed_at=dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc),
        )
        db.add(run)
        db.flush()
        db.add(models.StockMaster(symbol="AAA", display_name="Alpha", sector="Banks", market_region="masi"))
        db.add(
            models.FundamentalLatestSnapshot(
                id=1,
                import_id=run.id,
                symbol="AAA",
                company_name="Alpha",
                latest_statement_year=2024,
                metrics_json={"Current_Price": 100.0, "MarketCap_Calc": 1000.0},
                scores_json={"overall": 72.0, "quality": 80.0, "value": 65.0},
                diagnostics_json={},
                coverage_json={},
                model_eligibility_json={},
                source_json={"currency": "MAD"},
            )
        )
        for idx, (scenario, fair_value, confidence) in enumerate(
            [
                ("bear", 90.0, 0.50),
                ("base", 118.0, 0.60),
                ("bull", 104.0, 0.70),
            ],
            start=1,
        ):
            db.add(
                models.FundamentalEnsembleResult(
                    id=idx,
                    import_id=run.id,
                    symbol="AAA",
                    scenario=scenario,
                    fair_value_low=fair_value * 0.95,
                    fair_value_base=fair_value,
                    fair_value_high=fair_value * 1.05,
                    current_price=100.0,
                    upside_pct=fair_value / 100.0 - 1.0,
                    confidence_score=confidence,
                    usable_model_count=1,
                    excluded_model_count=0,
                    model_weights_json={"fcff_dcf": 1.0},
                    warnings_json=[],
                    currency="MAD",
                )
            )
        db.commit()
    finally:
        db.close()


def test_integrity_thesis_catalyst_history_and_exports() -> None:
    app, engine, SessionLocal = _client_and_session()
    try:
        _seed(SessionLocal)
        with TestClient(app) as client:
            response = client.get("/fundamentals/stocks/AAA/integrity")
            assert response.status_code == 200
            assert response.json()["overall_status"] == "pass"

            detail = client.get("/fundamentals/stocks/AAA")
            assert detail.status_code == 200
            period_metrics = detail.json()["period_metrics"]
            assert {row["period_type"] for row in period_metrics} == {"annual", "quarterly"}
            assert next(row for row in period_metrics if row["period_type"] == "quarterly")["period_label"] == "Q2"

            thesis_body = {
                "direction": "long",
                "conviction": "high",
                "core_thesis": "Alpha is a high-quality bank with resilient earnings and valuation upside.",
                "bullish_drivers": [{"title": "Quality", "detail": "Returns remain above peers.", "pillar": "quality"}],
                "bearish_drivers": [{"title": "Rates", "detail": "Lower rates could pressure margins.", "pillar": "risk"}],
                "target_price": 130,
                "stop_price": 90,
                "target_horizon_months": 12,
            }
            assert client.post("/fundamentals/stocks/AAA/thesis", json=thesis_body).status_code == 200
            thesis_body["core_thesis"] = "Alpha remains attractive after a cleaner thesis update and a better catalyst path."
            assert client.post("/fundamentals/stocks/AAA/thesis", json=thesis_body).status_code == 200
            history = client.get("/fundamentals/stocks/AAA/thesis/history").json()
            assert len(history["items"]) == 2
            assert sum(1 for item in history["items"] if item["is_current"]) == 1

            catalyst = client.post(
                "/fundamentals/stocks/AAA/catalysts",
                json={"event_type": "earnings", "event_date": "2026-06-15", "impact_tier": "moderate", "title": "FY results"},
            )
            assert catalyst.status_code == 200
            catalyst_id = catalyst.json()["id"]
            calendar = client.get("/fundamentals/calendar?from=2026-06-01&to=2026-06-30").json()
            assert [item["id"] for item in calendar["items"]] == [catalyst_id]
            patched = client.patch(f"/fundamentals/catalysts/{catalyst_id}", json={"event_date": "2026-06-18"})
            assert patched.status_code == 200
            assert patched.json()["id"] == catalyst_id
            assert client.delete(f"/fundamentals/catalysts/{catalyst_id}").status_code == 204

            pillar = client.get("/fundamentals/stocks/AAA/pillar-history").json()
            assert pillar["trend"]["quality"] == "on_track"

            sheet = client.get("/fundamentals/stocks/AAA/tearsheet")
            assert sheet.status_code == 200
            assert "section-valuation" in sheet.text
    finally:
        engine.dispose()


def test_auto_scenario_selects_objective_closest_to_current_price() -> None:
    app, engine, SessionLocal = _client_and_session()
    try:
        _seed_auto_scenarios(SessionLocal)
        with TestClient(app) as client:
            batch = client.post("/fundamentals/snapshot/batch?scenario=auto", json={"symbols": ["AAA"]})
            assert batch.status_code == 200
            assert batch.json()["AAA"]["fair_value"] == 104.0
            assert batch.json()["AAA"]["confidence_score"] == 0.70

            detail = client.get("/fundamentals/stocks/AAA")
            assert detail.status_code == 200
            assert detail.json()["ensemble"]["scenario"] == "bull"
            assert detail.json()["ensemble"]["fair_value_base"] == 104.0
            assert set(detail.json()["ensembles"]) == {"bear", "base", "bull"}

            universe = client.get("/fundamentals/universe")
            assert universe.status_code == 200
            row = next(item for item in universe.json() if item["symbol"] == "AAA")
            assert row["ensemble"]["scenario"] == "bull"
            assert row["target_price"] == 104.0

            manual_base = client.get("/fundamentals/stocks/AAA?scenario=base")
            assert manual_base.status_code == 200
            assert manual_base.json()["ensemble"]["scenario"] == "base"
            assert manual_base.json()["ensemble"]["fair_value_base"] == 118.0
    finally:
        engine.dispose()
