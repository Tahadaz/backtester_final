from __future__ import annotations

import datetime as dt

import pytest

from core.quant_core.fundamentals.cost_of_capital import cost_of_equity_capm, wacc_build_up
from core.quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot
from core.quant_core.fundamentals.valuation import DEFAULT_ASSUMPTIONS, compute_symbol_valuations


def _row(metric: str, value: float, year: int) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol="TST",
        company_name="Test",
        statement_year=year,
        metric_name=metric,
        metric_value=value,
        raw_metric_name=metric,
        source_sheet="brief39_fixture",
        as_of_date=dt.date(year + 1, 3, 31),
    )


def _history() -> list[AnnualMetricRow]:
    return [
        _row("Equity_Group", 900.0, 2024),
        _row("Resultat_net_part_du_groupe", 90.0, 2024),
        _row("Equity_Group", 1_100.0, 2025),
        _row("Resultat_net_part_du_groupe", 120.0, 2025),
        _row("Dividendes", 48.0, 2025),
    ]


def _snapshot() -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol="TST",
        company_name="Test",
        latest_statement_year=2025,
        metrics={
            "Current_Price": 100.0,
            "MarketCap_Calc": 1_000.0,
            "Shares_Outstanding": 10.0,
            "Price_to_Book": 1.0,
            "PER": 8.0,
            "Dividend_Yield": 0.048,
            "Dividend_Payout": 0.40,
        },
        source={"currency": "MAD"},
        as_of_date=dt.date(2026, 3, 31),
    )


def _assumptions(*, beta: float, cost_of_equity: float, liquidity_flag: bool = False) -> dict[str, float | dict[str, object]]:
    build = wacc_build_up(
        cost_of_equity=cost_of_equity,
        cost_of_debt=DEFAULT_ASSUMPTIONS["cost_of_debt"],
        tax_rate=DEFAULT_ASSUMPTIONS["tax_rate"],
        equity_weight=DEFAULT_ASSUMPTIONS["default_equity_weight"],
        debt_weight=DEFAULT_ASSUMPTIONS["default_debt_weight"],
    )
    build.update(
        {
            "beta": beta,
            "beta_source": "beta_history",
            "beta_method": "ols",
            "beta_as_of": "2026-06-01",
            "beta_liquidity_flag": liquidity_flag,
            "market_proxy": "MASI",
            "cost_of_equity_floor": DEFAULT_ASSUMPTIONS["cost_of_equity_floor"],
            "cost_of_equity_unfloored": cost_of_equity,
        }
    )
    return {
        **DEFAULT_ASSUMPTIONS,
        "currency": "MAD",
        "cost_of_equity": cost_of_equity,
        "wacc": build["wacc"],
        "cost_of_capital_build_up": build,
    }


def _models_by_name(assumptions: dict[str, object]):
    _eligibility, rows = compute_symbol_valuations(
        snapshot=_snapshot(),
        history=_history(),
        peer_snapshots=[_snapshot()],
        sectors={"TST": "Industrie"},
        assumptions=assumptions,
        scenario="base",
    )
    return {row.model: row for row in rows}


def test_beta_from_assumptions_is_recorded_in_every_model_input() -> None:
    models = _models_by_name(_assumptions(beta=0.44, cost_of_equity=0.065))

    for row in models.values():
        assert row.inputs["beta"] == pytest.approx(0.44)
        assert row.inputs["beta_source"] == "beta_history"
        assert row.inputs["cost_of_equity"] == pytest.approx(0.065)
        assert "default_beta_for_cost_of_equity" not in row.warnings


def test_cost_of_equity_floor_honors_negative_beta_without_reverting_to_one() -> None:
    unfloored = cost_of_equity_capm(risk_free_rate=0.035, beta=-0.02, equity_risk_premium=0.060)
    floored = max(unfloored, DEFAULT_ASSUMPTIONS["cost_of_equity_floor"], DEFAULT_ASSUMPTIONS["risk_free_rate"])

    assert unfloored == pytest.approx(0.0338)
    assert floored == pytest.approx(0.065)
    assert floored != pytest.approx(DEFAULT_ASSUMPTIONS["cost_of_equity"])


def test_consistent_group_basis_roe_across_equity_models() -> None:
    models = _models_by_name(_assumptions(beta=0.80, cost_of_equity=0.083))
    expected = 120.0 / ((900.0 + 1_100.0) / 2.0)

    ddm = models["ddm"]
    residual_income = models["residual_income"]
    justified = models["justified_multiples"]

    assert ddm.inputs["roe"] == pytest.approx(expected)
    assert residual_income.inputs["roe"] == pytest.approx(expected)
    assert justified.inputs["roe"] == pytest.approx(expected)
    assert ddm.inputs["roe_source"] == "group_roe_rnpg_over_avg_group_equity"
    assert residual_income.inputs["roe_source"] == ddm.inputs["roe_source"]
    assert justified.inputs["roe_source"] == ddm.inputs["roe_source"]


def test_group_basis_roe_rejects_scale_inconsistent_previous_equity() -> None:
    history = [
        _row("Equity_Group", 90_000.0, 2024),
        _row("Equity_Group", 360.0, 2025),
        _row("Resultat_net_part_du_groupe", 66.0, 2025),
        _row("Dividendes", 20.0, 2025),
    ]
    _eligibility, rows = compute_symbol_valuations(
        snapshot=_snapshot(),
        history=history,
        peer_snapshots=[_snapshot()],
        sectors={"TST": "Industrie"},
        assumptions=_assumptions(beta=0.80, cost_of_equity=0.083),
        scenario="base",
    )
    models = {row.model: row for row in rows}

    assert models["justified_multiples"].inputs["roe"] == pytest.approx(66.0 / 360.0)
    assert models["justified_multiples"].inputs["roe_source"] == "group_roe_rnpg_over_current_group_equity"


def test_liquidity_flag_carries_confidence_haircut_warning() -> None:
    models = _models_by_name(_assumptions(beta=0.50, cost_of_equity=0.065, liquidity_flag=True))

    ddm = models["ddm"]
    assert "beta_liquidity_flag_confidence_haircut" in ddm.warnings
    assert ddm.inputs["beta_liquidity_flag"] is True
