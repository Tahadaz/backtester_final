from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
from typing import Any

from .domain import DataTieOutReport, IntegrityCheck, IntegrityReport
from .minority import resolve_minority_roe_basis
from .valuation import DEFAULT_ASSUMPTIONS


STATUS_RANK = {"pass": 0, "derived": 1, "warn": 2, "fail": 3}
HAIRCUT_BY_STATUS = {
    "pass": 0.0,
    "derived": 0.05,
    "warn": 0.10,
    "fail": 0.30,
    "unavailable": 0.05,
}
CORE_TIEOUT_METRICS = {
    "Total_Assets",
    "Total_Liabilities",
    "Total_Liabilities_And_Equity",
    "Total_Equity",
    "Total_Equity_Group",
    "Equity_Group",
    "Capitaux_propres_part_du_groupe",
    "Minority_Interest",
    "Interets_minoritaires",
    "Shares_Outstanding",
    "BVPS",
    "Book_Value_Per_Share",
    "NetIncome",
    "Net_Income",
    "Resultat_net",
    "Resultat_net_part_du_groupe",
    "NetIncome_Group",
    "ROE",
    "Return_on_Equity",
    "Price_to_Book",
    "P_B",
    "Current_Price",
}
BLOCKING_TIEOUT_CHECKS = {
    "t1_balance_sheet",
    "t2_equity_per_share",
    "t3_income_consistency",
    "t4_group_basis_roe",
    "t5_single_annual_vintage",
    "t7_plausibility",
}
CORRECTIONS_PATH = Path(__file__).resolve().parent / "data" / "fundamental_corrections.json"


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


