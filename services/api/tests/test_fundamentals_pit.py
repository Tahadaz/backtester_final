from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.services.fundamentals import get_snapshot_as_of, sync_bvc_period_metrics_to_annual_and_latest


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    for table in (
        models.FundamentalImport.__table__,
        models.FundamentalSourceDocument.__table__,
        models.FundamentalAnnualMetric.__table__,
        models.FundamentalPeriodMetric.__table__,
        models.FundamentalLatestSnapshot.__table__,
    ):
        table.create(engine)
    try:
        yield SessionLocal
    finally:
        engine.dispose()


def _run(db) -> models.FundamentalImport:
    run = models.FundamentalImport(
        filename="bvc.xlsx",
        source_hash="hash",
        data_source="bvc",
        status="succeeded",
        company_count=1,
        symbol_count=1,
        annual_metric_count=0,
        latest_snapshot_count=1,
        completed_at=dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc),
    )
    db.add(run)
    db.flush()
    return run


def _doc(db, run_id, *, fiscal_year: int, publication_date: dt.date, kind: str = "RFA") -> models.FundamentalSourceDocument:
    row = models.FundamentalSourceDocument(
        id=fiscal_year,
        import_id=run_id,
        symbol="AAA",
        company_name="Alpha",
        document_title=f"Rapport financier annuel {fiscal_year}",
        source_url=f"https://example.test/{fiscal_year}.pdf",
        document_kind=kind,
        publication_date=publication_date,
        fiscal_year=fiscal_year,
        period_type="annual",
        period_label="FY",
        status="succeeded",
        extracted_field_count=42,
        raw_json={},
    )
    db.add(row)
    db.flush()
    return row


def _period_metric(db, run_id, doc_id: int, metric: str, value: float, *, fiscal_year: int = 2024) -> None:
    db.add(
        models.FundamentalPeriodMetric(
            import_id=run_id,
            source_document_id=doc_id,
            symbol="AAA",
            company_name="Alpha",
            fiscal_year=fiscal_year,
            period_type="annual",
            period_label="FY",
            metric_name=metric,
            metric_value=value,
            raw_metric_name=f"{metric}_{fiscal_year}",
        )
    )


def test_bvc_period_sync_stamps_as_of_and_maps_cgnc_fields(session_factory) -> None:
    db = session_factory()
    try:
        run = _run(db)
        doc = _doc(db, run.id, fiscal_year=2024, publication_date=dt.date(2025, 3, 31))
        db.add(
            models.FundamentalLatestSnapshot(
                import_id=run.id,
                symbol="AAA",
                company_name="Alpha",
                latest_statement_year=2024,
                data_source="bvc",
                metrics_json={},
                scores_json={},
                diagnostics_json={},
                coverage_json={},
                model_eligibility_json={},
                source_json={},
            )
        )
        for metric, value in {
            "Chiffre_daffaires": 1_000.0,
            "Resultat_dexploitation": 150.0,
            "Dotations_dexploitation": 25.0,
            "Flux_de_tresorerie_lies_a_lactivite": 120.0,
            "Flux_de_tresorerie_lies_aux_investissements": -40.0,
            "Capitaux_propres": 500.0,
            "Dettes_de_financement": 180.0,
            "Tresorerie_Actif": 60.0,
            "Total_Passif": 900.0,
        }.items():
            _period_metric(db, run.id, int(doc.id), metric, value)
        db.commit()

        result = sync_bvc_period_metrics_to_annual_and_latest(db, import_id=run.id)
        db.commit()

        assert result["annual_inserted_count"] > 9
        revenue = (
            db.query(models.FundamentalAnnualMetric)
            .filter_by(import_id=run.id, symbol="AAA", statement_year=2024, metric_name="Revenue")
            .one()
        )
        assert revenue.metric_value == pytest.approx(1_000.0)
        assert revenue.as_of_date == dt.date(2025, 3, 31)
        assert revenue.source_document_id == doc.id
        ebitda = (
            db.query(models.FundamentalAnnualMetric)
            .filter_by(import_id=run.id, symbol="AAA", statement_year=2024, metric_name="EBITDA")
            .one()
        )
        assert ebitda.metric_value == pytest.approx(175.0)
        fcf = (
            db.query(models.FundamentalAnnualMetric)
            .filter_by(import_id=run.id, symbol="AAA", statement_year=2024, metric_name="Free_Cash_Flow")
            .one()
        )
        assert fcf.metric_value == pytest.approx(80.0)

        snapshot = db.query(models.FundamentalLatestSnapshot).filter_by(import_id=run.id, symbol="AAA").one()
        assert snapshot.as_of_date == dt.date(2025, 3, 31)
        assert snapshot.source_document_id == doc.id
        assert snapshot.metrics_json["Revenue"] == pytest.approx(1_000.0)
        assert snapshot.metrics_json["Free_Cash_Flow"] == pytest.approx(80.0)
        assert snapshot.diagnostics_json["statement_archetype"] == "cgnc_social"
    finally:
        db.close()


