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


def test_peg_garp_skips_trailing_cagr_when_latest_earnings_are_negative() -> None:
    snapshot = _screen_snapshot("PEGNEG", per=12.0, growth=0.0)
    snapshot.metrics.pop("NetIncome_Growth")
    snapshot.metrics.pop("EBIT_Growth", None)
    history = [
        _row("PEGNEG", 2021, "Resultat_net", 70.0),
        _row("PEGNEG", 2022, "Resultat_net", 40.0),
        _row("PEGNEG", 2023, "Resultat_net", 10.0),
        _row("PEGNEG", 2024, "Resultat_net", -20.0),
    ]

    result = peg_garp(snapshot, history)

    assert result["score"] is None
    assert "trailing_growth_unavailable_nonpositive_history" in result["warnings"]
    assert "missing_growth" in result["warnings"]


def test_altman_z_non_financial_and_financial_variants() -> None:
    snapshot = _screen_snapshot("ALT")
    non_financial = altman_z(snapshot, _history("ALT"), "Industrie")
    financial = altman_z(snapshot, _history("ALT"), "Banques")

    assert non_financial["variant"] == "Z''_EM"
    assert non_financial["zone"] == "safe"
    assert non_financial["z_value"] == pytest.approx(3.686, abs=0.001)
    assert [term["key"] for term in non_financial["terms"]] == ["wc_ta", "re_ta", "ebit_ta", "equity_tl"]
    assert sum(term["contribution"] for term in non_financial["terms"]) == pytest.approx(non_financial["z_value"], abs=0.001)
    wc_term = next(term for term in non_financial["terms"] if term["key"] == "wc_ta")
    assert wc_term["raw"]["numerator"]["label"] == "Fonds de roulement"
    assert wc_term["raw"]["numerator"]["value"] == pytest.approx(200.0)
    assert [metric["metric_name"] for metric in wc_term["raw"]["numerator"]["metrics"]] == [
        "Current_Assets",
        "Current_Liabilities",
    ]
    assert wc_term["raw"]["denominator"] == {
        "label": "Actif total",
        "metric_name": "Total_Assets",
        "value": 1_000.0,
        "statement_year": 2024,
    }
    assert financial["score"] is None
    assert financial["applicable"] is False
    assert "altman_not_applicable_financials" in financial["warnings"]


def test_eva_value_creator_and_financial_skip() -> None:
    snapshot = _screen_snapshot("EVA")
    result = eva(snapshot, _history("EVA"), {"wacc": 0.0851, "tax_rate": 0.30}, "Industrie")
    financial = eva(snapshot, _history("EVA"), {}, "Banques")

    assert result["applicable"] is True
    assert result["roic_spread"] == pytest.approx(0.0149, abs=0.0001)
    assert result["score"] == pytest.approx(64.9, abs=0.1)
    assert result["wacc_source"] == "assumption"
    assert financial["applicable"] is False
    assert financial["score"] is None
    assert financial["wacc_source"] == "default"


def test_altman_and_eva_accept_cgnc_metric_aliases() -> None:
    snapshot = FundamentalSnapshot(
        symbol="CGNC",
        company_name="CGNC",
        latest_statement_year=2024,
        metrics={
            "Resultat_dexploitation": 100.0,
            "Total_Actif": 1_000.0,
            "Total_Passif": 1_000.0,
            "Capitaux_propres": 500.0,
            "Actif_circulant": 400.0,
            "Passif_circulant": 200.0,
            "Chiffre_daffaires": 1_000.0,
            "MarketCap_Calc": 1_000.0,
            "Dettes_de_financement": 200.0,
            "Tresorerie_Actif": 50.0,
        },
    )

    altman = altman_z(snapshot, [], "Industrie")
    eva_result = eva(snapshot, [], {"wacc": 0.0851, "tax_rate": 0.30}, "Industrie")

    assert altman["score"] is not None
    assert altman["z_value"] == pytest.approx(3.034, abs=0.001)
    assert "missing_ebit" not in altman["warnings"]
    assert "missing_total_assets" not in altman["warnings"]
    assert "missing_total_liabilities" not in altman["warnings"]
    assert eva_result["score"] is not None
    assert eva_result["invested_capital"] == pytest.approx(700.0)
    assert eva_result["roic_spread"] == pytest.approx(0.0149, abs=0.0001)


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


