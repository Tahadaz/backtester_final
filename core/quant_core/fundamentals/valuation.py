from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import replace
from math import isfinite
from random import Random
from statistics import median
from typing import Any, Callable, Iterable

from .domain import AnnualMetricRow, EnsembleResult, FundamentalSnapshot, IntegrityReport, ValuationResult


MODEL_VERSION = "v3.0"
DEFAULT_CURRENCY = "MAD"

# Calibrated 2026-05 against:
#   - SGTM IPO prospectus (AMMC, Oct 2025): rf=2.88% BDT 10Y, ERP=6.07% broker avg, tax=35%
#   - Attijari GR (Oct 2025, 6.7%), CFG Research (Mar 2025, 5.0%), BMCE Capital GR (Feb 2025, 6.5%)
#   - Damodaran ctryprem (Jan 2026): Morocco total ERP 7.47% = 4.23% mature + 3.24% CRP
# We follow the Moroccan broker / SGTM convention: a single combined ERP that already
# embeds country risk, and no separate CRP layered on top (avoid double-counting).
DEFAULT_ASSUMPTIONS: dict[str, float] = {
    "risk_free_rate": 0.029,          # BDT 10Y, marché secondaire (~2.88% at 28/10/2025)
    "equity_risk_premium": 0.060,     # Moroccan broker consensus (Attijari/CFG/BMCE avg ~6.07%)
    "country_risk_premium": 0.000,    # already embedded in ERP above; do NOT double-count
    "cost_of_equity": 0.089,          # rf + 1.0 × ERP at default beta=1.0
    "cost_of_debt": 0.055,            # MAD corporate spread; consistent with SGTM
    "tax_rate": 0.35,                 # current effective IS for large groups (post-2023 reform)
    "wacc": 0.0786,                   # 0.70 × 0.089 + 0.30 × 0.055 × (1-0.35)
    "default_debt_weight": 0.30,
    "default_equity_weight": 0.70,
    "terminal_growth": 0.025,         # SGTM uses 2.5%; Moroccan IB practice 2.0-2.75%
    "forecast_years": 5.0,
    "fade_years": 5.0,
    "growth_cap": 0.08,
    "stable_payout_ratio": 0.55,
    "peer_min_count": 3.0,
    "proxy_weight_cap": 0.25,
    "bs_balance_warn_bps": 50.0,
    "bs_balance_fail_bps": 200.0,
    "sensitivity_wacc_step": 0.005,
    "sensitivity_terminal_growth_step": 0.005,
    "sensitivity_growth_cap_step": 0.01,
}

SCENARIO_DEFAULT_OVERRIDES: dict[str, dict[str, float]] = {
    "bear": {"growth_cap": 0.04, "terminal_growth": 0.020, "wacc": 0.090, "cost_of_equity": 0.105},
    "base": {},
    "bull": {"growth_cap": 0.12, "terminal_growth": 0.030, "wacc": 0.070, "cost_of_equity": 0.080},
}

VALUATION_MODEL_ORDER = (
    "relative_multiples",
    "reverse_dcf",
    "fcff_dcf",
    "fcfe_dcf",
    "ddm",
    "residual_income",
    "justified_multiples",
)

FINANCIAL_SECTOR_TOKENS = (
    "banque",
    "bank",
    "assurance",
    "insurance",
    "financement",
    "leasing",
    "credit",
)

CONFIDENCE_TO_SCORE = {
    "high": 0.85,
    "medium": 0.60,
    "low": 0.35,
    "unavailable": 0.0,
}

MODEL_BASE_WEIGHTS = {
    "fcff_dcf": 1.00,
    "fcfe_dcf": 0.75,
    "ddm": 0.70,
    "residual_income": 0.90,
    "justified_multiples": 0.75,
    "relative_multiples": 0.65,
    "reverse_dcf": 0.0,
}


def default_assumptions_for_scenario(scenario: str = "base") -> dict[str, float]:
    assumptions = dict(DEFAULT_ASSUMPTIONS)
    assumptions.update(SCENARIO_DEFAULT_OVERRIDES.get((scenario or "base").lower(), {}))
    return assumptions


def resolve_assumptions(
    symbol: str,
    scenario: str,
    *,
    overrides_loader: Callable[[str, str], dict[str, float] | None] | None = None,
) -> tuple[dict[str, float], dict[str, str]]:
    """Resolve default, scenario, and per-symbol assumption layers."""

    resolved = dict(DEFAULT_ASSUMPTIONS)
    provenance: dict[str, str] = {key: "default" for key in resolved}

    scenario_key = (scenario or "base").lower()
    for key, value in SCENARIO_DEFAULT_OVERRIDES.get(scenario_key, {}).items():
        resolved[key] = float(value)
        provenance[key] = "scenario"

    if overrides_loader is not None:
        symbol_overrides = overrides_loader(symbol.upper(), scenario_key) or {}
        for key, value in symbol_overrides.items():
            if key not in DEFAULT_ASSUMPTIONS:
                raise ValueError(f"unknown assumption key: {key}")
            resolved[key] = float(value)
            provenance[key] = "symbol"

    return resolved, provenance


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _ratio(value: Any) -> float | None:
    out = _num(value)
    if out is None:
        return None
    return out / 100.0 if abs(out) > 2.0 else out


def _dividend_yield_ratio(value: Any) -> float | None:
    out = _num(value)
    if out is None:
        return None
    # Dividend_Yield arrives from some import paths as percentage points
    # (1.52 means 1.52%), while older core fixtures use ratios (0.04 means 4%).
    return out / 100.0 if abs(out) > 0.25 else out


def _positive(value: Any) -> float | None:
    out = _num(value)
    return out if out is not None and out > 0 else None


def _growth(value: Any, cap: float) -> float:
    out = _ratio(value)
    if out is None:
        return 0.03
    return max(-0.05, min(cap, out))


def _snapshot_currency(snapshot: FundamentalSnapshot) -> str:
    raw = snapshot.source.get("currency") or snapshot.metrics.get("Currency") or DEFAULT_CURRENCY
    return str(raw or DEFAULT_CURRENCY).upper()


