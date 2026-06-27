from __future__ import annotations

import datetime as dt

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.services.fundamentals import derive_research_overlay


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


def test_overlay_dates_separate_data_cutoff_valuation_and_target() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    for table in (
        models.Dataset.__table__,
        models.FundamentalImport.__table__,
        models.FundamentalSourceDocument.__table__,
        models.FundamentalLatestSnapshot.__table__,
        models.FundamentalPeriodMetric.__table__,
        models.FundamentalValuationResult.__table__,
        models.FundamentalEnsembleResult.__table__,
    ):
        table.create(engine)
    db = SessionLocal()
    try:
        run = models.FundamentalImport(
            filename="overlay.xlsx",
            source_hash="overlay-hash",
            status="succeeded",
            company_count=1,
            symbol_count=1,
            annual_metric_count=0,
            latest_snapshot_count=1,
            completed_at=dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc),
            source_universe="masi",
        )
        db.add(run)
        db.flush()
        db.add(
            models.FundamentalLatestSnapshot(
                import_id=run.id,
                symbol="AAA",
                company_name="Alpha",
                latest_statement_year=2026,
                metrics_json={"Current_Price": 100.0},
                scores_json={},
                diagnostics_json={},
                coverage_json={},
                model_eligibility_json={},
                source_json={},
                as_of_date=dt.date(2026, 8, 15),
            )
        )
        db.add(
            models.FundamentalPeriodMetric(
                import_id=run.id,
                symbol="AAA",
                company_name="Alpha",
                fiscal_year=2026,
                period_type="quarterly",
                period_label="Q2",
                period_end_date=dt.date(2026, 6, 30),
                metric_name="Revenue",
                metric_value=100.0,
            )
        )
        ensemble = models.FundamentalEnsembleResult(
            import_id=run.id,
            symbol="AAA",
            scenario="base",
            fair_value_low=100.0,
            fair_value_base=120.0,
            fair_value_high=140.0,
            current_price=100.0,
            upside_pct=0.20,
            confidence_score=0.80,
            usable_model_count=3,
            excluded_model_count=0,
            model_weights_json={},
            warnings_json=[],
            computed_at=dt.datetime(2026, 8, 10, 9, 30, tzinfo=dt.timezone.utc),
        )
        db.add(ensemble)
        db.commit()

        overlay = derive_research_overlay(db, symbol="AAA", scenario="base", ensemble=ensemble, import_row=run, current_price=100.0)

        assert overlay["as_of_date"] == "2026-06-30"
        assert overlay["valuation_date"] == "2026-08-10"
        assert overlay["target_date"] == "2027-06-30"
    finally:
        db.close()
        engine.dispose()
