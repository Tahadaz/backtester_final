from __future__ import annotations

from collections import Counter, defaultdict
from math import isfinite
from statistics import mean, median, pstdev
from typing import Iterable

from .cgnc_mapping import FINANCIAL_ARCHETYPES, FINANCIAL_SUPPRESSED_METRICS, resolve_metric_name
from .domain import AnnualMetricRow, FundamentalSnapshot
from .screens import altman_z, eva, magic_formula, peg_garp, regression_adjusted_multiples
from .valuation import DEFAULT_ASSUMPTIONS


LOWER_IS_BETTER = {
    "PER",
    "Price_to_Book",
    "Price_to_Sales",
    "EV_to_EBIT",
    "EV_to_Sales",
    "EV_to_EBITDA",
    "Debt_to_Equity",
    "NetDebt_to_Equity",
    "NetDebt_to_EBITDA",
    "Equity_Multiplier",
    # Bank-specific: lower = better credit quality / efficiency / funding risk
    "Cout_du_risque",
    "Cost_to_Income",
    "Loans_to_Deposits",
    # Insurance-specific: combined ratio < 1 = underwriting profit
    "Combined_Ratio",
}

# Industrial pillar metric sets
VALUE_METRICS = ("PER", "Price_to_Book", "Price_to_Sales", "EV_to_EBITDA", "FCF_Yield", "Dividend_Yield")
QUALITY_METRICS = ("ROE", "ROA", "Operating_Margin", "Net_Margin")
GROWTH_METRICS = ("Revenue_Growth", "EBIT_Growth", "NetIncome_Growth")
DIVIDEND_METRICS = ("Dividend_Coverage", "Dividend_Payout")
RISK_METRICS = ("Debt_to_Equity", "NetDebt_to_EBITDA", "Equity_Multiplier")
CASH_FLOW_METRICS = ("FCF_Margin", "Operating_CF_Margin", "CAF_Margin")
HEALTH_METRICS = ("Current_Ratio", "Cash_Ratio", "Interest_Coverage")

# Bank pillar metric sets — FINANCIAL_SUPPRESSED_METRICS are never included
BANK_VALUE_METRICS = ("PER", "Price_to_Book", "Dividend_Yield")
BANK_QUALITY_METRICS = ("ROE", "ROA", "Net_Interest_Margin", "Cost_to_Income")
BANK_GROWTH_METRICS = ("Revenue_Growth", "NetIncome_Growth")
BANK_RISK_METRICS = ("Cout_du_risque", "Loans_to_Deposits")
BANK_CASH_FLOW_METRICS: tuple[str, ...] = ()
BANK_HEALTH_METRICS: tuple[str, ...] = ()

# Generic financial archetype (insurance, leasing, …)
FINANCIAL_VALUE_METRICS = ("PER", "Price_to_Book", "Dividend_Yield")
FINANCIAL_QUALITY_METRICS = ("ROE", "ROA", "Net_Margin", "Combined_Ratio")
FINANCIAL_GROWTH_METRICS = ("Revenue_Growth", "NetIncome_Growth")
FINANCIAL_RISK_METRICS = ("Equity_Multiplier",)
FINANCIAL_CASH_FLOW_METRICS: tuple[str, ...] = ()
FINANCIAL_HEALTH_METRICS: tuple[str, ...] = ()

TRAILING_METRICS = (
    "ROE",
    "ROA",
    "Revenue_Growth",
    "NetIncome_Growth",
    "Operating_Margin",
    "FCF_Margin",
    "Debt_to_Equity",
)
SCORING_TRAILING_METRICS = tuple(dict.fromkeys((
    *VALUE_METRICS, *QUALITY_METRICS,
    *BANK_VALUE_METRICS, *BANK_QUALITY_METRICS,
    *FINANCIAL_VALUE_METRICS, *FINANCIAL_QUALITY_METRICS,
)))
SMOOTHING_DIAGNOSTIC_METRICS = tuple(dict.fromkeys((*TRAILING_METRICS, *SCORING_TRAILING_METRICS)))

OVERALL_WEIGHTS = {
    "value": 0.20,
    "quality": 0.22,
    "growth": 0.16,
    "risk": 0.14,
    "cash_flow": 0.14,
    "health": 0.14,
}


