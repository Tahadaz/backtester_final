from __future__ import annotations

import datetime as dt
import calendar
import logging
from dataclasses import dataclass, field
from math import isfinite
from statistics import mean, median
from typing import Any, Iterable, Mapping

_log = logging.getLogger(__name__)

from .cgnc_mapping import resolve_metric_name
from .domain import AnnualMetricRow, FundamentalSnapshot, IntegrityCheck, PeriodMetricRow


REVENUE_ALIASES = ("Revenue", "Chiffre_daffaires", "Clean_Chiffre_daffaires")
EBIT_ALIASES = ("EBIT", "Resultat_dexploitation")
EBITDA_ALIASES = ("EBITDA", "Excedent_brut_dexploitation")
DANDA_ALIASES = ("Depreciation_Amortization", "DandA", "Dotations_dexploitation")
CAPEX_ALIASES = ("Capex", "Capital_Expenditures")
WORKING_CAPITAL_ALIASES = ("Working_Capital",)
CURRENT_ASSET_ALIASES = ("Current_Assets", "Actif_circulant")
CURRENT_LIABILITY_ALIASES = ("Current_Liabilities", "Passif_circulant")
NET_INCOME_ALIASES = ("NetIncome", "Net_Income", "Clean_Resultat_net", "Resultat_net")
TAX_ALIASES = ("Income_Tax_Expense", "Impots_sur_les_resultats")
DEBT_ALIASES = ("Total_Debt", "Debt_Total", "Dettes_de_financement")
CASH_ALIASES = ("Cash", "Cash_and_Equivalents", "CFS_Ending_Cash", "Tresorerie_Actif")
EQUITY_ALIASES = (
    "Total_Equity",
    "Shareholders_Equity",
    "Total_Shareholders_Equity",
    "Stockholders_Equity",
    "Total_Stockholders_Equity",
    "Clean_Capitaux_propres",
    "Capitaux_propres",
    "Equity",
    "Total_Common_Equity",
    "Common_Equity",
)
TOTAL_ASSET_ALIASES = ("Total_Assets", "Total_Actif")
TOTAL_LIABILITY_ALIASES = ("Total_Liabilities",)
DIVIDEND_ALIASES = ("Dividends_Paid", "Dividendes", "Clean_Dividendes")
FREE_CASH_FLOW_ALIASES = ("Free_Cash_Flow",)
OPERATING_CF_ALIASES = ("Operating_Cash_Flow", "CF_Operating", "Flux_de_tresorerie_lies_a_lactivite")
INVESTING_CF_ALIASES = ("CF_Investing", "Flux_de_tresorerie_lies_aux_investissements")
INTEREST_ALIASES = ("Interest_Expense", "Charges_Interets", "Net_Interest_Expense", "Resultat_financier")
PNB_ALIASES = ("PNB", "Produit_Net_Bancaire", "Net_Banking_Income")
RBE_ALIASES = ("RBE", "Resultat_Brut_Exploitation", "Gross_Operating_Income")
COST_OF_RISK_ALIASES = ("Cout_du_risque", "Cost_of_Risk", "Provision_for_Loan_Losses", "Provision_Loan_Losses")
COST_OF_RISK_RATIO_ALIASES = ("Cost_of_Risk_Pct", "Cout_du_risque_to_Loans", "Cout_du_risque_to_PNB")
LOANS_ALIASES = ("Loans_Net", "Net_Loans", "Customer_Loans", "Creances_sur_la_clientele")
ROE_ALIASES = ("ROE", "Return_on_Equity")

PERIODS_PER_YEAR_BY_TYPE = {"annual": 1, "semiannual": 2, "quarterly": 4}
PERIOD_TYPE_BY_PERIODS = {value: key for key, value in PERIODS_PER_YEAR_BY_TYPE.items()}
HORIZON_PERIOD_TYPE = {"year": "annual", "semester": "semiannual", "quarter": "quarterly"}
MIN_SAME_PERIOD_OBSERVATIONS = 3


@dataclass(frozen=True)
class DriverEstimate:
    name: str
    projected_by_year: dict[int, float]
    method: str
    inputs: dict[str, Any]
    historical_series: list[dict[str, float | int]]
    anchor_value: float | None
    divergence: float | None
    warning: str | None = None
    projected_by_period: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "projected_by_year": {str(year): value for year, value in self.projected_by_year.items()},
            "method": self.method,
            "inputs": self.inputs,
            "historical_series": self.historical_series,
            "anchor_value": self.anchor_value,
            "divergence": self.divergence,
            "warning": self.warning,
            "projected_by_period": self.projected_by_period,
        }


@dataclass(frozen=True)
class Projection:
    symbol: str
    scenario: str
    start_year: int
    forecast_years: int
    as_of: dt.date | None
    statements: list[dict[str, Any]]
    drivers: dict[str, DriverEstimate]
    fcff: list[float]
    fcfe: list[float]
    dividends: list[float]
    book_values: list[float]
    periods_per_year: int = 1
    period_type: str = "annual"
    growth_decomposition: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    fallback: bool = False
    confidence_cap: str | None = None
    integrity_checks: list[IntegrityCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "scenario": self.scenario,
            "start_year": self.start_year,
            "forecast_years": self.forecast_years,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "periods_per_year": self.periods_per_year,
            "period_type": self.period_type,
            "statements": self.statements,
            "drivers": {name: estimate.to_dict() for name, estimate in self.drivers.items()},
            "fcff": self.fcff,
            "fcfe": self.fcfe,
            "dividends": self.dividends,
            "book_values": self.book_values,
            "growth_decomposition": self.growth_decomposition,
            "warnings": self.warnings,
            "fallback": self.fallback,
            "confidence_cap": self.confidence_cap,
            "integrity_checks": [check_to_dict(check) for check in self.integrity_checks],
        }


def check_to_dict(check: IntegrityCheck) -> dict[str, Any]:
    return {
        "name": check.name,
        "status": check.status,
        "delta": check.delta,
        "rel_delta": check.rel_delta,
        "inputs": check.inputs,
        "message": check.message,
    }


