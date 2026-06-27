from __future__ import annotations

import datetime as dt

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.quant_core.fundamentals.domain import IntegrityReport
from services.api.app import models
from services.api.app.services.fundamentals import _load_history, source_integrity_report_for_history


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


def _session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    for table in (
        models.FundamentalImport.__table__,
        models.FundamentalAnnualMetric.__table__,
    ):
        table.create(engine)
    return SessionLocal()


def _run(*, filename: str, status: str = "succeeded") -> models.FundamentalImport:
    return models.FundamentalImport(
        filename=filename,
        source_hash=filename,
        status=status,
        company_count=1,
        symbol_count=1,
        annual_metric_count=0,
        latest_snapshot_count=0,
        completed_at=dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc),
    )


def _metric(import_id, year: int, name: str, value: float, *, source: str = "bvc_jsonl") -> models.FundamentalAnnualMetric:
    return models.FundamentalAnnualMetric(
        import_id=import_id,
        symbol="MNG",
        company_name="Managem",
        statement_year=year,
        metric_name=name,
        metric_value=value,
        raw_metric_name=name,
        source_sheet=source,
        as_of_date=dt.date(year + 1, 4, 30),
    )


def test_history_repairs_prior_dividends_and_supplemental_liability_imbalance() -> None:
    db = _session()
    try:
        current = _run(filename="current")
        prior = _run(filename="prior")
        db.add_all([current, prior])
        db.flush()
        db.add_all(
            [
                _metric(current.id, 2025, "Total_Assets", 1_000.0),
                _metric(current.id, 2025, "Total_Equity", 400.0),
                _metric(current.id, 2025, "Total_Liabilities", 550.0, source="stockanalysis_supplement"),
                _metric(current.id, 2025, "Cash", 100.0),
                _metric(current.id, 2025, "CFS_Ending_Cash", 100.0),
                _metric(current.id, 2025, "NetIncome", 100.0),
                _metric(prior.id, 2025, "Dividendes", 40.0, source="stockanalysis"),
                _metric(prior.id, 2025, "Clean_Dividendes", 40.0, source="stockanalysis"),
                _metric(prior.id, 2025, "Dividend_Per_Share", 4.0, source="stockanalysis"),
            ]
        )
        db.commit()

        history = _load_history(db, current.id, "MNG")

        liabilities = [row for row in history if row.statement_year == 2025 and row.metric_name == "Total_Liabilities"]
        assert liabilities[-1].metric_value == 600.0
        assert liabilities[-1].raw_metric_name == "derived:assets_minus_equity"
        assert any(row.metric_name == "Dividendes" and row.metric_value == 40.0 for row in history)

        stale = IntegrityReport(symbol="MNG", statement_year=2025, checks=[], overall_status="fail", confidence_haircut=0.3)
        rebuilt = source_integrity_report_for_history(stale, history=history, symbol="MNG", statement_year=2025)

        assert rebuilt is not None
        assert rebuilt.overall_status == "pass"
        assert [check.name for check in rebuilt.checks] == ["bs_balance", "cash_tie_out", "ni_link"]
    finally:
        db.close()
