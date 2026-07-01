from __future__ import annotations

import datetime as dt

import pytest

from core.quant_core.fundamentals.cgnc_mapping import infer_statement_archetype, map_cgnc_annual_metrics
from core.quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot
from core.quant_core.fundamentals.projection import build_projection
from core.quant_core.fundamentals.valuation import compute_symbol_valuations, default_assumptions_for_scenario


def _row(symbol: str, year: int, metric: str, value: float) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol=symbol,
        company_name=symbol,
        statement_year=year,
        metric_name=metric,
        metric_value=value,
        as_of_date=dt.date(year + 1, 4, 30),
    )


def _cgnc_row(metric: str, value: float | None = 1.0) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol="ATW",
        company_name="Attijariwafa Bank",
        statement_year=2024,
        metric_name=metric,
        metric_value=value,
        raw_metric_name=metric,
        source_sheet="bvc_jsonl",
        source_field=metric,
    )


def _bank_snapshot(symbol: str = "ATW", **metrics: float) -> FundamentalSnapshot:
    base = {
        "Current_Price": 100.0,
        "Shares_Outstanding": 10.0,
        "MarketCap_Calc": 1000.0,
        "Price_to_Book": 3.0,
        "PER": 8.0,
        "ROE": 0.42,
        "Dividend_Yield": 0.06,
        "Dividend_Payout": 0.35,
        "Price_to_PNB": 1.9,
    }
    base.update(metrics)
    return FundamentalSnapshot(
        symbol=symbol,
        company_name=symbol,
        latest_statement_year=2024,
        metrics=base,
        source={"currency": "MAD"},
        as_of_date=dt.date(2025, 4, 30),
    )


def _bank_history(*, include_rbe: bool = True) -> list[AnnualMetricRow]:
    rows: list[AnnualMetricRow] = []
    pnb_by_year = {2021: 420.0, 2022: 462.0, 2023: 508.2, 2024: 559.02}
    equity_by_year = {2021: 260.0, 2022: 280.0, 2023: 305.0, 2024: 333.0}
    loans_by_year = {2021: 850.0, 2022: 900.0, 2023: 955.0, 2024: 1012.0}
    for year, pnb in pnb_by_year.items():
        loans = loans_by_year[year]
        rbe = pnb * 0.48
        cost = loans * 0.012
        pretax = rbe - cost
        tax = pretax * 0.30
        net_income = pretax - tax
        dividends = net_income * 0.35
        rows.extend(
            [
                _row("ATW", year, "PNB", pnb),
                _row("ATW", year, "Loans_Net", loans),
                _row("ATW", year, "Cout_du_risque", cost),
                _row("ATW", year, "Income_Tax_Expense", tax),
                _row("ATW", year, "NetIncome", net_income),
                _row("ATW", year, "Dividends_Paid", dividends),
                _row("ATW", year, "Total_Equity", equity_by_year[year]),
                _row("ATW", year, "ROE", net_income / equity_by_year[year]),
            ]
        )
        if include_rbe:
            rows.extend(
                [
                    _row("ATW", year, "RBE", rbe),
                    _row("ATW", year, "Marge_RBE", 0.48),
                ]
            )
    return rows


def _peer(symbol: str, *, per: float, pb: float, pnb: float | None = None) -> FundamentalSnapshot:
    metrics = {"PER": per, "Price_to_Book": pb, "ROE": 0.18, "Dividend_Payout": 0.4}
    if pnb is not None:
        metrics["Price_to_PNB"] = pnb
    return FundamentalSnapshot(
        symbol=symbol,
        company_name=symbol,
        latest_statement_year=2024,
        metrics=metrics,
        source={"currency": "MAD"},
        as_of_date=dt.date(2025, 4, 30),
    )


def _bank_peers() -> list[FundamentalSnapshot]:
    return [
        _peer("BCP", per=9.0, pb=2.4, pnb=1.6),
        _peer("BOA", per=10.0, pb=2.5, pnb=1.7),
        _peer("CIH", per=11.0, pb=2.6, pnb=1.8),
    ]


