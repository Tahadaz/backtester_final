from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.worker.tasks.targeted_bvc_fundamentals import (
    _persist_bvc_lineage,
    _matches_period,
    _normalize_period_types,
    _period_metric_models_from_result_row,
    _row_matches_terms,
    _symbol_for_result_row,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


def test_bvc_financial_results_unknown_period_is_treated_as_annual() -> None:
    row = {
        "Company": "MANAGEM",
        "Document_Title": "Managem - CP relatif aux resultats financiers 2025",
        "Source_URL": "https://media.casablanca-bourse.com/sites/default/files/2026-03/cp_managem_2025.pdf",
        "Period_Type": "unknown",
        "Period_Label": "",
        "Fiscal_Year": 2025,
        "Chiffre_daffaires_2025": 13_694_000_000.0,
        "Resultat_net_2025": 3_002_000_000.0,
    }

    assert _matches_period(row, ["annual"], [2025])

    metrics = _period_metric_models_from_result_row(
        row,
        import_id=uuid.uuid4(),
        source_document_id=1,
        symbol="MNG",
    )

    assert {metric.metric_name for metric in metrics} == {"Chiffre_daffaires", "Resultat_net"}
    assert {metric.period_type for metric in metrics} == {"annual"}
    assert {metric.period_label for metric in metrics} == {"FY"}


def test_bvc_period_defaults_and_quarterly_label_from_title() -> None:
    assert _normalize_period_types(None) == ["annual", "semiannual", "quarterly"]
    assert _normalize_period_types([]) == ["annual", "semiannual", "quarterly"]
    assert _normalize_period_types(["semester", "quarterly"]) == ["semiannual", "quarterly"]
    assert _normalize_period_types(["interim"]) == ["semiannual", "quarterly"]
    assert _normalize_period_types(["semestriel", "trimestriel"]) == ["semiannual", "quarterly"]

    row = {
        "Company": "MANAGEM",
        "Document_Title": "Managem : CP relatif aux indicateurs du 4eme trimestre 2025",
        "Source_URL": "https://media.casablanca-bourse.com/sites/default/files/2026-02/cp_managem_t4_25.pdf",
        "Period_Type": "quarterly",
        "Period_Label": "Q2",
        "Fiscal_Year": 2025,
        "Chiffre_daffaires_2025": 13_694_000_000.0,
    }

    assert _matches_period(row, ["quarterly"], [2025])
    metrics = _period_metric_models_from_result_row(
        row,
        import_id=uuid.uuid4(),
        source_document_id=1,
        symbol="MNG",
    )

    assert {metric.period_type for metric in metrics} == {"quarterly"}
    assert {metric.period_label for metric in metrics} == {"Q4"}


def test_bvc_period_metrics_derive_free_cash_flow_from_operating_cash_flow_and_capex() -> None:
    row = {
        "Company": "MANAGEM",
        "Document_Title": "Managem: document de reference relatif a l'exercice 2022 et au 1er semestre 2023",
        "Source_URL": "https://media.casablanca-bourse.com/sites/default/files/2024-03/dr_managem_002_2024_3.pdf",
        "Period_Type": "semiannual",
        "Period_Label": "S1",
        "Fiscal_Year": 2023,
        "Flux_tresorerie_activites_operationnelles_2023": 1_418_000_000.0,
        "Flux_tresorerie_investissement_CAPEX_2023": -1_880_000_000.0,
    }

    metrics = _period_metric_models_from_result_row(
        row,
        import_id=uuid.uuid4(),
        source_document_id=1,
        symbol="MNG",
    )
    by_metric = {metric.metric_name: metric for metric in metrics}

    assert by_metric["Free_Cash_Flow"].metric_value == -462_000_000.0
    assert by_metric["Free_Cash_Flow"].raw_metric_name == "derived:cfo_minus_capex:2023"
    assert by_metric["Free_Cash_Flow"].is_proxy is True


def test_bvc_lineage_reuses_source_document_for_duplicate_urls(monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    for table in (
        models.FundamentalImport.__table__,
        models.FundamentalSourceDocument.__table__,
        models.FundamentalPeriodMetric.__table__,
    ):
        table.create(engine)
    db = SessionLocal()
    try:
        run = models.FundamentalImport(
            filename="bvc.jsonl",
            source_hash="hash",
            data_source="bvc",
            status="running",
        )
        db.add(run)
        db.flush()
        rows = [
            {
                "Company": "MANAGEM",
                "Document_Title": "Managem : Resultats financiers 2024 et CP RFA 2024",
                "Source_URL": "https://media.casablanca-bourse.com/managem_2024.pdf",
                "Publication_Date": "2025-04-30",
                "Period_Type": "annual",
                "Period_Label": "FY",
                "Fiscal_Year": 2024,
                "Chiffre_daffaires_2024": 8_859_400_000.0,
                "Status": "SUCCESS",
                "Extracted_Field_Count": 20,
            },
            {
                "Company": "MANAGEM",
                "Document_Title": "Managem : Resultats financiers 2024 et CP RFA 2024",
                "Source_URL": "https://media.casablanca-bourse.com/managem_2024.pdf",
                "Publication_Date": "2025-04-30",
                "Period_Type": "annual",
                "Period_Label": "FY",
                "Fiscal_Year": 2024,
                "Resultat_net_2024": 619_800_000.0,
                "Status": "SUCCESS",
                "Extracted_Field_Count": 20,
            },
        ]
        monkeypatch.setattr(
            "services.worker.tasks.targeted_bvc_fundamentals._load_bvc_jsonl_rows",
            lambda _path: rows,
        )

        document_count, metric_count = _persist_bvc_lineage(
            db,
            import_id=run.id,
            symbols=["MNG"],
            stocks={},
            company_terms={"MNG": ["MANAGEM"]},
            source_urls=[],
            period_types=["annual"],
            years=[2024],
        )

        assert document_count == 1
        assert metric_count == 2
        assert db.query(models.FundamentalSourceDocument).count() == 1
        assert db.query(models.FundamentalPeriodMetric).count() == 2
    finally:
        db.close()
        engine.dispose()


def test_bvc_lineage_keeps_shared_url_documents_isolated_by_symbol(monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    for table in (
        models.FundamentalImport.__table__,
        models.FundamentalSourceDocument.__table__,
        models.FundamentalPeriodMetric.__table__,
    ):
        table.create(engine)
    db = SessionLocal()
    try:
        run = models.FundamentalImport(
            filename="bvc.jsonl",
            source_hash="hash",
            data_source="bvc",
            status="running",
        )
        db.add(run)
        db.flush()
        rows = [
            {
                "Company": "ALPHA",
                "Document_Title": "Alpha : Resultats financiers 2024",
                "Source_URL": "https://media.casablanca-bourse.com/shared.pdf",
                "Publication_Date": "2025-04-30",
                "Period_Type": "annual",
                "Period_Label": "FY",
                "Fiscal_Year": 2024,
                "Chiffre_daffaires_2024": 100.0,
                "Status": "SUCCESS",
                "Extracted_Field_Count": 1,
            },
            {
                "Company": "BETA",
                "Document_Title": "Beta : Resultats financiers 2024",
                "Source_URL": "https://media.casablanca-bourse.com/shared.pdf",
                "Publication_Date": "2025-04-30",
                "Period_Type": "annual",
                "Period_Label": "FY",
                "Fiscal_Year": 2024,
                "Chiffre_daffaires_2024": 200.0,
                "Status": "SUCCESS",
                "Extracted_Field_Count": 1,
            },
        ]
        monkeypatch.setattr(
            "services.worker.tasks.targeted_bvc_fundamentals._load_bvc_jsonl_rows",
            lambda _path: rows,
        )

        document_count, metric_count = _persist_bvc_lineage(
            db,
            import_id=run.id,
            symbols=["AAA", "BBB"],
            stocks={},
            company_terms={"AAA": ["ALPHA"], "BBB": ["BETA"]},
            source_urls=[],
            period_types=["annual"],
            years=[2024],
        )

        assert document_count == 2
        assert metric_count == 2
        documents = db.query(models.FundamentalSourceDocument).order_by(models.FundamentalSourceDocument.symbol).all()
        assert [document.symbol for document in documents] == ["AAA", "BBB"]
        metrics = db.query(models.FundamentalPeriodMetric).order_by(models.FundamentalPeriodMetric.symbol).all()
        assert metrics[0].source_document_id != metrics[1].source_document_id
    finally:
        db.close()
        engine.dispose()


def test_bvc_symbol_matching_uses_document_title_when_company_is_unknown() -> None:
    row = {
        "Company": "UNKNOWN_TICKER",
        "Document_Title": "MNG: Rapport financier annuel 2022",
        "Source_URL": "https://media.casablanca-bourse.com/sites/default/files/2023-08/managem_rfa_2022.pdf",
    }

    assert _symbol_for_result_row(
        row,
        stocks={},
        company_terms={"MNG": ["MNG", "MANAGEM"]},
    ) == "MNG"


def test_bvc_symbol_matching_does_not_match_short_ticker_inside_company_word() -> None:
    assert not _row_matches_terms(
        "TRAVAUX GENERAUX DE CONSTRUCTION DE CASABLANCA",
        "",
        ["STR", "STROC INDUSTRIE"],
    )

    row = {
        "Company": "TRAVAUX GENERAUX DE CONSTRUCTION DE CASABLANCA",
        "Document_Title": "TGCC - Resultats financiers 2025 et CP RFA 2025",
        "Source_URL": "https://media.casablanca-bourse.com/sites/default/files/2026-05/tgcc_2025.pdf",
    }

    assert _symbol_for_result_row(
        row,
        stocks={"STR": object()},
        company_terms={"STR": ["STR", "STROC INDUSTRIE"]},
    ) is None


def test_bvc_symbol_matching_rejects_ticker_when_document_evidence_conflicts() -> None:
    row = {
        "Ticker": "STR",
        "Company": "TRAVAUX GENERAUX DE CONSTRUCTION DE CASABLANCA",
        "Document_Title": "TGCC - Resultats financiers 2025 et CP RFA 2025",
        "Source_URL": "https://media.casablanca-bourse.com/sites/default/files/2026-05/tgcc_2025.pdf",
    }

    assert _symbol_for_result_row(
        row,
        stocks={"STR": object()},
        company_terms={"STR": ["STR", "STROC INDUSTRIE"]},
    ) is None
