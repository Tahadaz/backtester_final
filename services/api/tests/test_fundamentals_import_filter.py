from core.quant_core.fundamentals.domain import (
    AnnualMetricRow,
    CompanyMapping,
    FundamentalQualityIssue,
    FundamentalSnapshot,
    FundamentalWorkbook,
)

from services.api.app.services.fundamentals import _filter_workbook_to_stock_master_symbols


def test_workbook_filter_keeps_only_existing_stock_master_symbols() -> None:
    parsed = FundamentalWorkbook(
        mappings=[
            CompanyMapping(company_name="Known Co", mapped_company_name="Known Co", symbol="AAA"),
            CompanyMapping(company_name="Unknown Co", mapped_company_name="Unknown Co", symbol="ZZZ"),
            CompanyMapping(company_name="Unmapped Co", mapped_company_name=None, symbol=None),
        ],
        annual_metrics=[
            AnnualMetricRow(symbol="AAA", company_name="Known Co", statement_year=2024, metric_name="ROE", metric_value=0.2),
            AnnualMetricRow(symbol="ZZZ", company_name="Unknown Co", statement_year=2024, metric_name="ROE", metric_value=0.1),
        ],
        latest_snapshots=[
            FundamentalSnapshot(symbol="AAA", company_name="Known Co", latest_statement_year=2024),
            FundamentalSnapshot(symbol="ZZZ", company_name="Unknown Co", latest_statement_year=2024),
        ],
        quality_issues=[
            FundamentalQualityIssue(severity="warning", code="known_warning", symbol="AAA", message="known"),
            FundamentalQualityIssue(severity="warning", code="unknown_warning", symbol="ZZZ", message="unknown"),
        ],
        summary={
            "mapped_company_count": 3,
            "mapped_symbol_count": 2,
            "annual_metric_count": 2,
            "latest_snapshot_count": 2,
        },
    )

    filtered = _filter_workbook_to_stock_master_symbols(parsed, existing_symbols={"AAA"})

    assert [mapping.symbol for mapping in filtered.mappings] == ["AAA"]
    assert [row.symbol for row in filtered.annual_metrics] == ["AAA"]
    assert [row.symbol for row in filtered.latest_snapshots] == ["AAA"]
    assert filtered.summary["mapped_company_count"] == 1
    assert filtered.summary["mapped_symbol_count"] == 1
    assert filtered.summary["workbook_mapped_company_count"] == 3
    assert filtered.summary["ignored_mapping_count"] == 2
    assert filtered.summary["ignored_symbols"] == ["ZZZ"]

    issue_codes = [issue.code for issue in filtered.quality_issues]
    assert "known_warning" in issue_codes
    assert "unknown_warning" not in issue_codes
    assert "unknown_symbol_ignored" in issue_codes
    assert "unmapped_company_ignored" in issue_codes


def test_workbook_filter_canonicalizes_known_bvc_symbol_aliases() -> None:
    parsed = FundamentalWorkbook(
        mappings=[
            CompanyMapping(company_name="DISTY TECHNOLOGIES", mapped_company_name="DISTY TECHNOLOGIES", symbol="DISTY"),
            CompanyMapping(company_name="SANLAM MAROC", mapped_company_name="Sanlam Maroc", symbol="SNA"),
            CompanyMapping(company_name="ZELLIDJA S.A", mapped_company_name="Zellidja", symbol="ZCO"),
        ],
        annual_metrics=[
            AnnualMetricRow(symbol="DISTY", company_name="DISTY TECHNOLOGIES", statement_year=2024, metric_name="ROE", metric_value=0.2),
            AnnualMetricRow(symbol="SNA", company_name="SANLAM MAROC", statement_year=2024, metric_name="ROE", metric_value=0.1),
            AnnualMetricRow(symbol="ZCO", company_name="ZELLIDJA S.A", statement_year=2024, metric_name="ROE", metric_value=0.3),
        ],
        latest_snapshots=[
            FundamentalSnapshot(symbol="DISTY", company_name="DISTY TECHNOLOGIES", latest_statement_year=2024),
            FundamentalSnapshot(symbol="SNA", company_name="SANLAM MAROC", latest_statement_year=2024),
            FundamentalSnapshot(symbol="ZCO", company_name="ZELLIDJA S.A", latest_statement_year=2024),
        ],
        quality_issues=[],
        summary={},
    )

    filtered = _filter_workbook_to_stock_master_symbols(parsed, existing_symbols={"DYT", "SAH", "ZDJ"})

    assert [mapping.symbol for mapping in filtered.mappings] == ["DYT", "SAH", "ZDJ"]
    assert {row.symbol for row in filtered.annual_metrics} == {"DYT", "SAH", "ZDJ"}
    assert {row.symbol for row in filtered.latest_snapshots} == {"DYT", "SAH", "ZDJ"}
    assert filtered.summary["canonicalized_symbol_aliases"] == ["DISTY->DYT", "SNA->SAH", "ZCO->ZDJ"]


def test_workbook_filter_prefers_company_alias_when_raw_symbol_collides() -> None:
    parsed = FundamentalWorkbook(
        mappings=[
            CompanyMapping(company_name="SANLAM MAROC", mapped_company_name="Sanlam Maroc", symbol="SNA"),
            CompanyMapping(company_name="STOKVIS NORD AFRIQUE", mapped_company_name="STOKVIS NORD AFRIQUE", symbol="STV"),
        ],
        annual_metrics=[
            AnnualMetricRow(
                symbol="SNA",
                company_name="SANLAM MAROC",
                statement_year=2025,
                metric_name="Capitaux_propres",
                metric_value=6_062_749_000,
            ),
            AnnualMetricRow(
                symbol="STV",
                company_name="STOKVIS NORD AFRIQUE",
                statement_year=2025,
                metric_name="Capitaux_propres",
                metric_value=-96_517_000,
            ),
        ],
        latest_snapshots=[
            FundamentalSnapshot(symbol="SNA", company_name="SANLAM MAROC", latest_statement_year=2025),
            FundamentalSnapshot(symbol="STV", company_name="STOKVIS NORD AFRIQUE", latest_statement_year=2025),
        ],
        quality_issues=[],
        summary={},
    )

    filtered = _filter_workbook_to_stock_master_symbols(parsed, existing_symbols={"SAH", "SNA"})

    assert [mapping.symbol for mapping in filtered.mappings] == ["SAH", "SNA"]
    assert {
        (row.symbol, row.company_name, row.metric_value)
        for row in filtered.annual_metrics
        if row.metric_name == "Capitaux_propres"
    } == {
        ("SAH", "SANLAM MAROC", 6_062_749_000),
        ("SNA", "STOKVIS NORD AFRIQUE", -96_517_000),
    }
    assert [snapshot.symbol for snapshot in filtered.latest_snapshots] == ["SAH", "SNA"]
    assert filtered.summary["canonicalized_symbol_aliases"] == ["SNA->SAH", "STV->SNA"]