def _raw_value(rows_by_metric: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in rows_by_metric and rows_by_metric.get(name) not in (None, ""):
            return rows_by_metric.get(name)
    return None


def _status_from_rel(rel_delta: float, *, pass_threshold: float, warn_threshold: float) -> str:
    abs_rel = abs(rel_delta)
    if abs_rel <= pass_threshold:
        return "pass"
    if abs_rel <= warn_threshold:
        return "warn"
    return "fail"


def _check(
    *,
    name: str,
    status: str,
    delta: float | None = None,
    rel_delta: float | None = None,
    inputs: dict[str, float | None] | None = None,
    message: str | None = None,
) -> IntegrityCheck:
    return IntegrityCheck(
        name=name,
        status=status,
        delta=delta,
        rel_delta=rel_delta,
        inputs=inputs or {},
        message=message,
    )


def _metric_year_issues(metric_years: dict[str, Any], target_year: int) -> dict[str, int]:
    issues: dict[str, int] = {}
    for metric, raw_year in metric_years.items():
        if metric not in CORE_TIEOUT_METRICS:
            continue
        try:
            year = int(raw_year)
        except (TypeError, ValueError):
            continue
        if year != target_year:
            issues[metric] = year
    return issues


def _stored_ratio_delta(stored: float | None, recomputed: float | None) -> tuple[float | None, float | None]:
    if stored is None or recomputed is None:
        return None, None
    delta = stored - recomputed
    return delta, delta / max(abs(recomputed), 1e-9)


def _correction_value(payload: Any) -> float | None:
    if isinstance(payload, dict):
        return _num(payload.get("value"))
    return _num(payload)


def load_curated_corrections(path: Path | None = None) -> dict[str, Any]:
    source = path or CORRECTIONS_PATH
    if not source.exists():
        return {"version": "missing", "symbols": {}}
    with source.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return {"version": "invalid", "symbols": {}}
    symbols = data.get("symbols")
    if not isinstance(symbols, dict):
        data["symbols"] = {}
    return data


def curated_correction_entry(
    symbol: str,
    statement_year: int,
    *,
    corrections: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    payload = corrections if corrections is not None else load_curated_corrections()
    symbols = payload.get("symbols") if isinstance(payload, dict) else None
    if not isinstance(symbols, dict):
        return None
    by_year = symbols.get(str(symbol or "").upper())
    if not isinstance(by_year, dict):
        return None
    entry = by_year.get(str(int(statement_year)))
    return dict(entry) if isinstance(entry, dict) else None


def apply_curated_corrections(
    rows_by_metric: dict[str, Any],
    entry: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    corrected = dict(rows_by_metric or {})
    provenance: dict[str, Any] = {}
    if not entry:
        return corrected, provenance
    corrections = entry.get("corrections")
    if not isinstance(corrections, dict):
        return corrected, provenance
    for metric, payload in corrections.items():
        value = _correction_value(payload)
        corrected[str(metric)] = value
        provenance[str(metric)] = dict(payload) if isinstance(payload, dict) else {"value": value}
    return corrected, provenance


def _t1_balance_sheet(rows_by_metric: dict[str, Any], assumptions: dict[str, float]) -> tuple[IntegrityCheck, dict[str, float | None]]:
    assets = _value(rows_by_metric, "Total_Assets", "Total_Actif", "Actif_Total")
    liabilities = _value(rows_by_metric, "Total_Liabilities", "Total_Debt_And_Liabilities")
    equity = _value(rows_by_metric, "Total_Equity", "Capitaux_propres", "Shareholders_Equity", "Total_Shareholders_Equity")
    total_passif = _value(rows_by_metric, "Total_Liabilities_And_Equity", "Total_Passif", "Passif_Total")
    if liabilities is None and total_passif is not None and equity is not None:
        liabilities = total_passif - equity
    inputs = {
        "Total_Assets": assets,
        "Total_Liabilities": liabilities,
        "Total_Equity": equity,
        "Total_Liabilities_And_Equity": total_passif,
    }
    recomputed = {"Total_Liabilities": liabilities, "Total_Liabilities_And_Equity": total_passif or assets}
    if assets is None or liabilities is None or equity is None:
        return _check(
            name="t1_balance_sheet",
            status="unavailable",
            inputs=inputs,
            message="t1_unavailable: missing assets, liabilities, or equity",
        ), recomputed
    delta = assets - liabilities - equity
    rel_delta = delta / max(abs(assets), 1.0)
    pass_threshold = float(assumptions.get("bs_balance_warn_bps", 50.0)) / 10_000.0
    warn_threshold = float(assumptions.get("bs_balance_fail_bps", 200.0)) / 10_000.0
    status = _status_from_rel(rel_delta, pass_threshold=pass_threshold, warn_threshold=warn_threshold)
    if total_passif is not None:
        passif_delta = assets - total_passif
        passif_rel = passif_delta / max(abs(assets), 1.0)
        if abs(passif_rel) > warn_threshold:
            status = "fail"
            delta = passif_delta
            rel_delta = passif_rel
    return _check(
        name="t1_balance_sheet",
        status=status,
        delta=delta,
        rel_delta=rel_delta,
        inputs=inputs,
        message=None if status == "pass" else "t1_fail: assets do not tie to liabilities plus equity",
    ), recomputed


# BVPS is reported on a group (parent-shareholder) basis. When only consolidated
# Total_Equity is available, the gap between BVPS*shares and Total_Equity is minority
# interest, which is legitimate — not a tie-out failure. Bands below distinguish a normal
# minority slice from a units/shares error masquerading as one.
T2_MINORITY_WARN_FRACTION = 0.45
T2_MINORITY_MAX_FRACTION = 0.60


def _t2_equity_per_share(rows_by_metric: dict[str, Any]) -> tuple[IntegrityCheck, dict[str, float | None]]:
    group_equity = _value(
        rows_by_metric,
        "Equity_Group",
        "Total_Equity_Group",
        "Capitaux_propres_part_du_groupe",
        "Total_Common_Equity",
    )
    total_equity = _value(rows_by_metric, "Total_Equity", "Capitaux_propres")
    minority = _value(rows_by_metric, "Minority_Interest", "Interets_minoritaires")
    # Derive group equity from the consolidated total minus minority interest when the group
    # line is not reported directly (StockAnalysis exposes Total_Equity + BVPS, not the split).
    if group_equity is None and total_equity is not None and minority is not None:
        group_equity = total_equity - minority
    shares = _value(rows_by_metric, "Shares_Outstanding", "Shares", "Nombre_actions")
    stored_bvps = _value(rows_by_metric, "BVPS", "Book_Value_Per_Share")
    inputs = {
        "Equity_Group": group_equity,
        "Total_Equity": total_equity,
        "Minority_Interest": minority,
        "Shares_Outstanding": shares,
        "BVPS": stored_bvps,
    }
    if shares is None or shares <= 0 or (group_equity is None and total_equity is None):
        return _check(
            name="t2_equity_per_share",
            status="unavailable",
            inputs=inputs,
            message="t2_unavailable: missing equity or shares outstanding",
        ), {"BVPS": None}

    # Strict tie-out when group equity is known (reported or derived from minority interest).
    if group_equity is not None:
        recomputed_bvps = group_equity / shares
        if stored_bvps is None:
            return _check(
                name="t2_equity_per_share",
                status="pass",
                inputs=inputs,
                message="t2_derived: BVPS recomputed from group equity and shares",
            ), {"BVPS": recomputed_bvps}
        delta, rel_delta = _stored_ratio_delta(stored_bvps, recomputed_bvps)
        status = _status_from_rel(rel_delta or 0.0, pass_threshold=0.01, warn_threshold=0.05)
        return _check(
            name="t2_equity_per_share",
            status=status,
            delta=delta,
            rel_delta=rel_delta,
            inputs=inputs,
            message=None if status == "pass" else "t2_fail: stored BVPS does not match group equity divided by shares",
        ), {"BVPS": recomputed_bvps}

    # Minority-aware fallback: only consolidated Total_Equity is available, with no group split.
    # Treat BVPS*shares as the implied group equity; the remainder is implied minority interest.
    recomputed_total_bvps = total_equity / shares
    if stored_bvps is None:
        return _check(
            name="t2_equity_per_share",
            status="pass",
            inputs=inputs,
            message="t2_derived: BVPS recomputed from consolidated equity; group split unavailable",
        ), {"BVPS": recomputed_total_bvps}
    implied_group_equity = stored_bvps * shares
    implied_minority_fraction = (total_equity - implied_group_equity) / total_equity if total_equity else None
    inputs["Implied_Minority_Fraction"] = implied_minority_fraction
    delta, rel_delta = _stored_ratio_delta(stored_bvps, recomputed_total_bvps)
    # Group equity cannot exceed consolidated equity — that is a genuine failure.
    if implied_minority_fraction is not None and implied_minority_fraction < -0.01:
        return _check(
            name="t2_equity_per_share",
            status="fail",
            delta=delta,
            rel_delta=rel_delta,
            inputs=inputs,
            message="t2_fail: implied group equity exceeds consolidated equity",
        ), {"BVPS": stored_bvps}
    # An implausibly large minority slice points to a units/shares error, not real minorities.
    if implied_minority_fraction is not None and implied_minority_fraction > T2_MINORITY_MAX_FRACTION:
        return _check(
            name="t2_equity_per_share",
            status="fail",
            delta=delta,
            rel_delta=rel_delta,
            inputs=inputs,
            message=f"t2_fail: implied minority interest {implied_minority_fraction:.1%} exceeds plausible band",
        ), {"BVPS": stored_bvps}
    # Otherwise the BVPS<->total gap is consistent with normal minority interest: group tie-out holds.
    status = "pass" if (implied_minority_fraction is None or implied_minority_fraction <= T2_MINORITY_WARN_FRACTION) else "warn"
    message = None if status == "pass" else f"t2_warn: large implied minority interest {implied_minority_fraction:.1%}"
    return _check(
        name="t2_equity_per_share",
        status=status,
        delta=delta,
        rel_delta=rel_delta,
        inputs=inputs,
        message=message,
    ), {"BVPS": stored_bvps}


def _t3_income_consistency(rows_by_metric: dict[str, Any]) -> tuple[IntegrityCheck, dict[str, float | None]]:
    net_income = _value(rows_by_metric, "NetIncome", "Net_Income", "IS_Net_Income", "Resultat_net")
    resultat_net = _value(rows_by_metric, "Resultat_net", "IS_Net_Income", "Net_Income", "NetIncome")
    rnpg = _value(rows_by_metric, "Resultat_net_part_du_groupe", "RNPG", "NetIncome_Group", "Net_Income_Group")
    inputs = {"NetIncome": net_income, "Resultat_net": resultat_net, "RNPG": rnpg}
    if net_income is None and resultat_net is None:
        return _check(
            name="t3_income_consistency",
            status="unavailable",
            inputs=inputs,
            message="t3_unavailable: missing Resultat_net or NetIncome",
        ), {"NetIncome": None, "NetIncome_Group": rnpg}
    base_income = net_income if net_income is not None else resultat_net
    if net_income is not None and resultat_net is not None:
        delta = net_income - resultat_net
        rel_delta = delta / max(abs(resultat_net), 1.0)
        if abs(rel_delta) > 0.005:
            return _check(
                name="t3_income_consistency",
                status="fail",
                delta=delta,
                rel_delta=rel_delta,
                inputs=inputs,
                message="t3_fail: NetIncome does not equal Resultat_net",
            ), {"NetIncome": resultat_net, "NetIncome_Group": rnpg}
    if rnpg is not None and base_income is not None and base_income >= 0 and rnpg > base_income + max(abs(base_income) * 0.005, 1.0):
        delta = rnpg - base_income
        return _check(
            name="t3_income_consistency",
            status="fail",
            delta=delta,
            rel_delta=delta / max(abs(base_income), 1.0),
            inputs=inputs,
            message="t3_fail: RNPG exceeds consolidated net income",
        ), {"NetIncome": base_income, "NetIncome_Group": rnpg}
    return _check(
        name="t3_income_consistency",
        status="pass",
        inputs=inputs,
        message=None,
    ), {"NetIncome": base_income, "NetIncome_Group": rnpg}


def _t4_group_basis_roe(
    rows_by_metric: dict[str, Any],
    previous_rows_by_metric: dict[str, Any] | None,
    assumptions: dict[str, float],
) -> tuple[IntegrityCheck, dict[str, float | None]]:
    epsilon = float(assumptions.get("minority_materiality_epsilon", DEFAULT_ASSUMPTIONS["minority_materiality_epsilon"]))
    basis = resolve_minority_roe_basis(rows_by_metric, epsilon=epsilon)
    previous_group_equity = _value(
        previous_rows_by_metric or {},
        "Equity_Group",
        "Total_Equity_Group",
        "Capitaux_propres_part_du_groupe",
        "Total_Common_Equity",
    )
    stored_roe = _value(rows_by_metric, "ROE", "Return_on_Equity")
    inputs = {
        "RNPG": basis.rnpg,
        "NetIncome": basis.net_income,
        "Equity_Group": basis.group_equity,
        "Reported_RNPG": basis.reported_rnpg,
        "Reported_Equity_Group": basis.reported_group_equity,
        "Total_Equity": basis.total_equity,
        "Minority_Interest": basis.minority_interest,
        "minority_materiality_epsilon": epsilon,
        "minority_interest_to_equity": basis.mi_ratio,
        "equity_group_gap_to_total": basis.equity_gap_ratio,
        "rnpg_gap_to_net_income": basis.rnpg_gap_ratio,
        "Previous_Equity_Group": previous_group_equity,
        "ROE": stored_roe,
        "t4_basis": basis.basis,
    }
    if basis.is_material_minority and (basis.rnpg is None or basis.group_equity is None):
        return _check(
            name="t4_group_basis_roe",
            status="unavailable",
            inputs=inputs,
            message="t4_unavailable: needs_group_figures_for_material_minority",
        ), {"ROE": None, "t4_basis": basis.basis}
    if basis.rnpg is None or basis.group_equity is None or basis.group_equity == 0:
        return _check(
            name="t4_group_basis_roe",
            status="unavailable",
            inputs=inputs,
            message="t4_unavailable: missing NetIncome/Total_Equity for no-minority ROE",
        ), {"ROE": None, "t4_basis": basis.basis}

    recomputed = basis.rnpg / basis.group_equity
    delta, rel_delta = _stored_ratio_delta(stored_roe, recomputed)
    if recomputed > 1.0 or recomputed < -1.0:
        return _check(
            name="t4_group_basis_roe",
            status="fail",
            delta=delta,
            rel_delta=rel_delta,
            inputs=inputs,
            message="t4_fail: recomputed group ROE outside plausibility band",
        ), {"ROE": recomputed, "t4_basis": basis.basis}
    return _check(
        name="t4_group_basis_roe",
        status="pass",
        delta=delta,
        rel_delta=rel_delta,
        inputs=inputs,
        message="t4_derived: ROE recomputed; stored ROE ignored",
    ), {"ROE": recomputed, "t4_basis": basis.basis}


def _t5_single_annual_vintage(
    *,
    statement_year: int,
    snapshot_year: int | None,
    metric_years: dict[str, Any] | None,
    period_type: str | None,
) -> IntegrityCheck:
    mismatched_years = _metric_year_issues(metric_years or {}, statement_year)
    normalized_period = str(period_type or "annual").strip().lower()
    inputs: dict[str, float | None] = {
        "statement_year": float(statement_year),
        "snapshot_year": float(snapshot_year) if snapshot_year is not None else None,
    }
    if snapshot_year is not None and int(snapshot_year) != int(statement_year):
        return _check(
            name="t5_single_annual_vintage",
            status="fail",
            inputs=inputs,
            message=f"t5_fail: snapshot year {snapshot_year} does not match annual year {statement_year}",
        )
    if mismatched_years:
        return _check(
            name="t5_single_annual_vintage",
            status="fail",
            inputs=inputs,
            message=f"t5_fail: mixed fiscal years {mismatched_years}",
        )
    if normalized_period not in {"annual", "fy", ""}:
        return _check(
            name="t5_single_annual_vintage",
            status="fail",
            inputs=inputs,
            message=f"t5_fail: snapshot period is {normalized_period}, expected annual",
        )
    return _check(name="t5_single_annual_vintage", status="pass", inputs=inputs, message=None)


def _t6_existing_integrity(rows_by_metric: dict[str, Any], assumptions: dict[str, float], symbol: str, statement_year: int) -> list[IntegrityCheck]:
    report = build_integrity_report(symbol, statement_year, rows_by_metric, assumptions)
    checks: list[IntegrityCheck] = []
    for check in report.checks:
        checks.append(
            _check(
                name=f"t6_{check.name}",
                status=check.status,
                delta=check.delta,
                rel_delta=check.rel_delta,
                inputs=check.inputs,
                message=check.message,
            )
        )
    return checks


def _t7_plausibility(rows_by_metric: dict[str, Any], recomputed: dict[str, float | None]) -> IntegrityCheck:
    current_price = _value(rows_by_metric, "Current_Price", "Price")
    shares = _value(rows_by_metric, "Shares_Outstanding", "Shares")
    group_equity = _value(rows_by_metric, "Equity_Group", "Total_Equity_Group", "Total_Common_Equity")
    if group_equity is None:
        group_equity = _value(rows_by_metric, "Total_Equity")
    roe = recomputed.get("ROE")
    pb = None
    if current_price is not None and shares is not None and group_equity is not None and group_equity > 0:
        pb = (current_price * shares) / group_equity
    stored_pb = _value(rows_by_metric, "Price_to_Book", "P_B", "PB")
    if pb is None and stored_pb is not None:
        pb = stored_pb
    inputs = {"ROE": roe, "Price_to_Book": pb, "Stored_Price_to_Book": stored_pb}
    problems: list[str] = []
    if roe is not None and (roe > 1.0 or roe < -1.0):
        problems.append(f"implausible_roe={roe:.6f}")
    if pb is not None and (pb < 0.0 or pb > 10.0):
        problems.append(f"implausible_price_to_book={pb:.6f}")
    if problems:
        return _check(
            name="t7_plausibility",
            status="fail",
            inputs=inputs,
            message="t7_fail: " + ",".join(problems),
        )
    return _check(name="t7_plausibility", status="pass", inputs=inputs, message=None)


def build_data_tieout_report(
    symbol: str,
    statement_year: int,
    rows_by_metric: dict[str, Any],
    *,
    previous_rows_by_metric: dict[str, Any] | None = None,
    snapshot_year: int | None = None,
    metric_years: dict[str, Any] | None = None,
    period_type: str | None = "annual",
    assumptions: dict[str, float] = DEFAULT_ASSUMPTIONS,
    provenance: dict[str, Any] | None = None,
) -> DataTieOutReport:
    """Recompute source-data tie-outs and classify the annual row set.

    Stored ROE/BVPS/P/B values are only used as observed ratios to compare
    against recomputed raw-line formulas; they never drive the recomputed output.
    """

    checks: list[IntegrityCheck] = []
    recomputed: dict[str, float | None] = {}
    t1, t1_recomputed = _t1_balance_sheet(rows_by_metric, assumptions)
    checks.append(t1)
    recomputed.update(t1_recomputed)
    t2, t2_recomputed = _t2_equity_per_share(rows_by_metric)
    checks.append(t2)
    recomputed.update(t2_recomputed)
    t3, t3_recomputed = _t3_income_consistency(rows_by_metric)
    checks.append(t3)
    recomputed.update(t3_recomputed)
    t4, t4_recomputed = _t4_group_basis_roe(rows_by_metric, previous_rows_by_metric, assumptions)
    checks.append(t4)
    recomputed.update(t4_recomputed)
    checks.append(
        _t5_single_annual_vintage(
            statement_year=int(statement_year),
            snapshot_year=snapshot_year,
            metric_years=metric_years,
            period_type=period_type,
        )
    )
    checks.extend(_t6_existing_integrity(rows_by_metric, assumptions, symbol, int(statement_year)))
    checks.append(_t7_plausibility(rows_by_metric, recomputed))

    failed_checks = [check.name for check in checks if check.status == "fail"]
    blocking_unavailable = [
        check.name
        for check in checks
        if check.name in BLOCKING_TIEOUT_CHECKS and check.status == "unavailable"
    ]
    warnings = [
        f"{check.name}:{check.status}:{check.message or ''}".rstrip(":")
        for check in checks
        if check.status in {"warn", "derived", "unavailable"} and check.name not in blocking_unavailable
    ]
    status = "verified" if not failed_checks and not blocking_unavailable else "data_unverified"
    offending = {
        check.name: {
            "status": check.status,
            "message": check.message,
            "inputs": check.inputs,
            "delta": check.delta,
            "rel_delta": check.rel_delta,
        }
        for check in checks
        if check.status == "fail" or check.name in blocking_unavailable
    }
    reason_parts = failed_checks + blocking_unavailable
    return DataTieOutReport(
        symbol=str(symbol or "").upper(),
        statement_year=int(statement_year),
        status=status,
        checks=checks,
        failed_checks=failed_checks + blocking_unavailable,
        warnings=warnings,
        offending_metrics=offending,
        recomputed_metrics=recomputed,
        provenance=dict(provenance or {}),
        reason=";".join(reason_parts) if reason_parts else None,
    )


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
    is_net_income_group = _value(
        rows_by_metric, "Resultat_net_part_du_groupe", "RNPG", "NetIncome_Group", "Net_Income_Group"
    )
    cfs_net_income = _value(rows_by_metric, "CFS_Net_Income_Top_Of_CFS")
    inputs = {
        "IS_Net_Income": is_net_income,
        "IS_Net_Income_Group": is_net_income_group,
        "CFS_Net_Income_Top_Of_CFS": cfs_net_income,
    }
    candidates = [
        ("total", is_net_income),
        ("group", is_net_income_group),
    ]
    candidates = [(basis, value) for basis, value in candidates if value is not None]
    if cfs_net_income is None or not candidates:
        return IntegrityCheck(
            name="ni_link",
            status="unavailable",
            delta=None,
            rel_delta=None,
            inputs=inputs,
            message="ni_link_unavailable: cannot verify IS to CFS net income link",
        )
    # The top-of-CFS net income may be reported on a consolidated (total) or a
    # group-share basis depending on the filer/provider. Tie out against whichever
    # basis the CFS figure matches so companies with minority interests are not
    # systematically flagged for the minority-interest difference; a genuine
    # discrepancy still fails because it matches neither basis.
    basis, value = min(
        candidates,
        key=lambda item: abs((cfs_net_income - item[1]) / max(abs(item[1]), 1.0)),
    )
    delta = value - cfs_net_income
    rel_delta = delta / max(abs(value), 1.0)
    return IntegrityCheck(
        name="ni_link",
        status=_status_from_rel(rel_delta, pass_threshold=0.005, warn_threshold=0.02),
        delta=delta,
        rel_delta=rel_delta,
        inputs={**inputs, "ni_link_basis": basis},
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