def _clean(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _ratio(value: float | None) -> float | None:
    out = _clean(value)
    if out is None:
        return None
    return out / 100.0 if abs(out) > 2.0 else out


def _percentile_scores(values: dict[str, float], *, lower_is_better: bool, min_cohort: int = 3) -> dict[str, float | None]:
    if not values:
        return {}
    if len(values) < min_cohort:
        return {symbol: None for symbol in values}
    ordered = sorted(values.items(), key=lambda item: item[1])
    n = len(ordered)
    scores: dict[str, float | None] = {}
    for rank, (symbol, _) in enumerate(ordered):
        pct = 100.0 * rank / (n - 1)
        scores[symbol] = 100.0 - pct if lower_is_better else pct
    return scores


def _metric_breakdown(values: dict[str, float], *, lower_is_better: bool, min_cohort: int = 3) -> dict[str, dict[str, float | None]]:
    if not values:
        return {}
    if len(values) < min_cohort:
        return {
            symbol: {"value": value, "median": None, "z_score": None, "pct_deviation_from_median": None}
            for symbol, value in values.items()
        }
    vals = list(values.values())
    median_value = median(vals)
    stdev_value = pstdev(vals) if len(vals) > 1 else 0.0
    sign = -1.0 if lower_is_better else 1.0
    out: dict[str, dict[str, float | None]] = {}
    for symbol, value in values.items():
        z_score = sign * ((value - median_value) / stdev_value) if stdev_value > 0 else 0.0
        pct_dev = sign * ((value / median_value) - 1.0) if median_value else 0.0
        out[symbol] = {
            "value": value,
            "median": median_value,
            "z_score": z_score,
            "pct_deviation_from_median": pct_dev,
        }
    return out


def _metric_percentiles(
    snapshots: Iterable[FundamentalSnapshot],
    *,
    sectors: dict[str, str | None] | None = None,
    peer_min_count: int = 3,
) -> dict[str, dict[str, dict[str, float | str | None]]]:
    rows = list(snapshots)
    metric_names = sorted({metric for row in rows for metric in row.metrics})
    sector_map = sectors or {}
    out: dict[str, dict[str, dict[str, float | str | None]]] = {}
    for metric in metric_names:
        lower_is_better = metric in LOWER_IS_BETTER
        market_values = {
            row.symbol: value
            for row in rows
            if (value := _clean(row.metrics.get(metric))) is not None
        }
        market_scores = _percentile_scores(market_values, lower_is_better=lower_is_better, min_cohort=peer_min_count)
        market_breakdown = _metric_breakdown(market_values, lower_is_better=lower_is_better, min_cohort=peer_min_count)
        by_sector: dict[str, dict[str, float]] = defaultdict(dict)
        for symbol, value in market_values.items():
            sector = sector_map.get(symbol)
            if sector:
                by_sector[sector][symbol] = value
        metric_out: dict[str, dict[str, float | str | None]] = {}
        for sector_values in by_sector.values():
            if len(sector_values) < peer_min_count:
                continue
            sector_scores = _percentile_scores(sector_values, lower_is_better=lower_is_better, min_cohort=peer_min_count)
            sector_breakdown = _metric_breakdown(sector_values, lower_is_better=lower_is_better, min_cohort=peer_min_count)
            for symbol, score in sector_scores.items():
                metric_out[symbol] = {
                    "score": score,
                    "scope": "sector",
                    "cohort_size": float(len(sector_values)),
                    **sector_breakdown.get(symbol, {}),
                }
        for symbol, score in market_scores.items():
            if symbol in metric_out:
                continue
            metric_out[symbol] = {
                "score": score,
                "scope": "market" if score is not None else "insufficient",
                "cohort_size": float(len(market_values)),
                **market_breakdown.get(symbol, {}),
            }
        out[metric] = metric_out
    return out


def _avg(items: Iterable[float | None]) -> float | None:
    values = [float(item) for item in items if item is not None and isfinite(float(item))]
    return mean(values) if values else None


def _clip_score(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, min(100.0, float(value))), 4)


def _score_group(symbol: str, percentiles: dict[str, dict[str, dict[str, float | str | None]]], metrics: tuple[str, ...]) -> float | None:
    return _clip_score(_avg(_clean(percentiles.get(metric, {}).get(symbol, {}).get("score")) for metric in metrics))


def _score_scope(symbol: str, percentiles: dict[str, dict[str, dict[str, float | str | None]]], metrics: tuple[str, ...]) -> str:
    scopes = [
        str(entry.get("scope"))
        for metric in metrics
        if (entry := percentiles.get(metric, {}).get(symbol))
    ]
    if not scopes:
        return "unavailable"
    counts = Counter(scopes)
    if counts.get("sector", 0) >= counts.get("market", 0) and counts.get("sector", 0) > 0:
        return "sector"
    if counts.get("market", 0) > 0:
        return "market"
    return "insufficient"


