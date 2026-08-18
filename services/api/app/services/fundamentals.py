from __future__ import annotations

import datetime as dt
import logging
import os
import unicodedata
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from math import isfinite
from statistics import median
from typing import Any, Callable, Literal

from sqlalchemy import func, inspect as sa_inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, load_only
from sqlalchemy.orm.attributes import set_committed_value

from core.quant_core.fundamentals.cgnc_mapping import resolve_metric_name
from core.quant_core.fundamentals import (
    ASSUMPTION_META,
    DEFAULT_ASSUMPTIONS,
    PITSignalSnapshot,
    SignalBacktestConfig,
    compute_default_sensitivity_grids,
    compute_sensitivity,
    compute_symbol_valuations,
    compute_valuation_ensemble,
    available_horizons,
    build_projection,
    default_assumptions_for_scenario,
    enrich_terminal_growth_assumptions,
    cost_of_equity_capm,
    infer_statement_archetype,
    is_cyclical_or_commodity,
    map_cgnc_annual_metrics,
    normalize_scenario_probabilities,
    parse_fundamental_workbook,
    peer_driver_medians,
    resolve_assumptions,
    run_signal_backtest,
    scenario_probabilities_from_assumptions,
    score_fundamental_snapshots,
    wacc_build_up,
)
from core.quant_core.fundamentals.integrity import build_data_tieout_report, build_integrity_report, overall_status, report_from_dict, report_to_dict
from core.quant_core.fundamentals.projection import Projection
from core.quant_core.fundamentals.domain import (
    AnnualMetricRow,
    DataTieOutReport,
    FundamentalQualityIssue,
    FundamentalSnapshot,
    FundamentalWorkbook,
    IntegrityCheck,
    IntegrityReport,
    PeriodMetricRow,
    ValuationResult,
)
from core.quant_core.fundamentals.valuation import (
    VALUATION_MODEL_ORDER,
    _ensemble_weight_overrides_from_assumptions,
    _is_financial,
    _peer_stats,
    _relative_multiples,
)
from core.quant_core.fundamentals.trends import PILLAR_KEYS, classify_all_pillar_trends

from .. import models
from ..json_sanitize import sanitize_json_compatible
from ..market_data_loader import load_close_series_from_store
from .bourse_live_quotes import effective_price_from_quote, get_cached_live_quotes, get_or_refresh_live_quotes
from .consensus import load_forward_view
from .fundamental_macro import resolve_macro_config
from .model_forecast import load_model_forecast_view


METHODOLOGY_VERSION = "v3"
SUCCEEDED_IMPORT_STATUSES = ("succeeded", "partial")
FundamentalScope = Literal["masi", "non_masi", "all"]
VALUATION_SCENARIOS = ("bear", "base", "bull")
FUNDAMENTAL_LIVE_QUOTE_MAX_AGE_SECONDS = 6 * 60 * 60
AssumptionOverrideLoader = Callable[[str, str], dict[str, float] | None]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResearchOverlayPrefetch:
    """Bulk-loaded inputs used to derive research overlays without per-symbol SQL."""

    rating_inputs: dict[tuple[uuid.UUID, str], tuple[float | None, float | None]]
    verification_reasons: dict[tuple[uuid.UUID, str], str | None]
    data_cutoffs: dict[tuple[uuid.UUID, str], dt.date | None]
    horizon_predictions: dict[tuple[uuid.UUID, str], list[dict[str, Any]]]
    revision_targets: dict[str, list[tuple[uuid.UUID, float]]]
    base_ensembles: dict[tuple[uuid.UUID, str], models.FundamentalEnsembleResult]


def normalize_period_label(period_type: str | None, period_label: str | None) -> str:
    """Canonicalize equivalent period labels used by different providers."""
    normalized_type = str(period_type or "annual").strip().lower()
    label = str(period_label or "").strip().upper()
    if normalized_type == "semiannual":
        if label in {"S1", "SEM1", "SEMESTRE1", "SEMESTRE 1", "1"}:
            return "H1"
        if label in {"S2", "SEM2", "SEMESTRE2", "SEMESTRE 2", "2"}:
            return "H2"
    return label or ("FY" if normalized_type == "annual" else "")

PHASE2_STATIC_RETIRED_ASSUMPTIONS = {
    "growth_cap",
    "terminal_growth",
    "terminal_growth_firm",
    "terminal_growth_equity",
}

FINANCIAL_SECTOR_TOKENS = (
    "banque",
    "bank",
    "assurance",
    "insurance",
    "takaful",
    "financement",
    "leasing",
    "credit",
)
BANK_SECTOR_TOKENS = ("banque", "bank")
INSURANCE_SECTOR_TOKENS = ("assurance", "insurance", "takaful")
GENERAL_FINANCIAL_SECTOR_TOKENS = ("financement", "leasing", "credit")
FINANCIAL_SUPPRESSED_METRICS = {
    "Capex",
    "Capital_Expenditures",
    "EBITDA",
    "EnterpriseValue",
    "Enterprise_Value",
    "EV_to_EBITDA",
    "EV_to_Sales",
    "FCF_Margin",
    "FCF_Yield",
    "Free_Cash_Flow",
    "Net_Debt",
    "Price_to_Sales",
}

SYNTHETIC_COVERAGE_SPREADS = (
    (8.5, "AA", 0.010),
    (6.5, "A+", 0.014),
    (5.0, "A", 0.018),
    (3.5, "BBB", 0.026),
    (2.5, "BB", 0.034),
    (1.5, "B", 0.045),
    (0.8, "CCC", 0.055),
    (float("-inf"), "CC/C", 0.060),
)


_LATEST_SNAPSHOT_COLUMN_NAMES = tuple(column.name for column in models.FundamentalLatestSnapshot.__table__.columns)
_ANNUAL_METRIC_COLUMN_NAMES = tuple(column.name for column in models.FundamentalAnnualMetric.__table__.columns)


def _existing_table_columns(db: Session, model: Any) -> set[str]:
    try:
        return {str(column["name"]) for column in sa_inspect(db.connection()).get_columns(model.__tablename__)}
    except SQLAlchemyError:
        return {column.name for column in model.__table__.columns}


def _table_exists(db: Session, model: Any) -> bool:
    try:
        return bool(sa_inspect(db.connection()).has_table(model.__tablename__))
    except SQLAlchemyError:
        return True


def _load_options_for_existing_columns(db: Session, model: Any, column_names: tuple[str, ...]) -> tuple[list[Any], set[str]]:
    existing_columns = _existing_table_columns(db, model)
    if set(column_names).issubset(existing_columns):
        return [], existing_columns
    attrs = [getattr(model, name) for name in column_names if name in existing_columns]
    return ([load_only(*attrs)] if attrs else []), existing_columns


def _snapshot_query(db: Session) -> tuple[Any, set[str]]:
    options, columns = _load_options_for_existing_columns(db, models.FundamentalLatestSnapshot, _LATEST_SNAPSHOT_COLUMN_NAMES)
    query = db.query(models.FundamentalLatestSnapshot)
    if options:
        query = query.options(*options)
    return query, columns


def _annual_metric_query(db: Session) -> tuple[Any, set[str]]:
    options, columns = _load_options_for_existing_columns(db, models.FundamentalAnnualMetric, _ANNUAL_METRIC_COLUMN_NAMES)
    query = db.query(models.FundamentalAnnualMetric)
    if options:
        query = query.options(*options)
    return query, columns


def _coerce_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return dt.date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _legacy_snapshot_as_of(snapshot: models.FundamentalLatestSnapshot, import_row: models.FundamentalImport | None, columns: set[str]) -> dt.date | None:
    source = dict(snapshot.source_json or {}) if "source_json" in columns else {}
    coverage = dict(snapshot.coverage_json or {}) if "coverage_json" in columns else {}
    lineage = source.get("pit_lineage") if isinstance(source.get("pit_lineage"), dict) else {}
    for candidate in (
        lineage.get("as_of_date"),
        source.get("as_of_date"),
        coverage.get("pit_as_of_date"),
        coverage.get("as_of_date"),
    ):
        parsed = _coerce_date(candidate)
        if parsed is not None:
            return parsed
    stamp = (
        (import_row.completed_at if import_row is not None else None)
        or (import_row.imported_at if import_row is not None else None)
        or (import_row.created_at if import_row is not None else None)
    )
    return _coerce_date(stamp)


def _apply_snapshot_schema_compat(
    snapshot: models.FundamentalLatestSnapshot,
    import_row: models.FundamentalImport | None,
    columns: set[str],
) -> models.FundamentalLatestSnapshot:
    if "data_source" not in columns:
        set_committed_value(snapshot, "data_source", "workbook")
    if "as_of_date" not in columns:
        set_committed_value(snapshot, "as_of_date", _legacy_snapshot_as_of(snapshot, import_row, columns))
    if "source_document_id" not in columns:
        set_committed_value(snapshot, "source_document_id", None)
    if "is_canonical" not in columns:
        set_committed_value(snapshot, "is_canonical", None)
    return snapshot


def _apply_annual_schema_compat(row: models.FundamentalAnnualMetric, columns: set[str]) -> models.FundamentalAnnualMetric:
    if "as_of_date" not in columns:
        set_committed_value(row, "as_of_date", None)
    if "source_document_id" not in columns:
        set_committed_value(row, "source_document_id", None)
    return row


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
    "EV_to_EBIT",
    "EV_to_EBITDA",
    "EV_to_Sales",
    "NetDebt",
    "NetDebt_to_EBITDA",
    "NetDebt_to_Equity",
)

NON_STOCK_SYMBOLS = {"INSTRUMENT", "MAJ", "MAJJ", "WORKSHEET"}


def _parse_source_priority(raw: str | None) -> tuple[str, ...]:
    values: list[str] = []
    for item in (raw or "").split(","):
        value = item.strip().lower()
        if value and value not in values:
            values.append(value)
    return tuple(values)


MASI_FUNDAMENTAL_SOURCE_PRIORITY = _parse_source_priority(
    os.getenv("FUNDAMENTAL_MASI_SOURCE_PRIORITY", "stockanalysis,workbook,bvc,yfinance,demo_fixture")
)

CORE_STATEMENT_METRIC_GROUPS = (
    ("Revenue", "Chiffre_daffaires", "Clean_Chiffre_daffaires"),
    ("NetIncome", "Net_Income", "Resultat_net", "Clean_Resultat_net"),
    ("Total_Assets", "Total_Actif"),
    (
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
    ),
    ("Operating_Cash_Flow", "CF_Operating", "Flux_de_tresorerie_lies_a_lactivite"),
)
MIN_USABLE_MODELS_FOR_RATING = 3

# Statement totals the data-verification gate requires before a symbol can be rated.
# Each tuple is an alias group; the gate is satisfied only when every group has a value.
REQUIRED_GATE_METRIC_GROUPS = (
    ("Total_Actif", "Total_Assets", "Actif_Total"),
    (
        "Total_Passif",
        "Total_Liabilities",
        "Total_Liabilities_And_Equity",
        "Passif_Total",
        "Total_Debt_And_Liabilities",
    ),
    (
        "Capitaux_propres",
        "Total_Equity",
        "Capitaux_propres_part_du_groupe",
        "Shareholders_Equity",
        "Total_Shareholders_Equity",
    ),
    ("Resultat_net", "NetIncome", "Net_Income", "Resultat_net_part_du_groupe"),
)

# Balance-sheet identity (CGNC/IFRS): Total Assets == Total Equity & Liabilities.
_BS_ASSETS_TOTAL_ALIASES = ("Total_Actif", "Total_Assets", "Actif_Total")
_BS_PASSIF_TOTAL_ALIASES = (
    "Total_Liabilities_And_Equity",
    "Total_Passif",
    "Passif_Total",
    "Total_Liabilities",
    "Total_Debt_And_Liabilities",
)
_BS_SYNTH_PASSIF_METRIC = "Total_Liabilities_And_Equity"


def _metric_groups_complete(present: set[str]) -> bool:
    """True when every required statement-total alias group has a present metric."""
    return all(any(name in present for name in group) for group in REQUIRED_GATE_METRIC_GROUPS)


def _upside_from_price(fair_value: Any, current_price: Any) -> float | None:
    fair = _num(fair_value)
    current = _positive_num(current_price)
    if fair is None or current is None:
        return None
    return fair / current - 1.0


def derive_recommendation(
    ensemble: models.FundamentalEnsembleResult | None,
    *,
    current_price: Any = None,
    cost_of_equity: Any = None,
    forward_dividend_yield: Any = None,
) -> str | None:
    """Map expected total return over required return to the 5-tier research ladder."""

    if ensemble is None:
        return "NR"
    warnings = list(ensemble.warnings_json or [])
    if any(str(warning).startswith("data_unverified_nr") for warning in warnings):
        return "NR"
    if "no_usable_valuation_models" in warnings:
        return "NR"
    current = _positive_num(current_price)
    if current is None:
        current = _positive_num(ensemble.current_price)
    target = _positive_num(ensemble.fair_value_base)
    confidence = _num(ensemble.confidence_score)
    usable_models = max(0, int(ensemble.usable_model_count or 0))
    agreement = _ensemble_agreement(ensemble)
    cost = _positive_num(cost_of_equity)
    dividend_yield = _num(forward_dividend_yield)
    if dividend_yield is None:
        dividend_yield = 0.0
    if (
        target is None
        or current is None
        or confidence is None
        or cost is None
        or usable_models < MIN_USABLE_MODELS_FOR_RATING
        or agreement < float(DEFAULT_ASSUMPTIONS["rating_agreement_min"])
        or confidence < float(DEFAULT_ASSUMPTIONS["rating_confidence_min"])
    ):
        return "NR"
    expected_total_return = target / current - 1.0 + dividend_yield
    excess = expected_total_return - cost
    if excess > float(DEFAULT_ASSUMPTIONS["rating_buy_excess_return"]):
        return "BUY"
    if excess >= float(DEFAULT_ASSUMPTIONS["rating_accumulate_excess_return"]):
        return "ACCUMULATE"
    if excess >= float(DEFAULT_ASSUMPTIONS["rating_reduce_excess_return"]):
        return "HOLD"
    if excess >= float(DEFAULT_ASSUMPTIONS["rating_sell_excess_return"]):
        return "REDUCE"
    return "SELL"


def _ensemble_agreement(ensemble: models.FundamentalEnsembleResult | None) -> float:
    if ensemble is None:
        return 0.0
    cv = _num(getattr(ensemble, "model_dispersion_cv", None))
    if cv is None:
        return 1.0
    return max(0.0, 1.0 - min(1.0, cv))


def _rating_inputs_from_valuation_rows(
    db: Session,
    *,
    symbol: str,
    import_id: uuid.UUID | None,
    scenario: str,
) -> tuple[float | None, float | None]:
    if import_id is None:
        return None, None
    rows = (
        db.query(models.FundamentalValuationResult)
        .filter(
            models.FundamentalValuationResult.symbol == symbol.upper(),
            models.FundamentalValuationResult.import_id == import_id,
            models.FundamentalValuationResult.scenario == scenario,
        )
        .all()
    )
    costs: list[float] = []
    dividend_yields: list[float] = []
    for row in rows:
        inputs = row.inputs_json or {}
        cost = _positive_num(inputs.get("cost_of_equity"))
        if cost is not None:
            costs.append(cost)
        dividend_yield = _num(inputs.get("dividend_yield"))
        if dividend_yield is not None and dividend_yield >= 0:
            dividend_yields.append(dividend_yield)
    return (
        float(median(costs)) if costs else None,
        float(median(dividend_yields)) if dividend_yields else 0.0,
    )


def _base_ensemble_for_overlay(
    db: Session,
    *,
    symbol: str,
    ensemble: models.FundamentalEnsembleResult | None,
    import_row: models.FundamentalImport | None,
) -> models.FundamentalEnsembleResult | None:
    import_id = ensemble.import_id if ensemble is not None else import_row.id if import_row is not None else None
    if ensemble is not None and str(ensemble.scenario or "base").lower() == "base":
        return ensemble
    if import_id is None:
        return None
    base = (
        db.query(models.FundamentalEnsembleResult)
        .filter(
            models.FundamentalEnsembleResult.symbol == symbol.upper(),
            models.FundamentalEnsembleResult.import_id == import_id,
            models.FundamentalEnsembleResult.scenario == "base",
        )
        .one_or_none()
    )
    return base


def derive_conviction(ensemble: models.FundamentalEnsembleResult | None) -> int:
    """Conviction is a 1-5 ladder from confidence and model breadth."""

    if ensemble is None:
        return 0
    warnings = list(ensemble.warnings_json or [])
    if any(str(warning).startswith("data_unverified_nr") for warning in warnings):
        return 0
    if "no_usable_valuation_models" in warnings:
        return 0
    confidence = _num(ensemble.confidence_score) or 0.0
    model_count = max(0, int(ensemble.usable_model_count or 0))
    agreement = _ensemble_agreement(ensemble)
    if (
        confidence <= 0
        or model_count < MIN_USABLE_MODELS_FOR_RATING
        or agreement < float(DEFAULT_ASSUMPTIONS["rating_agreement_min"])
    ):
        return 0
    coverage = min(1.0, model_count / float(DEFAULT_ASSUMPTIONS["ensemble_confidence_target_models"]))
    raw = round((0.75 * confidence + 0.25 * coverage) * 5.0)
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


