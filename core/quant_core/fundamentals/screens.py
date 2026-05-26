from __future__ import annotations

import math
import unicodedata
from statistics import mean
from typing import Any

from .domain import AnnualMetricRow, FundamentalSnapshot


FINANCIAL_SECTOR_TOKENS = (
    "banque",
    "bank",
    "assurance",
    "insurance",
    "financement",
    "leasing",
    "credit",
)


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _positive(value: Any) -> float | None:
    out = _num(value)
    return out if out is not None and out > 0 else None


def _ratio(value: Any) -> float | None:
    out = _num(value)
    if out is None:
        return None
    return out / 100.0 if abs(out) > 2.0 else out


def _normalize_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _is_financial(sector: str | None) -> bool:
    normalized = _normalize_text(sector)
    return any(token in normalized for token in FINANCIAL_SECTOR_TOKENS)


def _metric_series(history: list[AnnualMetricRow], *metric_names: str) -> list[tuple[int, float]]:
    names = set(metric_names)
    rows = [
        (row.statement_year, float(row.metric_value))
        for row in history
        if row.metric_name in names and row.metric_value is not None and _num(row.metric_value) is not None
    ]
    return sorted(rows)


def _latest_metric(history: list[AnnualMetricRow], *metric_names: str) -> float | None:
    rows = _metric_series(history, *metric_names)
    return rows[-1][1] if rows else None


def _snapshot_or_history(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], *metric_names: str) -> float | None:
    for metric_name in metric_names:
        value = _num(snapshot.metrics.get(metric_name))
        if value is not None:
            return value
    return _latest_metric(history, *metric_names)


def _screen_unavailable(reason: str, name: str, warnings: list[str] | None = None, *, scope: str | None = None) -> dict[str, Any]:
    warning_list = list(warnings or [])
    if reason not in warning_list:
        warning_list.append(reason)
    return {
        "score": None,
        "scope": scope,
        "warnings": warning_list,
        "methodology": f"{name}: unavailable because required inputs were missing or invalid.",
    }


def _clip_score(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, min(100.0, float(value))), 2)


def _percentile_rank(values: dict[str, float], target: str, *, lower_is_better: bool) -> float | None:
    if target not in values or len(values) < 3:
        return None
    sorted_items = sorted(values.items(), key=lambda item: item[1])
    n = len(sorted_items)
    for rank, (symbol, _) in enumerate(sorted_items):
        if symbol == target:
            pct = 100.0 * rank / (n - 1)
            return 100.0 - pct if lower_is_better else pct
    return None


def _magic_inputs(snapshot: FundamentalSnapshot) -> tuple[dict[str, float] | None, str | None]:
    metrics = snapshot.metrics
    ebit = _positive(metrics.get("EBIT")) or _positive(metrics.get("Resultat_Exploitation"))
    total_assets = _positive(metrics.get("Total_Assets"))
    current_assets = _num(metrics.get("Current_Assets")) or 0.0
    current_liabilities = _num(metrics.get("Current_Liabilities")) or 0.0
    cash = _num(metrics.get("Cash_and_Equivalents")) or _num(metrics.get("Cash")) or 0.0
    total_debt = _num(metrics.get("Total_Debt")) or _num(metrics.get("Debt_Total"))
    if total_debt is None:
        net_debt = _num(metrics.get("NetDebt"))
        if net_debt is not None:
            total_debt = net_debt + cash
    market_cap = _positive(metrics.get("MarketCap_Calc"))

    if ebit is None:
        return None, "missing_ebit"
    if total_assets is None or market_cap is None:
        return None, "missing_balance_sheet_or_market_cap"

    net_working_capital = max(0.0, current_assets - current_liabilities - cash)
    intangibles = _num(metrics.get("Goodwill")) or _num(metrics.get("Intangibles")) or 0.0
    net_ppe = max(0.0, total_assets - current_assets - intangibles)
    invested_op_capital = net_working_capital + net_ppe
    if invested_op_capital <= 0:
        return None, "invested_capital_non_positive"

    enterprise_value = market_cap + (total_debt or 0.0) - cash
    if enterprise_value <= 0:
        return None, "enterprise_value_non_positive"

    roc = ebit / invested_op_capital
    earnings_yield = ebit / enterprise_value
    return {
        "roc": roc,
        "earnings_yield": earnings_yield,
        "ebit": ebit,
        "net_working_capital": net_working_capital,
        "net_ppe_proxy": net_ppe,
        "invested_op_capital": invested_op_capital,
        "enterprise_value": enterprise_value,
        "market_cap": market_cap,
        "total_debt": total_debt or 0.0,
        "cash": cash,
    }, None


