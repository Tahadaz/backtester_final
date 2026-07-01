from __future__ import annotations

import datetime as dt

import pytest

from core.quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot, PeriodMetricRow
from core.quant_core.fundamentals.projection import (
    annual_rate_to_period_rate,
    available_horizons,
    build_projection,
    projection_integrity_checks,
    scenario_hierarchy_checks,
)
from core.quant_core.fundamentals.valuation import compute_symbol_valuations, default_assumptions_for_scenario


def _row(year: int, metric: str, value: float) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol="AAA",
        company_name="Alpha",
        statement_year=year,
        metric_name=metric,
        metric_value=value,
        as_of_date=dt.date(year + 1, 4, 30),
    )


def _period_row(year: int, period_type: str, period_label: str, metric: str, value: float) -> PeriodMetricRow:
    month = {
        "Q1": 3,
        "Q2": 6,
        "Q3": 9,
        "Q4": 12,
        "H1": 6,
        "H2": 12,
        "FY": 12,
    }[period_label]
    day = 31 if month in {3, 12} else 30
    return PeriodMetricRow(
        symbol="AAA",
        company_name="Alpha",
        fiscal_year=year,
        period_type=period_type,
        period_label=period_label,
        metric_name=metric,
        metric_value=value,
        period_end_date=dt.date(year, month, day).isoformat(),
    )


def _history(*, include_cash_flow: bool = True) -> list[AnnualMetricRow]:
    revenues = {2021: 100.0, 2022: 110.0, 2023: 121.0, 2024: 133.1}
    rows: list[AnnualMetricRow] = []
    for year, revenue in revenues.items():
        rows.extend(
            [
                _row(year, "Revenue", revenue),
                _row(year, "EBIT", revenue * 0.12),
                _row(year, "Depreciation_Amortization", revenue * 0.03),
                _row(year, "Capex", revenue * 0.05),
                _row(year, "Working_Capital", revenue * 0.18),
                _row(year, "NetIncome", revenue * 0.07),
                _row(year, "Dividends_Paid", revenue * 0.025),
                _row(year, "Total_Equity", 200.0 + (year - 2021) * 15.0),
                _row(year, "Total_Debt", 80.0),
                _row(year, "Cash", 25.0 + (year - 2021) * 2.0),
                _row(year, "Total_Assets", 330.0 + (year - 2021) * 15.0),
                _row(year, "Total_Liabilities", 130.0),
            ]
        )
        if include_cash_flow:
            rows.extend(
                [
                    _row(year, "Operating_Cash_Flow", revenue * 0.09),
                    _row(year, "CF_Investing", -revenue * 0.05),
                    _row(year, "Free_Cash_Flow", revenue * 0.04),
                ]
            )
    return rows


def _period_history_from_annual(period_type: str, periods: list[str]) -> list[PeriodMetricRow]:
    rows: list[PeriodMetricRow] = []
    divisor = len(periods)
    for year, revenue in {2021: 100.0, 2022: 110.0, 2023: 121.0, 2024: 133.1}.items():
        for label in periods:
            period_revenue = revenue / divisor
            rows.extend(
                [
                    _period_row(year, period_type, label, "Revenue", period_revenue),
                    _period_row(year, period_type, label, "EBIT", period_revenue * 0.12),
                    _period_row(year, period_type, label, "Depreciation_Amortization", period_revenue * 0.03),
                    _period_row(year, period_type, label, "Capex", period_revenue * 0.05),
                    _period_row(year, period_type, label, "Working_Capital", period_revenue * 0.18),
                    _period_row(year, period_type, label, "NetIncome", period_revenue * 0.07),
                    _period_row(year, period_type, label, "Dividends_Paid", period_revenue * 0.025),
                    _period_row(year, period_type, label, "Total_Equity", 200.0 + (year - 2021) * 15.0),
                    _period_row(year, period_type, label, "Total_Debt", 80.0),
                    _period_row(year, period_type, label, "Cash", 25.0 + (year - 2021) * 2.0),
                    _period_row(year, period_type, label, "Total_Assets", 330.0 + (year - 2021) * 15.0),
                    _period_row(year, period_type, label, "Total_Liabilities", 130.0),
                    _period_row(year, period_type, label, "Operating_Cash_Flow", period_revenue * 0.09),
                    _period_row(year, period_type, label, "CF_Investing", -period_revenue * 0.05),
                    _period_row(year, period_type, label, "Free_Cash_Flow", period_revenue * 0.04),
                ]
            )
    return rows


