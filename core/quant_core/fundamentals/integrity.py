from __future__ import annotations

from math import isfinite
from typing import Any

from .domain import IntegrityCheck, IntegrityReport
from .valuation import DEFAULT_ASSUMPTIONS


STATUS_RANK = {"pass": 0, "derived": 1, "warn": 2, "fail": 3}
HAIRCUT_BY_STATUS = {
    "pass": 0.0,
    "derived": 0.05,
    "warn": 0.10,
    "fail": 0.30,
    "unavailable": 0.05,
}


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _value(rows_by_metric: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = _num(rows_by_metric.get(name))
        if value is not None:
            return value
    return None


def _status_from_rel(rel_delta: float, *, pass_threshold: float, warn_threshold: float) -> str:
    abs_rel = abs(rel_delta)
    if abs_rel <= pass_threshold:
        return "pass"
    if abs_rel <= warn_threshold:
        return "warn"
    return "fail"


def _bs_balance(rows_by_metric: dict[str, Any], assumptions: dict[str, float]) -> IntegrityCheck:
    assets = _value(rows_by_metric, "Total_Assets")
    liabilities = _value(rows_by_metric, "Total_Liabilities")
    equity = _value(rows_by_metric, "Total_Equity")
    inputs = {
        "Total_Assets": assets,
        "Total_Liabilities": liabilities,
        "Total_Equity": equity,
    }
    if assets is None or liabilities is None or equity is None:
        return IntegrityCheck(
            name="bs_balance",
            status="unavailable",
            delta=None,
            rel_delta=None,
            inputs=inputs,
            message="bs_balance_unavailable: missing Total_Assets, Total_Liabilities, or Total_Equity",
        )
    delta = assets - liabilities - equity
    rel_delta = delta / max(abs(assets), 1.0)
    pass_threshold = float(assumptions.get("bs_balance_warn_bps", 50.0)) / 10_000.0
    warn_threshold = float(assumptions.get("bs_balance_fail_bps", 200.0)) / 10_000.0
    return IntegrityCheck(
        name="bs_balance",
        status=_status_from_rel(rel_delta, pass_threshold=pass_threshold, warn_threshold=warn_threshold),
        delta=delta,
        rel_delta=rel_delta,
        inputs=inputs,
        message=None,
    )


def _cash_tie_out(rows_by_metric: dict[str, Any]) -> IntegrityCheck:
    ending_cash = _value(rows_by_metric, "CFS_Ending_Cash")
    bs_cash = _value(rows_by_metric, "BS_Cash_and_Equivalents", "Cash_and_Equivalents", "Cash")
    beginning_cash = _value(rows_by_metric, "CFS_Beginning_Cash")
    operating = _value(rows_by_metric, "CF_Operating", "Operating_Cash_Flow")
    investing = _value(rows_by_metric, "CF_Investing")
    financing = _value(rows_by_metric, "CF_Financing")
    fx_effect = _value(rows_by_metric, "CF_FX_Effect")
    derived = False
    if ending_cash is None and beginning_cash is not None:
        parts = [operating, investing, financing, fx_effect or 0.0]
        if all(value is not None for value in parts[:3]):
            ending_cash = beginning_cash + sum(float(value or 0.0) for value in parts)
            derived = True
    inputs = {
        "CFS_Ending_Cash": ending_cash,
        "BS_Cash_and_Equivalents": bs_cash,
        "CFS_Beginning_Cash": beginning_cash,
        "CF_Operating": operating,
        "CF_Investing": investing,
        "CF_Financing": financing,
        "CF_FX_Effect": fx_effect,
    }
    if ending_cash is None or bs_cash is None:
        return IntegrityCheck(
            name="cash_tie_out",
            status="unavailable",
            delta=None,
            rel_delta=None,
            inputs=inputs,
            message="cash_tie_out_unavailable: missing CFS ending cash or BS cash",
        )
    delta = ending_cash - bs_cash
    rel_delta = delta / max(abs(bs_cash), 1.0)
    status = _status_from_rel(rel_delta, pass_threshold=0.01, warn_threshold=0.05)
    if derived:
        status = "derived" if status == "pass" else "warn"
    return IntegrityCheck(
        name="cash_tie_out",
        status=status,
        delta=delta,
        rel_delta=rel_delta,
        inputs=inputs,
        message="derived CFS_Ending_Cash from cash-flow components" if derived else None,
    )


def _ni_link(rows_by_metric: dict[str, Any]) -> IntegrityCheck:
    is_net_income = _value(rows_by_metric, "IS_Net_Income", "Resultat_net", "NetIncome")
    cfs_net_income = _value(rows_by_metric, "CFS_Net_Income_Top_Of_CFS")
    inputs = {
        "IS_Net_Income": is_net_income,
        "CFS_Net_Income_Top_Of_CFS": cfs_net_income,
    }
    if is_net_income is None or cfs_net_income is None:
        return IntegrityCheck(
            name="ni_link",
            status="unavailable",
            delta=None,
            rel_delta=None,
            inputs=inputs,
            message="ni_link_unavailable: cannot verify IS to CFS net income link",
        )
    delta = is_net_income - cfs_net_income
    rel_delta = delta / max(abs(is_net_income), 1.0)
    return IntegrityCheck(
        name="ni_link",
        status=_status_from_rel(rel_delta, pass_threshold=0.005, warn_threshold=0.02),
        delta=delta,
        rel_delta=rel_delta,
        inputs=inputs,
        message=None,
    )


def overall_status(checks: list[IntegrityCheck]) -> str:
    ranked = [check.status for check in checks if check.status != "unavailable"]
    if not ranked:
        return "unavailable"
    return max(ranked, key=lambda status: STATUS_RANK.get(status, -1))


def build_integrity_report(
    symbol: str,
    statement_year: int,
    rows_by_metric: dict[str, float | None],
    assumptions: dict[str, float] = DEFAULT_ASSUMPTIONS,
) -> IntegrityReport:
    checks = [
        _bs_balance(rows_by_metric, assumptions),
        _cash_tie_out(rows_by_metric),
        _ni_link(rows_by_metric),
    ]
    status = overall_status(checks)
    return IntegrityReport(
        symbol=symbol.upper(),
        statement_year=int(statement_year),
        checks=checks,
        overall_status=status,
        confidence_haircut=HAIRCUT_BY_STATUS.get(status, 0.0),
    )


def report_to_dict(report: IntegrityReport) -> dict[str, Any]:
    return {
        "symbol": report.symbol,
        "statement_year": report.statement_year,
        "overall_status": report.overall_status,
        "confidence_haircut": report.confidence_haircut,
        "checks": [
            {
                "name": check.name,
                "status": check.status,
                "delta": check.delta,
                "rel_delta": check.rel_delta,
                "inputs": check.inputs,
                "message": check.message,
            }
            for check in report.checks
        ],
        "projected_statements": report.projected_statements,
        "projection_checks": [
            {
                "name": check.name,
                "status": check.status,
                "delta": check.delta,
                "rel_delta": check.rel_delta,
                "inputs": check.inputs,
                "message": check.message,
            }
            for check in report.projection_checks
        ],
    }


def report_from_dict(data: dict[str, Any]) -> IntegrityReport:
    checks = [
        IntegrityCheck(
            name=str(item.get("name")),
            status=str(item.get("status")),
            delta=_num(item.get("delta")),
            rel_delta=_num(item.get("rel_delta")),
            inputs={str(k): _num(v) for k, v in dict(item.get("inputs") or {}).items()},
            message=item.get("message"),
        )
        for item in list(data.get("checks") or [])
        if isinstance(item, dict)
    ]
    projection_checks = [
        IntegrityCheck(
            name=str(item.get("name")),
            status=str(item.get("status")),
            delta=_num(item.get("delta")),
            rel_delta=_num(item.get("rel_delta")),
            inputs={str(k): _num(v) for k, v in dict(item.get("inputs") or {}).items()},
            message=item.get("message"),
        )
        for item in list(data.get("projection_checks") or [])
        if isinstance(item, dict)
    ]
    return IntegrityReport(
        symbol=str(data.get("symbol") or "").upper(),
        statement_year=int(data.get("statement_year") or 0),
        checks=checks,
        overall_status=str(data.get("overall_status") or overall_status(checks)),
        confidence_haircut=float(data.get("confidence_haircut") or 0.0),
        projected_statements=list(data.get("projected_statements") or []),
        projection_checks=projection_checks,
    )