def build_projection(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    assumptions: Mapping[str, Any],
    scenario: str = "base",
    overrides: Mapping[str, Any] | None = None,
    *,
    period_history: list[PeriodMetricRow] | None = None,
    period_type: str = "annual",
    periods_per_year: int | None = None,
    cyclical: bool = False,
) -> Projection:
    """Build one driver-based operating projection for all intrinsic models."""

    overrides = overrides or {}
    resolved_period_type = _normalize_period_type(period_type, periods_per_year)
    resolved_periods_per_year = periods_per_year or PERIODS_PER_YEAR_BY_TYPE.get(resolved_period_type, 1)
    financial_archetype = str(assumptions.get("_financial_archetype") or "").strip().lower()
    if financial_archetype in {"bank", "insurance", "financial"}:
        return _build_financial_projection(
            snapshot,
            history,
            assumptions,
            scenario=scenario,
            overrides=overrides,
            archetype=financial_archetype,
        )
    if resolved_periods_per_year > 1:
        return _build_period_projection(
            snapshot,
            history,
            period_history or [],
            assumptions,
            scenario=scenario,
            overrides=overrides,
            period_type=resolved_period_type,
            periods_per_year=resolved_periods_per_year,
            cyclical=cyclical,
        )

    years = max(1, int(float(assumptions.get("forecast_years", 5.0))))
    terminal_growth = _float(assumptions.get("terminal_growth_firm", assumptions.get("terminal_growth")), 0.025)
    tax_rate_assumption = _float(assumptions.get("tax_rate"), 0.35)
    peer_driver_medians = _peer_driver_medians(assumptions)
    unavailable_driver_warnings: list[str] = []

    revenue_series = _series(history, REVENUE_ALIASES)
    if not revenue_series:
        revenue_snapshot = _snapshot_value(snapshot, REVENUE_ALIASES)
        if revenue_snapshot is not None:
            start_year = int(snapshot.latest_statement_year or dt.date.today().year)
            revenue_series = [(start_year, revenue_snapshot)]
    if not revenue_series:
        start_year = int(snapshot.latest_statement_year or dt.date.today().year)
        empty = Projection(
            symbol=snapshot.symbol.upper(),
            scenario=scenario,
            start_year=start_year,
            forecast_years=years,
            as_of=snapshot.as_of_date,
            statements=[],
            drivers={},
            fcff=[],
            fcfe=[],
            dividends=[],
            book_values=[],
            periods_per_year=1,
            period_type="annual",
            warnings=["missing_revenue_history"],
            fallback=True,
            confidence_cap="low",
        )
        return empty

    start_year = int(snapshot.latest_statement_year or revenue_series[-1][0])
    latest_revenue = _latest_value(revenue_series)
    revenue_growth_history = _growth_series(revenue_series)
    historical_growth_bound = _winsorized_peak_growth(revenue_growth_history)
    cagr_3y = _cagr(revenue_series, periods=3)
    last_year_growth = revenue_growth_history[-1][1] if revenue_growth_history else cagr_3y
    growth_warning = None
    if cagr_3y is None and last_year_growth is None:
        peer_growth = _peer_driver_value(peer_driver_medians, "revenue_growth")
        if peer_growth is not None:
            year1_growth = peer_growth
            growth_method = "sector peer median revenue growth because revenue history has one usable point"
            growth_warning = "revenue_growth_from_peer_median"
        else:
            year1_growth = terminal_growth
            growth_method = "unavailable because revenue history has one usable point and no peer median"
            growth_warning = "revenue_growth_unavailable_no_history_no_peer"
            unavailable_driver_warnings.append(growth_warning)
    elif cagr_3y is None:
        year1_growth = float(last_year_growth or 0.0)
        growth_method = f"last-year revenue growth {year1_growth:.2%} fades to terminal {terminal_growth:.2%}"
    elif last_year_growth is None:
        year1_growth = float(cagr_3y)
        growth_method = f"3y revenue CAGR {year1_growth:.2%} fades to terminal {terminal_growth:.2%}"
    else:
        year1_growth = 0.5 * float(cagr_3y) + 0.5 * float(last_year_growth)
        growth_method = (
            f"blend(3y revenue CAGR {cagr_3y:.2%}, last-year growth {last_year_growth:.2%}) "
            f"fades to terminal {terminal_growth:.2%}"
        )
    if historical_growth_bound is not None:
        year1_growth = min(year1_growth, historical_growth_bound)
    year1_growth = max(-0.10, year1_growth)

    # brief 54 §3 Phase 3.2: seed near-year revenue growth from consensus forward view.
    # Only fires when the forward fiscal year is immediately next (start_year+1) so we
    # never extrapolate a two-year-out estimate back onto the near-year growth path.
    _fwd_rev = _finite(assumptions.get("forward_revenue"))
    _fwd_ni = _finite(assumptions.get("forward_net_income"))
    _fwd_year_raw = assumptions.get("forward_fiscal_year")
    _fwd_near_year = int(_fwd_year_raw) if _fwd_year_raw is not None else start_year + 1
    _fwd_rev_seeded = False
    if (
        _fwd_near_year == start_year + 1
        and _fwd_rev is not None
        and _fwd_rev > 0
        and latest_revenue is not None
        and latest_revenue > 0
    ):
        _fwd_growth = (_fwd_rev / latest_revenue) - 1.0
        year1_growth = max(-0.10, _fwd_growth)
        growth_method = (
            f"forward revenue {_fwd_rev:,.0f} MAD (consensus); "
            f"seeded growth {year1_growth:.2%} fades to terminal {terminal_growth:.2%}"
        )
        growth_warning = None
        _fwd_rev_seeded = True

    growth_path = _fade_path(year1_growth, terminal_growth, years)
    growth_path = _apply_override_series("revenue_growth", growth_path, start_year, overrides)
    growth_anchor = cagr_3y if cagr_3y is not None else last_year_growth
    growth_divergence, divergence_warning = _divergence(growth_path[0], growth_anchor, name="revenue_growth")
    growth_warning = growth_warning or divergence_warning

    margin_series = _ratio_series(history, EBIT_ALIASES, REVENUE_ALIASES)
    ebit_peer = _peer_driver_value(peer_driver_medians, "ebit_margin")
    ebit_anchor, ebit_margin_unavailable = _trailing_or_peer(
        margin_series,
        peer_value=ebit_peer,
        unavailable_warning="ebit_margin_unavailable_no_history_no_peer",
    )
    if ebit_margin_unavailable:
        unavailable_driver_warnings.append(ebit_margin_unavailable)
    latest_margin = margin_series[-1][1] if margin_series else ebit_anchor
    year1_margin = latest_margin
    midcycle_margin = None
    recovery_or_fade: str | None = None
    if cyclical and len(margin_series) >= 3:
        # Through-cycle mean reversion (brief 44 RC-A): fade FROM the latest realized
        # margin TO the mid-cycle median, in whichever direction is needed. A trough
        # year recovers UP to mid-cycle; an elevated year fades DOWN. Do NOT pin the
        # start to the median — that clips a trough name to a trough-dragged flat line
        # and is the dominant source of the engine's one-directional downward bias.
        midcycle_margin = float(median([value for _year, value in margin_series]))
        ebit_anchor = midcycle_margin
        year1_margin = latest_margin
        recovery_or_fade = "recovery" if latest_margin < midcycle_margin else "fade"

    # brief 54 §3 Phase 3.2: seed near-year EBIT margin from consensus forward NI/Rev.
    # Gross-up NI margin → EBIT margin using the tax-rate assumption (effective tax is
    # computed later; tax_rate_assumption is the best available rate at this point).
    # Caps at 60 % to avoid blowups from near-zero revenue years.
    _fwd_ebit_margin: float | None = None
    if _fwd_rev_seeded and _fwd_ni is not None and _fwd_ni > 0:
        _implied_ni_margin = _fwd_ni / _fwd_rev  # type: ignore[operator]
        _tax_denom = max(0.01, 1.0 - tax_rate_assumption)
        _fwd_ebit_margin = max(0.0, min(0.60, _implied_ni_margin / _tax_denom))
        year1_margin = _fwd_ebit_margin

    margin_path = _fade_path(year1_margin, ebit_anchor, years)
    margin_path = _apply_override_series("ebit_margin", margin_path, start_year, overrides)
    margin_divergence, margin_warning = _divergence(margin_path[0], ebit_anchor, name="ebit_margin", absolute_band=0.05)
    if not margin_series and ebit_peer is not None:
        margin_warning = "ebit_margin_from_peer_median"
    if cyclical:
        margin_warning = "midcycle_ebit_margin_applied" if midcycle_margin is not None else "midcycle_ebit_margin_unavailable_insufficient_history"
    if ebit_margin_unavailable:
        margin_warning = ebit_margin_unavailable

    effective_tax = _effective_tax_rate(history)
    tax_rate = effective_tax if effective_tax is not None else tax_rate_assumption
    tax_path = _apply_override_series("tax_rate", [tax_rate] * years, start_year, overrides)

    dand_a_series = _ratio_series(history, DANDA_ALIASES, REVENUE_ALIASES)
    dand_a_peer = _peer_driver_value(peer_driver_medians, "depreciation_amortization_pct")
    dand_a_pct, dand_a_unavailable = _trailing_or_peer(
        dand_a_series,
        peer_value=dand_a_peer,
        unavailable_warning="d_and_a_pct_unavailable_no_history_no_peer",
    )
    if dand_a_unavailable:
        unavailable_driver_warnings.append(dand_a_unavailable)
    dand_a_warning = None
    if not dand_a_series and dand_a_peer is not None:
        dand_a_warning = "d_and_a_pct_from_peer_median"
    if dand_a_unavailable:
        dand_a_warning = dand_a_unavailable
    dand_a_path = _apply_override_series("depreciation_amortization_pct", [dand_a_pct] * years, start_year, overrides)

    capex_series = _ratio_series(history, CAPEX_ALIASES, REVENUE_ALIASES, absolute_numerator=True)
    capex_peer = _peer_driver_value(peer_driver_medians, "capex_pct")
    capex_pct, capex_unavailable = _trailing_or_peer(
        capex_series,
        peer_value=capex_peer,
        unavailable_warning="capex_pct_unavailable_no_history_no_peer",
    )
    if capex_unavailable:
        unavailable_driver_warnings.append(capex_unavailable)
    midcycle_capex_pct = None
    if cyclical and len(capex_series) >= 3:
        midcycle_capex_pct = float(median([value for _year, value in capex_series]))
    maintenance_capex_norm = (
        midcycle_capex_pct
        if midcycle_capex_pct is not None
        else _float(assumptions.get("maintenance_capex_pct"), capex_pct)
    )
    if cyclical:
        # Mid-cycle maintenance capex = median(capex%) over the cycle, or the D&A%
        # maintenance proxy when there's no capex history. Do NOT take
        # max(D&A%, capex%) for cyclicals — that inflates maintenance capex and
        # double-penalizes FCFF on top of the margin normalization (brief 44 RC-A).
        maintenance_capex_pct = (
            midcycle_capex_pct if midcycle_capex_pct is not None else dand_a_pct
        )
    else:
        maintenance_capex_pct = max(dand_a_pct, maintenance_capex_norm)
    capex_warning = None
    if not capex_series and capex_peer is not None:
        capex_warning = "capex_pct_from_peer_median"
    if cyclical:
        capex_warning = (
            "midcycle_maintenance_capex_applied"
            if midcycle_capex_pct is not None
            else "midcycle_maintenance_capex_unavailable_registry_assumption"
        )
    if capex_unavailable:
        capex_warning = capex_unavailable
    capex_path = _fade_path(capex_pct, maintenance_capex_pct, years)
    capex_path = _apply_override_series("capex_pct", capex_path, start_year, overrides)

    wc_series = _working_capital_ratio_series(history)
    wc_peer = _peer_driver_value(peer_driver_medians, "working_capital_pct")
    wc_pct, wc_unavailable = _trailing_or_peer(
        wc_series,
        peer_value=wc_peer,
        unavailable_warning="working_capital_pct_unavailable_no_history_no_peer",
    )
    if wc_unavailable:
        unavailable_driver_warnings.append(wc_unavailable)
    wc_warning = None
    if not wc_series and wc_peer is not None:
        wc_warning = "working_capital_pct_from_peer_median"
    if wc_unavailable:
        wc_warning = wc_unavailable
    wc_path = _apply_override_series("working_capital_pct", [wc_pct] * years, start_year, overrides)

    payout_series = _payout_ratio_series(history)
    payout_peer = _peer_driver_value(peer_driver_medians, "payout_ratio")
    payout_ratio, payout_unavailable = _trailing_or_peer(
        payout_series,
        peer_value=payout_peer,
        unavailable_warning="payout_ratio_unavailable_no_history_no_peer",
    )
    if payout_unavailable:
        unavailable_driver_warnings.append(payout_unavailable)
    payout_warning = None
    if not payout_series and payout_peer is not None:
        payout_warning = "payout_ratio_from_peer_median"
    if payout_unavailable:
        payout_warning = payout_unavailable
    if isfinite(float(payout_ratio)):
        payout_ratio = _clamp(payout_ratio, 0.0, 0.95)
    payout_path = _apply_override_series("payout_ratio", [payout_ratio] * years, start_year, overrides)

    cash_flow_missing = not (
        _series(history, FREE_CASH_FLOW_ALIASES)
        or _series(history, OPERATING_CF_ALIASES)
        or _series(history, INVESTING_CF_ALIASES)
    )
    warnings = [warning for warning in (growth_warning, margin_warning, capex_warning, wc_warning, dand_a_warning, payout_warning) if warning]
    if cash_flow_missing:
        warnings.append("cash_flow_statement_missing_driver_fallback")
    if unavailable_driver_warnings:
        warnings.append("projection_driver_unavailable")

    latest_equity = _latest_or_snapshot(history, snapshot, EQUITY_ALIASES)
    if latest_equity is None:
        latest_equity = _book_equity_proxy(snapshot) or 0.0
        warnings.append("equity_proxy_or_zero_for_projection")
    latest_debt = _latest_or_snapshot(history, snapshot, DEBT_ALIASES) or 0.0
    latest_cash = _latest_or_snapshot(history, snapshot, CASH_ALIASES) or 0.0
    working_capital = _latest_working_capital(history) or 0.0
    latest_assets = _latest_or_snapshot(history, snapshot, TOTAL_ASSET_ALIASES)
    latest_liabilities = _latest_or_snapshot(history, snapshot, TOTAL_LIABILITY_ALIASES)
    if latest_liabilities is not None:
        other_liabilities = max(0.0, latest_liabilities - latest_debt)
    elif latest_assets is not None:
        other_liabilities = max(0.0, latest_assets - latest_debt - latest_equity)
    else:
        other_liabilities = 0.0
    if latest_assets is None:
        latest_assets = latest_debt + other_liabilities + latest_equity
        warnings.append("total_assets_missing_non_cash_asset_proxy")
    non_cash_assets = max(0.0, latest_assets - latest_cash)
    interest = abs(_latest_or_snapshot(history, snapshot, INTEREST_ALIASES) or 0.0)
    if interest > latest_revenue:
        interest = 0.0

    statements: list[dict[str, Any]] = []
    fcff: list[float] = []
    fcfe: list[float] = []
    dividends: list[float] = []
    book_values: list[float] = []
    previous_revenue = latest_revenue
    previous_equity = latest_equity
    previous_cash = latest_cash
    for index in range(years):
        fiscal_year = start_year + index + 1
        revenue = previous_revenue * (1.0 + growth_path[index])
        delta_revenue = revenue - previous_revenue
        ebit = revenue * margin_path[index]
        dand_a = revenue * max(0.0, dand_a_path[index])
        ebitda = ebit + dand_a
        tax = _clamp(tax_path[index], 0.0, 0.60)
        nopat = ebit * (1.0 - tax)
        capex = revenue * max(0.0, capex_path[index])
        delta_wc = delta_revenue * wc_path[index]
        working_capital += delta_wc
        reinvestment = capex + delta_wc - dand_a
        fcff_value = nopat - reinvestment
        after_tax_interest = interest * (1.0 - tax)
        fcfe_value = fcff_value - after_tax_interest
        net_income = (ebit - interest) * (1.0 - tax)
        dividend = max(0.0, net_income) * _clamp(payout_path[index], 0.0, 0.95)
        beginning_equity = previous_equity
        ending_equity = previous_equity + net_income - dividend
        operating_cf = net_income + dand_a - delta_wc
        investing_cf = -capex
        financing_cf = -dividend
        ending_cash = previous_cash + operating_cf + investing_cf + financing_cf
        non_cash_assets = max(0.0, non_cash_assets + reinvestment)
        total_liabilities_before_plug = latest_debt + other_liabilities
        total_assets_before_plug = ending_cash + non_cash_assets
        completed_bs = _complete_projected_balance_sheet(
            total_assets_before_plug=total_assets_before_plug,
            total_liabilities_before_plug=total_liabilities_before_plug,
            total_equity=ending_equity,
        )
        gross_profit = max(ebitda, ebit, net_income, 0.0)
        statement = {
            "fiscal_year": fiscal_year,
            "periods_per_year": 1,
            "period_type": "annual",
            "period_index": 0,
            "period_label": "FY",
            "period_end_date": _annual_period_end_date(snapshot.as_of_date, fiscal_year),
            "revenue": revenue,
            "revenue_growth": growth_path[index],
            "gross_profit": gross_profit,
            "ebitda": ebitda,
            "ebit": ebit,
            "ebit_margin": margin_path[index],
            "tax_rate": tax,
            "nopat": nopat,
            "depreciation_amortization": dand_a,
            "capex": capex,
            "delta_working_capital": delta_wc,
            "working_capital": working_capital,
            "reinvestment": reinvestment,
            "fcff": fcff_value,
            "interest_expense": interest,
            "fcfe": fcfe_value,
            "net_income": net_income,
            "dividends": dividend,
            "beginning_equity": beginning_equity,
            "beginning_cash": previous_cash,
            "operating_cash_flow": operating_cf,
            "investing_cash_flow": investing_cf,
            "financing_cash_flow": financing_cf,
            "ending_cash": ending_cash,
            "cash": ending_cash,
            "non_cash_assets": non_cash_assets,
            "debt": latest_debt,
            "total_equity": ending_equity,
            **completed_bs,
        }
        statements.append(statement)
        fcff.append(fcff_value)
        fcfe.append(fcfe_value)
        dividends.append(dividend)
        book_values.append(ending_equity)
        previous_revenue = revenue
        previous_equity = ending_equity
        previous_cash = ending_cash

    fiscal_years = [start_year + index + 1 for index in range(years)]
    drivers = {
        "revenue_growth": DriverEstimate(
            name="revenue_growth",
            projected_by_year=_year_map(fiscal_years, growth_path),
            method=growth_method,
            inputs={
                "cagr_3y": cagr_3y,
                "last_year_growth": last_year_growth,
                "terminal_growth": terminal_growth,
                "historical_growth_upper_bound": historical_growth_bound,
                "growth_bound_method": "winsorized_peak_yoy_90th_percentile" if historical_growth_bound is not None else "none_one_point_history",
                "blend_weight_cagr": 0.5,
                "blend_weight_last_year": 0.5,
                "peer_median": _peer_driver_value(peer_driver_medians, "revenue_growth"),
            },
            historical_series=_series_to_dict(revenue_growth_history[-7:]),
            anchor_value=growth_anchor,
            divergence=growth_divergence,
            warning=growth_warning,
        ),
        "ebit_margin": DriverEstimate(
            name="ebit_margin",
            projected_by_year=_year_map(fiscal_years, margin_path),
            method=(
                f"forward NI/Rev gross-up → seeded EBIT margin {_fwd_ebit_margin:.2%}; "
                f"fades to {'mid-cycle median' if midcycle_margin is not None else 'trailing average'} {ebit_anchor:.2%}"
                if _fwd_ebit_margin is not None
                else (
                    f"latest EBIT margin {latest_margin:.2%} {recovery_or_fade or 'reverts'}s "
                    f"to mid-cycle median {ebit_anchor:.2%} over the horizon"
                    if midcycle_margin is not None
                    else f"latest realized EBIT margin {latest_margin:.2%} fades to trailing-3y average {ebit_anchor:.2%}"
                )
            ),
            inputs={
                "trailing_3y_average": ebit_anchor,
                "latest_margin": latest_margin,
                "forward_seeded_ebit_margin": _fwd_ebit_margin,
                "peer_median": ebit_peer,
                "cyclical": cyclical,
                "midcycle_margin": midcycle_margin,
                "midcycle_observation_count": len(margin_series),
                "normalized_earnings_basis": (
                    {
                        "window": {
                            "start": margin_series[0][0],
                            "end": margin_series[-1][0],
                            "count": len(margin_series),
                        },
                        "median_margin": midcycle_margin,
                        "latest_margin": latest_margin,
                        "trailing_vs_midcycle_pct": (
                            latest_margin / midcycle_margin - 1.0
                            if midcycle_margin not in (0.0, None)
                            else None
                        ),
                        "recovery_or_fade": recovery_or_fade,
                    }
                    if midcycle_margin is not None
                    else None
                ),
            },
            historical_series=_series_to_dict(margin_series[-7:]),
            anchor_value=ebit_anchor,
            divergence=margin_divergence,
            warning=margin_warning,
        ),
        "tax_rate": DriverEstimate(
            name="tax_rate",
            projected_by_year=_year_map(fiscal_years, tax_path),
            method="effective tax rate when cleanly derivable, otherwise registry tax_rate",
            inputs={"assumption_tax_rate": tax_rate_assumption, "effective_tax_rate": effective_tax},
            historical_series=_series_to_dict(_tax_rate_series(history)[-7:]),
            anchor_value=tax_rate,
            divergence=0.0,
        ),
        "capex_pct": DriverEstimate(
            name="capex_pct",
            projected_by_year=_year_map(fiscal_years, capex_path),
            method=(
                "trailing absolute Capex / Revenue fades to maintenance capex "
                "(mid-cycle median capex / Revenue for cyclicals, else "
                "max(D&A / Revenue, structural maintenance norm))"
            ),
            inputs={
                "current_capex_pct": capex_pct,
                "maintenance_capex_pct": maintenance_capex_pct,
                "d_and_a_pct": dand_a_pct,
                "structural_maintenance_capex_norm": _float(assumptions.get("maintenance_capex_pct"), capex_pct),
                "midcycle_maintenance_capex_pct": midcycle_capex_pct,
                "default_used": not bool(capex_series),
                "peer_median": capex_peer,
                "cyclical": cyclical,
            },
            historical_series=_series_to_dict(capex_series[-7:]),
            anchor_value=capex_pct,
            divergence=abs(capex_path[0] - maintenance_capex_pct),
            warning=capex_warning,
        ),
        "working_capital_pct": DriverEstimate(
            name="working_capital_pct",
            projected_by_year=_year_map(fiscal_years, wc_path),
            method="trailing working capital / revenue applied to incremental sales",
            inputs={"trailing_3y_average": wc_pct, "default_used": not bool(wc_series), "peer_median": wc_peer},
            historical_series=_series_to_dict(wc_series[-7:]),
            anchor_value=wc_pct,
            divergence=0.0,
            warning=wc_warning,
        ),
        "depreciation_amortization_pct": DriverEstimate(
            name="depreciation_amortization_pct",
            projected_by_year=_year_map(fiscal_years, dand_a_path),
            method="trailing-3y D&A / Revenue average",
            inputs={"trailing_3y_average": dand_a_pct, "default_used": not bool(dand_a_series), "peer_median": dand_a_peer},
            historical_series=_series_to_dict(dand_a_series[-7:]),
            anchor_value=dand_a_pct,
            divergence=0.0,
            warning=dand_a_warning,
        ),
        "payout_ratio": DriverEstimate(
            name="payout_ratio",
            projected_by_year=_year_map(fiscal_years, payout_path),
            method="trailing dividends / net income average, capped at 95%",
            inputs={"trailing_3y_average": payout_ratio, "peer_median": payout_peer},
            historical_series=_series_to_dict(payout_series[-7:]),
            anchor_value=payout_ratio,
            divergence=0.0,
        ),
        "fcff": DriverEstimate(
            name="fcff",
            projected_by_year=_year_map(fiscal_years, fcff),
            method="Revenue -> EBIT -> NOPAT - (Capex + delta WC - D&A)",
            inputs={"cash_flow_statement_missing": cash_flow_missing},
            historical_series=_series_to_dict(_series(history, FREE_CASH_FLOW_ALIASES)[-7:]),
            anchor_value=_latest_or_none(_series(history, FREE_CASH_FLOW_ALIASES)),
            divergence=None,
            warning="direct_driver_fcff_fallback" if cash_flow_missing else None,
        ),
    }
    growth_decomposition = {
        "revenue_growth": _series_to_dict(revenue_growth_history[-7:]),
        "ebit_growth": _series_to_dict(_growth_series(_series(history, EBIT_ALIASES))[-7:]),
        "net_income_growth": _series_to_dict(_growth_series(_series(history, NET_INCOME_ALIASES))[-7:]),
        "fcf_growth": _series_to_dict(_growth_series(_series(history, FREE_CASH_FLOW_ALIASES))[-7:]),
        "projected_revenue_growth": _series_to_dict(list(zip(fiscal_years, growth_path))),
        "terminal_growth": terminal_growth,
        "method": growth_method,
        "cyclical": cyclical,
        "midcycle_ebit_margin": midcycle_margin,
    }
    checks = projection_integrity_checks(statements, starting_equity=latest_equity)
    return Projection(
        symbol=snapshot.symbol.upper(),
        scenario=scenario,
        start_year=start_year,
        forecast_years=years,
        as_of=snapshot.as_of_date,
        statements=statements,
        drivers=drivers,
        fcff=fcff,
        fcfe=fcfe,
        dividends=dividends,
        book_values=book_values,
        periods_per_year=1,
        period_type="annual",
        growth_decomposition=growth_decomposition,
        warnings=warnings,
        fallback=bool(cash_flow_missing or unavailable_driver_warnings),
        confidence_cap="unavailable" if unavailable_driver_warnings else "low" if cash_flow_missing else None,
        integrity_checks=checks,
    )