def _assumption_currency(assumptions: dict[str, Any] | None) -> str:
    raw = (assumptions or {}).get("currency", DEFAULT_CURRENCY)
    return str(raw or DEFAULT_CURRENCY).upper()


def _normalize_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _is_financial(sector: str | None) -> bool:
    normalized = _normalize_text(sector)
    return any(token in normalized for token in FINANCIAL_SECTOR_TOKENS)


def _latest_metric(history: list[AnnualMetricRow], *metrics: str) -> float | None:
    names = set(metrics)
    rows = [row for row in history if row.metric_name in names and row.metric_value is not None]
    if not rows:
        return None
    return sorted(rows, key=lambda row: row.statement_year)[-1].metric_value


def _metric_series(history: list[AnnualMetricRow], metric: str) -> list[float]:
    rows = sorted(
        (row for row in history if row.metric_name == metric and row.metric_value is not None),
        key=lambda row: row.statement_year,
    )
    return [float(row.metric_value) for row in rows if row.metric_value is not None and isfinite(float(row.metric_value))]


def _current_price(snapshot: FundamentalSnapshot) -> float | None:
    return _positive(snapshot.metrics.get("Current_Price"))


def _market_cap(snapshot: FundamentalSnapshot) -> float | None:
    return _positive(snapshot.metrics.get("MarketCap_Calc"))


def _shares(snapshot: FundamentalSnapshot) -> float | None:
    return _positive(snapshot.metrics.get("Shares_Outstanding"))


def _upside(fair_value: float | None, current_price: float | None) -> float | None:
    if fair_value is None or current_price is None or current_price <= 0:
        return None
    return fair_value / current_price - 1.0


def _confidence(base: str, warnings: list[str], *, proxy: bool = False) -> str:
    if base == "unavailable":
        return "unavailable"
    if proxy and base == "high":
        base = "medium"
    if warnings and base == "high":
        return "medium"
    if len(warnings) >= 2:
        return "low"
    return base


def _data_quality(confidence: str, warnings: list[str], proxy: bool = False) -> float:
    score = CONFIDENCE_TO_SCORE.get(confidence, 0.0) * 100.0
    score -= min(30.0, len(warnings) * 7.5)
    if proxy:
        score = min(score, 60.0)
    return max(0.0, min(100.0, score))


def _result(
    *,
    snapshot: FundamentalSnapshot,
    scenario: str,
    model: str,
    fair_value: float | None,
    current_price: float | None,
    confidence: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    methodology: str,
    family: str = "intrinsic",
    proxy: bool = False,
    currency: str | None = None,
) -> ValuationResult:
    warnings = warnings or []
    quality_score = _data_quality(confidence, warnings, proxy)
    confidence_score = quality_score / 100.0
    return ValuationResult(
        symbol=snapshot.symbol,
        scenario=scenario,
        model=model,
        fair_value=fair_value,
        current_price=current_price,
        upside_pct=_upside(fair_value, current_price),
        confidence=confidence,
        inputs=inputs,
        outputs=outputs or {},
        warnings=warnings,
        family=family,
        model_version=MODEL_VERSION,
        methodology=methodology,
        confidence_score=confidence_score,
        weight=None,
        is_proxy=proxy,
        data_quality_score=quality_score,
        currency=currency or _snapshot_currency(snapshot),
    )


def _peer_stats(
    snapshots: Iterable[FundamentalSnapshot],
    sectors: dict[str, str | None],
    target_symbol: str,
    peer_min_count: int,
) -> dict[str, dict[str, Any]]:
    target_sector = sectors.get(target_symbol)
    grouped: dict[str, list[float]] = defaultdict(list)
    fallback: dict[str, list[float]] = defaultdict(list)
    for row in snapshots:
        if row.symbol == target_symbol:
            continue
        for metric in ("PER", "Price_to_Book", "Price_to_Sales", "EV_to_EBITDA"):
            value = _positive(row.metrics.get(metric))
            if value is None:
                continue
            fallback[metric].append(value)
            if target_sector and sectors.get(row.symbol) == target_sector:
                grouped[metric].append(value)
    out: dict[str, dict[str, Any]] = {}
    for metric in ("PER", "Price_to_Book", "Price_to_Sales", "EV_to_EBITDA"):
        sector_values = grouped[metric]
        market_values = fallback[metric]
        source = sector_values if len(sector_values) >= peer_min_count else market_values
        if source:
            out[metric] = {
                "median": float(median(source)),
                "count": len(source),
                "scope": "sector" if source is sector_values else "market",
            }
    return out


def _has_dividend(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow]) -> bool:
    dividend_yield = _positive(_dividend_yield_ratio(snapshot.metrics.get("Dividend_Yield")))
    return dividend_yield is not None or (_latest_metric(history, "Dividendes", "Clean_Dividendes") or 0) > 0


def _eligible_models(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], sector: str | None) -> dict[str, Any]:
    financial = _is_financial(sector)
    positive_fcf = [value for value in _metric_series(history, "Free_Cash_Flow") if value > 0]
    has_fcf_proxy = (
        _positive(snapshot.metrics.get("FCF_Yield")) is not None
        or _positive(snapshot.metrics.get("FCF_Margin")) is not None
        or bool(positive_fcf)
    )
    has_book_roe = _positive(snapshot.metrics.get("Price_to_Book")) is not None and _num(snapshot.metrics.get("ROE")) is not None
    has_multiples = any(_positive(snapshot.metrics.get(metric)) is not None for metric in ("PER", "Price_to_Book", "EV_to_EBITDA"))
    has_price_market = _current_price(snapshot) is not None and _market_cap(snapshot) is not None
    return {
        "fcff_dcf": {
            "eligible": bool(not financial and has_fcf_proxy),
            "confidence": "high" if len(positive_fcf) >= 3 else ("medium" if has_fcf_proxy else "unavailable"),
        },
        "fcfe_dcf": {
            "eligible": bool(not financial and has_fcf_proxy),
            "confidence": "medium" if has_fcf_proxy else "unavailable",
            "proxy_required": True,
        },
        "ddm": {
            "eligible": bool(_has_dividend(snapshot, history)),
            "confidence": "high" if _positive(_dividend_yield_ratio(snapshot.metrics.get("Dividend_Yield"))) else ("medium" if _has_dividend(snapshot, history) else "unavailable"),
        },
        "residual_income": {
            "eligible": bool(has_book_roe),
            "confidence": "high" if financial and has_book_roe else ("medium" if has_book_roe else "unavailable"),
        },
        "justified_multiples": {
            "eligible": bool(has_book_roe or _positive(snapshot.metrics.get("PER")) is not None),
            "confidence": "high" if financial and has_book_roe else ("medium" if has_book_roe or _positive(snapshot.metrics.get("PER")) else "unavailable"),
        },
        "relative_multiples": {
            "eligible": bool(has_multiples),
            "confidence": "high" if sum(_positive(snapshot.metrics.get(metric)) is not None for metric in ("PER", "Price_to_Book", "EV_to_EBITDA")) >= 2 else ("medium" if has_multiples else "unavailable"),
        },
        "reverse_dcf": {
            "eligible": bool(has_price_market),
            "confidence": "medium" if has_price_market else "unavailable",
        },
        "is_financial": financial,
    }