def _history_by_symbol(rows: Iterable[AnnualMetricRow] | None) -> dict[str, list[AnnualMetricRow]]:
    out: dict[str, list[AnnualMetricRow]] = defaultdict(list)
    for row in rows or []:
        out[row.symbol].append(row)
    for symbol in out:
        out[symbol].sort(key=lambda item: (item.statement_year, item.metric_name))
    return out


def _series(history: list[AnnualMetricRow], *metric_names: str) -> list[tuple[int, float]]:
    canonical_names = {resolve_metric_name(n) for n in metric_names}
    by_year: dict[int, float] = {}
    for row in history:
        if resolve_metric_name(row.metric_name) not in canonical_names:
            continue
        value = _clean(row.metric_value)
        if value is not None and row.statement_year not in by_year:
            by_year[row.statement_year] = value
    return sorted(by_year.items())


def _latest(history: list[AnnualMetricRow], *metric_names: str) -> float | None:
    values = _series(history, *metric_names)
    return values[-1][1] if values else None


def _previous(history: list[AnnualMetricRow], *metric_names: str) -> float | None:
    values = _series(history, *metric_names)
    return values[-2][1] if len(values) >= 2 else None


def _latest_point(history: list[AnnualMetricRow], *metric_names: str) -> dict[str, object]:
    values = _series(history, *metric_names)
    if not values:
        return {"metric_name": metric_names[0] if metric_names else None, "value": None, "statement_year": None}
    year, value = values[-1]
    return {"metric_name": resolve_metric_name(metric_names[0]) if metric_names else None, "value": value, "statement_year": year}


def _previous_point(history: list[AnnualMetricRow], *metric_names: str) -> dict[str, object]:
    values = _series(history, *metric_names)
    if len(values) < 2:
        return {"metric_name": metric_names[0] if metric_names else None, "value": None, "statement_year": None}
    year, value = values[-2]
    return {"metric_name": resolve_metric_name(metric_names[0]) if metric_names else None, "value": value, "statement_year": year}


def _snapshot_point(snapshot: FundamentalSnapshot, metric_name: str, value: float | None = None) -> dict[str, object]:
    return {
        "metric_name": resolve_metric_name(metric_name),
        "value": _clean(snapshot.metrics.get(metric_name)) if value is None else value,
        "statement_year": snapshot.latest_statement_year,
    }


def _trailing_average(history: list[AnnualMetricRow], metric_name: str, years: int = 3) -> float | None:
    values = _series(history, metric_name)
    if len(values) < years:
        return None
    return mean(value for _, value in values[-years:])


def _snapshot_with_smoothed_score_metrics(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow]) -> FundamentalSnapshot:
    metrics = dict(snapshot.metrics)
    for metric in SCORING_TRAILING_METRICS:
        trailing = _trailing_average(history, metric, 3)
        if trailing is not None:
            metrics[metric] = trailing
    return FundamentalSnapshot(
        symbol=snapshot.symbol,
        company_name=snapshot.company_name,
        latest_statement_year=snapshot.latest_statement_year,
        metrics=metrics,
        scores=snapshot.scores,
        diagnostics=snapshot.diagnostics,
        coverage=snapshot.coverage,
        model_eligibility=snapshot.model_eligibility,
        source=snapshot.source,
        as_of_date=snapshot.as_of_date,
        source_document_id=snapshot.source_document_id,
    )


def _trend_improved(history: list[AnnualMetricRow], metric_name: str, *, lower_is_better: bool = False) -> bool | None:
    latest = _latest(history, metric_name)
    previous = _previous(history, metric_name)
    if latest is None or previous is None:
        return None
    return latest < previous if lower_is_better else latest > previous


def _net_income_proxy(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow]) -> tuple[float | None, str | None]:
    value = _latest(history, "NetIncome", "Resultat_net", "Clean_Resultat_net")
    if value is not None:
        return value, "reported_resultat_net"
    revenue = _latest(history, "Revenue", "Chiffre_daffaires", "Clean_Chiffre_daffaires")
    net_margin = _ratio(snapshot.metrics.get("Net_Margin"))
    if revenue is not None and net_margin is not None:
        return revenue * net_margin, "revenue_times_net_margin"
    return None, None


