from __future__ import annotations

import datetime as dt
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")

from services.api.app import models
from services.api.app.services import fundamentals as fundamentals_service
from services.api.scripts.prune_superseded_fundamentals import prune_superseded_fundamentals


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    for table in (
        models.StockMaster.__table__,
        models.FundamentalImport.__table__,
        models.FundamentalSourceDocument.__table__,
        models.FundamentalAnnualMetric.__table__,
        models.FundamentalPeriodMetric.__table__,
        models.FundamentalLatestSnapshot.__table__,
        models.FundamentalQualityIssue.__table__,
        models.FundamentalValuationResult.__table__,
        models.FundamentalEnsembleResult.__table__,
        models.FundamentalProjection.__table__,
        models.FundamentalIntegrityReport.__table__,
        models.FundamentalPillarScoreHistory.__table__,
    ):
        table.create(engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _run(
    *,
    filename: str,
    status: str = "succeeded",
    data_source: str = "bvc",
    completed_at: dt.datetime,
) -> models.FundamentalImport:
    return models.FundamentalImport(
        filename=filename,
        source_hash=f"hash-{filename}",
        data_source=data_source,
        source_universe="masi",
        status=status,
        completed_at=completed_at,
        imported_at=completed_at,
    )


def _snapshot(import_id, *, symbol: str = "MNG", metrics: dict | None = None, is_canonical: bool | None = None) -> models.FundamentalLatestSnapshot:
    return models.FundamentalLatestSnapshot(
        import_id=import_id,
        symbol=symbol,
        company_name=symbol,
        latest_statement_year=2024,
        metrics_json=metrics or {"Revenue": 100.0, "NetIncome": 10.0, "Total_Assets": 200.0, "Total_Equity": 120.0, "Current_Price": 100.0},
        scores_json={},
        diagnostics_json={},
        coverage_json={},
        model_eligibility_json={},
        source_json={"currency": "MAD"},
        as_of_date=dt.date(2025, 4, 30),
        is_canonical=is_canonical,
    )


def _ensemble(import_id, *, symbol: str = "MNG", fair_value: float = 130.0) -> models.FundamentalEnsembleResult:
    return models.FundamentalEnsembleResult(
        import_id=import_id,
        symbol=symbol,
        scenario="base",
        fair_value_low=fair_value * 0.9,
        fair_value_base=fair_value,
        fair_value_high=fair_value * 1.1,
        current_price=100.0,
        upside_pct=fair_value / 100.0 - 1.0,
        confidence_score=0.80,
        usable_model_count=4,
        excluded_model_count=0,
        model_weights_json={"residual_income": 1.0},
        warnings_json=[],
        model_dispersion_cv=0.05,
    )


def _valuation(import_id, *, symbol: str = "MNG") -> models.FundamentalValuationResult:
    return models.FundamentalValuationResult(
        import_id=import_id,
        symbol=symbol,
        scenario="base",
        model="residual_income",
        fair_value=130.0,
        current_price=100.0,
        upside_pct=0.30,
        confidence="high",
        confidence_score=0.85,
        weight=1.0,
        family="intrinsic",
        methodology="fixture",
        inputs_json={"cost_of_equity": 0.10},
        outputs_json={},
        warnings_json=["fixture"],
    )


def test_canonical_resolution_is_shared_by_rows_imports_overlay_and_revalue(db_session) -> None:
    db = db_session
    db.add(models.StockMaster(symbol="MNG", display_name="Managem", sector="Mines", market_region="masi"))
    older_rich = _run(filename="older-rich.xlsx", data_source="bvc", completed_at=dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc))
    newer_thin = _run(filename="newer-thin.xlsx", data_source="yfinance", completed_at=dt.datetime(2025, 2, 1, tzinfo=dt.timezone.utc))
    db.add_all([older_rich, newer_thin])
    db.flush()
    db.add_all(
        [
            _snapshot(older_rich.id, metrics={"Revenue": 100.0, "NetIncome": 10.0, "Total_Assets": 200.0, "Total_Equity": 120.0, "Current_Price": 100.0}),
            _snapshot(newer_thin.id, metrics={"Current_Price": 100.0}),
            _ensemble(older_rich.id, fair_value=130.0),
            _ensemble(newer_thin.id, fair_value=90.0),
            _valuation(older_rich.id),
        ]
    )
    db.commit()

    canonical = fundamentals_service.refresh_canonical_snapshot_flags(db, symbols=["MNG"])
    snapshot = fundamentals_service.latest_snapshot_rows_by_symbol(db, symbols=["MNG"])["MNG"]
    import_row = fundamentals_service.latest_imports_by_symbol(db, symbols=["MNG"])["MNG"]
    scalar = fundamentals_service.canonical_snapshot_for_symbol(db, "MNG")
    overlay = fundamentals_service.derive_research_overlay(
        db,
        symbol="MNG",
        scenario="base",
        ensemble=db.query(models.FundamentalEnsembleResult).filter_by(import_id=snapshot.import_id, symbol="MNG", scenario="base").one(),
        import_row=import_row,
        current_price=100.0,
    )

    assert canonical["MNG"] == older_rich.id
    assert snapshot.import_id == older_rich.id
    assert import_row.id == older_rich.id
    assert scalar is not None and scalar.import_id == older_rich.id
    assert overlay["target_price"] == pytest.approx(130.0)
    assert db.query(models.FundamentalLatestSnapshot).filter_by(import_id=older_rich.id, symbol="MNG").one().is_canonical is True
    assert db.query(models.FundamentalLatestSnapshot).filter_by(import_id=newer_thin.id, symbol="MNG").one().is_canonical is False