def test_cgnc_mapping_suppresses_industrial_metrics_for_bank_and_insurance() -> None:
    bank_rows = map_cgnc_annual_metrics(
        [
            _cgnc_row("PNB", 500.0),
            _cgnc_row("Resultat_dexploitation", 120.0),
            _cgnc_row("Dotations_dexploitation", 30.0),
            _cgnc_row("Flux_de_tresorerie_lies_aux_investissements", -70.0),
            _cgnc_row("Flux_tresorerie_investissement_CAPEX", -55.0),
            _cgnc_row("Free_Cash_Flow", 99.0),
            _cgnc_row("EV_to_EBITDA", 7.0),
        ]
    )
    bank_metrics = {row.metric_name for row in bank_rows}

    assert infer_statement_archetype(["PNB", "Resultat_net"]) == "bank"
    assert {"EBITDA", "Free_Cash_Flow", "Capex", "Capital_Expenditures", "EV_to_EBITDA"}.isdisjoint(bank_metrics)

    insurance_rows = map_cgnc_annual_metrics(
        [
            _cgnc_row("Primes_assurance", 400.0),
            _cgnc_row("Resultat_dexploitation", 120.0),
            _cgnc_row("Dotations_dexploitation", 30.0),
            _cgnc_row("Flux_de_tresorerie_lies_aux_investissements", -70.0),
        ]
    )
    insurance_metrics = {row.metric_name for row in insurance_rows}

    assert infer_statement_archetype(["Primes_assurance", "Resultat_net"]) == "insurance"
    assert {"EBITDA", "Free_Cash_Flow", "Capex", "Capital_Expenditures"}.isdisjoint(insurance_metrics)


def test_bank_values_with_equity_side_models_only() -> None:
    assumptions = default_assumptions_for_scenario("base")
    snapshot = _bank_snapshot()
    peers = _bank_peers()
    sectors = {"ATW": "Banques", "BCP": "Banques", "BOA": "Banques", "CIH": "Banques"}

    eligibility, results = compute_symbol_valuations(
        snapshot=snapshot,
        history=_bank_history(),
        peer_snapshots=peers,
        sectors=sectors,
        assumptions=assumptions,
        scenario="base",
    )
    by_model = {row.model: row for row in results}

    assert eligibility["financial_archetype"]["class"] == "bank"
    assert by_model["residual_income"].fair_value is not None
    assert by_model["residual_income"].fair_value > 0
    assert by_model["ddm"].fair_value is not None
    assert by_model["ddm"].fair_value > 0
    assert by_model["fcff_dcf"].confidence == "unavailable"
    assert by_model["fcfe_dcf"].confidence == "unavailable"
    assert by_model["reverse_dcf"].confidence == "unavailable"
    assert all("ev_multiple_skipped_missing_bridge" not in row.warnings for row in results)
    usable_models = {row.model for row in results if row.fair_value is not None and row.confidence != "unavailable"}
    assert usable_models <= {"relative_multiples", "ddm", "residual_income", "justified_multiples"}


def test_financial_relative_multiples_use_pb_pe_and_pnb_only_when_observed() -> None:
    eligibility, results = compute_symbol_valuations(
        snapshot=_bank_snapshot(EV_to_EBITDA=5.0, Price_to_Sales=2.0),
        history=_bank_history(),
        peer_snapshots=_bank_peers(),
        sectors={"ATW": "Banques", "BCP": "Banques", "BOA": "Banques", "CIH": "Banques"},
        assumptions=default_assumptions_for_scenario("base"),
        scenario="base",
    )
    relative = {row.model: row for row in results}["relative_multiples"]

    assert eligibility["relative_multiples"]["eligible"] is True
    assert set(relative.inputs["selected_ratio_keys"]) == {"PER", "Price_to_Book", "Price_to_PNB"}
    assert "EV_to_EBITDA" not in relative.inputs["own_multiples"]
    assert relative.inputs["ev_to_ebitda_bridge"] == {}
    assert "Price_to_Sales" not in relative.outputs["implied_prices"]