def _fcf_start(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow]) -> tuple[float | None, str | None]:
    market_cap = _market_cap(snapshot)
    revenue = _latest_metric(history, "Chiffre_daffaires", "Clean_Chiffre_daffaires")
    fcf = _latest_metric(history, "Free_Cash_Flow")
    if fcf is not None:
        return fcf, "reported_free_cash_flow"
    fcf_yield = _ratio(snapshot.metrics.get("FCF_Yield"))
    if market_cap and fcf_yield is not None:
        return market_cap * fcf_yield, "market_cap_times_fcf_yield"
    fcf_margin = _ratio(snapshot.metrics.get("FCF_Margin"))
    if revenue and fcf_margin is not None:
        return revenue * fcf_margin, "revenue_times_fcf_margin"
    return None, None


def _fcf_growth_input(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], assumptions: dict[str, float]) -> tuple[float, str, bool]:
    cap = float(assumptions["growth_cap"])
    candidates = (
        ("FCF_Growth", "reported_fcf_growth", False),
        ("OperatingCF_Growth", "reported_operating_cf_growth", False),
        ("NetIncome_Growth", "earnings_growth_proxy", True),
        ("Revenue_Growth", "revenue_growth_proxy", True),
    )
    for metric_name, source, is_proxy in candidates:
        value = snapshot.metrics.get(metric_name)
        if value is not None:
            return _growth(value, cap), source, is_proxy
    fcf_series = _metric_series(history, "Free_Cash_Flow")
    if len(fcf_series) >= 4 and fcf_series[0] > 0:
        cagr = (fcf_series[-1] / fcf_series[0]) ** (1.0 / (len(fcf_series) - 1)) - 1.0
        return max(-0.05, min(cap, cagr)), "fcf_series_cagr", False
    return min(cap, 0.03), "default_3pct_no_data", True


def _net_debt_bridge(history: list[AnnualMetricRow]) -> tuple[float, str, bool]:
    net_debt = _latest_metric(history, "NetDebt")
    if net_debt is not None:
        return net_debt, "reported_net_debt", False
    debt = _latest_metric(history, "Total_Debt", "Debt_Total")
    cash = _latest_metric(history, "Cash_and_Equivalents", "Cash")
    if debt is not None and cash is not None:
        return debt - cash, "computed_from_debt_minus_cash", False
    if debt is not None:
        return debt, "debt_only_cash_missing", True
    return 0.0, "missing_net_debt_bridge", True


def _fcfe_start(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], assumptions: dict[str, float]) -> tuple[float | None, str | None, bool]:
    fcf, fcf_source = _fcf_start(snapshot, history)
    if fcf is None:
        return None, None, True
    tax_rate = float(assumptions.get("tax_rate", DEFAULT_ASSUMPTIONS["tax_rate"]))
    interest = abs(_latest_metric(history, "Interest_Expense", "Charges_Interets") or 0.0)
    issuance = _latest_metric(history, "Debt_Issuance", "Debt_Raised") or 0.0
    repayment = abs(_latest_metric(history, "Debt_Repayment", "Debt_Repaid") or 0.0)
    if interest == 0.0 and issuance == 0.0 and repayment == 0.0:
        return fcf, fcf_source, True
    fcfe = fcf - interest * (1.0 - tax_rate) + issuance - repayment
    return fcfe, f"{fcf_source}_adjusted_for_debt_flows" if fcf_source else "fcf_adjusted_for_debt_flows", False


def _sustainable_dividend_growth(snapshot: FundamentalSnapshot, assumptions: dict[str, float]) -> tuple[float, str, list[str]]:
    warnings: list[str] = []
    cap = float(assumptions["growth_cap"])
    roe = _ratio(snapshot.metrics.get("ROE"))
    payout = _ratio(snapshot.metrics.get("Dividend_Payout"))
    if payout is None or payout < 0 or payout > 1.5:
        payout = float(assumptions["stable_payout_ratio"])
        warnings.append("using_stable_payout_assumption")
    retention = max(0.0, min(1.0, 1.0 - payout))
    if roe is None:
        warnings.append("using_earnings_growth_proxy")
        return (
            _growth(snapshot.metrics.get("NetIncome_Growth") or snapshot.metrics.get("Revenue_Growth"), cap),
            "earnings_growth_proxy",
            warnings,
        )
    return max(-0.05, min(cap, roe * retention)), "sustainable_growth_from_roe_retention", warnings


def _justified_growth(sustainable_growth: float, terminal_growth: float, fade_years: int) -> float:
    if sustainable_growth <= terminal_growth:
        return sustainable_growth
    h_period = max(1, int(fade_years)) / 2.0
    return terminal_growth + h_period * (sustainable_growth - terminal_growth) / max(1, int(fade_years))