def _empty_projection(
    snapshot: FundamentalSnapshot,
    *,
    scenario: str,
    start_year: int,
    years: int,
    warnings: list[str],
) -> Projection:
    return Projection(
        symbol=snapshot.symbol.upper(),
        scenario=scenario,
        start_year=start_year,
        forecast_years=years,
        as_of=snapshot.as_of_date,
        statements=[],
        drivers={},
        fcff=[],
        fcfe=[],
        dividends=[],
        book_values=[],
        periods_per_year=1,
        period_type="annual",
        warnings=warnings,
        fallback=True,
        confidence_cap="unavailable",
    )


def _build_financial_projection(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    assumptions: Mapping[str, Any],
    *,
    scenario: str,
    overrides: Mapping[str, Any],
    archetype: str,
) -> Projection:
    if archetype == "bank":
        return _build_bank_projection(snapshot, history, assumptions, scenario=scenario, overrides=overrides)
    return _build_roe_financial_projection(
        snapshot,
        history,
        assumptions,
        scenario=scenario,
        overrides=overrides,
        archetype=archetype,
    )


def _financial_start_year(snapshot: FundamentalSnapshot, series: list[tuple[int, float]]) -> int:
    return int(snapshot.latest_statement_year or (series[-1][0] if series else dt.date.today().year))


def _ratio_input(value: Any) -> float | None:
    raw = _finite(value)
    if raw is None:
        return None
    return raw / 100.0 if abs(raw) > 2.0 else raw


def _ratio_metric_series(history: list[AnnualMetricRow], aliases: Iterable[str]) -> list[tuple[int, float]]:
    rows = _series(history, aliases)
    out: list[tuple[int, float]] = []
    for year, value in rows:
        ratio = _ratio_input(value)
        if ratio is not None:
            out.append((year, ratio))
    return out


def _bank_cost_of_risk_series(history: list[AnnualMetricRow]) -> tuple[list[tuple[int, float]], str | None]:
    direct = _ratio_metric_series(history, COST_OF_RISK_RATIO_ALIASES)
    if direct:
        return [(year, abs(value)) for year, value in direct], "direct_ratio"
    cost = dict(_series(history, COST_OF_RISK_ALIASES))
    loans = dict(_series(history, LOANS_ALIASES))
    pnb = dict(_series(history, PNB_ALIASES))
    out: list[tuple[int, float]] = []
    basis = None
    for year in sorted(cost):
        denominator = loans.get(year)
        if denominator is not None and denominator > 0:
            basis = "loans_net"
            out.append((year, abs(cost[year]) / denominator))
            continue
        denominator = pnb.get(year)
        if denominator is not None and denominator > 0:
            basis = "pnb"
            out.append((year, abs(cost[year]) / denominator))
    return out, basis


def _financial_growth_path(
    series: list[tuple[int, float]],
    *,
    years: int,
    start_year: int,
    terminal_growth: float,
    peer_driver_medians: Mapping[str, Any],
    peer_driver: str,
    driver_name: str,
    overrides: Mapping[str, Any],
) -> tuple[list[float], str, list[tuple[int, float]], float | None, float | None, float | None, str | None]:
    growth_history = _growth_series(series)
    historical_growth_bound = _winsorized_peak_growth(growth_history)
    cagr_3y = _cagr(series, periods=3)
    last_year_growth = growth_history[-1][1] if growth_history else cagr_3y
    warning = None
    if cagr_3y is None and last_year_growth is None:
        peer_growth = _peer_driver_value(peer_driver_medians, peer_driver)
        if peer_growth is None:
            return [], f"{driver_name}_growth_unavailable_no_history_no_peer", growth_history, None, None, historical_growth_bound, f"{driver_name}_growth_unavailable_no_history_no_peer"
        year1_growth = peer_growth
        method = f"sector peer median {driver_name} growth because history has one usable point"
        warning = f"{driver_name}_growth_from_peer_median"
    elif cagr_3y is None:
        year1_growth = float(last_year_growth or 0.0)
        method = f"last-year {driver_name} growth {year1_growth:.2%} fades to terminal {terminal_growth:.2%}"
    elif last_year_growth is None:
        year1_growth = float(cagr_3y)
        method = f"3y {driver_name} CAGR {year1_growth:.2%} fades to terminal {terminal_growth:.2%}"
    else:
        year1_growth = 0.5 * float(cagr_3y) + 0.5 * float(last_year_growth)
        method = (
            f"blend(3y {driver_name} CAGR {cagr_3y:.2%}, last-year growth {last_year_growth:.2%}) "
            f"fades to terminal {terminal_growth:.2%}"
        )
    if historical_growth_bound is not None:
        year1_growth = min(year1_growth, historical_growth_bound)
    year1_growth = max(-0.10, year1_growth)
    path = _fade_path(year1_growth, terminal_growth, years)
    return (
        _apply_override_series(f"{driver_name}_growth", path, start_year, overrides),
        method,
        growth_history,
        cagr_3y,
        last_year_growth,
        historical_growth_bound,
        warning,
    )


def _financial_payout_ratio(
    history: list[AnnualMetricRow],
    peer_driver_medians: Mapping[str, Any],
) -> tuple[float | None, list[tuple[int, float]], str | None]:
    payout_series = _payout_ratio_series(history)
    payout_peer = _peer_driver_value(peer_driver_medians, "payout_ratio")
    payout_ratio, payout_unavailable = _trailing_or_peer(
        payout_series,
        peer_value=payout_peer,
        unavailable_warning="payout_ratio_unavailable_no_history_no_peer",
    )
    if payout_unavailable:
        return None, payout_series, payout_unavailable
    return _clamp(payout_ratio, 0.0, 0.95), payout_series, "payout_ratio_from_peer_median" if not payout_series and payout_peer is not None else None


def _financial_equity_anchor(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
) -> tuple[float | None, str | None]:
    equity = _latest_or_snapshot(history, snapshot, EQUITY_ALIASES)
    if equity is not None and equity > 0:
        return equity, None
    proxy = _book_equity_proxy(snapshot)
    if proxy is not None and proxy > 0:
        return proxy, "book_equity_from_price_to_book_proxy"
    return None, "missing_financial_book_equity"