def _dupont(snapshot: FundamentalSnapshot) -> dict[str, float | None]:
    net_margin = _ratio(snapshot.metrics.get("Net_Margin"))
    asset_turnover = _clean(snapshot.metrics.get("Asset_Turnover"))
    equity_multiplier = _clean(snapshot.metrics.get("Equity_Multiplier"))
    reported_roe = _ratio(snapshot.metrics.get("ROE"))
    implied = None
    if net_margin is not None and asset_turnover is not None and equity_multiplier is not None:
        implied = net_margin * asset_turnover * equity_multiplier
    gap = abs(implied - reported_roe) if implied is not None and reported_roe is not None else None
    quality = None
    if gap is not None:
        quality = _clip_score(100.0 - min(100.0, gap * 500.0))
    return {
        "net_margin": net_margin,
        "asset_turnover": asset_turnover,
        "equity_multiplier": equity_multiplier,
        "implied_roe": implied,
        "reported_roe": reported_roe,
        "roe_bridge_gap": gap,
        "score": quality,
    }


def _piotroski_lite(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow]) -> dict[str, object]:
    roa = _ratio(snapshot.metrics.get("ROA"))
    fcf = _latest(history, "Free_Cash_Flow")
    net_income, net_income_source = _net_income_proxy(snapshot, history)
    checks: list[dict[str, object]] = []

    def add(
        name: str,
        passed: bool | None,
        value: float | None = None,
        *,
        comparison: dict[str, object] | None = None,
    ) -> None:
        checks.append({
            "name": name,
            "available": passed is not None,
            "passed": bool(passed) if passed is not None else None,
            "value": value,
            "comparison": comparison or {},
        })

    add(
        "positive_roa",
        roa is not None and roa > 0,
        roa,
        comparison={"operator": "> 0", "current": _snapshot_point(snapshot, "ROA", roa)},
    )
    add(
        "positive_free_cash_flow",
        fcf is not None and fcf > 0,
        fcf,
        comparison={"operator": "> 0", "current": _latest_point(history, "Free_Cash_Flow")},
    )
    add(
        "roa_improving",
        _trend_improved(history, "ROA"),
        roa,
        comparison={"operator": ">", "current": _latest_point(history, "ROA"), "prior": _previous_point(history, "ROA")},
    )
    add(
        "cash_flow_exceeds_earnings",
        (fcf > net_income) if fcf is not None and net_income is not None else None,
        fcf,
        comparison={
            "operator": ">",
            "current": _latest_point(history, "Free_Cash_Flow"),
            "prior": {"metric_name": net_income_source or "NetIncome", "value": net_income, "statement_year": snapshot.latest_statement_year},
        },
    )
    add(
        "leverage_decreasing",
        _trend_improved(history, "Debt_to_Equity", lower_is_better=True),
        _clean(snapshot.metrics.get("Debt_to_Equity")),
        comparison={"operator": "<", "current": _latest_point(history, "Debt_to_Equity"), "prior": _previous_point(history, "Debt_to_Equity")},
    )
    add(
        "liquidity_improving",
        _trend_improved(history, "Current_Ratio"),
        _clean(snapshot.metrics.get("Current_Ratio")),
        comparison={"operator": ">", "current": _latest_point(history, "Current_Ratio"), "prior": _previous_point(history, "Current_Ratio")},
    )
    add(
        "operating_margin_improving",
        _trend_improved(history, "Operating_Margin"),
        _clean(snapshot.metrics.get("Operating_Margin")),
        comparison={"operator": ">", "current": _latest_point(history, "Operating_Margin"), "prior": _previous_point(history, "Operating_Margin")},
    )
    add(
        "asset_turnover_improving",
        _trend_improved(history, "Asset_Turnover"),
        _clean(snapshot.metrics.get("Asset_Turnover")),
        comparison={"operator": ">", "current": _latest_point(history, "Asset_Turnover"), "prior": _previous_point(history, "Asset_Turnover")},
    )
    revenue_growth = _ratio(snapshot.metrics.get("Revenue_Growth"))
    add(
        "positive_revenue_growth",
        (revenue_growth or 0.0) > 0,
        revenue_growth,
        comparison={"operator": "> 0", "current": _snapshot_point(snapshot, "Revenue_Growth", revenue_growth)},
    )

    available = [item for item in checks if item["available"]]
    passed = [item for item in available if item["passed"]]
    score = _clip_score(100.0 * len(passed) / len(available)) if available else None
    return {
        "score": score,
        "points": len(passed),
        "available_points": len(available),
        "max_points": len(checks),
        "checks": checks,
        "net_income_source": net_income_source,
    }


