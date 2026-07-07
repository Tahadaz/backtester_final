from __future__ import annotations

import hashlib
import datetime as dt
import os
import uuid
from collections import defaultdict
from math import isfinite
from pathlib import Path
from statistics import median, pstdev
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.quant_core.fundamentals import DEFAULT_ASSUMPTIONS, eva, scenario_probabilities_from_assumptions
from core.quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot
from core.quant_core.fundamentals.triangulation import compute_triangulation

from .. import models
from ..auth import AppUser, optional_app_user, require_admin, require_app_user
from ..config import settings
from ..db import get_db
from ..queue import get_queue
from ..schemas.fundamentals import (
    AssumptionSetOut,
    AssumptionOverrideIn,
    AssumptionOverrideOut,
    AssumptionResolvedOut,
    AssumptionUpdateIn,
    AnnualMetricRawOut,
    CatalystCalendarOut,
    CatalystIn,
    CatalystOut,
    CatalystPatchIn,
    EnsembleOut,
    FundamentalComparableBenchmarkOut,
    FundamentalComparableMetaOut,
    FundamentalComparablePeerOut,
    FundamentalComparablesOut,
    FundamentalComparablesRequest,
    FundamentalCoverageRow,
    FundamentalImportOut,
    FundamentalLightSnapshot,
    FundamentalMethodologyOut,
    FundamentalMetricOverrideIn,
    FundamentalMetricOverrideOut,
    FundamentalProviderStatusItemOut,
    FundamentalProviderStatusOut,
    FundamentalScreenRankedRow,
    FundamentalSignalRecomputeIn,
    FundamentalSignalRecomputeOut,
    FundamentalSignalBacktestIn,
    FundamentalSignalBacktestOut,
    FundamentalSnapshotBatchIn,
    FundamentalSourceDocumentOut,
    FundamentalStockDetailOut,
    IntegrityCheckOut,
    IntegrityReportOut,
    MissingFinancialDataSummaryOut,
    MissingFinancialMetricOut,
    PillarHistoryOut,
    PeriodMetricOut,
    StockanalysisFundamentalImportIn,
    StockanalysisFundamentalImportQueuedOut,
    FundamentalUniverseRow,
    QualityIssueOut,
    TargetedBvcFundamentalImportIn,
    TargetedBvcFundamentalImportQueuedOut,
    TargetedBvcFundamentalTargetOut,
    ThesisHistoryOut,
    ThesisIn,
    ThesisOut,
    ValuationResultOut,
    YfinanceFundamentalImportIn,
    YfinanceFundamentalImportQueuedOut,
)
from ..services.consensus import load_broker_target
from ..services.fundamental_beta import recompute_universe_betas
from ..services.fundamentals import (
    CORE_STATEMENT_METRIC_GROUPS,
    SUCCEEDED_IMPORT_STATUSES,
    VALUATION_SCENARIOS,
    _table_exists,
    annual_by_year,
    annual_metric_rows_for_symbol,
    clean_assumption_override_values,
    compute_symbol_sensitivity,
    create_import_run,
    derive_research_overlay,
    enriched_snapshots_by_symbol,
    execute_import_run,
    latest_import,
    latest_imports_by_symbol,
    latest_integrity_report,
    latest_snapshot_rows_by_symbol,
    lightweight_enriched_snapshots_by_symbol,
    make_bulk_overrides_loader,
    market_price_context_by_symbol,
    methodology_payload,
    normalize_period_label,
    period_metric_rows_for_symbol,
    pillar_history_for_symbol,
    persist_pillar_history_for_import,
    current_metric_overrides,
    refresh_symbol_after_metric_override,
    recompute_symbol_valuations,
    recompute_symbol_valuations_all_scenarios,
    resolved_assumptions_with_provenance,
    rescore_universe,
    run_and_persist_fundamental_signal_backtest,
    technical_context,
    upsert_assumptions,
)
from core.quant_core.fundamentals.tearsheet import render_morning_note, render_tearsheet
from ..services.market_universe import list_signal_universe
from ..storage import put_bytes

router = APIRouter(prefix="/fundamentals", tags=["fundamentals"])

RATE_SENSITIVE_MODELS = frozenset({"fcff_dcf", "fcfe_dcf", "ddm", "residual_income"})
REQUIRED_COVERAGE_METRICS = ("Current_Price", "PER", "Price_to_Book", "ROE", "Debt_to_Equity", "FCF_Yield")
TARGETED_BVC_IGNORED_SYMBOLS = {"INSTRUMENT", "MAJ"}
FUNDAMENTAL_NON_STOCK_SYMBOLS = {"INSTRUMENT", "MAJ", "MAJJ", "WORKSHEET"}
BVC_PERIOD_TYPES = {"annual", "semiannual", "quarterly"}
BVC_DEFAULT_PERIOD_TYPES = ["annual", "semiannual", "quarterly"]
BVC_PERIOD_TYPE_ALIASES = {
    "yearly": ["annual"],
    "annuel": ["annual"],
    "annual": ["annual"],
    "semester": ["semiannual"],
    "semestriel": ["semiannual"],
    "semestre": ["semiannual"],
    "semiannual": ["semiannual"],
    "quarter": ["quarterly"],
    "quarterly": ["quarterly"],
    "trimestriel": ["quarterly"],
    "trimestre": ["quarterly"],
    "interim": ["semiannual", "quarterly"],
    "interimaire": ["semiannual", "quarterly"],
}
DEFAULT_COMPARABLE_METRICS = (
    "PER",
    "EV_to_EBITDA",
    "Price_to_Book",
    "Price_to_Sales",
    "ROE",
    "Dividend_Yield",
    "Revenue_Growth",
)
HEADLINE_SCENARIO = "base"
CORE_MISSING_METRIC_LABELS = {
    "Revenue": "Chiffre d'affaires",
    "NetIncome": "Resultat net",
    "Total_Assets": "Total actif",
    "Total_Equity": "Capitaux propres",
    "Operating_Cash_Flow": "Flux d'exploitation",
}
CORE_MISSING_METRIC_CATEGORIES = {
    "Revenue": "income",
    "NetIncome": "income",
    "Total_Assets": "balance",
    "Total_Equity": "balance",
    "Operating_Cash_Flow": "cashflow",
}
SUPPLEMENTAL_MISSING_METRIC_GROUPS: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    ("annual", "income", "EBIT", "Resultat d'exploitation", ("EBIT", "Operating_Income", "OperatingIncome", "Resultat_Exploitation")),
    ("annual", "income", "EBITDA", "EBITDA", ("EBITDA", "Normalized_EBITDA")),
    ("annual", "income", "Depreciation_Amortization", "D&A", ("Depreciation_Amortization", "DandA", "Dotations_dexploitation")),
    ("annual", "balance", "Total_Liabilities", "Total passif", ("Total_Liabilities", "Total_Passif", "Passif_Total")),
    ("annual", "balance", "Total_Debt", "Dette totale", ("Total_Debt", "Debt", "Financial_Debt", "Dette_Financiere", "Dettes")),
    ("annual", "balance", "Cash_and_Equivalents", "Tresorerie", ("Cash_and_Equivalents", "BS_Cash_and_Equivalents", "Cash", "Tresorerie")),
    ("annual", "cashflow", "Free_Cash_Flow", "Flux de tresorerie disponible", ("Free_Cash_Flow", "Levered_Free_Cash_Flow")),
    ("annual", "cashflow", "Capex", "Depenses d'investissement", ("Capex", "CAPEX", "Capital_Expenditure", "Capital_Expenditures", "Flux_tresorerie_investissement_CAPEX")),
)
LATEST_MISSING_METRIC_GROUPS: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    ("latest", "coverage", "Current_Price", "Cours actuel", ("Current_Price",)),
    ("latest", "ratios", "PER", "PER", ("PER", "Price_to_Earnings", "PE_Ratio")),
    ("latest", "ratios", "Price_to_Book", "Cours / valeur comptable", ("Price_to_Book", "P_B")),
    ("latest", "ratios", "ROE", "Rentabilite des capitaux propres", ("ROE",)),
    ("latest", "ratios", "Debt_to_Equity", "Dette / capitaux propres", ("Debt_to_Equity", "Debt_Equity")),
    ("latest", "ratios", "FCF_Yield", "Rendement FCF", ("FCF_Yield",)),
)


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _positive_num(value: Any) -> float | None:
    out = _num(value)
    return out if out is not None and out > 0 else None


def _rate_sensitive_weight_from_weights(weights: dict[str, Any] | None) -> float:
    total = 0.0
    for model in RATE_SENSITIVE_MODELS:
        value = _num((weights or {}).get(model))
        if value is not None and value > 0:
            total += value
    return max(0.0, min(1.0, total))


def _upside_from_price(fair_value: Any, current_price: Any) -> float | None:
    fair = _num(fair_value)
    current = _positive_num(current_price)
    if fair is None or current is None:
        return None
    return fair / current - 1.0


def _split_secret_list(raw: str | None) -> list[str]:
    return [item.strip() for item in (raw or "").replace(";", ",").split(",") if item.strip()]


def _normalize_period_types(values: list[str] | None, *, default_all: bool = False) -> list[str]:
    period_types = []
    default_values = BVC_DEFAULT_PERIOD_TYPES
    for value in values or default_values:
        normalized = str(value or "").strip().lower()
        for period_type in BVC_PERIOD_TYPE_ALIASES.get(normalized, [normalized]):
            if period_type in BVC_PERIOD_TYPES and period_type not in period_types:
                period_types.append(period_type)
    return period_types or list(BVC_DEFAULT_PERIOD_TYPES)


def _years_from_request(body: TargetedBvcFundamentalImportIn) -> list[int]:
    years = {int(year) for year in body.years or [] if int(year) >= 1900}
    if body.start_year is not None or body.end_year is not None:
        start = int(body.start_year or body.end_year or 1900)
        end = int(body.end_year or body.start_year or dt.date.today().year)
        if start > end:
            start, end = end, start
        years.update(range(max(1900, start), min(2100, end) + 1))
    return sorted(years)


def _import_out(row: models.FundamentalImport) -> FundamentalImportOut:
    return FundamentalImportOut(
        id=str(row.id),
        dataset_id=str(row.dataset_id) if row.dataset_id else None,
        filename=row.filename,
        source_hash=row.source_hash,
        data_source=row.data_source or "workbook",
        source_universe=row.source_universe,
        status=row.status,
        methodology_version=row.methodology_version or "v3",
        rq_job_id=row.rq_job_id,
        company_count=int(row.company_count or 0),
        symbol_count=int(row.symbol_count or 0),
        annual_metric_count=int(row.annual_metric_count or 0),
        latest_snapshot_count=int(row.latest_snapshot_count or 0),
        quality_issue_count=int(row.quality_issue_count or 0),
        summary=dict(row.summary_json or {}),
        error_message=row.error_message,
        created_at=row.created_at.isoformat() if row.created_at else "",
        imported_at=row.imported_at.isoformat() if row.imported_at else None,
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
    )


def _valuation_out(
    row: models.FundamentalValuationResult,
    *,
    current_price_override: Any = None,
) -> ValuationResultOut:
    override_price = _positive_num(current_price_override)
    current_price = override_price
    if override_price is None:
        current_price = row.current_price
    upside_pct = (
        _upside_from_price(row.fair_value, override_price)
        if override_price is not None
        else row.upside_pct
    )
    return ValuationResultOut(
        model=row.model,
        scenario=row.scenario,
        fair_value=row.fair_value,
        current_price=current_price,
        upside_pct=upside_pct,
        confidence=row.confidence,
        confidence_score=row.confidence_score,
        weight=row.weight,
        family=row.family,
        methodology=row.methodology,
        model_version=row.model_version,
        is_proxy=bool(row.is_proxy),
        data_quality_score=row.data_quality_score,
        currency=row.currency,
        inputs=dict(row.inputs_json or {}),
        outputs=dict(row.outputs_json or {}),
        warnings=list(row.warnings_json or []),
        computed_at=row.computed_at.isoformat() if row.computed_at else None,
    )


def _annual_raw_out(row: models.FundamentalAnnualMetric) -> AnnualMetricRawOut:
    override_created_at = getattr(row, "_manual_override_created_at", None)
    override_id = getattr(row, "_manual_override_id", None)
    return AnnualMetricRawOut(
        statement_year=row.statement_year,
        metric_name=row.metric_name,
        metric_value=row.metric_value,
        original_metric_value=getattr(row, "_manual_override_original_value", None),
        raw_metric_name=row.raw_metric_name,
        source_sheet=row.source_sheet,
        source_field=row.source_field,
        is_proxy=bool(row.is_proxy),
        as_of_date=row.as_of_date.isoformat() if row.as_of_date else None,
        source_document_id=row.source_document_id,
        is_overridden=override_id is not None,
        manual_override_id=int(override_id) if override_id is not None else None,
        manual_override_note=getattr(row, "_manual_override_note", None),
        manual_override_created_by=getattr(row, "_manual_override_created_by", None),
        manual_override_created_at=override_created_at.isoformat() if override_created_at else None,
    )


def _period_metric_out(row: models.FundamentalPeriodMetric) -> PeriodMetricOut:
    return PeriodMetricOut(
        fiscal_year=row.fiscal_year,
        period_type=row.period_type,
        period_label=normalize_period_label(row.period_type, row.period_label),
        metric_name=row.metric_name,
        metric_value=row.metric_value,
        raw_metric_name=row.raw_metric_name,
        period_end_date=row.period_end_date.isoformat() if row.period_end_date else None,
        source_url=row.source_url,
        document_title=row.document_title,
        source_document_id=row.source_document_id,
        is_proxy=bool(row.is_proxy),
    )


def _ensemble_out(
    row: models.FundamentalEnsembleResult | None,
    *,
    current_price_override: Any = None,
) -> EnsembleOut | None:
    if row is None:
        return None
    override_price = _positive_num(current_price_override)
    current_price = override_price
    if override_price is None:
        current_price = row.current_price
    upside_pct = (
        _upside_from_price(row.fair_value_base, override_price)
        if override_price is not None
        else row.upside_pct
    )
    model_weights = dict(row.model_weights_json or {})
    return EnsembleOut(
        symbol=row.symbol,
        scenario=row.scenario,
        fair_value_low=row.fair_value_low,
        fair_value_base=row.fair_value_base,
        fair_value_high=row.fair_value_high,
        current_price=current_price,
        upside_pct=upside_pct,
        confidence_score=row.confidence_score,
        usable_model_count=int(row.usable_model_count or 0),
        excluded_model_count=int(row.excluded_model_count or 0),
        model_weights=model_weights,
        rate_sensitive_weight=_rate_sensitive_weight_from_weights(model_weights),
        warnings=list(row.warnings_json or []),
        currency=row.currency,
        model_dispersion_low=row.model_dispersion_low,
        model_dispersion_base=row.model_dispersion_base,
        model_dispersion_high=row.model_dispersion_high,
        monte_carlo_low=row.monte_carlo_low,
        monte_carlo_base=row.monte_carlo_base,
        monte_carlo_high=row.monte_carlo_high,
        fair_value_mean=row.fair_value_mean,
        model_dispersion_cv=row.model_dispersion_cv,
        dispersion_factor=row.dispersion_factor,
        sensitivity_grids=dict(row.sensitivity_grids_json or {}) if getattr(row, "sensitivity_grids_json", None) else None,
    )


def _scenario_vintage_key(row: models.FundamentalEnsembleResult) -> str | None:
    value = row.computed_at
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    else:
        value = value.astimezone(dt.timezone.utc)
    return value.isoformat()


def _scenario_rows_are_coherent(rows_by_scenario: dict[str, models.FundamentalEnsembleResult | None]) -> bool:
    rows = {scenario: rows_by_scenario.get(scenario) for scenario in VALUATION_SCENARIOS}
    if any(row is None for row in rows.values()):
        return False
    vintages = {_scenario_vintage_key(row) for row in rows.values() if row is not None}
    if len(vintages) != 1 or None in vintages:
        return False
    values = {scenario: _num(row.fair_value_base) for scenario, row in rows.items() if row is not None}
    if all(values.get(scenario) is not None for scenario in VALUATION_SCENARIOS):
        return bool(values["bear"] <= values["base"] <= values["bull"])
    return True


def _coherent_scenario_rows(
    rows_by_scenario: dict[str, models.FundamentalEnsembleResult | None],
) -> tuple[dict[str, models.FundamentalEnsembleResult], bool]:
    rows = {
        scenario: row
        for scenario in VALUATION_SCENARIOS
        if (row := rows_by_scenario.get(scenario)) is not None
    }
    if not rows:
        return {}, False
    if _scenario_rows_are_coherent(rows):
        return rows, False
    base = rows.get(HEADLINE_SCENARIO)
    return ({HEADLINE_SCENARIO: base} if base is not None else {}, True)


def _quality_issue_out(row: models.FundamentalQualityIssue) -> QualityIssueOut:
    return QualityIssueOut(
        severity=row.severity,
        code=row.code,
        message=row.message,
        symbol=row.symbol,
        metric_name=row.metric_name,
        statement_year=row.statement_year,
        context=dict(row.context_json or {}),
    )