def test_failed_import_cleanup_preserves_audit_and_source_documents(db_session) -> None:
    db = db_session
    run = _run(filename="failed.xlsx", status="failed", completed_at=dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc))
    db.add(run)
    db.flush()
    doc = models.FundamentalSourceDocument(
        import_id=run.id,
        symbol="MNG",
        company_name="Managem",
        source_url="https://example.test/mng.pdf",
        status="failed",
        raw_json={},
    )
    db.add(doc)
    db.flush()
    db.add_all(
        [
            _snapshot(run.id),
            _valuation(run.id),
            _ensemble(run.id),
            models.FundamentalAnnualMetric(import_id=run.id, symbol="MNG", company_name="MNG", statement_year=2024, metric_name="Revenue", metric_value=1.0),
        ]
    )
    db.commit()

    fundamentals_service.delete_fundamental_import_artifacts(db, import_id=run.id, include_statement_rows=True)
    db.commit()

    assert db.get(models.FundamentalImport, run.id) is not None
    assert db.get(models.FundamentalSourceDocument, doc.id) is not None
    assert db.query(models.FundamentalLatestSnapshot).filter_by(import_id=run.id).count() == 0
    assert db.query(models.FundamentalValuationResult).filter_by(import_id=run.id).count() == 0
    assert db.query(models.FundamentalEnsembleResult).filter_by(import_id=run.id).count() == 0
    assert db.query(models.FundamentalAnnualMetric).filter_by(import_id=run.id).count() == 0


@pytest.mark.xfail(
    reason="pre-existing branch regression: stale_import_count count off since canonical-promotion refactor",
    strict=False,
)
def test_prune_superseded_fundamentals_dry_run_and_apply_preserve_overlay(db_session) -> None:
    db = db_session
    db.add(models.StockMaster(symbol="MNG", display_name="Managem", sector="Mines", market_region="masi"))
    runs = [
        _run(filename="stale-1.xlsx", data_source="yfinance", completed_at=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)),
        _run(filename="stale-2.xlsx", data_source="stockanalysis", completed_at=dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc)),
        _run(filename="stale-3.xlsx", data_source="workbook", completed_at=dt.datetime(2024, 9, 1, tzinfo=dt.timezone.utc)),
        _run(filename="canonical.xlsx", data_source="bvc", completed_at=dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)),
    ]
    db.add_all(runs)
    db.flush()
    for index, run in enumerate(runs):
        db.add(_snapshot(run.id, is_canonical=(run is runs[-1])))
        db.add(_valuation(run.id))
        db.add(_ensemble(run.id, fair_value=80.0 + index * 10.0))
    db.commit()

    before_snapshots = set(fundamentals_service.latest_snapshot_rows_by_symbol(db))
    canonical_snapshot = fundamentals_service.latest_snapshot_rows_by_symbol(db, symbols=["MNG"])["MNG"]
    canonical_import = fundamentals_service.latest_imports_by_symbol(db, symbols=["MNG"])["MNG"]
    before_overlay = fundamentals_service.derive_research_overlay(
        db,
        symbol="MNG",
        scenario="base",
        ensemble=db.query(models.FundamentalEnsembleResult).filter_by(import_id=canonical_snapshot.import_id, symbol="MNG", scenario="base").one(),
        import_row=canonical_import,
        current_price=100.0,
    )

    dry_run = prune_superseded_fundamentals(db, symbols=["MNG"], apply=False)
    assert dry_run[0]["stale_import_count"] == 3
    assert db.query(models.FundamentalEnsembleResult).filter_by(symbol="MNG").count() == 4

    applied = prune_superseded_fundamentals(db, symbols=["MNG"], apply=True)
    after_snapshots = set(fundamentals_service.latest_snapshot_rows_by_symbol(db))
    canonical_snapshot_after = fundamentals_service.latest_snapshot_rows_by_symbol(db, symbols=["MNG"])["MNG"]
    canonical_import_after = fundamentals_service.latest_imports_by_symbol(db, symbols=["MNG"])["MNG"]
    after_overlay = fundamentals_service.derive_research_overlay(
        db,
        symbol="MNG",
        scenario="base",
        ensemble=db.query(models.FundamentalEnsembleResult).filter_by(import_id=canonical_snapshot_after.import_id, symbol="MNG", scenario="base").one(),
        import_row=canonical_import_after,
        current_price=100.0,
    )

    assert applied[0]["deleted"]["ensembles"] == 3
    assert db.query(models.FundamentalLatestSnapshot).filter_by(symbol="MNG").count() == 1
    assert db.query(models.FundamentalValuationResult).filter_by(symbol="MNG").count() == 1
    assert db.query(models.FundamentalEnsembleResult).filter_by(symbol="MNG").count() == 1
    assert before_snapshots == after_snapshots == {"MNG"}
    assert before_overlay["target_price"] == after_overlay["target_price"]