def _snapshot() -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol="AAA",
        company_name="Alpha",
        latest_statement_year=2024,
        metrics={
            "Current_Price": 100.0,
            "Shares_Outstanding": 10.0,
            "MarketCap_Calc": 1000.0,
            "Price_to_Book": 4.2,
            "PER": 12.0,
            "ROE": 0.14,
        },
        source={"currency": "MAD"},
        as_of_date=dt.date(2025, 4, 30),
    )


def test_driver_defaults_reproduce_history_rule() -> None:
    assumptions = default_assumptions_for_scenario("base")
    projection = build_projection(_snapshot(), _history(), assumptions, scenario="base")

    growth_driver = projection.drivers["revenue_growth"]
    years = sorted(growth_driver.projected_by_year)

    assert growth_driver.inputs["cagr_3y"] == pytest.approx(0.10)
    assert growth_driver.inputs["last_year_growth"] == pytest.approx(0.10)
    assert growth_driver.inputs["historical_growth_upper_bound"] == pytest.approx(0.10)
    assert "growth_cap" not in growth_driver.inputs
    assert growth_driver.projected_by_year[years[0]] == pytest.approx(0.10)
    assert growth_driver.projected_by_year[years[-1]] == pytest.approx(assumptions["terminal_growth"])
    assert "blend(3y revenue CAGR" in growth_driver.method
    assert growth_driver.historical_series[-1] == {"year": 2024, "value": pytest.approx(0.10)}


def test_projection_ties_out_and_carries_integrity_checks() -> None:
    projection = build_projection(_snapshot(), _history(), default_assumptions_for_scenario("base"), scenario="base")

    assert projection.fallback is False
    assert projection.statements
    for statement in projection.statements:
        assert statement["total_assets"] == pytest.approx(statement["ending_cash"] + statement["non_cash_assets"])
        assert statement["total_assets"] == pytest.approx(statement["total_liabilities_and_equity"])
        assert statement["ending_cash"] == pytest.approx(statement["cash"])
    assert all(check.status == "pass" for check in projection.integrity_checks if check.status != "unavailable")
    as_dict = projection.to_dict()
    assert as_dict["growth_decomposition"]["revenue_growth"]
    assert as_dict["growth_decomposition"]["projected_revenue_growth"]


def test_period_rate_round_trips_to_annual_rate() -> None:
    for periods_per_year in (1, 2, 4):
        annual = 0.077225
        period = annual_rate_to_period_rate(annual, periods_per_year)
        assert (1.0 + period) ** periods_per_year - 1.0 == pytest.approx(annual)


def test_available_horizons_require_same_period_observations() -> None:
    annual_only: list[PeriodMetricRow] = []
    assert available_horizons(annual_only) == {"year"}

    quarterly = _period_history_from_annual("quarterly", ["Q1", "Q2", "Q3", "Q4"])
    semiannual = _period_history_from_annual("semiannual", ["H1", "H2"])
    assert available_horizons(quarterly + semiannual) == {"quarter", "semester", "year"}


def test_quarterly_projection_uses_same_period_yoy_not_flat_annual_split() -> None:
    rows: list[PeriodMetricRow] = []
    seasonal = {"Q1": 10.0, "Q2": 20.0, "Q3": 30.0, "Q4": 80.0}
    for year, growth in {2021: 1.00, 2022: 1.10, 2023: 1.21, 2024: 1.331}.items():
        for label, base_revenue in seasonal.items():
            revenue = base_revenue * growth
            rows.extend(
                [
                    _period_row(year, "quarterly", label, "Revenue", revenue),
                    _period_row(year, "quarterly", label, "EBIT", revenue * 0.12),
                    _period_row(year, "quarterly", label, "Total_Equity", 200.0),
                    _period_row(year, "quarterly", label, "Total_Debt", 80.0),
                    _period_row(year, "quarterly", label, "Cash", 25.0),
                    _period_row(year, "quarterly", label, "Total_Assets", 330.0),
                    _period_row(year, "quarterly", label, "Total_Liabilities", 130.0),
                ]
            )

    projection = build_projection(
        _snapshot(),
        _history(),
        default_assumptions_for_scenario("base"),
        scenario="base",
        period_history=rows,
        period_type="quarterly",
        periods_per_year=4,
    )

    first_year = projection.statements[:4]
    q1 = next(row for row in first_year if row["period_label"] == "Q1")
    q4 = next(row for row in first_year if row["period_label"] == "Q4")

    assert q4["revenue"] > q1["revenue"] * 5
    assert q1["revenue"] != pytest.approx(sum(row["revenue"] for row in first_year) / 4)