def test_bank_missing_rbe_margin_makes_projection_dependent_ri_unavailable() -> None:
    _, results = compute_symbol_valuations(
        snapshot=_bank_snapshot(),
        history=_bank_history(include_rbe=False),
        peer_snapshots=[],
        sectors={"ATW": "Banques"},
        assumptions={**default_assumptions_for_scenario("base"), "peer_min_count": 3.0},
        scenario="base",
    )
    residual_income = {row.model: row for row in results}["residual_income"]

    assert residual_income.fair_value is None
    assert residual_income.confidence == "unavailable"
    assert "bank_rbe_margin_unavailable_no_history_no_peer" in residual_income.warnings


def test_insurer_uses_flagged_roe_book_equity_projection_without_pnb() -> None:
    history = [
        _row("WAA", 2022, "NetIncome", 90.0),
        _row("WAA", 2022, "Dividends_Paid", 35.0),
        _row("WAA", 2022, "Total_Equity", 600.0),
        _row("WAA", 2022, "ROE", 0.15),
        _row("WAA", 2023, "NetIncome", 96.0),
        _row("WAA", 2023, "Dividends_Paid", 38.0),
        _row("WAA", 2023, "Total_Equity", 640.0),
        _row("WAA", 2023, "ROE", 0.15),
        _row("WAA", 2024, "NetIncome", 105.0),
        _row("WAA", 2024, "Dividends_Paid", 42.0),
        _row("WAA", 2024, "Total_Equity", 700.0),
        _row("WAA", 2024, "ROE", 0.15),
    ]
    snapshot = FundamentalSnapshot(
        symbol="WAA",
        company_name="Wafa Assurance",
        latest_statement_year=2024,
        metrics={
            "Current_Price": 100.0,
            "Shares_Outstanding": 10.0,
            "MarketCap_Calc": 1000.0,
            "Price_to_Book": 1.4,
            "PER": 9.0,
            "ROE": 0.15,
            "Dividend_Yield": 0.04,
            "Dividend_Payout": 0.40,
        },
        source={"currency": "MAD"},
        as_of_date=dt.date(2025, 4, 30),
    )

    assumptions = {**default_assumptions_for_scenario("base"), "_financial_archetype": "insurance"}
    projection = build_projection(snapshot, history, assumptions, scenario="base")
    _, results = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[],
        sectors={"WAA": "Assurances"},
        assumptions=default_assumptions_for_scenario("base"),
        scenario="base",
    )
    by_model = {row.model: row for row in results}

    assert "insurer_simplified_roe_projection" in projection.warnings
    assert by_model["residual_income"].fair_value is not None
    assert by_model["ddm"].fair_value is not None
    assert by_model["relative_multiples"].inputs["financial_ratio_set"].startswith("P/B + P/E")


def test_thin_data_financial_confidence_is_not_auto_high() -> None:
    _, results = compute_symbol_valuations(
        snapshot=_bank_snapshot(Dividend_Yield=0.0, Price_to_PNB=None),
        history=[],
        peer_snapshots=[],
        sectors={"ATW": "Banques"},
        assumptions=default_assumptions_for_scenario("base"),
        scenario="base",
    )
    residual_income = {row.model: row for row in results}["residual_income"]

    assert residual_income.fair_value is not None
    assert residual_income.confidence != "high"
    assert "bank_projection_unavailable_using_pb_roe_fallback" in residual_income.warnings