def _build_bank_projection(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    assumptions: Mapping[str, Any],
    *,
    scenario: str,
    overrides: Mapping[str, Any],
) -> Projection:
    years = max(1, int(float(assumptions.get("forecast_years", 5.0))))
    terminal_growth = _float(assumptions.get("terminal_growth_equity", assumptions.get("terminal_growth")), 0.025)
    tax_rate_assumption = _float(assumptions.get("tax_rate"), 0.35)
    peer_driver_medians = _peer_driver_medians(assumptions)

    pnb_series = _series(history, PNB_ALIASES)
    if not pnb_series:
        pnb_snapshot = _snapshot_value(snapshot, PNB_ALIASES)
        if pnb_snapshot is not None:
            pnb_series = [(int(snapshot.latest_statement_year or dt.date.today().year), pnb_snapshot)]
    start_year = _financial_start_year(snapshot, pnb_series)
    if not pnb_series:
        return _empty_projection(
            snapshot,
            scenario=scenario,
            start_year=start_year,
            years=years,
            warnings=["bank_pnb_unavailable_no_history_no_peer"],
        )

    growth_path, growth_method, pnb_growth_history, cagr_3y, last_year_growth, growth_bound, growth_warning = _financial_growth_path(
        pnb_series,
        years=years,
        start_year=start_year,
        terminal_growth=terminal_growth,
        peer_driver_medians=peer_driver_medians,
        peer_driver="bank_pnb_growth",
        driver_name="pnb",
        overrides=overrides,
    )
    if not growth_path:
        return _empty_projection(
            snapshot,
            scenario=scenario,
            start_year=start_year,
            years=years,
            warnings=[growth_warning or "pnb_growth_unavailable_no_history_no_peer"],
        )

    rbe_margin_series = _ratio_metric_series(history, ("Marge_RBE", "RBE_Margin")) or _ratio_series(history, RBE_ALIASES, PNB_ALIASES)
    rbe_peer = _peer_driver_value(peer_driver_medians, "bank_rbe_margin")
    rbe_margin, rbe_unavailable = _trailing_or_peer(
        rbe_margin_series,
        peer_value=rbe_peer,
        unavailable_warning="bank_rbe_margin_unavailable_no_history_no_peer",
    )
    if rbe_unavailable:
        return _empty_projection(snapshot, scenario=scenario, start_year=start_year, years=years, warnings=[rbe_unavailable])
    rbe_margin = _clamp(rbe_margin, -1.0, 1.0)

    cost_of_risk_series, cost_of_risk_basis = _bank_cost_of_risk_series(history)
    cost_peer = _peer_driver_value(peer_driver_medians, "bank_cost_of_risk_pct")
    cost_of_risk_pct, cost_unavailable = _trailing_or_peer(
        cost_of_risk_series,
        peer_value=cost_peer,
        unavailable_warning="bank_cost_of_risk_unavailable_no_history_no_peer",
    )
    if cost_unavailable:
        return _empty_projection(snapshot, scenario=scenario, start_year=start_year, years=years, warnings=[cost_unavailable])
    cost_of_risk_pct = _clamp(abs(cost_of_risk_pct), 0.0, 1.0)

    payout_ratio, payout_series, payout_warning = _financial_payout_ratio(history, peer_driver_medians)
    if payout_ratio is None:
        return _empty_projection(snapshot, scenario=scenario, start_year=start_year, years=years, warnings=[payout_warning or "payout_ratio_unavailable_no_history_no_peer"])

    latest_equity, equity_warning = _financial_equity_anchor(snapshot, history)
    if latest_equity is None:
        return _empty_projection(snapshot, scenario=scenario, start_year=start_year, years=years, warnings=[equity_warning or "missing_financial_book_equity"])
    latest_pnb = _latest_value(pnb_series)
    latest_loans = _latest_or_snapshot(history, snapshot, LOANS_ALIASES)
    tax_rate = _effective_tax_rate(history)
    tax_warning = None
    if tax_rate is None:
        tax_rate = tax_rate_assumption
        tax_warning = "tax_rate_from_registry_assumption"
    tax_path = _apply_override_series("tax_rate", [tax_rate] * years, start_year, overrides)
    rbe_path = _apply_override_series("bank_rbe_margin", [rbe_margin] * years, start_year, overrides)
    cost_path = _apply_override_series("bank_cost_of_risk_pct", [cost_of_risk_pct] * years, start_year, overrides)
    payout_path = _apply_override_series("payout_ratio", [payout_ratio] * years, start_year, overrides)

    warnings = [
        warning
        for warning in (
            growth_warning,
            "bank_rbe_margin_from_peer_median" if not rbe_margin_series and rbe_peer is not None else None,
            "bank_cost_of_risk_from_peer_median" if not cost_of_risk_series and cost_peer is not None else None,
            payout_warning,
            equity_warning,
            tax_warning,
        )
        if warning
    ]
    if latest_loans is None or latest_loans <= 0:
        warnings.append("bank_cost_of_risk_uses_pnb_denominator")

    statements: list[dict[str, Any]] = []
    dividends: list[float] = []
    book_values: list[float] = []
    previous_pnb = latest_pnb
    previous_equity = latest_equity
    previous_loans = latest_loans if latest_loans is not None and latest_loans > 0 else None
    for index in range(years):
        fiscal_year = start_year + index + 1
        pnb = previous_pnb * (1.0 + growth_path[index])
        loans = previous_loans * (1.0 + growth_path[index]) if previous_loans is not None else None
        rbe = pnb * rbe_path[index]
        cost_base = loans if loans is not None and loans > 0 else pnb
        cost_of_risk = abs(cost_base * cost_path[index])
        pre_tax_income = rbe - cost_of_risk
        tax = _clamp(tax_path[index], 0.0, 0.60)
        net_income = pre_tax_income * (1.0 - tax)
        dividend = max(0.0, net_income) * _clamp(payout_path[index], 0.0, 0.95)
        beginning_equity = previous_equity
        ending_equity = beginning_equity + net_income - dividend
        statement = {
            "fiscal_year": fiscal_year,
            "periods_per_year": 1,
            "period_type": "annual",
            "period_index": 0,
            "period_label": "FY",
            "period_end_date": _annual_period_end_date(snapshot.as_of_date, fiscal_year),
            "pnb": pnb,
            "pnb_growth": growth_path[index],
            "rbe": rbe,
            "bank_rbe_margin": rbe_path[index],
            "cost_of_risk": cost_of_risk,
            "bank_cost_of_risk_pct": cost_path[index],
            "cost_of_risk_basis": "loans_net" if loans is not None and loans > 0 else "pnb",
            "loans_net": loans,
            "pre_tax_income": pre_tax_income,
            "tax_rate": tax,
            "net_income": net_income,
            "dividends": dividend,
            "beginning_equity": beginning_equity,
            "total_equity": ending_equity,
            "book_equity": ending_equity,
            "roe": net_income / beginning_equity if beginning_equity else None,
        }
        statements.append(statement)
        dividends.append(dividend)
        book_values.append(ending_equity)
        previous_pnb = pnb
        previous_equity = ending_equity
        previous_loans = loans

    fiscal_years = [start_year + index + 1 for index in range(years)]
    drivers = {
        "pnb_growth": DriverEstimate(
            name="pnb_growth",
            projected_by_year=_year_map(fiscal_years, growth_path),
            method=growth_method,
            inputs={
                "cagr_3y": cagr_3y,
                "last_year_growth": last_year_growth,
                "terminal_growth": terminal_growth,
                "historical_growth_upper_bound": growth_bound,
                "peer_median": _peer_driver_value(peer_driver_medians, "bank_pnb_growth"),
            },
            historical_series=_series_to_dict(pnb_growth_history[-7:]),
            anchor_value=cagr_3y if cagr_3y is not None else last_year_growth,
            divergence=None,
            warning=growth_warning,
        ),
        "bank_rbe_margin": DriverEstimate(
            name="bank_rbe_margin",
            projected_by_year=_year_map(fiscal_years, rbe_path),
            method="observed trailing RBE / PNB margin, with peer median fallback only when available",
            inputs={"trailing_3y_average": rbe_margin, "peer_median": rbe_peer},
            historical_series=_series_to_dict(rbe_margin_series[-7:]),
            anchor_value=rbe_margin,
            divergence=0.0,
            warning="bank_rbe_margin_from_peer_median" if not rbe_margin_series and rbe_peer is not None else None,
        ),
        "bank_cost_of_risk_pct": DriverEstimate(
            name="bank_cost_of_risk_pct",
            projected_by_year=_year_map(fiscal_years, cost_path),
            method="observed cost of risk divided by loans, or PNB when loans are unavailable",
            inputs={"trailing_3y_average": cost_of_risk_pct, "peer_median": cost_peer, "basis": cost_of_risk_basis},
            historical_series=_series_to_dict(cost_of_risk_series[-7:]),
            anchor_value=cost_of_risk_pct,
            divergence=0.0,
            warning="bank_cost_of_risk_from_peer_median" if not cost_of_risk_series and cost_peer is not None else None,
        ),
        "tax_rate": DriverEstimate(
            name="tax_rate",
            projected_by_year=_year_map(fiscal_years, tax_path),
            method="effective tax rate when cleanly derivable, otherwise registry tax_rate",
            inputs={"assumption_tax_rate": tax_rate_assumption, "effective_tax_rate": _effective_tax_rate(history)},
            historical_series=_series_to_dict(_tax_rate_series(history)[-7:]),
            anchor_value=tax_rate,
            divergence=0.0,
            warning=tax_warning,
        ),
        "payout_ratio": DriverEstimate(
            name="payout_ratio",
            projected_by_year=_year_map(fiscal_years, payout_path),
            method="observed dividends / net income, capped at 95%; peer median only when available",
            inputs={"trailing_3y_average": payout_ratio, "peer_median": _peer_driver_value(peer_driver_medians, "payout_ratio")},
            historical_series=_series_to_dict(payout_series[-7:]),
            anchor_value=payout_ratio,
            divergence=0.0,
            warning=payout_warning,
        ),
    }
    return Projection(
        symbol=snapshot.symbol.upper(),
        scenario=scenario,
        start_year=start_year,
        forecast_years=years,
        as_of=snapshot.as_of_date,
        statements=statements,
        drivers=drivers,
        fcff=[],
        fcfe=[],
        dividends=dividends,
        book_values=book_values,
        periods_per_year=1,
        period_type="annual",
        growth_decomposition={
            "pnb_growth": _series_to_dict(pnb_growth_history[-7:]),
            "projected_pnb_growth": _series_to_dict(list(zip(fiscal_years, growth_path))),
            "terminal_growth": terminal_growth,
            "method": "bank_equity_side_projection",
        },
        warnings=warnings,
        fallback=bool(warnings),
        confidence_cap="low" if warnings else None,
        integrity_checks=_financial_retained_earnings_checks(statements),
    )


def _roe_projection_series(history: list[AnnualMetricRow]) -> list[tuple[int, float]]:
    direct = _ratio_metric_series(history, ROE_ALIASES)
    if direct:
        return direct
    net_income = dict(_series(history, NET_INCOME_ALIASES))
    equity = dict(_series(history, EQUITY_ALIASES))
    out: list[tuple[int, float]] = []
    for year in sorted(set(net_income) & set(equity)):
        if equity[year] > 0:
            out.append((year, net_income[year] / equity[year]))
    return out


def _build_roe_financial_projection(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    assumptions: Mapping[str, Any],
    *,
    scenario: str,
    overrides: Mapping[str, Any],
    archetype: str,
) -> Projection:
    years = max(1, int(float(assumptions.get("forecast_years", 5.0))))
    start_year = int(snapshot.latest_statement_year or dt.date.today().year)
    peer_driver_medians = _peer_driver_medians(assumptions)
    roe_series = _roe_projection_series(history)
    snapshot_roe = _ratio_input(snapshot.metrics.get("ROE"))
    if not roe_series and snapshot_roe is not None:
        roe_series = [(start_year, snapshot_roe)]
    peer_name = "insurer_roe" if archetype == "insurance" else "financial_roe"
    roe_peer = _peer_driver_value(peer_driver_medians, peer_name) or _peer_driver_value(peer_driver_medians, "insurer_roe")
    roe, roe_unavailable = _trailing_or_peer(
        roe_series,
        peer_value=roe_peer,
        unavailable_warning=("insurer_roe_unavailable_no_history_no_peer" if archetype == "insurance" else "financial_roe_unavailable_no_history_no_peer"),
    )
    if roe_unavailable:
        return _empty_projection(snapshot, scenario=scenario, start_year=start_year, years=years, warnings=[roe_unavailable])
    latest_equity, equity_warning = _financial_equity_anchor(snapshot, history)
    if latest_equity is None:
        return _empty_projection(snapshot, scenario=scenario, start_year=start_year, years=years, warnings=[equity_warning or "missing_financial_book_equity"])
    payout_ratio, payout_series, payout_warning = _financial_payout_ratio(history, peer_driver_medians)
    if payout_ratio is None:
        return _empty_projection(snapshot, scenario=scenario, start_year=start_year, years=years, warnings=[payout_warning or "payout_ratio_unavailable_no_history_no_peer"])

    roe_path = _apply_override_series("roe", [roe] * years, start_year, overrides)
    payout_path = _apply_override_series("payout_ratio", [payout_ratio] * years, start_year, overrides)
    warnings = [
        "insurer_simplified_roe_projection" if archetype == "insurance" else "financial_simplified_roe_projection",
        *[
            warning
            for warning in (
                "roe_from_peer_median" if not roe_series and roe_peer is not None else None,
                payout_warning,
                equity_warning,
            )
            if warning
        ],
    ]
    statements: list[dict[str, Any]] = []
    dividends: list[float] = []
    book_values: list[float] = []
    previous_equity = latest_equity
    for index in range(years):
        fiscal_year = start_year + index + 1
        beginning_equity = previous_equity
        net_income = beginning_equity * roe_path[index]
        dividend = max(0.0, net_income) * _clamp(payout_path[index], 0.0, 0.95)
        ending_equity = beginning_equity + net_income - dividend
        statement = {
            "fiscal_year": fiscal_year,
            "periods_per_year": 1,
            "period_type": "annual",
            "period_index": 0,
            "period_label": "FY",
            "period_end_date": _annual_period_end_date(snapshot.as_of_date, fiscal_year),
            "net_income": net_income,
            "dividends": dividend,
            "beginning_equity": beginning_equity,
            "total_equity": ending_equity,
            "book_equity": ending_equity,
            "roe": roe_path[index],
        }
        statements.append(statement)
        dividends.append(dividend)
        book_values.append(ending_equity)
        previous_equity = ending_equity

    fiscal_years = [start_year + index + 1 for index in range(years)]
    drivers = {
        "roe": DriverEstimate(
            name="roe",
            projected_by_year=_year_map(fiscal_years, roe_path),
            method="observed trailing ROE applied to beginning book equity; peer median only when available",
            inputs={"trailing_3y_average": roe, "peer_median": roe_peer},
            historical_series=_series_to_dict(roe_series[-7:]),
            anchor_value=roe,
            divergence=0.0,
            warning="roe_from_peer_median" if not roe_series and roe_peer is not None else None,
        ),
        "payout_ratio": DriverEstimate(
            name="payout_ratio",
            projected_by_year=_year_map(fiscal_years, payout_path),
            method="observed dividends / net income, capped at 95%; peer median only when available",
            inputs={"trailing_3y_average": payout_ratio, "peer_median": _peer_driver_value(peer_driver_medians, "payout_ratio")},
            historical_series=_series_to_dict(payout_series[-7:]),
            anchor_value=payout_ratio,
            divergence=0.0,
            warning=payout_warning,
        ),
    }
    return Projection(
        symbol=snapshot.symbol.upper(),
        scenario=scenario,
        start_year=start_year,
        forecast_years=years,
        as_of=snapshot.as_of_date,
        statements=statements,
        drivers=drivers,
        fcff=[],
        fcfe=[],
        dividends=dividends,
        book_values=book_values,
        periods_per_year=1,
        period_type="annual",
        growth_decomposition={
            "roe": _series_to_dict(roe_series[-7:]),
            "terminal_growth": _float(assumptions.get("terminal_growth_equity", assumptions.get("terminal_growth")), 0.025),
            "method": "insurer_simplified_roe_projection" if archetype == "insurance" else "financial_simplified_roe_projection",
        },
        warnings=warnings,
        fallback=True,
        confidence_cap="low",
        integrity_checks=_financial_retained_earnings_checks(statements),
    )


def _financial_retained_earnings_checks(statements: list[dict[str, Any]]) -> list[IntegrityCheck]:
    checks: list[IntegrityCheck] = []
    for statement in statements:
        year = int(statement.get("fiscal_year") or 0)
        net_income = _float(statement.get("net_income"), 0.0)
        dividends = _float(statement.get("dividends"), 0.0)
        beginning_equity = _float(statement.get("beginning_equity"), 0.0)
        equity = _float(statement.get("total_equity"), 0.0)
        delta = equity - (beginning_equity + net_income - dividends)
        checks.append(
            IntegrityCheck(
                name=f"projection_financial_retained_earnings_{year}",
                status=_status(delta, max(abs(equity), 1.0)),
                delta=delta,
                rel_delta=_rel(delta, equity),
                inputs={
                    "Prior_Equity": beginning_equity,
                    "Net_Income": net_income,
                    "Dividends": dividends,
                    "Total_Equity": equity,
                },
                message="financial_equity_side_identity: ending equity equals beginning equity plus NI minus dividends",
            )
        )
    return checks