def test_intrinsic_value_is_approximately_invariant_to_projection_granularity() -> None:
    snapshot = _snapshot()
    history = _history()
    assumptions = {
        **default_assumptions_for_scenario("base"),
        "terminal_growth": 0.02,
        "terminal_growth_firm": 0.02,
        "terminal_growth_equity": 0.02,
        "wacc": 0.09,
        "cost_of_equity": 0.10,
    }
    annual_projection = build_projection(snapshot, history, assumptions, scenario="base")
    semi_projection = build_projection(
        snapshot,
        history,
        assumptions,
        scenario="base",
        period_history=_period_history_from_annual("semiannual", ["H1", "H2"]),
        period_type="semiannual",
        periods_per_year=2,
    )
    quarterly_projection = build_projection(
        snapshot,
        history,
        assumptions,
        scenario="base",
        period_history=_period_history_from_annual("quarterly", ["Q1", "Q2", "Q3", "Q4"]),
        period_type="quarterly",
        periods_per_year=4,
    )

    fair_values = []
    for projection in (annual_projection, semi_projection, quarterly_projection):
        _eligibility, valuations = compute_symbol_valuations(
            snapshot=snapshot,
            history=history,
            peer_snapshots=[snapshot],
            assumptions={**assumptions, "_projection": projection},
        )
        fair = next(row for row in valuations if row.model == "fcff_dcf").fair_value
        assert fair is not None
        fair_values.append(fair)

    annual = fair_values[0]
    assert fair_values[1] == pytest.approx(annual, rel=0.01)
    assert fair_values[2] == pytest.approx(annual, rel=0.01)


def test_projection_balance_check_uses_completed_statement_and_gap_diagnostic() -> None:
    projection = build_projection(_snapshot(), _history(), default_assumptions_for_scenario("base"), scenario="base")
    statement = dict(projection.statements[0])
    statement["projection_bs_pre_plug_delta"] = float(statement["total_assets"]) * 0.05
    statement["balance_sheet_plug"] = statement["projection_bs_pre_plug_delta"]

    checks = projection_integrity_checks([statement], starting_equity=245.0)
    gap = next(check for check in checks if check.name.startswith("projection_financing_gap_"))
    balance = next(check for check in checks if check.name.startswith("projection_bs_balance_"))

    assert gap.status == "warn"
    assert gap.delta == pytest.approx(statement["projection_bs_pre_plug_delta"])
    assert balance.status == "pass"
    assert balance.delta == pytest.approx(0.0)


def test_no_cash_flow_statement_uses_capped_driver_fallback() -> None:
    projection = build_projection(_snapshot(), _history(include_cash_flow=False), default_assumptions_for_scenario("base"), scenario="base")

    assert projection.fallback is True
    assert projection.confidence_cap == "low"
    assert "cash_flow_statement_missing_driver_fallback" in projection.warnings
    assert len(projection.fcff) == 5
    assert projection.drivers["fcff"].warning == "direct_driver_fcff_fallback"


def test_driver_override_changes_fair_value_deterministically() -> None:
    snapshot = _snapshot()
    history = _history()
    assumptions = default_assumptions_for_scenario("base")
    base_projection = build_projection(snapshot, history, assumptions, scenario="base")
    bull_projection = build_projection(snapshot, history, assumptions, scenario="base", overrides={"revenue_growth": [0.16, 0.13, 0.10, 0.07, 0.04]})

    _, base_values = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot],
        assumptions={**assumptions, "_projection": base_projection},
    )
    _, bull_values = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot],
        assumptions={**assumptions, "_projection": bull_projection},
    )
    base_fcff = next(row for row in base_values if row.model == "fcff_dcf")
    bull_fcff = next(row for row in bull_values if row.model == "fcff_dcf")

    assert bull_fcff.fair_value is not None
    assert base_fcff.fair_value is not None
    assert bull_fcff.fair_value > base_fcff.fair_value


