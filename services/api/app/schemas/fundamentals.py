from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Recommendation = Literal["BUY", "HOLD", "SELL"]
PillarName = Literal["value", "quality", "growth", "risk", "cash_flow", "health"]


class FundamentalImportOut(BaseModel):
    id: str
    dataset_id: str | None = None
    filename: str
    source_hash: str
    data_source: str = "workbook"
    source_universe: str | None = None
    status: str
    methodology_version: str = "v3"
    rq_job_id: str | None = None
    company_count: int
    symbol_count: int
    annual_metric_count: int
    latest_snapshot_count: int
    quality_issue_count: int = 0
    summary: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: str
    imported_at: str | None = None
    completed_at: str | None = None


class QualityIssueOut(BaseModel):
    severity: str
    code: str
    message: str
    symbol: str | None = None
    metric_name: str | None = None
    statement_year: int | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class TechnicalContextOut(BaseModel):
    horizon: str | None = None
    signal_label: str | None = None
    signal_score_pct: float | None = None
    computed_at: str | None = None


class IntegrityCheckOut(BaseModel):
    name: str
    status: str
    delta: float | None = None
    rel_delta: float | None = None
    inputs: dict[str, float | None] = Field(default_factory=dict)
    message: str | None = None


class IntegrityReportOut(BaseModel):
    symbol: str
    statement_year: int
    checks: list[IntegrityCheckOut] = Field(default_factory=list)
    overall_status: str
    confidence_haircut: float = 0.0
    projected_statements: list[dict[str, Any]] = Field(default_factory=list)
    projection_checks: list[IntegrityCheckOut] = Field(default_factory=list)


class ThesisDriverOut(BaseModel):
    title: str
    detail: str
    pillar: PillarName | None = None


class InvalidationConditionOut(BaseModel):
    condition: str
    breached: bool = False


class ThesisIn(BaseModel):
    as_of: str | None = None
    direction: Literal["long", "short", "pair_long", "pair_short", "avoid"]
    conviction: Literal["high", "medium", "low"]
    core_thesis: str
    bullish_drivers: list[ThesisDriverOut] = Field(default_factory=list)
    bearish_drivers: list[ThesisDriverOut] = Field(default_factory=list)
    target_price: float | None = None
    target_horizon_months: int | None = None
    stop_price: float | None = None
    invalidation_conditions: list[InvalidationConditionOut] = Field(default_factory=list)
    linked_catalyst_ids: list[int] = Field(default_factory=list)


class ThesisOut(ThesisIn):
    id: int
    symbol: str
    created_by: str
    created_at: str | None = None
    is_current: bool = True
    warnings: list[str] = Field(default_factory=list)


class ThesisHistoryOut(BaseModel):
    items: list[ThesisOut] = Field(default_factory=list)


class CatalystIn(BaseModel):
    event_type: Literal["earnings", "dividend", "ex_dividend", "agm", "guidance", "regulatory", "product", "m_and_a", "split", "other"]
    event_date: str
    event_date_confidence: Literal["confirmed", "estimated", "rumour"] = "confirmed"
    impact_tier: Literal["high", "moderate", "routine"]
    expected_direction: Literal["positive", "negative", "neutral"] | None = None
    title: str
    notes: str | None = None


class CatalystPatchIn(BaseModel):
    event_date: str | None = None
    event_date_confidence: Literal["confirmed", "estimated", "rumour"] | None = None
    impact_tier: Literal["high", "moderate", "routine"] | None = None
    expected_direction: Literal["positive", "negative", "neutral"] | None = None
    title: str | None = None
    notes: str | None = None


class CatalystOut(CatalystIn):
    id: int
    symbol: str
    source: str
    created_at: str | None = None
    updated_at: str | None = None
    is_active: bool = True
    superseded_by_id: int | None = None


class CatalystCalendarOut(BaseModel):
    from_date: str
    to_date: str
    items: list[CatalystOut] = Field(default_factory=list)
    truncated: bool = False