def _build_period_projection(
    snapshot: FundamentalSnapshot,
    annual_history: list[AnnualMetricRow],
    period_history: list[PeriodMetricRow],
    assumptions: Mapping[str, Any],
    *,
    scenario: str,
    overrides: Mapping[str, Any],
    period_type: str,
    periods_per_year: int,
    cyclical: bool,
) -> Projection:
    years = max(1, int(float(assumptions.get("forecast_years", 5.0))))
    steps = years * periods_per_year
    terminal_growth = _float(assumptions.get("terminal_growth_firm", assumptions.get("terminal_growth")), 0.025)
    terminal_growth_period = annual_rate_to_period_rate(terminal_growth, periods_per_year)
    tax_rate_assumption = _float(assumptions.get("tax_rate"), 0.35)
    peer_driver_medians = _peer_driver_medians(assumptions)
    unavailable_driver_warnings: list[str] = []

    revenue_series = _period_series(period_history, period_type, REVENUE_ALIASES)
    if not revenue_series:
        start_year = int(snapshot.latest_statement_year or dt.date.today().year)
        return Projection(
            symbol=snapshot.symbol.upper(),
            scenario=scenario,
            start_year=start_year,
            forecast_years=years,
            as_of=snapshot.as_of_date,
            statements=[],
            drivers={},
            fcff=[],
            fcfe=[],
            dividends=[],
            book_values=[],
            periods_per_year=periods_per_year,
            period_type=period_type,
            warnings=[f"missing_{period_type}_revenue_history"],
            fallback=True,
            confidence_cap="low",
        )

    start_key = revenue_series[-1][0]
    start_year = int(start_key[0])
    revenue_growth_history = _period_yoy_growth_series(revenue_series)
    historical_growth_bound = _winsorized_peak_values([value for _key, value in revenue_growth_history])
    cagr_3y = _trailing_average(revenue_growth_history[-(3 * periods_per_year) :], default=terminal_growth) if revenue_growth_history else None
    last_year_growth = revenue_growth_history[-1][1] if revenue_growth_history else cagr_3y
    growth_warning = None
    if cagr_3y is None and last_year_growth is None:
        peer_growth = _peer_driver_value(peer_driver_medians, "revenue_growth")
        if peer_growth is not None:
            year1_growth = peer_growth
            growth_method = f"sector peer median revenue growth because {period_type} revenue history has one usable same-period point"
            growth_warning = "revenue_growth_from_peer_median"
        else:
            year1_growth = terminal_growth
            growth_method = f"unavailable because {period_type} revenue history has one usable same-period point and no peer median"
            growth_warning = "revenue_growth_unavailable_no_history_no_peer"
            unavailable_driver_warnings.append(growth_warning)
    elif cagr_3y is None:
        year1_growth = float(last_year_growth or 0.0)
        growth_method = f"last same-period YoY revenue growth {year1_growth:.2%} fades to terminal {terminal_growth:.2%}"
    elif last_year_growth is None:
        year1_growth = float(cagr_3y)
        growth_method = f"3y same-period YoY revenue growth {year1_growth:.2%} fades to terminal {terminal_growth:.2%}"
    else:
        year1_growth = 0.5 * float(cagr_3y) + 0.5 * float(last_year_growth)
        growth_method = (
            f"blend(3y same-period YoY revenue growth {cagr_3y:.2%}, last same-period YoY growth {last_year_growth:.2%}) "
            f"fades to terminal {terminal_growth:.2%}"
        )
    if historical_growth_bound is not None:
        year1_growth = min(year1_growth, historical_growth_bound)
    year1_growth = max(-0.10, year1_growth)
    growth_path = _fade_path(year1_growth, terminal_growth, steps)
    growth_path = _apply_override_period_series("revenue_growth", growth_path, start_key, periods_per_year, overrides)
    growth_anchor = cagr_3y if cagr_3y is not None else last_year_growth
    growth_divergence, divergence_warning = _divergence(growth_path[0], growth_anchor, name="revenue_growth")
    growth_warning = growth_warning or divergence_warning

    margin_series = _period_ratio_series(period_history, period_type, EBIT_ALIASES, REVENUE_ALIASES)
    annual_margin_series = _ratio_series(annual_history, EBIT_ALIASES, REVENUE_ALIASES)
    ebit_peer = _peer_driver_value(peer_driver_medians, "ebit_margin")
    ebit_anchor, ebit_margin_unavailable = _trailing_or_peer(
        margin_series or annual_margin_series,
        peer_value=ebit_peer,
        unavailable_warning="ebit_margin_unavailable_no_history_no_peer",
    )
    if ebit_margin_unavailable:
        unavailable_driver_warnings.append(ebit_margin_unavailable)
    latest_margin = margin_series[-1][1] if margin_series else ebit_anchor
    midcycle_margin = None
    if cyclical and len(annual_margin_series) >= 3:
        # Through-cycle mean reversion (brief 44 RC-A): fade FROM the latest realized
        # margin TO the mid-cycle median. Do NOT clip the start to the median — that
        # pins a trough quarter to a trough-dragged flat line.
        midcycle_margin = float(median([value for _year, value in annual_margin_series]))
        ebit_anchor = midcycle_margin
    margin_path = _fade_path(latest_margin, ebit_anchor, steps)
    margin_path = _apply_override_period_series("ebit_margin", margin_path, start_key, periods_per_year, overrides)
    margin_divergence, margin_warning = _divergence(margin_path[0], ebit_anchor, name="ebit_margin", absolute_band=0.05)
    if not margin_series and not annual_margin_series and ebit_peer is not None:
        margin_warning = "ebit_margin_from_peer_median"
    if cyclical:
        margin_warning = "midcycle_ebit_margin_applied" if midcycle_margin is not None else "midcycle_ebit_margin_unavailable_insufficient_history"
    if ebit_margin_unavailable:
        margin_warning = ebit_margin_unavailable

    effective_tax = _period_effective_tax_rate(period_history, period_type)
    if effective_tax is None:
        effective_tax = _effective_tax_rate(annual_history)
    tax_rate = effective_tax if effective_tax is not None else tax_rate_assumption
    tax_path = _apply_override_period_series("tax_rate", [tax_rate] * steps, start_key, periods_per_year, overrides)

    dand_a_series = _period_ratio_series(period_history, period_type, DANDA_ALIASES, REVENUE_ALIASES)
    annual_dand_a_series = _ratio_series(annual_history, DANDA_ALIASES, REVENUE_ALIASES)
    dand_a_peer = _peer_driver_value(peer_driver_medians, "depreciation_amortization_pct")
    dand_a_pct, dand_a_unavailable = _trailing_or_peer(
        dand_a_series or annual_dand_a_series,
        peer_value=dand_a_peer,
        unavailable_warning="d_and_a_pct_unavailable_no_history_no_peer",
    )
    if dand_a_unavailable:
        unavailable_driver_warnings.append(dand_a_unavailable)
    dand_a_warning = None
    if not dand_a_series and not annual_dand_a_series and dand_a_peer is not None:
        dand_a_warning = "d_and_a_pct_from_peer_median"
    if dand_a_unavailable:
        dand_a_warning = dand_a_unavailable
    dand_a_path = _apply_override_period_series("depreciation_amortization_pct", [dand_a_pct] * steps, start_key, periods_per_year, overrides)

    annual_capex_series = _ratio_series(annual_history, CAPEX_ALIASES, REVENUE_ALIASES, absolute_numerator=True)
    capex_series = _period_ratio_series(period_history, period_type, CAPEX_ALIASES, REVENUE_ALIASES, absolute_numerator=True)
    capex_peer = _peer_driver_value(peer_driver_medians, "capex_pct")
    capex_pct, capex_unavailable = _trailing_or_peer(
        capex_series or annual_capex_series,
        peer_value=capex_peer,
        unavailable_warning="capex_pct_unavailable_no_history_no_peer",
    )
    if capex_unavailable:
        unavailable_driver_warnings.append(capex_unavailable)
    midcycle_capex_pct = None
    if cyclical and len(annual_capex_series) >= 3:
        midcycle_capex_pct = float(median([value for _year, value in annual_capex_series]))
    maintenance_capex_norm = (
        midcycle_capex_pct
        if midcycle_capex_pct is not None
        else _float(assumptions.get("maintenance_capex_pct"), capex_pct)
    )
    if cyclical:
        # Mid-cycle maintenance capex = median(capex%) over the cycle, or the D&A%
        # maintenance proxy when there's no capex history. Do NOT take
        # max(D&A%, capex%) for cyclicals — that inflates maintenance capex and
        # double-penalizes FCFF on top of the margin normalization (brief 44 RC-A).
        maintenance_capex_pct = (
            midcycle_capex_pct if midcycle_capex_pct is not None else dand_a_pct
        )
    else:
        maintenance_capex_pct = max(dand_a_pct, maintenance_capex_norm)
    capex_warning = None
    if not capex_series and not annual_capex_series and capex_peer is not None:
        capex_warning = "capex_pct_from_peer_median"
    if cyclical:
        capex_warning = (
            "midcycle_maintenance_capex_applied"
            if midcycle_capex_pct is not None
            else "midcycle_maintenance_capex_unavailable_registry_assumption"
        )
    if capex_unavailable:
        capex_warning = capex_unavailable
    capex_path = _fade_path(capex_pct, maintenance_capex_pct, steps)
    capex_path = _apply_override_period_series("capex_pct", capex_path, start_key, periods_per_year, overrides)

    annual_wc_series = _working_capital_ratio_series(annual_history)
    wc_series = _period_working_capital_ratio_series(period_history, period_type)
    wc_peer = _peer_driver_value(peer_driver_medians, "working_capital_pct")
    wc_pct, wc_unavailable = _trailing_or_peer(
        wc_series or annual_wc_series,
        peer_value=wc_peer,
        unavailable_warning="working_capital_pct_unavailable_no_history_no_peer",
    )
    if wc_unavailable:
        unavailable_driver_warnings.append(wc_unavailable)
    wc_warning = None
    if not wc_series and not annual_wc_series and wc_peer is not None:
        wc_warning = "working_capital_pct_from_peer_median"
    if wc_unavailable:
        wc_warning = wc_unavailable
    wc_path = _apply_override_period_series("working_capital_pct", [wc_pct] * steps, start_key, periods_per_year, overrides)

    annual_payout_series = _payout_ratio_series(annual_history)
    payout_series = _period_payout_ratio_series(period_history, period_type)
    payout_peer = _peer_driver_value(peer_driver_medians, "payout_ratio")
    payout_ratio, payout_unavailable = _trailing_or_peer(
        payout_series or annual_payout_series,
        peer_value=payout_peer,
        unavailable_warning="payout_ratio_unavailable_no_history_no_peer",
    )
    if payout_unavailable:
        unavailable_driver_warnings.append(payout_unavailable)
    payout_warning = None
    if not payout_series and not annual_payout_series and payout_peer is not None:
        payout_warning = "payout_ratio_from_peer_median"
    if payout_unavailable:
        payout_warning = payout_unavailable
    if isfinite(float(payout_ratio)):
        payout_ratio = _clamp(payout_ratio, 0.0, 0.95)
    payout_path = _apply_override_period_series("payout_ratio", [payout_ratio] * steps, start_key, periods_per_year, overrides)

    cash_flow_missing = not (
        _period_series(period_history, period_type, FREE_CASH_FLOW_ALIASES)
        or _period_series(period_history, period_type, OPERATING_CF_ALIASES)
        or _period_series(period_history, period_type, INVESTING_CF_ALIASES)
        or _series(annual_history, FREE_CASH_FLOW_ALIASES)
        or _series(annual_history, OPERATING_CF_ALIASES)
        or _series(annual_history, INVESTING_CF_ALIASES)
    )
    warnings = [warning for warning in (growth_warning, margin_warning, capex_warning, wc_warning, dand_a_warning, payout_warning) if warning]
    if cash_flow_missing:
        warnings.append("cash_flow_statement_missing_driver_fallback")
    if unavailable_driver_warnings:
        warnings.append("projection_driver_unavailable")

    latest_equity = _latest_period_or_annual_or_snapshot(period_history, annual_history, snapshot, period_type, EQUITY_ALIASES)
    if latest_equity is None:
        latest_equity = _book_equity_proxy(snapshot) or 0.0
        warnings.append("equity_proxy_or_zero_for_projection")
    latest_debt = _latest_period_or_annual_or_snapshot(period_history, annual_history, snapshot, period_type, DEBT_ALIASES) or 0.0
    latest_cash = _latest_period_or_annual_or_snapshot(period_history, annual_history, snapshot, period_type, CASH_ALIASES) or 0.0
    working_capital = _latest_period_working_capital(period_history, period_type)
    if working_capital is None:
        working_capital = _latest_working_capital(annual_history) or 0.0
    latest_assets = _latest_period_or_annual_or_snapshot(period_history, annual_history, snapshot, period_type, TOTAL_ASSET_ALIASES)
    latest_liabilities = _latest_period_or_annual_or_snapshot(period_history, annual_history, snapshot, period_type, TOTAL_LIABILITY_ALIASES)
    if latest_liabilities is not None:
        other_liabilities = max(0.0, latest_liabilities - latest_debt)
    elif latest_assets is not None:
        other_liabilities = max(0.0, latest_assets - latest_debt - latest_equity)
    else:
        other_liabilities = 0.0
    if latest_assets is None:
        latest_assets = latest_debt + other_liabilities + latest_equity
        warnings.append("total_assets_missing_non_cash_asset_proxy")
    non_cash_assets = max(0.0, latest_assets - latest_cash)
    interest = abs(_latest_period_or_annual_or_snapshot(period_history, annual_history, snapshot, period_type, INTEREST_ALIASES) or 0.0)
    latest_revenue = float(revenue_series[-1][1])
    if interest > latest_revenue:
        interest = 0.0

    statements: list[dict[str, Any]] = []
    fcff: list[float] = []
    fcfe: list[float] = []
    dividends: list[float] = []
    book_values: list[float] = []
    revenue_by_period = {key: value for key, value in revenue_series}
    previous_equity = latest_equity
    previous_cash = latest_cash
    same_period_fallback_count = 0
    for index in range(steps):
        fiscal_year, period_index = _future_period_key(start_key, index + 1, periods_per_year)
        same_period_key = (fiscal_year - 1, period_index)
        same_period_revenue = revenue_by_period.get(same_period_key)
        if same_period_revenue is None:
            same_period_revenue = revenue_by_period[sorted(revenue_by_period)[-1]]
            same_period_fallback_count += 1
        revenue = same_period_revenue * (1.0 + growth_path[index])
        revenue_by_period[(fiscal_year, period_index)] = revenue
        delta_revenue = revenue - same_period_revenue
        ebit = revenue * margin_path[index]
        dand_a = revenue * max(0.0, dand_a_path[index])
        ebitda = ebit + dand_a
        tax = _clamp(tax_path[index], 0.0, 0.60)
        nopat = ebit * (1.0 - tax)
        capex = revenue * max(0.0, capex_path[index])
        delta_wc = delta_revenue * wc_path[index]
        working_capital += delta_wc
        reinvestment = capex + delta_wc - dand_a
        fcff_value = nopat - reinvestment
        after_tax_interest = interest * (1.0 - tax)
        fcfe_value = fcff_value - after_tax_interest
        net_income = (ebit - interest) * (1.0 - tax)
        dividend = max(0.0, net_income) * _clamp(payout_path[index], 0.0, 0.95)
        beginning_equity = previous_equity
        ending_equity = previous_equity + net_income - dividend
        operating_cf = net_income + dand_a - delta_wc
        investing_cf = -capex
        financing_cf = -dividend
        ending_cash = previous_cash + operating_cf + investing_cf + financing_cf
        non_cash_assets = max(0.0, non_cash_assets + reinvestment)
        total_liabilities_before_plug = latest_debt + other_liabilities
        total_assets_before_plug = ending_cash + non_cash_assets
        completed_bs = _complete_projected_balance_sheet(
            total_assets_before_plug=total_assets_before_plug,
            total_liabilities_before_plug=total_liabilities_before_plug,
            total_equity=ending_equity,
        )
        gross_profit = max(ebitda, ebit, net_income, 0.0)
        period_label = _period_label(period_index, periods_per_year)
        statement = {
            "fiscal_year": fiscal_year,
            "periods_per_year": periods_per_year,
            "period_type": period_type,
            "period_index": period_index,
            "period_label": period_label,
            "period_end_date": _period_end_date(fiscal_year, period_index, periods_per_year),
            "revenue": revenue,
            "revenue_growth": growth_path[index],
            "revenue_growth_yoy": growth_path[index],
            "revenue_growth_period_terminal": terminal_growth_period,
            "gross_profit": gross_profit,
            "ebitda": ebitda,
            "ebit": ebit,
            "ebit_margin": margin_path[index],
            "tax_rate": tax,
            "nopat": nopat,
            "depreciation_amortization": dand_a,
            "capex": capex,
            "delta_working_capital": delta_wc,
            "working_capital": working_capital,
            "reinvestment": reinvestment,
            "fcff": fcff_value,
            "interest_expense": interest,
            "fcfe": fcfe_value,
            "net_income": net_income,
            "dividends": dividend,
            "beginning_equity": beginning_equity,
            "beginning_cash": previous_cash,
            "operating_cash_flow": operating_cf,
            "investing_cash_flow": investing_cf,
            "financing_cash_flow": financing_cf,
            "ending_cash": ending_cash,
            "cash": ending_cash,
            "non_cash_assets": non_cash_assets,
            "debt": latest_debt,
            "total_equity": ending_equity,
            **completed_bs,
        }
        statements.append(statement)
        fcff.append(fcff_value)
        fcfe.append(fcfe_value)
        dividends.append(dividend)
        book_values.append(ending_equity)
        previous_equity = ending_equity
        previous_cash = ending_cash

    if same_period_fallback_count:
        warnings.append(f"same_period_anchor_missing_{same_period_fallback_count}_steps")

    period_keys = [(int(row["fiscal_year"]), int(row["period_index"])) for row in statements]
    period_records = [_period_projection_record(key, _period_label(key[1], periods_per_year), value) for key, value in zip(period_keys, growth_path)]
    drivers = {
        "revenue_growth": DriverEstimate(
            name="revenue_growth",
            projected_by_year=_year_map_from_period_path(period_keys, growth_path),
            projected_by_period=period_records,
            method=growth_method,
            inputs={
                "cagr_3y": cagr_3y,
                "last_year_growth": last_year_growth,
                "terminal_growth": terminal_growth,
                "terminal_growth_period": terminal_growth_period,
                "periods_per_year": periods_per_year,
                "historical_growth_upper_bound": historical_growth_bound,
                "growth_bound_method": "winsorized_peak_same_period_yoy_90th_percentile" if historical_growth_bound is not None else "none_one_point_history",
                "blend_weight_cagr": 0.5,
                "blend_weight_last_year": 0.5,
                "peer_median": _peer_driver_value(peer_driver_medians, "revenue_growth"),
            },
            historical_series=_period_series_to_dict(revenue_growth_history[-(7 * periods_per_year) :], periods_per_year),
            anchor_value=growth_anchor,
            divergence=growth_divergence,
            warning=growth_warning,
        ),
        "ebit_margin": DriverEstimate(
            name="ebit_margin",
            projected_by_year=_year_map_from_period_path(period_keys, margin_path),
            projected_by_period=[_period_projection_record(key, _period_label(key[1], periods_per_year), value) for key, value in zip(period_keys, margin_path)],
            method=(
                f"mid-cycle EBIT margin {ebit_anchor:.2%} from observed annual cycle history"
                if midcycle_margin is not None
                else f"latest realized {period_type} EBIT margin {latest_margin:.2%} fades to trailing average {ebit_anchor:.2%}"
            ),
            inputs={
                "trailing_average": ebit_anchor,
                "latest_margin": latest_margin,
                "periods_per_year": periods_per_year,
                "peer_median": ebit_peer,
                "cyclical": cyclical,
                "midcycle_margin": midcycle_margin,
                "midcycle_observation_count": len(annual_margin_series),
            },
            historical_series=_period_series_to_dict(margin_series[-(7 * periods_per_year) :], periods_per_year),
            anchor_value=ebit_anchor,
            divergence=margin_divergence,
            warning=margin_warning,
        ),
        "tax_rate": DriverEstimate(
            name="tax_rate",
            projected_by_year=_year_map_from_period_path(period_keys, tax_path),
            projected_by_period=[_period_projection_record(key, _period_label(key[1], periods_per_year), value) for key, value in zip(period_keys, tax_path)],
            method="period effective tax rate when cleanly derivable, otherwise registry tax_rate",
            inputs={"assumption_tax_rate": tax_rate_assumption, "effective_tax_rate": effective_tax, "periods_per_year": periods_per_year},
            historical_series=_period_series_to_dict(_period_tax_rate_series(period_history, period_type)[-(7 * periods_per_year) :], periods_per_year),
            anchor_value=tax_rate,
            divergence=0.0,
        ),
        "capex_pct": DriverEstimate(
            name="capex_pct",
            projected_by_year=_year_map_from_period_path(period_keys, capex_path),
            projected_by_period=[_period_projection_record(key, _period_label(key[1], periods_per_year), value) for key, value in zip(period_keys, capex_path)],
            method="period absolute Capex / Revenue fades to maintenance capex max(D&A / Revenue, structural maintenance norm)",
            inputs={
                "current_capex_pct": capex_pct,
                "maintenance_capex_pct": maintenance_capex_pct,
                "d_and_a_pct": dand_a_pct,
                "structural_maintenance_capex_norm": _float(assumptions.get("maintenance_capex_pct"), capex_pct),
                "midcycle_maintenance_capex_pct": midcycle_capex_pct,
                "default_used": not bool(capex_series),
                "periods_per_year": periods_per_year,
                "peer_median": capex_peer,
                "cyclical": cyclical,
            },
            historical_series=_period_series_to_dict(capex_series[-(7 * periods_per_year) :], periods_per_year),
            anchor_value=capex_pct,
            divergence=abs(capex_path[0] - maintenance_capex_pct),
            warning=capex_warning,
        ),
        "working_capital_pct": DriverEstimate(
            name="working_capital_pct",
            projected_by_year=_year_map_from_period_path(period_keys, wc_path),
            projected_by_period=[_period_projection_record(key, _period_label(key[1], periods_per_year), value) for key, value in zip(period_keys, wc_path)],
            method="period working capital / revenue applied to incremental same-period sales",
            inputs={"trailing_average": wc_pct, "default_used": not bool(wc_series), "periods_per_year": periods_per_year, "peer_median": wc_peer},
            historical_series=_period_series_to_dict(wc_series[-(7 * periods_per_year) :], periods_per_year),
            anchor_value=wc_pct,
            divergence=0.0,
            warning=wc_warning,
        ),
        "depreciation_amortization_pct": DriverEstimate(
            name="depreciation_amortization_pct",
            projected_by_year=_year_map_from_period_path(period_keys, dand_a_path),
            projected_by_period=[_period_projection_record(key, _period_label(key[1], periods_per_year), value) for key, value in zip(period_keys, dand_a_path)],
            method="period D&A / Revenue trailing average",
            inputs={"trailing_average": dand_a_pct, "default_used": not bool(dand_a_series), "periods_per_year": periods_per_year, "peer_median": dand_a_peer},
            historical_series=_period_series_to_dict(dand_a_series[-(7 * periods_per_year) :], periods_per_year),
            anchor_value=dand_a_pct,
            divergence=0.0,
            warning=dand_a_warning,
        ),
        "payout_ratio": DriverEstimate(
            name="payout_ratio",
            projected_by_year=_year_map_from_period_path(period_keys, payout_path),
            projected_by_period=[_period_projection_record(key, _period_label(key[1], periods_per_year), value) for key, value in zip(period_keys, payout_path)],
            method="period dividends / net income average, capped at 95%",
            inputs={"trailing_average": payout_ratio, "periods_per_year": periods_per_year, "peer_median": payout_peer},
            historical_series=_period_series_to_dict(payout_series[-(7 * periods_per_year) :], periods_per_year),
            anchor_value=payout_ratio,
            divergence=0.0,
        ),
        "fcff": DriverEstimate(
            name="fcff",
            projected_by_year=_year_map_from_period_path(period_keys, fcff),
            projected_by_period=[_period_projection_record(key, _period_label(key[1], periods_per_year), value) for key, value in zip(period_keys, fcff)],
            method="Period Revenue -> EBIT -> NOPAT - (Capex + delta WC - D&A)",
            inputs={"cash_flow_statement_missing": cash_flow_missing, "periods_per_year": periods_per_year},
            historical_series=_period_series_to_dict(_period_series(period_history, period_type, FREE_CASH_FLOW_ALIASES)[-(7 * periods_per_year) :], periods_per_year),
            anchor_value=_latest_or_none(_series(annual_history, FREE_CASH_FLOW_ALIASES)),
            divergence=None,
            warning="direct_driver_fcff_fallback" if cash_flow_missing else None,
        ),
    }
    growth_decomposition = {
        "revenue_growth": _period_series_to_dict(revenue_growth_history[-(7 * periods_per_year) :], periods_per_year),
        "ebit_growth": _period_series_to_dict(_period_yoy_growth_series(_period_series(period_history, period_type, EBIT_ALIASES))[-(7 * periods_per_year) :], periods_per_year),
        "net_income_growth": _period_series_to_dict(_period_yoy_growth_series(_period_series(period_history, period_type, NET_INCOME_ALIASES))[-(7 * periods_per_year) :], periods_per_year),
        "fcf_growth": _period_series_to_dict(_period_yoy_growth_series(_period_series(period_history, period_type, FREE_CASH_FLOW_ALIASES))[-(7 * periods_per_year) :], periods_per_year),
        "projected_revenue_growth": [_period_projection_record(key, _period_label(key[1], periods_per_year), value) for key, value in zip(period_keys, growth_path)],
        "terminal_growth": terminal_growth,
        "terminal_growth_period": terminal_growth_period,
        "periods_per_year": periods_per_year,
        "period_type": period_type,
        "method": growth_method,
        "cyclical": cyclical,
        "midcycle_ebit_margin": midcycle_margin,
    }
    checks = projection_integrity_checks(statements, starting_equity=latest_equity)
    return Projection(
        symbol=snapshot.symbol.upper(),
        scenario=scenario,
        start_year=start_year,
        forecast_years=years,
        as_of=snapshot.as_of_date,
        statements=statements,
        drivers=drivers,
        fcff=fcff,
        fcfe=fcfe,
        dividends=dividends,
        book_values=book_values,
        periods_per_year=periods_per_year,
        period_type=period_type,
        growth_decomposition=growth_decomposition,
        warnings=warnings,
        fallback=bool(cash_flow_missing or unavailable_driver_warnings),
        confidence_cap="unavailable" if unavailable_driver_warnings else "low" if cash_flow_missing else None,
        integrity_checks=checks,
    )


