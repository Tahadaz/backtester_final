from __future__ import annotations

import datetime as dt
import json
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")
os.environ["FUNDAMENTAL_DISABLE_LIVE_QUOTES"] = "1"

from services.api.app import models
from services.api.app.services import fundamentals as fundamentals_service
from services.api.scripts.remediate_fundamentals import (
    _proof_rows_and_provenance,
    apply_fy2025_reingestion,
    load_fy2025_proof_artifacts,
    remediate_fundamentals,
)


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
        models.Dataset.__table__,
        models.StockMaster.__table__,
        models.MarketDataStore.__table__,
        models.FundamentalImport.__table__,
        models.FundamentalSourceDocument.__table__,
        models.FundamentalAnnualMetric.__table__,
        models.FundamentalPeriodMetric.__table__,
        models.FundamentalLatestSnapshot.__table__,
        models.FundamentalValuationResult.__table__,
        models.FundamentalEnsembleResult.__table__,
        models.FundamentalProjection.__table__,
        models.FundamentalIntegrityReport.__table__,
        models.FundamentalAssumptionOverride.__table__,
        models.FundamentalDataVerification.__table__,
    ):
        table.create(engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _run(filename: str = "brief38.xlsx") -> models.FundamentalImport:
    when = dt.datetime(2026, 4, 30, tzinfo=dt.timezone.utc)
    return models.FundamentalImport(
        filename=filename,
        source_hash=f"hash-{filename}",
        data_source="bvc",
        source_universe="masi",
        status="succeeded",
        completed_at=when,
        imported_at=when,
    )


def _snapshot(import_id, *, symbol: str, metrics: dict[str, float]) -> models.FundamentalLatestSnapshot:
    return models.FundamentalLatestSnapshot(
        import_id=import_id,
        symbol=symbol,
        company_name=symbol,
        latest_statement_year=2025,
        data_source="bvc",
        metrics_json=metrics,
        scores_json={},
        diagnostics_json={},
        coverage_json={},
        model_eligibility_json={},
        source_json={"currency": "MAD"},
        as_of_date=dt.date(2026, 4, 30),
        is_canonical=True,
    )


def _annual(db, import_id, symbol: str, metric: str, value: float) -> None:
    db.add(
        models.FundamentalAnnualMetric(
            import_id=import_id,
            symbol=symbol,
            company_name=symbol,
            statement_year=2025,
            metric_name=metric,
            metric_value=value,
            raw_metric_name=metric,
            source_sheet="fixture",
        )
    )


def test_remediation_persists_curated_lhm_correction_and_verified_status(db_session) -> None:
    db = db_session
    db.add(models.StockMaster(symbol="LHM", display_name="LafargeHolcim Maroc", sector="Ciment", market_region="masi", shares_outstanding=23_431_240))
    run = _run()
    db.add(run)
    db.flush()
    db.add_all(
        [
            models.FundamentalSourceDocument(
                import_id=run.id,
                symbol="LHM",
                company_name="LHM",
                document_title="LafargeHolcim Maroc - Resultats financiers 2025 et CP RFA 2025",
                source_url="https://media.casablanca-bourse.com/sites/default/files/2026-04/lafargeholcim_maroc_2025.pdf",
                document_kind="RFA",
                fiscal_year=2025,
                period_type="annual",
                status="processed",
                raw_json={},
            ),
            models.FundamentalSourceDocument(
                import_id=run.id,
                symbol="LHM",
                company_name="LHM",
                document_title="StockAnalysis supplemental three-statement data for LHM",
                source_url="https://stockanalysis.com/quote/cbse/LHM/financials/",
                document_kind="stockanalysis",
                fiscal_year=2025,
                period_type="annual",
                status="processed",
                raw_json={},
            ),
        ]
    )
    bad_metrics = {
        "Total_Assets": 994_546_000.0,
        "Total_Liabilities": 7_838_000_000.0,
        "Total_Liabilities_And_Equity": 19_995_000_000.0,
        "Total_Equity": 156_299_000.0,
        "Equity_Group": 156_299_000.0,
        "Shares_Outstanding": 23_431_240.0,
        "Resultat_net": 2_165_873_000.0,
        "Resultat_net_part_du_groupe": 2_165_873_000.0,
        "ROE": 13.857,
        "Current_Price": 1420.0,
    }
    db.add(_snapshot(run.id, symbol="LHM", metrics=bad_metrics))
    for metric, value in bad_metrics.items():
        _annual(db, run.id, "LHM", metric, value)
    db.commit()

    dry_run = remediate_fundamentals(db, symbols=["LHM"], apply=False)
    assert dry_run[0]["status"] == "verified"
    assert db.query(models.FundamentalDataVerification).count() == 0

    applied = remediate_fundamentals(db, symbols=["LHM"], apply=True)
    assert applied[0]["status"] == "verified"
    row = db.query(models.FundamentalDataVerification).filter_by(symbol="LHM").one()
    assert row.status == "verified"
    assert row.stockanalysis_json["covered"] is True
    corrected = db.query(models.FundamentalAnnualMetric).filter_by(symbol="LHM", metric_name="Total_Equity").one()
    assert corrected.metric_value == pytest.approx(12_156_299_000.0)
    assert corrected.source_sheet == "brief38_curated"


def test_data_unverified_verification_gates_recompute_to_nr(db_session) -> None:
    db = db_session
    db.add(models.StockMaster(symbol="STR", display_name="Stroc Industrie", sector="Industrie", market_region="masi", shares_outstanding=1_248_515))
    run = _run("str.xlsx")
    db.add(run)
    db.flush()
    metrics = {"Shares_Outstanding": 1_248_515.0, "Resultat_net": 500_000.0, "Current_Price": 30.0}
    db.add(_snapshot(run.id, symbol="STR", metrics=metrics))
    db.add(
        models.FundamentalDataVerification(
            import_id=run.id,
            symbol="STR",
            statement_year=2025,
            status="data_unverified",
            reason="official_document_missing_balance_sheet_tieout_lines_for_current_snapshot",
            failed_checks_json=["t1_balance_sheet", "t2_equity_per_share"],
            warnings_json=[],
            offending_metrics_json={},
            recomputed_metrics_json={},
            corrections_json={},
            provenance_json={},
            source_urls_json=[],
            stockanalysis_json={},
            tieout_report_json={},
        )
    )
    db.commit()

    rows = fundamentals_service.recompute_symbol_valuations_all_scenarios(db, import_id=run.id, symbol="STR")
    db.commit()

    assert rows
    assert {row.scenario for row in rows} == {"bear", "base", "bull"}
    assert all(row.fair_value is None for row in rows)
    assert all(row.confidence == "unavailable" for row in rows)
    assert all(any(str(w).startswith("data_unverified_nr") for w in row.warnings_json) for row in rows)
    ensembles = db.query(models.FundamentalEnsembleResult).filter_by(symbol="STR").all()
    assert {row.scenario for row in ensembles} == {"bear", "base", "bull"}
    assert all(row.fair_value_base is None for row in ensembles)
    assert all(fundamentals_service.derive_recommendation(row, current_price=30.0) == "NR" for row in ensembles)


def test_recompute_auto_computes_verification_when_absent(db_session) -> None:
    """No pre-existing verification row → recompute auto-computes tieout → NR when data fails T1."""
    db = db_session
    db.add(models.StockMaster(symbol="MNG", display_name="Managem", sector="Mines", market_region="masi"))
    run = _run("mng.xlsx")
    db.add(run)
    db.flush()
    # Misbalanced sheet: assets 1M != liabilities 300k + equity 200k → T1 fails (40% gap)
    bad_metrics = {
        "Total_Assets": 1_000_000.0,
        "Total_Liabilities": 300_000.0,
        "Total_Equity": 200_000.0,
        "Current_Price": 100.0,
        "Shares_Outstanding": 10_000.0,
    }
    db.add(_snapshot(run.id, symbol="MNG", metrics=bad_metrics))
    for metric, value in bad_metrics.items():
        _annual(db, run.id, "MNG", metric, value)
    db.commit()

    assert db.query(models.FundamentalDataVerification).count() == 0

    rows = fundamentals_service.recompute_symbol_valuations(db, import_id=run.id, symbol="MNG", scenario="base")
    db.flush()

    verif = db.query(models.FundamentalDataVerification).filter_by(symbol="MNG").one_or_none()
    assert verif is not None, "auto-compute must create a FundamentalDataVerification row"
    assert verif.status == "data_unverified"

    assert rows
    assert all(row.fair_value is None for row in rows)
    ensemble = db.query(models.FundamentalEnsembleResult).filter_by(symbol="MNG", scenario="base").one_or_none()
    assert ensemble is not None
    assert ensemble.fair_value_base is None
    assert any("data_unverified_nr" in str(w) for w in (ensemble.warnings_json or []))


def test_curated_verification_not_overwritten_by_recompute(db_session) -> None:
    """Curated row (non-empty corrections_json) must not be touched by auto-recompute.

    We use status=data_unverified with corrections so the function exits via the NR
    path (avoids needing the full valuation DB schema) while still proving the guard.
    """
    db = db_session
    db.add(models.StockMaster(symbol="MNG", display_name="Managem", sector="Mines", market_region="masi"))
    run = _run("mng2.xlsx")
    db.add(run)
    db.flush()
    bad_metrics = {
        "Total_Assets": 1_000_000.0,
        "Total_Liabilities": 300_000.0,
        "Total_Equity": 200_000.0,
        "Current_Price": 100.0,
        "Shares_Outstanding": 10_000.0,
    }
    db.add(_snapshot(run.id, symbol="MNG", metrics=bad_metrics))
    for metric, value in bad_metrics.items():
        _annual(db, run.id, "MNG", metric, value)
    db.add(
        models.FundamentalDataVerification(
            import_id=run.id,
            symbol="MNG",
            statement_year=2025,
            status="data_unverified",
            reason="curated_official_document_correction",
            failed_checks_json=["t1_balance_sheet"],
            warnings_json=[],
            offending_metrics_json={},
            recomputed_metrics_json={},
            corrections_json={"Total_Equity": "curated_correction"},
            provenance_json={},
            source_urls_json=[],
            stockanalysis_json={},
            tieout_report_json={},
        )
    )
    db.commit()

    fundamentals_service.recompute_symbol_valuations(db, import_id=run.id, symbol="MNG", scenario="base")
    db.flush()

    verif = db.query(models.FundamentalDataVerification).filter_by(symbol="MNG").one()
    assert verif.status == "data_unverified", "curated verdict must be unchanged"
    assert verif.reason == "curated_official_document_correction", "curated reason must be intact"
    assert "Total_Equity" in (verif.corrections_json or {}), "corrections_json must be intact"


def test_remediation_no_minority_basis_verifies_without_group_lines(db_session) -> None:
    db = db_session
    run = _run("no-minority.xlsx")
    db.add(run)
    db.flush()
    metrics = {
        "Total_Assets": 1_000.0,
        "Total_Liabilities": 600.0,
        "Total_Liabilities_And_Equity": 1_000.0,
        "Total_Equity": 400.0,
        "Shares_Outstanding": 10.0,
        "Resultat_net": 40.0,
        "NetIncome": 40.0,
        "Current_Price": 80.0,
    }
    db.add(_snapshot(run.id, symbol="NMI", metrics=metrics))
    for metric, value in metrics.items():
        _annual(db, run.id, "NMI", metric, value)
    db.commit()

    applied = remediate_fundamentals(db, symbols=["NMI"], apply=True)

    assert applied[0]["status"] == "verified"
    row = db.query(models.FundamentalDataVerification).filter_by(symbol="NMI").one()
    assert row.status == "verified"
    assert row.recomputed_metrics_json["ROE"] == pytest.approx(0.10)
    assert row.recomputed_metrics_json["t4_basis"] == "no_minority_total_equity"


def test_fy2025_proof_artifact_loader_keeps_cited_observed_figures(tmp_path) -> None:
    proof_dir = tmp_path / "fy2025"
    proof_dir.mkdir()
    url = "https://media.casablanca-bourse.com/sites/default/files/2026-03/test_2025.pdf"
    (proof_dir / "TST.json").write_text(
        """
{
  "symbol": "TST",
  "fiscal_year": 2025,
  "source_documents": [{"source_url": "https://media.casablanca-bourse.com/sites/default/files/2026-03/test_2025.pdf"}],
  "figures": {
    "Total_Assets": {
      "metric_name": "Total_Assets",
      "status": "observed",
      "value": 1000,
      "reported_value": "1 000",
      "unit": "MAD",
      "source_url": "https://media.casablanca-bourse.com/sites/default/files/2026-03/test_2025.pdf",
      "page": 4,
      "line": "table-row",
      "verbatim_label": "Total actif"
    },
    "Equity_Group": {
      "metric_name": "Equity_Group",
      "status": "unavailable",
      "reason": "line_not_disclosed_in_examined_fy2025_filing",
      "source_url": "https://media.casablanca-bourse.com/sites/default/files/2026-03/test_2025.pdf",
      "page": 4,
      "line": "table-row",
      "verbatim_label": "Capitaux propres part du groupe line absent in the cited statement section"
    }
  }
}
""",
        encoding="utf-8",
    )

    artifacts = load_fy2025_proof_artifacts(proof_dir=proof_dir)
    rows, provenance, figure_map = _proof_rows_and_provenance(artifacts["TST"])

    assert rows == {"Total_Assets": 1000.0}
    assert "Equity_Group" not in rows
    assert provenance["Total_Assets"]["source_url"] == url
    assert provenance["Total_Assets"]["page"] == 4
    assert provenance["Total_Assets"]["label"] == "Total actif"
    assert figure_map["Total_Assets"]["reported_value"] == "1 000"


def test_fy2025_reingestion_replaces_canonical_year_with_proof_set(db_session, tmp_path) -> None:
    db = db_session
    proof_dir = tmp_path / "fy2025"
    proof_dir.mkdir()
    url = "https://media.casablanca-bourse.com/sites/default/files/2026-03/b42_2025.pdf"
    figures = {
        "Total_Assets": 1000.0,
        "Total_Liabilities_And_Equity": 1000.0,
        "Total_Equity": 400.0,
        "Equity_Group": 400.0,
        "Minority_Interest": 0.0,
        "Shares_Outstanding": 10.0,
        "Revenue": 500.0,
        "Operating_Income": 70.0,
        "Resultat_net": 40.0,
        "Resultat_net_part_du_groupe": 40.0,
        "Dividend_Per_Share": 1.0,
    }
    artifact_figures = {
        metric: {
            "metric_name": metric,
            "status": "observed",
            "value": value,
            "reported_value": str(value),
            "unit": "MAD",
            "source_url": url,
            "page": 6,
            "line": "table-row",
            "verbatim_label": metric,
        }
        for metric, value in figures.items()
    }
    (proof_dir / "B42.json").write_text(
        json.dumps(
            {
                "symbol": "B42",
                "fiscal_year": 2025,
                "source_documents": [{"source_url": url, "document_title": "B42 FY2025 official filing"}],
                "figures": artifact_figures,
            }
        ),
        encoding="utf-8",
    )

    db.add(models.StockMaster(symbol="B42", display_name="Brief 42", sector="Industrie", market_region="masi", shares_outstanding=10))
    run = _run("brief42.xlsx")
    db.add(run)
    db.flush()
    db.add(_snapshot(run.id, symbol="B42", metrics={"Current_Price": 25.0, "Revenue": 9999.0}))
    _annual(db, run.id, "B42", "Revenue", 9999.0)
    _annual(db, run.id, "B42", "Uncited_Old_Metric", 123.0)
    db.commit()

    rows = apply_fy2025_reingestion(db, symbols=["B42"], apply=True, proof_dir=proof_dir)

    assert rows[0]["status"] == "verified"
    snapshot = db.query(models.FundamentalLatestSnapshot).filter_by(symbol="B42").one()
    assert snapshot.latest_statement_year == 2025
    assert snapshot.metrics_json["Revenue"] == pytest.approx(500.0)
    assert snapshot.metrics_json["Current_Price"] == pytest.approx(25.0)
    assert "Uncited_Old_Metric" not in snapshot.metrics_json
    metric_names = {
        row.metric_name: row
        for row in db.query(models.FundamentalAnnualMetric).filter_by(symbol="B42", statement_year=2025).all()
    }
    assert "Uncited_Old_Metric" not in metric_names
    assert metric_names["Revenue"].metric_value == pytest.approx(500.0)
    assert metric_names["Revenue"].source_sheet == "brief42_fy2025_proof"
    verification = db.query(models.FundamentalDataVerification).filter_by(symbol="B42").one()
    assert verification.status == "verified"
    assert verification.source_urls_json == [url]


def test_canonical_resolver_prefers_brief42_verified_snapshot_over_partial_recency(db_session) -> None:
    db = db_session
    db.add(models.StockMaster(symbol="CAN", display_name="Canonical", sector="Industrie", market_region="masi", shares_outstanding=10))
    proof_run = _run("proof.xlsx")
    partial_run = _run("partial.xlsx")
    partial_run.completed_at = proof_run.completed_at + dt.timedelta(days=1)
    partial_run.imported_at = proof_run.imported_at + dt.timedelta(days=1)
    db.add_all([proof_run, partial_run])
    db.flush()
    proof_snapshot = _snapshot(
        proof_run.id,
        symbol="CAN",
        metrics={
            "Total_Assets": 1000.0,
            "Total_Equity": 400.0,
            "Revenue": 500.0,
        },
    )
    proof_snapshot.source_json = {"brief42_fy2025_reingestion": {"artifact": "data/corrections/fy2025/CAN.json"}}
    proof_snapshot.coverage_json = {"data_verification": {"status": "verified", "reason": None}}
    partial_snapshot = _snapshot(
        partial_run.id,
        symbol="CAN",
        metrics={
            "Total_Assets": 1200.0,
            "Total_Equity": 410.0,
            "Revenue": 510.0,
        },
    )
    partial_snapshot.is_canonical = False
    db.add_all([proof_snapshot, partial_snapshot])
    db.commit()

    canonical = fundamentals_service.refresh_canonical_snapshot_flags(db, symbols=["CAN"])

    assert canonical["CAN"] == proof_run.id
    assert fundamentals_service.latest_snapshot_rows_by_symbol(db, symbols=["CAN"])["CAN"].import_id == proof_run.id
