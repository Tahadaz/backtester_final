from __future__ import annotations

import pytest

from quant_core.fundamentals import (
    altman_z,
    eva,
    magic_formula,
    peg_garp,
    regression_adjusted_multiples,
    score_fundamental_snapshots,
)
from quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot


def _row(symbol: str, year: int, metric: str, value: float) -> AnnualMetricRow:
    return AnnualMetricRow(symbol=symbol, company_name=symbol, statement_year=year, metric_name=metric, metric_value=value)


def _screen_snapshot(
    symbol: str,
    *,
    ebit: float = 100.0,
    market_cap: float = 1_000.0,
    total_debt: float = 200.0,
    cash: float = 50.0,
    growth: float = 0.10,
    roe: float = 0.14,
    per: float = 10.0,
) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        company_name=symbol,
        latest_statement_year=2024,
        metrics={
            "EBIT": ebit,
            "Total_Assets": 1_000.0,
            "Current_Assets": 400.0,
            "Current_Liabilities": 200.0,
            "Cash_and_Equivalents": cash,
            "Total_Debt": total_debt,
            "Total_Liabilities": 500.0,
            "Retained_Earnings": 200.0,
            "MarketCap_Calc": market_cap,
            "PER": per,
            "Price_to_Book": 1.2,
            "EV_to_EBITDA": 7.0,
            "Price_to_Sales": 1.1,
            "ROE": roe,
            "ROA": 0.07,
            "Operating_Margin": 0.15,
            "Net_Margin": 0.10,
            "Revenue_Growth": growth,
            "NetIncome_Growth": growth,
            "Debt_to_Equity": 0.6,
            "FCF_Margin": 0.08,
            "Operating_CF_Margin": 0.09,
            "Current_Ratio": 1.2,
            "Interest_Coverage": 5.0,
        },
    )


def _history(symbol: str) -> list[AnnualMetricRow]:
    return [
        _row(symbol, 2021, "Chiffre_daffaires", 850.0),
        _row(symbol, 2022, "Chiffre_daffaires", 900.0),
        _row(symbol, 2023, "Chiffre_daffaires", 950.0),
        _row(symbol, 2024, "Chiffre_daffaires", 1_000.0),
        _row(symbol, 2021, "Resultat_net", 70.0),
        _row(symbol, 2022, "Resultat_net", 80.0),
        _row(symbol, 2023, "Resultat_net", 90.0),
        _row(symbol, 2024, "Resultat_net", 100.0),
        _row(symbol, 2024, "Free_Cash_Flow", 80.0),
        _row(symbol, 2024, "Total_Debt", 200.0),
    ]


def test_magic_formula_ranks_target_within_cohort() -> None:
    target = _screen_snapshot("AAA", ebit=100, market_cap=1_000)
    peers = [
        target,
        _screen_snapshot("P1", ebit=120, market_cap=800),
        _screen_snapshot("P2", ebit=80, market_cap=800),
        _screen_snapshot("P3", ebit=60, market_cap=1_700),
    ]
    result = magic_formula(target, peers, sectors={row.symbol: "Industrie" for row in peers})

    assert result["scope"] == "sector"
    assert result["score"] == pytest.approx(66.67, abs=0.02)
    assert result["roc"] > 0
    assert result["earnings_yield"] > 0


def test_magic_formula_missing_inputs_returns_warning() -> None:
    result = magic_formula(
        FundamentalSnapshot(symbol="MISS", company_name="MISS", latest_statement_year=2024, metrics={}),
        [],
    )

    assert result["score"] is None
    assert "missing_ebit" in result["warnings"]


def test_peg_garp_zone_boundaries() -> None:
    very_cheap = peg_garp(_screen_snapshot("PEG1", per=7.4, growth=0.10), _history("PEG1"))
    reasonable = peg_garp(_screen_snapshot("PEG2", per=14.0, growth=0.10), _history("PEG2"))
    expensive = peg_garp(_screen_snapshot("PEG3", per=35.0, growth=0.10), _history("PEG3"))

    assert very_cheap["zone"] == "very_cheap_growth"
    assert very_cheap["score"] == 100.0
    assert reasonable["zone"] == "reasonable_growth"
    assert expensive["zone"] == "very_expensive"


def test_altman_z_non_financial_and_financial_variants() -> None:
    snapshot = _screen_snapshot("ALT")
    non_financial = altman_z(snapshot, _history("ALT"), "Industrie")
    financial = altman_z(snapshot, _history("ALT"), "Banques")

    assert non_financial["variant"] == "Z"
    assert non_financial["zone"] == "safe"
    assert non_financial["z_value"] == pytest.approx(3.05, abs=0.001)
    assert financial["variant"] == "Z''"
    assert financial["zone"] == "safe"
    assert financial["score"] > non_financial["score"]


def test_eva_value_creator_and_financial_skip() -> None:
    snapshot = _screen_snapshot("EVA")
    result = eva(snapshot, _history("EVA"), {"wacc": 0.0851, "tax_rate": 0.30}, "Industrie")
    financial = eva(snapshot, _history("EVA"), {"wacc": 0.0851, "tax_rate": 0.30}, "Banques")

    assert result["applicable"] is True
    assert result["roic_spread"] == pytest.approx(0.0149, abs=0.0001)
    assert result["score"] == pytest.approx(64.9, abs=0.1)
    assert financial["applicable"] is False
    assert financial["score"] is None


def test_regression_adjusted_multiples_requires_and_uses_cohort() -> None:
    small = regression_adjusted_multiples(_screen_snapshot("SMALL"), [_screen_snapshot("P1")])
    assert small["score"] is None
    assert "insufficient_cohort_for_regression" in small["warnings"]

    cohort: list[FundamentalSnapshot] = []
    for index in range(9):
        growth = 0.02 + index * 0.005
        roe = 0.08 + index * 0.01
        market_cap = 800.0 + index * 275.0
        leverage = 0.25 + index * 0.08
        per = 8.0 + 55.0 * growth + 18.0 * roe + 0.20 * index + leverage
        row = _screen_snapshot(f"R{index}", growth=growth, roe=roe, market_cap=market_cap, per=per)
        row.metrics["Debt_to_Equity"] = leverage
        row.metrics["Price_to_Book"] = 0.8 + roe * 5.0 + leverage * 0.2
        row.metrics["EV_to_EBITDA"] = 5.5 + growth * 20.0 + leverage * 0.4
        row.metrics["Price_to_Sales"] = 0.7 + growth * 8.0 + roe * 2.0
        cohort.append(row)

    result = regression_adjusted_multiples(cohort[4], cohort, sectors={row.symbol: "Industrie" for row in cohort})
    assert result["scope"] == "sector"
    assert result["score"] is not None
    assert "PER" in result["regression_richness"]
    assert result["coefficients"]["PER"]["cohort_size"] == 9


def test_score_fundamental_snapshots_includes_screens() -> None:
    snapshots = [_screen_snapshot(f"S{index}", ebit=80.0 + index * 5.0, market_cap=900.0 + index * 120.0) for index in range(8)]
    history = [row for snapshot in snapshots for row in _history(snapshot.symbol)]

    scored = score_fundamental_snapshots(snapshots, history, sectors={row.symbol: "Industrie" for row in snapshots})

    for snapshot in scored:
        screens = snapshot.diagnostics["screens"]
        assert set(screens) == {"magic_formula", "peg_garp", "altman_z", "eva", "regression_adj"}
        assert screens["peg_garp"]["score"] is not None