def projection_integrity_checks(statements: list[dict[str, Any]], *, starting_equity: float) -> list[IntegrityCheck]:
    checks: list[IntegrityCheck] = []
    for statement in statements:
        year = int(statement["fiscal_year"])
        period_label = str(statement.get("period_label") or "FY")
        suffix = str(year) if period_label == "FY" else f"{year}_{period_label}"
        assets = _float(statement.get("total_assets"), 0.0)
        liabilities = _float(statement.get("total_liabilities"), 0.0)
        equity = _float(statement.get("total_equity"), 0.0)
        pre_plug_delta = _float(statement.get("projection_bs_pre_plug_delta"), 0.0)
        checks.append(
            IntegrityCheck(
                name=f"projection_financing_gap_{suffix}",
                status=_diagnostic_status(pre_plug_delta, assets),
                delta=pre_plug_delta,
                rel_delta=_rel(pre_plug_delta, assets),
                inputs={
                    "Total_Assets_Before_Plug": _float(statement.get("total_assets_before_plug"), assets),
                    "Total_Liabilities_Before_Plug": _float(statement.get("total_liabilities_before_plug"), liabilities),
                    "Total_Equity": equity,
                    "Projected_Other_Liabilities_Adjustment": _float(statement.get("projected_other_liabilities_adjustment"), 0.0),
                    "Projected_Other_Asset_Adjustment": _float(statement.get("projected_other_asset_adjustment"), 0.0),
                },
                message="diagnostic_only: projected statement completed with explicit other-liability/asset adjustment",
            )
        )
        delta = _float(statement.get("projection_bs_post_plug_delta"), assets - liabilities - equity)
        checks.append(
            IntegrityCheck(
                name=f"projection_bs_balance_{suffix}",
                status=_status(delta, assets),
                delta=delta,
                rel_delta=_rel(delta, assets),
                inputs={
                    "Total_Assets": assets,
                    "Total_Liabilities": liabilities,
                    "Total_Equity": equity,
                    "Balance_Sheet_Plug": _float(statement.get("balance_sheet_plug"), 0.0),
                },
                message="completed_identity: total assets equal liabilities plus equity after explicit projection adjustment",
            )
        )
        ending_cash = _float(statement.get("ending_cash"), 0.0)
        bs_cash = assets - _float(statement.get("non_cash_assets"), 0.0)
        cash_delta = ending_cash - bs_cash
        checks.append(
            IntegrityCheck(
                name=f"projection_cash_tie_out_{suffix}",
                status=_status(cash_delta, bs_cash),
                delta=cash_delta,
                rel_delta=_rel(cash_delta, bs_cash),
                inputs={"CFS_Ending_Cash": ending_cash, "BS_Cash": bs_cash, "Beginning_Cash": _float(statement.get("beginning_cash"), 0.0)},
                message="construction_identity: BS cash = total_assets - non_cash_assets = ending_cash by construction; cannot fail",
            )
        )
        net_income = _float(statement.get("net_income"), 0.0)
        dividends = _float(statement.get("dividends"), 0.0)
        beginning_equity = _float(statement.get("beginning_equity"), starting_equity)
        re_target = beginning_equity + net_income - dividends
        re_delta = equity - re_target
        checks.append(
            IntegrityCheck(
                name=f"projection_retained_earnings_{suffix}",
                status=_status(re_delta, max(abs(equity), 1.0)),
                delta=re_delta,
                rel_delta=_rel(re_delta, equity),
                inputs={"Prior_Equity": beginning_equity, "Net_Income": net_income, "Dividends": dividends, "Total_Equity": equity},
                message="construction_identity: ending_equity is defined as beginning_equity + NI - dividends; cannot fail",
            )
        )
        cfs_net_income = _float(statement.get("operating_cash_flow"), 0.0) - _float(statement.get("depreciation_amortization"), 0.0) + _float(statement.get("delta_working_capital"), 0.0)
        ni_delta = net_income - cfs_net_income
        checks.append(
            IntegrityCheck(
                name=f"projection_net_income_link_{suffix}",
                status=_status(ni_delta, net_income),
                delta=ni_delta,
                rel_delta=_rel(ni_delta, net_income),
                inputs={"IS_Net_Income": net_income, "CFS_Net_Income_Top_Of_CFS": cfs_net_income},
                message="construction_identity: operating_cf is defined as NI + D&A - delta_WC so this always reconciles; cannot fail",
            )
        )
        checks.append(_margin_hierarchy_check(statement, suffix))
        capex = _float(statement.get("capex"), 0.0)
        financing_cf = _float(statement.get("financing_cash_flow"), 0.0)
        sign_ok = capex >= -1e-9 and financing_cf <= 1e-9
        checks.append(
            IntegrityCheck(
                name=f"projection_sign_conventions_{suffix}",
                status="pass" if sign_ok else "warn",
                delta=None,
                rel_delta=None,
                inputs={"Capex_Use_Of_Cash": capex, "Financing_CF": financing_cf, "Dividends": dividends},
                message=None if sign_ok else "capex should be positive use-of-cash and dividends negative in CFF",
            )
        )
    return checks


