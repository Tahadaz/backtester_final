from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CompanyMapping:
    company_name: str
    mapped_company_name: str | None
    symbol: str | None
    shares_outstanding: float | None = None
    match_type: str | None = None
    score_note: str | None = None
    source: str | None = None
    canonical_company_name: str | None = None
    is_duplicate_symbol: bool = False


@dataclass(frozen=True)
class AnnualMetricRow:
    symbol: str
    company_name: str
    statement_year: int
    metric_name: str
    metric_value: float | None
    raw_metric_name: str | None = None
    source_sheet: str | None = None
    source_field: str | None = None
    is_proxy: bool = False
    as_of_date: dt.date | None = None
    source_document_id: int | None = None


@dataclass(frozen=True)
class PeriodMetricRow:
    symbol: str
    company_name: str
    fiscal_year: int
    period_type: str
    period_label: str
    metric_name: str
    metric_value: float | None
    raw_metric_name: str | None = None
    period_end_date: str | None = None
    source_url: str | None = None
    document_title: str | None = None
    source_document_id: int | None = None
    is_proxy: bool = False


@dataclass(frozen=True)
class FundamentalQualityIssue:
    severity: str
    code: str
    message: str
    symbol: str | None = None
    metric_name: str | None = None
    statement_year: int | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class FundamentalSnapshot:
    symbol: str
    company_name: str
    latest_statement_year: int | None
    metrics: dict[str, float | None] = field(default_factory=dict)
    scores: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    model_eligibility: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    as_of_date: dt.date | None = None
    source_document_id: int | None = None


@dataclass(frozen=True)
class FundamentalWorkbook:
    mappings: list[CompanyMapping]
    annual_metrics: list[AnnualMetricRow]
    latest_snapshots: list[FundamentalSnapshot]
    summary: dict[str, Any]
    quality_issues: list[FundamentalQualityIssue] = field(default_factory=list)
    period_metrics: list[PeriodMetricRow] = field(default_factory=list)


@dataclass(frozen=True)
class ValuationResult:
    symbol: str
    scenario: str
    model: str
    fair_value: float | None
    current_price: float | None
    upside_pct: float | None
    confidence: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    warnings: list[str]
    family: str = "valuation"
    model_version: str = "v3"
    methodology: str | None = None
    confidence_score: float | None = None
    weight: float | None = None
    is_proxy: bool = False
    data_quality_score: float | None = None
    currency: str | None = "MAD"


@dataclass(frozen=True)
class EnsembleResult:
    symbol: str
    scenario: str
    fair_value_low: float | None
    fair_value_base: float | None
    fair_value_high: float | None
    current_price: float | None
    upside_pct: float | None
    confidence_score: float | None
    usable_model_count: int
    excluded_model_count: int
    model_weights: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    currency: str | None = "MAD"
    model_dispersion_low: float | None = None
    model_dispersion_base: float | None = None
    model_dispersion_high: float | None = None
    monte_carlo_low: float | None = None
    monte_carlo_base: float | None = None
    monte_carlo_high: float | None = None
    fair_value_mean: float | None = None
    model_dispersion_cv: float | None = None
    dispersion_factor: float | None = None
    sensitivity_grids: dict[str, Any] | None = None


@dataclass(frozen=True)
class AssumptionVersion:
    scenario: str
    assumptions: dict[str, float]
    source: str = "seeded_default"
    version_label: str = "base"


@dataclass(frozen=True)
class IntegrityCheck:
    name: str
    status: str
    delta: float | None
    rel_delta: float | None
    inputs: dict[str, float | None]
    message: str | None = None


@dataclass(frozen=True)
class IntegrityReport:
    symbol: str
    statement_year: int
    checks: list[IntegrityCheck]
    overall_status: str
    confidence_haircut: float
    projected_statements: list[dict[str, Any]] = field(default_factory=list)
    projection_checks: list[IntegrityCheck] = field(default_factory=list)


@dataclass(frozen=True)
class DataTieOutReport:
    symbol: str
    statement_year: int
    status: str
    checks: list[IntegrityCheck]
    failed_checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    offending_metrics: dict[str, Any] = field(default_factory=dict)
    recomputed_metrics: dict[str, float | None] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None


@dataclass(frozen=True)
class ThesisDriver:
    title: str
    detail: str
    pillar: str | None = None


@dataclass(frozen=True)
class InvalidationCondition:
    condition: str
    breached: bool = False


@dataclass(frozen=True)
class Thesis:
    symbol: str
    as_of: str
    direction: str
    conviction: str
    core_thesis: str
    bullish_drivers: list[ThesisDriver]
    bearish_drivers: list[ThesisDriver]
    target_price: float | None
    target_horizon_months: int | None
    stop_price: float | None
    invalidation_conditions: list[InvalidationCondition]
    linked_catalyst_ids: list[int]
    created_by: str
    created_at: str
    is_current: bool


@dataclass(frozen=True)
class Catalyst:
    id: int
    symbol: str
    event_type: str
    event_date: str
    event_date_confidence: str
    impact_tier: str
    expected_direction: str | None
    title: str
    notes: str | None
    source: str
    created_at: str
    updated_at: str
    is_active: bool
    superseded_by_id: int | None