def test_divergence_and_scenario_hierarchy_checks() -> None:
    snapshot = _snapshot()
    history = _history()
    assumptions = default_assumptions_for_scenario("base")
    divergent = build_projection(snapshot, history, assumptions, scenario="base", overrides={"revenue_growth": [0.30, 0.20, 0.12, 0.07, 0.03]})
    assert divergent.drivers["revenue_growth"].warning == "revenue_growth_diverges_from_history"

    projections = {
        "bear": build_projection(snapshot, history, assumptions, scenario="bear", overrides={"revenue_growth": [0.02] * 5, "ebit_margin": [0.10] * 5}),
        "base": build_projection(snapshot, history, assumptions, scenario="base", overrides={"revenue_growth": [0.05] * 5, "ebit_margin": [0.12] * 5}),
        "bull": build_projection(snapshot, history, assumptions, scenario="bull", overrides={"revenue_growth": [0.08] * 5, "ebit_margin": [0.14] * 5}),
    }
    checks = scenario_hierarchy_checks(projections)
    assert checks
    assert all(check.status == "pass" for check in checks)


def test_revenue_growth_uses_stock_historical_peak_not_static_cap() -> None:
    history = [
        _row(2021, "Revenue", 100.0),
        _row(2022, "Revenue", 130.0),
        _row(2023, "Revenue", 195.0),
        _row(2024, "Revenue", 312.0),
        _row(2021, "EBIT", 10.0),
        _row(2022, "EBIT", 13.0),
        _row(2023, "EBIT", 19.5),
        _row(2024, "EBIT", 31.2),
    ]

    projection = build_projection(_snapshot(), history, default_assumptions_for_scenario("base"), scenario="base")
    growth_driver = projection.drivers["revenue_growth"]
    first_year = min(growth_driver.projected_by_year)

    assert growth_driver.inputs["historical_growth_upper_bound"] > 0.10
    assert growth_driver.projected_by_year[first_year] > 0.10


def test_year_one_ebit_margin_anchors_on_latest_realized_margin() -> None:
    history = [
        _row(2022, "Revenue", 100.0),
        _row(2022, "EBIT", 10.0),
        _row(2023, "Revenue", 110.0),
        _row(2023, "EBIT", 11.0),
        _row(2024, "Revenue", 121.0),
        _row(2024, "EBIT", 36.3),
        _row(2024, "Total_Equity", 200.0),
        _row(2024, "Total_Debt", 80.0),
        _row(2024, "Cash", 25.0),
        _row(2024, "Total_Assets", 330.0),
        _row(2024, "Total_Liabilities", 130.0),
    ]

    projection = build_projection(_snapshot(), history, default_assumptions_for_scenario("base"), scenario="base")
    margin_driver = projection.drivers["ebit_margin"]
    first_year = min(margin_driver.projected_by_year)

    assert margin_driver.projected_by_year[first_year] == pytest.approx(margin_driver.inputs["latest_margin"])


def test_high_capex_projection_fades_to_positive_terminal_fcff_and_nonzero_dcf() -> None:
    history: list[AnnualMetricRow] = []
    for year, revenue in {2021: 1_000.0, 2022: 1_150.0, 2023: 1_300.0, 2024: 1_450.0}.items():
        history.extend(
            [
                _row(year, "Revenue", revenue),
                _row(year, "EBIT", revenue * 0.25),
                _row(year, "Depreciation_Amortization", revenue * 0.05),
                _row(year, "Capex", revenue * 0.70),
                _row(year, "Working_Capital", revenue * 0.10),
                _row(year, "Total_Equity", 800.0),
                _row(year, "Total_Debt", 0.0),
                _row(year, "Cash", 0.0),
                _row(year, "Total_Assets", 800.0),
                _row(year, "Total_Liabilities", 0.0),
                _row(year, "Operating_Cash_Flow", revenue * 0.20),
                _row(year, "CF_Investing", -revenue * 0.70),
                _row(year, "Free_Cash_Flow", -revenue * 0.50),
            ]
        )
    snapshot = _snapshot()
    assumptions = {
        **default_assumptions_for_scenario("base"),
        "maintenance_capex_pct": 0.04,
        "terminal_growth": 0.02,
        "terminal_growth_firm": 0.02,
        "wacc": 0.09,
    }
    projection = build_projection(snapshot, history, assumptions, scenario="base")

    capex_driver = projection.drivers["capex_pct"]
    capex_years = sorted(capex_driver.projected_by_year)
    assert capex_driver.inputs["current_capex_pct"] == pytest.approx(0.70)
    assert capex_driver.inputs["maintenance_capex_pct"] == pytest.approx(0.05)
    assert capex_driver.projected_by_year[capex_years[0]] == pytest.approx(0.70)
    assert capex_driver.projected_by_year[capex_years[-1]] == pytest.approx(0.05)
    assert projection.fcff[0] < 0
    assert projection.fcff[-1] > 0

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot],
        assumptions={**assumptions, "_projection": projection},
    )
    fcff = next(row for row in valuations if row.model == "fcff_dcf")

    assert fcff.fair_value is not None
    assert fcff.fair_value > 0