def magic_formula(
    snapshot: FundamentalSnapshot,
    peer_snapshots: list[FundamentalSnapshot],
    sectors: dict[str, str | None] | None = None,
    *,
    peer_min_count: int = 3,
) -> dict[str, Any]:
    warnings: list[str] = []
    target_components, reason = _magic_inputs(snapshot)
    if target_components is None:
        return _screen_unavailable(reason or "missing_inputs", "Magic Formula", warnings)

    sector_map = sectors or {}
    candidates: dict[str, FundamentalSnapshot] = {snapshot.symbol: snapshot}
    for peer in peer_snapshots:
        candidates.setdefault(peer.symbol, peer)

    roc_values: dict[str, float] = {}
    ey_values: dict[str, float] = {}
    for symbol, candidate in candidates.items():
        components, _peer_reason = _magic_inputs(candidate)
        if components is None:
            continue
        roc_values[symbol] = float(components["roc"])
        ey_values[symbol] = float(components["earnings_yield"])

    target_sector = sector_map.get(snapshot.symbol)
    sector_peer_count = sum(
        1
        for symbol in roc_values
        if symbol != snapshot.symbol and target_sector and sector_map.get(symbol) == target_sector
    )
    scope = "sector" if target_sector and sector_peer_count >= peer_min_count else "market"
    if scope == "sector":
        roc_cohort = {symbol: value for symbol, value in roc_values.items() if sector_map.get(symbol) == target_sector}
        ey_cohort = {symbol: value for symbol, value in ey_values.items() if sector_map.get(symbol) == target_sector}
    else:
        roc_cohort = roc_values
        ey_cohort = ey_values

    roc_rank = _percentile_rank(roc_cohort, snapshot.symbol, lower_is_better=False)
    ey_rank = _percentile_rank(ey_cohort, snapshot.symbol, lower_is_better=False)
    if roc_rank is None or ey_rank is None:
        return {
            "score": None,
            "scope": scope,
            "warnings": [*warnings, "insufficient_cohort"],
            "methodology": "Greenblatt Magic Formula: rank by ROC and earnings yield within sector when enough peers exist, otherwise market.",
            "roc": target_components["roc"],
            "earnings_yield": target_components["earnings_yield"],
            "roc_rank": roc_rank,
            "ey_rank": ey_rank,
            "components": {key: value for key, value in target_components.items() if key not in {"roc", "earnings_yield"}},
        }

    score = (roc_rank + ey_rank) / 2.0
    return {
        "score": _clip_score(score),
        "scope": scope,
        "warnings": warnings,
        "methodology": "Greenblatt Magic Formula: rank by ROC and earnings yield within sector when enough peers exist, otherwise market.",
        "roc": target_components["roc"],
        "earnings_yield": target_components["earnings_yield"],
        "roc_rank": round(roc_rank, 2),
        "ey_rank": round(ey_rank, 2),
        "components": {key: value for key, value in target_components.items() if key not in {"roc", "earnings_yield"}},
    }