def _dcf_cash_flows(start: float, growth: float, terminal_growth: float, discount_rate: float, years: int) -> tuple[list[float], float | None]:
    projected: list[float] = []
    present_value = 0.0
    current = start
    for step in range(1, years + 1):
        fade = step / max(years, 1)
        step_growth = growth * (1.0 - fade) + terminal_growth * fade
        current *= 1.0 + step_growth
        projected.append(current)
        present_value += current / ((1.0 + discount_rate) ** step)
    if not projected or discount_rate <= terminal_growth:
        return projected, None
    terminal_value = projected[-1] * (1.0 + terminal_growth) / (discount_rate - terminal_growth)
    return projected, present_value + terminal_value / ((1.0 + discount_rate) ** years)


def _fcff_dcf(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], current_price: float | None, assumptions: dict[str, float], scenario: str) -> ValuationResult:
    warnings: list[str] = []
    fcf, fcf_source = _fcf_start(snapshot, history)
    shares = _shares(snapshot)
    if fcf is None or fcf <= 0:
        warnings.append("missing_positive_fcf")
    if not shares:
        warnings.append("missing_shares")
    wacc = float(assumptions["wacc"])
    terminal_growth = float(assumptions["terminal_growth"])
    if wacc <= terminal_growth:
        warnings.append("wacc_not_above_terminal_growth")
    years = int(assumptions["forecast_years"])
    growth, growth_source, growth_is_proxy = _fcf_growth_input(snapshot, history, assumptions)
    if growth_is_proxy:
        warnings.append(growth_source)
    net_debt, net_debt_source, net_debt_warning = _net_debt_bridge(history)
    if net_debt_warning:
        warnings.append("missing_net_debt_bridge")
    fair = None
    projected: list[float] = []
    if fcf and fcf > 0 and shares and wacc > terminal_growth:
        projected, enterprise_value = _dcf_cash_flows(fcf, growth, terminal_growth, wacc, years)
        if enterprise_value is not None:
            fair = max(0.0, enterprise_value - net_debt) / shares
    base = "high" if len([v for v in _metric_series(history, "Free_Cash_Flow") if v > 0]) >= 3 else "medium"
    confidence = _confidence(base, warnings)
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model="fcff_dcf",
        fair_value=fair,
        current_price=current_price,
        confidence=confidence,
        inputs={
            "fcf_start": fcf,
            "fcf_source": fcf_source,
            "growth": growth,
            "fcf_growth_source": growth_source,
            "wacc": wacc,
            "terminal_growth": terminal_growth,
            "net_debt": net_debt,
            "net_debt_source": net_debt_source,
        },
        outputs={"projected_fcf": projected},
        warnings=warnings,
        methodology="FCFF discounted cash flow with fading growth and net-debt bridge to equity value.",
    )


def _fcfe_dcf(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], current_price: float | None, assumptions: dict[str, float], scenario: str) -> ValuationResult:
    warnings: list[str] = []
    fcfe, fcfe_source, is_proxy = _fcfe_start(snapshot, history, assumptions)
    if is_proxy:
        warnings.append("fcfe_proxy_from_free_cash_flow")
    shares = _shares(snapshot)
    if fcfe is None or fcfe <= 0:
        warnings.append("missing_positive_equity_cash_flow_proxy")
    if not shares:
        warnings.append("missing_shares")
    cost = float(assumptions["cost_of_equity"])
    terminal_growth = float(assumptions["terminal_growth"])
    if cost <= terminal_growth:
        warnings.append("cost_of_equity_not_above_terminal_growth")
    years = int(assumptions["forecast_years"])
    growth = _growth(snapshot.metrics.get("NetIncome_Growth") or snapshot.metrics.get("Revenue_Growth"), float(assumptions["growth_cap"]))
    fair = None
    projected: list[float] = []
    if fcfe and fcfe > 0 and shares and cost > terminal_growth:
        projected, equity_value = _dcf_cash_flows(fcfe, growth, terminal_growth, cost, years)
        if equity_value is not None:
            fair = max(0.0, equity_value) / shares
    base = "high" if not is_proxy and len([v for v in _metric_series(history, "Free_Cash_Flow") if v > 0]) >= 3 else "medium"
    confidence = _confidence(base, warnings, proxy=is_proxy)
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model="fcfe_dcf",
        fair_value=fair,
        current_price=current_price,
        confidence=confidence,
        inputs={"fcfe_start": fcfe, "fcfe_source": fcfe_source, "growth": growth, "cost_of_equity": cost, "terminal_growth": terminal_growth},
        outputs={"projected_fcfe": projected},
        warnings=warnings,
        methodology="FCFE equity DCF using debt-flow-adjusted free cash flow when available; otherwise positive FCF is treated as a capped-confidence proxy.",
        proxy=is_proxy,
    )


def _ddm(snapshot: FundamentalSnapshot, history: list[AnnualMetricRow], current_price: float | None, assumptions: dict[str, float], scenario: str) -> ValuationResult:
    warnings: list[str] = []
    cost = float(assumptions["cost_of_equity"])
    terminal_growth = float(assumptions["terminal_growth"])
    fade_years = max(1, int(assumptions["fade_years"]))
    h_factor = fade_years / 2.0
    if cost <= terminal_growth:
        warnings.append("cost_of_equity_not_above_terminal_growth")
    latest_dividend_total = _latest_metric(history, "Dividendes", "Clean_Dividendes")
    shares = _shares(snapshot)
    dividend_source = None
    dividend = None
    if latest_dividend_total and shares:
        dividend = latest_dividend_total / shares
        dividend_source = "reported_dividends_per_share"
    dividend_yield = _dividend_yield_ratio(snapshot.metrics.get("Dividend_Yield"))
    if dividend is None and current_price and dividend_yield and dividend_yield > 0:
        dividend = current_price * dividend_yield
        dividend_source = "dividend_yield_times_price"
    if dividend is None or dividend <= 0:
        warnings.append("missing_positive_dividend")
    growth, growth_source, growth_warnings = _sustainable_dividend_growth(snapshot, assumptions)
    warnings.extend(item for item in growth_warnings if item not in warnings)
    if growth < terminal_growth:
        warnings.append("ddm_growth_below_terminal")
    spread = max(0.0, growth - terminal_growth)
    fair = (
        dividend * ((1.0 + terminal_growth) + h_factor * spread) / (cost - terminal_growth)
        if dividend and cost > terminal_growth
        else None
    )
    confidence = _confidence("high" if dividend_yield else "medium", warnings)
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model="ddm",
        fair_value=fair,
        current_price=current_price,
        confidence=confidence,
        inputs={
            "dividend_per_share": dividend,
            "dividend_source": dividend_source,
            "reported_dividend_total": latest_dividend_total,
            "shares": shares,
            "dividend_yield": dividend_yield,
            "growth": growth,
            "growth_source": growth_source,
            "cost_of_equity": cost,
            "terminal_growth": terminal_growth,
            "fade_years": fade_years,
            "h_factor": h_factor,
        },
        warnings=warnings,
        methodology="H-model dividend discount model for dividend-paying stocks.",
    )