# ---------------------------------------------------------------------------
# brief 54 §3 Phase 3.2: forward-estimate seeding for fcff_dcf
# ---------------------------------------------------------------------------

def _history_iam_like() -> list[AnnualMetricRow]:
    """IAM-like history: latest_statement_year=2025, 10% CAGR, 30% EBIT margin."""
    revenues = {2021: 30_000.0, 2022: 33_000.0, 2023: 36_300.0, 2024: 39_930.0, 2025: 43_923.0}
    rows: list[AnnualMetricRow] = []
    for year, rev in revenues.items():
        rows.extend([
            _row(year, "Revenue", rev),
            _row(year, "EBIT", rev * 0.30),
            _row(year, "Depreciation_Amortization", rev * 0.08),
            _row(year, "Capex", rev * 0.12),
            _row(year, "Working_Capital", rev * 0.05),
            _row(year, "NetIncome", rev * 0.17),
            _row(year, "Total_Equity", 60_000.0),
            _row(year, "Total_Debt", 15_000.0),
            _row(year, "Cash", 5_000.0),
            _row(year, "Total_Assets", 80_000.0),
            _row(year, "Total_Liabilities", 20_000.0),
            _row(year, "Operating_Cash_Flow", rev * 0.22),
            _row(year, "CF_Investing", -rev * 0.12),
            _row(year, "Free_Cash_Flow", rev * 0.10),
        ])
    return rows


def _snapshot_2025() -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol="TST",
        company_name="Test",
        latest_statement_year=2025,
        metrics={"Current_Price": 100.0, "Shares_Outstanding": 879.1},
        source={"currency": "MAD"},
        as_of_date=dt.date(2026, 6, 28),
    )


def test_forward_revenue_seeds_near_year_growth() -> None:
    """When forward_revenue is present for start_year+1, year-1 growth must be
    derived from it rather than from the mechanical trailing CAGR."""
    history = _history_iam_like()
    snap = _snapshot_2025()
    # 2026 forward revenue implies ~+2.9% growth (vs trailing 10% CAGR) — well within floor
    fwd_rev = 43_923.0 * 1.029
    assumptions = {
        **default_assumptions_for_scenario("base"),
        "forward_revenue": fwd_rev,
        "forward_net_income": fwd_rev * 0.14,
        "forward_fiscal_year": 2026,
    }

    proj_with = build_projection(snap, history, assumptions, scenario="base")
    proj_without = build_projection(snap, history, default_assumptions_for_scenario("base"), scenario="base")

    growth_driver = proj_with.drivers["revenue_growth"]
    years = sorted(growth_driver.projected_by_year)
    seeded_year1_growth = growth_driver.projected_by_year[years[0]]
    mechanical_year1_growth = proj_without.drivers["revenue_growth"].projected_by_year[years[0]]

    # Seeded growth must differ from mechanical CAGR (~10%)
    assert seeded_year1_growth != pytest.approx(mechanical_year1_growth, rel=0.01)
    # Seeded growth should be near +2.9%
    assert seeded_year1_growth == pytest.approx(0.029, abs=0.002)
    # Method string must mention "forward revenue"
    assert "forward revenue" in growth_driver.method


def test_forward_ni_seeds_near_year_ebit_margin() -> None:
    """When forward_revenue and forward_net_income are both present, year-1 EBIT
    margin must be seeded from NI/Rev gross-up, not from trailing margin."""
    history = _history_iam_like()
    snap = _snapshot_2025()
    # Imply a lower forward EBIT margin: NI margin = 14%, tax=35% → EBIT≈21.5%
    fwd_rev = 43_923.0 * 1.05
    fwd_ni = fwd_rev * 0.14
    assumptions = {
        **default_assumptions_for_scenario("base"),
        "forward_revenue": fwd_rev,
        "forward_net_income": fwd_ni,
        "forward_fiscal_year": 2026,
        "tax_rate": 0.35,
    }

    proj = build_projection(snap, history, assumptions, scenario="base")

    margin_driver = proj.drivers["ebit_margin"]
    years = sorted(margin_driver.projected_by_year)
    year1_margin = margin_driver.projected_by_year[years[0]]

    expected_ebit_margin = (fwd_ni / fwd_rev) / (1.0 - 0.35)  # ≈ 0.2154
    assert year1_margin == pytest.approx(expected_ebit_margin, abs=0.005)
    assert "forward NI/Rev" in margin_driver.method
    assert margin_driver.inputs["forward_seeded_ebit_margin"] is not None