def scenario_hierarchy_checks(projections: Mapping[str, Projection]) -> list[IntegrityCheck]:
    ordered = [projections.get("bear"), projections.get("base"), projections.get("bull")]
    if any(item is None for item in ordered):
        return []
    checks: list[IntegrityCheck] = []
    for index in range(min(len(item.statements) for item in ordered if item is not None)):
        year = int(ordered[1].statements[index]["fiscal_year"])  # type: ignore[index]
        for item in ("revenue", "ebitda", "fcff", "ebit_margin"):
            bear = _float(ordered[0].statements[index].get(item), 0.0)  # type: ignore[union-attr]
            base = _float(ordered[1].statements[index].get(item), 0.0)  # type: ignore[union-attr]
            bull = _float(ordered[2].statements[index].get(item), 0.0)  # type: ignore[union-attr]
            ok = bull + 1e-9 >= base >= bear - 1e-9
            checks.append(
                IntegrityCheck(
                    name=f"projection_scenario_hierarchy_{item}_{year}",
                    status="pass" if ok else "warn",
                    delta=None,
                    rel_delta=None,
                    inputs={"bear": bear, "base": base, "bull": bull},
                    message=None if ok else "scenario hierarchy violated",
                )
            )
    return checks


def _float(value: Any, default: float | None = None) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        if default is None:
            raise
        return default
    return out if isfinite(out) else (default if default is not None else 0.0)


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _snapshot_value(snapshot: FundamentalSnapshot, aliases: Iterable[str]) -> float | None:
    for alias in aliases:
        canonical = resolve_metric_name(alias)
        value = _finite(snapshot.metrics.get(canonical))
        if value is not None:
            return value
        if alias != canonical:
            value = _finite(snapshot.metrics.get(alias))
            if value is not None:
                return value
    return None


def _pick_best_row_per_year(
    history: list[AnnualMetricRow],
    aliases: Iterable[str],
) -> dict[int, AnnualMetricRow]:
    """Return one authoritative AnnualMetricRow per statement year.

    1. Drops None / non-finite values.
    2. Rejects per-year candidates whose magnitude is >100× off the year's own
       candidate median (catches mis-scaled twins like 370.32 vs 1.397e9).
    3. Among survivors: prefers non-proxy, then most-recent as_of_date, then
       highest source_document_id (most recent authoritative ingest).
    """
    canonical_set = {resolve_metric_name(a) for a in aliases}
    candidates_by_year: dict[int, list[AnnualMetricRow]] = {}
    for row in history:
        if resolve_metric_name(row.metric_name) not in canonical_set:
            continue
        if _finite(row.metric_value) is None:
            continue
        candidates_by_year.setdefault(int(row.statement_year), []).append(row)

    if not candidates_by_year:
        return {}

    # Per-year absolute-magnitude medians → cross-year series median
    year_meds: dict[int, float] = {}
    for yr, rows in candidates_by_year.items():
        mags: list[float] = []
        for r in rows:
            v = _finite(r.metric_value)
            if v is not None:
                mags.append(abs(v))
        if mags:
            year_meds[yr] = float(median(mags))

    series_med: float | None = float(median(list(year_meds.values()))) if year_meds else None

    by_year: dict[int, AnnualMetricRow] = {}
    for yr, rows in candidates_by_year.items():
        # Reference: the year's own candidate median (most local)
        year_rep = year_meds.get(yr)
        reference = year_rep if (year_rep is not None and year_rep > 0) else series_med

        survivors: list[AnnualMetricRow] = []
        for row in rows:
            v = _finite(row.metric_value)
            if v is None:
                continue
            if reference is None or reference <= 0.0:
                survivors.append(row)
                continue
            mag = abs(v)
            if mag == 0:
                survivors.append(row)
                continue
            ratio = mag / reference if mag >= reference else reference / mag
            if ratio > 100.0:
                _log.warning(
                    "metric_resolver: outlier rejected %s/%s year=%d value=%g ref=%g",
                    row.metric_name, row.symbol, yr, v, reference,
                )
            else:
                survivors.append(row)

        if not survivors:
            # Fallback: keep closest to reference to avoid silently losing a year
            survivors = [min(rows, key=lambda r: abs(abs(_finite(r.metric_value) or 0.0) - (reference or 0.0)))]

        # Prefer: non-proxy > most-recent as_of_date > highest source_document_id
        survivors.sort(
            key=lambda r: (
                0 if r.is_proxy else 1,
                (r.as_of_date or dt.date.min).toordinal(),
                int(r.source_document_id or 0),
            ),
            reverse=True,
        )
        by_year[yr] = survivors[0]

    return by_year


def annual_rate_to_period_rate(rate: float, periods_per_year: int) -> float:
    periods = max(1, int(periods_per_year or 1))
    return (1.0 + float(rate)) ** (1.0 / periods) - 1.0


def _normalize_period_type(period_type: str | None, periods_per_year: int | None = None) -> str:
    if periods_per_year in PERIOD_TYPE_BY_PERIODS:
        return PERIOD_TYPE_BY_PERIODS[int(periods_per_year)]
    normalized = str(period_type or "annual").strip().lower()
    if normalized in {"quarter", "q", "trimestre", "trimestriel"}:
        return "quarterly"
    if normalized in {"semester", "semestre", "semestriel", "half", "halfyear", "half-year"}:
        return "semiannual"
    return normalized if normalized in PERIODS_PER_YEAR_BY_TYPE else "annual"


def _annual_period_end_date(_as_of: dt.date | None, fiscal_year: int) -> str:
    return dt.date(int(fiscal_year), 12, 31).isoformat()


def _period_index_from_label(label: str | None, periods_per_year: int) -> int:
    text = str(label or "").strip().upper()
    digits = "".join(char for char in text if char.isdigit())
    if digits:
        return max(0, min(periods_per_year - 1, int(digits) - 1))
    if text in {"FY", "ANNUAL", "ANNUEL"}:
        return 0
    return 0


def _period_label(period_index: int, periods_per_year: int) -> str:
    if periods_per_year == 4:
        return f"Q{int(period_index) + 1}"
    if periods_per_year == 2:
        return f"H{int(period_index) + 1}"
    return "FY"


def _period_end_date(fiscal_year: int, period_index: int, periods_per_year: int) -> str:
    month = int(12 / max(1, periods_per_year)) * (int(period_index) + 1)
    month = max(1, min(12, month))
    return dt.date(int(fiscal_year), month, calendar.monthrange(int(fiscal_year), month)[1]).isoformat()


def _parse_date(value: Any) -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _future_period_key(start_key: tuple[int, int], offset: int, periods_per_year: int) -> tuple[int, int]:
    periods = max(1, int(periods_per_year or 1))
    total = int(start_key[0]) * periods + int(start_key[1]) + int(offset)
    return total // periods, total % periods


def _period_projection_record(key: tuple[int, int], label: str, value: float) -> dict[str, Any]:
    return {
        "fiscal_year": int(key[0]),
        "period_index": int(key[1]),
        "period_label": label,
        "value": float(value),
    }


def _winsorized_peak_values(values: Iterable[float]) -> float | None:
    cleaned = sorted(float(value) for value in values if isfinite(float(value)))
    if not cleaned:
        return None
    index = min(len(cleaned) - 1, max(0, int(round((len(cleaned) - 1) * 0.90))))
    return cleaned[index]


def _pick_best_period_row(
    history: list[PeriodMetricRow],
    period_type: str,
    aliases: Iterable[str],
) -> dict[tuple[int, int], PeriodMetricRow]:
    alias_set = set(aliases)
    normalized_type = _normalize_period_type(period_type)
    periods_per_year = PERIODS_PER_YEAR_BY_TYPE.get(normalized_type, 1)
    candidates_by_period: dict[tuple[int, int], list[PeriodMetricRow]] = {}
    for row in history:
        if _normalize_period_type(row.period_type) != normalized_type:
            continue
        if row.metric_name not in alias_set:
            continue
        if _finite(row.metric_value) is None:
            continue
        key = (int(row.fiscal_year), _period_index_from_label(row.period_label, periods_per_year))
        candidates_by_period.setdefault(key, []).append(row)

    if not candidates_by_period:
        return {}

    period_meds: dict[tuple[int, int], float] = {}
    for key, rows in candidates_by_period.items():
        mags = [abs(float(row.metric_value)) for row in rows if _finite(row.metric_value) is not None]
        if mags:
            period_meds[key] = float(median(mags))
    series_med = float(median(list(period_meds.values()))) if period_meds else None

    selected: dict[tuple[int, int], PeriodMetricRow] = {}
    for key, rows in candidates_by_period.items():
        reference = period_meds.get(key) or series_med
        survivors: list[PeriodMetricRow] = []
        for row in rows:
            value = _finite(row.metric_value)
            if value is None:
                continue
            if reference is None or reference <= 0.0 or value == 0:
                survivors.append(row)
                continue
            mag = abs(value)
            ratio = mag / reference if mag >= reference else reference / mag
            if ratio <= 100.0:
                survivors.append(row)
            else:
                _log.warning(
                    "period_metric_resolver: outlier rejected %s/%s period=%s value=%g ref=%g",
                    row.metric_name,
                    row.symbol,
                    key,
                    value,
                    reference,
                )
        if not survivors:
            survivors = [min(rows, key=lambda r: abs(abs(_finite(r.metric_value) or 0.0) - (reference or 0.0)))]
        survivors.sort(
            key=lambda row: (
                0 if row.is_proxy else 1,
                (_parse_date(row.period_end_date) or dt.date.min).toordinal(),
                int(row.source_document_id or 0),
            ),
            reverse=True,
        )
        selected[key] = survivors[0]
    return selected


def _period_series(
    history: list[PeriodMetricRow],
    period_type: str,
    aliases: Iterable[str],
) -> list[tuple[tuple[int, int], float]]:
    by_period = _pick_best_period_row(history, period_type, aliases)
    return [(key, _float(row.metric_value, 0.0)) for key, row in sorted(by_period.items())]


def _period_yoy_growth_series(series: list[tuple[tuple[int, int], float]]) -> list[tuple[tuple[int, int], float]]:
    values = {key: value for key, value in series}
    out: list[tuple[tuple[int, int], float]] = []
    for key, value in sorted(values.items()):
        previous = values.get((key[0] - 1, key[1]))
        if previous is not None and previous > 0:
            out.append((key, value / previous - 1.0))
    return out


def _period_ratio_series(
    history: list[PeriodMetricRow],
    period_type: str,
    numerator_aliases: Iterable[str],
    denominator_aliases: Iterable[str],
    *,
    absolute_numerator: bool = False,
) -> list[tuple[tuple[int, int], float]]:
    numerator = dict(_period_series(history, period_type, numerator_aliases))
    denominator = dict(_period_series(history, period_type, denominator_aliases))
    out: list[tuple[tuple[int, int], float]] = []
    for key in sorted(set(numerator) & set(denominator)):
        den = denominator[key]
        if den == 0:
            continue
        num = abs(numerator[key]) if absolute_numerator else numerator[key]
        out.append((key, num / den))
    return out


def _period_working_capital_ratio_series(history: list[PeriodMetricRow], period_type: str) -> list[tuple[tuple[int, int], float]]:
    wc = dict(_period_series(history, period_type, WORKING_CAPITAL_ALIASES))
    if not wc:
        current_assets = dict(_period_series(history, period_type, CURRENT_ASSET_ALIASES))
        current_liabilities = dict(_period_series(history, period_type, CURRENT_LIABILITY_ALIASES))
        wc = {key: current_assets[key] - current_liabilities[key] for key in set(current_assets) & set(current_liabilities)}
    revenue = dict(_period_series(history, period_type, REVENUE_ALIASES))
    out: list[tuple[tuple[int, int], float]] = []
    for key in sorted(set(wc) & set(revenue)):
        if revenue[key] != 0:
            out.append((key, wc[key] / revenue[key]))
    return out


def _latest_period_working_capital(history: list[PeriodMetricRow], period_type: str) -> float | None:
    series = _period_series(history, period_type, WORKING_CAPITAL_ALIASES)
    if series:
        return float(series[-1][1])
    current_assets = dict(_period_series(history, period_type, CURRENT_ASSET_ALIASES))
    current_liabilities = dict(_period_series(history, period_type, CURRENT_LIABILITY_ALIASES))
    common = sorted(set(current_assets) & set(current_liabilities))
    if not common:
        return None
    key = common[-1]
    return current_assets[key] - current_liabilities[key]


def _period_tax_rate_series(history: list[PeriodMetricRow], period_type: str) -> list[tuple[tuple[int, int], float]]:
    taxes = dict(_period_series(history, period_type, TAX_ALIASES))
    net_income = dict(_period_series(history, period_type, NET_INCOME_ALIASES))
    out: list[tuple[tuple[int, int], float]] = []
    for key in sorted(set(taxes) & set(net_income)):
        tax = abs(taxes[key])
        pretax = net_income[key] + tax
        if pretax > 0:
            out.append((key, _clamp(tax / pretax, 0.0, 0.60)))
    return out


def _period_effective_tax_rate(history: list[PeriodMetricRow], period_type: str) -> float | None:
    series = _period_tax_rate_series(history, period_type)
    if not series:
        return None
    return float(mean([value for _key, value in series[-3:]]))


def _period_payout_ratio_series(history: list[PeriodMetricRow], period_type: str) -> list[tuple[tuple[int, int], float]]:
    dividends = dict(_period_series(history, period_type, DIVIDEND_ALIASES))
    net_income = dict(_period_series(history, period_type, NET_INCOME_ALIASES))
    out: list[tuple[tuple[int, int], float]] = []
    for key in sorted(set(dividends) & set(net_income)):
        if net_income[key] > 0:
            out.append((key, _clamp(abs(dividends[key]) / net_income[key], 0.0, 0.95)))
    return out


