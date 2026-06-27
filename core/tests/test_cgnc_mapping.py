from __future__ import annotations

import datetime as dt

import pytest

from core.quant_core.fundamentals.cgnc_mapping import (
    infer_statement_archetype,
    infer_statement_archetype_from_values,
    map_cgnc_annual_metrics,
)
from core.quant_core.fundamentals.domain import AnnualMetricRow


def _row(metric: str, value: float | None, year: int = 2024) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol="AAA",
        company_name="Alpha",
        statement_year=year,
        metric_name=metric,
        metric_value=value,
        raw_metric_name=f"{metric}_{year}",
        source_sheet="bvc_jsonl",
        source_field=f"{metric}_{year}",
        as_of_date=dt.date(2025, 3, 31),
        source_document_id=7,
    )


def _metrics(rows: list[AnnualMetricRow]) -> dict[str, AnnualMetricRow]:
    return {row.metric_name: row for row in rows}


def test_cgnc_mapping_derives_ebitda_when_ebe_missing() -> None:
    mapped = _metrics(
        map_cgnc_annual_metrics(
            [
                _row("Resultat_dexploitation", 120.0),
                _row("Dotations_dexploitation", 30.0),
            ]
        )
    )

    assert mapped["EBIT"].metric_value == pytest.approx(120.0)
    assert mapped["Depreciation_Amortization"].metric_value == pytest.approx(30.0)
    assert mapped["EBITDA"].metric_value == pytest.approx(150.0)
    assert mapped["EBITDA"].is_proxy is True
    assert mapped["EBITDA"].as_of_date == dt.date(2025, 3, 31)
    assert mapped["EBITDA"].source_document_id == 7


def test_cgnc_mapping_derives_fcf_from_caf_fallback_and_signed_investing_cf() -> None:
    mapped = _metrics(
        map_cgnc_annual_metrics(
            [
                _row("Capacite_dautofinancement", 200.0),
                _row("Variation_du_besoin_de_financement_global", 40.0),
                _row("Flux_de_tresorerie_lies_aux_investissements", -70.0),
                _row("Dividendes_distribues", -12.0),
            ]
        )
    )

    assert mapped["Operating_Cash_Flow"].metric_value == pytest.approx(160.0)
    assert mapped["Free_Cash_Flow"].metric_value == pytest.approx(90.0)
    assert mapped["Capex"].metric_value == pytest.approx(70.0)
    assert "Dividendes" not in mapped


def test_cgnc_mapping_derives_fcf_from_bvc_operating_cash_flow_and_capex_field() -> None:
    mapped = _metrics(
        map_cgnc_annual_metrics(
            [
                _row("Flux_tresorerie_activites_operationnelles", 2_485_000_000.0),
                _row("Flux_tresorerie_investissement_CAPEX", -2_408_000_000.0),
            ]
        )
    )

    assert mapped["Operating_Cash_Flow"].metric_value == pytest.approx(2_485_000_000.0)
    assert mapped["Capex"].metric_value == pytest.approx(2_408_000_000.0)
    assert mapped["Capital_Expenditures"].metric_value == pytest.approx(2_408_000_000.0)
    assert mapped["Free_Cash_Flow"].metric_value == pytest.approx(77_000_000.0)
    assert mapped["Free_Cash_Flow"].raw_metric_name == "derived:cfo_minus_capex"


def test_cgnc_mapping_derives_roe_and_growth_from_annual_history() -> None:
    rows = map_cgnc_annual_metrics(
        [
            _row("Chiffre_daffaires", 10_000.0, 2024),
            _row("Resultat_net", 787.0, 2024),
            _row("Capitaux_propres", 11_000.0, 2024),
            _row("Chiffre_daffaires", 13_700.0, 2025),
            _row("Resultat_net", 3_000.0, 2025),
            _row("Capitaux_propres", 11_500.0, 2025),
        ]
    )
    mapped = {(row.statement_year, row.metric_name): row for row in rows}

    assert mapped[(2025, "ROE")].metric_value == pytest.approx(3_000.0 / ((11_000.0 + 11_500.0) / 2.0))
    assert mapped[(2025, "Revenue_Growth")].metric_value == pytest.approx(0.37)
    assert mapped[(2025, "NetIncome_Growth")].metric_value == pytest.approx((3_000.0 - 787.0) / 787.0)


def test_cgnc_mapping_prefers_group_basis_for_roe_when_available() -> None:
    rows = map_cgnc_annual_metrics(
        [
            _row("Resultat_net", 5_621.0, 2025),
            _row("Resultat_net_part_du_groupe", 4_503.0, 2025),
            _row("Capitaux_propres", 57_956.0, 2025),
            _row("Capitaux_propres_part_du_groupe", 41_452.0, 2025),
        ]
    )
    mapped = {(row.statement_year, row.metric_name): row for row in rows}

    assert mapped[(2025, "ROE")].metric_value == pytest.approx(4_503.0 / 41_452.0)
    assert mapped[(2025, "ROE")].raw_metric_name == "derived:group_net_income_over_avg_group_equity"


def test_infer_statement_archetype_uses_cgnc_esg_fields() -> None:
    assert infer_statement_archetype(["Chiffre_daffaires", "Excedent_brut_dexploitation"]) == "cgnc_social"
    assert infer_statement_archetype(["Resultat_net_part_du_groupe"]) == "ifrs_consolidated"


def test_infer_statement_archetype_from_values_english_bank() -> None:
    """StockAnalysis-style English bank metrics (all non-null) must classify as bank."""
    metrics = {
        "Net_Interest_Income": 4_800_000_000.0,
        "Loans_Net": 100_000_000_000.0,
        "Customer_Deposits": 120_000_000_000.0,
        "Provision_for_Loan_Losses": 600_000_000.0,
        "NetIncome": 1_500_000_000.0,
        "Total_Assets": 180_000_000_000.0,
        "Total_Equity": 15_000_000_000.0,
    }
    assert infer_statement_archetype_from_values(metrics) == "bank"


def test_infer_statement_archetype_from_values_industrial_with_null_bank_keys() -> None:
    """English industrial metrics with null bank keys must NOT classify as bank.

    The StockAnalysis provider writes bank-specific keys for every symbol but
    leaves them null for industrials.  The from_values variant must filter those
    out before detection so industrials are not mis-classified.
    """
    metrics = {
        "Revenue": 4_200_000_000.0,
        "EBIT": 700_000_000.0,
        "Total_Assets": 8_000_000_000.0,
        "Total_Equity": 2_500_000_000.0,
        # bank keys present but null — must be ignored
        "Net_Interest_Income": None,
        "Customer_Deposits": None,
        "Loans_Net": None,
        "Provision_for_Loan_Losses": None,
    }
    archetype = infer_statement_archetype_from_values(metrics)
    assert archetype != "bank", (
        f"Industrial symbol with null bank keys was mis-classified as {archetype!r}"
    )