def _accrual_quality(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow]) -> dict[str, float | str | None]:
    fcf = _latest(history, "Free_Cash_Flow")
    net_income, source = _net_income_proxy(snapshot, history)
    if fcf is None or net_income is None or net_income == 0:
        return {"score": None, "cash_conversion": None, "accrual_ratio": None, "net_income_source": source}
    cash_conversion = fcf / abs(net_income)
    accrual_ratio = (net_income - fcf) / abs(net_income)
    score = _clip_score(50.0 + max(-50.0, min(50.0, cash_conversion * 35.0)))
    return {
        "score": score,
        "cash_conversion": cash_conversion,
        "accrual_ratio": accrual_ratio,
        "net_income_source": source,
    }


def _weighted_score(parts: dict[str, float | None]) -> tuple[float | None, float | None]:
    present = [(name, value) for name, value in parts.items() if value is not None]
    if not present:
        return None, None
    weight_sum = sum(OVERALL_WEIGHTS[name] for name, _ in present)
    if weight_sum <= 0:
        return None, None
    raw = sum(float(value) * OVERALL_WEIGHTS[name] for name, value in present) / weight_sum
    coverage = weight_sum / sum(OVERALL_WEIGHTS.values())
    if coverage < 0.5:
        return None, coverage
    return _clip_score(raw), coverage


def _get_archetype(snapshot: FundamentalSnapshot) -> str:
    arch = snapshot.diagnostics.get("archetype") or snapshot.source.get("archetype")
    return str(arch) if arch else "unknown"


def _pillar_metrics_for_archetype(archetype: str) -> dict[str, tuple[str, ...]]:
    if archetype == "bank":
        return {
            "value": BANK_VALUE_METRICS,
            "quality": BANK_QUALITY_METRICS,
            "growth": BANK_GROWTH_METRICS,
            "risk": BANK_RISK_METRICS,
            "cash_flow": BANK_CASH_FLOW_METRICS,
            "health": BANK_HEALTH_METRICS,
        }
    if archetype in FINANCIAL_ARCHETYPES:
        return {
            "value": FINANCIAL_VALUE_METRICS,
            "quality": FINANCIAL_QUALITY_METRICS,
            "growth": FINANCIAL_GROWTH_METRICS,
            "risk": FINANCIAL_RISK_METRICS,
            "cash_flow": FINANCIAL_CASH_FLOW_METRICS,
            "health": FINANCIAL_HEALTH_METRICS,
        }
    return {
        "value": VALUE_METRICS,
        "quality": QUALITY_METRICS,
        "growth": GROWTH_METRICS,
        "risk": RISK_METRICS,
        "cash_flow": CASH_FLOW_METRICS,
        "health": HEALTH_METRICS,
    }