class EnsembleOut(BaseModel):
    symbol: str | None = None
    scenario: str | None = None
    fair_value_low: float | None = None
    fair_value_base: float | None = None
    fair_value_high: float | None = None
    current_price: float | None = None
    upside_pct: float | None = None
    confidence_score: float | None = None
    usable_model_count: int = 0
    excluded_model_count: int = 0
    model_weights: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    currency: str | None = None
    model_dispersion_low: float | None = None
    model_dispersion_base: float | None = None
    model_dispersion_high: float | None = None
    monte_carlo_low: float | None = None
    monte_carlo_base: float | None = None
    monte_carlo_high: float | None = None
    sensitivity_grids: dict[str, Any] | None = None


class FundamentalUniverseRow(BaseModel):
    symbol: str
    company_name: str
    display_name: str | None = None
    sector: str | None = None
    market_region: str | None = None
    latest_statement_year: int | None = None
    current_price: float | None = None
    market_cap: float | None = None
    overall_score: float | None = None
    value_score: float | None = None
    quality_score: float | None = None
    growth_score: float | None = None
    dividend_score: float | None = None
    risk_score: float | None = None
    cash_flow_score: float | None = None
    health_score: float | None = None
    accrual_quality_score: float | None = None
    magic_formula_score: float | None = None
    peg_value: float | None = None
    peg_garp_score: float | None = None
    altman_z_score: float | None = None
    altman_zone: str | None = None
    eva_score: float | None = None
    regression_adj_score: float | None = None
    regression_richness_avg: float | None = None
    recommendation: Recommendation | None = None
    target_price: float | None = None
    conviction: int = 0
    revision_direction: Literal["up", "down", "="] = "="
    analyst: str | None = None
    as_of_date: str | None = None
    free_float_pct: float | None = None
    screens: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    model_eligibility: dict[str, Any] = Field(default_factory=dict)
    valuation_summary: dict[str, Any] = Field(default_factory=dict)
    ensemble: EnsembleOut | None = None
    technical: TechnicalContextOut | None = None
    data_source: str | None = None
    imported_at: str | None = None


class AnnualMetricOut(BaseModel):
    statement_year: int
    metrics: dict[str, float | None]


class AnnualMetricRawOut(BaseModel):
    statement_year: int
    metric_name: str
    metric_value: float | None = None
    raw_metric_name: str | None = None
    source_sheet: str | None = None
    source_field: str | None = None
    is_proxy: bool = False


class PeriodMetricOut(BaseModel):
    fiscal_year: int
    period_type: str
    period_label: str
    metric_name: str
    metric_value: float | None = None
    raw_metric_name: str | None = None
    period_end_date: str | None = None
    source_url: str | None = None
    document_title: str | None = None
    is_proxy: bool = False


class ValuationResultOut(BaseModel):
    model: str
    scenario: str
    fair_value: float | None = None
    current_price: float | None = None
    upside_pct: float | None = None
    confidence: str
    confidence_score: float | None = None
    weight: float | None = None
    family: str = "intrinsic"
    methodology: str | None = None
    model_version: str = "v3"
    is_proxy: bool = False
    data_quality_score: float | None = None
    currency: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    computed_at: str | None = None


class FundamentalStockDetailOut(BaseModel):
    symbol: str
    company_name: str
    display_name: str | None = None
    sector: str | None = None
    latest_statement_year: int | None = None
    metrics: dict[str, float | None] = Field(default_factory=dict)
    scores: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    screens: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    model_eligibility: dict[str, Any] = Field(default_factory=dict)
    annual: list[AnnualMetricOut] = Field(default_factory=list)
    annual_raw: list[AnnualMetricRawOut] = Field(default_factory=list)
    period_metrics: list[PeriodMetricOut] = Field(default_factory=list)
    valuations: list[ValuationResultOut] = Field(default_factory=list)
    ensemble: EnsembleOut | None = None
    ensembles: dict[str, EnsembleOut] = Field(default_factory=dict)
    assumptions: dict[str, Any] = Field(default_factory=dict)
    assumption_provenance: dict[str, dict[str, str]] = Field(default_factory=dict)
    integrity: IntegrityReportOut | None = None
    thesis: ThesisOut | None = None
    catalysts: list[CatalystOut] = Field(default_factory=list)
    trend: dict[str, str] = Field(default_factory=dict)
    comps_table: dict[str, Any] | None = None
    quality_issues: list[QualityIssueOut] = Field(default_factory=list)
    technical: TechnicalContextOut | None = None
    recommendation: Recommendation | None = None
    target_price: float | None = None
    conviction: int = 0
    revision_direction: Literal["up", "down", "="] = "="
    analyst: str | None = None
    as_of_date: str | None = None
    free_float_pct: float | None = None
    data_source: str | None = None
    imported_at: str | None = None