def _residual_income(snapshot: FundamentalSnapshot, current_price: float | None, assumptions: dict[str, float], scenario: str, is_financial: bool) -> ValuationResult:
    warnings: list[str] = []
    cost = float(assumptions["cost_of_equity"])
    fade_years = max(1, int(assumptions["fade_years"]))
    payout = _ratio(snapshot.metrics.get("Dividend_Payout"))
    if payout is None or payout < 0 or payout > 1.5:
        payout = float(assumptions["stable_payout_ratio"])
        warnings.append("using_stable_payout_assumption")
    retention = max(0.0, min(1.0, 1.0 - payout))
    pb = _positive(snapshot.metrics.get("Price_to_Book"))
    roe = _ratio(snapshot.metrics.get("ROE"))
    book_value = current_price / pb if current_price and pb else None
    if book_value is None:
        warnings.append("missing_book_value_proxy")
    if roe is None:
        warnings.append("missing_roe")
    fair = None
    projected: list[dict[str, float]] = []
    if book_value and roe is not None and cost > 0:
        book = book_value
        pv_residual_income = 0.0
        for year in range(1, fade_years + 2):
            fade = (year - 1) / fade_years
            year_roe = roe * (1.0 - fade) + cost * fade
            residual_income = book * (year_roe - cost)
            pv_residual_income += residual_income / ((1.0 + cost) ** year)
            projected.append({"year": float(year), "roe": year_roe, "book_value": book, "residual_income": residual_income})
            book *= 1.0 + year_roe * retention
        fair = max(0.0, book_value + pv_residual_income)
    confidence = _confidence("high" if is_financial else "medium", warnings)
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model="residual_income",
        fair_value=fair,
        current_price=current_price,
        confidence=confidence,
        inputs={"book_value_per_share": book_value, "roe": roe, "cost_of_equity": cost, "fade_years": fade_years, "payout": payout},
        outputs={"projected_residual_income": projected},
        warnings=warnings,
        methodology="Residual income model with ROE spread fading linearly to cost of equity over the competitive erosion horizon.",
    )


def _justified_multiples(snapshot: FundamentalSnapshot, current_price: float | None, assumptions: dict[str, float], scenario: str, is_financial: bool) -> ValuationResult:
    warnings: list[str] = []
    cost = float(assumptions["cost_of_equity"])
    terminal_growth = float(assumptions["terminal_growth"])
    fade_years = int(assumptions["fade_years"])
    roe = _ratio(snapshot.metrics.get("ROE"))
    payout = _ratio(snapshot.metrics.get("Dividend_Payout"))
    if payout is None or payout < 0 or payout > 1.5:
        payout = float(assumptions["stable_payout_ratio"])
        warnings.append("using_stable_payout_assumption")
    retention = max(0.0, min(1.0, 1.0 - payout))
    sustainable_growth = min(float(assumptions["growth_cap"]), max(-0.05, (roe or 0.0) * retention))
    growth = _justified_growth(sustainable_growth, terminal_growth, fade_years)
    if cost <= growth:
        warnings.append("cost_of_equity_not_above_justified_growth")
    implied_prices: dict[str, float] = {}
    if current_price and cost > growth:
        pb = _positive(snapshot.metrics.get("Price_to_Book"))
        if roe is not None and pb:
            justified_pb = max(0.0, (roe - growth) / (cost - growth))
            if justified_pb > 0:
                implied_prices["justified_pb"] = current_price * justified_pb / pb
        per = _positive(snapshot.metrics.get("PER"))
        if per and payout > 0:
            justified_pe = payout * (1.0 + growth) / (cost - growth)
            if justified_pe > 0:
                implied_prices["justified_pe"] = current_price * justified_pe / per
    if not implied_prices:
        warnings.append("no_usable_justified_multiple")
    fair = float(median(implied_prices.values())) if implied_prices else None
    base = "high" if is_financial and "justified_pb" in implied_prices else ("medium" if implied_prices else "unavailable")
    confidence = _confidence(base, warnings)
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model="justified_multiples",
        fair_value=fair,
        current_price=current_price,
        confidence=confidence,
        inputs={
            "roe": roe,
            "payout": payout,
            "sustainable_growth": sustainable_growth,
            "growth": growth,
            "terminal_growth": terminal_growth,
            "fade_years": fade_years,
            "cost_of_equity": cost,
        },
        outputs={"implied_prices": implied_prices},
        warnings=warnings,
        methodology="Justified P/B and P/E from ROE, payout, growth, and cost of equity.",
        family="relative",
    )


def _relative_multiples(snapshot: FundamentalSnapshot, current_price: float | None, peer_stats: dict[str, dict[str, Any]], scenario: str) -> ValuationResult:
    warnings: list[str] = []
    implied: dict[str, float] = {}
    if current_price is None:
        warnings.append("missing_current_price")
    else:
        for metric in ("PER", "Price_to_Book", "Price_to_Sales", "EV_to_EBITDA"):
            own = _positive(snapshot.metrics.get(metric))
            peer = _positive(peer_stats.get(metric, {}).get("median"))
            if own and peer:
                implied[metric] = current_price * peer / own
        if not implied:
            warnings.append("no_usable_peer_multiple")
    fair = float(median(implied.values())) if implied else None
    confidence = "high" if len(implied) >= 3 else ("medium" if len(implied) >= 2 else ("low" if implied else "unavailable"))
    confidence = _confidence(confidence, warnings)
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model="relative_multiples",
        fair_value=fair,
        current_price=current_price,
        confidence=confidence,
        inputs={"peer_stats": peer_stats, "own_multiples": {m: snapshot.metrics.get(m) for m in peer_stats}},
        outputs={"implied_prices": implied},
        warnings=warnings,
        methodology="Peer-relative valuation using sector medians when enough peers exist, otherwise market medians.",
        family="relative",
    )


