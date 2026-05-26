from __future__ import annotations

import datetime as dt
import logging
import unicodedata
import uuid
from collections import Counter, defaultdict
from dataclasses import replace
from math import isfinite
from typing import Any, Callable, Literal

from sqlalchemy.orm import Session

from core.quant_core.fundamentals import (
    DEFAULT_ASSUMPTIONS,
    compute_default_sensitivity_grids,
    compute_sensitivity,
    compute_symbol_valuations,
    compute_valuation_ensemble,
    default_assumptions_for_scenario,
    parse_fundamental_workbook,
    resolve_assumptions,
    score_fundamental_snapshots,
)
from core.quant_core.fundamentals.integrity import build_integrity_report, report_from_dict, report_to_dict
from core.quant_core.fundamentals.domain import (
    AnnualMetricRow,
    FundamentalQualityIssue,
    FundamentalSnapshot,
    FundamentalWorkbook,
    IntegrityReport,
    PeriodMetricRow,
)
from core.quant_core.fundamentals.trends import PILLAR_KEYS, classify_all_pillar_trends

from .. import models
from ..json_sanitize import sanitize_json_compatible


METHODOLOGY_VERSION = "v3"
SUCCEEDED_IMPORT_STATUSES = ("succeeded", "partial")
FundamentalScope = Literal["masi", "non_masi", "all"]
VALUATION_SCENARIOS = ("bear", "base", "bull")
AssumptionOverrideLoader = Callable[[str, str], dict[str, float] | None]
logger = logging.getLogger(__name__)


# Casablanca/BVC publications and legacy workbooks sometimes use older market
# mnemonics while stock_master keeps the current app ticker.
FUNDAMENTAL_SYMBOL_ALIASES = {
    "DISTY": "DYT",
    "SNA": "SAH",
    "ZCO": "ZDJ",
    "SNE": "SNP",
    "SGTM": "GTM",
}

FUNDAMENTAL_COMPANY_SYMBOL_ALIASES = {
    "DISTY TECHNOLOGIES": "DYT",
    "SANLAM MAROC": "SAH",
    "SAHAM ASSURANCE": "SAH",
    "STOKVIS NORD AFRIQUE": "SNA",
    "ZELLIDJA": "ZDJ",
    "ZELLIDJA S.A": "ZDJ",
    "SOCIETE NATIONALE D'ELECTROLYSE ET DE PETROCHIMIE": "SNP",
    "SNEP": "SNP",
    "SOCIETE GENERALE DES TRAVAUX DU MAROC": "GTM",
    "SGTM": "GTM",
    "IB MAROC.COM SA": "IBC",
    "IB MAROC": "IBC",
}

PRICE_DERIVED_METRICS = (
    "Current_Price",
    "Shares_Outstanding",
    "MarketCap_Calc",
    "PER",
    "Price_to_Book",
    "Price_to_Sales",
    "Dividend_Yield",
    "FCF_Yield",
    "EnterpriseValue",
    "EV_to_EBITDA",
)

NON_STOCK_SYMBOLS = {"INSTRUMENT", "MAJ", "MAJJ", "WORKSHEET"}


def derive_recommendation(ensemble: models.FundamentalEnsembleResult | None) -> str | None:
    """Map valuation upside and confidence to a research-style BUY/HOLD/SELL label."""

    if ensemble is None:
        return None
    upside = _num(ensemble.upside_pct)
    confidence = _num(ensemble.confidence_score)
    usable_models = max(0, int(ensemble.usable_model_count or 0))
    if upside is None or confidence is None or usable_models <= 0:
        return None
    is_confident = confidence is not None and confidence >= 0.45
    if upside is not None and upside > 0.12 and is_confident:
        return "BUY"
    if upside is not None and upside < -0.10 and is_confident:
        return "SELL"
    return "HOLD"


def derive_conviction(ensemble: models.FundamentalEnsembleResult | None) -> int:
    """Conviction is a 1-5 ladder from confidence and model breadth."""

    if ensemble is None:
        return 0
    confidence = _num(ensemble.confidence_score) or 0.0
    model_count = max(0, int(ensemble.usable_model_count or 0))
    if confidence <= 0 or model_count <= 0:
        return 0
    raw = round(confidence * model_count / 7.0 * 5.0)
    return max(1, min(5, int(raw)))


def derive_revision_direction(
    db: Session,
    *,
    symbol: str,
    scenario: str,
    current_import_id: uuid.UUID | None,
    target_price: float | None,
) -> str:
    """Compare the target price with the previous available import for the same symbol."""

    current_target = _positive_num(target_price)
    if current_target is None:
        return "="
    rows = (
        db.query(models.FundamentalEnsembleResult, models.FundamentalImport)
        .join(models.FundamentalImport, models.FundamentalEnsembleResult.import_id == models.FundamentalImport.id)
        .filter(
            models.FundamentalEnsembleResult.symbol == symbol.upper(),
            models.FundamentalEnsembleResult.scenario == scenario,
            models.FundamentalEnsembleResult.fair_value_base.isnot(None),
            models.FundamentalImport.status.in_(SUCCEEDED_IMPORT_STATUSES),
        )
        .order_by(
            models.FundamentalImport.completed_at.desc().nullslast(),
            models.FundamentalImport.imported_at.desc().nullslast(),
            models.FundamentalImport.created_at.desc(),
        )
        .limit(8)
        .all()
    )
    previous_target = None
    for ensemble, _import_row in rows:
        if current_import_id is not None and ensemble.import_id == current_import_id:
            continue
        previous_target = _positive_num(ensemble.fair_value_base)
        if previous_target is not None:
            break
    if previous_target is None:
        return "="
    change = current_target / previous_target - 1.0
    if change > 0.02:
        return "up"
    if change < -0.02:
        return "down"
    return "="


def derive_research_overlay(
    db: Session,
    *,
    symbol: str,
    scenario: str,
    ensemble: models.FundamentalEnsembleResult | None,
    import_row: models.FundamentalImport | None,
    free_float_pct: float | None = None,
) -> dict[str, Any]:
    target_price = _num(ensemble.fair_value_base) if ensemble is not None else None
    as_of = None
    if ensemble is not None and ensemble.computed_at is not None:
        as_of = ensemble.computed_at.date().isoformat()
    elif import_row is not None:
        when = import_row.completed_at or import_row.imported_at or import_row.created_at
        as_of = when.date().isoformat() if when else None
    return {
        "recommendation": derive_recommendation(ensemble),
        "target_price": target_price,
        "conviction": derive_conviction(ensemble),
        "revision_direction": derive_revision_direction(
            db,
            symbol=symbol,
            scenario=scenario,
            current_import_id=ensemble.import_id if ensemble is not None else import_row.id if import_row is not None else None,
            target_price=target_price,
        ),
        "analyst": "Systeme quantitatif",
        "as_of_date": as_of,
        "free_float_pct": free_float_pct,
    }


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _date_or_none(value: Any) -> dt.date | None:
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


def _stock_master_symbols(db: Session) -> set[str]:
    rows = db.query(models.StockMaster.symbol).all()
    return {str(row[0]).strip().upper() for row in rows if row[0] and str(row[0]).strip().upper() not in NON_STOCK_SYMBOLS}


def _normalize_company_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.strip().upper().replace(".", " ").split())


def _canonical_symbol_for_mapping(mapping: CompanyMapping, existing_symbols: set[str]) -> str | None:
    symbol = str(mapping.symbol or "").strip().upper()
    company_candidates = (
        _normalize_company_key(mapping.company_name),
        _normalize_company_key(mapping.mapped_company_name),
        _normalize_company_key(mapping.canonical_company_name),
    )
    for company in company_candidates:
        aliased = FUNDAMENTAL_COMPANY_SYMBOL_ALIASES.get(company)
        if aliased in existing_symbols:
            return aliased

    if symbol in existing_symbols:
        return symbol
    aliased = FUNDAMENTAL_SYMBOL_ALIASES.get(symbol)
    if aliased in existing_symbols:
        return aliased
    return symbol or None