def test_forward_seeding_does_not_apply_for_non_adjacent_year() -> None:
    """If forward_fiscal_year is start_year+2 (not the immediate next year),
    seeding must NOT fire — year-1 growth must remain mechanical."""
    history = _history_iam_like()
    snap = _snapshot_2025()
    assumptions = {
        **default_assumptions_for_scenario("base"),
        "forward_revenue": 40_000.0,
        "forward_fiscal_year": 2027,  # two years out, not adjacent
    }

    proj_seeded = build_projection(snap, history, assumptions, scenario="base")
    proj_baseline = build_projection(snap, history, default_assumptions_for_scenario("base"), scenario="base")

    years = sorted(proj_seeded.drivers["revenue_growth"].projected_by_year)
    year1_seeded = proj_seeded.drivers["revenue_growth"].projected_by_year[years[0]]
    year1_base = proj_baseline.drivers["revenue_growth"].projected_by_year[years[0]]

    assert year1_seeded == pytest.approx(year1_base, rel=0.001)
    assert "forward revenue" not in proj_seeded.drivers["revenue_growth"].method


def test_forward_seeding_mechanical_fallback_when_absent() -> None:
    """No forward_revenue in assumptions → projection is identical to baseline."""
    history = _history_iam_like()
    snap = _snapshot_2025()
    assumptions = default_assumptions_for_scenario("base")

    proj = build_projection(snap, history, assumptions, scenario="base")
    years = sorted(proj.drivers["revenue_growth"].projected_by_year)

    # Mechanical 10% CAGR should be used (not a seeded forward value)
    assert proj.drivers["revenue_growth"].projected_by_year[years[0]] == pytest.approx(0.10, abs=0.01)
    assert proj.drivers["ebit_margin"].inputs["forward_seeded_ebit_margin"] is None


def test_forward_seeded_fcff_dcf_differs_from_mechanical() -> None:
    """End-to-end: seeding lower forward revenue → lower fcff_dcf fair value than
    mechanical baseline.  Confirms the wiring propagates through the DCF."""
    history = _history_iam_like()
    snap = _snapshot_2025()

    base_assumptions = default_assumptions_for_scenario("base")
    seeded_assumptions = {
        **base_assumptions,
        # Forward revenue implies ~3% growth vs trailing 10% CAGR — well above floor
        "forward_revenue": 43_923.0 * 1.03,
        "forward_net_income": 43_923.0 * 1.03 * 0.10,  # lower NI margin too
        "forward_fiscal_year": 2026,
    }

    proj_base = build_projection(snap, history, base_assumptions, scenario="base")
    proj_seeded = build_projection(snap, history, seeded_assumptions, scenario="base")

    _, vals_base = compute_symbol_valuations(
        snapshot=snap, history=history, peer_snapshots=[snap],
        assumptions={**base_assumptions, "_projection": proj_base},
    )
    _, vals_seeded = compute_symbol_valuations(
        snapshot=snap, history=history, peer_snapshots=[snap],
        assumptions={**seeded_assumptions, "_projection": proj_seeded},
    )

    def _fcff(vals: list) -> float:
        return next(r.fair_value for r in vals if r.model == "fcff_dcf" and r.fair_value is not None)

    fv_base = _fcff(vals_base)
    fv_seeded = _fcff(vals_seeded)

    # Lower near-year revenue should produce a lower DCF fair value
    assert fv_seeded < fv_base, f"Seeded FV {fv_seeded:.1f} should be < mechanical FV {fv_base:.1f}"


def _history_iam_like_with_dividends() -> list[AnnualMetricRow]:
    """Same as _history_iam_like but with a dividend line so payout_ratio is
    derivable from history (needed to exercise the ddm projected-dividends path)."""
    history = _history_iam_like()
    revenue_by_year = {row.statement_year: row.metric_value for row in history if row.metric_name == "Revenue"}
    dividend_rows = [_row(year, "Dividendes", rev * 0.17 * 0.40) for year, rev in revenue_by_year.items()]
    return history + dividend_rows