def _reverse_dcf(snapshot: FundamentalSnapshot, current_price: float | None, assumptions: dict[str, float], scenario: str) -> ValuationResult:
    warnings: list[str] = []
    market_cap = _market_cap(snapshot)
    fcf_yield = _ratio(snapshot.metrics.get("FCF_Yield"))
    implied = None
    if fcf_yield and fcf_yield > 0:
        implied = float(assumptions["wacc"]) - fcf_yield
    else:
        warnings.append("missing_fcf_yield_for_reverse_dcf")
    confidence = _confidence("medium" if market_cap and current_price else "unavailable", warnings)
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model="reverse_dcf",
        fair_value=None,
        current_price=current_price,
        confidence=confidence,
        inputs={"market_cap": market_cap, "fcf_yield": fcf_yield, "wacc": assumptions["wacc"]},
        outputs={
            "implied_perpetual_growth": implied,
            "interpretation": (
                f"Market implies {implied * 100:.1f}% perpetual FCF growth at WACC={float(assumptions['wacc']) * 100:.1f}%."
                if implied is not None
                else None
            ),
        },
        warnings=warnings,
        methodology="Reverse DCF diagnostic. fair_value is intentionally empty; primary output is implied_perpetual_growth.",
        family="diagnostic",
    )


def _unavailable(snapshot: FundamentalSnapshot, scenario: str, model: str, current_price: float | None, reason: str) -> ValuationResult:
    return _result(
        snapshot=snapshot,
        scenario=scenario,
        model=model,
        fair_value=None,
        current_price=current_price,
        confidence="unavailable",
        inputs={},
        outputs={},
        warnings=[reason],
        methodology="Model not run because eligibility rules were not satisfied.",
    )


def _integrity_warning(report: IntegrityReport) -> str | None:
    status = report.overall_status
    if status == "pass":
        return None
    failed = [
        check.name
        for check in report.checks
        if check.status in {"fail", "warn", "derived", "unavailable"}
    ]
    suffix = ",".join(failed) if failed else "all_checks_unavailable"
    if status == "fail":
        return f"integrity_fail: {suffix}"
    if status == "warn":
        return f"integrity_warn: {suffix}"
    if status == "derived":
        return f"integrity_derived_cash: {suffix}"
    return "integrity_unavailable"


def _apply_integrity_report(results: list[ValuationResult], report: IntegrityReport | None) -> list[ValuationResult]:
    if report is None or report.overall_status == "pass":
        return results
    haircut = max(0.0, min(0.5, float(report.confidence_haircut or 0.0)))
    warning = _integrity_warning(report)
    adjusted: list[ValuationResult] = []
    for row in results:
        confidence_score = row.confidence_score
        data_quality_score = row.data_quality_score
        if confidence_score is not None:
            confidence_score = max(0.0, confidence_score * (1.0 - haircut))
        if data_quality_score is not None:
            data_quality_score = max(0.0, data_quality_score * (1.0 - haircut))
        warnings = list(row.warnings)
        if warning and warning not in warnings:
            warnings.append(warning)
        adjusted.append(
            replace(
                row,
                warnings=warnings,
                confidence_score=confidence_score,
                data_quality_score=data_quality_score,
                is_proxy=True if report.overall_status == "fail" else row.is_proxy,
            )
        )
    return adjusted


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct))))
    return ordered[index]


def _monte_carlo_band(usable: list[tuple[ValuationResult, float]], total_weight: float, *, seed: str, samples: int = 500) -> tuple[float | None, float | None, float | None]:
    if not usable or total_weight <= 0:
        return None, None, None
    rng = Random(seed)
    draws: list[float] = []
    for _ in range(samples):
        fair = 0.0
        for row, weight in usable:
            if row.fair_value is None:
                continue
            confidence = row.confidence_score if row.confidence_score is not None else CONFIDENCE_TO_SCORE.get(row.confidence, 0.0)
            sigma = max(0.03, (1.0 - confidence) * 0.18)
            shocked = max(0.0, float(row.fair_value) * (1.0 + rng.gauss(0.0, sigma)))
            fair += shocked * weight
        draws.append(fair / total_weight)
    return _percentile(draws, 0.05), _percentile(draws, 0.50), _percentile(draws, 0.95)