def _canonicalize_workbook_symbols(
    parsed: FundamentalWorkbook,
    *,
    existing_symbols: set[str],
) -> FundamentalWorkbook:
    canonical_by_original: dict[str, str] = {}
    canonical_by_company: dict[str, str] = {}
    mappings: list[CompanyMapping] = []

    for mapping in parsed.mappings:
        canonical = _canonical_symbol_for_mapping(mapping, existing_symbols)
        if mapping.symbol and canonical:
            canonical_by_original[str(mapping.symbol).strip().upper()] = canonical
        canonical_by_company[_normalize_company_key(mapping.company_name)] = canonical or ""
        if mapping.mapped_company_name:
            canonical_by_company[_normalize_company_key(mapping.mapped_company_name)] = canonical or ""
        mappings.append(
            replace(
                mapping,
                symbol=canonical,
                score_note=(
                    f"{mapping.score_note or ''}; canonicalized from {mapping.symbol}".strip("; ")
                    if canonical and mapping.symbol and canonical != str(mapping.symbol).strip().upper()
                    else mapping.score_note
                ),
            )
        )

    def canonical_for_row(symbol: str, company_name: str) -> str:
        raw = str(symbol or "").strip().upper()
        company_canonical = canonical_by_company.get(_normalize_company_key(company_name))
        if company_canonical:
            return company_canonical
        return (
            canonical_by_original.get(raw)
            or FUNDAMENTAL_SYMBOL_ALIASES.get(raw)
            or raw
        )

    annual_best: dict[tuple[str, int, str], AnnualMetricRow] = {}
    for row in parsed.annual_metrics:
        canonical = canonical_for_row(row.symbol, row.company_name)
        updated = replace(row, symbol=canonical)
        key = (updated.symbol, updated.statement_year, updated.metric_name)
        if key not in annual_best or (annual_best[key].metric_value is None and updated.metric_value is not None):
            annual_best[key] = updated

    period_best: dict[tuple[str, int, str, str, str], PeriodMetricRow] = {}
    for row in parsed.period_metrics:
        canonical = canonical_for_row(row.symbol, row.company_name)
        updated = replace(row, symbol=canonical)
        key = (updated.symbol, updated.fiscal_year, updated.period_type, updated.period_label, updated.metric_name)
        if key not in period_best or (period_best[key].metric_value is None and updated.metric_value is not None):
            period_best[key] = updated

    snapshot_best: dict[str, tuple[tuple[int, int], FundamentalSnapshot]] = {}
    for snapshot in parsed.latest_snapshots:
        canonical = canonical_for_row(snapshot.symbol, snapshot.company_name)
        updated = replace(snapshot, symbol=canonical)
        metric_count = sum(value is not None for value in updated.metrics.values())
        key = (updated.latest_statement_year or -1, metric_count)
        if canonical not in snapshot_best or key > snapshot_best[canonical][0]:
            snapshot_best[canonical] = (key, updated)

    quality_issues = []
    for issue in parsed.quality_issues:
        if issue.symbol:
            canonical = FUNDAMENTAL_SYMBOL_ALIASES.get(str(issue.symbol).strip().upper(), str(issue.symbol).strip().upper())
            quality_issues.append(replace(issue, symbol=canonical))
        else:
            quality_issues.append(issue)

    summary = dict(parsed.summary or {})
    canonicalized = sorted(
        {
            f"{raw}->{canonical}"
            for raw, canonical in canonical_by_original.items()
            if raw != canonical
        }
    )
    if canonicalized:
        summary["canonicalized_symbol_aliases"] = canonicalized

    return FundamentalWorkbook(
        mappings=mappings,
        annual_metrics=sorted(annual_best.values(), key=lambda item: (item.symbol, item.statement_year, item.metric_name)),
        latest_snapshots=sorted((item for _key, item in snapshot_best.values()), key=lambda item: item.symbol),
        summary=summary,
        quality_issues=quality_issues,
        period_metrics=sorted(
            period_best.values(),
            key=lambda item: (item.symbol, item.fiscal_year, item.period_type, item.period_label, item.metric_name),
        ),
    )


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _positive_num(value: Any) -> float | None:
    out = _num(value)
    return out if out is not None and out > 0 else None


def _safe_ratio(numerator: Any, denominator: Any) -> float | None:
    num = _num(numerator)
    den = _positive_num(denominator)
    if num is None or den is None:
        return None
    return num / den


def _as_percent(value: float | None) -> float | None:
    return None if value is None else value * 100.0


def _latest_history_metric(history: list[AnnualMetricRow], *metric_names: str) -> float | None:
    names = set(metric_names)
    rows = [
        row
        for row in history
        if row.metric_name in names and row.metric_value is not None
    ]
    if not rows:
        return None
    return _num(sorted(rows, key=lambda row: row.statement_year)[-1].metric_value)


def _snapshot_metric(metrics: dict[str, Any], *metric_names: str) -> float | None:
    for metric_name in metric_names:
        value = _num(metrics.get(metric_name))
        if value is not None:
            return value
    return None