def peg_garp(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
) -> dict[str, Any]:
    warnings: list[str] = []
    per = _positive(snapshot.metrics.get("PER"))
    if per is None:
        return _screen_unavailable("missing_per", "PEG / GARP", warnings)

    growth_source = "NetIncome_Growth"
    growth = _ratio(snapshot.metrics.get("NetIncome_Growth"))
    if growth is None:
        growth_source = "EBIT_Growth"
        growth = _ratio(snapshot.metrics.get("EBIT_Growth"))
        if growth is not None:
            warnings.append("using_ebit_growth_proxy")
    if growth is None:
        series = _metric_series(history, "Resultat_net", "Clean_Resultat_net", "NetIncome")
        if len(series) >= 4 and series[0][1] > 0:
            growth = (series[-1][1] / series[0][1]) ** (1.0 / (len(series) - 1)) - 1.0
            growth_source = "trailing_3y_cagr"
            warnings.append("using_trailing_growth")
    if growth is None:
        return _screen_unavailable("missing_growth", "PEG / GARP", warnings)

    growth_pct = max(0.01, growth * 100.0)
    peg = per / growth_pct
    if peg <= 0.75:
        score = 100.0
        zone = "very_cheap_growth"
    elif peg <= 1.00:
        score = 80.0
        zone = "cheap_growth"
    elif peg <= 1.50:
        score = 60.0
        zone = "reasonable_growth"
    elif peg <= 2.00:
        score = 40.0
        zone = "fairly_priced"
    elif peg <= 3.00:
        score = 20.0
        zone = "expensive_growth"
    else:
        score = 0.0
        zone = "very_expensive"

    return {
        "score": score,
        "scope": None,
        "warnings": warnings,
        "methodology": "Peter Lynch PEG = P/E divided by earnings growth percent; GARP zone scoring.",
        "peg": round(peg, 3),
        "per": per,
        "growth_used": growth,
        "growth_source": growth_source,
        "zone": zone,
    }


def altman_z(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    sector: str | None,
) -> dict[str, Any]:
    warnings: list[str] = []
    ta = _positive(snapshot.metrics.get("Total_Assets")) or _latest_metric(history, "Total_Assets")
    if ta is None or ta <= 0:
        return _screen_unavailable("missing_total_assets", "Altman Z", warnings)

    ca = _snapshot_or_history(snapshot, history, "Current_Assets") or 0.0
    cl = _snapshot_or_history(snapshot, history, "Current_Liabilities") or 0.0
    wc = ca - cl

    retained = _snapshot_or_history(snapshot, history, "Retained_Earnings", "Reserves")
    if retained is None:
        warnings.append("missing_retained_earnings")
        retained = 0.0

    ebit = _positive(snapshot.metrics.get("EBIT")) or _positive(snapshot.metrics.get("Resultat_Exploitation")) or _latest_metric(history, "EBIT", "Resultat_Exploitation")
    if ebit is None:
        return _screen_unavailable("missing_ebit", "Altman Z", warnings)

    tl = _snapshot_or_history(snapshot, history, "Total_Liabilities")
    if tl is None or tl <= 0:
        return _screen_unavailable("missing_total_liabilities", "Altman Z", warnings)

    sales = _latest_metric(history, "Chiffre_daffaires", "Clean_Chiffre_daffaires", "Revenue") or _positive(snapshot.metrics.get("Revenue"))
    if sales is None or sales <= 0:
        return _screen_unavailable("missing_sales", "Altman Z", warnings)

    book_equity = ta - tl
    if _is_financial(sector):
        wc_ta = wc / ta
        re_ta = retained / ta
        ebit_ta = ebit / ta
        equity_tl = book_equity / tl
        z_value = 6.56 * wc_ta + 3.26 * re_ta + 6.72 * ebit_ta + 1.05 * equity_tl
        zone = "safe" if z_value > 2.60 else "grey" if z_value > 1.10 else "distress"
        return {
            "score": _clip_score(z_value * 20.0),
            "scope": None,
            "warnings": warnings,
            "methodology": "Altman Z-score for distress probability; financials use the Z'' emerging-market variant.",
            "z_value": round(z_value, 3),
            "variant": "Z''",
            "zone": zone,
            "components": {"wc_ta": wc_ta, "re_ta": re_ta, "ebit_ta": ebit_ta, "equity_tl": equity_tl},
        }

    market_cap = _positive(snapshot.metrics.get("MarketCap_Calc"))
    if market_cap is None:
        return _screen_unavailable("missing_market_cap", "Altman Z", warnings)
    wc_ta = wc / ta
    re_ta = retained / ta
    ebit_ta = ebit / ta
    market_tl = market_cap / tl
    sales_ta = sales / ta
    z_value = 1.2 * wc_ta + 1.4 * re_ta + 3.3 * ebit_ta + 0.6 * market_tl + 1.0 * sales_ta
    zone = "safe" if z_value > 2.99 else "grey" if z_value > 1.81 else "distress"
    return {
        "score": _clip_score((z_value - 1.0) * 25.0),
        "scope": None,
        "warnings": warnings,
        "methodology": "Altman Z-score for distress probability; financials use the Z'' emerging-market variant.",
        "z_value": round(z_value, 3),
        "variant": "Z",
        "zone": zone,
        "components": {
            "wc_ta": wc_ta,
            "re_ta": re_ta,
            "ebit_ta": ebit_ta,
            "mkt_tl": market_tl,
            "sales_ta": sales_ta,
        },
    }