def compute_valuation_ensemble(symbol: str, scenario: str, valuations: list[ValuationResult]) -> EnsembleResult:
    usable: list[tuple[ValuationResult, float]] = []
    warnings: list[str] = []
    currencies = {row.currency for row in valuations if row.currency}
    currency = sorted(currencies)[0] if currencies else DEFAULT_CURRENCY
    if len(currencies) > 1:
        warnings.append("mixed_model_currencies")
    for result in valuations:
        if result.family == "diagnostic":
            continue
        if result.fair_value is None or result.current_price is None or result.confidence not in {"high", "medium", "low"}:
            continue
        base_weight = MODEL_BASE_WEIGHTS.get(result.model, 0.0)
        if base_weight <= 0:
            continue
        confidence_score = result.confidence_score if result.confidence_score is not None else CONFIDENCE_TO_SCORE.get(result.confidence, 0.0)
        weight = base_weight * confidence_score
        if result.is_proxy:
            weight = min(weight, MODEL_BASE_WEIGHTS.get(result.model, 0.0) * DEFAULT_ASSUMPTIONS["proxy_weight_cap"])
            warnings.append(f"{result.model}_proxy_weight_capped")
        if weight > 0:
            usable.append((result, weight))
    current_price = next((row.current_price for row in valuations if row.current_price), None)
    if not usable:
        return EnsembleResult(
            symbol=symbol,
            scenario=scenario,
            fair_value_low=None,
            fair_value_base=None,
            fair_value_high=None,
            current_price=current_price,
            upside_pct=None,
            confidence_score=None,
            usable_model_count=0,
            excluded_model_count=len(valuations),
            model_weights={},
            warnings=[*warnings, "no_usable_valuation_models"],
            currency=currency,
        )
    total_weight = sum(weight for _, weight in usable)
    ordered = sorted((float(row.fair_value), weight, row.model) for row, weight in usable if row.fair_value is not None)
    fair_base = sum(value * weight for value, weight, _ in ordered) / total_weight
    low_index = max(0, int(len(ordered) * 0.25) - 1)
    high_index = min(len(ordered) - 1, int(len(ordered) * 0.75))
    fair_low = min(fair_base, ordered[low_index][0])
    fair_high = max(fair_base, ordered[high_index][0])
    model_weights = {model: round(weight / total_weight, 6) for _, weight, model in ordered}
    confidence = sum((row.confidence_score or 0.0) * weight for row, weight in usable) / total_weight
    mc_low, mc_base, mc_high = _monte_carlo_band(usable, total_weight, seed=f"{symbol}:{scenario}:{currency}")
    return EnsembleResult(
        symbol=symbol,
        scenario=scenario,
        fair_value_low=mc_low if mc_low is not None else fair_low,
        fair_value_base=fair_base,
        fair_value_high=mc_high if mc_high is not None else fair_high,
        current_price=current_price,
        upside_pct=_upside(fair_base, current_price),
        confidence_score=confidence,
        usable_model_count=len(usable),
        excluded_model_count=max(0, len(valuations) - len(usable)),
        model_weights=model_weights,
        warnings=warnings,
        currency=currency,
        model_dispersion_low=fair_low,
        model_dispersion_base=fair_base,
        model_dispersion_high=fair_high,
        monte_carlo_low=mc_low,
        monte_carlo_base=mc_base,
        monte_carlo_high=mc_high,
    )


def compute_symbol_valuations(
    *,
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    peer_snapshots: list[FundamentalSnapshot],
    sectors: dict[str, str | None] | None = None,
    assumptions: dict[str, float] | None = None,
    scenario: str = "base",
    integrity: IntegrityReport | None = None,
) -> tuple[dict[str, Any], list[ValuationResult]]:
    """Route a stock through all relevant fundamental valuation models."""

    merged_assumptions = {**default_assumptions_for_scenario(scenario), **(assumptions or {})}
    sector_map = sectors or {}
    current_price = _current_price(snapshot)
    snapshot_currency = _snapshot_currency(snapshot)
    assumption_currency = _assumption_currency(assumptions)
    if snapshot_currency != assumption_currency:
        results = [_unavailable(snapshot, scenario, model, current_price, "currency_mismatch") for model in VALUATION_MODEL_ORDER]
        eligibility = {
            model: {"eligible": False, "confidence": "unavailable", "reason": "currency_mismatch"}
            for model in VALUATION_MODEL_ORDER
        }
        eligibility["currency"] = {"snapshot": snapshot_currency, "assumptions": assumption_currency, "status": "mismatch"}
        ensemble = compute_valuation_ensemble(snapshot.symbol, scenario, results)
        eligibility["ensemble"] = {
            "usable_model_count": ensemble.usable_model_count,
            "excluded_model_count": ensemble.excluded_model_count,
            "confidence_score": ensemble.confidence_score,
            "model_weights": ensemble.model_weights,
            "warnings": ensemble.warnings,
            "currency": ensemble.currency,
        }
        return eligibility, results
    is_financial = _is_financial(sector_map.get(snapshot.symbol))
    eligibility = _eligible_models(snapshot, history, sector_map.get(snapshot.symbol))
    peer_stats = _peer_stats(peer_snapshots, sector_map, snapshot.symbol, int(merged_assumptions["peer_min_count"]))

    results: list[ValuationResult] = [
        _relative_multiples(snapshot, current_price, peer_stats, scenario) if eligibility["relative_multiples"]["eligible"] else _unavailable(snapshot, scenario, "relative_multiples", current_price, "model_not_eligible"),
        _reverse_dcf(snapshot, current_price, merged_assumptions, scenario) if eligibility["reverse_dcf"]["eligible"] else _unavailable(snapshot, scenario, "reverse_dcf", current_price, "model_not_eligible"),
        _fcff_dcf(snapshot, history, current_price, merged_assumptions, scenario) if eligibility["fcff_dcf"]["eligible"] else _unavailable(snapshot, scenario, "fcff_dcf", current_price, "model_not_eligible"),
        _fcfe_dcf(snapshot, history, current_price, merged_assumptions, scenario) if eligibility["fcfe_dcf"]["eligible"] else _unavailable(snapshot, scenario, "fcfe_dcf", current_price, "model_not_eligible"),
        _ddm(snapshot, history, current_price, merged_assumptions, scenario) if eligibility["ddm"]["eligible"] else _unavailable(snapshot, scenario, "ddm", current_price, "model_not_eligible"),
        _residual_income(snapshot, current_price, merged_assumptions, scenario, is_financial) if eligibility["residual_income"]["eligible"] else _unavailable(snapshot, scenario, "residual_income", current_price, "model_not_eligible"),
        _justified_multiples(snapshot, current_price, merged_assumptions, scenario, is_financial) if eligibility["justified_multiples"]["eligible"] else _unavailable(snapshot, scenario, "justified_multiples", current_price, "model_not_eligible"),
    ]
    results = _apply_integrity_report(results, integrity)
    ensemble = compute_valuation_ensemble(snapshot.symbol, scenario, results)
    for index, row in enumerate(results):
        weight = ensemble.model_weights.get(row.model)
        if weight is None and row.family == "diagnostic":
            weight = 0.0
        results[index] = ValuationResult(
            symbol=row.symbol,
            scenario=row.scenario,
            model=row.model,
            fair_value=row.fair_value,
            current_price=row.current_price,
            upside_pct=row.upside_pct,
            confidence=row.confidence,
            inputs=row.inputs,
            outputs=row.outputs,
            warnings=row.warnings,
            family=row.family,
            model_version=row.model_version,
            methodology=row.methodology,
            confidence_score=row.confidence_score,
            weight=weight,
            is_proxy=row.is_proxy,
            data_quality_score=row.data_quality_score,
            currency=row.currency,
        )
    eligibility["ensemble"] = {
        "usable_model_count": ensemble.usable_model_count,
        "excluded_model_count": ensemble.excluded_model_count,
        "confidence_score": ensemble.confidence_score,
        "model_weights": ensemble.model_weights,
        "warnings": ensemble.warnings,
        "currency": ensemble.currency,
        "model_dispersion": {
            "low": ensemble.model_dispersion_low,
            "base": ensemble.model_dispersion_base,
            "high": ensemble.model_dispersion_high,
        },
        "monte_carlo": {
            "low": ensemble.monte_carlo_low,
            "base": ensemble.monte_carlo_base,
            "high": ensemble.monte_carlo_high,
        },
    }
    if integrity is not None:
        eligibility["data_integrity"] = {
            "overall_status": integrity.overall_status,
            "confidence_haircut": integrity.confidence_haircut,
            "warnings": [_integrity_warning(integrity)] if _integrity_warning(integrity) else [],
        }
    return eligibility, results