def load_research_overlay_prefetch(
    db: Session,
    *,
    import_ids_by_symbol: dict[str, uuid.UUID | None],
) -> ResearchOverlayPrefetch:
    """Load every universe-overlay input in a bounded number of queries."""

    normalized = {
        str(symbol).strip().upper(): import_id
        for symbol, import_id in import_ids_by_symbol.items()
        if symbol and import_id is not None
    }
    symbols = sorted(normalized)
    import_ids = sorted(set(normalized.values()), key=str)
    wanted_pairs = {(import_id, symbol) for symbol, import_id in normalized.items()}
    rating_inputs: dict[tuple[uuid.UUID, str], tuple[float | None, float | None]] = {}
    verification_reasons: dict[tuple[uuid.UUID, str], str | None] = {}
    data_cutoffs: dict[tuple[uuid.UUID, str], dt.date | None] = {}
    horizon_predictions: dict[tuple[uuid.UUID, str], list[dict[str, Any]]] = {}
    revision_targets: dict[str, list[tuple[uuid.UUID, float]]] = defaultdict(list)
    base_ensembles: dict[tuple[uuid.UUID, str], models.FundamentalEnsembleResult] = {}
    if not symbols:
        return ResearchOverlayPrefetch(
            rating_inputs=rating_inputs,
            verification_reasons=verification_reasons,
            data_cutoffs=data_cutoffs,
            horizon_predictions=horizon_predictions,
            revision_targets=dict(revision_targets),
            base_ensembles=base_ensembles,
        )

    valuation_rows = (
        db.query(models.FundamentalValuationResult)
        .filter(
            models.FundamentalValuationResult.symbol.in_(symbols),
            models.FundamentalValuationResult.import_id.in_(import_ids),
            models.FundamentalValuationResult.scenario == "base",
        )
        .all()
    )
    costs_by_pair: dict[tuple[uuid.UUID, str], list[float]] = defaultdict(list)
    yields_by_pair: dict[tuple[uuid.UUID, str], list[float]] = defaultdict(list)
    for row in valuation_rows:
        key = (row.import_id, str(row.symbol).upper())
        if key not in wanted_pairs:
            continue
        inputs = row.inputs_json or {}
        cost = _positive_num(inputs.get("cost_of_equity"))
        if cost is not None:
            costs_by_pair[key].append(cost)
        dividend_yield = _num(inputs.get("dividend_yield"))
        if dividend_yield is not None and dividend_yield >= 0:
            yields_by_pair[key].append(dividend_yield)
    for key in wanted_pairs:
        costs = costs_by_pair.get(key, [])
        dividend_yields = yields_by_pair.get(key, [])
        rating_inputs[key] = (
            float(median(costs)) if costs else None,
            float(median(dividend_yields)) if dividend_yields else 0.0,
        )

    snapshot_rows = (
        db.query(
            models.FundamentalLatestSnapshot.import_id,
            models.FundamentalLatestSnapshot.symbol,
            models.FundamentalLatestSnapshot.latest_statement_year,
            models.FundamentalLatestSnapshot.as_of_date,
            models.FundamentalLatestSnapshot.model_eligibility_json,
        )
        .filter(
            models.FundamentalLatestSnapshot.symbol.in_(symbols),
            models.FundamentalLatestSnapshot.import_id.in_(import_ids),
        )
        .all()
    )
    statement_years: dict[tuple[uuid.UUID, str], int | None] = {}
    for import_id, symbol, statement_year, as_of_date, eligibility_payload in snapshot_rows:
        key = (import_id, str(symbol).upper())
        if key not in wanted_pairs:
            continue
        statement_years[key] = statement_year
        data_cutoffs[key] = as_of_date
        raw_predictions = dict(eligibility_payload or {}).get("horizon_predictions")
        horizon_predictions[key] = [dict(item) for item in raw_predictions if isinstance(item, dict)] if isinstance(raw_predictions, list) else []

    if _table_exists(db, models.FundamentalDataVerification):
        verification_rows = (
            db.query(models.FundamentalDataVerification)
            .filter(
                models.FundamentalDataVerification.symbol.in_(symbols),
                models.FundamentalDataVerification.import_id.in_(import_ids),
            )
            .all()
        )
        for row in verification_rows:
            key = (row.import_id, str(row.symbol).upper())
            if key in wanted_pairs and statement_years.get(key) == row.statement_year:
                verification_reasons[key] = _data_unverified_reason(row)
    for key in wanted_pairs:
        verification_reasons.setdefault(key, None)
        horizon_predictions.setdefault(key, [])

    period_rows = (
        db.query(
            models.FundamentalPeriodMetric.import_id,
            models.FundamentalPeriodMetric.symbol,
            func.max(models.FundamentalPeriodMetric.period_end_date),
        )
        .filter(
            models.FundamentalPeriodMetric.symbol.in_(symbols),
            models.FundamentalPeriodMetric.import_id.in_(import_ids),
            models.FundamentalPeriodMetric.metric_value.isnot(None),
            models.FundamentalPeriodMetric.period_end_date.isnot(None),
        )
        .group_by(models.FundamentalPeriodMetric.import_id, models.FundamentalPeriodMetric.symbol)
        .all()
    )
    period_cutoffs: dict[tuple[uuid.UUID, str], dt.date] = {
        (import_id, str(symbol).upper()): cutoff
        for import_id, symbol, cutoff in period_rows
        if cutoff is not None
    }
    annual_rows = (
        db.query(
            models.FundamentalAnnualMetric.import_id,
            models.FundamentalAnnualMetric.symbol,
            models.FundamentalAnnualMetric.statement_year,
            models.FundamentalAnnualMetric.as_of_date,
        )
        .filter(
            models.FundamentalAnnualMetric.symbol.in_(symbols),
            models.FundamentalAnnualMetric.import_id.in_(import_ids),
            models.FundamentalAnnualMetric.metric_value.isnot(None),
        )
        .order_by(
            models.FundamentalAnnualMetric.statement_year.desc(),
            models.FundamentalAnnualMetric.as_of_date.desc().nullslast(),
        )
        .all()
    )
    annual_cutoffs: dict[tuple[uuid.UUID, str], dt.date] = {}
    for import_id, symbol, statement_year, as_of_date in annual_rows:
        key = (import_id, str(symbol).upper())
        if key in wanted_pairs and key not in annual_cutoffs:
            annual_cutoffs[key] = as_of_date or dt.date(int(statement_year), 12, 31)
    for key in wanted_pairs:
        data_cutoffs[key] = period_cutoffs.get(key) or data_cutoffs.get(key) or annual_cutoffs.get(key)

    revision_rows = (
        db.query(models.FundamentalEnsembleResult, models.FundamentalImport)
        .join(models.FundamentalImport, models.FundamentalEnsembleResult.import_id == models.FundamentalImport.id)
        .filter(
            models.FundamentalEnsembleResult.symbol.in_(symbols),
            models.FundamentalEnsembleResult.scenario == "base",
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
    for ensemble, _import_row in revision_rows:
        key = (ensemble.import_id, str(ensemble.symbol).upper())
        if key in wanted_pairs:
            base_ensembles[key] = ensemble
        target = _positive_num(ensemble.fair_value_base)
        if target is not None:
            revision_targets[str(ensemble.symbol).upper()].append((ensemble.import_id, target))

    return ResearchOverlayPrefetch(
        rating_inputs=rating_inputs,
        verification_reasons=verification_reasons,
        data_cutoffs=data_cutoffs,
        horizon_predictions=horizon_predictions,
        revision_targets=dict(revision_targets),
        base_ensembles=base_ensembles,
    )


def derive_research_overlay(
    db: Session,
    *,
    symbol: str,
    scenario: str,
    ensemble: models.FundamentalEnsembleResult | None,
    import_row: models.FundamentalImport | None,
    current_price: Any = None,
    free_float_pct: float | None = None,
    prefetched: ResearchOverlayPrefetch | None = None,
) -> dict[str, Any]:
    if prefetched is not None:
        candidate_import_id = ensemble.import_id if ensemble is not None else import_row.id if import_row is not None else None
        candidate_key = (candidate_import_id, symbol.upper()) if candidate_import_id is not None else None
        headline_ensemble = (
            ensemble
            if ensemble is not None and str(ensemble.scenario or "base").lower() == "base"
            else prefetched.base_ensembles.get(candidate_key)
        )
    else:
        headline_ensemble = _base_ensemble_for_overlay(db, symbol=symbol, ensemble=ensemble, import_row=import_row)
    import_id = headline_ensemble.import_id if headline_ensemble is not None else import_row.id if import_row is not None else None
    prefetch_key = (import_id, symbol.upper()) if import_id is not None else None
    if prefetched is not None:
        cost_of_equity, dividend_yield = prefetched.rating_inputs.get(prefetch_key, (None, 0.0))
    else:
        cost_of_equity, dividend_yield = _rating_inputs_from_valuation_rows(
            db,
            symbol=symbol,
            import_id=import_id,
            scenario="base",
        )
    recommendation = derive_recommendation(
        headline_ensemble,
        current_price=current_price,
        cost_of_equity=cost_of_equity,
        forward_dividend_yield=dividend_yield,
    )
    verification_reason = None
    if prefetched is not None:
        verification_reason = prefetched.verification_reasons.get(prefetch_key)
    elif import_id is not None:
        snapshot_year_row = (
            db.query(models.FundamentalLatestSnapshot.latest_statement_year)
            .filter(
                models.FundamentalLatestSnapshot.import_id == import_id,
                models.FundamentalLatestSnapshot.symbol == symbol.upper(),
            )
            .first()
        )
        verification_reason = _data_unverified_reason(
            latest_data_verification(
                db,
                import_id=import_id,
                symbol=symbol,
                statement_year=snapshot_year_row[0] if snapshot_year_row is not None else None,
            )
        )
    if verification_reason is not None:
        recommendation = "NR"
    target_price = _num(headline_ensemble.fair_value_base) if headline_ensemble is not None and recommendation != "NR" else None
    as_of_date = prefetched.data_cutoffs.get(prefetch_key) if prefetched is not None else _overlay_data_cutoff(db, symbol=symbol, import_id=import_id)
    valuation_date = None
    if headline_ensemble is not None and headline_ensemble.computed_at is not None:
        valuation_date = headline_ensemble.computed_at.date()
    elif import_row is not None:
        when = import_row.completed_at or import_row.imported_at or import_row.created_at
        valuation_date = when.date() if when else None
    target_date = _add_years(as_of_date, 1) if as_of_date is not None else None
    if prefetched is not None:
        horizon_predictions = [dict(item) for item in prefetched.horizon_predictions.get(prefetch_key, [])]
        override_price = _positive_num(current_price)
        if override_price is not None:
            for item in horizon_predictions:
                target = _positive_num(item.get("forward_target"))
                if target is not None:
                    item["upside"] = target / override_price - 1.0
        revision_direction = "="
        current_target = _positive_num(target_price)
        if current_target is not None:
            for candidate_import_id, previous_target in prefetched.revision_targets.get(symbol.upper(), []):
                if import_id is not None and candidate_import_id == import_id:
                    continue
                change = current_target / previous_target - 1.0
                revision_direction = "up" if change > 0.02 else "down" if change < -0.02 else "="
                break
    else:
        horizon_predictions = _horizon_predictions_from_snapshot_payload(db, symbol=symbol, import_id=import_id, current_price=current_price)
        revision_direction = derive_revision_direction(
            db,
            symbol=symbol,
            scenario="base",
            current_import_id=headline_ensemble.import_id if headline_ensemble is not None else import_row.id if import_row is not None else None,
            target_price=target_price,
        )
    return {
        "recommendation": recommendation,
        "target_price": target_price,
        "conviction": derive_conviction(headline_ensemble),
        "revision_direction": revision_direction,
        "analyst": "Systeme quantitatif",
        "as_of_date": as_of_date.isoformat() if as_of_date else None,
        "valuation_date": valuation_date.isoformat() if valuation_date else None,
        "target_date": target_date.isoformat() if target_date else None,
        "horizon_predictions": horizon_predictions,
        "free_float_pct": free_float_pct,
        "data_verification": {"status": "data_unverified", "reason": verification_reason} if verification_reason else None,
    }


def _add_years(value: dt.date, years: int) -> dt.date:
    try:
        return value.replace(year=value.year + int(years))
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + int(years))


def _add_months(value: dt.date, months: int) -> dt.date:
    month_index = value.month - 1 + int(months)
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, _month_last_day(year, month))
    return dt.date(year, month, day)


def _month_last_day(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (dt.date(year, month + 1, 1) - dt.timedelta(days=1)).day


def _overlay_data_cutoff(db: Session, *, symbol: str, import_id: uuid.UUID | None) -> dt.date | None:
    if import_id is None:
        return None
    symbol = symbol.upper()
    period_row = (
        db.query(models.FundamentalPeriodMetric.period_end_date)
        .filter(
            models.FundamentalPeriodMetric.import_id == import_id,
            models.FundamentalPeriodMetric.symbol == symbol,
            models.FundamentalPeriodMetric.metric_value.isnot(None),
            models.FundamentalPeriodMetric.period_end_date.isnot(None),
        )
        .order_by(models.FundamentalPeriodMetric.period_end_date.desc())
        .first()
    )
    if period_row is not None and period_row[0] is not None:
        return period_row[0]
    snapshot = (
        db.query(models.FundamentalLatestSnapshot)
        .filter(models.FundamentalLatestSnapshot.import_id == import_id, models.FundamentalLatestSnapshot.symbol == symbol)
        .first()
    )
    if snapshot is not None and snapshot.as_of_date is not None:
        return snapshot.as_of_date
    annual_row = (
        db.query(models.FundamentalAnnualMetric.statement_year, models.FundamentalAnnualMetric.as_of_date)
        .filter(
            models.FundamentalAnnualMetric.import_id == import_id,
            models.FundamentalAnnualMetric.symbol == symbol,
            models.FundamentalAnnualMetric.metric_value.isnot(None),
        )
        .order_by(models.FundamentalAnnualMetric.statement_year.desc(), models.FundamentalAnnualMetric.as_of_date.desc().nullslast())
        .first()
    )
    if annual_row is None:
        return None
    return annual_row[1] or dt.date(int(annual_row[0]), 12, 31)


def _horizon_predictions_from_snapshot_payload(
    db: Session,
    *,
    symbol: str,
    import_id: uuid.UUID | None,
    current_price: Any = None,
) -> list[dict[str, Any]]:
    if import_id is None:
        return []
    row = (
        db.query(models.FundamentalLatestSnapshot.model_eligibility_json)
        .filter(models.FundamentalLatestSnapshot.import_id == import_id, models.FundamentalLatestSnapshot.symbol == symbol.upper())
        .first()
    )
    payload = dict(row[0] or {}) if row is not None else {}
    raw = payload.get("horizon_predictions")
    if not isinstance(raw, list):
        return []
    override_price = _positive_num(current_price)
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        target = _positive_num(copied.get("forward_target"))
        if target is not None and override_price is not None:
            copied["upside"] = target / override_price - 1.0
        out.append(copied)
    return out


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
        updated = replace(row, symbol=canonical, period_label=normalize_period_label(row.period_type, row.period_label))
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
    canonical_names = {resolve_metric_name(n) for n in metric_names}
    by_year: dict[int, float] = {}
    for row in sorted(history, key=lambda r: r.statement_year):
        if resolve_metric_name(row.metric_name) not in canonical_names or row.metric_value is None:
            continue
        yr = int(row.statement_year)
        if yr not in by_year:
            value = _num(row.metric_value)
            if value is not None:
                by_year[yr] = value
    return by_year[max(by_year)] if by_year else None


def _snapshot_metric(metrics: dict[str, Any], *metric_names: str) -> float | None:
    for metric_name in metric_names:
        canonical = resolve_metric_name(metric_name)
        value = _num(metrics.get(canonical))
        if value is not None:
            return value
        if canonical != metric_name:
            value = _num(metrics.get(metric_name))
            if value is not None:
                return value
    return None


def _history_metric_series(history: list[AnnualMetricRow], *metric_names: str) -> list[float]:
    canonical_names = {resolve_metric_name(n) for n in metric_names}
    by_year: dict[int, float] = {}
    for row in sorted(history, key=lambda item: item.statement_year):
        if resolve_metric_name(row.metric_name) not in canonical_names:
            continue
        value = _num(row.metric_value)
        if value is not None and int(row.statement_year) not in by_year:
            by_year[int(row.statement_year)] = value
    return [by_year[yr] for yr in sorted(by_year)]


def _history_metric_year_map(history: list[AnnualMetricRow], *metric_names: str) -> dict[int, float]:
    canonical_names = {resolve_metric_name(n) for n in metric_names}
    out: dict[int, float] = {}
    for row in sorted(history, key=lambda item: (item.statement_year, item.as_of_date or dt.date.min, item.source_document_id or 0)):
        if resolve_metric_name(row.metric_name) not in canonical_names:
            continue
        value = _num(row.metric_value)
        if value is not None:
            out[int(row.statement_year)] = value
    return out


def _latest_non_null_history_year(history: list[AnnualMetricRow]) -> int | None:
    years = [int(row.statement_year) for row in history if _num(row.metric_value) is not None]
    return max(years) if years else None


def _year_over_year_growth(values_by_year: dict[int, float], year: int | None) -> float | None:
    if year is None or year not in values_by_year:
        return None
    previous_years = [candidate for candidate in values_by_year if candidate < year and values_by_year[candidate] != 0]
    if not previous_years:
        return None
    previous_year = max(previous_years)
    previous = values_by_year[previous_year]
    return (values_by_year[year] - previous) / abs(previous)


def _normalized_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _is_financial_sector(sector: str | None) -> bool:
    normalized = _normalized_text(sector)
    return any(token in normalized for token in FINANCIAL_SECTOR_TOKENS)


def _financial_archetype_for_sector(sector: str | None) -> str | None:
    normalized = _normalized_text(sector)
    if any(token in normalized for token in INSURANCE_SECTOR_TOKENS):
        return "insurance"
    if any(token in normalized for token in BANK_SECTOR_TOKENS):
        return "bank"
    if any(token in normalized for token in GENERAL_FINANCIAL_SECTOR_TOKENS):
        return "financial"
    return "financial" if _is_financial_sector(sector) else None


def _sanitize_financial_snapshot(snapshot: FundamentalSnapshot, *, sector: str | None) -> FundamentalSnapshot:
    if not _is_financial_sector(sector):
        return snapshot
    return replace(
        snapshot,
        metrics={key: value for key, value in dict(snapshot.metrics or {}).items() if key not in FINANCIAL_SUPPRESSED_METRICS},
    )


def _sanitize_financial_history(history: list[AnnualMetricRow], *, sector: str | None) -> list[AnnualMetricRow]:
    if not _is_financial_sector(sector):
        return history
    return [row for row in history if row.metric_name not in FINANCIAL_SUPPRESSED_METRICS]


def _synthetic_debt_spread(coverage: float | None) -> tuple[float | None, str | None]:
    if coverage is None:
        return None, None
    for threshold, bucket, spread in SYNTHETIC_COVERAGE_SPREADS:
        if coverage >= threshold:
            return spread, bucket
    return None, None


def _date_from_iso(value: Any) -> dt.date | None:
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _isoformat_datetime(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _overlay_live_quotes_on_price_context(
    db: Session,
    *,
    context: dict[str, dict[str, Any]],
    symbols: list[str],
) -> None:
    if str(os.getenv("FUNDAMENTAL_DISABLE_LIVE_QUOTES", "")).strip().lower() in {"1", "true", "yes"}:
        return
    try:
        quotes = get_cached_live_quotes(
            db,
            symbols,
            max_age_seconds=FUNDAMENTAL_LIVE_QUOTE_MAX_AGE_SECONDS,
        )
    except Exception:
        logger.debug("Fundamental live quote overlay unavailable", exc_info=True)
        return

    for symbol, quote in quotes.items():
        live_price = _positive_num(quote.last_price)
        if live_price is None or not quote.is_fresh:
            continue

        symbol_context = context.setdefault(symbol, {})
        official_date = _date_from_iso(symbol_context.get("price_as_of"))
        if quote.session_date is not None and official_date is not None and quote.session_date < official_date:
            continue

        effective_price, effective_source = effective_price_from_quote(
            official_price=_positive_num(symbol_context.get("current_price")),
            quote=quote,
            live_if_fresh=True,
        )
        if effective_source != "live":
            continue
        current_price = _positive_num(effective_price)
        if current_price is None:
            continue

        price_as_of = (
            quote.session_date.isoformat()
            if quote.session_date is not None
            else quote.quote_timestamp.date().isoformat()
            if quote.quote_timestamp is not None
            else None
        )
        symbol_context.update(
            {
                "current_price": current_price,
                "price_as_of": price_as_of,
                "price_source": "bourse_live_quote",
                "price_source_provider": quote.source_provider,
                "price_timeframe": "live",
                "price_source_url": quote.source_url,
                "live_quote_updated_at": _isoformat_datetime(quote.updated_at),
                "live_quote_age_seconds": quote.age_seconds,
            }
        )


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
    live_quote_symbols: list[str] = []
    for stock in stock_rows:
        symbol = str(stock.symbol).strip().upper()
        context.setdefault(symbol, {})
        asset_class = str(getattr(stock, "asset_class", None) or "equity").strip().lower()
        market_region = str(stock.market_region or "").strip().lower()
        if (
            symbol not in NON_STOCK_SYMBOLS
            and bool(getattr(stock, "is_active", True))
            and asset_class == "equity"
            and market_region == "masi"
        ):
            live_quote_symbols.append(symbol)
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
                "adv20": _positive_num(row.adv_20d),
                "price_as_of": price_as_of,
                "price_source": "market_data_store",
                "price_source_provider": row.source_provider,
                "price_timeframe": row.timeframe,
            }
        )

    if live_quote_symbols:
        _overlay_live_quotes_on_price_context(db, context=context, symbols=sorted(set(live_quote_symbols)))
    return context