def _market_price_context_by_symbol(db: Session, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
    wanted = sorted({str(symbol).strip().upper() for symbol in symbols if symbol})
    if not wanted:
        return {}

    context: dict[str, dict[str, Any]] = {symbol: {} for symbol in wanted}
    stock_rows = (
        db.query(models.StockMaster)
        .filter(models.StockMaster.symbol.in_(wanted))
        .all()
    )
    for stock in stock_rows:
        symbol = str(stock.symbol).strip().upper()
        context.setdefault(symbol, {})
        shares = _positive_num(stock.shares_outstanding)
        if shares is not None:
            context[symbol].update(
                {
                    "shares_outstanding": shares,
                    "shares_source": stock.shares_source,
                    "shares_as_of": stock.shares_as_of.isoformat() if stock.shares_as_of else None,
                }
            )

    market_rows = (
        db.query(models.MarketDataStore)
        .filter(
            models.MarketDataStore.symbol.in_(wanted),
            models.MarketDataStore.timeframe.in_(("1D", "1d")),
        )
        .all()
    )
    best_market: dict[str, models.MarketDataStore] = {}
    for row in market_rows:
        symbol = str(row.symbol).strip().upper()
        price = _positive_num(row.close_last)
        if price is None:
            continue
        current_best = best_market.get(symbol)
        if current_best is None:
            best_market[symbol] = row
            continue
        row_date = row.data_as_of or (row.end_ts.date() if row.end_ts else None)
        best_date = current_best.data_as_of or (current_best.end_ts.date() if current_best.end_ts else None)
        if best_date is None or (row_date is not None and row_date > best_date):
            best_market[symbol] = row

    for symbol, row in best_market.items():
        context.setdefault(symbol, {})
        price_as_of = row.data_as_of.isoformat() if row.data_as_of else row.end_ts.date().isoformat() if row.end_ts else None
        context[symbol].update(
            {
                "current_price": _positive_num(row.close_last),
                "price_as_of": price_as_of,
                "price_source": "market_data_store",
                "price_source_provider": row.source_provider,
                "price_timeframe": row.timeframe,
            }
        )

    return context


def _history_by_symbol_for_snapshot_rows(
    db: Session,
    snapshot_rows: Iterable[models.FundamentalLatestSnapshot],
) -> dict[str, list[AnnualMetricRow]]:
    by_import: dict[uuid.UUID, list[str]] = defaultdict(list)
    for row in snapshot_rows:
        by_import[row.import_id].append(str(row.symbol).upper())

    out: dict[str, list[AnnualMetricRow]] = defaultdict(list)
    for import_id, symbols in by_import.items():
        query = db.query(models.FundamentalAnnualMetric).filter(
            models.FundamentalAnnualMetric.import_id == import_id,
            models.FundamentalAnnualMetric.symbol.in_(symbols),
        )
        for row in query.order_by(
            models.FundamentalAnnualMetric.symbol.asc(),
            models.FundamentalAnnualMetric.statement_year.asc(),
            models.FundamentalAnnualMetric.metric_name.asc(),
        ).all():
            out[str(row.symbol).upper()].append(_annual_from_model(row))
    return out


def _enrich_snapshot_with_market_data(
    snapshot: FundamentalSnapshot,
    *,
    price_context: dict[str, Any] | None,
    history: list[AnnualMetricRow],
) -> FundamentalSnapshot:
    context = price_context or {}
    metrics = dict(snapshot.metrics or {})
    coverage = dict(snapshot.coverage or {})
    source = dict(snapshot.source or {})
    derived: list[str] = []

    app_price = _positive_num(context.get("current_price"))
    if app_price is not None:
        metrics["Current_Price"] = app_price
        derived.append("Current_Price")

    shares = _positive_num(context.get("shares_outstanding")) or _positive_num(metrics.get("Shares_Outstanding"))
    if shares is not None:
        metrics["Shares_Outstanding"] = shares
        derived.append("Shares_Outstanding")

    market_cap = app_price * shares if app_price is not None and shares is not None else _positive_num(metrics.get("MarketCap_Calc"))
    if market_cap is not None:
        metrics["MarketCap_Calc"] = market_cap
        derived.append("MarketCap_Calc")

    revenue = _latest_history_metric(history, "Chiffre_daffaires", "Revenue", "Clean_Chiffre_daffaires")
    if revenue is None:
        revenue = _snapshot_metric(metrics, "Chiffre_daffaires", "Revenue", "Clean_Chiffre_daffaires")
    net_income = _latest_history_metric(history, "Resultat_net", "NetIncome", "Clean_Resultat_net")
    if net_income is None:
        net_income = _snapshot_metric(metrics, "Resultat_net", "NetIncome", "Clean_Resultat_net")
    total_equity = _latest_history_metric(history, "Total_Equity", "Equity", "Capitaux_propres", "Clean_Capitaux_propres")
    if total_equity is None:
        total_equity = _snapshot_metric(metrics, "Total_Equity", "Equity", "Capitaux_propres", "Clean_Capitaux_propres")
    free_cash_flow = _latest_history_metric(history, "Free_Cash_Flow")
    if free_cash_flow is None:
        free_cash_flow = _snapshot_metric(metrics, "Free_Cash_Flow")
    dividends = _latest_history_metric(history, "Dividendes", "Dividends_Paid", "Clean_Dividendes")
    if dividends is None:
        dividends = _snapshot_metric(metrics, "Dividendes", "Dividends_Paid", "Clean_Dividendes")
    total_debt = _latest_history_metric(history, "Total_Debt", "Debt_Total")
    if total_debt is None:
        total_debt = _snapshot_metric(metrics, "Total_Debt", "Debt_Total")
    cash = _latest_history_metric(history, "Cash", "Cash_and_Equivalents")
    if cash is None:
        cash = _snapshot_metric(metrics, "Cash", "Cash_and_Equivalents")
    ebitda = _latest_history_metric(history, "EBITDA")
    if ebitda is None:
        ebitda = _snapshot_metric(metrics, "EBITDA")

    if market_cap is not None:
        per = _safe_ratio(market_cap, net_income if net_income is not None and net_income > 0 else None)
        if per is not None:
            metrics["PER"] = per
            derived.append("PER")

        price_to_book = _safe_ratio(market_cap, total_equity)
        if price_to_book is not None:
            metrics["Price_to_Book"] = price_to_book
            derived.append("Price_to_Book")

        price_to_sales = _safe_ratio(market_cap, revenue)
        if price_to_sales is not None:
            metrics["Price_to_Sales"] = price_to_sales
            derived.append("Price_to_Sales")

        fcf_yield = _safe_ratio(free_cash_flow, market_cap)
        if fcf_yield is not None:
            metrics["FCF_Yield"] = _as_percent(fcf_yield)
            derived.append("FCF_Yield")

        dividend_yield = _safe_ratio(dividends, market_cap)
        if dividend_yield is not None:
            metrics["Dividend_Yield"] = _as_percent(dividend_yield)
            derived.append("Dividend_Yield")

        net_debt = None
        if total_debt is not None and cash is not None:
            net_debt = total_debt - cash
        elif total_debt is not None:
            net_debt = total_debt
        if net_debt is not None:
            enterprise_value = market_cap + net_debt
            metrics["EnterpriseValue"] = enterprise_value
            derived.append("EnterpriseValue")
            ev_to_ebitda = _safe_ratio(enterprise_value, ebitda)
            if ev_to_ebitda is not None:
                metrics["EV_to_EBITDA"] = ev_to_ebitda
                derived.append("EV_to_EBITDA")

    price_lineage = {
        "current_price": app_price,
        "price_as_of": context.get("price_as_of"),
        "price_source": context.get("price_source"),
        "price_source_provider": context.get("price_source_provider"),
        "price_timeframe": context.get("price_timeframe"),
        "shares_outstanding": shares,
        "shares_source": context.get("shares_source"),
        "shares_as_of": context.get("shares_as_of"),
        "derived_metrics": sorted(set(derived)),
    }
    coverage.update(
        {
            "has_current_price": metrics.get("Current_Price") is not None,
            "has_market_cap": metrics.get("MarketCap_Calc") is not None,
            "has_shares_outstanding": metrics.get("Shares_Outstanding") is not None,
            "price_as_of": context.get("price_as_of"),
            "price_source": context.get("price_source"),
            "price_source_provider": context.get("price_source_provider"),
            "price_derived_metrics": sorted(set(derived)),
            "metric_count": sum(value is not None for value in metrics.values()),
        }
    )
    source["price_lineage"] = price_lineage
    return replace(snapshot, metrics=metrics, coverage=coverage, source=source)


def _enrich_workbook_with_market_data(db: Session, parsed: FundamentalWorkbook) -> FundamentalWorkbook:
    symbols = [snapshot.symbol for snapshot in parsed.latest_snapshots]
    price_context = _market_price_context_by_symbol(db, symbols)
    history_by_symbol: dict[str, list[AnnualMetricRow]] = defaultdict(list)
    for row in parsed.annual_metrics:
        history_by_symbol[str(row.symbol).upper()].append(row)
    snapshots = [
        _enrich_snapshot_with_market_data(
            snapshot,
            price_context=price_context.get(str(snapshot.symbol).upper()),
            history=history_by_symbol.get(str(snapshot.symbol).upper(), []),
        )
        for snapshot in parsed.latest_snapshots
    ]
    summary = dict(parsed.summary or {})
    summary["market_price_enriched_symbol_count"] = sum(
        1 for snapshot in snapshots if snapshot.coverage.get("price_source") == "market_data_store"
    )
    return replace(parsed, latest_snapshots=snapshots, summary=summary)


def enriched_snapshots_by_symbol(
    db: Session,
    snapshot_rows: dict[str, models.FundamentalLatestSnapshot] | Iterable[models.FundamentalLatestSnapshot],
) -> dict[str, FundamentalSnapshot]:
    if isinstance(snapshot_rows, dict):
        rows = list(snapshot_rows.values())
    else:
        rows = list(snapshot_rows)
    symbols = [str(row.symbol).upper() for row in rows]
    price_context = _market_price_context_by_symbol(db, symbols)
    history_by_symbol = _history_by_symbol_for_snapshot_rows(db, rows)
    return {
        str(row.symbol).upper(): _enrich_snapshot_with_market_data(
            _snapshot_from_model(row),
            price_context=price_context.get(str(row.symbol).upper()),
            history=history_by_symbol.get(str(row.symbol).upper(), []),
        )
        for row in rows
    }


def lightweight_enriched_snapshots_by_symbol(
    db: Session,
    snapshot_rows: dict[str, models.FundamentalLatestSnapshot] | Iterable[models.FundamentalLatestSnapshot],
) -> dict[str, FundamentalSnapshot]:
    """Enrich current price/share fields without loading annual history.

    This is intended for list/read surfaces where the UI only needs current
    price, market cap, coverage, scores, and valuation summaries. Full detail
    endpoints should continue using enriched_snapshots_by_symbol so ratios that
    depend on annual history stay available.
    """

    if isinstance(snapshot_rows, dict):
        rows = list(snapshot_rows.values())
    else:
        rows = list(snapshot_rows)
    symbols = [str(row.symbol).upper() for row in rows]
    price_context = _market_price_context_by_symbol(db, symbols)
    return {
        str(row.symbol).upper(): _enrich_snapshot_with_market_data(
            _snapshot_from_model(row),
            price_context=price_context.get(str(row.symbol).upper()),
            history=[],
        )
        for row in rows
    }


def _filter_workbook_to_stock_master_symbols(
    parsed: FundamentalWorkbook,
    *,
    existing_symbols: set[str],
) -> FundamentalWorkbook:
    """Keep workbook fundamentals only for symbols already registered in stock_master."""

    normalized_existing = {str(symbol).strip().upper() for symbol in existing_symbols if symbol}
    parsed = _canonicalize_workbook_symbols(parsed, existing_symbols=normalized_existing)

    imported_mappings = [
        mapping
        for mapping in parsed.mappings
        if mapping.symbol and mapping.symbol.strip().upper() in normalized_existing
    ]
    imported_symbols = {mapping.symbol.strip().upper() for mapping in imported_mappings if mapping.symbol}

    annual_metrics = [row for row in parsed.annual_metrics if row.symbol.strip().upper() in imported_symbols]
    period_metrics = [row for row in parsed.period_metrics if row.symbol.strip().upper() in imported_symbols]
    latest_snapshots = [row for row in parsed.latest_snapshots if row.symbol.strip().upper() in imported_symbols]

    ignored_mappings = [
        mapping
        for mapping in parsed.mappings
        if not mapping.symbol or mapping.symbol.strip().upper() not in normalized_existing
    ]
    ignored_symbols = sorted(
        {mapping.symbol.strip().upper() for mapping in ignored_mappings if mapping.symbol}
    )
    ignored_issues = [
        FundamentalQualityIssue(
            severity="warning",
            code="unmapped_company_ignored" if not mapping.symbol else "unknown_symbol_ignored",
            message=(
                "Workbook company has no usable ticker mapping and was skipped."
                if not mapping.symbol
                else f"Workbook company maps to {mapping.symbol.strip().upper()}, but that symbol is not in stock_master; skipped."
            ),
            symbol=mapping.symbol.strip().upper() if mapping.symbol else None,
            context={
                "company_name": mapping.company_name,
                "mapped_company_name": mapping.mapped_company_name,
                "match_type": mapping.match_type,
                "score_note": mapping.score_note,
            },
        )
        for mapping in ignored_mappings
    ]
    quality_issues = [
        issue
        for issue in parsed.quality_issues
        if issue.symbol is None or issue.symbol.strip().upper() in imported_symbols
    ]
    quality_issues.extend(ignored_issues)

    original_summary = dict(parsed.summary or {})
    imported_duplicate_symbols = sorted(
        {
            mapping.symbol.strip().upper()
            for mapping in imported_mappings
            if mapping.symbol and mapping.is_duplicate_symbol
        }
    )
    summary = {
        **original_summary,
        "workbook_mapped_company_count": original_summary.get("mapped_company_count", len(parsed.mappings)),
        "workbook_mapped_symbol_count": original_summary.get(
            "mapped_symbol_count",
            len({mapping.symbol for mapping in parsed.mappings if mapping.symbol}),
        ),
        "workbook_annual_metric_count": original_summary.get("annual_metric_count", len(parsed.annual_metrics)),
        "workbook_latest_snapshot_count": original_summary.get("latest_snapshot_count", len(parsed.latest_snapshots)),
        "mapped_company_count": len(imported_mappings),
        "mapped_symbol_count": len(imported_symbols),
        "annual_metric_count": len(annual_metrics),
        "latest_snapshot_count": len(latest_snapshots),
        "duplicate_symbols": imported_duplicate_symbols,
        "stock_master_symbol_count": len(normalized_existing),
        "ignored_mapping_count": len(ignored_mappings),
        "ignored_unmapped_company_count": sum(1 for mapping in ignored_mappings if not mapping.symbol),
        "unknown_symbol_ignored_count": sum(1 for mapping in ignored_mappings if mapping.symbol),
        "ignored_symbol_count": len(ignored_symbols),
        "ignored_symbols": ignored_symbols,
        "quality_issue_count": len(quality_issues),
        "quality_issue_counts": dict(Counter(issue.severity for issue in quality_issues)),
    }

    return FundamentalWorkbook(
        mappings=imported_mappings,
        annual_metrics=annual_metrics,
        latest_snapshots=latest_snapshots,
        summary=summary,
        quality_issues=quality_issues,
        period_metrics=period_metrics,
    )


def latest_import(db: Session) -> models.FundamentalImport | None:
    """Latest completed fundamental import, regardless of provider."""

    return (
        db.query(models.FundamentalImport)
        .filter(
            models.FundamentalImport.status.in_(SUCCEEDED_IMPORT_STATUSES),
        )
        .order_by(models.FundamentalImport.completed_at.desc().nullslast(), models.FundamentalImport.imported_at.desc().nullslast())
        .first()
    )


def _latest_key(import_row: models.FundamentalImport) -> dt.datetime:
    return (
        import_row.completed_at
        or import_row.imported_at
        or import_row.created_at
        or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    )


def latest_snapshot_rows_by_symbol(
    db: Session,
    *,
    symbols: list[str] | None = None,
    scope: FundamentalScope = "all",
) -> dict[str, models.FundamentalLatestSnapshot]:
    query = (
        db.query(models.FundamentalLatestSnapshot, models.FundamentalImport, models.StockMaster)
        .join(models.FundamentalImport, models.FundamentalLatestSnapshot.import_id == models.FundamentalImport.id)
        .outerjoin(models.StockMaster, models.StockMaster.symbol == models.FundamentalLatestSnapshot.symbol)
        .filter(models.FundamentalImport.status.in_(SUCCEEDED_IMPORT_STATUSES))
        .filter(~models.FundamentalLatestSnapshot.symbol.in_(NON_STOCK_SYMBOLS))
    )
    if symbols:
        query = query.filter(models.FundamentalLatestSnapshot.symbol.in_([symbol.upper() for symbol in symbols]))
    if scope == "masi":
        query = query.filter(
            (models.FundamentalImport.source_universe == "masi")
            | (models.StockMaster.market_region == "masi")
        )
    elif scope == "non_masi":
        query = query.filter(
            (models.FundamentalImport.source_universe == "non_masi")
            | (
                (models.StockMaster.market_region.isnot(None))
                & (models.StockMaster.market_region != "masi")
            )
        )

    latest: dict[str, tuple[dt.datetime, models.FundamentalLatestSnapshot]] = {}
    for snapshot, import_row, _stock in query.all():
        symbol = str(snapshot.symbol).upper()
        key = _latest_key(import_row)
        if symbol not in latest or key > latest[symbol][0]:
            latest[symbol] = (key, snapshot)
    return {symbol: row for symbol, (_key, row) in latest.items()}


def latest_imports_by_symbol(
    db: Session,
    *,
    symbols: list[str] | None = None,
    scope: FundamentalScope = "all",
) -> dict[str, models.FundamentalImport]:
    query = (
        db.query(models.FundamentalLatestSnapshot, models.FundamentalImport, models.StockMaster)
        .join(models.FundamentalImport, models.FundamentalLatestSnapshot.import_id == models.FundamentalImport.id)
        .outerjoin(models.StockMaster, models.StockMaster.symbol == models.FundamentalLatestSnapshot.symbol)
        .filter(models.FundamentalImport.status.in_(SUCCEEDED_IMPORT_STATUSES))
        .filter(~models.FundamentalLatestSnapshot.symbol.in_(NON_STOCK_SYMBOLS))
    )
    if symbols:
        query = query.filter(models.FundamentalLatestSnapshot.symbol.in_([symbol.upper() for symbol in symbols]))
    if scope == "masi":
        query = query.filter(
            (models.FundamentalImport.source_universe == "masi")
            | (models.StockMaster.market_region == "masi")
        )
    elif scope == "non_masi":
        query = query.filter(
            (models.FundamentalImport.source_universe == "non_masi")
            | (
                (models.StockMaster.market_region.isnot(None))
                & (models.StockMaster.market_region != "masi")
            )
        )

    latest: dict[str, tuple[dt.datetime, models.FundamentalImport]] = {}
    for snapshot, import_row, _stock in query.all():
        symbol = str(snapshot.symbol).upper()
        key = _latest_key(import_row)
        if symbol not in latest or key > latest[symbol][0]:
            latest[symbol] = (key, import_row)
    return {symbol: row for symbol, (_key, row) in latest.items()}


def create_import_run(
    db: Session,
    *,
    dataset: models.Dataset | None = None,
    data_source: str = "workbook",
    source_universe: str | None = "masi",
    filename: str | None = None,
    source_hash: str | None = None,
    object_key: str | None = None,
    summary: dict[str, Any] | None = None,
) -> models.FundamentalImport:
    if dataset is not None:
        filename = filename or dataset.filename or "fundamentals.xlsx"
        source_hash = source_hash or dataset.data_hash
        object_key = object_key or dataset.object_key
    if not filename:
        filename = f"{data_source}_fundamentals"
    if not source_hash:
        source_hash = uuid.uuid5(uuid.NAMESPACE_URL, f"{data_source}:{filename}:{_utcnow().isoformat()}").hex
    row = models.FundamentalImport(
        dataset_id=dataset.id if dataset is not None else None,
        filename=filename,
        source_hash=source_hash[:64],
        object_key=object_key,
        data_source=data_source,
        source_universe=source_universe,
        status="queued",
        methodology_version=METHODOLOGY_VERSION,
        summary_json=summary or {},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _stock_sectors(db: Session, symbols: list[str] | None = None) -> dict[str, str | None]:
    query = db.query(models.StockMaster.symbol, models.StockMaster.sector)
    if symbols:
        query = query.filter(models.StockMaster.symbol.in_(symbols))
    return {str(symbol).upper(): sector for symbol, sector in query.all()}


def _snapshot_from_model(row: models.FundamentalLatestSnapshot) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=row.symbol,
        company_name=row.company_name,
        latest_statement_year=row.latest_statement_year,
        metrics=dict(row.metrics_json or {}),
        scores=dict(row.scores_json or {}),
        diagnostics=dict(row.diagnostics_json or {}),
        coverage=dict(row.coverage_json or {}),
        model_eligibility=dict(row.model_eligibility_json or {}),
        source=dict(row.source_json or {}),
    )


def _annual_from_model(row: models.FundamentalAnnualMetric) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol=row.symbol,
        company_name=row.company_name,
        statement_year=row.statement_year,
        metric_name=row.metric_name,
        metric_value=row.metric_value,
        raw_metric_name=row.raw_metric_name,
        source_sheet=row.source_sheet,
        source_field=row.source_field,
        is_proxy=bool(row.is_proxy),
    )