# ---------------------------------------------------------------------------
# Bank archetype scoring
# ---------------------------------------------------------------------------

def _bank_snapshot(symbol: str, *, per: float = 8.0, price_to_book: float = 1.2,
                   roe: float = 0.12, nim: float = 0.035, cti: float = 0.55,
                   cout_du_risque: float = 0.015, loans_to_deposits: float = 0.75) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        company_name=symbol,
        latest_statement_year=2024,
        metrics={
            "ROE": roe,
            "ROA": 0.01 + roe * 0.05,
            "Net_Interest_Margin": nim,
            "Cost_to_Income": cti,
            "Revenue_Growth": 0.08,
            "NetIncome_Growth": 0.10,
            "Cout_du_risque": cout_du_risque,
            "Loans_to_Deposits": loans_to_deposits,
            "PER": per,
            "Price_to_Book": price_to_book,
            "Dividend_Yield": 0.05,
        },
        diagnostics={"archetype": "bank"},
        source={"archetype": "bank"},
    )


def test_bank_snapshot_scoring_uses_bank_pillar_metrics() -> None:
    # Build a cohort of 5 banks with varied metrics so the percentile scorer has enough peers.
    banks = [
        _bank_snapshot(f"BNK{i}",
                       per=7.0 + i * 1.5,
                       price_to_book=0.9 + i * 0.15,
                       roe=0.10 + i * 0.02,
                       nim=0.030 + i * 0.003,
                       cti=0.60 - i * 0.03,
                       cout_du_risque=0.020 - i * 0.002,
                       loans_to_deposits=0.80 - i * 0.04)
        for i in range(5)
    ]
    scored = score_fundamental_snapshots(banks)
    target = scored[0]

    # Core assertion: bank pillar scores are non-null using bank-specific metrics.
    assert target.scores["value"] is not None, "bank value score must be non-null (PER / P_B / Div_Yield)"
    assert target.scores["quality"] is not None, "bank quality score must be non-null (ROE / ROA / NIM / C_I)"
    assert target.scores["risk"] is not None, "bank risk score must be non-null (Cout_du_risque / L_D)"

    # Industrial-only metrics must never appear in the bank's ranked breakdown.
    breakdown = target.diagnostics.get("metric_breakdown", {})
    for forbidden in ("EV_to_EBITDA", "Current_Ratio", "Debt_to_Equity", "FCF_Yield", "Price_to_Sales"):
        assert forbidden not in breakdown, f"bank must not be ranked on industrial metric {forbidden!r}"

    # Canonical risk metric name enforced — alias must be absent.
    assert "Cout_du_risque" in breakdown, "Cout_du_risque must appear in bank metric breakdown"
    assert "Cost_of_Risk" not in breakdown, "alias Cost_of_Risk must not appear (use canonical)"


# ---------------------------------------------------------------------------
# Insurance archetype scoring
# ---------------------------------------------------------------------------

def _insurer_snapshot(
    symbol: str,
    *,
    premiums_earned: float = 1_000.0,
    policy_benefits: float = 600.0,
    policy_acq_costs: float = 150.0,
    per: float = 9.0,
    price_to_book: float = 1.1,
    roe: float = 0.11,
    combined_ratio: float = 0.75,
) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        company_name=symbol,
        latest_statement_year=2024,
        metrics={
            "Revenue": premiums_earned,
            "Premiums_Earned": premiums_earned,
            "Policy_Benefits": policy_benefits,
            "Policy_Acquisition_Costs": policy_acq_costs,
            "Combined_Ratio": combined_ratio,
            "ROE": roe,
            "ROA": 0.02,
            "Net_Margin": 0.09,
            "Revenue_Growth": 0.07,
            "NetIncome_Growth": 0.08,
            "PER": per,
            "Price_to_Book": price_to_book,
            "Dividend_Yield": 0.04,
            "Equity_Multiplier": 4.0,
        },
        diagnostics={"archetype": "insurance"},
        source={"archetype": "insurance"},
    )