def compute_sensitivity(
    *,
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    peer_snapshots: list[FundamentalSnapshot],
    sectors: dict[str, str | None] | None = None,
    base_assumptions: dict[str, float] | None = None,
    scenario: str = "base",
    axis_x: str = "wacc",
    axis_y: str = "terminal_growth",
    range_x: tuple[float, float] = (0.07, 0.13),
    range_y: tuple[float, float] = (0.01, 0.05),
    steps: int = 5,
    integrity: IntegrityReport | None = None,
) -> dict[str, Any]:
    allowed = {"wacc", "terminal_growth", "growth_cap", "cost_of_equity"}
    if axis_x not in allowed or axis_y not in allowed:
        raise ValueError(f"Sensitivity axes must be one of {sorted(allowed)}")
    if steps < 2 or steps > 11:
        raise ValueError("Sensitivity steps must be between 2 and 11")

    def linspace(bounds: tuple[float, float]) -> list[float]:
        start, end = bounds
        return [start + (end - start) * index / (steps - 1) for index in range(steps)]

    xs = linspace(range_x)
    ys = linspace(range_y)
    base = {**default_assumptions_for_scenario(scenario), **(base_assumptions or {})}
    matrix: list[list[float | None]] = []
    upside_matrix: list[list[float | None]] = []
    confidence_matrix: list[list[float | None]] = []
    for y_value in ys:
        row_values: list[float | None] = []
        row_upside: list[float | None] = []
        row_confidence: list[float | None] = []
        for x_value in xs:
            assumptions = {**base, axis_x: float(x_value), axis_y: float(y_value)}
            _, valuations = compute_symbol_valuations(
                snapshot=snapshot,
                history=history,
                peer_snapshots=peer_snapshots,
                sectors=sectors,
                assumptions=assumptions,
                scenario=scenario,
                integrity=integrity,
            )
            ensemble = compute_valuation_ensemble(snapshot.symbol, scenario, valuations)
            row_values.append(ensemble.fair_value_base)
            row_upside.append(ensemble.upside_pct)
            row_confidence.append(ensemble.confidence_score)
        matrix.append(row_values)
        upside_matrix.append(row_upside)
        confidence_matrix.append(row_confidence)
    return {
        "symbol": snapshot.symbol,
        "scenario": scenario,
        "axis_x": axis_x,
        "axis_y": axis_y,
        "xs": xs,
        "ys": ys,
        "matrix": matrix,
        "axis_x_meta": {"key": axis_x, "values": xs},
        "axis_y_meta": {"key": axis_y, "values": ys},
        "fair_value_base": matrix,
        "upside_pct": upside_matrix,
        "confidence_score": confidence_matrix,
    }


def compute_default_sensitivity_grids(
    *,
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    peer_snapshots: list[FundamentalSnapshot],
    sectors: dict[str, str | None] | None = None,
    base_assumptions: dict[str, float] | None = None,
    scenario: str = "base",
    integrity: IntegrityReport | None = None,
) -> dict[str, Any]:
    base = {**default_assumptions_for_scenario(scenario), **(base_assumptions or {})}
    wacc = float(base.get("wacc", DEFAULT_ASSUMPTIONS["wacc"]))
    terminal_growth = float(base.get("terminal_growth", DEFAULT_ASSUMPTIONS["terminal_growth"]))
    growth_cap = float(base.get("growth_cap", DEFAULT_ASSUMPTIONS["growth_cap"]))
    wacc_step = float(base.get("sensitivity_wacc_step", DEFAULT_ASSUMPTIONS["sensitivity_wacc_step"]))
    terminal_step = float(base.get("sensitivity_terminal_growth_step", DEFAULT_ASSUMPTIONS["sensitivity_terminal_growth_step"]))
    growth_step = float(base.get("sensitivity_growth_cap_step", DEFAULT_ASSUMPTIONS["sensitivity_growth_cap_step"]))
    offsets = (-2, -1, 0, 1, 2)

    def bounds(center: float, step: float) -> tuple[float, float]:
        return center + offsets[0] * step, center + offsets[-1] * step

    return {
        "wacc_x_terminal_growth": compute_sensitivity(
            snapshot=snapshot,
            history=history,
            peer_snapshots=peer_snapshots,
            sectors=sectors,
            base_assumptions=base,
            scenario=scenario,
            axis_x="wacc",
            axis_y="terminal_growth",
            range_x=bounds(wacc, wacc_step),
            range_y=bounds(terminal_growth, terminal_step),
            steps=5,
            integrity=integrity,
        ),
        "wacc_x_growth_cap": compute_sensitivity(
            snapshot=snapshot,
            history=history,
            peer_snapshots=peer_snapshots,
            sectors=sectors,
            base_assumptions=base,
            scenario=scenario,
            axis_x="wacc",
            axis_y="growth_cap",
            range_x=bounds(wacc, wacc_step),
            range_y=bounds(growth_cap, growth_step),
            steps=5,
            integrity=integrity,
        ),
    }