def test_forward_ni_seeds_bank_projection_net_income() -> None:
    """Banks route through _build_bank_projection — a separate code path from
    build_projection's default (non-financial) branch. BKGR covers bank forward
    NI (ATW/BCP/CIH), so this seam must fire there too (brief 54 §3.3)."""
    history = _bank_history()
    snapshot = _bank_snapshot()
    base_assumptions = {**default_assumptions_for_scenario("base"), "_financial_archetype": "bank"}
    proj_base = build_projection(snapshot, history, base_assumptions, scenario="base")

    fwd_ni = proj_base.statements[0]["net_income"] * 1.5
    fwd_year = proj_base.statements[0]["fiscal_year"]
    seeded_assumptions = {**base_assumptions, "forward_net_income": fwd_ni, "forward_fiscal_year": fwd_year}
    proj_seeded = build_projection(snapshot, history, seeded_assumptions, scenario="base")

    assert proj_seeded.statements[0]["net_income"] == pytest.approx(fwd_ni)
    assert "net_income_forward_seeded" in proj_seeded.warnings
    # pnb/rbe path (drives relative_multiples/fcff-style outputs) must be untouched.
    assert proj_seeded.statements[0]["pnb"] == pytest.approx(proj_base.statements[0]["pnb"])

    sectors = {"ATW": "Banques", "BCP": "Banques", "BOA": "Banques", "CIH": "Banques"}
    _, vals_base = compute_symbol_valuations(
        snapshot=snapshot, history=history, peer_snapshots=_bank_peers(), sectors=sectors,
        assumptions=default_assumptions_for_scenario("base"), scenario="base",
    )
    _, vals_seeded = compute_symbol_valuations(
        snapshot=snapshot, history=history, peer_snapshots=_bank_peers(), sectors=sectors,
        assumptions={**default_assumptions_for_scenario("base"), "forward_net_income": fwd_ni, "forward_fiscal_year": fwd_year},
        scenario="base",
    )

    def _fair(vals: list, model: str) -> float | None:
        return next((r.fair_value for r in vals if r.model == model and r.fair_value is not None), None)

    assert _fair(vals_seeded, "ddm") > _fair(vals_base, "ddm")
    assert _fair(vals_seeded, "residual_income") > _fair(vals_base, "residual_income")
    # relative_multiples reads snapshot ratios, not the projection — must be unaffected.
    assert _fair(vals_seeded, "relative_multiples") == pytest.approx(_fair(vals_base, "relative_multiples"))


def test_forward_ni_seeds_insurer_roe_projection_net_income() -> None:
    """Insurers route through _build_roe_financial_projection — also separate
    from build_projection's default branch. Same seam must fire there."""
    history = [
        _row("WAA", 2022, "NetIncome", 90.0),
        _row("WAA", 2022, "Dividends_Paid", 35.0),
        _row("WAA", 2022, "Total_Equity", 600.0),
        _row("WAA", 2022, "ROE", 0.15),
        _row("WAA", 2023, "NetIncome", 96.0),
        _row("WAA", 2023, "Dividends_Paid", 38.0),
        _row("WAA", 2023, "Total_Equity", 640.0),
        _row("WAA", 2023, "ROE", 0.15),
        _row("WAA", 2024, "NetIncome", 105.0),
        _row("WAA", 2024, "Dividends_Paid", 42.0),
        _row("WAA", 2024, "Total_Equity", 700.0),
        _row("WAA", 2024, "ROE", 0.15),
    ]
    snapshot = FundamentalSnapshot(
        symbol="WAA",
        company_name="Wafa Assurance",
        latest_statement_year=2024,
        metrics={
            "Current_Price": 100.0,
            "Shares_Outstanding": 10.0,
            "MarketCap_Calc": 1000.0,
            "Price_to_Book": 1.4,
            "PER": 9.0,
            "ROE": 0.15,
            "Dividend_Yield": 0.04,
            "Dividend_Payout": 0.40,
        },
        source={"currency": "MAD"},
        as_of_date=dt.date(2025, 4, 30),
    )

    base_assumptions = {**default_assumptions_for_scenario("base"), "_financial_archetype": "insurance"}
    proj_base = build_projection(snapshot, history, base_assumptions, scenario="base")

    fwd_ni = proj_base.statements[0]["net_income"] * 1.5
    fwd_year = proj_base.statements[0]["fiscal_year"]
    seeded_assumptions = {**base_assumptions, "forward_net_income": fwd_ni, "forward_fiscal_year": fwd_year}
    proj_seeded = build_projection(snapshot, history, seeded_assumptions, scenario="base")

    assert proj_seeded.statements[0]["net_income"] == pytest.approx(fwd_ni)
    assert "net_income_forward_seeded" in proj_seeded.warnings

    sectors = {"WAA": "Assurances"}
    _, vals_base = compute_symbol_valuations(
        snapshot=snapshot, history=history, peer_snapshots=[], sectors=sectors,
        assumptions=default_assumptions_for_scenario("base"), scenario="base",
    )
    _, vals_seeded = compute_symbol_valuations(
        snapshot=snapshot, history=history, peer_snapshots=[], sectors=sectors,
        assumptions={**default_assumptions_for_scenario("base"), "forward_net_income": fwd_ni, "forward_fiscal_year": fwd_year},
        scenario="base",
    )

    def _fair(vals: list, model: str) -> float | None:
        return next((r.fair_value for r in vals if r.model == model and r.fair_value is not None), None)

    assert _fair(vals_seeded, "ddm") > _fair(vals_base, "ddm")
    assert _fair(vals_seeded, "residual_income") > _fair(vals_base, "residual_income")