def _latest_year_metric_map(history: list[AnnualMetricRow], statement_year: int | None = None) -> dict[str, float | None]:
    if statement_year is None:
        years = [row.statement_year for row in history if row.statement_year is not None]
        if not years:
            return {}
        statement_year = max(years)
    out: dict[str, float | None] = {}
    for row in history:
        if row.statement_year == statement_year:
            out[row.metric_name] = row.metric_value
    return out


def _integrity_from_model(row: models.FundamentalIntegrityReport | None) -> IntegrityReport | None:
    if row is None:
        return None
    return report_from_dict(
        {
            "symbol": row.symbol,
            "statement_year": row.statement_year,
            "overall_status": row.overall_status,
            "confidence_haircut": row.confidence_haircut,
            "checks": list(row.checks_json or []),
            "projected_statements": list(row.projected_statements_json or []),
            "projection_checks": list(row.projection_checks_json or []),
        }
    )


def latest_integrity_report(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
    statement_year: int | None = None,
) -> IntegrityReport | None:
    query = db.query(models.FundamentalIntegrityReport).filter(
        models.FundamentalIntegrityReport.import_id == import_id,
        models.FundamentalIntegrityReport.symbol == symbol.upper(),
    )
    if statement_year is not None:
        query = query.filter(models.FundamentalIntegrityReport.statement_year == statement_year)
    row = query.order_by(models.FundamentalIntegrityReport.statement_year.desc()).first()
    return _integrity_from_model(row)