def score_fundamental_snapshots(
    snapshots: list[FundamentalSnapshot],
    annual_metrics: Iterable[AnnualMetricRow] | None = None,
    *,
    sectors: dict[str, str | None] | None = None,
    peer_min_count: int = 3,
) -> list[FundamentalSnapshot]:
    """Attach ranked scores plus explainable fundamental diagnostics."""

    history = _history_by_symbol(annual_metrics)
    scoring_snapshots = [
        _snapshot_with_smoothed_score_metrics(snapshot, history.get(snapshot.symbol, []))
        for snapshot in snapshots
    ]

    # Financial-archetype stocks (banks, insurance) rank against archetype peers
    # only, not the mixed market — reuse sector-segmentation machinery by
    # assigning a synthetic sector key "__arch_<archetype>__".
    effective_sectors: dict[str, str | None] = dict(sectors or {})
    for snap in scoring_snapshots:
        archetype = _get_archetype(snap)
        if archetype in FINANCIAL_ARCHETYPES:
            effective_sectors[snap.symbol] = f"__arch_{archetype}__"

    percentiles = _metric_percentiles(scoring_snapshots, sectors=effective_sectors, peer_min_count=peer_min_count)
    out: list[FundamentalSnapshot] = []
    for snapshot in snapshots:
        archetype = _get_archetype(snapshot)
        pillars = _pillar_metrics_for_archetype(archetype)
        value_metrics = pillars["value"]
        quality_metrics = pillars["quality"]
        growth_metrics = pillars["growth"]
        risk_metrics = pillars["risk"]
        cash_flow_metrics = pillars["cash_flow"]
        health_metrics = pillars["health"]

        value_score = _score_group(snapshot.symbol, percentiles, value_metrics)
        quality_score = _score_group(snapshot.symbol, percentiles, quality_metrics)
        growth_score = _score_group(snapshot.symbol, percentiles, growth_metrics)
        dividend_score = _score_group(snapshot.symbol, percentiles, DIVIDEND_METRICS)
        risk_score = _score_group(snapshot.symbol, percentiles, risk_metrics)
        cash_flow_score = _score_group(snapshot.symbol, percentiles, cash_flow_metrics)
        health_score = _score_group(snapshot.symbol, percentiles, health_metrics)
        symbol_history = history.get(snapshot.symbol, [])
        dupont = _dupont(snapshot)
        piotroski = _piotroski_lite(snapshot, symbol_history)
        accrual = _accrual_quality(snapshot, symbol_history)
        accounting_discipline = _clip_score(_avg([_clean(piotroski.get("score")), _clean(dupont.get("score"))]))
        accrual_score = _clean(accrual.get("score"))

        adjusted_quality = _clip_score(_avg([quality_score, accounting_discipline, accrual_score]))
        parts = {
            "value": value_score,
            "quality": adjusted_quality,
            "growth": growth_score,
            "risk": risk_score,
            "cash_flow": cash_flow_score,
            "health": health_score,
        }
        overall, overall_coverage = _weighted_score(parts)
        score_scopes = {
            "value": _score_scope(snapshot.symbol, percentiles, value_metrics),
            "quality": _score_scope(snapshot.symbol, percentiles, quality_metrics),
            "growth": _score_scope(snapshot.symbol, percentiles, growth_metrics),
            "dividend": _score_scope(snapshot.symbol, percentiles, DIVIDEND_METRICS),
            "risk": _score_scope(snapshot.symbol, percentiles, risk_metrics),
            "cash_flow": _score_scope(snapshot.symbol, percentiles, cash_flow_metrics),
            "health": _score_scope(snapshot.symbol, percentiles, health_metrics),
        }
        metric_breakdown = {
            metric: entry
            for metric, by_symbol in percentiles.items()
            if (entry := by_symbol.get(snapshot.symbol)) is not None
        }
        smoothing = {
            metric: {
                "latest": snapshot.metrics.get(metric),
                "trailing_3y": _trailing_average(symbol_history, metric, 3),
                "trailing_5y": _trailing_average(symbol_history, metric, 5),
                "scoring_input": percentiles.get(metric, {}).get(snapshot.symbol, {}).get("value"),
            }
            for metric in SMOOTHING_DIAGNOSTIC_METRICS
        }
        sector = (sectors or {}).get(snapshot.symbol)
        screens = {
            "magic_formula": magic_formula(snapshot, snapshots, sectors=sectors, peer_min_count=peer_min_count),
            "peg_garp": peg_garp(snapshot, symbol_history),
            "altman_z": altman_z(snapshot, symbol_history, sector),
            "eva": eva(snapshot, symbol_history, DEFAULT_ASSUMPTIONS, sector),
            "regression_adj": regression_adjusted_multiples(snapshot, snapshots, sectors=sectors, cohort_min_count=8),
        }
        snapshot.scores = {
            "overall": overall,
            "overall_coverage_pct": overall_coverage,
            "value": value_score,
            "quality": adjusted_quality,
            "quality_raw": quality_score,
            "quality_components": {
                "raw_percentile": quality_score,
                "accounting_discipline": accounting_discipline,
                "piotroski_lite": _clean(piotroski.get("score")),
                "dupont_bridge": _clean(dupont.get("score")),
                "accrual_quality": accrual_score,
            },
            "growth": growth_score,
            "risk": risk_score,
            "cash_flow": cash_flow_score,
            "health": health_score,
            "accrual_quality": accrual_score,
            "component_count": float(sum(score is not None for score in parts.values())),
        }
        snapshot.diagnostics = {
            "dupont": dupont,
            "piotroski_lite": piotroski,
            "accrual_quality": accrual,
            "accounting_discipline": accounting_discipline,
            "dividend": {"score": dividend_score, "metrics": DIVIDEND_METRICS},
            "score_scopes": score_scopes,
            "metric_breakdown": metric_breakdown,
            "smoothing": smoothing,
            "screens": screens,
        }
        out.append(snapshot)
    return out