def _latest_period_or_annual_or_snapshot(
    period_history: list[PeriodMetricRow],
    annual_history: list[AnnualMetricRow],
    snapshot: FundamentalSnapshot,
    period_type: str,
    aliases: Iterable[str],
) -> float | None:
    series = _period_series(period_history, period_type, aliases)
    if series:
        return float(series[-1][1])
    return _latest_or_snapshot(annual_history, snapshot, aliases)


def _apply_override_period_series(
    name: str,
    values: list[float],
    start_key: tuple[int, int],
    periods_per_year: int,
    overrides: Mapping[str, Any],
) -> list[float]:
    raw = overrides.get(name)
    if raw is None:
        return values
    out = list(values)
    if isinstance(raw, Mapping):
        for index in range(len(out)):
            key = _future_period_key(start_key, index + 1, periods_per_year)
            label = _period_label(key[1], periods_per_year)
            candidates = (
                key,
                f"{key[0]}:{label}",
                f"{key[0]}-{label}",
                f"{key[0]}:{key[1]}",
                str(index),
                index,
                str(key[0]),
                key[0],
            )
            for candidate in candidates:
                if candidate in raw:
                    out[index] = _float(raw[candidate], out[index])
                    break
    elif isinstance(raw, (list, tuple)):
        for index, value in enumerate(raw[: len(out)]):
            out[index] = _float(value, out[index])
    else:
        out = [_float(raw, value) for value in out]
    return out


def _year_map_from_period_path(period_keys: list[tuple[int, int]], values: list[float]) -> dict[int, float]:
    out: dict[int, float] = {}
    for key, value in zip(period_keys, values):
        out[int(key[0])] = float(value)
    return out


def _period_series_to_dict(series: list[tuple[tuple[int, int], float]], periods_per_year: int) -> list[dict[str, Any]]:
    return [
        {
            "year": int(key[0]),
            "fiscal_year": int(key[0]),
            "period_index": int(key[1]),
            "period_label": _period_label(key[1], periods_per_year),
            "value": float(value),
        }
        for key, value in series
    ]


def available_horizons(period_history: list[PeriodMetricRow], *, min_same_period_observations: int = MIN_SAME_PERIOD_OBSERVATIONS) -> set[str]:
    available = {"year"}
    for horizon, period_type in (("semester", "semiannual"), ("quarter", "quarterly")):
        periods = PERIODS_PER_YEAR_BY_TYPE[period_type]
        by_period = _pick_best_period_row(period_history, period_type, REVENUE_ALIASES)
        counts = {index: 0 for index in range(periods)}
        for _year, index in by_period:
            counts[index] = counts.get(index, 0) + 1
        if counts and all(count >= min_same_period_observations for count in counts.values()):
            available.add(horizon)
    return available


def resolve_horizon_period_type(requested_horizon: str, available: set[str]) -> tuple[str, str, list[str]]:
    requested = str(requested_horizon or "year").strip().lower()
    if requested not in HORIZON_PERIOD_TYPE:
        requested = "year"
    order = {
        "quarter": ["quarter", "semester", "year"],
        "semester": ["semester", "year"],
        "year": ["year"],
    }[requested]
    warnings: list[str] = []
    for horizon in order:
        if horizon in available:
            if horizon != requested:
                warnings.append(f"horizon_downgraded_{requested}_to_{horizon}")
            return horizon, HORIZON_PERIOD_TYPE[horizon], warnings
    return "year", "annual", [f"horizon_downgraded_{requested}_to_year"]


def _series(history: list[AnnualMetricRow], aliases: Iterable[str]) -> list[tuple[int, float]]:
    by_year = _pick_best_row_per_year(history, aliases)
    return [(yr, _float(row.metric_value, 0.0)) for yr, row in sorted(by_year.items())]


def _latest_value(series: list[tuple[int, float]]) -> float:
    return float(series[-1][1])


def _latest_or_none(series: list[tuple[int, float]]) -> float | None:
    return float(series[-1][1]) if series else None


def _latest_or_snapshot(history: list[AnnualMetricRow], snapshot: FundamentalSnapshot, aliases: Iterable[str]) -> float | None:
    series = _series(history, aliases)
    if series:
        return float(series[-1][1])
    return _snapshot_value(snapshot, aliases)


def _growth_series(series: list[tuple[int, float]]) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    for (year, value), (_prev_year, previous) in zip(series[1:], series[:-1]):
        if previous > 0:
            out.append((year, value / previous - 1.0))
    return out


def _winsorized_peak_growth(growth_series: list[tuple[int, float]]) -> float | None:
    values = sorted(float(value) for _year, value in growth_series if isfinite(float(value)))
    if not values:
        return None
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * 0.90))))
    return values[index]


def _cagr(series: list[tuple[int, float]], *, periods: int) -> float | None:
    if len(series) < 2:
        return None
    selected = series[-(periods + 1) :]
    first_year, first = selected[0]
    last_year, last = selected[-1]
    elapsed = max(1, last_year - first_year)
    if first <= 0 or last <= 0:
        return None
    return last ** (1.0 / elapsed) / first ** (1.0 / elapsed) - 1.0


def _ratio_series(
    history: list[AnnualMetricRow],
    numerator_aliases: Iterable[str],
    denominator_aliases: Iterable[str],
    *,
    absolute_numerator: bool = False,
) -> list[tuple[int, float]]:
    numerator = dict(_series(history, numerator_aliases))
    denominator = dict(_series(history, denominator_aliases))
    out: list[tuple[int, float]] = []
    for year in sorted(set(numerator) & set(denominator)):
        den = denominator[year]
        if den == 0:
            continue
        num = abs(numerator[year]) if absolute_numerator else numerator[year]
        out.append((year, num / den))
    return out


def _working_capital_ratio_series(history: list[AnnualMetricRow]) -> list[tuple[int, float]]:
    wc = dict(_series(history, WORKING_CAPITAL_ALIASES))
    if not wc:
        current_assets = dict(_series(history, CURRENT_ASSET_ALIASES))
        current_liabilities = dict(_series(history, CURRENT_LIABILITY_ALIASES))
        wc = {year: current_assets[year] - current_liabilities[year] for year in set(current_assets) & set(current_liabilities)}
    revenue = dict(_series(history, REVENUE_ALIASES))
    out: list[tuple[int, float]] = []
    for year in sorted(set(wc) & set(revenue)):
        if revenue[year] != 0:
            out.append((year, wc[year] / revenue[year]))
    return out


def _latest_working_capital(history: list[AnnualMetricRow]) -> float | None:
    series = _series(history, WORKING_CAPITAL_ALIASES)
    if series:
        return float(series[-1][1])
    current_assets = dict(_series(history, CURRENT_ASSET_ALIASES))
    current_liabilities = dict(_series(history, CURRENT_LIABILITY_ALIASES))
    common = sorted(set(current_assets) & set(current_liabilities))
    if not common:
        return None
    year = common[-1]
    return current_assets[year] - current_liabilities[year]


def _tax_rate_series(history: list[AnnualMetricRow]) -> list[tuple[int, float]]:
    taxes = dict(_series(history, TAX_ALIASES))
    net_income = dict(_series(history, NET_INCOME_ALIASES))
    out: list[tuple[int, float]] = []
    for year in sorted(set(taxes) & set(net_income)):
        tax = abs(taxes[year])
        pretax = net_income[year] + tax
        if pretax > 0:
            out.append((year, _clamp(tax / pretax, 0.0, 0.60)))
    return out


def _effective_tax_rate(history: list[AnnualMetricRow]) -> float | None:
    series = _tax_rate_series(history)
    if not series:
        return None
    return float(mean([value for _year, value in series[-3:]]))


def _payout_ratio_series(history: list[AnnualMetricRow]) -> list[tuple[int, float]]:
    dividends = dict(_series(history, DIVIDEND_ALIASES))
    net_income = dict(_series(history, NET_INCOME_ALIASES))
    out: list[tuple[int, float]] = []
    for year in sorted(set(dividends) & set(net_income)):
        if net_income[year] > 0:
            out.append((year, _clamp(abs(dividends[year]) / net_income[year], 0.0, 0.95)))
    return out


def _trailing_average(series: list[tuple[int, float]], *, default: float) -> float:
    values = [float(value) for _year, value in series[-3:] if isfinite(float(value))]
    return float(mean(values)) if values else default


def _peer_driver_medians(assumptions: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = assumptions.get("_peer_driver_medians")
    return raw if isinstance(raw, Mapping) else {}


def _peer_driver_value(peer_medians: Mapping[str, Any], name: str) -> float | None:
    raw = peer_medians.get(name)
    if isinstance(raw, Mapping):
        raw = raw.get("median")
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def _trailing_or_peer(
    series: list[tuple[int, float]],
    *,
    peer_value: float | None,
    unavailable_warning: str,
) -> tuple[float, str | None]:
    values = [float(value) for _year, value in series[-3:] if isfinite(float(value))]
    if values:
        return float(mean(values)), None
    if peer_value is not None:
        return peer_value, None
    return float("nan"), unavailable_warning


def _fade_path(start: float, end: float, years: int) -> list[float]:
    if years <= 1:
        return [float(start)]
    return [float(start + (end - start) * index / (years - 1)) for index in range(years)]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _apply_override_series(name: str, values: list[float], start_year: int, overrides: Mapping[str, Any]) -> list[float]:
    raw = overrides.get(name)
    if raw is None:
        return values
    out = list(values)
    if isinstance(raw, Mapping):
        for index in range(len(out)):
            year = start_year + index + 1
            if year in raw:
                out[index] = _float(raw[year], out[index])
            elif str(year) in raw:
                out[index] = _float(raw[str(year)], out[index])
            elif index in raw:
                out[index] = _float(raw[index], out[index])
            elif str(index) in raw:
                out[index] = _float(raw[str(index)], out[index])
    elif isinstance(raw, (list, tuple)):
        for index, value in enumerate(raw[: len(out)]):
            out[index] = _float(value, out[index])
    else:
        out = [_float(raw, value) for value in out]
    return out


def _divergence(value: float, anchor: float | None, *, name: str, absolute_band: float = 0.03) -> tuple[float | None, str | None]:
    if anchor is None:
        return None, None
    gap = value - anchor
    band = max(absolute_band, abs(anchor) * 0.5)
    if abs(gap) <= band:
        return gap, None
    return gap, f"{name}_diverges_from_history"


def _book_equity_proxy(snapshot: FundamentalSnapshot) -> float | None:
    market_cap = _snapshot_value(snapshot, ("MarketCap_Calc",))
    pb = _snapshot_value(snapshot, ("Price_to_Book",))
    if market_cap is not None and pb is not None and pb > 0:
        return market_cap / pb
    return None


def _year_map(years: list[int], values: list[float]) -> dict[int, float]:
    return {int(year): float(value) for year, value in zip(years, values)}


def _series_to_dict(series: list[tuple[int, float]]) -> list[dict[str, float | int]]:
    return [{"year": int(year), "value": float(value)} for year, value in series]


def _status(delta: float, base: float) -> str:
    rel = abs(_rel(delta, base) or 0.0)
    if rel <= 0.005:
        return "pass"
    if rel <= 0.02:
        return "warn"
    return "fail"


def _diagnostic_status(delta: float, base: float) -> str:
    rel = abs(_rel(delta, base) or 0.0)
    if rel <= 0.005:
        return "pass"
    return "warn"


def _rel(delta: float, base: float) -> float:
    return delta / max(abs(base), 1.0)


def _complete_projected_balance_sheet(
    *,
    total_assets_before_plug: float,
    total_liabilities_before_plug: float,
    total_equity: float,
) -> dict[str, float]:
    pre_gap = total_assets_before_plug - (total_liabilities_before_plug + total_equity)
    other_liabilities_adjustment = pre_gap
    other_asset_adjustment = 0.0
    total_liabilities = total_liabilities_before_plug + other_liabilities_adjustment
    total_assets = total_assets_before_plug
    if total_liabilities < 0.0:
        other_liabilities_adjustment = -total_liabilities_before_plug
        total_liabilities = 0.0
        remaining_gap = total_assets - (total_liabilities + total_equity)
        if remaining_gap < 0.0:
            other_asset_adjustment = -remaining_gap
            total_assets += other_asset_adjustment
    total_liabilities_and_equity = total_liabilities + total_equity
    post_delta = total_assets - total_liabilities_and_equity
    return {
        "total_assets": total_assets,
        "total_assets_before_plug": total_assets_before_plug,
        "total_liabilities": total_liabilities,
        "total_liabilities_before_plug": total_liabilities_before_plug,
        "total_liabilities_and_equity": total_liabilities_and_equity,
        "total_liabilities_and_equity_before_plug": total_liabilities_before_plug + total_equity,
        "projection_bs_pre_plug_delta": pre_gap,
        "projection_bs_post_plug_delta": post_delta,
        "balance_sheet_plug": pre_gap,
        "projected_other_liabilities_adjustment": other_liabilities_adjustment,
        "projected_other_asset_adjustment": other_asset_adjustment,
        "other_equity_adjustment": 0.0,
    }


def _margin_hierarchy_check(statement: dict[str, Any], period_suffix: str) -> IntegrityCheck:
    revenue = _float(statement.get("revenue"), 0.0)
    if revenue <= 0:
        return IntegrityCheck(
            name=f"projection_margin_hierarchy_{period_suffix}",
            status="unavailable",
            delta=None,
            rel_delta=None,
            inputs={"Revenue": revenue},
            message="margin hierarchy unavailable without positive revenue",
        )
    gross = _float(statement.get("gross_profit"), 0.0) / revenue
    ebitda = _float(statement.get("ebitda"), 0.0) / revenue
    ebit = _float(statement.get("ebit"), 0.0) / revenue
    net = _float(statement.get("net_income"), 0.0) / revenue
    ok = gross + 1e-9 >= ebitda >= ebit - 1e-9 and ebit >= net - 1e-9
    return IntegrityCheck(
        name=f"projection_margin_hierarchy_{period_suffix}",
        status="pass" if ok else "warn",
        delta=None,
        rel_delta=None,
        inputs={"Gross_Margin": gross, "EBITDA_Margin": ebitda, "EBIT_Margin": ebit, "Net_Margin": net},
        message=None if ok else "gross >= EBITDA >= EBIT >= net margin hierarchy violated",
    )