def test_forward_ni_seeds_near_year_net_income_directly() -> None:
    """forward_net_income alone (no forward_revenue) must override year-1 net
    income directly — this is the BKGR-only seam (BKGR has no revenue line)."""
    history = _history_iam_like_with_dividends()
    snap = _snapshot_2025()
    fwd_ni = 43_923.0 * 0.17 * 1.5  # well above trailing NI (~7,467)
    assumptions = {
        **default_assumptions_for_scenario("base"),
        "forward_net_income": fwd_ni,
        "forward_fiscal_year": 2026,
    }

    proj = build_projection(snap, history, assumptions, scenario="base")
    proj_base = build_projection(snap, history, default_assumptions_for_scenario("base"), scenario="base")

    assert proj.statements[0]["net_income"] == pytest.approx(fwd_ni)
    # Revenue/margin path must be untouched — no forward_revenue was supplied.
    assert proj.statements[0]["revenue"] == pytest.approx(proj_base.statements[0]["revenue"])
    assert "net_income_forward_seeded" in proj.warnings


def test_forward_ni_seeding_does_not_apply_for_non_adjacent_year() -> None:
    """forward_fiscal_year two years out must not seed year-1 net income."""
    history = _history_iam_like_with_dividends()
    snap = _snapshot_2025()
    assumptions = {
        **default_assumptions_for_scenario("base"),
        "forward_net_income": 999_999.0,
        "forward_fiscal_year": 2027,
    }

    proj = build_projection(snap, history, assumptions, scenario="base")

    assert proj.statements[0]["net_income"] != pytest.approx(999_999.0)
    assert "net_income_forward_seeded" not in proj.warnings


def test_forward_ni_seeds_ddm_and_residual_income_without_forward_revenue() -> None:
    """End-to-end: BKGR-only names (forward_net_income, no forward_revenue) must
    see ddm/residual_income move off the forward seed, while fcff_dcf — which
    needs forward revenue/margin — stays mechanical (brief 54 §3 model-mapping
    table: BKGR upgrades earnings/equity models, not fcff_dcf)."""
    history = _history_iam_like_with_dividends()
    # residual_income requires Price_to_Book for eligibility (has_book_roe);
    # _snapshot_2025 doesn't carry it, so build a local snapshot that does.
    snap = FundamentalSnapshot(
        symbol="TST",
        company_name="Test",
        latest_statement_year=2025,
        metrics={"Current_Price": 100.0, "Shares_Outstanding": 879.1, "Price_to_Book": 1.47},
        source={"currency": "MAD"},
        as_of_date=dt.date(2026, 6, 28),
    )

    base_assumptions = default_assumptions_for_scenario("base")
    fwd_ni = 43_923.0 * 0.17 * 1.5
    seeded_assumptions = {
        **base_assumptions,
        "forward_net_income": fwd_ni,
        "forward_fiscal_year": 2026,
    }

    proj_base = build_projection(snap, history, base_assumptions, scenario="base")
    proj_seeded = build_projection(snap, history, seeded_assumptions, scenario="base")

    _, vals_base = compute_symbol_valuations(
        snapshot=snap, history=history, peer_snapshots=[snap],
        assumptions={**base_assumptions, "_projection": proj_base},
    )
    _, vals_seeded = compute_symbol_valuations(
        snapshot=snap, history=history, peer_snapshots=[snap],
        assumptions={**seeded_assumptions, "_projection": proj_seeded},
    )

    def _fair(vals: list, model: str) -> float | None:
        return next((r.fair_value for r in vals if r.model == model and r.fair_value is not None), None)

    ddm_base, ddm_seeded = _fair(vals_base, "ddm"), _fair(vals_seeded, "ddm")
    ri_base, ri_seeded = _fair(vals_base, "residual_income"), _fair(vals_seeded, "residual_income")
    fcff_base, fcff_seeded = _fair(vals_base, "fcff_dcf"), _fair(vals_seeded, "fcff_dcf")

    assert ddm_base is not None and ddm_seeded is not None
    assert ddm_seeded > ddm_base
    assert ri_base is not None and ri_seeded is not None
    assert ri_seeded > ri_base
    # No forward_revenue supplied → fcff_dcf must be bit-for-bit unaffected.
    assert fcff_base == pytest.approx(fcff_seeded)