def _build_integrity_reports(annual_metrics: list[AnnualMetricRow]) -> list[IntegrityReport]:
    grouped: dict[tuple[str, int], list[AnnualMetricRow]] = defaultdict(list)
    for row in annual_metrics:
        grouped[(row.symbol.upper(), row.statement_year)].append(row)
    reports: list[IntegrityReport] = []
    for (symbol, year), rows in sorted(grouped.items()):
        reports.append(
            build_integrity_report(
                symbol=symbol,
                statement_year=year,
                rows_by_metric=_latest_year_metric_map(rows, year),
                assumptions=DEFAULT_ASSUMPTIONS,
            )
        )
    return reports


def _persist_integrity_reports(db: Session, *, import_id: uuid.UUID, reports: list[IntegrityReport]) -> None:
    if not reports:
        return
    symbols = sorted({report.symbol for report in reports})
    db.query(models.FundamentalIntegrityReport).filter(
        models.FundamentalIntegrityReport.import_id == import_id,
        models.FundamentalIntegrityReport.symbol.in_(symbols),
    ).delete(synchronize_session=False)
    db.add_all(
        [
            models.FundamentalIntegrityReport(
                import_id=import_id,
                symbol=report.symbol,
                statement_year=report.statement_year,
                overall_status=report.overall_status,
                confidence_haircut=report.confidence_haircut,
                checks_json=sanitize_json_compatible(report_to_dict(report)["checks"]),
                projected_statements_json=sanitize_json_compatible(report.projected_statements),
                projection_checks_json=sanitize_json_compatible(report_to_dict(report)["projection_checks"]),
            )
            for report in reports
        ]
    )