def eva(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    assumptions: dict[str, float],
    sector: str | None,
) -> dict[str, Any]:
    warnings: list[str] = []
    if _is_financial(sector):
        return {
            "score": None,
            "scope": None,
            "warnings": ["financial_sector_not_applicable"],
            "methodology": "EVA: ROIC versus WACC spread times invested capital; skipped for financial sectors.",
            "applicable": False,
            "nopat": None,
            "roic": None,
            "wacc_used": float(assumptions.get("wacc", 0.0851)),
            "roic_spread": None,
            "eva_value": None,
            "eva_margin": None,
            "invested_capital": None,
            "components": {},
        }

    ebit = _positive(snapshot.metrics.get("EBIT")) or _positive(snapshot.metrics.get("Resultat_Exploitation")) or _latest_metric(history, "EBIT", "Resultat_Exploitation")
    if ebit is None:
        return _screen_unavailable("missing_ebit", "EVA", warnings)

    tax_rate = float(assumptions.get("tax_rate", 0.30))
    nopat = ebit * (1.0 - tax_rate)
    cash = _num(snapshot.metrics.get("Cash_and_Equivalents")) or _num(snapshot.metrics.get("Cash")) or 0.0
    total_debt = _num(snapshot.metrics.get("Total_Debt")) or _latest_metric(history, "Total_Debt", "Debt_Total")
    if total_debt is None:
        net_debt = _num(snapshot.metrics.get("NetDebt")) or _latest_metric(history, "NetDebt")
        if net_debt is not None:
            total_debt = net_debt + cash
    if total_debt is None:
        total_debt = 0.0
        warnings.append("missing_debt_assumed_zero")

    ta = _positive(snapshot.metrics.get("Total_Assets")) or _latest_metric(history, "Total_Assets")
    tl = _snapshot_or_history(snapshot, history, "Total_Liabilities")
    if ta is None or tl is None:
        return _screen_unavailable("missing_balance_sheet", "EVA", warnings)

    book_equity = ta - tl
    invested_capital = total_debt + book_equity
    if invested_capital <= 0:
        return _screen_unavailable("invested_capital_non_positive", "EVA", warnings)

    roic = nopat / invested_capital
    wacc = float(assumptions.get("wacc", 0.0851))
    roic_spread = roic - wacc
    eva_value = roic_spread * invested_capital
    revenue = _latest_metric(history, "Chiffre_daffaires", "Clean_Chiffre_daffaires", "Revenue") or _positive(snapshot.metrics.get("Revenue"))
    eva_margin = eva_value / revenue if revenue and revenue > 0 else None
    return {
        "score": _clip_score(50.0 + roic_spread * 1000.0),
        "scope": None,
        "warnings": warnings,
        "methodology": "EVA: ROIC versus WACC spread times invested capital.",
        "nopat": nopat,
        "roic": roic,
        "wacc_used": wacc,
        "roic_spread": roic_spread,
        "eva_value": eva_value,
        "eva_margin": eva_margin,
        "invested_capital": invested_capital,
        "components": {
            "ebit": ebit,
            "tax_rate": tax_rate,
            "total_debt": total_debt,
            "book_equity": book_equity,
            "revenue": revenue,
        },
        "applicable": True,
    }