def _stockanalysis_row(symbol: str, year: int, metric: str, value: float) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol=symbol,
        company_name=symbol,
        statement_year=year,
        metric_name=metric,
        metric_value=value,
        raw_metric_name=metric,
        source_sheet="stockanalysis",
        source_field=metric,
        as_of_date=dt.date(year + 1, 4, 30),
    )


def _stockanalysis_bank_history(symbol: str = "ATW") -> list[AnnualMetricRow]:
    # Mirrors the real StockAnalysis-sourced ATW/BCP feed: no "PNB"/"RBE" line
    # items at all -- only "Revenues_Before_Loan_Losses" (= Net_Interest_Income
    # + Total_NonInterest_Income, i.e. PNB under a different label) and
    # "Provision_for_Loan_Losses" (already a COST_OF_RISK_ALIASES entry).
    rows: list[AnnualMetricRow] = []
    rbl_by_year = {2021: 420.0, 2022: 462.0, 2023: 508.2, 2024: 559.02}
    equity_by_year = {2021: 260.0, 2022: 280.0, 2023: 305.0, 2024: 333.0}
    loans_by_year = {2021: 850.0, 2022: 900.0, 2023: 955.0, 2024: 1012.0}
    for year, rbl in rbl_by_year.items():
        loans = loans_by_year[year]
        rbe = rbl * 0.48
        cost = loans * 0.012
        pretax = rbe - cost
        tax = pretax * 0.30
        net_income = pretax - tax
        dividends = net_income * 0.35
        rows.extend(
            [
                _stockanalysis_row(symbol, year, "Revenues_Before_Loan_Losses", rbl),
                _stockanalysis_row(symbol, year, "Loans_Net", loans),
                _stockanalysis_row(symbol, year, "Provision_for_Loan_Losses", cost),
                _stockanalysis_row(symbol, year, "NetIncome", net_income),
                _stockanalysis_row(symbol, year, "Dividendes", dividends),
                _stockanalysis_row(symbol, year, "Total_Equity", equity_by_year[year]),
                _stockanalysis_row(symbol, year, "Marge_RBE", 0.48),
            ]
        )
    return rows


def test_bank_projection_resolves_pnb_from_stockanalysis_revenues_before_loan_losses() -> None:
    # Regression for the ATW/BCP "unavailable" bank projection: StockAnalysis
    # (data_source="stockanalysis") labels the PNB-equivalent top line
    # "Revenues Before Loan Losses" instead of "PNB"/"Produit_Net_Bancaire".
    # Verified against real BVC-sourced PNB for the same fiscal year (ATW/BCP
    # 2025, <0.2% delta) and as an exact identity (Net_Interest_Income +
    # Total_NonInterest_Income) in the StockAnalysis feed itself -- this is
    # PNB, not a proxy, so it belongs in PNB_ALIASES.
    history = _stockanalysis_bank_history("ATW")
    snapshot = _bank_snapshot("ATW")
    assumptions = {**default_assumptions_for_scenario("base"), "_financial_archetype": "bank"}

    projection = build_projection(snapshot, history, assumptions, scenario="base")

    assert projection.statements, "bank projection must not be empty/unavailable"
    assert "bank_pnb_unavailable_no_history_no_peer" not in projection.warnings
    assert projection.confidence_cap != "unavailable"

    _, results = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=_bank_peers(),
        sectors={"ATW": "Banques", "BCP": "Banques", "BOA": "Banques", "CIH": "Banques"},
        assumptions=default_assumptions_for_scenario("base"),
        scenario="base",
    )
    by_model = {row.model: row for row in results}

    assert by_model["residual_income"].fair_value is not None
    assert by_model["residual_income"].fair_value > 0
    assert by_model["ddm"].fair_value is not None
    assert by_model["ddm"].fair_value > 0
    assert all(
        "bank_projection_unavailable_using_pb_roe_fallback" not in row.warnings for row in results
    )