def market_price_context_by_symbol(db: Session, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
    return _market_price_context_by_symbol(db, symbols)


def _history_by_symbol_for_snapshot_rows(
    db: Session,
    snapshot_rows: Iterable[models.FundamentalLatestSnapshot],
) -> dict[str, list[AnnualMetricRow]]:
    by_import: dict[uuid.UUID, list[str]] = defaultdict(list)
    for row in snapshot_rows:
        by_import[row.import_id].append(str(row.symbol).upper())

    out: dict[str, list[AnnualMetricRow]] = defaultdict(list)
    for import_id, symbols in by_import.items():
        query, annual_columns = _annual_metric_query(db)
        query = query.filter(
            models.FundamentalAnnualMetric.import_id == import_id,
            models.FundamentalAnnualMetric.symbol.in_(symbols),
        )
        for row in query.order_by(
            models.FundamentalAnnualMetric.symbol.asc(),
            models.FundamentalAnnualMetric.statement_year.asc(),
            models.FundamentalAnnualMetric.metric_name.asc(),
        ).all():
            out[str(row.symbol).upper()].append(_annual_from_model(_apply_annual_schema_compat(row, annual_columns)))
        for symbol in symbols:
            symbol_key = symbol.upper()
            out[symbol_key] = _apply_metric_overrides_to_history(db, out.get(symbol_key, []), symbols=[symbol_key])
            out[symbol_key] = _augment_history_for_valuation(
                db,
                import_id=import_id,
                symbol=symbol_key,
                history=out.get(symbol_key, []),
            )
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

    adv20 = _positive_num(context.get("adv20"))
    if adv20 is not None:
        metrics["ADV20"] = adv20
        derived.append("ADV20")

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
    total_equity = _latest_history_metric(
        history,
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
    if total_equity is None:
        total_equity = _snapshot_metric(
            metrics,
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
    free_cash_flow = _latest_history_metric(history, "Free_Cash_Flow")
    if free_cash_flow is None:
        free_cash_flow = _snapshot_metric(metrics, "Free_Cash_Flow")
    dividends = _latest_history_metric(history, "Dividendes", "Dividends_Paid", "Clean_Dividendes")
    if dividends is None:
        dividends = _snapshot_metric(metrics, "Dividendes", "Dividends_Paid", "Clean_Dividendes")
    ebit = _latest_history_metric(history, "EBIT", "Resultat_dexploitation", "Clean_Resultat_dexploitation")
    if ebit is None:
        ebit = _snapshot_metric(metrics, "EBIT", "Resultat_dexploitation", "Clean_Resultat_dexploitation")
    total_debt = _latest_history_metric(history, "Total_Debt", "Debt_Total", "Dettes_de_financement", "Clean_Dettes_de_financement")
    if total_debt is None:
        total_debt = _snapshot_metric(metrics, "Total_Debt", "Debt_Total", "Dettes_de_financement", "Clean_Dettes_de_financement")
    cash = _latest_history_metric(history, "Cash", "Cash_and_Equivalents", "Tresorerie_Actif", "Clean_Tresorerie_Actif")
    if cash is None:
        cash = _snapshot_metric(metrics, "Cash", "Cash_and_Equivalents", "Tresorerie_Actif", "Clean_Tresorerie_Actif")
    net_debt = _latest_history_metric(history, "NetDebt", "Net_Debt")
    if net_debt is None:
        net_debt = _snapshot_metric(metrics, "NetDebt", "Net_Debt")
    ebitda = _latest_history_metric(history, "EBITDA")
    if ebitda is None:
        ebitda = _snapshot_metric(metrics, "EBITDA")

    latest_history_year = _latest_non_null_history_year(history)
    revenue_by_year = _history_metric_year_map(history, "Chiffre_daffaires", "Revenue", "Clean_Chiffre_daffaires")
    net_income_by_year = _history_metric_year_map(history, "Resultat_net", "NetIncome", "Net_Income", "Clean_Resultat_net")
    equity_by_year = _history_metric_year_map(
        history,
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
    dividend_by_year = _history_metric_year_map(history, "Dividendes", "Dividends_Paid", "Clean_Dividendes")
    dps_by_year = _history_metric_year_map(history, "Dividend_Per_Share")
    derivation_year = latest_history_year or snapshot.latest_statement_year

    if dividends is None and derivation_year is not None and shares is not None:
        latest_dps = dps_by_year.get(int(derivation_year))
        if latest_dps is not None:
            dividends = latest_dps * shares
            metrics["Dividendes"] = dividends
            metrics["Clean_Dividendes"] = dividends
            derived.extend(["Dividendes", "Clean_Dividendes"])

    if derivation_year is not None:
        year = int(derivation_year)
        ni_for_roe = net_income_by_year.get(year, net_income)
        equity_for_roe = equity_by_year.get(year, total_equity)
        previous_equity_years = [candidate for candidate in equity_by_year if candidate < year]
        previous_equity = equity_by_year[max(previous_equity_years)] if previous_equity_years else None
        average_equity = (
            (previous_equity + equity_for_roe) / 2.0
            if previous_equity is not None and equity_for_roe is not None
            else equity_for_roe
        )
        roe = _safe_ratio(ni_for_roe, average_equity)
        if roe is not None:
            metrics["ROE"] = roe
            derived.append("ROE")

        revenue_growth = _year_over_year_growth(revenue_by_year, year)
        if revenue_growth is not None:
            metrics["Revenue_Growth"] = revenue_growth
            derived.append("Revenue_Growth")
        net_income_growth = _year_over_year_growth(net_income_by_year, year)
        if net_income_growth is not None:
            metrics["NetIncome_Growth"] = net_income_growth
            derived.append("NetIncome_Growth")

    if dividends is not None:
        payout = _safe_ratio(dividends, net_income if net_income is not None and net_income > 0 else None)
        if payout is not None:
            metrics["Dividend_Payout"] = payout
            derived.append("Dividend_Payout")
        coverage_ratio = _safe_ratio(net_income, dividends if dividends > 0 else None)
        if coverage_ratio is not None:
            metrics["Dividend_Coverage"] = coverage_ratio
            derived.append("Dividend_Coverage")

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

        if net_debt is None:
            if total_debt is not None and cash is not None:
                net_debt = total_debt - cash
            elif total_debt is not None:
                net_debt = total_debt
        if net_debt is not None:
            metrics["NetDebt"] = net_debt
            derived.append("NetDebt")
            enterprise_value = market_cap + net_debt
            metrics["EnterpriseValue"] = enterprise_value
            derived.append("EnterpriseValue")
            ev_to_ebitda = _safe_ratio(enterprise_value, ebitda)
            if ev_to_ebitda is not None:
                metrics["EV_to_EBITDA"] = ev_to_ebitda
                derived.append("EV_to_EBITDA")
            ev_to_ebit = _safe_ratio(enterprise_value, ebit)
            if ev_to_ebit is not None:
                metrics["EV_to_EBIT"] = ev_to_ebit
                derived.append("EV_to_EBIT")
            ev_to_sales = _safe_ratio(enterprise_value, revenue)
            if ev_to_sales is not None:
                metrics["EV_to_Sales"] = ev_to_sales
                derived.append("EV_to_Sales")
            net_debt_to_ebitda = _safe_ratio(net_debt, ebitda)
            if net_debt_to_ebitda is not None:
                metrics["NetDebt_to_EBITDA"] = net_debt_to_ebitda
                derived.append("NetDebt_to_EBITDA")
            net_debt_to_equity = _safe_ratio(net_debt, total_equity)
            if net_debt_to_equity is not None:
                metrics["NetDebt_to_Equity"] = net_debt_to_equity
                derived.append("NetDebt_to_Equity")

    price_lineage = {
        "current_price": app_price,
        "price_as_of": context.get("price_as_of"),
        "price_source": context.get("price_source"),
        "price_source_provider": context.get("price_source_provider"),
        "price_timeframe": context.get("price_timeframe"),
        "adv20": adv20,
        "shares_outstanding": shares,
        "shares_source": context.get("shares_source"),
        "shares_as_of": context.get("shares_as_of"),
        "derived_metrics": sorted(set(derived)),
    }
    coverage.update(
        {
            "has_current_price": metrics.get("Current_Price") is not None,
            "has_adv20": metrics.get("ADV20") is not None,
            "has_market_cap": metrics.get("MarketCap_Calc") is not None,
            "has_shares_outstanding": metrics.get("Shares_Outstanding") is not None,
            "adv20": adv20,
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
            _apply_metric_overrides_to_snapshot(db, _snapshot_from_model(row)),
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
            _apply_metric_overrides_to_snapshot(db, _snapshot_from_model(row)),
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


def _is_masi_source(import_row: models.FundamentalImport, stock: models.StockMaster | None) -> bool:
    return str(import_row.source_universe or "").lower() == "masi" or str(getattr(stock, "market_region", "") or "").lower() == "masi"


def _core_statement_metric_count(snapshot: models.FundamentalLatestSnapshot) -> int:
    metrics = dict(snapshot.metrics_json or {})
    count = 0
    for group in CORE_STATEMENT_METRIC_GROUPS:
        if any(metrics.get(metric_name) is not None for metric_name in group):
            count += 1
    return count


def _data_verification_rank(
    snapshot: models.FundamentalLatestSnapshot,
    verification_status: str | None = None,
) -> tuple[int, int]:
    source = dict(snapshot.source_json or {})
    status = str(verification_status or "").strip().lower()
    if not status:
        coverage = dict(snapshot.coverage_json or {})
        verification = coverage.get("data_verification") if isinstance(coverage, dict) else None
        status = str((verification or {}).get("status") or "").strip().lower() if isinstance(verification, dict) else ""
    status_rank = 2 if status == "verified" else 1 if status == "data_unverified" else 0
    proof_rank = 1 if source.get("brief42_fy2025_reingestion") else 0
    return proof_rank, status_rank


def _latest_symbol_rank(
    snapshot: models.FundamentalLatestSnapshot,
    import_row: models.FundamentalImport,
    stock: models.StockMaster | None,
    required_complete: int = 0,
    verification_status: str | None = None,
) -> tuple[int, int, int, int, int, int, dt.datetime]:
    source = str(import_row.data_source or "workbook").strip().lower()
    source_rank = 0
    core_metric_count = 0
    has_core_statement = 0
    if _is_masi_source(import_row, stock) and MASI_FUNDAMENTAL_SOURCE_PRIORITY:
        core_metric_count = _core_statement_metric_count(snapshot)
        has_core_statement = 1 if core_metric_count else 0
        try:
            source_rank = len(MASI_FUNDAMENTAL_SOURCE_PRIORITY) - MASI_FUNDAMENTAL_SOURCE_PRIORITY.index(source)
        except ValueError:
            source_rank = 0
    # An import that carries every statement total the rating gate requires must win
    # canonical over one that is missing them — otherwise a provenance flag on an
    # incomplete import keeps an unratable one canonical. required_complete is judged
    # from fundamental_annual_metric (the same source the verification gate reads), not
    # from the snapshot's metrics_json, which holds derived ratios for some imports.
    proof_rank, status_rank = _data_verification_rank(snapshot, verification_status=verification_status)
    # Tuple comparison: higher is better.
    # status_rank (verified=2 > data_unverified=1 > unknown=0) must come before proof_rank so
    # a verified import always beats a data_unverified one regardless of proof flags.
    # proof_rank then tiebreaks between imports with equal status (prefer deliberate re-ingest).
    return (
        required_complete,
        source_rank,
        status_rank,
        proof_rank,
        has_core_statement,
        core_metric_count,
        _latest_key(import_row),
    )


def _verification_statuses_for_candidates(
    db: Session,
    candidate_rows: list[tuple[models.FundamentalLatestSnapshot, models.FundamentalImport, models.StockMaster | None]],
) -> dict[tuple[uuid.UUID, str, int], str]:
    """Return live tie-out statuses keyed by candidate import/symbol/year."""

    if not candidate_rows or not _table_exists(db, models.FundamentalDataVerification):
        return {}
    keys = {
        (snapshot.import_id, str(snapshot.symbol).upper(), int(snapshot.latest_statement_year))
        for snapshot, _import_row, _stock in candidate_rows
        if snapshot.latest_statement_year is not None
    }
    if not keys:
        return {}
    import_ids = {import_id for import_id, _symbol, _year in keys}
    symbols = {symbol for _import_id, symbol, _year in keys}
    years = {year for _import_id, _symbol, year in keys}
    rows = (
        db.query(
            models.FundamentalDataVerification.import_id,
            models.FundamentalDataVerification.symbol,
            models.FundamentalDataVerification.statement_year,
            models.FundamentalDataVerification.status,
        )
        .filter(models.FundamentalDataVerification.import_id.in_(import_ids))
        .filter(func.upper(models.FundamentalDataVerification.symbol).in_(symbols))
        .filter(models.FundamentalDataVerification.statement_year.in_(years))
        .all()
    )
    out: dict[tuple[uuid.UUID, str, int], str] = {}
    for import_id, symbol, year, status in rows:
        key = (import_id, str(symbol).upper(), int(year))
        if key in keys:
            out[key] = str(status or "")
    return out


def _required_complete_imports(
    db: Session,
    candidate_rows: list[tuple[models.FundamentalLatestSnapshot, models.FundamentalImport, models.StockMaster | None]],
) -> set[tuple[uuid.UUID, str]]:
    """(import_id, symbol) pairs whose latest statement year carries every required total.

    Completeness is judged against fundamental_annual_metric — the same source the
    data-verification gate reads — so the canonical ranking agrees with what can
    actually be rated, rather than the snapshot's metrics_json (which stores derived
    ratios for some imports and would understate completeness).
    """
    year_by_key: dict[tuple[uuid.UUID, str], int] = {}
    for snapshot, import_row, _stock in candidate_rows:
        year = snapshot.latest_statement_year
        if year is None:
            continue
        year_by_key[(import_row.id, str(snapshot.symbol).upper())] = int(year)
    if not year_by_key:
        return set()

    import_ids = {import_id for import_id, _symbol in year_by_key}
    symbols = {symbol for _import_id, symbol in year_by_key}
    rows = (
        db.query(
            models.FundamentalAnnualMetric.import_id,
            models.FundamentalAnnualMetric.symbol,
            models.FundamentalAnnualMetric.statement_year,
            models.FundamentalAnnualMetric.metric_name,
        )
        .filter(models.FundamentalAnnualMetric.import_id.in_(import_ids))
        .filter(func.upper(models.FundamentalAnnualMetric.symbol).in_(symbols))
        .filter(models.FundamentalAnnualMetric.metric_value.isnot(None))
        .all()
    )
    present: dict[tuple[uuid.UUID, str, int], set[str]] = defaultdict(set)
    for import_id, symbol, year, metric_name in rows:
        present[(import_id, str(symbol).upper(), int(year))].add(metric_name)

    complete: set[tuple[uuid.UUID, str]] = set()
    for (import_id, symbol), year in year_by_key.items():
        if _metric_groups_complete(present.get((import_id, symbol, year), set())):
            complete.add((import_id, symbol))
    return complete


def _canonical_snapshot_candidate_rows(
    db: Session,
    *,
    symbols: list[str] | None = None,
    scope: FundamentalScope = "all",
) -> tuple[list[tuple[models.FundamentalLatestSnapshot, models.FundamentalImport, models.StockMaster | None]], set[str]]:
    snapshot_base_query, snapshot_columns = _snapshot_query(db)
    query = (
        snapshot_base_query.with_entities(models.FundamentalLatestSnapshot, models.FundamentalImport, models.StockMaster)
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

    return query.all(), snapshot_columns


def _resolve_canonical_snapshot_rows(
    db: Session,
    *,
    symbols: list[str] | None = None,
    scope: FundamentalScope = "all",
    prefer_persisted: bool = True,
) -> dict[str, tuple[models.FundamentalLatestSnapshot, models.FundamentalImport]]:
    rows, snapshot_columns = _canonical_snapshot_candidate_rows(db, symbols=symbols, scope=scope)
    complete_imports = _required_complete_imports(db, rows)
    verification_statuses = _verification_statuses_for_candidates(db, rows)
    ranked: dict[str, tuple[tuple[int, int, int, int, int, int, dt.datetime], models.FundamentalLatestSnapshot, models.FundamentalImport]] = {}
    flagged: dict[str, tuple[tuple[int, int, int, int, int, int, dt.datetime], models.FundamentalLatestSnapshot, models.FundamentalImport]] = {}
    has_canonical_column = "is_canonical" in snapshot_columns
    for snapshot, import_row, stock in rows:
        snapshot = _apply_snapshot_schema_compat(snapshot, import_row, snapshot_columns)
        symbol = str(snapshot.symbol).upper()
        required_complete = 1 if (import_row.id, symbol) in complete_imports else 0
        verification_key = (
            import_row.id,
            symbol,
            int(snapshot.latest_statement_year),
        ) if snapshot.latest_statement_year is not None else None
        key = _latest_symbol_rank(
            snapshot,
            import_row,
            stock,
            required_complete=required_complete,
            verification_status=verification_statuses.get(verification_key) if verification_key is not None else None,
        )
        if symbol not in ranked or key > ranked[symbol][0]:
            ranked[symbol] = (key, snapshot, import_row)
        if has_canonical_column and bool(getattr(snapshot, "is_canonical", False)):
            if symbol not in flagged or key > flagged[symbol][0]:
                flagged[symbol] = (key, snapshot, import_row)
    out: dict[str, tuple[models.FundamentalLatestSnapshot, models.FundamentalImport]] = {}
    for symbol in sorted(set(ranked) | set(flagged)):
        if prefer_persisted and symbol in flagged and (symbol not in ranked or flagged[symbol][0] >= ranked[symbol][0]):
            _key, snapshot, import_row = flagged[symbol]
        else:
            _key, snapshot, import_row = ranked[symbol]
        out[symbol] = (snapshot, import_row)
    return out


def latest_snapshot_rows_by_symbol(
    db: Session,
    *,
    symbols: list[str] | None = None,
    scope: FundamentalScope = "all",
) -> dict[str, models.FundamentalLatestSnapshot]:
    resolved = _resolve_canonical_snapshot_rows(db, symbols=symbols, scope=scope)
    return {symbol: snapshot for symbol, (snapshot, _import_row) in resolved.items()}


def latest_imports_by_symbol(
    db: Session,
    *,
    symbols: list[str] | None = None,
    scope: FundamentalScope = "all",
) -> dict[str, models.FundamentalImport]:
    resolved = _resolve_canonical_snapshot_rows(db, symbols=symbols, scope=scope)
    return {symbol: import_row for symbol, (_snapshot, import_row) in resolved.items()}


def canonical_snapshot_for_symbol(db: Session, symbol: str) -> models.FundamentalLatestSnapshot | None:
    return latest_snapshot_rows_by_symbol(db, symbols=[symbol.upper()]).get(symbol.upper())


def refresh_canonical_snapshot_flags(
    db: Session,
    *,
    symbols: list[str] | None = None,
    scope: FundamentalScope = "all",
) -> dict[str, uuid.UUID]:
    if "is_canonical" not in _existing_table_columns(db, models.FundamentalLatestSnapshot):
        return {}
    resolved = _resolve_canonical_snapshot_rows(db, symbols=symbols, scope=scope, prefer_persisted=False)
    wanted_symbols = sorted({symbol.upper() for symbol in (symbols or resolved.keys())})
    if not wanted_symbols:
        return {}
    canonical_by_symbol = {symbol: snapshot.import_id for symbol, (snapshot, _import_row) in resolved.items()}
    rows = (
        db.query(models.FundamentalLatestSnapshot)
        .filter(models.FundamentalLatestSnapshot.symbol.in_(wanted_symbols))
        .all()
    )
    for row in rows:
        symbol = str(row.symbol).upper()
        row.is_canonical = canonical_by_symbol.get(symbol) == row.import_id
        db.add(row)
    db.flush()
    return canonical_by_symbol


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


def delete_fundamental_import_artifacts(
    db: Session,
    *,
    import_id: uuid.UUID,
    include_statement_rows: bool = True,
) -> dict[str, int]:
    """Delete derived artifacts for an import while preserving audit/provenance rows."""

    deleted: dict[str, int] = {}

    def _delete(model: Any) -> None:
        if not _table_exists(db, model):
            deleted[model.__tablename__] = 0
            return
        deleted[model.__tablename__] = (
            db.query(model)
            .filter(model.import_id == import_id)
            .delete(synchronize_session=False)
        )

    for model in (
        models.FundamentalProjection,
        models.FundamentalValuationResult,
        models.FundamentalEnsembleResult,
        models.FundamentalLatestSnapshot,
        models.FundamentalIntegrityReport,
        models.FundamentalDataVerification,
        models.FundamentalPillarScoreHistory,
    ):
        _delete(model)
    if include_statement_rows:
        for model in (
            models.FundamentalCompanyMap,
            models.FundamentalAnnualMetric,
            models.FundamentalPeriodMetric,
        ):
            _delete(model)
    return deleted


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
        as_of_date=row.as_of_date,
        source_document_id=row.source_document_id,
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
        as_of_date=row.as_of_date,
        source_document_id=row.source_document_id,
    )


def _metric_override_rows(
    db: Session,
    *,
    symbols: list[str],
    statement_year: int | None = None,
) -> list[models.FundamentalMetricOverride]:
    normalized = sorted({symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()})
    if not normalized or not _table_exists(db, models.FundamentalMetricOverride):
        return []
    query = db.query(models.FundamentalMetricOverride).filter(
        models.FundamentalMetricOverride.symbol.in_(normalized),
        models.FundamentalMetricOverride.is_current.is_(True),
    )
    if statement_year is not None:
        query = query.filter(models.FundamentalMetricOverride.statement_year == int(statement_year))
    return query.order_by(
        models.FundamentalMetricOverride.symbol.asc(),
        models.FundamentalMetricOverride.statement_year.asc(),
        models.FundamentalMetricOverride.metric_name.asc(),
        models.FundamentalMetricOverride.created_at.desc(),
        models.FundamentalMetricOverride.id.desc(),
    ).all()


def current_metric_overrides(db: Session, *, symbol: str) -> list[models.FundamentalMetricOverride]:
    return _metric_override_rows(db, symbols=[symbol.upper()])


def _metric_override_map(
    db: Session,
    *,
    symbols: list[str],
    statement_year: int | None = None,
) -> dict[tuple[str, int, str], models.FundamentalMetricOverride]:
    rows = _metric_override_rows(db, symbols=symbols, statement_year=statement_year)
    return {
        (row.symbol.upper(), int(row.statement_year), str(row.metric_name)): row
        for row in rows
    }


def _apply_metric_overrides_to_history(
    db: Session,
    history: list[AnnualMetricRow],
    *,
    symbols: list[str] | None = None,
) -> list[AnnualMetricRow]:
    wanted = symbols or [row.symbol for row in history]
    overrides = _metric_override_map(db, symbols=wanted)
    if not overrides:
        return history

    company_by_symbol: dict[str, str] = {}
    for row in history:
        company_by_symbol.setdefault(row.symbol.upper(), row.company_name)

    seen: set[tuple[str, int, str]] = set()
    out: list[AnnualMetricRow] = []
    for row in history:
        key = (row.symbol.upper(), int(row.statement_year), row.metric_name)
        override = overrides.get(key)
        if override is None:
            out.append(row)
            continue
        seen.add(key)
        out.append(
            replace(
                row,
                metric_value=override.metric_value,
                raw_metric_name=row.raw_metric_name or row.metric_name,
                source_sheet="manual_override",
                source_field=override.note,
                is_proxy=False,
            )
        )

    for key, override in overrides.items():
        if key in seen:
            continue
        symbol, year, metric_name = key
        out.append(
            AnnualMetricRow(
                symbol=symbol,
                company_name=company_by_symbol.get(symbol, symbol),
                statement_year=year,
                metric_name=metric_name,
                metric_value=override.metric_value,
                raw_metric_name=metric_name,
                source_sheet="manual_override",
                source_field=override.note,
                is_proxy=False,
            )
        )
    return sorted(out, key=lambda row: (row.symbol, row.statement_year, row.metric_name, row.as_of_date or dt.date.min, row.source_document_id or 0))


def _apply_metric_overrides_to_snapshot(
    db: Session,
    snapshot: FundamentalSnapshot,
) -> FundamentalSnapshot:
    year = snapshot.latest_statement_year
    if year is None:
        return snapshot
    overrides = _metric_override_rows(db, symbols=[snapshot.symbol], statement_year=int(year))
    if not overrides:
        return snapshot
    metrics = dict(snapshot.metrics or {})
    source = dict(snapshot.source or {})
    coverage = dict(snapshot.coverage or {})
    metric_lineage = dict(source.get("metric_overrides") or {}) if isinstance(source.get("metric_overrides"), dict) else {}
    for override in overrides:
        key = str(override.metric_name)
        metric_lineage[key] = {
            "original_value": metrics.get(key),
            "override_value": override.metric_value,
            "note": override.note,
            "created_by": override.created_by,
            "created_at": override.created_at.isoformat() if override.created_at else None,
        }
        metrics[key] = override.metric_value
    source["metric_overrides"] = metric_lineage
    coverage["manual_metric_override_count"] = len(overrides)
    coverage["metric_count"] = sum(value is not None for value in metrics.values())
    return replace(snapshot, metrics=metrics, source=source, coverage=coverage)


def _apply_metric_overrides_to_annual_models(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
    rows: list[models.FundamentalAnnualMetric],
) -> list[models.FundamentalAnnualMetric]:
    overrides = _metric_override_map(db, symbols=[symbol])
    if not overrides:
        return rows
    seen: set[tuple[str, int, str]] = set()
    company_name = rows[0].company_name if rows else symbol.upper()
    out: list[models.FundamentalAnnualMetric] = []
    for row in rows:
        key = (row.symbol.upper(), int(row.statement_year), str(row.metric_name))
        override = overrides.get(key)
        if override is None:
            out.append(row)
            continue
        seen.add(key)
        display_row = models.FundamentalAnnualMetric(
            import_id=row.import_id,
            symbol=row.symbol,
            company_name=row.company_name,
            statement_year=row.statement_year,
            metric_name=row.metric_name,
            metric_value=override.metric_value,
            raw_metric_name=row.raw_metric_name or row.metric_name,
            source_sheet="manual_override",
            source_field=override.note,
            is_proxy=False,
            as_of_date=row.as_of_date,
            source_document_id=row.source_document_id,
        )
        setattr(display_row, "_manual_override_original_value", row.metric_value)
        setattr(display_row, "_manual_override_id", int(override.id))
        setattr(display_row, "_manual_override_note", override.note)
        setattr(display_row, "_manual_override_created_by", override.created_by)
        setattr(display_row, "_manual_override_created_at", override.created_at)
        out.append(display_row)
    for key, override in overrides.items():
        if key in seen:
            continue
        _symbol, year, metric_name = key
        synthetic = models.FundamentalAnnualMetric(
            import_id=import_id,
            symbol=symbol.upper(),
            company_name=company_name,
            statement_year=year,
            metric_name=metric_name,
            metric_value=override.metric_value,
            raw_metric_name=metric_name,
            source_sheet="manual_override",
            source_field=override.note,
            is_proxy=False,
        )
        setattr(synthetic, "_manual_override_original_value", None)
        setattr(synthetic, "_manual_override_id", int(override.id))
        setattr(synthetic, "_manual_override_note", override.note)
        setattr(synthetic, "_manual_override_created_by", override.created_by)
        setattr(synthetic, "_manual_override_created_at", override.created_at)
        out.append(synthetic)
    return sorted(out, key=lambda row: (row.statement_year, row.metric_name))


def _period_from_model(row: models.FundamentalPeriodMetric) -> PeriodMetricRow:
    return PeriodMetricRow(
        symbol=row.symbol,
        company_name=row.company_name,
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


def source_integrity_report_for_history(
    report: IntegrityReport | None,
    *,
    history: list[AnnualMetricRow],
    symbol: str,
    statement_year: int | None,
) -> IntegrityReport | None:
    if report is not None and report.checks:
        return report
    target_year = statement_year
    if target_year is None:
        years = [int(row.statement_year) for row in history if row.metric_value is not None]
        target_year = max(years) if years else None
    if target_year is None:
        return report
    rows_by_metric = _latest_year_metric_map(history, int(target_year))
    if not any(value is not None for value in rows_by_metric.values()):
        return report
    rebuilt = build_integrity_report(
        symbol=symbol,
        statement_year=int(target_year),
        rows_by_metric=rows_by_metric,
        assumptions=DEFAULT_ASSUMPTIONS,
    )
    if report is not None:
        rebuilt = replace(
            rebuilt,
            projected_statements=list(report.projected_statements),
            projection_checks=list(report.projection_checks),
        )
    return rebuilt


def _synthesize_balance_sheet_identity(parsed: FundamentalWorkbook) -> int:
    """Fill the liabilities-side balance-sheet total from the asset-side total.

    Published CGNC/IFRS balance sheets always satisfy Total Assets == Total Equity &
    Liabilities. The BVC scraper frequently captures only the asset-side grand total
    (Total_Actif) plus equity and drops the liabilities-side total, which leaves the
    data-verification gate (and the t1 balance check) unable to resolve. When no
    liabilities-side total is present for a statement year we synthesize
    Total_Liabilities_And_Equity = Total_Actif. This is an accounting identity, not an
    estimate; the synthesized row is flagged is_proxy for provenance. Returns the count
    of synthesized annual rows.
    """
    annual_by_key: dict[tuple[str, int], dict[str, AnnualMetricRow]] = defaultdict(dict)
    for row in parsed.annual_metrics:
        annual_by_key[(row.symbol.upper(), row.statement_year)][row.metric_name] = row

    synthesized: list[AnnualMetricRow] = []
    for metrics in annual_by_key.values():
        if any(
            metrics.get(alias) is not None and metrics[alias].metric_value is not None
            for alias in _BS_PASSIF_TOTAL_ALIASES
        ):
            continue
        assets_row = next(
            (
                metrics[alias]
                for alias in _BS_ASSETS_TOTAL_ALIASES
                if metrics.get(alias) is not None and metrics[alias].metric_value is not None
            ),
            None,
        )
        if assets_row is None:
            continue
        synthesized.append(
            replace(
                assets_row,
                metric_name=_BS_SYNTH_PASSIF_METRIC,
                raw_metric_name=None,
                source_field=f"cgnc_identity:{assets_row.metric_name}",
                is_proxy=True,
            )
        )
    parsed.annual_metrics.extend(synthesized)

    for snapshot in parsed.latest_snapshots:
        metrics = snapshot.metrics or {}
        if any(metrics.get(alias) is not None for alias in _BS_PASSIF_TOTAL_ALIASES):
            continue
        assets_val = next(
            (metrics[alias] for alias in _BS_ASSETS_TOTAL_ALIASES if metrics.get(alias) is not None),
            None,
        )
        if assets_val is None:
            continue
        snapshot.metrics[_BS_SYNTH_PASSIF_METRIC] = assets_val
    return len(synthesized)


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


PROJECTION_HAIRCUT_BY_STATUS = {
    "pass": 0.0,
    "derived": 0.05,
    "warn": 0.10,
    "fail": 0.30,
    "unavailable": 0.05,
}
STATUS_RANK = {"pass": 0, "derived": 1, "warn": 2, "fail": 3, "unavailable": -1}


def _combined_status(left: str, right: str) -> str:
    source_status = left or "unavailable"
    projection_status = right or "unavailable"
    if source_status == "unavailable" and projection_status in {"pass", "derived", "unavailable"}:
        return "unavailable"
    return max((source_status, projection_status), key=lambda status: STATUS_RANK.get(status, -1))


def _period_suffix(statement: dict[str, Any]) -> str:
    year = int(statement.get("fiscal_year") or 0)
    period_label = str(statement.get("period_label") or "FY")
    return str(year) if period_label == "FY" else f"{year}_{period_label}"


def _sector_adjusted_projection(projection: Projection, *, sector: str | None) -> Projection:
    if not _is_financial_sector(sector):
        return projection
    method = str((projection.growth_decomposition or {}).get("method") or "")
    if method in {"bank_equity_side_projection", "insurer_simplified_roe_projection", "financial_simplified_roe_projection"}:
        return projection
    checks = [
        IntegrityCheck(
            name=f"projection_financial_sector_not_applicable_{_period_suffix(statement)}",
            status="unavailable",
            delta=None,
            rel_delta=None,
            inputs={
                "total_assets": statement.get("total_assets"),
                "total_equity": statement.get("total_equity"),
            },
            message="financial_sector: industrial 3-statement balance projection is not applied to banks/insurance/leasing",
        )
        for statement in projection.statements
    ]
    warnings = list(projection.warnings)
    if "financial_sector_projection_balance_not_applicable" not in warnings:
        warnings.append("financial_sector_projection_balance_not_applicable")
    return replace(projection, warnings=warnings, integrity_checks=checks)


def _integrity_with_projection(
    *,
    report: IntegrityReport | None,
    projection: Projection,
    symbol: str,
    statement_year: int | None,
) -> IntegrityReport:
    if report is None:
        return IntegrityReport(
            symbol=symbol.upper(),
            statement_year=int(statement_year or projection.start_year),
            checks=[],
            overall_status="unavailable",
            confidence_haircut=0.0,
            projected_statements=list(projection.statements),
            projection_checks=list(projection.integrity_checks),
        )
    source_status = overall_status(report.checks) if report.checks else (report.overall_status or "unavailable")
    return replace(
        report,
        overall_status=source_status,
        confidence_haircut=max(report.confidence_haircut, PROJECTION_HAIRCUT_BY_STATUS.get(source_status, 0.0)),
        projected_statements=list(projection.statements),
        projection_checks=list(projection.integrity_checks),
    )


def _persist_projection_integrity_report(db: Session, *, import_id: uuid.UUID, report: IntegrityReport) -> None:
    row = (
        db.query(models.FundamentalIntegrityReport)
        .filter(
            models.FundamentalIntegrityReport.import_id == import_id,
            models.FundamentalIntegrityReport.symbol == report.symbol.upper(),
            models.FundamentalIntegrityReport.statement_year == report.statement_year,
        )
        .first()
    )
    payload = report_to_dict(report)
    if row is None:
        db.add(
            models.FundamentalIntegrityReport(
                import_id=import_id,
                symbol=report.symbol.upper(),
                statement_year=report.statement_year,
                overall_status=report.overall_status,
                confidence_haircut=report.confidence_haircut,
                checks_json=sanitize_json_compatible(payload["checks"]),
                projected_statements_json=sanitize_json_compatible(report.projected_statements),
                projection_checks_json=sanitize_json_compatible(payload["projection_checks"]),
            )
        )
        return
    row.overall_status = report.overall_status
    row.confidence_haircut = report.confidence_haircut
    row.projected_statements_json = sanitize_json_compatible(report.projected_statements)
    row.projection_checks_json = sanitize_json_compatible(payload["projection_checks"])
    db.add(row)


def _projection_line_evidence(projection: Projection, line_item: str) -> dict[str, Any]:
    driver_for_line = {
        "revenue_growth": "revenue_growth",
        "revenue": "revenue_growth",
        "ebit_margin": "ebit_margin",
        "ebit": "ebit_margin",
        "ebitda": "ebit_margin",
        "tax_rate": "tax_rate",
        "nopat": "tax_rate",
        "capex": "capex_pct",
        "delta_working_capital": "working_capital_pct",
        "working_capital": "working_capital_pct",
        "depreciation_amortization": "depreciation_amortization_pct",
        "fcff": "fcff",
        "fcfe": "fcff",
        "dividends": "payout_ratio",
        "total_equity": "payout_ratio",
    }.get(line_item)
    evidence: dict[str, Any] = {
        "kind": "projection_statement_line",
        "line_item": line_item,
        "fallback": projection.fallback,
        "warnings": projection.warnings,
    }
    if driver_for_line and driver_for_line in projection.drivers:
        evidence["driver"] = projection.drivers[driver_for_line].to_dict()
    return evidence


HORIZON_MONTHS = {"quarter": 3, "semester": 6, "year": 12}
HORIZON_PERIOD_BUILD = {"quarter": ("quarterly", 4), "semester": ("semiannual", 2), "year": ("annual", 1)}


def _snapshot_positive_metric(snapshot: FundamentalSnapshot, *keys: str) -> float | None:
    for key in keys:
        value = _positive_num(snapshot.metrics.get(key))
        if value is not None:
            return value
    return None


def _confidence_label_from_score(score: float | None) -> str:
    value = _num(score)
    if value is None or value <= 0:
        return "unavailable"
    if value >= 0.70:
        return "high"
    if value >= 0.40:
        return "medium"
    return "low"


def _target_pe_multiple(snapshot: FundamentalSnapshot, valuations: list[Any]) -> tuple[float | None, str | None]:
    for row in valuations:
        if getattr(row, "model", None) != "justified_multiples":
            continue
        multiples = dict((getattr(row, "outputs", None) or {}).get("justified_multiples") or {})
        value = _positive_num(multiples.get("implied_pe"))
        if value is not None:
            return value, "justified_pe"
    for row in valuations:
        if getattr(row, "model", None) != "relative_multiples":
            continue
        peer_stats = dict((getattr(row, "inputs", None) or {}).get("peer_stats") or {})
        per_stats = dict(peer_stats.get("PER") or {})
        value = _positive_num(per_stats.get("median"))
        if value is not None:
            return value, "relative_peer_pe"
    value = _positive_num(snapshot.metrics.get("PER"))
    return (value, "spot_pe") if value is not None else (None, None)


def _target_ev_ebitda_multiple(snapshot: FundamentalSnapshot, valuations: list[Any]) -> tuple[float | None, str | None]:
    for row in valuations:
        if getattr(row, "model", None) != "relative_multiples":
            continue
        peer_stats = dict((getattr(row, "inputs", None) or {}).get("peer_stats") or {})
        ev_stats = dict(peer_stats.get("EV_to_EBITDA") or {})
        value = _positive_num(ev_stats.get("median"))
        if value is not None:
            return value, "relative_peer_ev_to_ebitda"
    value = _positive_num(snapshot.metrics.get("EV_to_EBITDA"))
    return (value, "spot_ev_to_ebitda") if value is not None else (None, None)


def _net_debt_from_statement_or_snapshot(statement: dict[str, Any], snapshot: FundamentalSnapshot) -> float:
    debt = _num(statement.get("debt")) or _num(snapshot.metrics.get("Total_Debt")) or _num(snapshot.metrics.get("Debt_Total")) or 0.0
    cash = _num(statement.get("cash")) or _num(snapshot.metrics.get("Cash")) or _num(snapshot.metrics.get("Cash_and_Equivalents")) or 0.0
    return float(debt) - float(cash)


def _horizon_prediction_payload(
    *,
    horizon: str,
    projection: Projection,
    snapshot: FundamentalSnapshot,
    valuations: list[Any],
    ensemble: Any,
    data_cutoff: dt.date | None,
    current_price: Any,
) -> dict[str, Any] | None:
    if not projection.statements:
        return None
    statement = projection.statements[0]
    shares = _snapshot_positive_metric(snapshot, "Shares_Outstanding")
    warnings = list(projection.warnings)
    target: float | None = None
    method: str | None = None
    confidence = _confidence_label_from_score(getattr(ensemble, "confidence_score", None))
    if horizon == "year":
        target = _num(getattr(ensemble, "fair_value_base", None))
        if target is not None:
            method = "annual_ensemble"
    if target is None and shares:
        pe, pe_method = _target_pe_multiple(snapshot, valuations)
        net_income = _num(statement.get("net_income"))
        if pe is not None and net_income is not None and net_income > 0:
            target = (net_income / shares) * pe
            method = pe_method
        else:
            ev_multiple, ev_method = _target_ev_ebitda_multiple(snapshot, valuations)
            ebitda = _num(statement.get("ebitda"))
            if ev_multiple is not None and ebitda is not None and ebitda > 0:
                net_debt = _net_debt_from_statement_or_snapshot(statement, snapshot)
                target = max(0.0, ev_multiple * ebitda - net_debt) / shares
                method = ev_method
    if target is None:
        warnings.append("horizon_target_unavailable_missing_forward_multiple")
        confidence = "unavailable"
    current = _positive_num(current_price) or _positive_num(getattr(ensemble, "current_price", None))
    target_date = _add_months(data_cutoff, HORIZON_MONTHS[horizon]) if data_cutoff is not None else _date_or_none(statement.get("period_end_date"))
    return {
        "horizon": horizon,
        "period_type": projection.period_type,
        "periods_per_year": projection.periods_per_year,
        "forward_target": target,
        "upside": target / current - 1.0 if target is not None and current is not None else None,
        "target_date": target_date.isoformat() if target_date else None,
        "method": method or "unavailable",
        "confidence": confidence,
        "warnings": warnings,
        "available": target is not None,
    }


def _build_horizon_predictions(
    *,
    snapshot: FundamentalSnapshot,
    projections_by_horizon: dict[str, Projection],
    valuations: list[Any],
    ensemble: Any,
    data_cutoff: dt.date | None,
    current_price: Any,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for horizon in ("quarter", "semester", "year"):
        projection = projections_by_horizon.get(horizon)
        if projection is None:
            continue
        payload = _horizon_prediction_payload(
            horizon=horizon,
            projection=projection,
            snapshot=snapshot,
            valuations=valuations,
            ensemble=ensemble,
            data_cutoff=data_cutoff,
            current_price=current_price,
        )
        if payload is not None:
            out.append(payload)
    return out


def _persist_projection(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
    scenario: str,
    projection: Projection,
) -> None:
    if not _table_exists(db, models.FundamentalProjection):
        return
    symbol = symbol.upper()
    projection_columns = _existing_table_columns(db, models.FundamentalProjection)
    delete_query = db.query(models.FundamentalProjection).filter(
        models.FundamentalProjection.import_id == import_id,
        models.FundamentalProjection.symbol == symbol,
        models.FundamentalProjection.scenario == scenario,
    )
    if "period_type" in projection_columns:
        delete_query = delete_query.filter(models.FundamentalProjection.period_type == projection.period_type)
    delete_query.delete(synchronize_session=False)
    for pending in list(db.new):
        if not isinstance(pending, models.FundamentalProjection):
            continue
        if (
            pending.import_id == import_id
            and str(pending.symbol).upper() == symbol
            and str(pending.scenario) == scenario
            and str(getattr(pending, "period_type", projection.period_type)) == projection.period_type
        ):
            db.expunge(pending)
    rows: list[models.FundamentalProjection] = []
    for statement in projection.statements:
        fiscal_year = int(statement["fiscal_year"])
        period_index = int(statement.get("period_index") or 0)
        period_label = str(statement.get("period_label") or "FY")
        period_end_date = _date_or_none(statement.get("period_end_date"))
        for line_item, value in statement.items():
            if line_item in {"fiscal_year", "periods_per_year", "period_type", "period_index", "period_label", "period_end_date"}:
                continue
            numeric = _num(value)
            rows.append(
                models.FundamentalProjection(
                    import_id=import_id,
                    symbol=symbol,
                    scenario=scenario,
                    fiscal_year=fiscal_year,
                    periods_per_year=projection.periods_per_year,
                    period_type=projection.period_type,
                    period_index=period_index,
                    period_label=period_label,
                    period_end_date=period_end_date,
                    line_item=str(line_item),
                    projected_value=numeric,
                    evidence_json=sanitize_json_compatible(_projection_line_evidence(projection, str(line_item))),
                    as_of=projection.as_of,
                    is_override=False,
                )
            )
    for driver in projection.drivers.values():
        evidence = sanitize_json_compatible({"kind": "driver_estimate", **driver.to_dict()})
        if driver.projected_by_period:
            driver_periods = [
                (
                    int(item.get("fiscal_year") or item.get("year")),
                    int(item.get("period_index") or 0),
                    str(item.get("period_label") or "FY"),
                    _num(item.get("value")),
                )
                for item in driver.projected_by_period
            ]
        else:
            driver_periods = [(int(year), 0, "FY", _num(value)) for year, value in driver.projected_by_year.items()]
        for year, period_index, period_label, value in driver_periods:
            rows.append(
                models.FundamentalProjection(
                    import_id=import_id,
                    symbol=symbol,
                    scenario=scenario,
                    fiscal_year=int(year),
                    periods_per_year=projection.periods_per_year,
                    period_type=projection.period_type,
                    period_index=period_index,
                    period_label=period_label,
                    period_end_date=_date_or_none(next((s.get("period_end_date") for s in projection.statements if int(s.get("fiscal_year") or 0) == int(year) and int(s.get("period_index") or 0) == period_index), None)),
                    line_item=f"driver:{driver.name}",
                    projected_value=value,
                    evidence_json=evidence,
                    as_of=projection.as_of,
                    is_override=False,
                )
            )
    if rows:
        unique_rows: dict[tuple[Any, ...], models.FundamentalProjection] = {}
        for row in rows:
            unique_rows[
                (
                    row.import_id,
                    row.symbol,
                    row.scenario,
                    row.fiscal_year,
                    row.period_type,
                    row.period_index,
                    row.line_item,
                )
            ] = row
        db.add_all(list(unique_rows.values()))


def _signal_backtest_symbols(db: Session, *, universe: str, symbols: list[str] | None = None) -> list[str]:
    if symbols:
        return sorted({symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()})
    query = (
        db.query(models.StockMaster.symbol, models.MarketDataStore.adv_20d)
        .join(models.MarketDataStore, models.MarketDataStore.symbol == models.StockMaster.symbol)
        .filter(models.StockMaster.market_region == "masi")
        .filter(models.MarketDataStore.timeframe == "1D")
        .filter(models.MarketDataStore.object_key.isnot(None))
    )
    if universe == "masi20":
        query = query.order_by(models.MarketDataStore.adv_20d.desc().nullslast(), models.StockMaster.symbol.asc()).limit(20)
    else:
        query = query.order_by(models.StockMaster.symbol.asc())
    return [str(symbol).upper() for symbol, _adv in query.all()]


def _pit_signal_snapshots(
    db: Session,
    *,
    symbols: list[str],
    scenario: str,
) -> dict[str, list[PITSignalSnapshot]]:
    if not symbols:
        return {}
    snapshot_base_query, snapshot_columns = _snapshot_query(db)
    query = (
        snapshot_base_query.with_entities(
            models.FundamentalLatestSnapshot,
            models.FundamentalImport,
            models.FundamentalEnsembleResult,
        )
        .join(models.FundamentalImport, models.FundamentalLatestSnapshot.import_id == models.FundamentalImport.id)
        .outerjoin(
            models.FundamentalEnsembleResult,
            (models.FundamentalEnsembleResult.import_id == models.FundamentalLatestSnapshot.import_id)
            & (models.FundamentalEnsembleResult.symbol == models.FundamentalLatestSnapshot.symbol)
            & (models.FundamentalEnsembleResult.scenario == scenario),
        )
        .filter(models.FundamentalImport.status.in_(SUCCEEDED_IMPORT_STATUSES))
        .filter(models.FundamentalLatestSnapshot.symbol.in_(symbols))
    )
    if "as_of_date" in snapshot_columns:
        query = query.order_by(
            models.FundamentalLatestSnapshot.symbol.asc(),
            models.FundamentalLatestSnapshot.as_of_date.asc().nullslast(),
            models.FundamentalImport.completed_at.asc().nullslast(),
            models.FundamentalImport.imported_at.asc().nullslast(),
            models.FundamentalImport.created_at.asc(),
        )
    else:
        query = query.order_by(
            models.FundamentalLatestSnapshot.symbol.asc(),
            models.FundamentalImport.completed_at.asc().nullslast(),
            models.FundamentalImport.imported_at.asc().nullslast(),
            models.FundamentalImport.created_at.asc(),
        )
    rows = query.all()
    out: dict[str, list[PITSignalSnapshot]] = defaultdict(list)
    for snapshot, import_row, ensemble in rows:
        snapshot = _apply_snapshot_schema_compat(snapshot, import_row, snapshot_columns)
        as_of_date = snapshot.as_of_date
        if as_of_date is None:
            for candidate in (import_row.completed_at, import_row.imported_at, import_row.created_at):
                if candidate is not None:
                    as_of_date = candidate.date()
                    break
        if as_of_date is None:
            continue
        scores = dict(snapshot.scores_json or {})
        pillar = _num(scores.get("overall")) or _num(scores.get("overall_score"))
        if pillar is not None and pillar > 1.5:
            pillar /= 100.0
        out[str(snapshot.symbol).upper()].append(
            PITSignalSnapshot(
                symbol=str(snapshot.symbol).upper(),
                as_of_date=as_of_date,
                upside_pct=_num(ensemble.upside_pct) if ensemble is not None else None,
                pillar_score=pillar,
                source_id=str(snapshot.import_id),
            )
        )
    return out


def _price_history_for_signal_backtest(
    db: Session,
    *,
    symbols: list[str],
    price_loader: Callable[[str], Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    rows = (
        db.query(models.MarketDataStore)
        .filter(models.MarketDataStore.symbol.in_(symbols))
        .filter(models.MarketDataStore.timeframe == "1D")
        .all()
    )
    by_symbol = {str(row.symbol).upper(): row for row in rows}
    prices: dict[str, Any] = {}
    warnings: list[str] = []
    for symbol in symbols:
        row = by_symbol.get(symbol)
        if row is None or not row.object_key:
            warnings.append(f"missing_price_history:{symbol}")
            continue
        try:
            prices[symbol] = price_loader(str(row.object_key)) if price_loader else load_close_series_from_store(object_key=str(row.object_key))
        except Exception as exc:  # pragma: no cover - live storage errors vary
            warnings.append(f"price_load_failed:{symbol}:{exc}")
    return prices, warnings


def run_and_persist_fundamental_signal_backtest(
    db: Session,
    *,
    signal: str = "upside_pct",
    universe: str = "masi20",
    start: dt.date | None = None,
    end: dt.date | None = None,
    transaction_cost_bps: float = 25.0,
    long_short: bool = False,
    symbols: list[str] | None = None,
    scenario: str = "base",
    price_loader: Callable[[str], Any] | None = None,
) -> models.FundamentalSignalBacktest:
    run_id = uuid.uuid4()
    signal = "pillar_score" if signal == "pillar_score" else "upside_pct"
    universe = universe if universe in {"masi20", "full_masi", "custom"} else "masi20"
    selected_symbols: list[str] = []
    row_values: dict[str, Any] = {
        "status": "failed",
        "params_json": {},
        "quintile_returns_json": [],
        "ic_json": {},
        "equity_curve_json": [],
        "turnover_json": [],
        "holdings_json": [],
        "warnings_json": [],
    }
    try:
        selected_symbols = _signal_backtest_symbols(db, universe=universe, symbols=symbols)
        pit_warnings = []
        snapshot_columns = _existing_table_columns(db, models.FundamentalLatestSnapshot)
        if "as_of_date" not in snapshot_columns:
            pit_warnings.append("legacy_snapshot_as_of_fallback:run alembic PIT migration for strict point-in-time results")
        else:
            null_as_of_count = (
                db.query(models.FundamentalLatestSnapshot)
                .filter(models.FundamentalLatestSnapshot.symbol.in_(selected_symbols))
                .filter(models.FundamentalLatestSnapshot.as_of_date.is_(None))
                .count()
            )
            if null_as_of_count:
                pit_warnings.append("snapshot_as_of_import_timestamp_fallback")
        prices, price_warnings = _price_history_for_signal_backtest(db, symbols=selected_symbols, price_loader=price_loader)
        snapshots = _pit_signal_snapshots(db, symbols=selected_symbols, scenario=scenario)
        result = run_signal_backtest(
            price_history=prices,
            snapshots_by_symbol=snapshots,
            config=SignalBacktestConfig(
                signal=signal,  # type: ignore[arg-type]
                universe=universe,
                start=start,
                end=end,
                transaction_cost_bps=transaction_cost_bps,
                long_short=long_short,
            ),
            run_id=str(run_id),
        )
    except Exception as exc:
        db.rollback()
        row_values.update(
            {
                "status": "failed",
                "params_json": sanitize_json_compatible({"symbols": selected_symbols, "scenario": scenario}),
                "warnings_json": sanitize_json_compatible([str(exc)]),
                "error_message": str(exc),
            }
        )
    else:
        if not db.is_active:
            db.rollback()
        row_values.update(
            {
                "status": "succeeded",
                "as_of": result.as_of,
                "quintile_returns_json": sanitize_json_compatible(result.quintile_returns),
                "ic_json": sanitize_json_compatible(result.ic),
                "equity_curve_json": sanitize_json_compatible(result.equity_curve),
                "turnover_json": sanitize_json_compatible(result.turnover),
                "holdings_json": sanitize_json_compatible(result.holdings),
                "params_json": sanitize_json_compatible({**result.params, "symbols": selected_symbols, "scenario": scenario}),
                "warnings_json": sanitize_json_compatible([*pit_warnings, *price_warnings, *result.warnings]),
            }
        )
    row = models.FundamentalSignalBacktest(
        run_id=run_id,
        signal=signal,
        universe=universe,
        rebalance="M",
        **row_values,
    )
    db.add(row)
    db.flush()
    return row


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
    query, snapshot_columns = _snapshot_query(db)
    rows = (
        query
        .filter(models.FundamentalLatestSnapshot.import_id == import_id)
        .order_by(models.FundamentalLatestSnapshot.symbol.asc())
        .all()
    )
    import_row = db.get(models.FundamentalImport, import_id)
    return [
        _apply_metric_overrides_to_snapshot(
            db,
            _snapshot_from_model(_apply_snapshot_schema_compat(row, import_row, snapshot_columns)),
        )
        for row in rows
    ]


def _load_history(db: Session, import_id: uuid.UUID, symbol: str | None = None) -> list[AnnualMetricRow]:
    query, annual_columns = _annual_metric_query(db)
    query = query.filter(models.FundamentalAnnualMetric.import_id == import_id)
    if symbol:
        query = query.filter(models.FundamentalAnnualMetric.symbol == symbol.upper())
    rows = query.order_by(
        models.FundamentalAnnualMetric.symbol.asc(),
        models.FundamentalAnnualMetric.statement_year.asc(),
        models.FundamentalAnnualMetric.metric_name.asc(),
    ).all()
    history = [_annual_from_model(_apply_annual_schema_compat(row, annual_columns)) for row in rows]
    history = _apply_metric_overrides_to_history(db, history, symbols=[symbol.upper()] if symbol else None)
    if symbol:
        return _augment_history_for_valuation(db, import_id=import_id, symbol=symbol.upper(), history=history)
    grouped: dict[str, list[AnnualMetricRow]] = defaultdict(list)
    for row in history:
        grouped[row.symbol.upper()].append(row)
    out: list[AnnualMetricRow] = []
    for symbol_key, symbol_rows in grouped.items():
        out.extend(_augment_history_for_valuation(db, import_id=import_id, symbol=symbol_key, history=symbol_rows))
    return sorted(out, key=lambda row: (row.symbol, row.statement_year, row.metric_name, row.as_of_date or dt.date.min, row.source_document_id or 0))


def _period_metric_best_rows(
    db: Session, import_id: uuid.UUID, symbol: str
) -> list[models.FundamentalPeriodMetric]:
    """Cross-import period rows for one symbol, deduped to the best row per
    (fiscal_year, period_type, normalized period_label, metric_name).

    Sub-annual (quarterly/semiannual) rows are frequently ingested by targeted BVC
    scrapes under their own import_id, separate from the canonical workbook import
    used for annual snapshots, so this loads across all imports rather than scoping
    to `import_id`. Preference order: requested import > non-proxy > newest import
    (by fundamental_import.created_at) > highest row id.
    """
    rows = (
        db.query(models.FundamentalPeriodMetric, models.FundamentalImport.created_at)
        .join(models.FundamentalImport, models.FundamentalPeriodMetric.import_id == models.FundamentalImport.id)
        .filter(models.FundamentalPeriodMetric.symbol == symbol.upper())
        .all()
    )
    period_best: dict[tuple[str, int, str, str, str], tuple[tuple[int, int, dt.datetime, int], models.FundamentalPeriodMetric]] = {}
    for row, import_created_at in rows:
        normalized_label = normalize_period_label(row.period_type, row.period_label)
        key = (row.symbol.upper(), row.fiscal_year, row.period_type, normalized_label, row.metric_name)
        rank = (
            1 if row.import_id == import_id else 0,
            0 if row.is_proxy else 1,
            import_created_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            int(row.id or 0),
        )
        if key not in period_best or rank > period_best[key][0]:
            period_best[key] = (rank, row)
    return [row for _rank, row in period_best.values()]


def _load_period_history(db: Session, import_id: uuid.UUID, symbol: str | None = None) -> list[PeriodMetricRow]:
    if symbol is None:
        # Bulk/import-time path: keep scoped to the given import so we don't load the
        # whole table when processing an import rather than a single symbol's context.
        rows = (
            db.query(models.FundamentalPeriodMetric)
            .filter(models.FundamentalPeriodMetric.import_id == import_id)
            .order_by(
                models.FundamentalPeriodMetric.symbol.asc(),
                models.FundamentalPeriodMetric.period_type.asc(),
                models.FundamentalPeriodMetric.fiscal_year.asc(),
                models.FundamentalPeriodMetric.period_label.asc(),
                models.FundamentalPeriodMetric.metric_name.asc(),
            )
            .all()
        )
        return [_period_from_model(row) for row in rows]

    out = [_period_from_model(row) for row in _period_metric_best_rows(db, import_id, symbol)]
    return sorted(
        out,
        key=lambda item: (item.symbol, item.period_type, item.fiscal_year, item.period_label, item.metric_name),
    )


def period_metric_rows_for_symbol(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
    require_value: bool = True,
) -> list[models.FundamentalPeriodMetric]:
    """Cross-import period metric rows for user-facing readers (coverage, statement
    history) that need the raw ORM rows rather than `PeriodMetricRow` dataclasses."""
    rows = _period_metric_best_rows(db, import_id, symbol)
    if require_value:
        rows = [row for row in rows if row.metric_value is not None]
    return sorted(
        rows,
        key=lambda row: (
            row.period_type,
            row.fiscal_year,
            normalize_period_label(row.period_type, row.period_label),
            row.metric_name,
        ),
    )


def annual_metric_rows_for_symbol(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
    require_value: bool = True,
) -> list[models.FundamentalAnnualMetric]:
    query, annual_columns = _annual_metric_query(db)
    query = query.filter(
        models.FundamentalAnnualMetric.import_id == import_id,
        models.FundamentalAnnualMetric.symbol == symbol.upper(),
    )
    if require_value:
        query = query.filter(models.FundamentalAnnualMetric.metric_value.isnot(None))
    rows = query.order_by(
        models.FundamentalAnnualMetric.statement_year.asc(),
        models.FundamentalAnnualMetric.metric_name.asc(),
    ).all()
    annual_rows = [_apply_annual_schema_compat(row, annual_columns) for row in rows]
    return _apply_metric_overrides_to_annual_models(
        db,
        import_id=import_id,
        symbol=symbol.upper(),
        rows=annual_rows,
    )


DOCUMENT_KIND_RANK = {"RFA": 3, "CP": 2, "NOTICE": 1}
BVC_DIVIDEND_METRIC_NAMES = {
    "Clean_Dividendes",
    "Dividend_Coverage",
    "Dividend_Payout",
    "Dividend_Per_Share",
    "Dividend_Yield",
    "Dividendes",
    "Dividendes_distribues",
    "Dividends_Paid",
}
DIVIDEND_FALLBACK_METRIC_NAMES = {
    "Clean_Dividendes",
    "Dividend_Coverage",
    "Dividend_Payout",
    "Dividend_Per_Share",
    "Dividendes",
    "Dividends_Paid",
}
DIVIDEND_FALLBACK_SOURCES = {
    "casabourse_manual_correction",
    "stockanalysis",
    "stockanalysis_supplement",
}
SUPPLEMENTAL_BALANCE_SHEET_SOURCES = {
    "stockanalysis",
    "stockanalysis_supplement",
}


def _document_kind_rank(value: str | None) -> int:
    return DOCUMENT_KIND_RANK.get(str(value or "").strip().upper(), 0)


def _annual_row_rank(row: AnnualMetricRow) -> tuple[int, int, int, int]:
    return (
        1 if row.metric_value is not None else 0,
        0 if row.is_proxy else 1,
        (row.as_of_date or dt.date.min).toordinal(),
        int(row.source_document_id or 0),
    )


def _period_lineage_to_annual_rows(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbols: set[str] | None = None,
) -> list[AnnualMetricRow]:
    query = (
        db.query(models.FundamentalPeriodMetric, models.FundamentalSourceDocument)
        .join(
            models.FundamentalSourceDocument,
            models.FundamentalPeriodMetric.source_document_id == models.FundamentalSourceDocument.id,
        )
        .filter(
            models.FundamentalPeriodMetric.import_id == import_id,
            models.FundamentalPeriodMetric.period_type == "annual",
            models.FundamentalPeriodMetric.metric_value.isnot(None),
        )
    )
    if symbols:
        query = query.filter(models.FundamentalPeriodMetric.symbol.in_(sorted(symbols)))
    best: dict[tuple[str, int, str], tuple[tuple[int, int, dt.date, int], models.FundamentalPeriodMetric, models.FundamentalSourceDocument]] = {}
    for metric, document in query.all():
        key = (str(metric.symbol).upper(), int(metric.fiscal_year), str(metric.metric_name))
        rank = (
            _document_kind_rank(document.document_kind),
            int(document.extracted_field_count or 0),
            document.publication_date or dt.date.min,
            int(document.id or 0),
        )
        if key not in best or rank > best[key][0]:
            best[key] = (rank, metric, document)

    rows: list[AnnualMetricRow] = []
    for _rank, metric, document in best.values():
        if str(metric.metric_name) in BVC_DIVIDEND_METRIC_NAMES:
            continue
        rows.append(
            AnnualMetricRow(
                symbol=str(metric.symbol).upper(),
                company_name=metric.company_name,
                statement_year=int(metric.fiscal_year),
                metric_name=metric.metric_name,
                metric_value=metric.metric_value,
                raw_metric_name=metric.raw_metric_name or metric.metric_name,
                source_sheet="bvc_jsonl",
                source_field=metric.raw_metric_name or metric.metric_name,
                is_proxy=bool(metric.is_proxy),
                as_of_date=document.publication_date,
                source_document_id=int(document.id) if document.id is not None else None,
            )
        )
    return rows


def _has_positive_dividend(history: list[AnnualMetricRow]) -> bool:
    return any(
        row.metric_name in DIVIDEND_FALLBACK_METRIC_NAMES
        and row.metric_value is not None
        and row.metric_value > 0
        for row in history
    )


def _append_prior_dividend_history(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
    history: list[AnnualMetricRow],
) -> list[AnnualMetricRow]:
    if _has_positive_dividend(history):
        return history
    latest_year = max((int(row.statement_year) for row in history), default=None)
    if latest_year is None:
        return history

    query, annual_columns = _annual_metric_query(db)
    rows = (
        query.join(models.FundamentalImport, models.FundamentalAnnualMetric.import_id == models.FundamentalImport.id)
        .filter(
            models.FundamentalAnnualMetric.import_id != import_id,
            models.FundamentalAnnualMetric.symbol == symbol.upper(),
            models.FundamentalAnnualMetric.statement_year <= latest_year,
            models.FundamentalAnnualMetric.metric_name.in_(sorted(DIVIDEND_FALLBACK_METRIC_NAMES)),
            models.FundamentalAnnualMetric.metric_value.isnot(None),
            models.FundamentalAnnualMetric.metric_value > 0,
            models.FundamentalAnnualMetric.source_sheet.in_(sorted(DIVIDEND_FALLBACK_SOURCES)),
            models.FundamentalImport.status.in_(SUCCEEDED_IMPORT_STATUSES),
        )
        .all()
    )
    selected: dict[tuple[int, str], models.FundamentalAnnualMetric] = {}
    for row in rows:
        row = _apply_annual_schema_compat(row, annual_columns)
        key = (int(row.statement_year), row.metric_name)
        current = selected.get(key)
        rank = (
            row.as_of_date or dt.date.min,
            row.created_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            row.id or 0,
        )
        current_rank = (
            current.as_of_date or dt.date.min,
            current.created_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            current.id or 0,
        ) if current is not None else None
        if current is None or rank > current_rank:
            selected[key] = row

    if not selected:
        return history

    years = sorted({year for year, _metric in selected}, reverse=True)
    preferred_year = years[0]
    appended = [
        replace(
            _annual_from_model(selected[(year, metric)]),
            raw_metric_name=f"fallback_prior_import:{selected[(year, metric)].raw_metric_name or metric}",
            source_sheet=f"{selected[(year, metric)].source_sheet}:prior_import_fallback",
            is_proxy=True,
        )
        for year, metric in sorted(selected)
        if year == preferred_year
    ]
    return [*history, *appended]


def _append_balance_sheet_history_repairs(history: list[AnnualMetricRow]) -> list[AnnualMetricRow]:
    grouped: dict[tuple[str, int], list[AnnualMetricRow]] = defaultdict(list)
    for row in history:
        grouped[(row.symbol.upper(), int(row.statement_year))].append(row)

    repairs: list[AnnualMetricRow] = []
    for (_symbol, _year), rows in grouped.items():
        by_metric: dict[str, AnnualMetricRow] = {}
        for row in rows:
            if row.metric_value is None:
                continue
            by_metric.setdefault(row.metric_name, row)
        assets = by_metric.get("Total_Assets") or by_metric.get("Total_Actif")
        equity = (
            by_metric.get("Total_Equity")
            or by_metric.get("Shareholders_Equity")
            or by_metric.get("Total_Shareholders_Equity")
            or by_metric.get("Stockholders_Equity")
            or by_metric.get("Total_Stockholders_Equity")
            or by_metric.get("Clean_Capitaux_propres")
            or by_metric.get("Capitaux_propres")
            or by_metric.get("Equity")
            or by_metric.get("Total_Common_Equity")
            or by_metric.get("Common_Equity")
        )
        liabilities = by_metric.get("Total_Liabilities")
        if assets is None or equity is None or assets.metric_value is None or equity.metric_value is None:
            continue
        assets_value = float(assets.metric_value)
        equity_value = float(equity.metric_value)
        if assets_value <= 0 or equity_value < 0:
            continue
        repaired_value = assets_value - equity_value
        if repaired_value < 0:
            continue
        if liabilities is not None and liabilities.metric_value is not None:
            source_sheet = str(liabilities.source_sheet or "")
            imbalance = abs((assets_value - float(liabilities.metric_value) - equity_value) / max(abs(assets_value), 1.0))
            if source_sheet not in SUPPLEMENTAL_BALANCE_SHEET_SOURCES or imbalance <= 0.02:
                continue
        template = assets
        repairs.append(
            replace(
                template,
                metric_name="Total_Liabilities",
                metric_value=repaired_value,
                raw_metric_name="derived:assets_minus_equity",
                source_sheet="derived_history_repair",
                source_field="derived:assets_minus_equity",
                is_proxy=False,
            )
        )
    return [*history, *repairs] if repairs else history


def _augment_history_for_valuation(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
    history: list[AnnualMetricRow],
) -> list[AnnualMetricRow]:
    augmented = _append_balance_sheet_history_repairs(history)
    return _append_prior_dividend_history(db, import_id=import_id, symbol=symbol, history=augmented)


def _upsert_annual_metric_rows(
    db: Session,
    *,
    import_id: uuid.UUID,
    rows: list[AnnualMetricRow],
) -> tuple[int, int]:
    if not rows:
        return 0, 0
    row_by_key: dict[tuple[str, int, str], AnnualMetricRow] = {}
    for row in rows:
        if row.metric_value is None:
            continue  # never write null rows — they pollute the resolver
        key = (row.symbol.upper(), row.statement_year, row.metric_name)
        current = row_by_key.get(key)
        if current is None or _annual_row_rank(row) > _annual_row_rank(current):
            row_by_key[key] = row

    symbols = sorted({key[0] for key in row_by_key})
    years = sorted({key[1] for key in row_by_key})
    existing = {
        (row.symbol.upper(), int(row.statement_year), row.metric_name): row
        for row in db.query(models.FundamentalAnnualMetric)
        .filter(
            models.FundamentalAnnualMetric.import_id == import_id,
            models.FundamentalAnnualMetric.symbol.in_(symbols),
            models.FundamentalAnnualMetric.statement_year.in_(years),
        )
        .all()
    }
    inserted = 0
    updated = 0
    for key, row in row_by_key.items():
        current = existing.get(key)
        if current is None:
            db.add(
                models.FundamentalAnnualMetric(
                    import_id=import_id,
                    symbol=row.symbol.upper(),
                    company_name=row.company_name,
                    statement_year=row.statement_year,
                    metric_name=row.metric_name,
                    metric_value=row.metric_value,
                    raw_metric_name=row.raw_metric_name,
                    source_sheet=row.source_sheet,
                    source_field=row.source_field,
                    is_proxy=row.is_proxy,
                    as_of_date=row.as_of_date,
                    source_document_id=row.source_document_id,
                )
            )
            inserted += 1
            continue

        changed = False
        if current.metric_value is None and row.metric_value is not None:
            current.metric_value = row.metric_value
            current.raw_metric_name = row.raw_metric_name
            current.source_sheet = row.source_sheet
            current.source_field = row.source_field
            current.is_proxy = row.is_proxy
            changed = True
        if current.as_of_date is None and row.as_of_date is not None:
            current.as_of_date = row.as_of_date
            changed = True
        if current.source_document_id is None and row.source_document_id is not None:
            current.source_document_id = row.source_document_id
            changed = True
        if changed:
            db.add(current)
            updated += 1
    db.flush()
    return inserted, updated


def _sync_latest_snapshots_from_annual(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbols: set[str],
) -> int:
    if not symbols:
        return 0
    snapshots = (
        db.query(models.FundamentalLatestSnapshot)
        .filter(
            models.FundamentalLatestSnapshot.import_id == import_id,
            models.FundamentalLatestSnapshot.symbol.in_(sorted(symbols)),
        )
        .all()
    )
    if not snapshots:
        return 0
    history_by_symbol: dict[str, list[models.FundamentalAnnualMetric]] = defaultdict(list)
    for row in (
        db.query(models.FundamentalAnnualMetric)
        .filter(
            models.FundamentalAnnualMetric.import_id == import_id,
            models.FundamentalAnnualMetric.symbol.in_(sorted(symbols)),
            models.FundamentalAnnualMetric.metric_value.isnot(None),
        )
        .order_by(
            models.FundamentalAnnualMetric.symbol.asc(),
            models.FundamentalAnnualMetric.statement_year.asc(),
            models.FundamentalAnnualMetric.metric_name.asc(),
        )
        .all()
    ):
        history_by_symbol[str(row.symbol).upper()].append(row)

    updated = 0
    for snapshot in snapshots:
        symbol = str(snapshot.symbol).upper()
        history = history_by_symbol.get(symbol, [])
        if not history:
            continue
        previous_latest_year = snapshot.latest_statement_year
        latest_year = previous_latest_year
        max_year = max(row.statement_year for row in history)
        if (
            latest_year is None
            or not any(row.statement_year == latest_year for row in history)
            or int(latest_year) < int(max_year)
        ):
            latest_year = max_year
            snapshot.latest_statement_year = max_year
        latest_rows = [row for row in history if row.statement_year == latest_year]
        metrics = dict(snapshot.metrics_json or {})
        added_metrics = 0
        refreshed_metrics = 0
        for row in latest_rows:
            if row.metric_value is None:
                continue
            if metrics.get(row.metric_name) is None:
                added_metrics += 1
            elif metrics.get(row.metric_name) != row.metric_value:
                refreshed_metrics += 1
            metrics[row.metric_name] = row.metric_value

        dated_rows = [row for row in latest_rows if row.as_of_date is not None]
        best_lineage = sorted(
            dated_rows,
            key=lambda row: (row.as_of_date or dt.date.min, row.source_document_id or 0),
            reverse=True,
        )[0] if dated_rows else None
        as_of_date = best_lineage.as_of_date if best_lineage is not None else None
        source_document_id = best_lineage.source_document_id if best_lineage is not None else None

        diagnostics = dict(snapshot.diagnostics_json or {})
        coverage = dict(snapshot.coverage_json or {})
        source = dict(snapshot.source_json or {})
        archetype = infer_statement_archetype(row.metric_name for row in latest_rows)
        diagnostics["statement_archetype"] = archetype
        diagnostics["cgnc_mapped_metric_count"] = len([row for row in latest_rows if row.source_sheet == "bvc_cgnc_mapping"])
        if as_of_date is not None:
            coverage["pit_as_of_date"] = as_of_date.isoformat()
            source["pit_lineage"] = {
                "as_of_date": as_of_date.isoformat(),
                "source_document_id": source_document_id,
                "latest_statement_year": latest_year,
                "archetype": archetype,
            }
        coverage["metric_count"] = sum(value is not None for value in metrics.values())
        coverage["cgnc_added_latest_metric_count"] = added_metrics
        coverage["cgnc_refreshed_latest_metric_count"] = refreshed_metrics

        snapshot.metrics_json = sanitize_json_compatible(metrics)
        snapshot.diagnostics_json = sanitize_json_compatible(diagnostics)
        snapshot.coverage_json = sanitize_json_compatible(coverage)
        snapshot.source_json = sanitize_json_compatible(source)
        if snapshot.as_of_date is None and as_of_date is not None:
            snapshot.as_of_date = as_of_date
        if snapshot.source_document_id is None and source_document_id is not None:
            snapshot.source_document_id = source_document_id
        snapshot.updated_at = _utcnow()
        db.add(snapshot)
        updated += 1
    db.flush()
    return updated


def sync_bvc_period_metrics_to_annual_and_latest(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbols: set[str] | None = None,
) -> dict[str, int]:
    """Map BVC 46-field period metrics into the engine's PIT annual layer."""

    raw_rows = _period_lineage_to_annual_rows(db, import_id=import_id, symbols=symbols)
    mapped_rows = map_cgnc_annual_metrics(raw_rows)
    inserted, updated = _upsert_annual_metric_rows(db, import_id=import_id, rows=mapped_rows)
    affected_symbols = {row.symbol.upper() for row in mapped_rows}
    snapshot_count = _sync_latest_snapshots_from_annual(db, import_id=import_id, symbols=affected_symbols)
    return {
        "raw_period_metric_count": len(raw_rows),
        "mapped_annual_metric_count": len(mapped_rows),
        "annual_inserted_count": inserted,
        "annual_updated_count": updated,
        "latest_snapshot_updated_count": snapshot_count,
    }


def get_snapshot_as_of(
    db: Session,
    *,
    symbol: str,
    as_of: dt.date,
    import_id: uuid.UUID | None = None,
) -> FundamentalSnapshot | None:
    """Reconstruct a PIT snapshot using only rows public on or before as_of."""

    symbol = symbol.upper()
    if "as_of_date" not in _existing_table_columns(db, models.FundamentalAnnualMetric):
        return None
    query, annual_columns = _annual_metric_query(db)
    query = query.filter(
        models.FundamentalAnnualMetric.symbol == symbol,
        models.FundamentalAnnualMetric.as_of_date.isnot(None),
        models.FundamentalAnnualMetric.as_of_date <= as_of,
        models.FundamentalAnnualMetric.metric_value.isnot(None),
    )
    if import_id is not None:
        query = query.filter(models.FundamentalAnnualMetric.import_id == import_id)
    else:
        query = query.join(
            models.FundamentalImport,
            models.FundamentalAnnualMetric.import_id == models.FundamentalImport.id,
        ).filter(models.FundamentalImport.status.in_(SUCCEEDED_IMPORT_STATUSES))

    selected: dict[tuple[int, str], models.FundamentalAnnualMetric] = {}
    for row in query.all():
        row = _apply_annual_schema_compat(row, annual_columns)
        key = (int(row.statement_year), row.metric_name)
        current = selected.get(key)
        rank = (row.as_of_date or dt.date.min, row.created_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc), row.id or 0)
        current_rank = (
            current.as_of_date or dt.date.min,
            current.created_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            current.id or 0,
        ) if current is not None else None
        if current is None or rank > current_rank:
            selected[key] = row
    if not selected:
        return None

    latest_year = max(year for year, _metric_name in selected)
    latest_rows = [row for (year, _metric_name), row in selected.items() if year == latest_year]
    metrics = {row.metric_name: row.metric_value for row in latest_rows}
    best_as_of = max((row.as_of_date for row in selected.values() if row.as_of_date is not None), default=None)
    best_source_document_id = None
    if best_as_of is not None:
        source_candidates = [
            row.source_document_id
            for row in selected.values()
            if row.as_of_date == best_as_of and row.source_document_id is not None
        ]
        best_source_document_id = max(source_candidates) if source_candidates else None

    return FundamentalSnapshot(
        symbol=symbol,
        company_name=latest_rows[0].company_name if latest_rows else symbol,
        latest_statement_year=latest_year,
        metrics=metrics,
        coverage={
            "pit_as_of_date": as_of.isoformat(),
            "latest_available_as_of_date": best_as_of.isoformat() if best_as_of else None,
            "metric_count": sum(value is not None for value in metrics.values()),
        },
        diagnostics={"statement_archetype": infer_statement_archetype(metrics)},
        source={
            "pit_accessor": "get_snapshot_as_of",
            "source_document_id": best_source_document_id,
            "import_id": str(import_id) if import_id is not None else None,
        },
        as_of_date=best_as_of,
        source_document_id=best_source_document_id,
    )


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
        query, annual_columns = _annual_metric_query(db)
        query = query.filter(
            models.FundamentalAnnualMetric.import_id == import_id,
            models.FundamentalAnnualMetric.symbol.in_(item_symbols),
        )
        for row in query.order_by(
            models.FundamentalAnnualMetric.symbol.asc(),
            models.FundamentalAnnualMetric.statement_year.asc(),
            models.FundamentalAnnualMetric.metric_name.asc(),
        ).all():
            rows.append(_annual_from_model(_apply_annual_schema_compat(row, annual_columns)))
    return _apply_metric_overrides_to_history(db, rows, symbols=sorted(wanted))


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
        if key in DEFAULT_ASSUMPTIONS and ASSUMPTION_META.get(key, {}).get("editable", True) and value is not None
    }
    currency = assumptions.get("currency")
    if currency:
        cleaned["currency"] = str(currency).strip().upper()
    return cleaned


def _clean_static_assumptions(assumptions: dict[str, Any]) -> dict[str, Any]:
    cleaned = _clean_assumptions(assumptions)
    for key in PHASE2_STATIC_RETIRED_ASSUMPTIONS:
        cleaned.pop(key, None)
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
        if not ASSUMPTION_META.get(key, {}).get("editable", True):
            raise ValueError(f"assumption {key} is computed and cannot be edited directly")
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


def methodology_payload() -> dict[str, Any]:
    return {
        "version": METHODOLOGY_VERSION,
        "assumptions": {key: dict(value) for key, value in ASSUMPTION_META.items()},
        "models": {
            "order": list(("fcff_dcf", "fcfe_dcf", "ddm", "residual_income", "justified_multiples", "relative_multiples", "reverse_dcf")),
            "families": {
                "intrinsic": ["fcff_dcf", "fcfe_dcf", "ddm", "residual_income"],
                "relative": ["justified_multiples", "relative_multiples"],
                "diagnostic": ["reverse_dcf"],
            },
        },
        "cost_of_capital": {
            "formula": "Ke = max(rf + beta x ERP, cost_of_equity_floor); WACC = We x Ke + Wd x Kd x (1 - tax)",
            "beta_default": "2y weekly OLS vs MASI, Dimson+Blume/peer fallback only for thin names.",
        },
    }


def _latest_beta_history(
    db: Session,
    *,
    symbol: str,
    as_of: dt.date | None,
) -> models.FundamentalBetaHistory | None:
    if not _table_exists(db, models.FundamentalBetaHistory):
        return None
    query = db.query(models.FundamentalBetaHistory).filter(models.FundamentalBetaHistory.symbol == symbol.upper())
    if as_of is not None:
        query = query.filter(models.FundamentalBetaHistory.as_of <= as_of)
    try:
        return query.order_by(models.FundamentalBetaHistory.as_of.desc(), models.FundamentalBetaHistory.created_at.desc()).first()
    except SQLAlchemyError:
        db.rollback()
        return None


def _apply_live_cost_of_capital(
    db: Session,
    *,
    symbol: str,
    assumptions: dict[str, Any],
    provenance: dict[str, str] | None = None,
    sector: str | None = None,
    scenario: str = "base",
    snapshot_row: models.FundamentalLatestSnapshot | None = None,
    snapshot: FundamentalSnapshot | None = None,
    history: list[AnnualMetricRow] | None = None,
    use_snapshot_beta_as_of: bool = False,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    out: dict[str, Any] = dict(assumptions)
    symbol = symbol.upper()
    if snapshot is None:
        if snapshot_row is None:
            snapshot_row = latest_snapshot_rows_by_symbol(db, symbols=[symbol]).get(symbol)
        snapshot = _snapshot_from_model(snapshot_row) if snapshot_row is not None else None
    if history is None and snapshot_row is not None:
        history = _load_history(db, snapshot_row.import_id, symbol)
    history = history or []

    beta_as_of = snapshot.as_of_date if use_snapshot_beta_as_of and snapshot is not None else None
    beta_row = _latest_beta_history(db, symbol=symbol, as_of=beta_as_of)
    beta = _num(beta_row.beta if beta_row is not None else out.get("beta"))
    if beta is None:
        beta = float(DEFAULT_ASSUMPTIONS["beta"])
    beta_source = "beta_history" if beta_row is not None else "default_beta"

    macro_config = resolve_macro_config(db, as_of=beta_as_of)
    out.update(macro_config.assumption_updates())
    risk_free = float(out.get("risk_free_rate", DEFAULT_ASSUMPTIONS["risk_free_rate"]))
    base_erp = float(out.get("equity_risk_premium", DEFAULT_ASSUMPTIONS["equity_risk_premium"]))
    country_risk_premium = float(out.get("country_risk_premium", 0.0) or 0.0)
    scenario_erp_addon = float(out.get("scenario_erp_addon", DEFAULT_ASSUMPTIONS["scenario_erp_addon"]) or 0.0)
    erp = base_erp + country_risk_premium + scenario_erp_addon
    cost_equity_unfloored = cost_of_equity_capm(risk_free_rate=risk_free, beta=beta, equity_risk_premium=erp)
    cost_equity_floor = max(
        risk_free,
        float(out.get("cost_of_equity_floor", DEFAULT_ASSUMPTIONS.get("cost_of_equity_floor", 0.0)) or 0.0),
    )
    cost_equity = max(cost_equity_unfloored, cost_equity_floor, risk_free)
    existing_build = out.get("cost_of_capital_build_up")
    existing_build = existing_build if isinstance(existing_build, dict) else {}
    base_cost_debt = (
        _num(existing_build.get("base_cost_of_debt"))
        or _num(out.get("cost_of_debt"))
        or DEFAULT_ASSUMPTIONS["cost_of_debt"]
    )
    scenario_cost_of_debt_addon = float(out.get("scenario_cost_of_debt_addon", DEFAULT_ASSUMPTIONS["scenario_cost_of_debt_addon"]) or 0.0)
    tax_rate = float(out.get("tax_rate", DEFAULT_ASSUMPTIONS["tax_rate"]))

    equity_weight = float(out.get("default_equity_weight", DEFAULT_ASSUMPTIONS["default_equity_weight"]))
    debt_weight = float(out.get("default_debt_weight", DEFAULT_ASSUMPTIONS["default_debt_weight"]))
    target_total = equity_weight + debt_weight
    if target_total > 0:
        equity_weight /= target_total
        debt_weight /= target_total
    metrics = snapshot.metrics if snapshot is not None else {}
    market_cap = _snapshot_metric(metrics, "MarketCap_Calc", "MarketCap")
    debt = _latest_history_metric(history, "Total_Debt", "Debt_Total", "Dettes_de_financement")
    if debt is None:
        debt = _snapshot_metric(metrics, "Total_Debt", "Debt_Total", "Dettes_de_financement")
    use_market_weights = float(out.get("use_balance_sheet_capital_weights", DEFAULT_ASSUMPTIONS["use_balance_sheet_capital_weights"]) or 0.0) >= 0.5
    weight_source = "default_target_forced" if not use_market_weights else "default_target_missing_market_cap_or_debt"
    if use_market_weights and snapshot is not None:
        if market_cap is not None and market_cap > 0 and debt is not None and debt >= 0:
            capital = market_cap + debt
            if capital > 0:
                equity_weight = market_cap / capital
                debt_weight = debt / capital
                weight_source = "market_cap_plus_debt"

    interest = _latest_history_metric(history, "Interest_Expense", "Charges_Interets", "Net_Interest_Expense", "Resultat_financier")
    if interest is None:
        interest = _snapshot_metric(metrics, "Interest_Expense", "Charges_Interets", "Net_Interest_Expense", "Resultat_financier")
    interest_abs = abs(interest) if interest is not None else None
    ebit = _latest_history_metric(history, "EBIT", "Resultat_dexploitation")
    if ebit is None:
        ebit = _snapshot_metric(metrics, "EBIT", "Resultat_dexploitation")
    financial = _is_financial_sector(sector)
    interest_coverage = ebit / interest_abs if not financial and ebit is not None and ebit > 0 and interest_abs and interest_abs > 0 else None
    synthetic_spread, synthetic_bucket = _synthetic_debt_spread(interest_coverage)
    kd_synthetic = risk_free + synthetic_spread if synthetic_spread is not None else None
    debt_values = [value for value in _history_metric_series(history, "Total_Debt", "Debt_Total", "Dettes_de_financement") if value > 0]
    if debt is not None and debt > 0:
        debt_values.append(debt)
    average_total_debt = None
    if debt_values:
        tail = debt_values[-2:]
        average_total_debt = sum(tail) / len(tail)
    kd_effective = interest_abs / average_total_debt if interest_abs and average_total_debt and average_total_debt > 0 else None
    if kd_effective is not None and not (0.0 < kd_effective < 0.50):
        kd_effective = None
    if financial:
        cost_debt_pre_scenario = base_cost_debt
        cost_debt_source = "registry_default_financial_sector"
    elif kd_synthetic is not None:
        cost_debt_pre_scenario = kd_synthetic
        cost_debt_source = "synthetic_interest_coverage_spread"
    elif kd_effective is not None:
        cost_debt_pre_scenario = kd_effective
        cost_debt_source = "effective_interest_rate_fallback"
    else:
        cost_debt_pre_scenario = base_cost_debt
        cost_debt_source = "registry_default_missing_debt_inputs"
    cost_debt_unclamped = cost_debt_pre_scenario + scenario_cost_of_debt_addon
    cost_debt_floor = max(0.035, risk_free + 0.005)
    cost_debt_ceiling = min(0.085, risk_free + 0.060)
    cost_debt = max(cost_debt_floor, min(cost_debt_ceiling, cost_debt_unclamped))

    build = wacc_build_up(
        cost_of_equity=cost_equity,
        cost_of_debt=cost_debt,
        tax_rate=tax_rate,
        equity_weight=equity_weight,
        debt_weight=debt_weight,
    )
    build.update(
        {
            "beta": beta,
            "risk_free_rate": risk_free,
            "base_equity_risk_premium": base_erp,
            "country_risk_premium": country_risk_premium,
            "scenario_erp_addon": scenario_erp_addon,
            "effective_equity_risk_premium": erp,
            **macro_config.to_build_up_inputs(),
            "cost_of_equity_unfloored": cost_equity_unfloored,
            "cost_of_equity_floor": cost_equity_floor,
            "cost_of_equity_floor_bound": cost_equity > cost_equity_unfloored,
            "base_cost_of_debt": base_cost_debt,
            "scenario_cost_of_debt_addon": scenario_cost_of_debt_addon,
            "effective_cost_of_debt": cost_debt,
            "cost_of_debt_source": cost_debt_source,
            "cost_of_debt_pre_scenario": cost_debt_pre_scenario,
            "cost_of_debt_unclamped": cost_debt_unclamped,
            "cost_of_debt_floor": cost_debt_floor,
            "cost_of_debt_ceiling": cost_debt_ceiling,
            "kd_synthetic": kd_synthetic,
            "kd_effective": kd_effective,
            "interest_coverage": interest_coverage,
            "synthetic_spread": synthetic_spread,
            "synthetic_bucket": synthetic_bucket,
            "interest_expense": interest_abs,
            "average_total_debt": average_total_debt,
            "total_debt": debt,
            "market_cap": market_cap,
            "beta_source": beta_source,
            "beta_as_of": beta_row.as_of.isoformat() if beta_row is not None else None,
            "beta_method": beta_row.method if beta_row is not None else None,
            "beta_r2": beta_row.r2 if beta_row is not None else None,
            "beta_n_obs": beta_row.n_obs if beta_row is not None else None,
            "beta_zero_week_frac": beta_row.zero_week_frac if beta_row is not None else None,
            "beta_liquidity_flag": bool(beta_row.liquidity_flag) if beta_row is not None else None,
            "beta_frequency": beta_row.frequency if beta_row is not None else "weekly",
            "beta_window_years": beta_row.window_years if beta_row is not None else 2.0,
            "beta_lookup_as_of": beta_as_of.isoformat() if beta_as_of is not None else "latest",
            "weight_source": weight_source,
            "market_proxy": beta_row.proxy if beta_row is not None else "MASI",
        }
    )
    out["beta"] = beta
    out["cost_of_equity"] = build["cost_of_equity"]
    out["cost_of_debt"] = build["cost_of_debt"]
    out["wacc"] = build["wacc"]
    out["computed_equity_weight"] = build["equity_weight"]
    out["computed_debt_weight"] = build["debt_weight"]
    out["cost_of_capital_build_up"] = build
    existing_terminal_basis = out.get("terminal_growth_basis")
    if isinstance(existing_terminal_basis, dict):
        for key, path in (("terminal_growth_firm", "firm"), ("terminal_growth_equity", "equity")):
            path_basis = existing_terminal_basis.get(path)
            source = str(path_basis.get("source", "")) if isinstance(path_basis, dict) else ""
            if not source.startswith("explicit_"):
                out.pop(key, None)
        out.pop("terminal_growth_basis", None)
    terminal_explicit_keys: set[str] = set()
    if provenance is not None:
        terminal_explicit_keys = {
            key
            for key in ("terminal_growth", "terminal_growth_firm", "terminal_growth_equity")
            if provenance.get(key) == "user_override"
        }
    if snapshot is not None:
        out = enrich_terminal_growth_assumptions(
            snapshot,
            history,
            out,
            scenario=scenario,
            explicit_keys=terminal_explicit_keys,
            sector=sector,
        )

    if provenance is not None:
        provenance = dict(provenance)
        provenance["beta"] = "beta_history" if beta_row is not None else provenance.get("beta", "default")
        provenance["risk_free_rate"] = "macro_config"
        provenance["equity_risk_premium"] = "macro_config"
        provenance["country_risk_premium"] = "macro_config"
        provenance["cost_of_debt"] = "computed"
        provenance["cost_of_equity"] = "computed"
        provenance["wacc"] = "computed"
        provenance["computed_equity_weight"] = "computed"
        provenance["computed_debt_weight"] = "computed"
        provenance["cost_of_capital_build_up"] = "computed"
        for key in ("terminal_growth_firm", "terminal_growth_equity"):
            path = "firm" if key.endswith("_firm") else "equity"
            basis = out.get("terminal_growth_basis")
            path_basis = basis.get(path) if isinstance(basis, dict) and isinstance(basis.get(path), dict) else {}
            source = str(path_basis.get("source", ""))
            if source == "legacy_terminal_growth_override":
                provenance[key] = provenance.get("terminal_growth", "user_override")
            elif source.startswith("explicit_"):
                provenance[key] = provenance.get(key, "user_override")
            else:
                provenance[key] = "computed_from_fundamentals"
        provenance["terminal_growth_basis"] = "computed"
    return out, provenance


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
            merged.update(_clean_static_assumptions(dict(row.assumptions_json or {})))
    loader = overrides_loader or make_overrides_loader(db)
    for key, value in (loader(symbol, scenario) or {}).items():
        merged[key] = value
    merged, _merged_provenance, probability_warnings = normalize_scenario_probabilities(merged)
    merged, _provenance = _apply_live_cost_of_capital(db, symbol=symbol, assumptions=merged, sector=sector, scenario=scenario)
    merged["scenario_probabilities"] = scenario_probabilities_from_assumptions(merged)
    if probability_warnings:
        merged["scenario_probability_warnings"] = probability_warnings
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
            cleaned = _clean_static_assumptions(dict(row.assumptions_json or {}))
            for key, value in cleaned.items():
                merged[key] = value
                provenance[key] = "symbol" if scope_type == "symbol" else "scenario"
    loader = overrides_loader or make_overrides_loader(db)
    for key, value in (loader(symbol, scenario) or {}).items():
        merged[key] = value
        provenance[key] = "user_override"
    merged, provenance, probability_warnings = normalize_scenario_probabilities(merged, provenance)
    assumptions, provenance = _apply_live_cost_of_capital(db, symbol=symbol, assumptions=merged, provenance=provenance, sector=sector, scenario=scenario)
    assumptions["scenario_probabilities"] = scenario_probabilities_from_assumptions(assumptions)
    if probability_warnings:
        assumptions["scenario_probability_warnings"] = probability_warnings
    return assumptions, provenance


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
    if _table_exists(db, models.FundamentalProjection):
        db.query(models.FundamentalProjection).filter(
            models.FundamentalProjection.import_id == import_id,
            models.FundamentalProjection.symbol == symbol.upper(),
            models.FundamentalProjection.scenario == scenario,
        ).delete(synchronize_session=False)


def latest_data_verification(
    db: Session,
    *,
    import_id: uuid.UUID | None,
    symbol: str,
    statement_year: int | None,
) -> models.FundamentalDataVerification | None:
    if import_id is None or statement_year is None or not _table_exists(db, models.FundamentalDataVerification):
        return None
    return (
        db.query(models.FundamentalDataVerification)
        .filter(
            models.FundamentalDataVerification.import_id == import_id,
            models.FundamentalDataVerification.symbol == symbol.upper(),
            models.FundamentalDataVerification.statement_year == int(statement_year),
        )
        .one_or_none()
    )


def _data_unverified_reason(row: models.FundamentalDataVerification | None) -> str | None:
    if row is None or str(row.status or "") != "data_unverified":
        return None
    reason = str(row.reason or "").strip()
    if reason:
        return reason
    failed = [str(item) for item in (row.failed_checks_json or []) if str(item)]
    return ",".join(failed) if failed else "data_unverified"


def _rows_by_metric_from_history(
    history: list[AnnualMetricRow], statement_year: int
) -> tuple[dict[str, Any], dict[str, int]]:
    rows: dict[str, Any] = {}
    metric_years: dict[str, int] = {}
    for row in history:
        if row.statement_year == statement_year:
            rows[row.metric_name] = row.metric_value
            metric_years[row.metric_name] = row.statement_year
    return rows, metric_years


def _prev_rows_by_metric_from_history(
    history: list[AnnualMetricRow], statement_year: int
) -> dict[str, Any]:
    prev_year: int | None = None
    for row in history:
        if row.statement_year < statement_year:
            if prev_year is None or row.statement_year > prev_year:
                prev_year = row.statement_year
    if prev_year is None:
        return {}
    return {row.metric_name: row.metric_value for row in history if row.statement_year == prev_year}


def _upsert_auto_verification(
    db: Session,
    *,
    snapshot_row: models.FundamentalLatestSnapshot,
    import_id: uuid.UUID,
    symbol: str,
    statement_year: int,
    report: DataTieOutReport,
) -> models.FundamentalDataVerification:
    """Persist an auto-computed tieout verdict; never overwrites curated corrections or forced provenance."""
    existing = (
        db.query(models.FundamentalDataVerification)
        .filter(
            models.FundamentalDataVerification.import_id == import_id,
            models.FundamentalDataVerification.symbol == symbol.upper(),
            models.FundamentalDataVerification.statement_year == int(statement_year),
        )
        .one_or_none()
    )
    if existing is not None:
        if bool(existing.corrections_json) or bool(existing.provenance_json):
            return existing
        row = existing
    else:
        row = models.FundamentalDataVerification(
            import_id=import_id,
            symbol=symbol.upper(),
            statement_year=int(statement_year),
            status=report.status,
        )
        db.add(row)
    row.status = report.status
    row.reason = report.reason
    row.failed_checks_json = sanitize_json_compatible(report.failed_checks)
    row.warnings_json = sanitize_json_compatible(report.warnings)
    row.offending_metrics_json = sanitize_json_compatible(report.offending_metrics)
    row.recomputed_metrics_json = sanitize_json_compatible(report.recomputed_metrics)
    row.corrections_json = {}
    row.provenance_json = {}
    row.source_urls_json = []
    row.stockanalysis_json = {}
    row.tieout_report_json = sanitize_json_compatible({
        "status": report.status,
        "failed_checks": report.failed_checks,
        "warnings": report.warnings,
        "offending_metrics": report.offending_metrics,
        "recomputed_metrics": report.recomputed_metrics,
    })
    row.updated_at = _utcnow()
    coverage = dict(snapshot_row.coverage_json or {})
    coverage["data_verification"] = {"status": report.status, "reason": report.reason}
    snapshot_row.coverage_json = sanitize_json_compatible(coverage)
    db.add(snapshot_row)
    return row


def reverify_symbol(
    db: Session,
    symbol: str,
    *,
    import_id: uuid.UUID | None = None,
) -> models.FundamentalDataVerification | None:
    """Re-run the tieout for a symbol's canonical snapshot and overwrite the cached verdict.

    Safe to call at any time: curated rows (those with corrections_json or provenance_json)
    are never overwritten by _upsert_auto_verification.  Returns None if the symbol has no
    canonical snapshot or the tieout infrastructure table is absent.
    """
    symbol = symbol.upper()
    snap = canonical_snapshot_for_symbol(db, symbol)
    if snap is None:
        return None
    effective_import_id = import_id or snap.import_id
    sy = snap.latest_statement_year
    if sy is None or not _table_exists(db, models.FundamentalDataVerification):
        return None
    history = _load_history(db, effective_import_id, symbol)
    rows_bm, metric_years_bm = _rows_by_metric_from_history(history, sy)
    prev_rows_bm = _prev_rows_by_metric_from_history(history, sy)
    report = build_data_tieout_report(
        symbol, sy, rows_bm,
        previous_rows_by_metric=prev_rows_bm,
        snapshot_year=sy,
        metric_years=metric_years_bm,
        period_type="annual",
    )
    return _upsert_auto_verification(
        db,
        snapshot_row=snap,
        import_id=effective_import_id,
        symbol=symbol,
        statement_year=sy,
        report=report,
    )


def _nr_valuation_results_for_data_unverified(
    *,
    symbol: str,
    scenario: str,
    current_price: float | None,
    reason: str,
) -> list[ValuationResult]:
    warning = f"data_unverified_nr:{reason}"
    return [
        ValuationResult(
            symbol=symbol.upper(),
            scenario=scenario,
            model=model,
            fair_value=None,
            current_price=current_price,
            upside_pct=None,
            confidence="unavailable",
            inputs={"verification_status": "data_unverified", "reason": reason},
            outputs={"status": "not_rated"},
            warnings=[warning],
            family="diagnostic" if model == "reverse_dcf" else "valuation",
            methodology="Model withheld because the source annual data did not pass Brief 38 tie-out verification.",
            confidence_score=None,
            weight=0.0,
            is_proxy=True,
            data_quality_score=0.0,
            currency="MAD",
        )
        for model in VALUATION_MODEL_ORDER
    ]


def _persist_data_unverified_nr(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
    scenario: str,
    current_price: float | None,
    reason: str,
    computed_at: dt.datetime,
    snapshot_row: models.FundamentalLatestSnapshot,
) -> list[models.FundamentalValuationResult]:
    valuations = _nr_valuation_results_for_data_unverified(
        symbol=symbol,
        scenario=scenario,
        current_price=current_price,
        reason=reason,
    )
    ensemble = compute_valuation_ensemble(symbol.upper(), scenario, valuations)
    eligibility = {
        model: {"eligible": False, "confidence": "unavailable", "reason": "data_unverified"}
        for model in VALUATION_MODEL_ORDER
    }
    eligibility["data_verification"] = {"status": "data_unverified", "reason": reason}
    eligibility["ensemble"] = {
        "usable_model_count": ensemble.usable_model_count,
        "excluded_model_count": ensemble.excluded_model_count,
        "confidence_score": ensemble.confidence_score,
        "model_weights": ensemble.model_weights,
        "warnings": ensemble.warnings,
        "currency": ensemble.currency,
        "fair_value_mean": ensemble.fair_value_mean,
        "model_dispersion_cv": ensemble.model_dispersion_cv,
        "dispersion_factor": ensemble.dispersion_factor,
    }
    snapshot_row.model_eligibility_json = sanitize_json_compatible(eligibility)
    _delete_valuations(db, import_id, symbol, scenario)
    rows = [
        models.FundamentalValuationResult(
            import_id=import_id,
            symbol=symbol.upper(),
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
            computed_at=computed_at,
        )
        for result in valuations
    ]
    db.add_all(rows)
    db.add(
        models.FundamentalEnsembleResult(
            import_id=import_id,
            symbol=symbol.upper(),
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
            warnings_json=sanitize_json_compatible([*ensemble.warnings, f"data_unverified_nr:{reason}"]),
            sensitivity_grids_json=None,
            currency=ensemble.currency,
            model_dispersion_low=ensemble.model_dispersion_low,
            model_dispersion_base=ensemble.model_dispersion_base,
            model_dispersion_high=ensemble.model_dispersion_high,
            monte_carlo_low=ensemble.monte_carlo_low,
            monte_carlo_base=ensemble.monte_carlo_base,
            monte_carlo_high=ensemble.monte_carlo_high,
            fair_value_mean=ensemble.fair_value_mean,
            model_dispersion_cv=ensemble.model_dispersion_cv,
            dispersion_factor=ensemble.dispersion_factor,
            computed_at=computed_at,
        )
    )
    db.flush()
    return rows


def _clone_snapshot(snapshot: FundamentalSnapshot) -> FundamentalSnapshot:
    return replace(
        snapshot,
        metrics=dict(snapshot.metrics or {}),
        scores=dict(snapshot.scores or {}),
        diagnostics=dict(snapshot.diagnostics or {}),
        coverage=dict(snapshot.coverage or {}),
        model_eligibility=dict(snapshot.model_eligibility or {}),
        source=dict(snapshot.source or {}),
    )


def _symbol_valuation_context(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
) -> dict[str, Any]:
    snapshot_query, snapshot_columns = _snapshot_query(db)
    snapshot_row = (
        snapshot_query
        .filter(
            models.FundamentalLatestSnapshot.import_id == import_id,
            models.FundamentalLatestSnapshot.symbol == symbol,
        )
        .first()
    )
    if snapshot_row is None:
        return {"snapshot_row": None}

    snapshot_row = _apply_snapshot_schema_compat(snapshot_row, db.get(models.FundamentalImport, import_id), snapshot_columns)
    scope = _scope_for_symbols(db, [symbol])
    latest_rows = latest_snapshot_rows_by_symbol(db, scope=scope)
    current_snapshot = latest_rows.get(symbol)
    is_current_snapshot = current_snapshot is not None and current_snapshot.import_id == snapshot_row.import_id
    latest_rows[symbol] = snapshot_row
    enriched = enriched_snapshots_by_symbol(db, latest_rows)
    peer_snapshots = list(enriched.values())
    return {
        "snapshot_row": snapshot_row,
        "target_snapshot": enriched.get(symbol) or _snapshot_from_model(snapshot_row),
        "peer_snapshots": peer_snapshots,
        "history": _load_history(db, import_id, symbol),
        "period_history": _load_period_history(db, import_id, symbol),
        "sectors": _stock_sectors(db, [row.symbol for row in peer_snapshots]),
        "is_current_snapshot": is_current_snapshot,
    }


def compute_relative_multiples_preview(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
    scenario: str,
    peer_symbols: list[str],
) -> ValuationResult | None:
    """Recompute only the relative_multiples model against an explicit peer basket.

    Purely on-the-fly (no persistence, no tie-out/projection rebuild) so a user's
    comparator basket choice can be reflected in the ensemble/triangulation without
    touching the cached default (sector-based) valuation rows.
    """
    symbol = symbol.upper()
    scenario = _scenario_key(scenario)
    cleaned_peers = sorted({peer.strip().upper() for peer in peer_symbols if peer and peer.strip()} - {symbol})
    if not cleaned_peers:
        return None

    all_symbols = [symbol, *cleaned_peers]
    scope = _scope_for_symbols(db, all_symbols)
    latest_rows = latest_snapshot_rows_by_symbol(db, symbols=all_symbols, scope=scope)
    if symbol not in latest_rows:
        return None
    enriched = enriched_snapshots_by_symbol(db, latest_rows)
    target_snapshot = enriched.get(symbol)
    if target_snapshot is None:
        return None
    peer_snapshots = [enriched[peer] for peer in cleaned_peers if peer in enriched]
    if not peer_snapshots:
        return None

    synthetic_sector = "__comparator_basket__"
    sectors = {sym: synthetic_sector for sym in all_symbols}
    sector = _stock_sectors(db, [symbol]).get(symbol)
    is_financial = _is_financial(sector)
    history = _load_history(db, import_id, symbol)
    merged_assumptions = active_assumptions_for(db, symbol=symbol, sector=sector, scenario=scenario)
    peer_min_count = int(merged_assumptions.get("peer_min_count", DEFAULT_ASSUMPTIONS.get("peer_min_count", 3)))
    peer_stats = _peer_stats(peer_snapshots, sectors, symbol, peer_min_count)
    current_price = _positive_num(target_snapshot.metrics.get("Current_Price"))
    return _relative_multiples(target_snapshot, history, current_price, peer_stats, merged_assumptions, scenario, is_financial=is_financial)


def recompute_symbol_valuations(
    db: Session,
    *,
    import_id: uuid.UUID,
    symbol: str,
    scenario: str = "base",
    overrides_loader: AssumptionOverrideLoader | None = None,
    computed_at: dt.datetime | None = None,
    shared_context: dict[str, Any] | None = None,
    include_sensitivity_grids: bool = True,
) -> list[models.FundamentalValuationResult]:
    symbol = symbol.upper()
    scenario = _scenario_key(scenario)
    run_ts = computed_at or _utcnow()
    context = shared_context or _symbol_valuation_context(db, import_id=import_id, symbol=symbol)
    snapshot_row = context.get("snapshot_row")
    if snapshot_row is None:
        return []

    target_snapshot = _clone_snapshot(context["target_snapshot"])
    peer_snapshots = [_clone_snapshot(snapshot) for snapshot in context["peer_snapshots"]]
    history = list(context["history"])
    period_history = list(context["period_history"])
    sectors = dict(context["sectors"])
    is_current_snapshot = bool(context["is_current_snapshot"])
    verification = latest_data_verification(
        db,
        import_id=import_id,
        symbol=symbol,
        statement_year=target_snapshot.latest_statement_year,
    )
    # Re-run the tieout whenever the cached row carries no curated corrections or forced
    # provenance.  This keeps auto-verdicts fresh as tie-out logic evolves; rows that
    # carry analyst corrections/provenance are intentionally preserved as-is.
    _should_recompute_tieout = verification is None or (
        not bool(verification.corrections_json) and not bool(verification.provenance_json)
    )
    if _should_recompute_tieout and target_snapshot.latest_statement_year is not None and _table_exists(db, models.FundamentalDataVerification):
        rows_bm, metric_years_bm = _rows_by_metric_from_history(history, target_snapshot.latest_statement_year)
        prev_rows_bm = _prev_rows_by_metric_from_history(history, target_snapshot.latest_statement_year)
        tieout_report = build_data_tieout_report(
            symbol,
            target_snapshot.latest_statement_year,
            rows_bm,
            previous_rows_by_metric=prev_rows_bm,
            snapshot_year=target_snapshot.latest_statement_year,
            metric_years=metric_years_bm,
            period_type="annual",
        )
        verification = _upsert_auto_verification(
            db,
            snapshot_row=snapshot_row,
            import_id=import_id,
            symbol=symbol,
            statement_year=target_snapshot.latest_statement_year,
            report=tieout_report,
        )
        if tieout_report.status == "data_unverified":
            snapshot_row.metrics_json = sanitize_json_compatible(target_snapshot.metrics)
            snapshot_row.source_json = sanitize_json_compatible(target_snapshot.source)
            return _persist_data_unverified_nr(
                db,
                import_id=import_id,
                symbol=symbol,
                scenario=scenario,
                current_price=_positive_num(target_snapshot.metrics.get("Current_Price")),
                reason=tieout_report.reason or "data_unverified",
                computed_at=run_ts,
                snapshot_row=snapshot_row,
            )
    verification_reason = _data_unverified_reason(verification)
    if verification_reason is not None:
        snapshot_row.metrics_json = sanitize_json_compatible(target_snapshot.metrics)
        snapshot_row.coverage_json = sanitize_json_compatible(target_snapshot.coverage)
        snapshot_row.source_json = sanitize_json_compatible(target_snapshot.source)
        return _persist_data_unverified_nr(
            db,
            import_id=import_id,
            symbol=symbol,
            scenario=scenario,
            current_price=_positive_num(target_snapshot.metrics.get("Current_Price")),
            reason=verification_reason,
            computed_at=run_ts,
            snapshot_row=snapshot_row,
        )
    sector = sectors.get(symbol)
    financial_archetype = _financial_archetype_for_sector(sector)
    if financial_archetype is not None:
        target_snapshot = _sanitize_financial_snapshot(target_snapshot, sector=sector)
        history = _sanitize_financial_history(history, sector=sector)
        peer_snapshots = [
            _sanitize_financial_snapshot(snapshot, sector=sectors.get(snapshot.symbol))
            for snapshot in peer_snapshots
        ]
    assumptions = active_assumptions_for(
        db,
        symbol=symbol,
        sector=sector,
        scenario=scenario,
        overrides_loader=overrides_loader,
    )
    assumptions, _ = _apply_live_cost_of_capital(
        db,
        symbol=symbol,
        assumptions=assumptions,
        sector=sector,
        scenario=scenario,
        snapshot_row=snapshot_row,
        snapshot=target_snapshot,
        history=history,
        use_snapshot_beta_as_of=not is_current_snapshot,
    )
    if verification is not None and str(verification.status or "") == "verified":
        assumptions = {**assumptions, "_require_verified_group_roe": True}
    integrity = latest_integrity_report(
        db,
        import_id=import_id,
        symbol=symbol,
        statement_year=target_snapshot.latest_statement_year,
    )
    integrity = source_integrity_report_for_history(
        integrity,
        history=history,
        symbol=symbol,
        statement_year=target_snapshot.latest_statement_year,
    )
    driver_medians = peer_driver_medians(peer_snapshots, sectors, symbol, int(assumptions.get("peer_min_count", DEFAULT_ASSUMPTIONS["peer_min_count"])))
    assumptions = {**assumptions, "_peer_driver_medians": driver_medians, "_financial_archetype": financial_archetype or ""}

    # Phase 3 (brief 54 §3): forward-estimate injection via consensus store.
    # fiscal_year = latest_statement_year + 1 is the natural forward anchor and
    # rolls automatically when new actuals land (e.g. 2025 actuals → FY2026e).
    # load_forward_view returns {} when no consensus rows exist; core falls back
    # to the trailing/midcycle path unchanged — no coverage regression.
    _fwd_year = (target_snapshot.latest_statement_year or run_ts.year) + 1
    _fwd_view = load_forward_view(
        db,
        symbol,
        fiscal_year=_fwd_year,
        valuation_date=run_ts.date(),
    )
    # Phase 4 (brief 54 §3): model-forecaster fallback fills forward_revenue /
    # forward_net_income ONLY where consensus (above) didn't already supply
    # them -- consensus always wins. Backstops the ~50 thin MASI names and all
    # pre-2026 PIT history that BKGR/MarketScreener never cover. Validated to
    # beat the naive-CAGR mechanical baseline out-of-sample (see
    # core/quant_core/fundamentals/forecast_model.py); returns {} on thin data
    # or a missing scikit-learn (dev-only dependency) so there is no coverage
    # regression versus the pre-Phase-4 path.
    _model_view = load_model_forecast_view(
        db,
        symbol,
        import_id=import_id,
        fiscal_year=_fwd_year,
        as_of_year=_fwd_year - 1,
        existing_forward_view=_fwd_view,
    )
    if _model_view:
        _fwd_view = {**_model_view, **_fwd_view}
    if _fwd_view:
        assumptions = {**assumptions, **_fwd_view}

    cyclical_commodity = is_cyclical_or_commodity(symbol, sector)
    projection = _sector_adjusted_projection(
        build_projection(target_snapshot, history, assumptions, scenario=scenario, cyclical=cyclical_commodity),
        sector=sector,
    )
    horizon_set = available_horizons(period_history)
    projections_by_horizon: dict[str, Projection] = {"year": projection}
    for horizon, (period_type, periods_per_year) in HORIZON_PERIOD_BUILD.items():
        if horizon == "year" or horizon not in horizon_set:
            continue
        period_projection = _sector_adjusted_projection(
            build_projection(
                target_snapshot,
                history,
                assumptions,
                scenario=scenario,
                period_history=period_history,
                period_type=period_type,
                periods_per_year=periods_per_year,
                cyclical=cyclical_commodity,
            ),
            sector=sector,
        )
        if period_projection.statements:
            projections_by_horizon[horizon] = period_projection
    assumptions = {**assumptions, "_projection": projection}
    integrity = _integrity_with_projection(
        report=integrity,
        projection=projection,
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
    ensemble = compute_valuation_ensemble(
        symbol, scenario, valuations,
        weight_overrides=_ensemble_weight_overrides_from_assumptions(assumptions),
    )
    data_cutoff = _overlay_data_cutoff(db, symbol=symbol, import_id=import_id) or target_snapshot.as_of_date
    horizon_predictions = _build_horizon_predictions(
        snapshot=target_snapshot,
        projections_by_horizon=projections_by_horizon,
        valuations=valuations,
        ensemble=ensemble,
        data_cutoff=data_cutoff,
        current_price=target_snapshot.metrics.get("Current_Price"),
    )
    eligibility["available_horizons"] = sorted(horizon_set)
    eligibility["horizon_predictions"] = sanitize_json_compatible(horizon_predictions)
    sensitivity_grids = None
    if include_sensitivity_grids:
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
    for horizon_projection in projections_by_horizon.values():
        _persist_projection(db, import_id=import_id, symbol=symbol, scenario=scenario, projection=horizon_projection)
    _persist_projection_integrity_report(db, import_id=import_id, report=integrity)
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
            computed_at=run_ts,
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
            fair_value_mean=ensemble.fair_value_mean,
            model_dispersion_cv=ensemble.model_dispersion_cv,
            dispersion_factor=ensemble.dispersion_factor,
            computed_at=run_ts,
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
    include_sensitivity_grids: bool = True,
) -> list[models.FundamentalValuationResult]:
    rows: list[models.FundamentalValuationResult] = []
    loader = overrides_loader or make_bulk_overrides_loader(db, [symbol])
    run_ts = _utcnow()
    context = _symbol_valuation_context(db, import_id=import_id, symbol=symbol.upper())
    if context.get("snapshot_row") is None:
        return []
    seen: set[str] = set()
    normalized_scenarios = []
    for scenario in scenarios:
        scenario_key = _scenario_key(scenario)
        if scenario_key in seen:
            continue
        seen.add(scenario_key)
        normalized_scenarios.append(scenario_key)
    for scenario in normalized_scenarios:
        rows.extend(
            recompute_symbol_valuations(
                db,
                import_id=import_id,
                symbol=symbol,
                scenario=scenario,
                overrides_loader=loader,
                computed_at=run_ts,
                shared_context=context,
                include_sensitivity_grids=include_sensitivity_grids,
            )
        )
    refresh_canonical_snapshot_flags(db, symbols=[symbol.upper()])
    return rows


def refresh_import_after_pit_sync(db: Session, *, import_id: uuid.UUID) -> dict[str, int]:
    """Re-score and revalue an import after BVC PIT annual rows were added."""

    snapshot_rows = (
        db.query(models.FundamentalLatestSnapshot)
        .filter(models.FundamentalLatestSnapshot.import_id == import_id)
        .order_by(models.FundamentalLatestSnapshot.symbol.asc())
        .all()
    )
    if not snapshot_rows:
        return {"snapshot_count": 0, "valuation_count": 0}

    history = _load_history(db, import_id)
    db.query(models.FundamentalIntegrityReport).filter(
        models.FundamentalIntegrityReport.import_id == import_id,
    ).delete(synchronize_session=False)
    _persist_integrity_reports(db, import_id=import_id, reports=_build_integrity_reports(history))

    snapshots = [_snapshot_from_model(row) for row in snapshot_rows]
    sectors = _stock_sectors(db, [snapshot.symbol for snapshot in snapshots])
    scored = score_fundamental_snapshots(snapshots, history, sectors=sectors)
    scored_by_symbol = {snapshot.symbol.upper(): snapshot for snapshot in scored}
    for row in snapshot_rows:
        snapshot = scored_by_symbol.get(str(row.symbol).upper())
        if snapshot is None:
            continue
        row.metrics_json = sanitize_json_compatible(snapshot.metrics)
        row.scores_json = sanitize_json_compatible(snapshot.scores)
        row.diagnostics_json = sanitize_json_compatible(snapshot.diagnostics)
        row.coverage_json = sanitize_json_compatible(snapshot.coverage)
        row.source_json = sanitize_json_compatible(snapshot.source)
        row.updated_at = _utcnow()
        db.add(row)
    db.flush()

    persist_pillar_history_for_import(db, import_id=import_id)
    overrides_loader = make_bulk_overrides_loader(db, [row.symbol for row in snapshot_rows])
    valuation_count = 0
    for row in snapshot_rows:
        valuation_count += len(
            recompute_symbol_valuations_all_scenarios(
                db,
                import_id=import_id,
                symbol=row.symbol,
                overrides_loader=overrides_loader,
            )
        )
    db.flush()
    return {"snapshot_count": len(snapshot_rows), "valuation_count": valuation_count}


def refresh_symbol_after_metric_override(db: Session, *, symbol: str) -> dict[str, int]:
    """Rebuild source diagnostics, scores, projections, and valuations after a manual metric edit."""

    symbol = symbol.upper()
    snapshot_row = latest_snapshot_rows_by_symbol(db, symbols=[symbol]).get(symbol)
    if snapshot_row is None:
        return {"snapshot_count": 0, "valuation_count": 0}

    history = _load_history(db, snapshot_row.import_id, symbol)
    db.query(models.FundamentalIntegrityReport).filter(
        models.FundamentalIntegrityReport.import_id == snapshot_row.import_id,
        models.FundamentalIntegrityReport.symbol == symbol,
    ).delete(synchronize_session=False)
    _persist_integrity_reports(db, import_id=snapshot_row.import_id, reports=_build_integrity_reports(history))
    db.flush()

    scope = _scope_for_symbols(db, [symbol])
    snapshot_count = rescore_universe(db, scope=scope)
    persist_pillar_history_for_import(db, import_id=snapshot_row.import_id)
    valuation_count = len(
        recompute_symbol_valuations_all_scenarios(
            db,
            import_id=snapshot_row.import_id,
            symbol=symbol,
            scenarios=VALUATION_SCENARIOS,
            overrides_loader=make_bulk_overrides_loader(db, [symbol]),
        )
    )
    db.flush()
    return {"snapshot_count": snapshot_count, "valuation_count": valuation_count}


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
    assumptions, _ = _apply_live_cost_of_capital(
        db,
        symbol=symbol,
        assumptions=assumptions,
        sector=sectors.get(symbol),
        scenario=scenario,
        snapshot_row=snapshot_row,
        snapshot=target_snapshot,
        history=history,
    )
    integrity = latest_integrity_report(
        db,
        import_id=snapshot_row.import_id,
        symbol=symbol,
        statement_year=target_snapshot.latest_statement_year,
    )
    sensitivity = compute_sensitivity(
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
    sensitivity["default_grids"] = compute_default_sensitivity_grids(
        snapshot=target_snapshot,
        history=history,
        peer_snapshots=peer_snapshots,
        sectors=sectors,
        base_assumptions=assumptions,
        scenario=scenario,
        integrity=integrity,
    )
    return sensitivity


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
        _synthesize_balance_sheet_identity(parsed)
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
        if _table_exists(db, models.FundamentalProjection):
            db.query(models.FundamentalProjection).filter(models.FundamentalProjection.import_id == import_row.id).delete(synchronize_session=False)
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
                    as_of_date=row.as_of_date,
                    source_document_id=row.source_document_id,
                )
                for row in parsed.annual_metrics
            ]
        )
        db.bulk_save_objects(
            [
                models.FundamentalPeriodMetric(
                    import_id=import_row.id,
                    source_document_id=row.source_document_id,
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
                as_of_date=row.as_of_date,
                source_document_id=row.source_document_id,
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
        refresh_canonical_snapshot_flags(db, symbols=[snapshot.symbol for snapshot in scored_snapshots])
        db.commit()
        db.refresh(import_row)
        return import_row
    except Exception as exc:
        db.rollback()
        import_row = db.get(models.FundamentalImport, import_id) or import_row
        delete_fundamental_import_artifacts(db, import_id=import_row.id, include_statement_rows=True)
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
    db.query(models.FundamentalAssumptionSet).filter(
        models.FundamentalAssumptionSet.scope_type == scope_type,
        models.FundamentalAssumptionSet.scope_key == scope_key,
        models.FundamentalAssumptionSet.scenario == scenario,
        models.FundamentalAssumptionSet.is_active.is_(True),
    ).update({"is_active": False}, synchronize_session=False)
    existing = (
        db.query(models.FundamentalAssumptionSet.id)
        .filter(
            models.FundamentalAssumptionSet.scope_type == scope_type,
            models.FundamentalAssumptionSet.scope_key == scope_key,
            models.FundamentalAssumptionSet.scenario == scenario,
            models.FundamentalAssumptionSet.version_label == version_label,
        )
        .first()
    )
    if existing is not None:
        version_label = f"{version_label}-{_utcnow().strftime('%Y%m%d%H%M%S')}"
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