def regression_adjusted_multiples(
    snapshot: FundamentalSnapshot,
    peer_snapshots: list[FundamentalSnapshot],
    sectors: dict[str, str | None] | None = None,
    *,
    cohort_min_count: int = 8,
) -> dict[str, Any]:
    warnings: list[str] = []
    multiples = ("PER", "Price_to_Book", "EV_to_EBITDA", "Price_to_Sales")
    sector_map = sectors or {}
    target_sector = sector_map.get(snapshot.symbol)
    candidates_by_symbol: dict[str, FundamentalSnapshot] = {snapshot.symbol: snapshot}
    for peer in peer_snapshots:
        candidates_by_symbol.setdefault(peer.symbol, peer)
    candidates = list(candidates_by_symbol.values())
    sector_cohort = [row for row in candidates if target_sector and sector_map.get(row.symbol) == target_sector]
    cohort = sector_cohort if len(sector_cohort) >= cohort_min_count else candidates
    scope = "sector" if cohort is sector_cohort else "market"
    if len(cohort) < cohort_min_count:
        return _screen_unavailable("insufficient_cohort_for_regression", "Regression-adjusted multiples", warnings, scope=scope)

    try:
        import numpy as np
    except Exception:
        return _screen_unavailable("numpy_unavailable", "Regression-adjusted multiples", warnings, scope=scope)

    output: dict[str, Any] = {
        "score": None,
        "scope": scope,
        "warnings": warnings,
        "methodology": "Cross-sectional regression of valuation multiples on growth, ROE, size, and leverage; richness is standardized residual.",
        "regression_richness": {},
        "coefficients": {},
    }
    richness_values: list[float] = []

    for dep_metric in multiples:
        rows: list[tuple[str, float, float, float, float, float]] = []
        for item in cohort:
            multiple = _positive(item.metrics.get(dep_metric))
            growth = _ratio(item.metrics.get("NetIncome_Growth"))
            roe = _ratio(item.metrics.get("ROE"))
            market_cap = _positive(item.metrics.get("MarketCap_Calc"))
            leverage = _num(item.metrics.get("Debt_to_Equity"))
            if any(value is None for value in (multiple, growth, roe, market_cap, leverage)):
                continue
            rows.append((item.symbol, float(multiple), float(growth), float(roe), math.log(float(market_cap)), float(leverage)))

        if len(rows) < cohort_min_count:
            output["regression_richness"][dep_metric] = None
            warnings.append(f"insufficient_cohort_for_{dep_metric}")
            continue

        names = [row[0] for row in rows]
        y = np.array([row[1] for row in rows], dtype=float)
        x_matrix = np.column_stack(
            [
                np.ones(len(rows), dtype=float),
                [row[2] for row in rows],
                [row[3] for row in rows],
                [row[4] for row in rows],
                [row[5] for row in rows],
            ]
        )
        coefs, _residuals, _rank, _sv = np.linalg.lstsq(x_matrix, y, rcond=None)
        y_pred = x_matrix @ coefs
        residual_values = y - y_pred
        resid_std = float(np.std(residual_values, ddof=1)) if len(residual_values) > 1 else 0.0
        ss_res = float(np.sum(residual_values**2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

        actual = predicted = residual = richness = None
        if snapshot.symbol in names:
            index = names.index(snapshot.symbol)
            actual = float(y[index])
            predicted = float(y_pred[index])
            residual = float(actual - predicted)
            richness = residual / resid_std if resid_std > 0 else 0.0
            richness_values.append(float(richness))

        output["regression_richness"][dep_metric] = {
            "actual": actual,
            "predicted": predicted,
            "residual": residual,
            "richness_z": float(richness) if richness is not None else None,
        }
        output["coefficients"][dep_metric] = {
            "intercept": float(coefs[0]),
            "growth": float(coefs[1]),
            "roe": float(coefs[2]),
            "log_size": float(coefs[3]),
            "leverage": float(coefs[4]),
            "r_squared": round(r_squared, 4),
            "cohort_size": len(rows),
        }

    if richness_values:
        mean_richness = mean(richness_values)
        output["score"] = _clip_score(50.0 - mean_richness * 20.0)
        output["mean_richness_z"] = round(mean_richness, 4)
    return output