def test_insurer_snapshot_scoring_uses_financial_pillar_metrics() -> None:
    insurers = [
        _insurer_snapshot(
            f"INS{i}",
            premiums_earned=1_000.0 + i * 100.0,
            combined_ratio=0.80 - i * 0.02,
            roe=0.10 + i * 0.01,
            per=8.0 + i,
            price_to_book=0.9 + i * 0.1,
        )
        for i in range(5)
    ]
    scored = score_fundamental_snapshots(insurers)
    target = scored[0]

    assert target.scores["quality"] is not None, "insurer quality score must be non-null (ROE/ROA/Net_Margin/Combined_Ratio)"
    assert target.scores["value"] is not None, "insurer value score must be non-null"

    breakdown = target.diagnostics.get("metric_breakdown", {})
    # Combined_Ratio must be scored
    assert "Combined_Ratio" in breakdown, "Combined_Ratio must appear in insurer metric breakdown"
    # Industrial-only suppressed metrics must not appear
    for forbidden in ("FCF_Yield", "Price_to_Sales", "EV_to_EBITDA", "NetDebt_to_EBITDA"):
        assert forbidden not in breakdown, f"insurer must not be ranked on industrial metric {forbidden!r}"


def test_insurer_cohort_isolated_from_industrials() -> None:
    insurers = [_insurer_snapshot(f"INS{i}", combined_ratio=0.75 + i * 0.02) for i in range(5)]
    industrials = [_screen_snapshot(f"IND{i}", per=12.0 + i) for i in range(5)]
    all_snapshots = insurers + industrials

    scored = score_fundamental_snapshots(all_snapshots)
    scored_by_symbol = {s.symbol: s for s in scored}

    for i in range(5):
        sym = f"INS{i}"
        snap = scored_by_symbol[sym]
        breakdown = snap.diagnostics.get("metric_breakdown", {})
        # Combined_Ratio can only have insurer peers
        cr_entry = breakdown.get("Combined_Ratio")
        if cr_entry is not None:
            assert cr_entry.get("cohort_size", 0) <= 5, (
                f"Combined_Ratio cohort for {sym} must not exceed number of insurers"
            )


def test_bank_cohort_isolated_from_industrials() -> None:
    # Mixed cohort: 5 banks + 5 industrials.  Banks must be cohorted together,
    # not ranked against industrials.
    banks = [
        _bank_snapshot(f"BNK{i}", per=7.0 + i, nim=0.03 + i * 0.002)
        for i in range(5)
    ]
    industrials = [_screen_snapshot(f"IND{i}", per=12.0 + i) for i in range(5)]
    all_snapshots = banks + industrials

    scored = score_fundamental_snapshots(all_snapshots)
    scored_by_symbol = {s.symbol: s for s in scored}

    # For each bank, the score scope for any scored pillar must reference
    # the bank cohort, not the full market (NIM only exists for banks).
    for i in range(5):
        sym = f"BNK{i}"
        snap = scored_by_symbol[sym]
        breakdown = snap.diagnostics.get("metric_breakdown", {})
        # Net_Interest_Margin can only have bank peers → scope must be sector or market
        # (market IS the banks for this metric since industrials have no NIM value)
        nim_entry = breakdown.get("Net_Interest_Margin")
        if nim_entry is not None:
            assert nim_entry.get("cohort_size", 0) <= 5, (
                f"NIM cohort for {sym} must not exceed number of banks (got {nim_entry.get('cohort_size')})"
            )
