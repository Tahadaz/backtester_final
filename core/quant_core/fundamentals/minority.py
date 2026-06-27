from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any


TOTAL_EQUITY_ALIASES = (
    "Total_Equity",
    "Capitaux_propres",
    "Shareholders_Equity",
    "Total_Shareholders_Equity",
)
GROUP_EQUITY_ALIASES = (
    "Equity_Group",
    "Total_Equity_Group",
    "Capitaux_propres_part_du_groupe",
    "Total_Common_Equity",
    "Common_Equity",
)
NET_INCOME_ALIASES = ("NetIncome", "Net_Income", "IS_Net_Income", "Resultat_net")
GROUP_NET_INCOME_ALIASES = (
    "Resultat_net_part_du_groupe",
    "RNPG",
    "NetIncome_Group",
    "Net_Income_Group",
)
MINORITY_INTEREST_ALIASES = (
    "Minority_Interest",
    "Interets_minoritaires",
    "Non_Controlling_Interest",
    "Interests_Minoritaires",
)


@dataclass(frozen=True)
class MinorityRoeBasis:
    rnpg: float | None
    group_equity: float | None
    total_equity: float | None
    net_income: float | None
    reported_group_equity: float | None
    reported_rnpg: float | None
    minority_interest: float | None
    basis: str
    is_material_minority: bool
    mi_ratio: float | None
    equity_gap_ratio: float | None
    rnpg_gap_ratio: float | None
    reason: str


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def value_from_rows(rows_by_metric: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = _num(rows_by_metric.get(name))
        if value is not None:
            return value
    return None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return abs(numerator) / max(abs(denominator), 1.0)


def resolve_minority_roe_basis(
    rows_by_metric: dict[str, Any],
    *,
    epsilon: float,
) -> MinorityRoeBasis:
    """Resolve the group-basis ROE numerator/denominator from raw filing lines.

    When the filing provides no material minority evidence, consolidated net
    income and total equity are the group basis by definition. Material minority
    evidence keeps the stricter RNPG / group-equity requirement.
    """

    total_equity = value_from_rows(rows_by_metric, *TOTAL_EQUITY_ALIASES)
    reported_group_equity = value_from_rows(rows_by_metric, *GROUP_EQUITY_ALIASES)
    net_income = value_from_rows(rows_by_metric, *NET_INCOME_ALIASES)
    reported_rnpg = value_from_rows(rows_by_metric, *GROUP_NET_INCOME_ALIASES)
    minority_interest = value_from_rows(rows_by_metric, *MINORITY_INTEREST_ALIASES)

    mi_ratio = _ratio(minority_interest, total_equity)
    equity_gap_ratio = (
        _ratio(float(total_equity) - float(reported_group_equity), total_equity)
        if total_equity is not None and reported_group_equity is not None
        else None
    )
    rnpg_gap_ratio = (
        _ratio(float(net_income) - float(reported_rnpg), net_income)
        if net_income is not None and reported_rnpg is not None
        else None
    )

    if total_equity is None and reported_group_equity is not None:
        return MinorityRoeBasis(
            rnpg=reported_rnpg,
            group_equity=reported_group_equity,
            total_equity=total_equity,
            net_income=net_income,
            reported_group_equity=reported_group_equity,
            reported_rnpg=reported_rnpg,
            minority_interest=minority_interest,
            basis="reported_group_basis",
            is_material_minority=True,
            mi_ratio=mi_ratio,
            equity_gap_ratio=equity_gap_ratio,
            rnpg_gap_ratio=rnpg_gap_ratio,
            reason="total_equity_missing_use_reported_group_basis",
        )

    is_material = any(
        ratio is not None and ratio > float(epsilon)
        for ratio in (mi_ratio, equity_gap_ratio)
    )
    if is_material:
        return MinorityRoeBasis(
            rnpg=reported_rnpg,
            group_equity=reported_group_equity,
            total_equity=total_equity,
            net_income=net_income,
            reported_group_equity=reported_group_equity,
            reported_rnpg=reported_rnpg,
            minority_interest=minority_interest,
            basis="reported_group_basis",
            is_material_minority=True,
            mi_ratio=mi_ratio,
            equity_gap_ratio=equity_gap_ratio,
            rnpg_gap_ratio=rnpg_gap_ratio,
            reason="material_minority_requires_group_figures",
        )

    return MinorityRoeBasis(
        rnpg=net_income,
        group_equity=total_equity,
        total_equity=total_equity,
        net_income=net_income,
        reported_group_equity=reported_group_equity,
        reported_rnpg=reported_rnpg,
        minority_interest=minority_interest,
        basis="no_minority_total_equity",
        is_material_minority=False,
        mi_ratio=mi_ratio,
        equity_gap_ratio=equity_gap_ratio,
        rnpg_gap_ratio=rnpg_gap_ratio,
        reason="no_material_minority_evidence",
    )
