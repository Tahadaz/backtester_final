from __future__ import annotations

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, HTTPException

from core.quant_core.fixed_income import (
    BondDefinition,
    accrued_interest,
    carry,
    clean_price,
    current_yield,
    dirty_price,
    generate_schedule,
    risk_measures,
    shock_table,
    yield_to_maturity,
)

from ..schemas.offshore_lab import BondAnalyticsRequest, BondScenariosRequest

router = APIRouter(prefix="/offshore-lab", tags=["offshore-lab"])
METHODOLOGY = "Discounted cash flows at a flat yield compounded at coupon frequency; Newton-Raphson YTM solver with bisection fallback; analytic duration, convexity and DV01."


def _bond(payload: BondAnalyticsRequest) -> BondDefinition:
    return BondDefinition(**payload.bond.model_dump())


def _ytm(payload: BondAnalyticsRequest, bond: BondDefinition) -> float:
    if payload.quote.type == "yield":
        return payload.quote.value
    if payload.quote.type == "clean_price":
        return yield_to_maturity(bond, payload.settlement_date, clean=payload.quote.value)
    return yield_to_maturity(bond, payload.settlement_date, dirty=payload.quote.value)


def _envelope(payload: BondAnalyticsRequest, results: dict, warnings: list[str], interpretation: str) -> dict:
    frequency = payload.bond.coupon_frequency
    currency = payload.bond.currency.upper()
    return {
        "inputs": payload.model_dump(mode="json"),
        "methodology": METHODOLOGY,
        "data_source": "user-entered",
        "calculation_date": date.today().isoformat(),
        "assumptions": ["bullet redemption", "no default or optionality", "flat yield to maturity", f"{payload.bond.day_count} day count", f"yield compounded {frequency}x per year"],
        "units": {"prices": "per 100 face", "ytm": "decimal per annum", "current_yield": "decimal per annum", "durations": "years", "convexity": "years^2", "dv01_per_100": f"{currency} per 1bp per 100 face", "dv01_position": f"{currency} per 1bp for notional", "scenario_pnl": f"{currency} per 100 face"},
        "warnings": warnings,
        "results": results,
        "interpretation": interpretation,
    }


def _analytics(payload: BondAnalyticsRequest) -> tuple[BondDefinition, float, dict, list[str]]:
    bond = _bond(payload)
    ytm = _ytm(payload, bond)
    dirty = dirty_price(bond, payload.settlement_date, ytm)
    clean = clean_price(bond, payload.settlement_date, ytm)
    accrued = accrued_interest(bond, payload.settlement_date)
    risk = risk_measures(bond, payload.settlement_date, ytm)
    warnings: list[str] = []
    days_to_maturity = (bond.maturity_date - payload.settlement_date).days
    if days_to_maturity <= 30:
        warnings.append("settlement within 30 days of maturity: duration approximations degrade")
    results = {
        "ytm": ytm,
        "clean_price": clean,
        "dirty_price": dirty,
        "accrued_interest": accrued,
        "current_yield": current_yield(bond, clean),
        **asdict(risk),
        "dv01_position": risk.dv01_per_100 * payload.notional / 100.0,
        "cashflows": [{**asdict(flow), "date": flow.date.isoformat()} for flow in generate_schedule(bond, payload.settlement_date)],
    }
    return bond, ytm, results, warnings


@router.post("/bond/analytics")
def bond_analytics(payload: BondAnalyticsRequest) -> dict:
    try:
        bond, ytm, results, warnings = _analytics(payload)
        results["shock_table"] = [asdict(item) for item in shock_table(bond, payload.settlement_date, ytm, [-100, -50, 0, 50, 100])]
        if (bond.maturity_date - payload.settlement_date).days > 30:
            results["carry_30d"] = carry(bond, payload.settlement_date, ytm, 30)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    dv01 = results["dv01_position"]
    interpretation = f"A position DV01 of {dv01:,.2f} {bond.currency} means the {payload.notional:,.0f} {bond.currency} position gains or loses approximately {dv01:,.2f} {bond.currency} for each 1bp parallel yield move. Convexity matters for large shocks."
    return _envelope(payload, results, warnings, interpretation)


@router.post("/bond/scenarios")
def bond_scenarios(payload: BondScenariosRequest) -> dict:
    try:
        bond, ytm, analytics, warnings = _analytics(payload)
        scale = payload.notional / 100.0
        shocks = [{**asdict(item), "exact_pnl_position": item.exact_pnl_per_100 * scale, "approx_pnl_duration_position": item.approx_pnl_duration * scale, "approx_pnl_duration_convexity_position": item.approx_pnl_duration_convexity * scale} for item in shock_table(bond, payload.settlement_date, ytm, payload.shocks_bp)]
        result = {"analytics": analytics, "shock_table": shocks, "carry": carry(bond, payload.settlement_date, ytm, payload.holding_period_days) if payload.holding_period_days is not None else None}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _envelope(payload, result, warnings, "Exact repricing is shown beside duration and duration-plus-convexity approximations; approximation error should be judged by shock size.")