def test_period_projection_seeds_forward_revenue_and_net_income() -> None:
    """Quarterly/semiannual projections had zero forward seeding until now —
    they're display-only (valuation reads the annual projection), but a UI
    showing a mechanical quarterly path next to a consensus-seeded annual
    figure is a real inconsistency. forward_revenue/forward_net_income must
    seed the block of periods making up the immediate next fiscal year,
    with the block's summed revenue/net_income landing exactly on the
    consensus figures (brief 54 §3.3)."""
    snap = _snapshot()
    history = _history()
    period_history = _period_history_from_annual("quarterly", ["Q1", "Q2", "Q3", "Q4"])
    base_assumptions = default_assumptions_for_scenario("base")

    proj_base = build_projection(
        snap, history, base_assumptions, scenario="base",
        period_history=period_history, period_type="quarterly", periods_per_year=4,
    )
    fwd_year = proj_base.statements[0]["fiscal_year"]
    fwd_rev = sum(s["revenue"] for s in proj_base.statements[:4]) * 1.2
    fwd_ni = sum(s["net_income"] for s in proj_base.statements[:4]) * 1.5
    seeded_assumptions = {
        **base_assumptions,
        "forward_revenue": fwd_rev,
        "forward_net_income": fwd_ni,
        "forward_fiscal_year": fwd_year,
    }

    proj_seeded = build_projection(
        snap, history, seeded_assumptions, scenario="base",
        period_history=period_history, period_type="quarterly", periods_per_year=4,
    )

    block = proj_seeded.statements[:4]
    assert all(s["fiscal_year"] == fwd_year for s in block)
    assert sum(s["revenue"] for s in block) == pytest.approx(fwd_rev)
    assert sum(s["net_income"] for s in block) == pytest.approx(fwd_ni)
    assert "net_income_forward_seeded" in proj_seeded.warnings
    # The year after the seeded block must roll forward off the new (higher)
    # revenue base, not silently revert to the unseeded mechanical trajectory.
    assert proj_seeded.statements[4]["revenue"] > proj_base.statements[4]["revenue"]


def test_period_projection_ni_only_seed_without_forward_revenue() -> None:
    """BKGR-only case at period granularity: forward_net_income alone (no
    forward_revenue) must still seed the block's net_income via equal split,
    while revenue/margin stay mechanical."""
    snap = _snapshot()
    history = _history()
    period_history = _period_history_from_annual("quarterly", ["Q1", "Q2", "Q3", "Q4"])
    base_assumptions = default_assumptions_for_scenario("base")

    proj_base = build_projection(
        snap, history, base_assumptions, scenario="base",
        period_history=period_history, period_type="quarterly", periods_per_year=4,
    )
    fwd_year = proj_base.statements[0]["fiscal_year"]
    fwd_ni = sum(s["net_income"] for s in proj_base.statements[:4]) * 1.5
    seeded_assumptions = {**base_assumptions, "forward_net_income": fwd_ni, "forward_fiscal_year": fwd_year}

    proj_seeded = build_projection(
        snap, history, seeded_assumptions, scenario="base",
        period_history=period_history, period_type="quarterly", periods_per_year=4,
    )

    block = proj_seeded.statements[:4]
    assert sum(s["net_income"] for s in block) == pytest.approx(fwd_ni)
    assert all(ni == pytest.approx(fwd_ni / 4) for ni in (s["net_income"] for s in block))
    assert sum(s["revenue"] for s in block) == pytest.approx(sum(s["revenue"] for s in proj_base.statements[:4]))
    assert "net_income_forward_seeded" in proj_seeded.warnings


def test_period_projection_forward_seeding_requires_immediate_next_year() -> None:
    """forward_fiscal_year two years out must not seed any period block —
    mirrors the annual gate exactly."""
    snap = _snapshot()
    history = _history()
    period_history = _period_history_from_annual("quarterly", ["Q1", "Q2", "Q3", "Q4"])
    base_assumptions = default_assumptions_for_scenario("base")

    proj_base = build_projection(
        snap, history, base_assumptions, scenario="base",
        period_history=period_history, period_type="quarterly", periods_per_year=4,
    )
    non_adjacent_year = proj_base.statements[0]["fiscal_year"] + 1
    seeded_assumptions = {
        **base_assumptions,
        "forward_net_income": 999_999.0,
        "forward_revenue": 999_999.0,
        "forward_fiscal_year": non_adjacent_year,
    }

    proj_seeded = build_projection(
        snap, history, seeded_assumptions, scenario="base",
        period_history=period_history, period_type="quarterly", periods_per_year=4,
    )

    assert "net_income_forward_seeded" not in proj_seeded.warnings
    for statement in proj_seeded.statements:
        assert statement["net_income"] != pytest.approx(999_999.0 / 4)
