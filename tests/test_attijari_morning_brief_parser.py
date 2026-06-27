from __future__ import annotations

from types import SimpleNamespace

from scripts.backfill_attijari_morning_brief_fundamentals import extract_metrics_from_text


def test_extracts_cih_bank_morning_brief_quarterly_table() -> None:
    text = """
| MAROC | CIH BANK | Le RNPG en hausse de 50% au T1 2025
Indicateurs (MDH) T1 2024 T1 2025 Variation
PNB 1.123 1.300 15,8%
RBE 628 752 19,8%
Marge RBE 55,9% 57,8% +1,9 pts
Coût du risque 275 276 0,5%
RNPG 199 298 49,6%
Marge nette 17,8% 22,9% +5,1 pts
| MAROC | S2M | Le chiffre d'affaires consolidé en hausse
"""
    stocks = {"CIH": SimpleNamespace(symbol="CIH")}
    company_terms = {"CIH": ["CIH", "CIH BANK"]}

    metrics = extract_metrics_from_text(text, stocks=stocks, company_terms=company_terms)  # type: ignore[arg-type]

    by_key = {(metric.metric_name, metric.fiscal_year): metric for metric in metrics}
    assert by_key[("PNB", 2024)].metric_value == 1_123_000_000
    assert by_key[("PNB", 2025)].metric_value == 1_300_000_000
    assert by_key[("RBE", 2025)].period_type == "quarterly"
    assert by_key[("RBE", 2025)].period_label == "Q1"
    assert by_key[("Marge_RBE", 2025)].metric_value == 57.8
    assert by_key[("Cout_du_risque", 2025)].metric_value == 276_000_000
    assert by_key[("RNPG", 2025)].metric_value == 298_000_000
    assert by_key[("Marge_nette", 2024)].metric_value == 17.8


def test_extracts_space_separated_thousands_in_bank_tables() -> None:
    text = """
| MAROC | CIH BANK | Le RNPG en hausse
Indicateurs (MDH) 2024 2025 Variation
PNB 3 518 3 537 0,5%
RBE 1 988 1 997 0,5%
RNPG 657 862 31,2%
"""
    stocks = {"CIH": SimpleNamespace(symbol="CIH")}
    company_terms = {"CIH": ["CIH", "CIH BANK"]}

    metrics = extract_metrics_from_text(text, stocks=stocks, company_terms=company_terms)  # type: ignore[arg-type]

    by_key = {(metric.metric_name, metric.fiscal_year): metric for metric in metrics}
    assert by_key[("PNB", 2024)].metric_value == 3_518_000_000
    assert by_key[("PNB", 2025)].metric_value == 3_537_000_000
    assert by_key[("RBE", 2024)].metric_value == 1_988_000_000
    assert by_key[("RBE", 2025)].metric_value == 1_997_000_000
    assert by_key[("RNPG", 2025)].metric_value == 862_000_000


def test_extracts_mmdh_tables_to_full_mad_but_leaves_margins_unscaled() -> None:
    text = """
| MAROC | ATTIJARIWAFA BANK | Le RNPG en hausse
Indicateurs (MMDH) 2024 2025 Variation
PNB 33,1 34,9 5,4%
RBE 20,6 21,7 5,3%
Marge RBE 62,3% 62,2% -0,1 pts
Coût du risque 4,2 3,7 -11,9%
RNPG 9,2 10,6 15,2%
Marge nette 27,7% 30,5% +2,8 pts
"""
    stocks = {"ATW": SimpleNamespace(symbol="ATW")}
    company_terms = {"ATW": ["ATW", "ATTIJARIWAFA BANK"]}

    metrics = extract_metrics_from_text(text, stocks=stocks, company_terms=company_terms)  # type: ignore[arg-type]

    by_key = {(metric.metric_name, metric.fiscal_year): metric for metric in metrics}
    assert by_key[("PNB", 2024)].metric_value == 33_100_000_000
    assert by_key[("PNB", 2025)].metric_value == 34_900_000_000
    assert by_key[("RBE", 2025)].metric_value == 21_700_000_000
    assert by_key[("Cout_du_risque", 2024)].metric_value == 4_200_000_000
    assert by_key[("RNPG", 2025)].metric_value == 10_600_000_000
    assert by_key[("Marge_RBE", 2025)].metric_value == 62.2
    assert by_key[("Marge_nette", 2025)].metric_value == 30.5