def _source_document_out(row: models.FundamentalSourceDocument) -> FundamentalSourceDocumentOut:
    return FundamentalSourceDocumentOut(
        id=int(row.id),
        import_id=str(row.import_id),
        symbol=row.symbol,
        company_name=row.company_name,
        document_title=row.document_title,
        source_url=row.source_url,
        publication_date=row.publication_date.isoformat() if row.publication_date else None,
        fiscal_year=row.fiscal_year,
        period_type=row.period_type,
        period_label=row.period_label,
        period_end_date=row.period_end_date.isoformat() if row.period_end_date else None,
        status=row.status,
        error_message=row.error_message,
        extracted_field_count=int(row.extracted_field_count or 0),
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


def _integrity_check_out(item: dict[str, Any]) -> IntegrityCheckOut:
    return IntegrityCheckOut(
        name=str(item.get("name") or ""),
        status=str(item.get("status") or "unavailable"),
        delta=_num(item.get("delta")),
        rel_delta=_num(item.get("rel_delta")),
        inputs={str(k): _num(v) for k, v in dict(item.get("inputs") or {}).items()},
        message=item.get("message"),
    )


def _integrity_out(row: models.FundamentalIntegrityReport | None) -> IntegrityReportOut | None:
    if row is None:
        return None
    return IntegrityReportOut(
        symbol=row.symbol,
        statement_year=int(row.statement_year),
        checks=[_integrity_check_out(item) for item in list(row.checks_json or []) if isinstance(item, dict)],
        overall_status=row.overall_status,
        confidence_haircut=float(row.confidence_haircut or 0.0),
        projected_statements=list(row.projected_statements_json or []),
        projection_checks=[_integrity_check_out(item) for item in list(row.projection_checks_json or []) if isinstance(item, dict)],
    )


def _projection_payloads_by_period_type(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
    scenario: str,
) -> dict[str, dict[str, Any]]:
    if not _table_exists(db, models.FundamentalProjection):
        return {}
    rows = (
        db.query(models.FundamentalProjection)
        .filter(
            models.FundamentalProjection.import_id == import_id,
            models.FundamentalProjection.symbol == symbol.upper(),
            models.FundamentalProjection.scenario == scenario,
        )
        .order_by(
            models.FundamentalProjection.period_type.asc(),
            models.FundamentalProjection.fiscal_year.asc(),
            models.FundamentalProjection.period_index.asc(),
            models.FundamentalProjection.line_item.asc(),
        )
        .all()
    )
    grouped: dict[str, dict[str, Any]] = {}
    statement_maps: dict[str, dict[tuple[int, int], dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        period_type = str(row.period_type or "annual")
        payload = grouped.setdefault(
            period_type,
            {
                "statements": [],
                "drivers": {},
                "fcff": [],
                "fcfe": [],
                "dividends": [],
                "book_values": [],
                "growth_decomposition": {},
                "warnings": [],
            },
        )
        evidence = dict(row.evidence_json or {})
        if str(row.line_item).startswith("driver:"):
            driver_name = str(row.line_item).split(":", 1)[1]
            payload["drivers"][driver_name] = {k: v for k, v in evidence.items() if k != "kind"}
            continue
        key = (int(row.fiscal_year), int(row.period_index or 0))
        statement = statement_maps[period_type].setdefault(
            key,
            {
                "fiscal_year": int(row.fiscal_year),
                "periods_per_year": int(row.periods_per_year or 1),
                "period_type": period_type,
                "period_index": int(row.period_index or 0),
                "period_label": str(row.period_label or "FY"),
                "period_end_date": row.period_end_date.isoformat() if row.period_end_date else None,
            },
        )
        statement[str(row.line_item)] = row.projected_value
        warnings = evidence.get("warnings")
        if isinstance(warnings, list):
            for warning in warnings:
                if isinstance(warning, str) and warning not in payload["warnings"]:
                    payload["warnings"].append(warning)
    for period_type, statements_by_key in statement_maps.items():
        statements = [statements_by_key[key] for key in sorted(statements_by_key)]
        payload = grouped[period_type]
        payload["statements"] = statements
        payload["fcff"] = [item.get("fcff") for item in statements if item.get("fcff") is not None]
        payload["fcfe"] = [item.get("fcfe") for item in statements if item.get("fcfe") is not None]
        payload["dividends"] = [item.get("dividends") for item in statements if item.get("dividends") is not None]
        payload["book_values"] = [item.get("total_equity") for item in statements if item.get("total_equity") is not None]
    return grouped


def _signal_backtest_out(row: models.FundamentalSignalBacktest) -> FundamentalSignalBacktestOut:
    return FundamentalSignalBacktestOut(
        run_id=str(row.run_id),
        signal=row.signal,
        universe=row.universe,
        rebalance=row.rebalance,
        as_of=row.as_of.isoformat() if row.as_of else None,
        status=row.status,
        error_message=row.error_message,
        quintile_returns=list(row.quintile_returns_json or []),
        ic=dict(row.ic_json or {}),
        equity_curve=list(row.equity_curve_json or []),
        turnover=list(row.turnover_json or []),
        holdings=list(row.holdings_json or []),
        params=dict(row.params_json or {}),
        warnings=list(row.warnings_json or []),
    )


def _thesis_out(row: models.FundamentalThesis | None, *, warnings: list[str] | None = None) -> ThesisOut | None:
    if row is None:
        return None
    return ThesisOut(
        id=int(row.id),
        symbol=row.symbol,
        as_of=row.as_of.isoformat() if row.as_of else None,
        direction=row.direction,
        conviction=row.conviction,
        core_thesis=row.core_thesis,
        bullish_drivers=list(row.bullish_drivers_json or []),
        bearish_drivers=list(row.bearish_drivers_json or []),
        target_price=row.target_price,
        target_horizon_months=row.target_horizon_months,
        stop_price=row.stop_price,
        invalidation_conditions=list(row.invalidation_conditions_json or []),
        linked_catalyst_ids=list(row.linked_catalyst_ids_json or []),
        created_by=row.created_by,
        created_at=row.created_at.isoformat() if row.created_at else None,
        is_current=bool(row.is_current),
        warnings=warnings or [],
    )


def _catalyst_out(row: models.FundamentalCatalyst) -> CatalystOut:
    return CatalystOut(
        id=int(row.id),
        symbol=row.symbol,
        event_type=row.event_type,
        event_date=row.event_date.isoformat() if row.event_date else "",
        event_date_confidence=row.event_date_confidence,
        impact_tier=row.impact_tier,
        expected_direction=row.expected_direction,
        title=row.title,
        notes=row.notes,
        source=row.source,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        is_active=bool(row.is_active),
        superseded_by_id=int(row.superseded_by_id) if row.superseded_by_id else None,
    )


def _parse_date(raw: str | None, *, default: dt.date | None = None) -> dt.date:
    if not raw:
        if default is not None:
            return default
        raise HTTPException(status_code=422, detail="date is required")
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid date: {raw}") from exc


def _current_thesis(db: Session, symbol: str) -> models.FundamentalThesis | None:
    return (
        db.query(models.FundamentalThesis)
        .filter(models.FundamentalThesis.symbol == symbol.upper(), models.FundamentalThesis.is_current.is_(True))
        .order_by(models.FundamentalThesis.created_at.desc())
        .first()
    )


def _scenario_or_422(scenario: str) -> str:
    normalized = (scenario or "base").strip().lower()
    if normalized not in VALUATION_SCENARIOS:
        raise HTTPException(status_code=422, detail=f"scenario must be one of {', '.join(VALUATION_SCENARIOS)}")
    return normalized


def _scenario_or_auto(scenario: str) -> str:
    normalized = (scenario or HEADLINE_SCENARIO).strip().lower()
    if normalized == "auto":
        return HEADLINE_SCENARIO
    return _scenario_or_422(normalized)


def _fundamental_recompute_scenarios(scenario: str) -> list[str]:
    normalized = (scenario or "all").strip().lower()
    if normalized == "all":
        return list(VALUATION_SCENARIOS)
    return [_scenario_or_422(normalized)]


def _sync_fundamental_signal_rows(db: Session, symbols: list[str]) -> dict[str, int]:
    clean_symbols = sorted({str(symbol or "").strip().upper() for symbol in symbols if str(symbol or "").strip()})
    if not clean_symbols:
        return {"total": 0, "succeeded": 0, "failed": 0}
    from ..services.fundamental_signal_engine import upsert_fundamental_signal_rows

    return upsert_fundamental_signal_rows(db, symbols=clean_symbols)


def _auto_scenario_from_ensembles(
    ensembles: dict[str, models.FundamentalEnsembleResult | EnsembleOut | None],
    *,
    current_price: Any,
) -> str:
    current = _num(current_price)
    candidates: list[tuple[float, int, str]] = []
    tie_breaker = {"base": 0, "bear": 1, "bull": 2}
    for scenario_key in VALUATION_SCENARIOS:
        ensemble = ensembles.get(scenario_key)
        if ensemble is None:
            continue
        fair_value = _num(getattr(ensemble, "fair_value_base", None))
        scenario_current = current if current is not None else _num(getattr(ensemble, "current_price", None))
        if fair_value is None or scenario_current is None:
            continue
        candidates.append((abs(fair_value - scenario_current), tie_breaker.get(scenario_key, 99), scenario_key))
    if not candidates:
        return "base"
    return min(candidates)[2]


def _scenario_probabilities_payload(assumptions: dict[str, Any]) -> dict[str, float]:
    try:
        return scenario_probabilities_from_assumptions(assumptions)
    except Exception:
        return scenario_probabilities_from_assumptions(DEFAULT_ASSUMPTIONS)


def _assumption_warnings_payload(assumptions: dict[str, Any]) -> list[str]:
    raw = assumptions.get("scenario_probability_warnings")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item)]


def _headline_overlay(
    db: Session,
    *,
    symbol: str,
    viewed_scenario: str,
    base_ensemble: models.FundamentalEnsembleResult | None,
    import_row: models.FundamentalImport | None,
    current_price: Any,
    market_implied_scenario: str | None = None,
    free_float_pct: float | None = None,
) -> dict[str, Any]:
    overlay = derive_research_overlay(
        db,
        symbol=symbol,
        scenario=HEADLINE_SCENARIO,
        ensemble=base_ensemble,
        import_row=import_row,
        current_price=current_price,
        free_float_pct=free_float_pct,
    )
    if base_ensemble is None:
        overlay.update(
            {
                "recommendation": "NR",
                "target_price": None,
                "conviction": 0,
                "revision_direction": "=",
            }
        )
    overlay.update(
        {
            "headline_scenario": HEADLINE_SCENARIO,
            "viewed_scenario": viewed_scenario,
            "market_implied_scenario": market_implied_scenario,
        }
    )
    return overlay


def _created_by(user: AppUser) -> str:
    return (user.email or user.id or "api").strip() or "api"


def _current_assumption_override(
    db: Session,
    *,
    symbol: str,
    scenario: str,
) -> models.FundamentalAssumptionOverride | None:
    return (
        db.query(models.FundamentalAssumptionOverride)
        .filter(
            models.FundamentalAssumptionOverride.symbol == symbol.upper(),
            models.FundamentalAssumptionOverride.scenario == _scenario_or_422(scenario),
            models.FundamentalAssumptionOverride.is_current.is_(True),
        )
        .order_by(models.FundamentalAssumptionOverride.created_at.desc(), models.FundamentalAssumptionOverride.id.desc())
        .first()
    )


def _assumption_override_out(row: models.FundamentalAssumptionOverride) -> AssumptionOverrideOut:
    return AssumptionOverrideOut(
        id=int(row.id),
        symbol=row.symbol,
        scenario=row.scenario,
        overrides=clean_assumption_override_values(dict(row.overrides or {})),
        note=row.note,
        created_by=row.created_by,
        created_at=row.created_at.isoformat() if row.created_at else None,
        is_current=bool(row.is_current),
    )


def _metric_override_out(row: models.FundamentalMetricOverride) -> FundamentalMetricOverrideOut:
    return FundamentalMetricOverrideOut(
        id=int(row.id),
        symbol=row.symbol,
        statement_year=int(row.statement_year),
        metric_name=row.metric_name,
        metric_value=row.metric_value,
        note=row.note,
        created_by=row.created_by,
        created_at=row.created_at.isoformat() if row.created_at else None,
        is_current=bool(row.is_current),
    )


def _ensure_known_fundamental_symbol(db: Session, symbol: str) -> None:
    normalized = symbol.upper()
    if _metadata_by_symbol(db, [normalized]).get(normalized):
        return
    if latest_snapshot_rows_by_symbol(db, symbols=[normalized]).get(normalized) is not None:
        return
    raise HTTPException(status_code=404, detail=f"No fundamentals for {normalized}")


def _assumption_bundle(
    db: Session,
    *,
    symbol: str,
    sector: str | None,
    selected_scenario: str,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    selected_scenario = _scenario_or_422(selected_scenario)
    overrides_loader = make_bulk_overrides_loader(db, [symbol])
    selected_assumptions: dict[str, Any] = {}
    provenance_by_scenario: dict[str, dict[str, str]] = {}
    for scenario_key in VALUATION_SCENARIOS:
        assumptions, provenance = resolved_assumptions_with_provenance(
            db,
            symbol=symbol,
            sector=sector,
            scenario=scenario_key,
            overrides_loader=overrides_loader,
        )
        provenance_by_scenario[scenario_key] = provenance
        if scenario_key == selected_scenario:
            selected_assumptions = assumptions
    return selected_assumptions, provenance_by_scenario


def _latest_integrity_model(db: Session, snapshot: models.FundamentalLatestSnapshot) -> models.FundamentalIntegrityReport | None:
    query = db.query(models.FundamentalIntegrityReport).filter(
        models.FundamentalIntegrityReport.import_id == snapshot.import_id,
        models.FundamentalIntegrityReport.symbol == snapshot.symbol,
    )
    if snapshot.latest_statement_year is not None:
        query = query.filter(models.FundamentalIntegrityReport.statement_year == snapshot.latest_statement_year)
    return query.order_by(models.FundamentalIntegrityReport.statement_year.desc()).first()


def _upcoming_catalysts(db: Session, symbol: str, *, limit: int = 10) -> list[models.FundamentalCatalyst]:
    today = dt.date.today()
    return (
        db.query(models.FundamentalCatalyst)
        .filter(
            models.FundamentalCatalyst.symbol == symbol.upper(),
            models.FundamentalCatalyst.is_active.is_(True),
            models.FundamentalCatalyst.event_date >= today,
        )
        .order_by(models.FundamentalCatalyst.event_date.asc(), models.FundamentalCatalyst.id.asc())
        .limit(limit)
        .all()
    )


def _clean_text(value: str) -> str:
    return "".join(ch for ch in str(value or "").strip() if ch == "\n" or ch == "\t" or ord(ch) >= 32)


def _validate_driver_list(items: list[Any], field_name: str) -> list[dict[str, Any]]:
    if not 1 <= len(items) <= 6:
        raise HTTPException(status_code=422, detail=f"{field_name} must have 1 to 6 items")
    out: list[dict[str, Any]] = []
    for item in items:
        data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        title = _clean_text(data.get("title") or "")
        detail = _clean_text(data.get("detail") or "")
        if not title or len(title) > 100:
            raise HTTPException(status_code=422, detail=f"{field_name}.title must be 1 to 100 chars")
        if not detail or len(detail) > 600:
            raise HTTPException(status_code=422, detail=f"{field_name}.detail must be 1 to 600 chars")
        out.append({"title": title, "detail": detail, "pillar": data.get("pillar")})
    return out


def _validate_thesis_body(db: Session, symbol: str, body: ThesisIn) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    core_thesis = _clean_text(body.core_thesis)
    if len(core_thesis) < 30 or len(core_thesis) > 2000:
        raise HTTPException(status_code=422, detail="core_thesis must be 30 to 2000 chars")
    if body.target_price is not None and body.target_price <= 0:
        raise HTTPException(status_code=422, detail="target_price must be positive")
    if body.stop_price is not None and body.stop_price <= 0:
        raise HTTPException(status_code=422, detail="stop_price must be positive")
    if body.target_horizon_months is not None and not (1 <= int(body.target_horizon_months) <= 60):
        raise HTTPException(status_code=422, detail="target_horizon_months must be 1 to 60")
    if body.direction == "long" and body.target_price is not None and body.stop_price is not None:
        snapshot = latest_snapshot_rows_by_symbol(db, symbols=[symbol]).get(symbol.upper())
        current_price = None
        if snapshot is not None:
            current_price = _num((snapshot.metrics_json or {}).get("Current_Price"))
        if current_price is None:
            warnings.append("current_price_unknown: target/stop ordering not fully verified")
        elif not (body.target_price > current_price > body.stop_price):
            raise HTTPException(status_code=422, detail="long thesis requires target_price > current_price > stop_price")
    as_of = _parse_date(body.as_of, default=dt.date.today()) if body.as_of else dt.date.today()
    return (
        {
            "as_of": as_of,
            "direction": body.direction,
            "conviction": body.conviction,
            "core_thesis": core_thesis,
            "bullish_drivers_json": _validate_driver_list(body.bullish_drivers, "bullish_drivers"),
            "bearish_drivers_json": _validate_driver_list(body.bearish_drivers, "bearish_drivers"),
            "target_price": body.target_price,
            "target_horizon_months": body.target_horizon_months,
            "stop_price": body.stop_price,
            "invalidation_conditions_json": [item.model_dump() for item in body.invalidation_conditions],
            "linked_catalyst_ids_json": [int(item) for item in body.linked_catalyst_ids],
        },
        warnings,
    )


def _metadata_by_symbol(db: Session, symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    rows = db.query(models.StockMaster).filter(models.StockMaster.symbol.in_(symbols)).all()
    return {
        row.symbol: {
            "display_name": row.display_name,
            "sector": row.sector,
            "market_region": row.market_region,
        }
        for row in rows
    }


def _valuation_summary(
    rows: list[models.FundamentalValuationResult],
    ensemble: models.FundamentalEnsembleResult | None,
    *,
    snapshot_import_id: uuid.UUID | None = None,
    current_price_override: Any = None,
) -> dict[str, Any]:
    confidence_by_model = {row.model: row.confidence for row in rows}
    valuation_import_id = ensemble.import_id if ensemble else None
    is_stale = bool(snapshot_import_id is not None and valuation_import_id is not None and valuation_import_id != snapshot_import_id)
    consensus_upside = None
    if ensemble is not None:
        override_price = _positive_num(current_price_override)
        consensus_upside = (
            _upside_from_price(ensemble.fair_value_base, override_price)
            if override_price is not None
            else ensemble.upside_pct
        )
    model_weights = dict(ensemble.model_weights_json or {}) if ensemble else {}
    return {
        "model_count": len(rows),
        "usable_model_count": int(ensemble.usable_model_count or 0) if ensemble else 0,
        "excluded_model_count": int(ensemble.excluded_model_count or 0) if ensemble else len(rows),
        "consensus_fair_value": ensemble.fair_value_base if ensemble else None,
        "consensus_upside_pct": consensus_upside,
        "confidence_score": ensemble.confidence_score if ensemble else None,
        "confidence_by_model": confidence_by_model,
        "model_weights": model_weights,
        "rate_sensitive_weight": _rate_sensitive_weight_from_weights(model_weights),
        "snapshot_import_id": str(snapshot_import_id) if snapshot_import_id else None,
        "valuation_import_id": str(valuation_import_id) if valuation_import_id else None,
        "valuation_source": "latest_available" if is_stale else "latest_snapshot" if valuation_import_id else "missing",
        "is_stale": is_stale,
    }


def _latest_available_valuation_bundle(
    db: Session,
    symbols: list[str],
    scenario: str,
) -> tuple[dict[str, models.FundamentalEnsembleResult], dict[str, list[models.FundamentalValuationResult]]]:
    normalized_symbols = sorted({symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()})
    if not normalized_symbols:
        return {}, {}

    ensemble_rows = (
        db.query(models.FundamentalEnsembleResult, models.FundamentalImport)
        .join(models.FundamentalImport, models.FundamentalEnsembleResult.import_id == models.FundamentalImport.id)
        .filter(
            models.FundamentalEnsembleResult.symbol.in_(normalized_symbols),
            models.FundamentalEnsembleResult.scenario == scenario,
            models.FundamentalImport.status.in_(SUCCEEDED_IMPORT_STATUSES),
        )
        .order_by(
            models.FundamentalEnsembleResult.symbol.asc(),
            models.FundamentalImport.completed_at.desc().nullslast(),
            models.FundamentalImport.imported_at.desc().nullslast(),
            models.FundamentalImport.created_at.desc(),
        )
        .all()
    )
    ensemble_by_symbol: dict[str, models.FundamentalEnsembleResult] = {}
    import_id_by_symbol: dict[str, uuid.UUID] = {}
    for ensemble, _import_row in ensemble_rows:
        if ensemble.symbol in ensemble_by_symbol:
            continue
        ensemble_by_symbol[ensemble.symbol] = ensemble
        import_id_by_symbol[ensemble.symbol] = ensemble.import_id

    if not ensemble_by_symbol:
        return {}, {}

    valuation_rows = (
        db.query(models.FundamentalValuationResult)
        .filter(
            models.FundamentalValuationResult.symbol.in_(list(ensemble_by_symbol)),
            models.FundamentalValuationResult.import_id.in_(set(import_id_by_symbol.values())),
            models.FundamentalValuationResult.scenario == scenario,
        )
        .order_by(models.FundamentalValuationResult.symbol.asc(), models.FundamentalValuationResult.family.asc(), models.FundamentalValuationResult.model.asc())
        .all()
    )
    valuations_by_symbol: dict[str, list[models.FundamentalValuationResult]] = defaultdict(list)
    for row in valuation_rows:
        if import_id_by_symbol.get(row.symbol) == row.import_id:
            valuations_by_symbol[row.symbol].append(row)

    return ensemble_by_symbol, valuations_by_symbol


def _ensembles_by_scenario(
    db: Session,
    *,
    import_id: uuid.UUID | None,
    symbol: str,
    current_price_override: Any = None,
    allow_fallback: bool = True,
) -> tuple[dict[str, EnsembleOut], bool]:
    symbol = symbol.upper()
    rows: list[models.FundamentalEnsembleResult] = []
    if import_id is not None:
        rows = (
            db.query(models.FundamentalEnsembleResult)
            .filter(
                models.FundamentalEnsembleResult.import_id == import_id,
                models.FundamentalEnsembleResult.symbol == symbol,
                models.FundamentalEnsembleResult.scenario.in_(list(VALUATION_SCENARIOS)),
            )
            .all()
        )
    coherent_rows, scenario_trio_stale = _coherent_scenario_rows({row.scenario: row for row in rows})
    out = {
        row.scenario: rendered
        for row in coherent_rows.values()
        if (rendered := _ensemble_out(row, current_price_override=current_price_override)) is not None
    }
    for scenario_key in VALUATION_SCENARIOS:
        if scenario_key in out:
            continue
        if scenario_trio_stale or not allow_fallback:
            continue
        fallback_ensembles, _fallback_valuations = _latest_available_valuation_bundle(db, [symbol], scenario_key)
        rendered = _ensemble_out(fallback_ensembles.get(symbol), current_price_override=current_price_override)
        if rendered is not None:
            out[scenario_key] = rendered
    return out, scenario_trio_stale


def _ensure_latest_symbol_valuations(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
    scenario: str,
) -> None:
    symbol = symbol.upper()
    if scenario != "auto":
        _scenario_or_422(scenario)
    scenarios = list(VALUATION_SCENARIOS)
    _lock_symbol_valuation_refresh(db, import_id=import_id, symbol=symbol)
    existing_rows = (
        db.query(models.FundamentalEnsembleResult)
        .filter(
            models.FundamentalEnsembleResult.import_id == import_id,
            models.FundamentalEnsembleResult.symbol == symbol,
            models.FundamentalEnsembleResult.scenario.in_(scenarios),
        )
        .all()
    )
    existing = {str(row.scenario) for row in existing_rows}
    existing_by_scenario = {str(row.scenario): row for row in existing_rows}
    stale = [
        str(row.scenario)
        for row in existing_rows
        if _stale_valuation_ensemble(row)
    ]
    needed = [item for item in scenarios if item not in existing]
    for item in stale:
        if item not in needed:
            needed.append(item)
    if existing_rows and not _scenario_rows_are_coherent(existing_by_scenario):
        needed = list(scenarios)
    if not needed:
        return
    overrides_loader = make_bulk_overrides_loader(db, [symbol])
    recompute_symbol_valuations_all_scenarios(
        db,
        import_id=import_id,
        symbol=symbol,
        scenarios=scenarios,
        overrides_loader=overrides_loader,
    )
    db.commit()


def _stale_valuation_ensemble(row: models.FundamentalEnsembleResult) -> bool:
    warnings = [str(warning) for warning in (row.warnings_json or [])]
    if any(warning.startswith("withheld_") for warning in warnings):
        return True
    return bool(row.fair_value_base is None and row.model_dispersion_base is not None)


def _lock_symbol_valuation_refresh(db: Session, *, import_id: uuid.UUID, symbol: str) -> None:
    try:
        bind = db.get_bind()
        if bind.dialect.name != "postgresql":
            return
        db.query(models.FundamentalLatestSnapshot.id).filter(
            models.FundamentalLatestSnapshot.import_id == import_id,
            models.FundamentalLatestSnapshot.symbol == symbol.upper(),
        ).with_for_update().one_or_none()
    except SQLAlchemyError:
        return


def _filter_universe_rows(
    rows: list[FundamentalUniverseRow],
    *,
    market_region: str | None = None,
    sector: str | None = None,
    search: str | None = None,
) -> list[FundamentalUniverseRow]:
    region_filter = (market_region or "").strip().lower()
    sector_filter = (sector or "").strip().lower()
    query = (search or "").strip().lower()
    out: list[FundamentalUniverseRow] = []
    for row in rows:
        if region_filter and (row.market_region or "").lower() != region_filter:
            continue
        if sector_filter and (row.sector or "").lower() != sector_filter:
            continue
        if query:
            haystack = " ".join(
                value
                for value in (
                    row.symbol,
                    row.company_name,
                    row.display_name,
                    row.sector,
                    row.market_region,
                )
                if value
            ).lower()
            if query not in haystack:
                continue
        out.append(row)
    return out


def _comparable_number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _positive_comparable_number(value: Any) -> float | None:
    out = _comparable_number(value)
    return out if out is not None and out > 0 else None


def _clean_comparable_symbols(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        symbol = str(raw or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _comparable_metric_keys(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values or list(DEFAULT_COMPARABLE_METRICS):
        key = str(raw or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out or list(DEFAULT_COMPARABLE_METRICS)


def _comparable_component_shares(body: FundamentalComparablesRequest) -> dict[str, float]:
    out: dict[str, float] = {}
    for raw_symbol, raw_shares in dict(body.component_shares or {}).items():
        symbol = str(raw_symbol or "").strip().upper()
        shares = _positive_comparable_number(raw_shares)
        if symbol and shares is not None:
            out[symbol] = shares
    for component in body.components or []:
        symbol = str(component.symbol or "").strip().upper()
        shares = _positive_comparable_number(component.shares)
        if symbol and shares is not None:
            out[symbol] = shares
    return out


def _nullable_median(values: list[float]) -> float | None:
    return float(median(values)) if values else None


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(len(ordered) - 1, lo + 1)
    frac = pos - lo
    return float(ordered[lo] * (1.0 - frac) + ordered[hi] * frac)


def _metric_stats(values: list[float]) -> dict[str, float | int | None]:
    clean = [float(value) for value in values if _comparable_number(value) is not None]
    return {
        "max": max(clean) if clean else None,
        "p75": _quantile(clean, 0.75),
        "median": _quantile(clean, 0.50),
        "p25": _quantile(clean, 0.25),
        "min": min(clean) if clean else None,
        "n": len(clean),
    }


def _weighted_average_for_rows(
    rows: list[dict[str, Any]],
    metric_key: str,
    *,
    exclude_symbol: str | None = None,
) -> float | None:
    total_weight = 0.0
    weighted_sum = 0.0
    for row in rows:
        if exclude_symbol and row["symbol"] == exclude_symbol:
            continue
        value = _comparable_number(row["metrics"].get(metric_key))
        weight = _positive_comparable_number(row["weights"].get(metric_key))
        if value is None or weight is None:
            continue
        total_weight += weight
        weighted_sum += value * weight
    return weighted_sum / total_weight if total_weight > 0 else None


def _latest_run(db: Session) -> models.FundamentalImport | None:
    return latest_import(db)


def _latest_succeeded_or_404(db: Session) -> models.FundamentalImport:
    row = latest_import(db)
    if row is None:
        raise HTTPException(status_code=404, detail="No succeeded fundamental import found")
    return row


def _latest_snapshot_or_404(
    db: Session,
    symbol: str,
) -> tuple[models.FundamentalLatestSnapshot, models.FundamentalImport]:
    symbol = symbol.upper()
    snapshots = latest_snapshot_rows_by_symbol(db, symbols=[symbol])
    snapshot = snapshots.get(symbol)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"No fundamentals for {symbol}")
    import_row = db.get(models.FundamentalImport, snapshot.import_id)
    if import_row is None:
        raise HTTPException(status_code=404, detail=f"No import for {symbol}")
    return snapshot, import_row


def _coverage_pct(coverage: dict[str, Any]) -> float | None:
    raw = coverage.get("coverage_pct")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    metric_count = coverage.get("metric_count")
    try:
        if metric_count is None:
            return None
        return min(1.0, max(0.0, float(metric_count) / 20.0))
    except (TypeError, ValueError):
        return None


def _metric_key(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _has_metric_value(metrics: dict[str, Any], aliases: tuple[str, ...]) -> bool:
    normalized = {_metric_key(key): value for key, value in metrics.items()}
    for alias in aliases:
        value = metrics.get(alias)
        if _num(value) is not None:
            return True
        normalized_value = normalized.get(_metric_key(alias))
        if _num(normalized_value) is not None:
            return True
    return False


def _annual_metric_values_for_year(
    rows: list[models.FundamentalAnnualMetric],
    statement_year: int | None,
) -> dict[str, Any]:
    if statement_year is None:
        return {}
    out: dict[str, Any] = {}
    for row in rows:
        if row.statement_year == statement_year:
            out[str(row.metric_name)] = row.metric_value
    return out


def _missing_financial_check_specs() -> list[tuple[str, str, str, str, tuple[str, ...]]]:
    specs: list[tuple[str, str, str, str, tuple[str, ...]]] = []
    for group in CORE_STATEMENT_METRIC_GROUPS:
        primary = str(group[0])
        specs.append(
            (
                "annual",
                CORE_MISSING_METRIC_CATEGORIES.get(primary, "summary"),
                primary,
                CORE_MISSING_METRIC_LABELS.get(primary, primary),
                tuple(str(item) for item in group),
            )
        )
    specs.extend(SUPPLEMENTAL_MISSING_METRIC_GROUPS)
    specs.extend(LATEST_MISSING_METRIC_GROUPS)
    return specs


def _missing_financial_data_summary(
    *,
    latest_metrics: dict[str, Any],
    annual_rows: list[models.FundamentalAnnualMetric],
    statement_year: int | None,
) -> MissingFinancialDataSummaryOut:
    annual_years = [int(row.statement_year) for row in annual_rows if row.statement_year is not None]
    target_year = int(statement_year) if statement_year is not None else max(annual_years) if annual_years else None
    if target_year is None:
        return MissingFinancialDataSummaryOut()

    annual_metrics = _annual_metric_values_for_year(annual_rows, target_year)
    items: list[MissingFinancialMetricOut] = []
    seen: set[tuple[str, str]] = set()
    for scope, category, metric_name, label, aliases in _missing_financial_check_specs():
        key = (scope, metric_name)
        if key in seen:
            continue
        seen.add(key)
        source_metrics = latest_metrics if scope == "latest" else annual_metrics
        if _has_metric_value(source_metrics, aliases):
            continue
        items.append(
            MissingFinancialMetricOut(
                statement_year=target_year,
                metric_name=metric_name,
                label=label,
                category=category,
                scope="latest" if scope == "latest" else "annual",
                aliases=list(aliases),
            )
        )

    categories: dict[str, int] = defaultdict(int)
    latest_missing = 0
    annual_missing = 0
    for item in items:
        categories[item.category] += 1
        if item.scope == "latest":
            latest_missing += 1
        else:
            annual_missing += 1
    return MissingFinancialDataSummaryOut(
        statement_year=target_year,
        total_missing=len(items),
        latest_missing=latest_missing,
        annual_missing=annual_missing,
        categories=dict(categories),
        items=items,
    )


def _confidence_label(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    if score > 0:
        return "low"
    return "unavailable"


SCREEN_NAMES = {"magic_formula", "peg_garp", "altman_z", "eva", "regression_adj"}
VISIBLE_FACTOR_SCORE_KEYS = ("value", "quality", "quality_components")
VISIBLE_FACTOR_SCORE_SCOPE_KEYS = {"value", "quality"}
VISIBLE_FACTOR_METRIC_KEYS = {
    "PER",
    "Price_to_Book",
    "Price_to_Sales",
    "EV_to_EBITDA",
    "FCF_Yield",
    "Dividend_Yield",
    "ROE",
    "ROA",
    "Operating_Margin",
    "Net_Margin",
    "FCF_Margin",
    "Operating_CF_Margin",
    "CAF_Margin",
    "Interest_Coverage",
    "Debt_to_Equity",
    "NetDebt_to_EBITDA",
    "Current_Ratio",
    "Cash_Ratio",
    "Equity_Multiplier",
    "Asset_Turnover",
}


def _visible_factor_scores(scores: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(scores or {})
    return {key: raw.get(key) for key in VISIBLE_FACTOR_SCORE_KEYS if key in raw}


def _visible_factor_diagnostics(diagnostics: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(diagnostics or {})
    scopes = raw.get("score_scopes")
    if isinstance(scopes, dict):
        raw["score_scopes"] = {
            key: value
            for key, value in scopes.items()
            if key in VISIBLE_FACTOR_SCORE_SCOPE_KEYS
        }
    breakdown = raw.get("metric_breakdown")
    if isinstance(breakdown, dict):
        raw["metric_breakdown"] = {
            key: value
            for key, value in breakdown.items()
            if key in VISIBLE_FACTOR_METRIC_KEYS
        }
    return raw


def _screens_from_diagnostics(diagnostics: dict[str, Any] | None) -> dict[str, Any]:
    raw = (diagnostics or {}).get("screens")
    return dict(raw) if isinstance(raw, dict) else {}


def _snapshot_for_detail_screens(
    snapshot: models.FundamentalLatestSnapshot,
    enriched_snapshot: FundamentalSnapshot | None,
) -> FundamentalSnapshot:
    if enriched_snapshot is not None:
        return enriched_snapshot
    return FundamentalSnapshot(
        symbol=snapshot.symbol,
        company_name=snapshot.company_name,
        latest_statement_year=snapshot.latest_statement_year,
        metrics=dict(snapshot.metrics_json or {}),
        scores=dict(snapshot.scores_json or {}),
        diagnostics=dict(snapshot.diagnostics_json or {}),
        coverage=dict(snapshot.coverage_json or {}),
        model_eligibility=dict(snapshot.model_eligibility_json or {}),
        source=dict(snapshot.source_json or {}),
        as_of_date=snapshot.as_of_date,
        source_document_id=snapshot.source_document_id,
    )


def _annual_rows_for_detail_screens(rows: list[models.FundamentalAnnualMetric]) -> list[AnnualMetricRow]:
    return [
        AnnualMetricRow(
            symbol=row.symbol,
            company_name=row.company_name,
            statement_year=row.statement_year,
            metric_name=row.metric_name,
            metric_value=row.metric_value,
            raw_metric_name=row.raw_metric_name,
            source_sheet=row.source_sheet,
            source_field=row.source_field,
            is_proxy=bool(row.is_proxy),
            as_of_date=row.as_of_date,
            source_document_id=row.source_document_id,
        )
        for row in rows
    ]


def _overlay_detail_eva_screen(
    *,
    snapshot: models.FundamentalLatestSnapshot,
    enriched_snapshot: FundamentalSnapshot | None,
    annual_rows: list[models.FundamentalAnnualMetric],
    assumptions: dict[str, Any],
    sector: str | None,
    diagnostics: dict[str, Any],
    screens: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    eva_screen = eva(
        _snapshot_for_detail_screens(snapshot, enriched_snapshot),
        _annual_rows_for_detail_screens(annual_rows),
        assumptions,
        sector,
    )
    next_screens = dict(screens)
    next_screens["eva"] = eva_screen
    next_diagnostics = dict(diagnostics)
    diagnostic_screens = _screens_from_diagnostics(next_diagnostics)
    diagnostic_screens["eva"] = eva_screen
    next_diagnostics["screens"] = diagnostic_screens
    return next_diagnostics, next_screens


def _screen_score(screens: dict[str, Any], screen_name: str) -> float | None:
    raw = screens.get(screen_name)
    if not isinstance(raw, dict):
        return None
    value = raw.get("score")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _peg_value(screens: dict[str, Any]) -> float | None:
    raw = screens.get("peg_garp")
    if not isinstance(raw, dict):
        return None
    try:
        value = raw.get("peg")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _altman_zone(screens: dict[str, Any]) -> str | None:
    raw = screens.get("altman_z")
    if not isinstance(raw, dict):
        return None
    zone = raw.get("zone")
    return str(zone) if zone is not None else None


def _regression_richness_avg(screens: dict[str, Any]) -> float | None:
    raw = screens.get("regression_adj")
    if not isinstance(raw, dict):
        return None
    direct = raw.get("mean_richness_z")
    if direct is not None:
        try:
            return float(direct)
        except (TypeError, ValueError):
            return None
    richness = raw.get("regression_richness")
    if not isinstance(richness, dict):
        return None
    values = []
    for item in richness.values():
        if isinstance(item, dict):
            value = item.get("richness_z")
            try:
                if value is not None:
                    values.append(float(value))
            except (TypeError, ValueError):
                continue
    return sum(values) / len(values) if values else None


def _targeted_bvc_targets(
    db: Session,
    *,
    symbols: list[str],
    sectors: list[str] | None = None,
    include_mapping_repairs: bool,
    include_complete: bool = False,
) -> list[TargetedBvcFundamentalTargetOut]:
    requested = sorted({item.strip().upper() for item in symbols if item and item.strip()})
    sector_filter = sorted({item.strip().lower() for item in sectors or [] if item and item.strip()})
    query = db.query(models.StockMaster).filter(models.StockMaster.is_active.is_(True))
    if requested:
        query = query.filter(models.StockMaster.symbol.in_(requested))
    elif sector_filter:
        query = query.filter(func.lower(models.StockMaster.sector).in_(sector_filter))
    else:
        query = query.filter(
            (models.StockMaster.market_region == "masi")
            | (models.StockMaster.market_region.is_(None))
        )
    stock_rows = query.order_by(models.StockMaster.symbol.asc()).all()
    snapshots = latest_snapshot_rows_by_symbol(db, symbols=[row.symbol for row in stock_rows] if stock_rows else None)

    out: list[TargetedBvcFundamentalTargetOut] = []
    for stock in stock_rows:
        symbol = str(stock.symbol).upper()
        if symbol in TARGETED_BVC_IGNORED_SYMBOLS:
            continue
        if stock.market_region in {"us", "european", "asian"}:
            continue
        snapshot = snapshots.get(symbol)
        metrics = dict(snapshot.metrics_json or {}) if snapshot is not None else {}
        missing_metrics = [metric for metric in REQUIRED_COVERAGE_METRICS if metrics.get(metric) is None]
        has_snapshot = snapshot is not None
        has_annual = False
        if snapshot is not None:
            has_annual = (
                db.query(models.FundamentalAnnualMetric.id)
                .filter(
                    models.FundamentalAnnualMetric.import_id == snapshot.import_id,
                    models.FundamentalAnnualMetric.symbol == symbol,
                )
                .first()
                is not None
            )
        reason = ""
        if not has_snapshot:
            reason = "no_snapshot"
        elif missing_metrics:
            reason = "missing_metrics"
        elif include_mapping_repairs and symbol in {"DYT", "GTM", "IBC", "SAH", "SNP", "ZDJ"}:
            reason = "mapping_repair"
        elif include_complete:
            reason = "selected"
        if reason:
            out.append(
                TargetedBvcFundamentalTargetOut(
                    symbol=symbol,
                    display_name=stock.display_name,
                    market_region=stock.market_region,
                    reason=reason,
                    missing_metrics=missing_metrics,
                    has_snapshot=has_snapshot,
                    has_annual=has_annual,
                )
            )
    return out


def _stockanalysis_candidate_symbols(db: Session, *, symbols: list[str], missing_only: bool) -> list[str]:
    requested = sorted({item.strip().upper() for item in symbols if item and item.strip()} - FUNDAMENTAL_NON_STOCK_SYMBOLS)
    query = db.query(models.StockMaster).filter(
        models.StockMaster.is_active.is_(True),
        models.StockMaster.market_region == "masi",
        ~models.StockMaster.symbol.in_(FUNDAMENTAL_NON_STOCK_SYMBOLS),
    )
    if requested:
        query = query.filter(models.StockMaster.symbol.in_(requested))
    stock_rows = query.order_by(models.StockMaster.symbol.asc()).all()
    out = [str(row.symbol).upper() for row in stock_rows]
    if not missing_only or not out:
        return out

    snapshots = latest_snapshot_rows_by_symbol(db, symbols=out, scope="masi")
    missing: list[str] = []
    for symbol in out:
        snapshot = snapshots.get(symbol)
        if snapshot is None:
            missing.append(symbol)
            continue
        metrics = dict(snapshot.metrics_json or {})
        if any(metrics.get(metric) is None for metric in REQUIRED_COVERAGE_METRICS):
            missing.append(symbol)
    return missing


@router.post("/import", response_model=FundamentalImportOut, status_code=201, dependencies=[Depends(require_admin)])
def upload_and_import_fundamentals(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> FundamentalImportOut:
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > settings.DATASET_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    filename = Path(file.filename or "fundamentals.xlsx").name
    if Path(filename).suffix.lower() not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="Only .xlsx/.xls workbooks are supported")

    digest = hashlib.sha256(data).hexdigest()
    content_type = file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    object_key = f"datasets/{digest}/{filename}"
    put_bytes(object_key=object_key, data=data, content_type=content_type)

    dataset = models.Dataset(
        source="fundamental_excel",
        symbol="FUNDAMENTALS",
        timeframe="1Y",
        data_hash=digest,
        filename=filename,
        content_type=content_type,
        object_key=object_key,
        size_bytes=len(data),
        meta_json={"filename": filename, "purpose": "fundamental_research_v3"},
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    run = create_import_run(db, dataset=dataset)
    try:
        job = get_queue().enqueue("services.worker.tasks.fundamentals.execute_fundamental_import", str(run.id))
        run.rq_job_id = str(job.id)
        db.add(run)
        db.commit()
        db.refresh(run)
    except Exception:
        run = execute_import_run(db, import_id=run.id, payload=data)
        summary = dict(run.summary_json or {})
        summary["enqueue_fallback"] = True
        run.summary_json = summary
        db.add(run)
        db.commit()
        db.refresh(run)
    return _import_out(run)


@router.get("/imports/latest", response_model=FundamentalImportOut | None)
def get_latest_fundamental_import(db: Session = Depends(get_db)) -> FundamentalImportOut | None:
    row = _latest_run(db)
    return _import_out(row) if row else None


@router.get("/providers/status", response_model=FundamentalProviderStatusOut, dependencies=[Depends(require_admin)])
def get_fundamental_provider_status() -> FundamentalProviderStatusOut:
    keys = _split_secret_list(settings.FUNDAMENTAL_LLM_API_KEYS)
    provider = settings.FUNDAMENTAL_LLM_PROVIDER or "gemini"
    return FundamentalProviderStatusOut(
        llm=FundamentalProviderStatusItemOut(
            provider=provider,
            configured=bool(keys),
            key_count=len(keys),
            model=settings.FUNDAMENTAL_LLM_MODEL or None,
            base_url=settings.FUNDAMENTAL_LLM_BASE_URL or None,
            note="Secrets are read from server/worker environment variables only.",
        ),
        stockanalysis={
            "configured": True,
            "source": "https://stockanalysis.com/quote/cbse/{symbol}",
            "scope": "masi",
        },
        bvc={
            "configured": True,
            "publications_max_pages": settings.BVC_PUBLICATIONS_MAX_PAGES,
            "supported_period_types": sorted(BVC_PERIOD_TYPES),
        },
    )


@router.post(
    "/imports/stockanalysis",
    response_model=StockanalysisFundamentalImportQueuedOut,
    dependencies=[Depends(require_admin)],
)
def enqueue_stockanalysis_fundamental_import(
    body: StockanalysisFundamentalImportIn,
    db: Session = Depends(get_db),
) -> StockanalysisFundamentalImportQueuedOut:
    symbols = _stockanalysis_candidate_symbols(
        db,
        symbols=body.symbols or [],
        missing_only=body.missing_only,
    )
    if not symbols:
        raise HTTPException(status_code=400, detail="No active MASI symbols selected for StockAnalysis fundamentals refresh")
    batch_id = str(uuid.uuid4())
    try:
        job = get_queue().enqueue(
            "services.worker.tasks.refresh_stockanalysis_fundamentals.refresh_stockanalysis_universe",
            symbols=symbols,
            missing_only=False,
            triggered_by="api",
            batch_id=batch_id,
            job_timeout=14400,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not enqueue StockAnalysis fundamentals refresh: {exc}") from exc
    return StockanalysisFundamentalImportQueuedOut(batch_id=batch_id, enqueued_count=len(symbols), rq_job_id=str(job.id))


@router.post(
    "/imports/yfinance",
    response_model=YfinanceFundamentalImportQueuedOut,
    dependencies=[Depends(require_admin)],
)
def enqueue_yfinance_fundamental_import(
    body: YfinanceFundamentalImportIn,
    db: Session = Depends(get_db),
) -> YfinanceFundamentalImportQueuedOut:
    symbols = sorted({item.strip().upper() for item in body.symbols or [] if item and item.strip()})
    regions = [item.strip().lower() for item in body.market_regions or ["us", "european", "asian"] if item and item.strip()]
    if not symbols:
        rows = (
            db.query(models.StockMaster.symbol)
            .filter(models.StockMaster.is_active.is_(True), models.StockMaster.market_region.in_(regions))
            .order_by(models.StockMaster.symbol.asc())
            .all()
        )
        symbols = [str(row[0]).upper() for row in rows]
    if not symbols:
        raise HTTPException(status_code=400, detail="No symbols selected for yfinance fundamentals refresh")
    batch_id = str(uuid.uuid4())
    try:
        job = get_queue().enqueue(
            "services.worker.tasks.refresh_yfinance_fundamentals.refresh_yfinance_universe",
            symbols=symbols,
            market_regions=regions,
            triggered_by="api",
            batch_id=batch_id,
            job_timeout=7200,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not enqueue yfinance fundamentals refresh: {exc}") from exc
    return YfinanceFundamentalImportQueuedOut(batch_id=batch_id, enqueued_count=len(symbols), rq_job_id=str(job.id))


@router.post("/imports/bvc", response_model=TargetedBvcFundamentalImportQueuedOut, dependencies=[Depends(require_admin)])
@router.post("/imports/targeted-bvc", response_model=TargetedBvcFundamentalImportQueuedOut, dependencies=[Depends(require_admin)])
def enqueue_targeted_bvc_fundamental_import(
    body: TargetedBvcFundamentalImportIn,
    db: Session = Depends(get_db),
) -> TargetedBvcFundamentalImportQueuedOut:
    if not os.environ.get("BVC_PIPELINE_ENABLED"):
        raise HTTPException(
            status_code=503,
            detail="BVC pipeline is dormant. Set BVC_PIPELINE_ENABLED=1 in the API and worker environments to re-enable.",
        )
    source_urls = sorted({item.strip() for item in body.source_urls if item and item.strip()})
    years = _years_from_request(body)
    sectors = sorted({item.strip() for item in body.sectors if item and item.strip()})
    requested_symbols = sorted({item.strip().upper() for item in body.symbols if item and item.strip()})
    broad_scan = not source_urls and not requested_symbols and not sectors
    period_types = _normalize_period_types(body.period_types, default_all=not requested_symbols and not sectors)
    targets = _targeted_bvc_targets(
        db,
        symbols=requested_symbols,
        sectors=sectors,
        include_mapping_repairs=body.include_mapping_repairs,
        include_complete=bool(requested_symbols or sectors or body.force or broad_scan),
    )

    symbols = [] if broad_scan else [target.symbol for target in targets]
    selected_count = len(targets) if broad_scan else len(symbols) or len(source_urls)
    batch_id = str(uuid.uuid4())
    if body.dry_run:
        return TargetedBvcFundamentalImportQueuedOut(
            batch_id=batch_id,
            import_id=None,
            selected_count=selected_count,
            rq_job_id=None,
            dry_run=True,
            source_url_count=len(source_urls),
            sectors=sectors,
            period_types=period_types,
            years=years,
            targets=targets,
        )

    if not _split_secret_list(settings.FUNDAMENTAL_LLM_API_KEYS):
        raise HTTPException(
            status_code=503,
            detail="No fundamental LLM key configured. Set FUNDAMENTAL_LLM_API_KEYS or GEMINI_API_KEYS in the API and worker environment.",
        )

    digest_payload = {
        "kind": "bvc",
        "batch_id": batch_id,
        "symbols": symbols,
        "source_urls": source_urls,
        "sectors": sectors,
        "period_types": period_types,
        "years": years,
        "broad_scan": broad_scan,
    }
    digest = hashlib.sha256(str(digest_payload).encode("utf-8")).hexdigest()
    run = create_import_run(
        db,
        data_source="bvc",
        source_universe="masi",
        filename=f"targeted_bvc_fundamentals_{batch_id}.xlsx",
        source_hash=digest,
        summary={
            "batch_id": batch_id,
            "triggered_by": "api",
            "targeted_bvc": True,
            "symbols": symbols,
            "requested_symbols": requested_symbols,
            "source_urls": source_urls,
            "source_url_count": len(source_urls),
            "sectors": sectors,
            "period_types": period_types,
            "fields": body.fields or [],
            "years": years,
            "broad_scan": broad_scan,
            "only_unseen": body.only_unseen and not body.force,
            "force": body.force,
            "targets": [target.dict() for target in targets],
        },
    )
    try:
        job = get_queue().enqueue(
            "services.worker.tasks.targeted_bvc_fundamentals.execute_bvc_fundamental_import",
            str(run.id),
            symbols=symbols,
            source_urls=source_urls,
            sectors=sectors,
            period_types=period_types,
            fields=body.fields or [],
            years=years,
            start_year=body.start_year,
            end_year=body.end_year,
            batch_id=batch_id,
            only_unseen=body.only_unseen and not body.force,
            force=body.force,
            job_timeout=7200,
        )
        run.rq_job_id = str(job.id)
        db.add(run)
        db.commit()
        db.refresh(run)
    except Exception as exc:
        run.status = "failed"
        run.error_message = f"Could not enqueue targeted BVC fundamentals backfill: {exc}"
        db.add(run)
        db.commit()
        raise HTTPException(status_code=503, detail=run.error_message) from exc
    return TargetedBvcFundamentalImportQueuedOut(
        batch_id=batch_id,
        import_id=str(run.id),
        selected_count=selected_count,
        rq_job_id=str(job.id),
        source_url_count=len(source_urls),
        sectors=sectors,
        period_types=period_types,
        years=years,
        targets=targets,
    )


@router.get("/imports/{import_id}", response_model=FundamentalImportOut)
def get_fundamental_import(import_id: uuid.UUID, db: Session = Depends(get_db)) -> FundamentalImportOut:
    row = db.get(models.FundamentalImport, import_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Import not found")
    return _import_out(row)


@router.get("/imports/{import_id}/quality", response_model=list[QualityIssueOut])
def get_fundamental_import_quality(import_id: uuid.UUID, db: Session = Depends(get_db)) -> list[QualityIssueOut]:
    rows = (
        db.query(models.FundamentalQualityIssue)
        .filter(models.FundamentalQualityIssue.import_id == import_id)
        .order_by(models.FundamentalQualityIssue.severity.asc(), models.FundamentalQualityIssue.symbol.asc().nullslast())
        .all()
    )
    return [_quality_issue_out(row) for row in rows]


@router.get("/imports/{import_id}/documents", response_model=list[FundamentalSourceDocumentOut])
def get_fundamental_import_documents(import_id: uuid.UUID, db: Session = Depends(get_db)) -> list[FundamentalSourceDocumentOut]:
    rows = (
        db.query(models.FundamentalSourceDocument)
        .filter(models.FundamentalSourceDocument.import_id == import_id)
        .order_by(
            models.FundamentalSourceDocument.fiscal_year.desc().nullslast(),
            models.FundamentalSourceDocument.period_type.asc().nullslast(),
            models.FundamentalSourceDocument.company_name.asc().nullslast(),
        )
        .all()
    )
    return [_source_document_out(row) for row in rows]


@router.get("/coverage", response_model=list[FundamentalCoverageRow])
def get_fundamental_coverage(db: Session = Depends(get_db)) -> list[FundamentalCoverageRow]:
    snapshots = latest_snapshot_rows_by_symbol(db)
    enriched = enriched_snapshots_by_symbol(db, snapshots)
    imports = latest_imports_by_symbol(db)
    stock_rows = (
        db.query(models.StockMaster)
        .filter(models.StockMaster.is_active.is_(True))
        .order_by(models.StockMaster.symbol.asc())
        .all()
    )
    symbols = sorted({row.symbol for row in stock_rows} | set(snapshots))
    stock_by_symbol = {row.symbol: row for row in stock_rows}
    out: list[FundamentalCoverageRow] = []
    for symbol in symbols:
        snapshot = snapshots.get(symbol)
        enriched_snapshot = enriched.get(symbol)
        import_row = imports.get(symbol)
        stock = stock_by_symbol.get(symbol)
        annual_metric_count = 0
        annual_years: list[int] = []
        period_metric_count = 0
        period_types: list[str] = []
        quality_issue_count = 0
        metrics = dict(enriched_snapshot.metrics or {}) if enriched_snapshot is not None else {}
        coverage = dict(enriched_snapshot.coverage or {}) if enriched_snapshot is not None else {}
        if snapshot is not None:
            annual_rows = (
                db.query(models.FundamentalAnnualMetric.statement_year)
                .filter(
                    models.FundamentalAnnualMetric.import_id == snapshot.import_id,
                    models.FundamentalAnnualMetric.symbol == symbol,
                    models.FundamentalAnnualMetric.metric_value.isnot(None),
                )
                .all()
            )
            annual_metric_count = len(annual_rows)
            annual_years = sorted({int(row[0]) for row in annual_rows if row[0] is not None})
            period_rows = period_metric_rows_for_symbol(
                db, import_id=snapshot.import_id, symbol=symbol, require_value=True
            )
            period_metric_count = len(period_rows)
            period_types = sorted({str(row.period_type) for row in period_rows if row.period_type})
            quality_issue_count = (
                db.query(models.FundamentalQualityIssue)
                .filter(
                    models.FundamentalQualityIssue.import_id == snapshot.import_id,
                    models.FundamentalQualityIssue.symbol == symbol,
                )
                .count()
            )
        missing_metrics = [metric for metric in REQUIRED_COVERAGE_METRICS if metrics.get(metric) is None]
        imported_at = None
        if import_row is not None:
            when = import_row.completed_at or import_row.imported_at or import_row.created_at
            imported_at = when.isoformat() if when else None
        has_snapshot = snapshot is not None
        has_annual = annual_metric_count > 0
        available_periods = [
            label
            for label, enabled in (
                ("latest", has_snapshot),
                ("annual", has_annual),
                ("semiannual", "semiannual" in period_types),
                ("quarterly", "quarterly" in period_types),
            )
            if enabled
        ]
        out.append(
            FundamentalCoverageRow(
                symbol=symbol,
                display_name=stock.display_name if stock else None,
                sector=stock.sector if stock else None,
                market_region=stock.market_region if stock else None,
                has_snapshot=has_snapshot,
                has_annual=has_annual,
                latest_statement_year=enriched_snapshot.latest_statement_year if enriched_snapshot is not None else None,
                latest_metric_count=len(metrics),
                annual_metric_count=annual_metric_count,
                annual_year_count=len(annual_years),
                annual_years=annual_years,
                period_metric_count=period_metric_count,
                period_types=period_types,
                available_periods=available_periods,
                current_price=metrics.get("Current_Price"),
                shares_outstanding=metrics.get("Shares_Outstanding"),
                market_cap=metrics.get("MarketCap_Calc"),
                price_as_of=coverage.get("price_as_of") if isinstance(coverage.get("price_as_of"), str) else None,
                price_source=coverage.get("price_source") if isinstance(coverage.get("price_source"), str) else None,
                price_source_provider=coverage.get("price_source_provider") if isinstance(coverage.get("price_source_provider"), str) else None,
                data_source=(snapshot.data_source if snapshot is not None else None) or (import_row.data_source if import_row else None),
                source_universe=import_row.source_universe if import_row else None,
                last_imported_at=imported_at,
                quality_issue_count=quality_issue_count,
                missing_metrics=missing_metrics,
                status=str((snapshot.scores_json or {}).get("status") or import_row.status) if snapshot is not None and import_row is not None else "no_coverage",
            )
        )
    return out


@router.post("/snapshot/batch", response_model=dict[str, FundamentalLightSnapshot | None])
def get_fundamental_snapshot_batch(
    body: FundamentalSnapshotBatchIn,
    db: Session = Depends(get_db),
    scenario: str = "auto",
) -> dict[str, FundamentalLightSnapshot | None]:
    scenario = _scenario_or_auto(scenario)
    symbols = sorted({item.strip().upper() for item in body.symbols if item and item.strip()})
    if len(symbols) > 200:
        raise HTTPException(status_code=400, detail="At most 200 symbols are allowed")
    snapshots = latest_snapshot_rows_by_symbol(db, symbols=symbols)
    enriched = enriched_snapshots_by_symbol(db, snapshots)
    if not symbols:
        return {}
    import_ids = sorted({row.import_id for row in snapshots.values()})
    for row in snapshots.values():
        _ensure_latest_symbol_valuations(
            db,
            import_id=row.import_id,
            symbol=row.symbol,
            scenario=scenario,
        )
    ensembles = {}
    if import_ids:
        rows = (
            db.query(models.FundamentalEnsembleResult)
            .filter(
                models.FundamentalEnsembleResult.import_id.in_(import_ids),
                models.FundamentalEnsembleResult.scenario == scenario,
            )
            .all()
        )
        ensembles = {(row.import_id, row.symbol, row.scenario): row for row in rows}
    fallback_symbols = [
        symbol
        for symbol in symbols
        if snapshots.get(symbol) is not None
        and (snapshots[symbol].import_id, symbol, scenario) not in ensembles
    ]
    fallback_by_scenario: dict[str, dict[str, models.FundamentalEnsembleResult]] = {}
    fallback_by_scenario[scenario], _fallback_valuations = _latest_available_valuation_bundle(db, fallback_symbols, scenario)
    imports = latest_imports_by_symbol(db, symbols=symbols)
    out: dict[str, FundamentalLightSnapshot | None] = {}
    for symbol in symbols:
        snapshot = snapshots.get(symbol)
        if snapshot is None:
            out[symbol] = None
            continue
        scores = dict(snapshot.scores_json or {})
        enriched_snapshot = enriched.get(symbol)
        coverage = dict(enriched_snapshot.coverage or {}) if enriched_snapshot is not None else dict(snapshot.coverage_json or {})
        metrics = dict(enriched_snapshot.metrics or {}) if enriched_snapshot is not None else dict(snapshot.metrics_json or {})
        selected_scenario = scenario
        ensemble = ensembles.get((snapshot.import_id, symbol, selected_scenario)) or fallback_by_scenario.get(selected_scenario, {}).get(symbol)
        current_price = metrics.get("Current_Price")
        import_row = imports.get(symbol)
        when = (import_row.completed_at or import_row.imported_at or import_row.created_at) if import_row else None
        out[symbol] = FundamentalLightSnapshot(
            symbol=symbol,
            value_score=scores.get("value"),
            quality_score=scores.get("quality"),
            fair_value=ensemble.fair_value_base if ensemble else None,
            upside_pct=_upside_from_price(ensemble.fair_value_base, current_price) if ensemble else None,
            confidence=_confidence_label(ensemble.confidence_score if ensemble else None),
            confidence_score=ensemble.confidence_score if ensemble else None,
            coverage_pct=_coverage_pct(coverage),
            data_source=snapshot.data_source or (import_row.data_source if import_row else None),
            currency=(snapshot.source_json or {}).get("currency") or metrics.get("Currency"),
            as_of=when.isoformat() if when else None,
            metrics={key: value for key, value in metrics.items() if isinstance(value, (int, float)) or value is None},
        )
    return out


@router.get("/universe", response_model=list[FundamentalUniverseRow])
def get_fundamental_universe(
    db: Session = Depends(get_db),
    scenario: str = "auto",
    market_region: str | None = None,
    sector: str | None = None,
    search: str | None = None,
) -> list[FundamentalUniverseRow]:
    scenario = _scenario_or_auto(scenario)
    signal_symbols = [row.symbol for row in list_signal_universe(db)]
    snapshots_by_symbol = latest_snapshot_rows_by_symbol(db)
    import_by_symbol = latest_imports_by_symbol(db)
    if not snapshots_by_symbol:
        metadata = _metadata_by_symbol(db, signal_symbols)
        market_context = market_price_context_by_symbol(db, signal_symbols)
        tech = technical_context(db, signal_symbols)
        rows = [
            FundamentalUniverseRow(
                symbol=symbol,
                company_name=metadata.get(symbol, {}).get("display_name") or symbol,
                display_name=metadata.get(symbol, {}).get("display_name"),
                sector=metadata.get(symbol, {}).get("sector"),
                market_region=metadata.get(symbol, {}).get("market_region"),
                adv20=market_context.get(symbol, {}).get("adv20"),
                coverage={"status": "no_succeeded_import"},
                model_eligibility={},
                valuation_summary={"model_count": 0, "usable_model_count": 0},
                technical=tech.get(symbol),
            )
            for symbol in signal_symbols
        ]
        return sorted(
            _filter_universe_rows(rows, market_region=market_region, sector=sector, search=search),
            key=lambda row: row.symbol,
        )

    snapshots = list(snapshots_by_symbol.values())
    enriched = lightweight_enriched_snapshots_by_symbol(db, snapshots_by_symbol)
    symbols = [row.symbol for row in snapshots]
    all_symbols = sorted(set(symbols) | set(signal_symbols))
    metadata = _metadata_by_symbol(db, all_symbols)
    market_context = market_price_context_by_symbol(db, all_symbols)
    tech = technical_context(db, all_symbols)
    import_ids = sorted({row.import_id for row in snapshots})
    for row in snapshots:
        _ensure_latest_symbol_valuations(
            db,
            import_id=row.import_id,
            symbol=row.symbol,
            scenario=scenario,
        )
    scenario_filter_valuation = models.FundamentalValuationResult.scenario.in_(list(VALUATION_SCENARIOS))
    scenario_filter_ensemble = models.FundamentalEnsembleResult.scenario.in_(list(VALUATION_SCENARIOS))
    valuations = (
        db.query(models.FundamentalValuationResult)
        .filter(models.FundamentalValuationResult.import_id.in_(import_ids), scenario_filter_valuation)
        .all()
    )
    ensembles = (
        db.query(models.FundamentalEnsembleResult)
        .filter(models.FundamentalEnsembleResult.import_id.in_(import_ids), scenario_filter_ensemble)
        .all()
    )
    valuations_by_symbol: dict[tuple[uuid.UUID, str, str], list[models.FundamentalValuationResult]] = defaultdict(list)
    for row in valuations:
        valuations_by_symbol[(row.import_id, row.symbol, row.scenario)].append(row)
    ensemble_by_symbol = {(row.import_id, row.symbol, row.scenario): row for row in ensembles}
    fallback_symbols = [
        row.symbol
        for row in snapshots
        if (row.import_id, row.symbol, scenario) not in ensemble_by_symbol
    ]
    fallback_ensembles_by_scenario: dict[str, dict[str, models.FundamentalEnsembleResult]] = {}
    fallback_valuations_by_scenario: dict[str, dict[str, list[models.FundamentalValuationResult]]] = {}
    for fallback_scenario in sorted({scenario, HEADLINE_SCENARIO}):
        fallback_ensembles_by_scenario[fallback_scenario], fallback_valuations_by_scenario[fallback_scenario] = _latest_available_valuation_bundle(db, fallback_symbols, fallback_scenario)

    output = []
    for row in snapshots:
        enriched_snapshot = enriched.get(row.symbol)
        metrics = dict(enriched_snapshot.metrics or {}) if enriched_snapshot is not None else dict(row.metrics_json or {})
        coverage = dict(enriched_snapshot.coverage or {}) if enriched_snapshot is not None else dict(row.coverage_json or {})
        diagnostics = dict(row.diagnostics_json or {})
        screens = _screens_from_diagnostics(diagnostics)
        candidates = {
            scenario_key: ensemble_by_symbol.get((row.import_id, row.symbol, scenario_key))
            for scenario_key in VALUATION_SCENARIOS
        }
        coherent_candidates, scenario_trio_stale = _coherent_scenario_rows(candidates)
        market_implied_scenario = _auto_scenario_from_ensembles(coherent_candidates, current_price=metrics.get("Current_Price"))
        selected_scenario = HEADLINE_SCENARIO if scenario_trio_stale else scenario
        ensemble = coherent_candidates.get(selected_scenario)
        valuation_rows = valuations_by_symbol.get((row.import_id, row.symbol, selected_scenario), [])
        if ensemble is None:
            ensemble = fallback_ensembles_by_scenario.get(selected_scenario, {}).get(row.symbol)
            valuation_rows = fallback_valuations_by_scenario.get(selected_scenario, {}).get(row.symbol, [])
        import_row = import_by_symbol.get(row.symbol)
        base_ensemble = coherent_candidates.get(HEADLINE_SCENARIO)
        overlay = _headline_overlay(
            db,
            symbol=row.symbol,
            viewed_scenario=selected_scenario,
            base_ensemble=base_ensemble,
            import_row=import_row,
            current_price=metrics.get("Current_Price"),
            market_implied_scenario=market_implied_scenario,
        )
        output.append(
            FundamentalUniverseRow(
                symbol=row.symbol,
                company_name=row.company_name,
                display_name=metadata.get(row.symbol, {}).get("display_name"),
                sector=metadata.get(row.symbol, {}).get("sector"),
                market_region=metadata.get(row.symbol, {}).get("market_region"),
                latest_statement_year=enriched_snapshot.latest_statement_year if enriched_snapshot is not None else row.latest_statement_year,
                current_price=metrics.get("Current_Price"),
                adv20=metrics.get("ADV20") or market_context.get(row.symbol, {}).get("adv20"),
                market_cap=metrics.get("MarketCap_Calc"),
                value_score=(row.scores_json or {}).get("value"),
                quality_score=(row.scores_json or {}).get("quality"),
                magic_formula_score=_screen_score(screens, "magic_formula"),
                peg_value=_peg_value(screens),
                peg_garp_score=_screen_score(screens, "peg_garp"),
                altman_z_score=_screen_score(screens, "altman_z"),
                altman_zone=_altman_zone(screens),
                eva_score=_screen_score(screens, "eva"),
                regression_adj_score=_screen_score(screens, "regression_adj"),
                regression_richness_avg=_regression_richness_avg(screens),
                screens=screens,
                **overlay,
                scenario_trio_stale=scenario_trio_stale,
                scenario_probabilities=_scenario_probabilities_payload(DEFAULT_ASSUMPTIONS),
                coverage=coverage,
                model_eligibility=dict(row.model_eligibility_json or {}),
                valuation_summary=_valuation_summary(
                    valuation_rows,
                    ensemble,
                    snapshot_import_id=row.import_id,
                    current_price_override=metrics.get("Current_Price"),
                ),
                ensemble=_ensemble_out(ensemble, current_price_override=metrics.get("Current_Price")),
                technical=tech.get(row.symbol),
                data_source=row.data_source or (import_row.data_source if import_row else None),
                imported_at=(
                    import_by_symbol[row.symbol].completed_at.isoformat()
                    if import_by_symbol.get(row.symbol) and import_by_symbol[row.symbol].completed_at
                    else import_by_symbol[row.symbol].imported_at.isoformat()
                    if import_by_symbol.get(row.symbol) and import_by_symbol[row.symbol].imported_at
                    else None
                ),
            )
        )
    covered = {row.symbol for row in snapshots}
    for symbol in all_symbols:
        if symbol in covered:
            continue
        meta = metadata.get(symbol, {})
        output.append(
            FundamentalUniverseRow(
                symbol=symbol,
                company_name=meta.get("display_name") or symbol,
                display_name=meta.get("display_name"),
                sector=meta.get("sector"),
                market_region=meta.get("market_region"),
                adv20=market_context.get(symbol, {}).get("adv20"),
                coverage={"status": "no_coverage"},
                model_eligibility={},
                valuation_summary={"model_count": 0, "usable_model_count": 0},
                technical=tech.get(symbol),
            )
        )
    return sorted(
        _filter_universe_rows(output, market_region=market_region, sector=sector, search=search),
        key=lambda row: row.symbol,
    )


@router.get("/screens/{screen_name}", response_model=list[FundamentalScreenRankedRow])
def get_screen_ranking(
    screen_name: str,
    db: Session = Depends(get_db),
    top: int = 50,
    sector: str | None = None,
    market_region: str | None = None,
    scenario: str = "auto",
) -> list[FundamentalScreenRankedRow]:
    screen_name = screen_name.strip().lower()
    if screen_name not in SCREEN_NAMES:
        raise HTTPException(status_code=400, detail=f"screen_name must be one of {sorted(SCREEN_NAMES)}")
    limit = max(1, min(200, int(top or 50)))
    rows = get_fundamental_universe(
        db=db,
        scenario=scenario,
        market_region=market_region,
        sector=sector,
    )
    ranked: list[FundamentalScreenRankedRow] = []
    for row in rows:
        screen = row.screens.get(screen_name)
        if not isinstance(screen, dict):
            continue
        score = _screen_score(row.screens, screen_name)
        ranked.append(
            FundamentalScreenRankedRow(
                symbol=row.symbol,
                company_name=row.company_name,
                display_name=row.display_name,
                sector=row.sector,
                market_region=row.market_region,
                score=score,
                screen_name=screen_name,
                screen=screen,
                recommendation=row.recommendation,
                target_price=row.target_price,
                upside_pct=row.ensemble.upside_pct if row.ensemble else None,
                conviction=row.conviction,
            )
        )
    return sorted(
        ranked,
        key=lambda item: (item.score is not None, item.score if item.score is not None else float("-inf"), item.symbol),
        reverse=True,
    )[:limit]


@router.post("/stocks/{symbol}/comparables", response_model=FundamentalComparablesOut)
def get_fundamental_comparables(
    symbol: str,
    body: FundamentalComparablesRequest,
    db: Session = Depends(get_db),
) -> FundamentalComparablesOut:
    symbol = symbol.strip().upper()
    metric_keys = _comparable_metric_keys(body.metric_keys)
    component_shares = _comparable_component_shares(body)
    warnings: list[str] = []

    target_snapshot_rows = latest_snapshot_rows_by_symbol(db, symbols=[symbol])
    if symbol not in target_snapshot_rows:
        raise HTTPException(status_code=404, detail=f"No fundamentals for {symbol}")

    target_metadata = _metadata_by_symbol(db, [symbol]).get(symbol, {})
    comparator_symbols: list[str]
    comparator_sector = body.sector or target_metadata.get("sector")
    comparator_id = body.comparator_id
    comparator_name = body.comparator_name

    if body.comparator_type == "sector":
        if not comparator_sector:
            comparator_symbols = [symbol]
            warnings.append("target_sector_missing")
            comparator_name = comparator_name or "Sector unavailable"
        else:
            all_snapshot_rows = latest_snapshot_rows_by_symbol(db)
            all_metadata = _metadata_by_symbol(db, list(all_snapshot_rows))
            comparator_symbols = sorted(
                row_symbol
                for row_symbol in all_snapshot_rows
                if (all_metadata.get(row_symbol, {}).get("sector") or "").strip().lower()
                == str(comparator_sector).strip().lower()
            )
            if symbol not in comparator_symbols:
                comparator_symbols.insert(0, symbol)
            comparator_name = comparator_name or f"Sector - {comparator_sector}"
        comparator_id = comparator_id or f"sector:{comparator_sector or 'unknown'}"
    else:
        component_symbols = [component.symbol for component in body.components or []]
        comparator_symbols = _clean_comparable_symbols(
            [
                *(body.symbols or []),
                *component_symbols,
                *component_shares.keys(),
            ]
        )
        if not comparator_symbols:
            raise HTTPException(status_code=400, detail="Index comparables require symbols or components")
        comparator_name = comparator_name or "Selected index"

    target_in_comparator = symbol in set(comparator_symbols)
    requested_symbols = _clean_comparable_symbols([symbol, *comparator_symbols])
    snapshot_rows = latest_snapshot_rows_by_symbol(db, symbols=requested_symbols)
    missing_symbols = [item for item in comparator_symbols if item not in snapshot_rows]
    if missing_symbols:
        warnings.append(f"missing_fundamentals:{','.join(missing_symbols)}")

    enriched = enriched_snapshots_by_symbol(db, snapshot_rows)
    metadata = _metadata_by_symbol(db, requested_symbols)
    selected_snapshot = enriched.get(symbol)
    selected_metrics = {
        metric_key: _comparable_number((selected_snapshot.metrics if selected_snapshot else {}).get(metric_key))
        for metric_key in metric_keys
    }

    peer_rows: list[dict[str, Any]] = []
    ordered_symbols = _clean_comparable_symbols([symbol, *comparator_symbols]) if target_in_comparator else comparator_symbols
    for peer_symbol in ordered_symbols:
        snapshot = enriched.get(peer_symbol)
        if snapshot is None:
            continue

        metrics = dict(snapshot.metrics or {})
        current_price = _positive_comparable_number(metrics.get("Current_Price"))
        metric_shares = _positive_comparable_number(metrics.get("Shares_Outstanding"))
        market_cap = _positive_comparable_number(metrics.get("MarketCap_Calc"))
        component_share = component_shares.get(peer_symbol)
        row_warnings: list[str] = []

        if component_shares and component_share is None:
            row_warnings.append("missing_component_shares")

        shares = component_share if component_share is not None else metric_shares
        if component_share is not None:
            market_value = current_price * component_share if current_price is not None else None
            if market_value is None:
                row_warnings.append("missing_price_for_component_weight")
        elif market_cap is not None:
            market_value = market_cap
        elif current_price is not None and metric_shares is not None:
            market_value = current_price * metric_shares
        else:
            market_value = None
            row_warnings.append("missing_market_value_weight")

        row_metrics = {metric_key: _comparable_number(metrics.get(metric_key)) for metric_key in metric_keys}
        if not any(value is not None for value in row_metrics.values()):
            row_warnings.append("missing_comparable_metrics")

        peer_meta = metadata.get(peer_symbol, {})
        peer_rows.append(
            {
                "symbol": peer_symbol,
                "company_name": snapshot.company_name,
                "display_name": peer_meta.get("display_name"),
                "sector": peer_meta.get("sector"),
                "current_price": current_price,
                "shares": shares,
                "market_value": market_value,
                "base_weight": market_value,
                "is_target": peer_symbol == symbol,
                "metrics": row_metrics,
                "weights": {metric_key: None for metric_key in metric_keys},
                "contributions": {metric_key: None for metric_key in metric_keys},
                "warnings": row_warnings,
            }
        )

    benchmarks: dict[str, FundamentalComparableBenchmarkOut] = {}
    stats: dict[str, dict[str, float | int | None]] = {}
    used_equal_fallback = False
    for metric_key in metric_keys:
        value_rows = [
            row
            for row in peer_rows
            if _comparable_number(row["metrics"].get(metric_key)) is not None
        ]
        weighted_rows = [
            row
            for row in value_rows
            if _positive_comparable_number(row.get("base_weight")) is not None
        ]
        missing_weight_count = len(value_rows) - len(weighted_rows)
        use_equal_weight = False

        if not weighted_rows and value_rows:
            weighted_rows = value_rows
            use_equal_weight = True
            used_equal_fallback = True

        total_weight = sum(
            1.0 if use_equal_weight else float(row["base_weight"])
            for row in weighted_rows
            if use_equal_weight or _positive_comparable_number(row.get("base_weight")) is not None
        )
        if total_weight > 0:
            for row in weighted_rows:
                raw_weight = 1.0 if use_equal_weight else float(row["base_weight"])
                metric_weight = raw_weight / total_weight
                metric_value = float(row["metrics"][metric_key])
                row["weights"][metric_key] = metric_weight
                row["contributions"][metric_key] = metric_value * metric_weight

        values = [float(row["metrics"][metric_key]) for row in value_rows]
        metric_stats = _metric_stats(values)
        stats[metric_key] = metric_stats
        benchmarks[metric_key] = FundamentalComparableBenchmarkOut(
            metric_key=metric_key,
            selected_value=selected_metrics.get(metric_key),
            weighted_including_target=_weighted_average_for_rows(peer_rows, metric_key),
            weighted_excluding_target=_weighted_average_for_rows(peer_rows, metric_key, exclude_symbol=symbol),
            median=metric_stats["median"] if isinstance(metric_stats["median"], float) else _nullable_median(values),
            max=metric_stats["max"] if isinstance(metric_stats["max"], float) else None,
            p75=metric_stats["p75"] if isinstance(metric_stats["p75"], float) else None,
            p25=metric_stats["p25"] if isinstance(metric_stats["p25"], float) else None,
            min=metric_stats["min"] if isinstance(metric_stats["min"], float) else None,
            eligible_count=len(value_rows),
            weighted_count=len(weighted_rows),
            missing_metric_count=max(0, len(peer_rows) - len(value_rows)),
            missing_weight_count=max(0, missing_weight_count),
        )
        stdev_value = pstdev(values) if len(values) > 1 else 0.0
        median_value = _comparable_number(metric_stats.get("median"))
        for row in peer_rows:
            value = _comparable_number(row["metrics"].get(metric_key))
            row.setdefault("z_scores", {})[metric_key] = (
                (value - median_value) / stdev_value if value is not None and median_value is not None and stdev_value > 0 else None
            )
            row.setdefault("pct_dev_from_median", {})[metric_key] = (
                (value / median_value) - 1.0 if value is not None and median_value not in (None, 0) else None
            )

    if used_equal_fallback:
        warnings.append("equal_weight_fallback_used_for_some_metrics")

    peer_rows = sorted(
        peer_rows,
        key=lambda row: (
            not bool(row["is_target"]),
            -float(row["base_weight"] or 0.0),
            row["symbol"],
        ),
    )
    weight_source = (
        "component_shares_x_price"
        if body.comparator_type == "index" and component_shares
        else "market_cap"
    )
    return FundamentalComparablesOut(
        symbol=symbol,
        comparator=FundamentalComparableMetaOut(
            type=body.comparator_type,
            id=comparator_id,
            name=comparator_name or "Comparator",
            sector=str(comparator_sector) if comparator_sector else None,
            target_in_comparator=target_in_comparator,
            weight_source=weight_source,
        ),
        metric_keys=metric_keys,
        selected_metrics=selected_metrics,
        benchmarks=benchmarks,
        stats=stats,
        peers=[FundamentalComparablePeerOut(**row) for row in peer_rows],
        warnings=warnings,
    )


@router.get("/stocks/{symbol}", response_model=FundamentalStockDetailOut)
def get_fundamental_stock_detail(symbol: str, db: Session = Depends(get_db), scenario: str = "auto") -> FundamentalStockDetailOut:
    symbol = symbol.upper()
    scenario = _scenario_or_auto(scenario)
    snapshots = latest_snapshot_rows_by_symbol(db, symbols=[symbol])
    snapshot = snapshots.get(symbol)
    import_row = db.get(models.FundamentalImport, snapshot.import_id) if snapshot else None
    metadata = _metadata_by_symbol(db, [symbol]).get(symbol, {})
    if snapshot is None:
        if not metadata:
            raise HTTPException(status_code=404, detail=f"No fundamentals for {symbol}")
        selected_scenario = scenario
        assumptions, provenance_by_scenario = _assumption_bundle(
            db,
            symbol=symbol,
            sector=metadata.get("sector"),
            selected_scenario=selected_scenario,
        )
        return FundamentalStockDetailOut(
            symbol=symbol,
            company_name=metadata.get("display_name") or symbol,
            display_name=metadata.get("display_name"),
            sector=metadata.get("sector"),
            coverage={"status": "no_coverage"},
            annual=[],
            valuations=[],
            assumptions=assumptions,
            assumption_provenance=provenance_by_scenario,
            headline_scenario=HEADLINE_SCENARIO,
            viewed_scenario=selected_scenario,
            scenario_trio_stale=False,
            scenario_probabilities=_scenario_probabilities_payload(assumptions),
            assumption_warnings=_assumption_warnings_payload(assumptions),
            technical=technical_context(db, [symbol]).get(symbol),
        )

    annual_rows = annual_metric_rows_for_symbol(db, import_id=import_row.id, symbol=symbol)
    period_rows = period_metric_rows_for_symbol(db, import_id=import_row.id, symbol=symbol, require_value=True)
    enriched_snapshot = enriched_snapshots_by_symbol(db, {symbol: snapshot}).get(symbol)
    metrics_for_selection = dict(enriched_snapshot.metrics or {}) if enriched_snapshot is not None else dict(snapshot.metrics_json or {})
    current_price = metrics_for_selection.get("Current_Price")
    _ensure_latest_symbol_valuations(
        db,
        import_id=import_row.id if import_row else snapshot.import_id,
        symbol=symbol,
        scenario=scenario,
    )
    db.refresh(snapshot)
    scenario_ensembles, scenario_trio_stale = _ensembles_by_scenario(
        db,
        import_id=import_row.id if import_row else snapshot.import_id,
        symbol=symbol,
        current_price_override=current_price,
        allow_fallback=False,
    )
    selected_scenario = HEADLINE_SCENARIO if scenario_trio_stale else scenario
    market_implied_scenario = _auto_scenario_from_ensembles(
        scenario_ensembles,
        current_price=metrics_for_selection.get("Current_Price"),
    )
    valuations = (
        db.query(models.FundamentalValuationResult)
        .filter(models.FundamentalValuationResult.import_id == import_row.id, models.FundamentalValuationResult.symbol == symbol, models.FundamentalValuationResult.scenario == selected_scenario)
        .order_by(models.FundamentalValuationResult.family.asc(), models.FundamentalValuationResult.model.asc())
        .all()
    )
    broker_anchor = load_broker_target(db, symbol)
    triangulation = compute_triangulation(
        [
            {"model": row.model, "family": row.family, "fair_value": row.fair_value}
            for row in valuations
        ],
        current_price,
        broker_target=broker_anchor["value"] if broker_anchor else None,
    ).to_dict()
    if broker_anchor is not None:
        triangulation["broker"] = broker_anchor
    ensemble = (
        db.query(models.FundamentalEnsembleResult)
        .filter(models.FundamentalEnsembleResult.import_id == import_row.id, models.FundamentalEnsembleResult.symbol == symbol, models.FundamentalEnsembleResult.scenario == selected_scenario)
        .first()
    )
    base_ensemble = ensemble if selected_scenario == HEADLINE_SCENARIO else (
        db.query(models.FundamentalEnsembleResult)
        .filter(
            models.FundamentalEnsembleResult.import_id == import_row.id,
            models.FundamentalEnsembleResult.symbol == symbol,
            models.FundamentalEnsembleResult.scenario == HEADLINE_SCENARIO,
        )
        .first()
    )
    quality_issues = (
        db.query(models.FundamentalQualityIssue)
        .filter(models.FundamentalQualityIssue.import_id == import_row.id, models.FundamentalQualityIssue.symbol == symbol)
        .order_by(models.FundamentalQualityIssue.severity.asc(), models.FundamentalQualityIssue.code.asc())
        .all()
    )
    diagnostics = dict(snapshot.diagnostics_json or {})
    screens = _screens_from_diagnostics(diagnostics)
    assumptions, provenance_by_scenario = _assumption_bundle(
        db,
        symbol=symbol,
        sector=metadata.get("sector"),
        selected_scenario=selected_scenario,
    )
    diagnostics, screens = _overlay_detail_eva_screen(
        snapshot=snapshot,
        enriched_snapshot=enriched_snapshot,
        annual_rows=annual_rows,
        assumptions=assumptions,
        sector=metadata.get("sector"),
        diagnostics=diagnostics,
        screens=screens,
    )
    integrity_row = _latest_integrity_model(db, snapshot)
    metric_override_rows = current_metric_overrides(db, symbol=symbol)
    thesis_row = _current_thesis(db, symbol)
    catalyst_rows = _upcoming_catalysts(db, symbol)
    _history_items, trend = pillar_history_for_symbol(db, symbol=symbol, limit=12)
    comps_table: dict[str, Any] | None = None
    try:
        comps_table = get_fundamental_comparables(
            symbol,
            FundamentalComparablesRequest(comparator_type="sector", metric_keys=list(DEFAULT_COMPARABLE_METRICS)),
            db,
        ).model_dump()
    except Exception:
        comps_table = None
    overlay = _headline_overlay(
        db,
        symbol=symbol,
        viewed_scenario=selected_scenario,
        base_ensemble=base_ensemble,
        import_row=import_row,
        current_price=current_price,
        market_implied_scenario=market_implied_scenario,
    )
    detail_missing_financial_data = _missing_financial_data_summary(
        latest_metrics=metrics_for_selection,
        annual_rows=annual_rows,
        statement_year=enriched_snapshot.latest_statement_year if enriched_snapshot is not None else snapshot.latest_statement_year,
    )
    ensemble_weights = dict(ensemble.model_weights_json or {}) if ensemble else {}
    return FundamentalStockDetailOut(
        symbol=symbol,
        company_name=snapshot.company_name,
        display_name=metadata.get("display_name"),
        sector=metadata.get("sector"),
        latest_statement_year=enriched_snapshot.latest_statement_year if enriched_snapshot is not None else snapshot.latest_statement_year,
        metrics=dict(enriched_snapshot.metrics or {}) if enriched_snapshot is not None else dict(snapshot.metrics_json or {}),
        scores=_visible_factor_scores(snapshot.scores_json),
        diagnostics=_visible_factor_diagnostics(diagnostics),
        screens=screens,
        coverage=dict(enriched_snapshot.coverage or {}) if enriched_snapshot is not None else dict(snapshot.coverage_json or {}),
        model_eligibility=dict(snapshot.model_eligibility_json or {}),
        missing_financial_data=detail_missing_financial_data,
        annual=annual_by_year(annual_rows),
        annual_raw=[_annual_raw_out(row) for row in annual_rows],
        metric_overrides=[_metric_override_out(row) for row in metric_override_rows],
        period_metrics=[_period_metric_out(row) for row in period_rows],
        valuations=[_valuation_out(row, current_price_override=current_price) for row in valuations],
        projections_by_period_type=_projection_payloads_by_period_type(
            db,
            import_id=import_row.id,
            symbol=symbol,
            scenario=selected_scenario,
        ),
        ensemble=_ensemble_out(ensemble, current_price_override=current_price),
        ensembles=scenario_ensembles,
        rate_sensitive_weight=_rate_sensitive_weight_from_weights(ensemble_weights),
        triangulation=triangulation,
        assumptions=assumptions,
        assumption_provenance=provenance_by_scenario,
        scenario_trio_stale=scenario_trio_stale,
        scenario_probabilities=_scenario_probabilities_payload(assumptions),
        assumption_warnings=_assumption_warnings_payload(assumptions),
        integrity=_integrity_out(integrity_row),
        thesis=_thesis_out(thesis_row),
        catalysts=[_catalyst_out(row) for row in catalyst_rows],
        trend=trend,
        comps_table=comps_table,
        quality_issues=[_quality_issue_out(row) for row in quality_issues],
        technical=technical_context(db, [symbol]).get(symbol),
        **overlay,
        data_source=snapshot.data_source or (import_row.data_source if import_row else None),
        imported_at=(
            import_row.completed_at.isoformat()
            if import_row and import_row.completed_at
            else import_row.imported_at.isoformat()
            if import_row and import_row.imported_at
            else None
        ),
    )


@router.get("/stocks/{symbol}/valuation", response_model=list[ValuationResultOut])
def get_stock_valuation(symbol: str, db: Session = Depends(get_db), scenario: str = "base") -> list[ValuationResultOut]:
    snapshot, _import_row = _latest_snapshot_or_404(db, symbol)
    enriched_snapshot = enriched_snapshots_by_symbol(db, {symbol.upper(): snapshot}).get(symbol.upper())
    current_price = (enriched_snapshot.metrics or {}).get("Current_Price") if enriched_snapshot is not None else None
    rows = (
        db.query(models.FundamentalValuationResult)
        .filter(models.FundamentalValuationResult.import_id == snapshot.import_id, models.FundamentalValuationResult.symbol == symbol.upper(), models.FundamentalValuationResult.scenario == scenario)
        .order_by(models.FundamentalValuationResult.family.asc(), models.FundamentalValuationResult.model.asc())
        .all()
    )
    if not rows:
        _ensure_latest_symbol_valuations(db, import_id=snapshot.import_id, symbol=symbol.upper(), scenario=scenario)
        rows = (
            db.query(models.FundamentalValuationResult)
            .filter(models.FundamentalValuationResult.import_id == snapshot.import_id, models.FundamentalValuationResult.symbol == symbol.upper(), models.FundamentalValuationResult.scenario == scenario)
            .order_by(models.FundamentalValuationResult.family.asc(), models.FundamentalValuationResult.model.asc())
            .all()
        )
    return [_valuation_out(row, current_price_override=current_price) for row in rows]


@router.get("/stocks/{symbol}/sensitivity", response_model=dict[str, Any])
def get_stock_sensitivity(
    symbol: str,
    db: Session = Depends(get_db),
    scenario: str = "base",
    axis_x: str = "wacc",
    axis_y: str = "terminal_growth",
    steps: int = 5,
) -> dict[str, Any]:
    try:
        return compute_symbol_sensitivity(db, symbol=symbol, scenario=scenario, axis_x=axis_x, axis_y=axis_y, steps=steps)
    except ValueError as exc:
        raise HTTPException(status_code=400 if "Sensitivity" in str(exc) else 404, detail=str(exc)) from exc


@router.get("/stocks/{symbol}/integrity", response_model=IntegrityReportOut)
def get_stock_integrity(symbol: str, db: Session = Depends(get_db)) -> IntegrityReportOut:
    snapshot, _import_row = _latest_snapshot_or_404(db, symbol)
    row = _latest_integrity_model(db, snapshot)
    out = _integrity_out(row)
    if out is None:
        raise HTTPException(status_code=404, detail=f"No integrity report for {symbol.upper()}")
    return out


@router.get("/stocks/{symbol}/thesis", response_model=ThesisOut)
def get_stock_thesis(symbol: str, db: Session = Depends(get_db)) -> ThesisOut:
    row = _current_thesis(db, symbol)
    out = _thesis_out(row)
    if out is None:
        raise HTTPException(status_code=404, detail=f"No thesis for {symbol.upper()}")
    return out


@router.get("/stocks/{symbol}/thesis/history", response_model=ThesisHistoryOut)
def get_stock_thesis_history(symbol: str, db: Session = Depends(get_db)) -> ThesisHistoryOut:
    rows = (
        db.query(models.FundamentalThesis)
        .filter(models.FundamentalThesis.symbol == symbol.upper())
        .order_by(models.FundamentalThesis.created_at.desc(), models.FundamentalThesis.id.desc())
        .limit(50)
        .all()
    )
    return ThesisHistoryOut(items=[item for row in rows if (item := _thesis_out(row)) is not None])


@router.post("/stocks/{symbol}/thesis", response_model=ThesisOut)
def post_stock_thesis(
    symbol: str,
    body: ThesisIn,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(optional_app_user),
) -> ThesisOut:
    symbol = symbol.upper()
    _latest_snapshot_or_404(db, symbol)
    data, warnings = _validate_thesis_body(db, symbol, body)
    db.query(models.FundamentalThesis).filter(
        models.FundamentalThesis.symbol == symbol,
        models.FundamentalThesis.is_current.is_(True),
    ).update({"is_current": False}, synchronize_session=False)
    row = models.FundamentalThesis(symbol=symbol, created_by=user.id if user else "api", is_current=True, **data)
    db.add(row)
    db.flush()
    db.commit()
    db.refresh(row)
    out = _thesis_out(row, warnings=warnings)
    if out is None:
        raise HTTPException(status_code=500, detail="thesis persisted but could not be rendered")
    return out


@router.delete("/stocks/{symbol}/thesis", status_code=204)
def delete_stock_thesis(
    symbol: str,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(optional_app_user),
) -> Response:
    symbol = symbol.upper()
    _latest_snapshot_or_404(db, symbol)
    db.query(models.FundamentalThesis).filter(
        models.FundamentalThesis.symbol == symbol,
        models.FundamentalThesis.is_current.is_(True),
    ).update({"is_current": False}, synchronize_session=False)
    row = models.FundamentalThesis(
        symbol=symbol,
        as_of=dt.date.today(),
        direction="avoid",
        conviction="low",
        core_thesis="Thesis removed by user; historical thesis rows remain available for audit.",
        bullish_drivers_json=[{"title": "Removed", "detail": "Current thesis was removed.", "pillar": None}],
        bearish_drivers_json=[{"title": "Removed", "detail": "No active thesis is currently maintained.", "pillar": None}],
        target_price=None,
        target_horizon_months=None,
        stop_price=None,
        invalidation_conditions_json=[],
        linked_catalyst_ids_json=[],
        created_by=user.id if user else "api",
        is_current=True,
    )
    db.add(row)
    db.flush()
    db.commit()
    return Response(status_code=204)


@router.get("/calendar", response_model=CatalystCalendarOut)
def get_fundamental_calendar(
    db: Session = Depends(get_db),
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    impact_tier: str | None = None,
    symbol: str | None = None,
) -> CatalystCalendarOut:
    start = _parse_date(from_date, default=dt.date.today())
    end = _parse_date(to_date, default=start + dt.timedelta(days=30))
    tiers = {item.strip() for item in (impact_tier or "").split(",") if item.strip()}
    query = db.query(models.FundamentalCatalyst).filter(
        models.FundamentalCatalyst.is_active.is_(True),
        models.FundamentalCatalyst.event_date >= start,
        models.FundamentalCatalyst.event_date <= end,
    )
    if tiers:
        query = query.filter(models.FundamentalCatalyst.impact_tier.in_(tiers))
    if symbol:
        query = query.filter(models.FundamentalCatalyst.symbol == symbol.upper())
    rows = query.order_by(models.FundamentalCatalyst.event_date.asc(), models.FundamentalCatalyst.symbol.asc()).limit(501).all()
    return CatalystCalendarOut(
        from_date=start.isoformat(),
        to_date=end.isoformat(),
        items=[_catalyst_out(row) for row in rows[:500]],
        truncated=len(rows) > 500,
    )


@router.get("/stocks/{symbol}/catalysts", response_model=list[CatalystOut])
def get_stock_catalysts(symbol: str, db: Session = Depends(get_db), upcoming_only: bool = True) -> list[CatalystOut]:
    symbol = symbol.upper()
    _latest_snapshot_or_404(db, symbol)
    query = db.query(models.FundamentalCatalyst).filter(models.FundamentalCatalyst.symbol == symbol)
    if upcoming_only:
        query = query.filter(models.FundamentalCatalyst.is_active.is_(True), models.FundamentalCatalyst.event_date >= dt.date.today())
    else:
        query = query.filter(models.FundamentalCatalyst.event_date >= dt.date.today() - dt.timedelta(days=90))
    rows = query.order_by(models.FundamentalCatalyst.event_date.asc(), models.FundamentalCatalyst.id.asc()).all()
    return [_catalyst_out(row) for row in rows]


@router.post("/stocks/{symbol}/catalysts", response_model=CatalystOut)
def post_stock_catalyst(
    symbol: str,
    body: CatalystIn,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(optional_app_user),
) -> CatalystOut:
    symbol = symbol.upper()
    _latest_snapshot_or_404(db, symbol)
    row = models.FundamentalCatalyst(
        symbol=symbol,
        event_type=body.event_type,
        event_date=_parse_date(body.event_date),
        event_date_confidence=body.event_date_confidence,
        impact_tier=body.impact_tier,
        expected_direction=body.expected_direction,
        title=_clean_text(body.title),
        notes=_clean_text(body.notes or "") or None,
        source=f"manual:{user.id if user else 'api'}",
        source_payload_json={},
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _catalyst_out(row)


@router.patch("/catalysts/{catalyst_id}", response_model=CatalystOut)
def patch_catalyst(catalyst_id: int, body: CatalystPatchIn, db: Session = Depends(get_db)) -> CatalystOut:
    row = db.get(models.FundamentalCatalyst, catalyst_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No catalyst {catalyst_id}")
    new_date = _parse_date(body.event_date, default=row.event_date) if body.event_date else row.event_date
    if new_date != row.event_date and abs((new_date - row.event_date).days) > 14:
        new_row = models.FundamentalCatalyst(
            symbol=row.symbol,
            event_type=row.event_type,
            event_date=new_date,
            event_date_confidence=body.event_date_confidence or row.event_date_confidence,
            impact_tier=body.impact_tier or row.impact_tier,
            expected_direction=body.expected_direction if body.expected_direction is not None else row.expected_direction,
            title=_clean_text(body.title or row.title),
            notes=_clean_text(body.notes if body.notes is not None else row.notes or "") or None,
            source=row.source,
            source_payload_json=dict(row.source_payload_json or {}),
            is_active=True,
        )
        db.add(new_row)
        db.flush()
        row.is_active = False
        row.superseded_by_id = new_row.id
        db.commit()
        db.refresh(new_row)
        return _catalyst_out(new_row)
    row.event_date = new_date
    if body.event_date_confidence is not None:
        row.event_date_confidence = body.event_date_confidence
    if body.impact_tier is not None:
        row.impact_tier = body.impact_tier
    if body.expected_direction is not None:
        row.expected_direction = body.expected_direction
    if body.title is not None:
        row.title = _clean_text(body.title)
    if body.notes is not None:
        row.notes = _clean_text(body.notes) or None
    db.add(row)
    db.commit()
    db.refresh(row)
    return _catalyst_out(row)


@router.delete("/catalysts/{catalyst_id}", status_code=204)
def delete_catalyst(catalyst_id: int, db: Session = Depends(get_db)) -> Response:
    row = db.get(models.FundamentalCatalyst, catalyst_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No catalyst {catalyst_id}")
    row.is_active = False
    db.add(row)
    db.commit()
    return Response(status_code=204)


@router.get("/stocks/{symbol}/pillar-history", response_model=PillarHistoryOut)
def get_stock_pillar_history(symbol: str, db: Session = Depends(get_db), limit: int = 12) -> PillarHistoryOut:
    items, trend = pillar_history_for_symbol(db, symbol=symbol, limit=limit)
    if not items and symbol.upper() not in latest_snapshot_rows_by_symbol(db, symbols=[symbol.upper()]):
        raise HTTPException(status_code=404, detail=f"No fundamentals for {symbol.upper()}")
    return PillarHistoryOut(symbol=symbol.upper(), items=items, trend=trend)


@router.get("/methodology", response_model=FundamentalMethodologyOut)
def get_fundamental_methodology() -> FundamentalMethodologyOut:
    return FundamentalMethodologyOut(**methodology_payload())


@router.post("/recompute-betas", dependencies=[Depends(require_admin)])
def recompute_fundamental_betas(
    db: Session = Depends(get_db),
    as_of: str | None = None,
    window_years: float = 2.0,
    frequency: str = "weekly",
    proxy_symbol: str = "MASI",
    recompute_valuations: bool = True,
) -> dict[str, Any]:
    parsed_as_of = _parse_date(as_of, default=None) if as_of else None
    try:
        summary = recompute_universe_betas(
            db,
            as_of=parsed_as_of,
            window_years=window_years,
            frequency=frequency,
            proxy_symbol=proxy_symbol,
        )
        valuation_symbols = 0
        valuation_count = 0
        computed_symbols = [str(symbol).upper() for symbol in summary.get("computed_symbols", [])]
        if recompute_valuations and computed_symbols:
            snapshots = latest_snapshot_rows_by_symbol(db, symbols=computed_symbols)
            overrides_loader = make_bulk_overrides_loader(db, list(snapshots))
            for symbol, snapshot in snapshots.items():
                valuation_count += len(
                    recompute_symbol_valuations_all_scenarios(
                        db,
                        import_id=snapshot.import_id,
                        symbol=symbol,
                        overrides_loader=overrides_loader,
                    )
                )
                valuation_symbols += 1
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=f"Could not persist fundamental betas: {exc}") from exc
    db.commit()
    return {
        **summary,
        "recompute_valuations": recompute_valuations,
        "valuation_symbols": valuation_symbols,
        "valuation_count": valuation_count,
    }


@router.post("/signal-backtest", response_model=FundamentalSignalBacktestOut, dependencies=[Depends(require_admin)])
def create_fundamental_signal_backtest(body: FundamentalSignalBacktestIn, db: Session = Depends(get_db)) -> FundamentalSignalBacktestOut:
    start = _parse_date(body.start, default=None) if body.start else None
    end = _parse_date(body.end, default=None) if body.end else None
    scenario = _scenario_or_422(body.scenario)
    if body.universe == "custom" and not body.symbols:
        raise HTTPException(status_code=422, detail="custom universe requires symbols")
    try:
        row = run_and_persist_fundamental_signal_backtest(
            db,
            signal=body.signal,
            universe=body.universe,
            start=start,
            end=end,
            transaction_cost_bps=body.transaction_cost_bps,
            long_short=body.long_short,
            symbols=body.symbols or None,
            scenario=scenario,
        )
        db.commit()
        db.refresh(row)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Fundamental signal backtest storage is not ready. Run the Alembic migration before launching a persisted live backtest.",
        ) from exc
    return _signal_backtest_out(row)


@router.get("/signal-backtest/{run_id}", response_model=FundamentalSignalBacktestOut)
def get_fundamental_signal_backtest(run_id: uuid.UUID, db: Session = Depends(get_db)) -> FundamentalSignalBacktestOut:
    row = db.get(models.FundamentalSignalBacktest, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No fundamental signal backtest {run_id}")
    return _signal_backtest_out(row)


@router.get("/stocks/{symbol}/metric-overrides", response_model=list[FundamentalMetricOverrideOut])
def get_stock_metric_overrides(symbol: str, db: Session = Depends(get_db)) -> list[FundamentalMetricOverrideOut]:
    symbol = symbol.upper()
    _ensure_known_fundamental_symbol(db, symbol)
    return [_metric_override_out(row) for row in current_metric_overrides(db, symbol=symbol)]


@router.put("/stocks/{symbol}/metric-overrides", response_model=FundamentalMetricOverrideOut)
def put_stock_metric_override(
    symbol: str,
    body: FundamentalMetricOverrideIn,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_app_user),
    _admin: None = Depends(require_admin),
) -> FundamentalMetricOverrideOut:
    symbol = symbol.upper()
    _ensure_known_fundamental_symbol(db, symbol)
    metric_name = _clean_text(body.metric_name)
    if not metric_name:
        raise HTTPException(status_code=422, detail="metric_name is required")
    if body.statement_year < 1900 or body.statement_year > 2200:
        raise HTTPException(status_code=422, detail="statement_year is invalid")
    metric_value = body.metric_value
    if metric_value is not None and (not isinstance(metric_value, (int, float)) or not isfinite(float(metric_value))):
        raise HTTPException(status_code=422, detail="metric_value must be a finite number or null")
    db.query(models.FundamentalMetricOverride).filter(
        models.FundamentalMetricOverride.symbol == symbol,
        models.FundamentalMetricOverride.statement_year == int(body.statement_year),
        models.FundamentalMetricOverride.metric_name == metric_name,
        models.FundamentalMetricOverride.is_current.is_(True),
    ).update({"is_current": False}, synchronize_session=False)
    row = models.FundamentalMetricOverride(
        symbol=symbol,
        statement_year=int(body.statement_year),
        metric_name=metric_name,
        metric_value=float(metric_value) if metric_value is not None else None,
        note=_clean_text(body.note or "") or None,
        created_by=_created_by(user),
        is_current=True,
    )
    db.add(row)
    db.flush()
    row_id = int(row.id)
    db.commit()

    try:
        refresh_symbol_after_metric_override(db, symbol=symbol)
        _sync_fundamental_signal_rows(db, [symbol])
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Metric override was saved but refresh failed: {exc}") from exc

    current = db.get(models.FundamentalMetricOverride, row_id)
    if current is None:
        raise HTTPException(status_code=500, detail="Metric override was committed but could not be reloaded")
    return _metric_override_out(current)


@router.delete("/stocks/{symbol}/metric-overrides/{statement_year}/{metric_name}", status_code=204)
def delete_stock_metric_override(
    symbol: str,
    statement_year: int,
    metric_name: str,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_app_user),
    _admin: None = Depends(require_admin),
) -> Response:
    del user
    symbol = symbol.upper()
    metric_name = _clean_text(metric_name)
    _ensure_known_fundamental_symbol(db, symbol)
    db.query(models.FundamentalMetricOverride).filter(
        models.FundamentalMetricOverride.symbol == symbol,
        models.FundamentalMetricOverride.statement_year == int(statement_year),
        models.FundamentalMetricOverride.metric_name == metric_name,
        models.FundamentalMetricOverride.is_current.is_(True),
    ).update({"is_current": False}, synchronize_session=False)
    db.commit()
    try:
        refresh_symbol_after_metric_override(db, symbol=symbol)
        _sync_fundamental_signal_rows(db, [symbol])
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Metric override was cleared but refresh failed: {exc}") from exc
    return Response(status_code=204)


@router.get("/{symbol}/assumptions/{scenario}", response_model=AssumptionResolvedOut)
@router.get("/stocks/{symbol}/assumptions/{scenario}", response_model=AssumptionResolvedOut)
def get_stock_assumptions(symbol: str, scenario: str, db: Session = Depends(get_db)) -> AssumptionResolvedOut:
    symbol = symbol.upper()
    scenario = _scenario_or_422(scenario)
    metadata = _metadata_by_symbol(db, [symbol]).get(symbol, {})
    overrides_loader = make_bulk_overrides_loader(db, [symbol])
    assumptions, provenance = resolved_assumptions_with_provenance(
        db,
        symbol=symbol,
        sector=metadata.get("sector"),
        scenario=scenario,
        overrides_loader=overrides_loader,
    )
    return AssumptionResolvedOut(
        symbol=symbol,
        scenario=scenario,
        assumptions=assumptions,
        provenance=provenance,
        scenario_probabilities=_scenario_probabilities_payload(assumptions),
        warnings=_assumption_warnings_payload(assumptions),
    )


@router.get("/{symbol}/assumptions/{scenario}/override", response_model=AssumptionOverrideOut)
@router.get("/stocks/{symbol}/assumptions/{scenario}/override", response_model=AssumptionOverrideOut)
def get_stock_assumption_override(symbol: str, scenario: str, db: Session = Depends(get_db)) -> AssumptionOverrideOut:
    row = _current_assumption_override(db, symbol=symbol.upper(), scenario=scenario)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No current assumption override for {symbol.upper()} {scenario}")
    return _assumption_override_out(row)


@router.put("/{symbol}/assumptions/{scenario}/override", response_model=AssumptionOverrideOut)
@router.put("/stocks/{symbol}/assumptions/{scenario}/override", response_model=AssumptionOverrideOut)
def put_stock_assumption_override(
    symbol: str,
    scenario: str,
    body: AssumptionOverrideIn,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_app_user),
    _admin: None = Depends(require_admin),
) -> AssumptionOverrideOut:
    symbol = symbol.upper()
    scenario = _scenario_or_422(scenario)
    _ensure_known_fundamental_symbol(db, symbol)
    try:
        overrides = clean_assumption_override_values(body.overrides)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.query(models.FundamentalAssumptionOverride).filter(
        models.FundamentalAssumptionOverride.symbol == symbol,
        models.FundamentalAssumptionOverride.scenario == scenario,
        models.FundamentalAssumptionOverride.is_current.is_(True),
    ).update({"is_current": False}, synchronize_session=False)
    row = models.FundamentalAssumptionOverride(
        symbol=symbol,
        scenario=scenario,
        overrides=overrides,
        note=_clean_text(body.note or "") or None,
        created_by=_created_by(user),
        is_current=True,
    )
    db.add(row)
    db.flush()
    snapshot = latest_snapshot_rows_by_symbol(db, symbols=[symbol]).get(symbol)
    if snapshot is not None:
        recompute_symbol_valuations_all_scenarios(
            db,
            import_id=snapshot.import_id,
            symbol=symbol,
            overrides_loader=make_bulk_overrides_loader(db, [symbol]),
        )
        _sync_fundamental_signal_rows(db, [symbol])
    db.commit()
    current = _current_assumption_override(db, symbol=symbol, scenario=scenario)
    if current is None:
        raise HTTPException(status_code=500, detail="Assumption override was committed but could not be reloaded")
    return _assumption_override_out(current)


@router.delete("/{symbol}/assumptions/{scenario}/override", status_code=204)
@router.delete("/stocks/{symbol}/assumptions/{scenario}/override", status_code=204)
def delete_stock_assumption_override(
    symbol: str,
    scenario: str,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_app_user),
    _admin: None = Depends(require_admin),
) -> Response:
    del user
    symbol = symbol.upper()
    scenario = _scenario_or_422(scenario)
    _ensure_known_fundamental_symbol(db, symbol)
    db.query(models.FundamentalAssumptionOverride).filter(
        models.FundamentalAssumptionOverride.symbol == symbol,
        models.FundamentalAssumptionOverride.scenario == scenario,
        models.FundamentalAssumptionOverride.is_current.is_(True),
    ).update({"is_current": False}, synchronize_session=False)
    snapshot = latest_snapshot_rows_by_symbol(db, symbols=[symbol]).get(symbol)
    if snapshot is not None:
        recompute_symbol_valuations_all_scenarios(
            db,
            import_id=snapshot.import_id,
            symbol=symbol,
            overrides_loader=make_bulk_overrides_loader(db, [symbol]),
        )
        _sync_fundamental_signal_rows(db, [symbol])
    db.commit()
    return Response(status_code=204)


@router.delete("/stocks/{symbol}/assumptions/{scenario}", status_code=204, dependencies=[Depends(require_admin)])
def delete_stock_assumptions(symbol: str, scenario: str, db: Session = Depends(get_db)) -> Response:
    db.query(models.FundamentalAssumptionSet).filter(
        models.FundamentalAssumptionSet.scope_type == "symbol",
        models.FundamentalAssumptionSet.scope_key == symbol.upper(),
        models.FundamentalAssumptionSet.scenario == scenario,
        models.FundamentalAssumptionSet.is_active.is_(True),
    ).update({"is_active": False}, synchronize_session=False)
    snapshot = latest_snapshot_rows_by_symbol(db, symbols=[symbol.upper()]).get(symbol.upper())
    if snapshot is not None:
        recompute_symbol_valuations_all_scenarios(db, import_id=snapshot.import_id, symbol=symbol)
    db.commit()
    return Response(status_code=204)


def _detail_context(detail: FundamentalStockDetailOut) -> dict[str, Any]:
    return detail.model_dump()


@router.get("/stocks/{symbol}/tearsheet", response_class=HTMLResponse)
def get_stock_tearsheet(symbol: str, db: Session = Depends(get_db), lang: str = "fr", format: str = "html") -> HTMLResponse:
    detail = get_fundamental_stock_detail(symbol, db=db, scenario="base")
    html = render_tearsheet(_detail_context(detail), lang=lang, artefact="tearsheet")
    return HTMLResponse(content=html, media_type="text/html")


@router.get("/stocks/{symbol}/ic-memo", response_class=HTMLResponse)
def get_stock_ic_memo(symbol: str, db: Session = Depends(get_db), lang: str = "fr") -> HTMLResponse:
    detail = get_fundamental_stock_detail(symbol, db=db, scenario="base")
    html = render_tearsheet(_detail_context(detail), lang=lang, artefact="ic-memo")
    return HTMLResponse(content=html, media_type="text/html")


@router.get("/morning-note", response_class=HTMLResponse)
def get_morning_note(
    db: Session = Depends(get_db),
    date: str | None = None,
    symbols: str | None = None,
    lang: str = "fr",
) -> HTMLResponse:
    note_date = _parse_date(date, default=dt.date.today())
    requested = [item.strip().upper() for item in (symbols or "").split(",") if item.strip()]
    snapshot_rows = latest_snapshot_rows_by_symbol(db, symbols=requested or None)
    rows: list[dict[str, Any]] = []
    if snapshot_rows:
        ensembles, _valuations = _latest_available_valuation_bundle(db, list(snapshot_rows), "base")
        for symbol, snapshot in sorted(snapshot_rows.items()):
            ensemble = ensembles.get(symbol)
            rows.append(
                {
                    "symbol": symbol,
                    "company_name": snapshot.company_name,
                    "upside_pct": ensemble.upside_pct if ensemble else None,
                    "recommendation": derive_research_overlay(db, symbol=symbol, scenario="base", ensemble=ensemble, import_row=db.get(models.FundamentalImport, snapshot.import_id)).get("recommendation"),
                }
            )
    catalyst_rows = (
        db.query(models.FundamentalCatalyst)
        .filter(
            models.FundamentalCatalyst.is_active.is_(True),
            models.FundamentalCatalyst.event_date == note_date,
            models.FundamentalCatalyst.impact_tier.in_(["high", "moderate"]),
        )
        .order_by(models.FundamentalCatalyst.symbol.asc(), models.FundamentalCatalyst.id.asc())
        .all()
    )
    html = render_morning_note(
        {"date": note_date.isoformat(), "rows": rows, "catalysts": [_catalyst_out(row).model_dump() for row in catalyst_rows]},
        lang=lang,
    )
    return HTMLResponse(content=html, media_type="text/html")


@router.put("/assumptions/{scenario}", response_model=AssumptionSetOut, dependencies=[Depends(require_admin)])
def update_assumptions(scenario: str, body: AssumptionUpdateIn, db: Session = Depends(get_db)) -> AssumptionSetOut:
    scenario_key = _scenario_or_422(scenario)
    unknown = sorted(set(body.assumptions) - set(DEFAULT_ASSUMPTIONS) - {"currency"})
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown assumption keys: {', '.join(unknown)}")
    row = upsert_assumptions(
        db,
        scenario=scenario_key,
        assumptions=body.assumptions,
        scope_type=body.scope_type,
        scope_key=body.scope_key,
        version_label=body.version_label,
    )
    recomputed_symbols: list[str] = []
    if body.scope_type.strip().lower() == "desk":
        for symbol, snapshot in latest_snapshot_rows_by_symbol(db).items():
            recompute_symbol_valuations_all_scenarios(db, import_id=snapshot.import_id, symbol=symbol)
            recomputed_symbols.append(symbol)
    _sync_fundamental_signal_rows(db, recomputed_symbols)
    db.commit()
    return AssumptionSetOut(
        scope_type=row.scope_type,
        scope_key=row.scope_key,
        scenario=row.scenario,
        version_label=row.version_label,
        assumptions=dict(row.assumptions_json or {}),
        source=row.source,
        is_active=bool(row.is_active),
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.put("/stocks/{symbol}/assumptions/{scenario}", response_model=AssumptionSetOut, dependencies=[Depends(require_admin)])
def update_stock_assumptions(symbol: str, scenario: str, body: AssumptionUpdateIn, db: Session = Depends(get_db)) -> AssumptionSetOut:
    scenario_key = _scenario_or_422(scenario)
    snapshot, _import_row = _latest_snapshot_or_404(db, symbol)
    unknown = sorted(set(body.assumptions) - set(DEFAULT_ASSUMPTIONS) - {"currency"})
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown assumption keys: {', '.join(unknown)}")
    row = upsert_assumptions(
        db,
        scenario=scenario_key,
        assumptions=body.assumptions,
        scope_type="symbol",
        scope_key=symbol.upper(),
        version_label=body.version_label,
    )
    valuation_rows = recompute_symbol_valuations_all_scenarios(db, import_id=snapshot.import_id, symbol=symbol)
    valuations = [row for row in valuation_rows if str(row.scenario) == scenario_key]
    _sync_fundamental_signal_rows(db, [symbol])
    metadata = _metadata_by_symbol(db, [symbol.upper()]).get(symbol.upper(), {})
    _assumptions, provenance = resolved_assumptions_with_provenance(db, symbol=symbol, sector=metadata.get("sector"), scenario=scenario_key)
    db.commit()
    return AssumptionSetOut(
        scope_type=row.scope_type,
        scope_key=row.scope_key,
        scenario=row.scenario,
        version_label=row.version_label,
        assumptions=dict(row.assumptions_json or {}),
        source=row.source,
        is_active=bool(row.is_active),
        provenance=provenance,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        valuations=[_valuation_out(item) for item in valuations],
    )


@router.post("/recompute-signals", response_model=FundamentalSignalRecomputeOut, dependencies=[Depends(require_admin)])
def recompute_fundamental_signals(
    body: FundamentalSignalRecomputeIn,
    db: Session = Depends(get_db),
) -> FundamentalSignalRecomputeOut:
    scenarios = _fundamental_recompute_scenarios(body.scenario)
    symbol = str(body.symbol or "").strip().upper() or None
    failures: list[dict[str, str | None]] = []
    snapshot_count = 0
    pillar_history_count = 0
    valuation_count = 0

    if symbol:
        _latest_snapshot_or_404(db, symbol)
        symbols = [symbol]
        if body.refresh_scores:
            try:
                refreshed = refresh_symbol_after_metric_override(db, symbol=symbol)
                snapshot_count += int(refreshed.get("snapshot_count") or 0)
                valuation_count += int(refreshed.get("valuation_count") or 0)
                db.commit()
            except Exception as exc:
                db.rollback()
                failures.append({"symbol": symbol, "scenario": None, "error": str(exc)})
        else:
            snapshots = latest_snapshot_rows_by_symbol(db, symbols=[symbol])
            snapshot = snapshots.get(symbol)
            if snapshot is None:
                failures.append({"symbol": symbol, "scenario": None, "error": "No fundamental snapshot"})
            else:
                overrides_loader = make_bulk_overrides_loader(db, [symbol])
                if set(scenarios) == set(VALUATION_SCENARIOS):
                    try:
                        valuation_count += len(
                            recompute_symbol_valuations_all_scenarios(
                                db,
                                import_id=snapshot.import_id,
                                symbol=symbol,
                                scenarios=VALUATION_SCENARIOS,
                                overrides_loader=overrides_loader,
                            )
                        )
                        db.commit()
                    except Exception as exc:
                        db.rollback()
                        failures.append({"symbol": symbol, "scenario": "all", "error": str(exc)})
                else:
                    for scenario_key in scenarios:
                        try:
                            valuation_count += len(
                                recompute_symbol_valuations(
                                    db,
                                    import_id=snapshot.import_id,
                                    symbol=symbol,
                                    scenario=scenario_key,
                                    overrides_loader=overrides_loader,
                                )
                            )
                            db.commit()
                        except Exception as exc:
                            db.rollback()
                            failures.append({"symbol": symbol, "scenario": scenario_key, "error": str(exc)})

        signal_summary = _sync_fundamental_signal_rows(db, symbols)
        db.commit()
        return FundamentalSignalRecomputeOut(
            symbol_count=len(symbols),
            scenario=body.scenario,
            scenarios=scenarios,
            snapshot_count=snapshot_count,
            pillar_history_count=pillar_history_count,
            valuation_count=valuation_count,
            signal_summary=signal_summary,
            failures=failures,
        )

    snapshots = latest_snapshot_rows_by_symbol(db)
    if not snapshots:
        raise HTTPException(status_code=404, detail="No succeeded fundamental import found")

    if body.refresh_scores:
        snapshot_count = rescore_universe(db, scope="all")
        db.commit()
        snapshots = latest_snapshot_rows_by_symbol(db)
        for import_id in sorted({row.import_id for row in snapshots.values()}, key=str):
            pillar_history_count += persist_pillar_history_for_import(db, import_id=import_id)
            db.commit()

    symbols = sorted(snapshots)
    overrides_loader = make_bulk_overrides_loader(db, symbols)
    for item in symbols:
        snapshot = snapshots[item]
        if set(scenarios) == set(VALUATION_SCENARIOS):
            try:
                valuation_count += len(
                    recompute_symbol_valuations_all_scenarios(
                        db,
                        import_id=snapshot.import_id,
                        symbol=item,
                        scenarios=VALUATION_SCENARIOS,
                        overrides_loader=overrides_loader,
                    )
                )
                db.commit()
            except Exception as exc:
                db.rollback()
                failures.append({"symbol": item, "scenario": "all", "error": str(exc)})
        else:
            for scenario_key in scenarios:
                try:
                    valuation_count += len(
                        recompute_symbol_valuations(
                            db,
                            import_id=snapshot.import_id,
                            symbol=item,
                            scenario=scenario_key,
                            overrides_loader=overrides_loader,
                        )
                    )
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    failures.append({"symbol": item, "scenario": scenario_key, "error": str(exc)})

    signal_summary = _sync_fundamental_signal_rows(db, symbols)
    db.commit()
    return FundamentalSignalRecomputeOut(
        symbol_count=len(symbols),
        scenario=body.scenario,
        scenarios=scenarios,
        snapshot_count=snapshot_count,
        pillar_history_count=pillar_history_count,
        valuation_count=valuation_count,
        signal_summary=signal_summary,
        failures=failures,
    )


@router.post("/recompute", response_model=FundamentalImportOut, dependencies=[Depends(require_admin)])
def recompute_fundamentals(db: Session = Depends(get_db), scenario: str = "all", symbol: str | None = None) -> FundamentalImportOut:
    scenario_key = (scenario or "all").strip().lower()
    if scenario_key != "all":
        scenario_key = _scenario_or_422(scenario_key)
    recomputed_symbols: list[str] = []
    if symbol:
        snapshot, import_row = _latest_snapshot_or_404(db, symbol)
        if scenario_key == "all":
            recompute_symbol_valuations_all_scenarios(db, import_id=snapshot.import_id, symbol=symbol, scenarios=VALUATION_SCENARIOS)
        else:
            recompute_symbol_valuations(db, import_id=snapshot.import_id, symbol=symbol, scenario=scenario_key)
        recomputed_symbols.append(symbol.upper())
    else:
        snapshots = latest_snapshot_rows_by_symbol(db)
        if not snapshots:
            raise HTTPException(status_code=404, detail="No succeeded fundamental import found")
        import_row = latest_import(db) or db.get(models.FundamentalImport, next(iter(snapshots.values())).import_id)
        for item, snapshot_row in snapshots.items():
            if scenario_key == "all":
                recompute_symbol_valuations_all_scenarios(db, import_id=snapshot_row.import_id, symbol=item, scenarios=VALUATION_SCENARIOS)
            else:
                recompute_symbol_valuations(db, import_id=snapshot_row.import_id, symbol=item, scenario=scenario_key)
            recomputed_symbols.append(item)
    if scenario_key in {"base", "all"}:
        _sync_fundamental_signal_rows(db, recomputed_symbols)
    db.commit()
    db.refresh(import_row)
    return _import_out(import_row)