def test_bvc_period_sync_advances_latest_snapshot_to_newest_annual_year(session_factory) -> None:
    db = session_factory()
    try:
        run = _run(db)
        doc_2024 = _doc(db, run.id, fiscal_year=2024, publication_date=dt.date(2025, 3, 31))
        doc_2025 = _doc(db, run.id, fiscal_year=2025, publication_date=dt.date(2026, 3, 31))
        db.add(
            models.FundamentalLatestSnapshot(
                import_id=run.id,
                symbol="AAA",
                company_name="Alpha",
                latest_statement_year=2024,
                data_source="bvc",
                metrics_json={"Revenue": 900.0},
                scores_json={},
                diagnostics_json={},
                coverage_json={},
                model_eligibility_json={},
                source_json={},
            )
        )
        _period_metric(db, run.id, int(doc_2024.id), "Chiffre_daffaires", 1_000.0, fiscal_year=2024)
        _period_metric(db, run.id, int(doc_2025.id), "Chiffre_daffaires", 1_200.0, fiscal_year=2025)
        db.commit()

        result = sync_bvc_period_metrics_to_annual_and_latest(db, import_id=run.id)
        db.commit()

        assert result["latest_snapshot_updated_count"] == 1
        snapshot = db.query(models.FundamentalLatestSnapshot).filter_by(import_id=run.id, symbol="AAA").one()
        assert snapshot.latest_statement_year == 2025
        assert snapshot.metrics_json["Revenue"] == pytest.approx(1_200.0)
        assert snapshot.as_of_date == dt.date(2026, 3, 31)
        assert snapshot.coverage_json["cgnc_refreshed_latest_metric_count"] >= 1
    finally:
        db.close()


def test_get_snapshot_as_of_excludes_future_publication_rows(session_factory) -> None:
    db = session_factory()
    try:
        run = _run(db)
        doc_2024 = _doc(db, run.id, fiscal_year=2024, publication_date=dt.date(2025, 3, 31))
        doc_2025 = _doc(db, run.id, fiscal_year=2025, publication_date=dt.date(2026, 3, 31))
        db.add_all(
            [
                models.FundamentalAnnualMetric(
                    import_id=run.id,
                    symbol="AAA",
                    company_name="Alpha",
                    statement_year=2024,
                    metric_name="Revenue",
                    metric_value=1_000.0,
                    as_of_date=doc_2024.publication_date,
                    source_document_id=doc_2024.id,
                ),
                models.FundamentalAnnualMetric(
                    import_id=run.id,
                    symbol="AAA",
                    company_name="Alpha",
                    statement_year=2025,
                    metric_name="Revenue",
                    metric_value=1_200.0,
                    as_of_date=doc_2025.publication_date,
                    source_document_id=doc_2025.id,
                ),
            ]
        )
        db.commit()

        snapshot = get_snapshot_as_of(db, symbol="AAA", as_of=dt.date(2025, 12, 31), import_id=run.id)
        assert snapshot is not None
        assert snapshot.latest_statement_year == 2024
        assert snapshot.metrics["Revenue"] == pytest.approx(1_000.0)

        later = get_snapshot_as_of(db, symbol="AAA", as_of=dt.date(2026, 4, 1), import_id=run.id)
        assert later is not None
        assert later.latest_statement_year == 2025
        assert later.metrics["Revenue"] == pytest.approx(1_200.0)
    finally:
        db.close()