def _score_value(scores: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _num(scores.get(key))
        if value is not None:
            return value
    return None


def _history_row_dict(row: models.FundamentalPillarScoreHistory) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "as_of": row.as_of.isoformat() if row.as_of else None,
        "value_score": row.value_score,
        "quality_score": row.quality_score,
        "growth_score": row.growth_score,
        "risk_score": row.risk_score,
        "cash_flow_score": row.cash_flow_score,
        "health_score": row.health_score,
        "overall_score": row.overall_score,
        "pillar_coverage": dict(row.pillar_coverage_json or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def persist_pillar_history_for_import(db: Session, *, import_id: uuid.UUID) -> int:
    snapshots = (
        db.query(models.FundamentalLatestSnapshot)
        .filter(models.FundamentalLatestSnapshot.import_id == import_id)
        .order_by(models.FundamentalLatestSnapshot.symbol.asc())
        .all()
    )
    if not snapshots:
        return 0
    import_row = db.get(models.FundamentalImport, import_id)
    db.query(models.FundamentalPillarScoreHistory).filter(models.FundamentalPillarScoreHistory.import_id == import_id).delete(synchronize_session=False)
    rows: list[models.FundamentalPillarScoreHistory] = []
    for snapshot in snapshots:
        scores = dict(snapshot.scores_json or {})
        coverage = dict(snapshot.coverage_json or {})
        if snapshot.latest_statement_year:
            as_of = dt.date(int(snapshot.latest_statement_year), 12, 31)
        else:
            stamp = (import_row.completed_at if import_row else None) or (import_row.imported_at if import_row else None) or _utcnow()
            as_of = stamp.date()
        rows.append(
            models.FundamentalPillarScoreHistory(
                import_id=import_id,
                symbol=snapshot.symbol,
                as_of=as_of,
                value_score=_score_value(scores, "value"),
                quality_score=_score_value(scores, "quality"),
                growth_score=_score_value(scores, "growth"),
                risk_score=_score_value(scores, "risk"),
                cash_flow_score=_score_value(scores, "cash_flow"),
                health_score=_score_value(scores, "health"),
                overall_score=_score_value(scores, "overall"),
                pillar_coverage_json=sanitize_json_compatible({pillar: coverage.get(pillar) for pillar in PILLAR_KEYS}),
            )
        )
    db.add_all(rows)
    db.flush()
    return len(rows)


def pillar_history_for_symbol(db: Session, *, symbol: str, limit: int = 12) -> tuple[list[dict[str, Any]], dict[str, str]]:
    capped = max(1, min(24, int(limit or 12)))
    rows = (
        db.query(models.FundamentalPillarScoreHistory)
        .filter(models.FundamentalPillarScoreHistory.symbol == symbol.upper())
        .order_by(models.FundamentalPillarScoreHistory.as_of.desc(), models.FundamentalPillarScoreHistory.created_at.desc())
        .limit(capped)
        .all()
    )
    items = [_history_row_dict(row) for row in rows]
    return items, classify_all_pillar_trends(items)


def _load_snapshots(db: Session, import_id: uuid.UUID) -> list[FundamentalSnapshot]:
    rows = (
        db.query(models.FundamentalLatestSnapshot)
        .filter(models.FundamentalLatestSnapshot.import_id == import_id)
        .order_by(models.FundamentalLatestSnapshot.symbol.asc())
        .all()
    )
    return [_snapshot_from_model(row) for row in rows]


def _load_history(db: Session, import_id: uuid.UUID, symbol: str | None = None) -> list[AnnualMetricRow]:
    query = db.query(models.FundamentalAnnualMetric).filter(models.FundamentalAnnualMetric.import_id == import_id)
    if symbol:
        query = query.filter(models.FundamentalAnnualMetric.symbol == symbol.upper())
    rows = query.order_by(
        models.FundamentalAnnualMetric.symbol.asc(),
        models.FundamentalAnnualMetric.statement_year.asc(),
        models.FundamentalAnnualMetric.metric_name.asc(),
    ).all()
    return [_annual_from_model(row) for row in rows]


def _scope_for_symbols(db: Session, symbols: list[str]) -> FundamentalScope:
    regions = {
        str(symbol).upper(): region
        for symbol, region in db.query(models.StockMaster.symbol, models.StockMaster.market_region)
        .filter(models.StockMaster.symbol.in_([symbol.upper() for symbol in symbols]))
        .all()
    }
    if symbols and all(regions.get(symbol.upper()) == "masi" for symbol in symbols):
        return "masi"
    if symbols and all(regions.get(symbol.upper()) != "masi" for symbol in symbols):
        return "non_masi"
    return "all"


def _latest_history_for_symbols(
    db: Session,
    snapshots_by_symbol: dict[str, models.FundamentalLatestSnapshot],
    *,
    symbol: str | None = None,
) -> list[AnnualMetricRow]:
    rows: list[AnnualMetricRow] = []
    wanted = {symbol.upper()} if symbol else set(snapshots_by_symbol)
    by_import: dict[uuid.UUID, list[str]] = defaultdict(list)
    for item_symbol, snapshot in snapshots_by_symbol.items():
        if item_symbol in wanted:
            by_import[snapshot.import_id].append(item_symbol)
    for import_id, item_symbols in by_import.items():
        query = db.query(models.FundamentalAnnualMetric).filter(
            models.FundamentalAnnualMetric.import_id == import_id,
            models.FundamentalAnnualMetric.symbol.in_(item_symbols),
        )
        for row in query.order_by(
            models.FundamentalAnnualMetric.symbol.asc(),
            models.FundamentalAnnualMetric.statement_year.asc(),
            models.FundamentalAnnualMetric.metric_name.asc(),
        ).all():
            rows.append(_annual_from_model(row))
    return rows


def rescore_universe(db: Session, *, scope: FundamentalScope = "all") -> int:
    """Recompute cross-sectional scores for latest snapshots in one universe."""

    latest_rows = latest_snapshot_rows_by_symbol(db, scope=scope)
    if not latest_rows:
        return 0
    enriched = enriched_snapshots_by_symbol(db, latest_rows)
    snapshots = list(enriched.values())
    history = _latest_history_for_symbols(db, latest_rows)
    sectors = _stock_sectors(db, [row.symbol for row in snapshots])
    scored = score_fundamental_snapshots(snapshots, history, sectors=sectors)
    rows_by_symbol = {symbol.upper(): row for symbol, row in latest_rows.items()}
    for snapshot in scored:
        row = rows_by_symbol.get(snapshot.symbol.upper())
        if row is None:
            continue
        row.metrics_json = sanitize_json_compatible(snapshot.metrics)
        row.coverage_json = sanitize_json_compatible(snapshot.coverage)
        row.source_json = sanitize_json_compatible(snapshot.source)
        row.scores_json = sanitize_json_compatible(snapshot.scores)
        row.diagnostics_json = sanitize_json_compatible(snapshot.diagnostics)
        row.updated_at = _utcnow()
        db.add(row)
    db.flush()
    return len(scored)


def _clean_assumptions(assumptions: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {
        key: float(value)
        for key, value in assumptions.items()
        if key in DEFAULT_ASSUMPTIONS and value is not None
    }
    currency = assumptions.get("currency")
    if currency:
        cleaned["currency"] = str(currency).strip().upper()
    return cleaned


def _scenario_key(scenario: str) -> str:
    key = (scenario or "base").strip().lower()
    if key not in VALUATION_SCENARIOS:
        raise ValueError(f"scenario must be one of {', '.join(VALUATION_SCENARIOS)}")
    return key


def clean_assumption_override_values(overrides: dict[str, Any]) -> dict[str, float]:
    cleaned: dict[str, float] = {}
    for key, value in dict(overrides or {}).items():
        if key not in DEFAULT_ASSUMPTIONS:
            raise ValueError(f"unknown assumption key: {key}")
        if isinstance(value, bool) or value is None:
            raise ValueError(f"assumption {key} must be a finite float")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"assumption {key} must be a finite float") from exc
        if not isfinite(numeric):
            raise ValueError(f"assumption {key} must be a finite float")
        cleaned[key] = numeric
    return cleaned


def make_overrides_loader(db: Session) -> AssumptionOverrideLoader:
    def load(symbol: str, scenario: str) -> dict[str, float] | None:
        row = (
            db.query(models.FundamentalAssumptionOverride)
            .filter(
                models.FundamentalAssumptionOverride.symbol == symbol.strip().upper(),
                models.FundamentalAssumptionOverride.scenario == _scenario_key(scenario),
                models.FundamentalAssumptionOverride.is_current.is_(True),
            )
            .order_by(models.FundamentalAssumptionOverride.created_at.desc(), models.FundamentalAssumptionOverride.id.desc())
            .first()
        )
        if row is None:
            return None
        return clean_assumption_override_values(dict(row.overrides or {}))

    return load


def make_bulk_overrides_loader(db: Session, symbols: list[str]) -> AssumptionOverrideLoader:
    normalized = sorted({symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()})
    if not normalized:
        return lambda _symbol, _scenario: None
    rows = (
        db.query(models.FundamentalAssumptionOverride)
        .filter(
            models.FundamentalAssumptionOverride.symbol.in_(normalized),
            models.FundamentalAssumptionOverride.is_current.is_(True),
        )
        .all()
    )
    overrides_by_key: dict[tuple[str, str], dict[str, float]] = {
        (row.symbol.upper(), row.scenario): clean_assumption_override_values(dict(row.overrides or {}))
        for row in rows
    }

    def load(symbol: str, scenario: str) -> dict[str, float] | None:
        return overrides_by_key.get((symbol.strip().upper(), _scenario_key(scenario)))

    return load


def active_assumptions_for(
    db: Session,
    *,
    symbol: str,
    sector: str | None,
    scenario: str,
    overrides_loader: AssumptionOverrideLoader | None = None,
) -> dict[str, Any]:
    symbol = symbol.upper()
    scenario = _scenario_key(scenario)
    merged: dict[str, Any] = {**default_assumptions_for_scenario(scenario), "currency": "MAD"}
    scopes = [("desk", "GLOBAL")]
    if sector:
        scopes.append(("sector", sector))
    scopes.append(("symbol", symbol))
    for scope_type, scope_key in scopes:
        row = (
            db.query(models.FundamentalAssumptionSet)
            .filter(
                models.FundamentalAssumptionSet.scope_type == scope_type,
                models.FundamentalAssumptionSet.scope_key == scope_key,
                models.FundamentalAssumptionSet.scenario == scenario,
                models.FundamentalAssumptionSet.is_active.is_(True),
            )
            .order_by(models.FundamentalAssumptionSet.updated_at.desc().nullslast(), models.FundamentalAssumptionSet.created_at.desc())
            .first()
        )
        if row:
            merged.update(_clean_assumptions(dict(row.assumptions_json or {})))
    loader = overrides_loader or make_overrides_loader(db)
    for key, value in (loader(symbol, scenario) or {}).items():
        merged[key] = value
    return merged


def resolved_assumptions_with_provenance(
    db: Session,
    *,
    symbol: str,
    sector: str | None,
    scenario: str,
    overrides_loader: AssumptionOverrideLoader | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    symbol = symbol.upper()
    scenario = _scenario_key(scenario)
    resolved, provenance = resolve_assumptions(symbol, scenario, overrides_loader=None)
    merged: dict[str, Any] = {**resolved, "currency": "MAD"}
    provenance = {**provenance, "currency": "default"}
    scopes = [("desk", "GLOBAL")]
    if sector:
        scopes.append(("sector", sector))
    scopes.append(("symbol", symbol))
    for scope_type, scope_key in scopes:
        row = (
            db.query(models.FundamentalAssumptionSet)
            .filter(
                models.FundamentalAssumptionSet.scope_type == scope_type,
                models.FundamentalAssumptionSet.scope_key == scope_key,
                models.FundamentalAssumptionSet.scenario == scenario,
                models.FundamentalAssumptionSet.is_active.is_(True),
            )
            .order_by(models.FundamentalAssumptionSet.updated_at.desc().nullslast(), models.FundamentalAssumptionSet.created_at.desc())
            .first()
        )
        if row:
            cleaned = _clean_assumptions(dict(row.assumptions_json or {}))
            for key, value in cleaned.items():
                merged[key] = value
                provenance[key] = "symbol" if scope_type == "symbol" else "scenario"
    loader = overrides_loader or make_overrides_loader(db)
    for key, value in (loader(symbol, scenario) or {}).items():
        merged[key] = value
        provenance[key] = "symbol"
    return merged, provenance


def _delete_valuations(db: Session, import_id: uuid.UUID, symbol: str, scenario: str) -> None:
    db.query(models.FundamentalValuationResult).filter(
        models.FundamentalValuationResult.import_id == import_id,
        models.FundamentalValuationResult.symbol == symbol.upper(),
        models.FundamentalValuationResult.scenario == scenario,
    ).delete(synchronize_session=False)
    db.query(models.FundamentalEnsembleResult).filter(
        models.FundamentalEnsembleResult.import_id == import_id,
        models.FundamentalEnsembleResult.symbol == symbol.upper(),
        models.FundamentalEnsembleResult.scenario == scenario,
    ).delete(synchronize_session=False)


def recompute_symbol_valuations(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
    scenario: str = "base",
    overrides_loader: AssumptionOverrideLoader | None = None,
) -> list[models.FundamentalValuationResult]:
    symbol = symbol.upper()
    scenario = _scenario_key(scenario)
    snapshot_row = (
        db.query(models.FundamentalLatestSnapshot)
        .filter(
            models.FundamentalLatestSnapshot.import_id == import_id,
            models.FundamentalLatestSnapshot.symbol == symbol,
        )
        .first()
    )
    if snapshot_row is None:
        return []

    scope = _scope_for_symbols(db, [symbol])
    latest_rows = latest_snapshot_rows_by_symbol(db, scope=scope)
    latest_rows[symbol] = snapshot_row
    enriched = enriched_snapshots_by_symbol(db, latest_rows)
    peer_snapshots = list(enriched.values())
    target_snapshot = enriched.get(symbol) or _snapshot_from_model(snapshot_row)
    history = _load_history(db, import_id, symbol)
    sectors = _stock_sectors(db, [row.symbol for row in peer_snapshots])
    assumptions = active_assumptions_for(
        db,
        symbol=symbol,
        sector=sectors.get(symbol),
        scenario=scenario,
        overrides_loader=overrides_loader,
    )
    integrity = latest_integrity_report(
        db,
        import_id=import_id,
        symbol=symbol,
        statement_year=target_snapshot.latest_statement_year,
    )
    eligibility, valuations = compute_symbol_valuations(
        snapshot=target_snapshot,
        history=history,
        peer_snapshots=peer_snapshots,
        sectors=sectors,
        assumptions=assumptions,
        scenario=scenario,
        integrity=integrity,
    )
    ensemble = compute_valuation_ensemble(symbol, scenario, valuations)
    sensitivity_grids = compute_default_sensitivity_grids(
        snapshot=target_snapshot,
        history=history,
        peer_snapshots=peer_snapshots,
        sectors=sectors,
        base_assumptions=assumptions,
        scenario=scenario,
        integrity=integrity,
    )
    snapshot_row.metrics_json = sanitize_json_compatible(target_snapshot.metrics)
    snapshot_row.coverage_json = sanitize_json_compatible(target_snapshot.coverage)
    snapshot_row.source_json = sanitize_json_compatible(target_snapshot.source)
    snapshot_row.model_eligibility_json = sanitize_json_compatible(eligibility)
    _delete_valuations(db, import_id, symbol, scenario)
    rows = [
        models.FundamentalValuationResult(
            import_id=import_id,
            symbol=symbol,
            scenario=result.scenario,
            model=result.model,
            fair_value=result.fair_value,
            current_price=result.current_price,
            upside_pct=result.upside_pct,
            confidence=result.confidence,
            confidence_score=result.confidence_score,
            weight=result.weight,
            family=result.family,
            methodology=result.methodology,
            model_version=result.model_version,
            is_proxy=result.is_proxy,
            data_quality_score=result.data_quality_score,
            currency=result.currency,
            inputs_json=sanitize_json_compatible(result.inputs),
            outputs_json=sanitize_json_compatible(result.outputs),
            warnings_json=sanitize_json_compatible(result.warnings),
        )
        for result in valuations
    ]
    db.add_all(rows)
    db.add(
        models.FundamentalEnsembleResult(
            import_id=import_id,
            symbol=symbol,
            scenario=scenario,
            fair_value_low=ensemble.fair_value_low,
            fair_value_base=ensemble.fair_value_base,
            fair_value_high=ensemble.fair_value_high,
            current_price=ensemble.current_price,
            upside_pct=ensemble.upside_pct,
            confidence_score=ensemble.confidence_score,
            usable_model_count=ensemble.usable_model_count,
            excluded_model_count=ensemble.excluded_model_count,
            model_weights_json=sanitize_json_compatible(ensemble.model_weights),
            warnings_json=sanitize_json_compatible(ensemble.warnings),
            sensitivity_grids_json=sanitize_json_compatible(sensitivity_grids),
            currency=ensemble.currency,
            model_dispersion_low=ensemble.model_dispersion_low,
            model_dispersion_base=ensemble.model_dispersion_base,
            model_dispersion_high=ensemble.model_dispersion_high,
            monte_carlo_low=ensemble.monte_carlo_low,
            monte_carlo_base=ensemble.monte_carlo_base,
            monte_carlo_high=ensemble.monte_carlo_high,
        )
    )
    db.flush()
    return rows


def recompute_symbol_valuations_all_scenarios(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
    scenarios: Iterable[str] = VALUATION_SCENARIOS,
    overrides_loader: AssumptionOverrideLoader | None = None,
) -> list[models.FundamentalValuationResult]:
    rows: list[models.FundamentalValuationResult] = []
    loader = overrides_loader or make_bulk_overrides_loader(db, [symbol])
    for scenario in scenarios:
        rows.extend(
            recompute_symbol_valuations(
                db,
                import_id=import_id,
                symbol=symbol,
                scenario=scenario,
                overrides_loader=loader,
            )
        )
    return rows


def compute_symbol_sensitivity(
    db: Session,
    *,
    symbol: str,
    scenario: str = "base",
    axis_x: str = "wacc",
    axis_y: str = "terminal_growth",
    steps: int = 5,
) -> dict[str, Any]:
    symbol = symbol.upper()
    snapshot_row = latest_snapshot_rows_by_symbol(db, symbols=[symbol]).get(symbol)
    if snapshot_row is None:
        raise ValueError(f"No fundamentals for {symbol}")
    scope = _scope_for_symbols(db, [symbol])
    latest_rows = latest_snapshot_rows_by_symbol(db, scope=scope)
    latest_rows[symbol] = snapshot_row
    enriched = enriched_snapshots_by_symbol(db, latest_rows)
    peer_snapshots = list(enriched.values())
    target_snapshot = enriched.get(symbol) or _snapshot_from_model(snapshot_row)
    history = _load_history(db, snapshot_row.import_id, symbol)
    sectors = _stock_sectors(db, [row.symbol for row in peer_snapshots])
    assumptions = active_assumptions_for(db, symbol=symbol, sector=sectors.get(symbol), scenario=scenario)
    integrity = latest_integrity_report(
        db,
        import_id=snapshot_row.import_id,
        symbol=symbol,
        statement_year=target_snapshot.latest_statement_year,
    )
    return compute_sensitivity(
        snapshot=target_snapshot,
        history=history,
        peer_snapshots=peer_snapshots,
        sectors=sectors,
        base_assumptions=assumptions,
        scenario=scenario,
        axis_x=axis_x,
        axis_y=axis_y,
        steps=steps,
        integrity=integrity,
    )


def execute_import_run(
    db: Session,
    *,
    import_id: uuid.UUID,
    payload: bytes,
) -> models.FundamentalImport:
    import_row = db.get(models.FundamentalImport, import_id)
    if import_row is None:
        raise ValueError(f"Fundamental import run {import_id} does not exist")
    import_row.status = "running"
    import_row.imported_at = _utcnow()
    import_row.error_message = None
    db.commit()

    try:
        parsed = parse_fundamental_workbook(payload)
        parsed = _filter_workbook_to_stock_master_symbols(
            parsed,
            existing_symbols=_stock_master_symbols(db),
        )
        parsed = _enrich_workbook_with_market_data(db, parsed)
        parsed_symbols = [snapshot.symbol for snapshot in parsed.latest_snapshots]
        integrity_reports = _build_integrity_reports(parsed.annual_metrics)
        scored_snapshots = score_fundamental_snapshots(
            parsed.latest_snapshots,
            parsed.annual_metrics,
            sectors=_stock_sectors(db, parsed_symbols),
        )
        data_source = import_row.data_source or "workbook"
        source_universe = import_row.source_universe or ("masi" if data_source == "workbook" else None)

        db.query(models.FundamentalCompanyMap).filter(models.FundamentalCompanyMap.import_id == import_row.id).delete(synchronize_session=False)
        db.query(models.FundamentalAnnualMetric).filter(models.FundamentalAnnualMetric.import_id == import_row.id).delete(synchronize_session=False)
        db.query(models.FundamentalPeriodMetric).filter(models.FundamentalPeriodMetric.import_id == import_row.id).delete(synchronize_session=False)
        db.query(models.FundamentalSourceDocument).filter(models.FundamentalSourceDocument.import_id == import_row.id).delete(synchronize_session=False)
        db.query(models.FundamentalLatestSnapshot).filter(models.FundamentalLatestSnapshot.import_id == import_row.id).delete(synchronize_session=False)
        db.query(models.FundamentalQualityIssue).filter(models.FundamentalQualityIssue.import_id == import_row.id).delete(synchronize_session=False)
        db.query(models.FundamentalValuationResult).filter(models.FundamentalValuationResult.import_id == import_row.id).delete(synchronize_session=False)
        db.query(models.FundamentalEnsembleResult).filter(models.FundamentalEnsembleResult.import_id == import_row.id).delete(synchronize_session=False)
        db.query(models.FundamentalIntegrityReport).filter(models.FundamentalIntegrityReport.import_id == import_row.id).delete(synchronize_session=False)
        db.query(models.FundamentalPillarScoreHistory).filter(models.FundamentalPillarScoreHistory.import_id == import_row.id).delete(synchronize_session=False)

        db.bulk_save_objects(
            [
                models.FundamentalCompanyMap(
                    import_id=import_row.id,
                    company_name=mapping.company_name,
                    mapped_company_name=mapping.mapped_company_name,
                    canonical_company_name=mapping.canonical_company_name,
                    symbol=mapping.symbol,
                    shares_outstanding=mapping.shares_outstanding,
                    match_type=mapping.match_type,
                    score_note=mapping.score_note,
                    source=mapping.source,
                    is_duplicate_symbol=mapping.is_duplicate_symbol,
                )
                for mapping in parsed.mappings
            ]
        )
        db.bulk_save_objects(
            [
                models.FundamentalAnnualMetric(
                    import_id=import_row.id,
                    symbol=row.symbol,
                    company_name=row.company_name,
                    statement_year=row.statement_year,
                    metric_name=row.metric_name,
                    metric_value=row.metric_value,
                    raw_metric_name=row.raw_metric_name,
                    source_sheet=row.source_sheet,
                    source_field=row.source_field,
                    is_proxy=row.is_proxy,
                )
                for row in parsed.annual_metrics
            ]
        )
        db.bulk_save_objects(
            [
                models.FundamentalPeriodMetric(
                    import_id=import_row.id,
                    symbol=row.symbol,
                    company_name=row.company_name,
                    fiscal_year=row.fiscal_year,
                    period_type=row.period_type or "annual",
                    period_label=row.period_label or ("FY" if row.period_type == "annual" else ""),
                    period_end_date=_date_or_none(row.period_end_date),
                    metric_name=row.metric_name,
                    metric_value=row.metric_value,
                    raw_metric_name=row.raw_metric_name,
                    source_url=row.source_url,
                    document_title=row.document_title,
                    is_proxy=row.is_proxy,
                )
                for row in parsed.period_metrics
            ]
        )
        db.bulk_save_objects(
            [
                models.FundamentalQualityIssue(
                    import_id=import_row.id,
                    severity=issue.severity,
                    code=issue.code,
                    message=issue.message,
                    symbol=issue.symbol,
                    metric_name=issue.metric_name,
                    statement_year=issue.statement_year,
                    context_json=sanitize_json_compatible(issue.context),
                )
                for issue in parsed.quality_issues
            ]
        )
        snapshot_models = [
            models.FundamentalLatestSnapshot(
                import_id=import_row.id,
                symbol=row.symbol,
                company_name=row.company_name,
                latest_statement_year=row.latest_statement_year,
                data_source=data_source,
                metrics_json=sanitize_json_compatible(row.metrics),
                scores_json=sanitize_json_compatible(row.scores),
                diagnostics_json=sanitize_json_compatible(row.diagnostics),
                coverage_json=sanitize_json_compatible(row.coverage),
                model_eligibility_json={},
                source_json=sanitize_json_compatible(row.source),
            )
            for row in scored_snapshots
        ]
        db.bulk_save_objects(snapshot_models)
        _persist_integrity_reports(db, import_id=import_row.id, reports=integrity_reports)
        db.flush()

        import_row.status = "succeeded"
        import_row.data_source = data_source
        import_row.source_universe = source_universe
        import_row.company_count = len(parsed.mappings)
        import_row.symbol_count = len({mapping.symbol for mapping in parsed.mappings if mapping.symbol})
        import_row.annual_metric_count = len(parsed.annual_metrics)
        import_row.latest_snapshot_count = len(scored_snapshots)
        import_row.quality_issue_count = len(parsed.quality_issues)
        import_row.summary_json = sanitize_json_compatible(parsed.summary)
        import_row.completed_at = _utcnow()
        db.commit()

        if source_universe in {"masi", "non_masi"}:
            rescore_universe(db, scope=source_universe)
            persist_pillar_history_for_import(db, import_id=import_row.id)
            db.commit()
        else:
            persist_pillar_history_for_import(db, import_id=import_row.id)
            db.commit()

        overrides_loader = make_bulk_overrides_loader(db, [snapshot.symbol for snapshot in scored_snapshots])
        for snapshot in scored_snapshots:
            recompute_symbol_valuations_all_scenarios(
                db,
                import_id=import_row.id,
                symbol=snapshot.symbol,
                overrides_loader=overrides_loader,
            )
        db.commit()
        try:
            from .fundamental_signal_engine import upsert_fundamental_signal_rows

            upsert_fundamental_signal_rows(db, symbols=[snapshot.symbol for snapshot in scored_snapshots])
            db.commit()
        except Exception:
            logger.debug("fundamental signal row sync failed", exc_info=True)
            db.rollback()
        db.refresh(import_row)
        return import_row
    except Exception as exc:
        db.rollback()
        import_row = db.get(models.FundamentalImport, import_id) or import_row
        import_row.status = "failed"
        import_row.error_message = str(exc)
        import_row.completed_at = _utcnow()
        db.add(import_row)
        db.commit()
        raise


def ingest_fundamental_workbook(
    db: Session,
    *,
    dataset: models.Dataset,
    payload: bytes,
) -> models.FundamentalImport:
    run = create_import_run(db, dataset=dataset)
    return execute_import_run(db, import_id=run.id, payload=payload)


def upsert_assumptions(
    db: Session,
    *,
    scenario: str,
    assumptions: dict[str, Any],
    scope_type: str = "desk",
    scope_key: str = "GLOBAL",
    version_label: str = "base",
) -> models.FundamentalAssumptionSet:
    scope_type = scope_type.strip().lower()
    scope_key = (scope_key or "GLOBAL").strip().upper() if scope_type == "symbol" else (scope_key or "GLOBAL").strip()
    cleaned = _clean_assumptions(assumptions)
    row = (
        db.query(models.FundamentalAssumptionSet)
        .filter(
            models.FundamentalAssumptionSet.scope_type == scope_type,
            models.FundamentalAssumptionSet.scope_key == scope_key,
            models.FundamentalAssumptionSet.scenario == scenario,
            models.FundamentalAssumptionSet.version_label == version_label,
        )
        .first()
    )
    if row is None:
        row = models.FundamentalAssumptionSet(
            scope_type=scope_type,
            scope_key=scope_key,
            scenario=scenario,
            version_label=version_label,
            assumptions_json={**default_assumptions_for_scenario(scenario), "currency": "MAD", **cleaned} if scope_type == "desk" else cleaned,
            source="user",
            is_active=True,
        )
        db.add(row)
    else:
        row.assumptions_json = {**dict(row.assumptions_json or {}), **cleaned}
        row.source = "user"
        row.is_active = True
    db.flush()
    return row


def technical_context(db: Session, symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    rows = (
        db.query(models.SignalEngineGlobalResult)
        .filter(
            models.SignalEngineGlobalResult.symbol.in_(symbols),
            models.SignalEngineGlobalResult.status == "succeeded",
        )
        .order_by(
            models.SignalEngineGlobalResult.symbol.asc(),
            models.SignalEngineGlobalResult.computed_at.desc().nullslast(),
        )
        .all()
    )
    priority = {"medium": 0, "monthly": 1, "short": 2, "weekly": 3, "long": 4, "quarterly": 5}
    chosen: dict[str, models.SignalEngineGlobalResult] = {}
    for row in rows:
        existing = chosen.get(row.symbol)
        if existing is None or priority.get(row.horizon, 99) < priority.get(existing.horizon, 99):
            chosen[row.symbol] = row
    return {
        symbol.upper(): {
            "horizon": row.horizon,
            "signal_label": row.signal_label,
            "signal_score_pct": row.expanded_aggregate_score_pct if row.expanded_aggregate_score_pct is not None else row.aggregate_score_pct,
            "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        }
        for symbol, row in chosen.items()
    }


def annual_by_year(rows: list[models.FundamentalAnnualMetric]) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = defaultdict(dict)
    for row in rows:
        if row.metric_value is None:
            continue
        grouped[row.statement_year][row.metric_name] = row.metric_value
    return [
        {"statement_year": year, "metrics": metrics}
        for year, metrics in sorted(grouped.items())
        if any(value is not None for value in metrics.values())
    ]