class FundamentalComparableComponentIn(BaseModel):
    symbol: str
    shares: float | None = None


class FundamentalComparablesRequest(BaseModel):
    comparator_type: Literal["sector", "index"] = "sector"
    comparator_id: str | None = None
    comparator_name: str | None = None
    sector: str | None = None
    symbols: list[str] = Field(default_factory=list)
    components: list[FundamentalComparableComponentIn] = Field(default_factory=list)
    component_shares: dict[str, float] = Field(default_factory=dict)
    metric_keys: list[str] = Field(default_factory=list)


class FundamentalComparableMetaOut(BaseModel):
    type: Literal["sector", "index"]
    id: str | None = None
    name: str
    sector: str | None = None
    target_in_comparator: bool = False
    weight_source: str = "market_value"


class FundamentalComparableBenchmarkOut(BaseModel):
    metric_key: str
    selected_value: float | None = None
    weighted_including_target: float | None = None
    weighted_excluding_target: float | None = None
    median: float | None = None
    max: float | None = None
    p75: float | None = None
    p25: float | None = None
    min: float | None = None
    eligible_count: int = 0
    weighted_count: int = 0
    missing_metric_count: int = 0
    missing_weight_count: int = 0


class FundamentalComparablePeerOut(BaseModel):
    symbol: str
    company_name: str
    display_name: str | None = None
    sector: str | None = None
    current_price: float | None = None
    shares: float | None = None
    market_value: float | None = None
    base_weight: float | None = None
    is_target: bool = False
    metrics: dict[str, float | None] = Field(default_factory=dict)
    z_scores: dict[str, float | None] = Field(default_factory=dict)
    pct_dev_from_median: dict[str, float | None] = Field(default_factory=dict)
    weights: dict[str, float | None] = Field(default_factory=dict)
    contributions: dict[str, float | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class FundamentalComparablesOut(BaseModel):
    symbol: str
    comparator: FundamentalComparableMetaOut
    metric_keys: list[str] = Field(default_factory=list)
    selected_metrics: dict[str, float | None] = Field(default_factory=dict)
    benchmarks: dict[str, FundamentalComparableBenchmarkOut] = Field(default_factory=dict)
    stats: dict[str, dict[str, float | int | None]] = Field(default_factory=dict)
    peers: list[FundamentalComparablePeerOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FundamentalScreenRankedRow(BaseModel):
    symbol: str
    company_name: str
    display_name: str | None = None
    sector: str | None = None
    market_region: str | None = None
    score: float | None = None
    screen_name: str
    screen: dict[str, Any] = Field(default_factory=dict)
    recommendation: Recommendation | None = None
    target_price: float | None = None
    upside_pct: float | None = None
    conviction: int = 0


class AssumptionUpdateIn(BaseModel):
    assumptions: dict[str, Any]
    scope_type: str = "desk"
    scope_key: str = "GLOBAL"
    version_label: str = "base"


class AssumptionOverrideIn(BaseModel):
    overrides: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class AssumptionOverrideOut(BaseModel):
    id: int
    symbol: str
    scenario: str
    overrides: dict[str, float] = Field(default_factory=dict)
    note: str | None = None
    created_by: str
    created_at: str | None = None
    is_current: bool = True


class AssumptionSetOut(BaseModel):
    scope_type: str
    scope_key: str
    scenario: str
    version_label: str
    assumptions: dict[str, Any]
    source: str
    is_active: bool = True
    provenance: dict[str, str] = Field(default_factory=dict)
    updated_at: str | None = None
    valuations: list[ValuationResultOut] = Field(default_factory=list)


class AssumptionResolvedOut(BaseModel):
    symbol: str
    scenario: str
    assumptions: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, str] = Field(default_factory=dict)


class PillarHistoryRow(BaseModel):
    symbol: str
    as_of: str | None = None
    value_score: float | None = None
    quality_score: float | None = None
    growth_score: float | None = None
    risk_score: float | None = None
    cash_flow_score: float | None = None
    health_score: float | None = None
    overall_score: float | None = None
    pillar_coverage: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class PillarHistoryOut(BaseModel):
    symbol: str
    items: list[PillarHistoryRow] = Field(default_factory=list)
    trend: dict[str, str] = Field(default_factory=dict)


class YfinanceFundamentalImportIn(BaseModel):
    symbols: list[str] | None = None
    market_regions: list[str] | None = None


class YfinanceFundamentalImportQueuedOut(BaseModel):
    batch_id: str
    enqueued_count: int
    rq_job_id: str | None = None


class TargetedBvcFundamentalImportIn(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    period_types: list[str] = Field(default_factory=list)
    start_year: int | None = None
    end_year: int | None = None
    fields: list[str] | None = None
    years: list[int] | None = None
    dry_run: bool = False
    only_unseen: bool = True
    force: bool = False
    include_mapping_repairs: bool = True


class FundamentalProviderStatusItemOut(BaseModel):
    provider: str
    configured: bool
    key_count: int = 0
    model: str | None = None
    base_url: str | None = None
    note: str | None = None


class FundamentalProviderStatusOut(BaseModel):
    llm: FundamentalProviderStatusItemOut
    bvc: dict[str, Any] = Field(default_factory=dict)


class TargetedBvcFundamentalTargetOut(BaseModel):
    symbol: str
    display_name: str | None = None
    market_region: str | None = None
    reason: str
    missing_metrics: list[str] = Field(default_factory=list)
    has_snapshot: bool = False
    has_annual: bool = False


class TargetedBvcFundamentalImportQueuedOut(BaseModel):
    batch_id: str
    import_id: str | None = None
    selected_count: int
    rq_job_id: str | None = None
    dry_run: bool = False
    source_url_count: int = 0
    sectors: list[str] = Field(default_factory=list)
    period_types: list[str] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)
    targets: list[TargetedBvcFundamentalTargetOut] = Field(default_factory=list)


class FundamentalSourceDocumentOut(BaseModel):
    id: int
    import_id: str
    symbol: str | None = None
    company_name: str | None = None
    document_title: str | None = None
    source_url: str
    publication_date: str | None = None
    fiscal_year: int | None = None
    period_type: str | None = None
    period_label: str | None = None
    period_end_date: str | None = None
    status: str
    error_message: str | None = None
    extracted_field_count: int = 0
    created_at: str | None = None


class FundamentalCoverageRow(BaseModel):
    symbol: str
    display_name: str | None = None
    sector: str | None = None
    market_region: str | None = None
    has_snapshot: bool
    has_annual: bool
    latest_statement_year: int | None = None
    latest_metric_count: int = 0
    annual_metric_count: int = 0
    annual_year_count: int = 0
    annual_years: list[int] = Field(default_factory=list)
    period_metric_count: int = 0
    period_types: list[str] = Field(default_factory=list)
    available_periods: list[str] = Field(default_factory=list)
    current_price: float | None = None
    shares_outstanding: float | None = None
    market_cap: float | None = None
    price_as_of: str | None = None
    price_source: str | None = None
    price_source_provider: str | None = None
    data_source: str | None = None
    source_universe: str | None = None
    last_imported_at: str | None = None
    quality_issue_count: int = 0
    missing_metrics: list[str] = Field(default_factory=list)
    status: str | None = None


class FundamentalSnapshotBatchIn(BaseModel):
    symbols: list[str]


class FundamentalLightSnapshot(BaseModel):
    symbol: str
    overall_score: float | None = None
    value_score: float | None = None
    quality_score: float | None = None
    growth_score: float | None = None
    risk_score: float | None = None
    cash_flow_score: float | None = None
    health_score: float | None = None
    fair_value: float | None = None
    upside_pct: float | None = None
    confidence: str | None = None
    confidence_score: float | None = None
    coverage_pct: float | None = None
    data_source: str | None = None
    currency: str | None = None
    as_of: str | None = None
    metrics: dict[str, float | None] = Field(default_factory=dict)
