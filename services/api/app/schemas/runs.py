from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from .analytics import EdgeMetricsOut

class RunCreateRequest(BaseModel):
    spec_json: Dict[str, Any] = Field(..., description="Run specification JSON")
    spec_hash: str = Field(..., description="Stable hash of spec_json (from quant_core.run_spec)")
    dataset_id: Optional[UUID] = None


class RunCreateResponse(BaseModel):
    run_id: UUID
    status: str
    run_type: str


class WalkForwardResolveDatesRequest(BaseModel):
    spec_json: Dict[str, Any] = Field(..., description="Run specification JSON")
    dataset_id: Optional[UUID] = None


class WalkForwardResolveDatesResponse(BaseModel):
    requested_start_date: Optional[str] = None
    requested_end_date: Optional[str] = None
    resolved_start_date: str
    resolved_end_date: str
    end_date_policy: str
    alignment_notes: Dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class RunListItemOut(BaseModel):
    run_id: UUID
    status: str
    run_type: str
    mode: Optional[str] = None
    seed: Optional[int] = None
    dataset_hash: Optional[str] = None
    code_version: Optional[str] = None
    integrity_status: Optional[str] = None
    dataset_id: Optional[UUID]
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class RunIntegrityCheckOut(BaseModel):
    check_name: str
    status: str
    details_json: Dict[str, Any]
    created_at: datetime


class RunFoldOut(BaseModel):
    fold_index: int
    train_start: Optional[datetime] = None
    train_end: Optional[datetime] = None
    test_start: Optional[datetime] = None
    test_end: Optional[datetime] = None
    fold_metrics_json: Dict[str, Any] = Field(default_factory=dict)
    fold_artifacts: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class WfoPeriodOut(BaseModel):
    fold_no: int
    symbol: str = ""
    strategy_kind: str = ""
    horizon: Optional[str] = None
    train_start: Optional[datetime] = None
    train_end: Optional[datetime] = None
    test_start: datetime
    test_end: datetime
    winning_trial_id: str = ""
    optimal_params: Dict[str, Any] = Field(default_factory=dict)
    is_objective_name: Optional[str] = None
    is_objective_value: Optional[float] = None
    oos_pnl: Optional[float] = None
    oos_return: Optional[float] = None
    oos_cagr: Optional[float] = None
    oos_sharpe: Optional[float] = None
    oos_max_drawdown: Optional[float] = None
    oos_win_pct: Optional[float] = None
    oos_n_fills: Optional[int] = None
    cumulative_oos_pnl: Optional[float] = None
    is_holdout: bool = False


class StitchedOosSummary(BaseModel):
    total_oos_pnl: Optional[float] = None
    mean_oos_sharpe: Optional[float] = None
    median_oos_sharpe: Optional[float] = None
    worst_fold_drawdown: Optional[float] = None
    profitable_folds: int = 0
    total_folds: int = 0
    profitable_pct: Optional[float] = None


class ClassicalWfoReport(BaseModel):
    periods: list[WfoPeriodOut] = Field(default_factory=list)
    stitched_oos_summary: StitchedOosSummary = Field(default_factory=StitchedOosSummary)
    current_live_params: Optional[Dict[str, Any]] = None
    current_live_trial_id: Optional[str] = None
    final_holdout_summary: Optional[WfoPeriodOut] = None
    data_source: str = "run_wfo_period"


class RunSignificanceOut(BaseModel):
    method: str
    pvalue: Optional[float] = None
    statistic: Optional[float] = None
    mc_null_dist_ref: Optional[str] = None
    details_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RunRiskOut(BaseModel):
    kelly_fraction: Optional[float] = None
    half_kelly: Optional[float] = None
    chosen_leverage: Optional[float] = None
    mc_drawdown_pctl: Optional[float] = None
    mc_var: Optional[float] = None
    mc_cvar: Optional[float] = None
    details_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RunMetricOut(BaseModel):
    run_id: UUID
    symbol: str
    metric_name: str
    metric_value: float


class FillOut(BaseModel):
    id: UUID
    run_id: UUID
    timestamp: datetime
    symbol: str
    side: str
    qty: float
    price: float
    fees: float
    notional: float
    meta: Optional[Dict[str, Any]]


class PositionLedgerOut(BaseModel):
    id: UUID
    run_id: UUID
    timestamp: datetime
    symbol: str
    available_qty: float
    cmp: float
    position_value_cost: float
    pnl_realise: float
    pnl_latent: float
    mark_price: float


class StrategyLeaderboardOut(BaseModel):
    run_id: UUID
    symbol: str
    strategy_kind: str
    rank: int

    pnl: Optional[float]
    cagr: Optional[float]
    total_return: Optional[float]
    sharpe: Optional[float]
    max_drawdown: Optional[float]
    win_pct: Optional[float]
    efficiency: Optional[float]
    n_fills: Optional[int]

    confidence_score: Optional[float]
    opportunity_score: Optional[float]
    horizon: Optional[str]

    signal_label: Optional[str]
    signal_today: Optional[float]
    signal_date: Optional[datetime]

    best_params_json: Optional[Dict[str, Any]]
    plot_url: Optional[str]
    ledger_url: Optional[str]
    edge: Optional[EdgeMetricsOut] = None


class MaterializeStrategyDetailsRequest(BaseModel):
    symbol: str
    strategy_kind: str
    strategy_params: Optional[Dict[str, Any]] = None
    portfolio_overrides: Optional[Dict[str, Any]] = None


class MaterializeStrategyDetailsResponse(BaseModel):
    run_id: UUID
    symbol: str
    strategy_kind: str
    metrics: Dict[str, Any]
    trade_performance: list[Dict[str, Any]]
    trade_ledger: list[Dict[str, Any]]
    plots: Dict[str, Any]
    signal_label: Optional[str] = None
    signal_today: Optional[float] = None
    signal_date: Optional[datetime] = None


class DecisionLayerOut(BaseModel):
    score: float
    weight: float
    inputs: Dict[str, Any] = Field(default_factory=dict)
    thresholds: Dict[str, Any] = Field(default_factory=dict)
    explain: str = ""


class DecisionScoreOut(BaseModel):
    total: float = 0.0
    layers: Dict[str, DecisionLayerOut] = Field(default_factory=dict)


class DecisionLevelsOut(BaseModel):
    support: float | None = None
    resistance: float | None = None
    entry: float | None = None
    stop: float | None = None
    target: float | None = None


class DecisionRiskOut(BaseModel):
    rr: float = 0.0
    risk_per_share: float | None = None
    reward_per_share: float | None = None
    score: float = 0.0
    invalidation: str = ""


class DecisionPageOut(BaseModel):
    symbol: str
    strategy_kind: str
    trial_id: str
    direction: str
    status: str
    when_to_act: list[str] = Field(default_factory=list)
    levels: DecisionLevelsOut = Field(default_factory=DecisionLevelsOut)
    invalidation: str = ""
    risk: DecisionRiskOut = Field(default_factory=DecisionRiskOut)
    opportunity: DecisionScoreOut = Field(default_factory=DecisionScoreOut)
    confidence: DecisionScoreOut = Field(default_factory=DecisionScoreOut)
    opportunity_score: float
    confidence_score: float
    explain: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime | None = None


class StrategyDecisionOut(BaseModel):
    run_id: UUID
    symbol: str
    strategy_kind: str
    trial_id: str
    rank: int | None = None
    params_hash: str
    params_json: Dict[str, Any] = Field(default_factory=dict)
    opportunity_score: float
    confidence_score: float
    status: str
    opportunity_subscores: Dict[str, DecisionLayerOut] = Field(default_factory=dict)
    confidence_subscores: Dict[str, DecisionLayerOut] = Field(default_factory=dict)
    decision_page: DecisionPageOut
    explain: Dict[str, Any] = Field(default_factory=dict)
    computed_at: datetime


class DecisionDashboardParamOut(BaseModel):
    key: str
    value: Any = None
    description: str = ""
    impact: str = ""


class DecisionDashboardCheckOut(BaseModel):
    name: str
    expr: str = ""
    value: Any = None
    threshold: Any = None
    pass_: bool = Field(alias="pass")


class DecisionDashboardRuleOut(BaseModel):
    rule_name: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    checks: list[DecisionDashboardCheckOut] = Field(default_factory=list)
    final_direction: int = 0
    strategy_direction: int = 0
    final_direction_label: str = "neutral"


class DecisionDashboardTimeseriesMarkerOut(BaseModel):
    t: str
    value: float | None = None
    direction: int | None = None
    kind: str | None = None


class DecisionDashboardTimeseriesOut(BaseModel):
    t: list[str] = Field(default_factory=list)
    open: list[float | None] = Field(default_factory=list)
    high: list[float | None] = Field(default_factory=list)
    low: list[float | None] = Field(default_factory=list)
    close: list[float | None] = Field(default_factory=list)
    volume: list[float | None] = Field(default_factory=list)
    sma_ref: list[float | None] = Field(default_factory=list)
    sma100: list[float | None] = Field(default_factory=list)
    sma200: list[float | None] = Field(default_factory=list)
    rsi14: list[float | None] = Field(default_factory=list)
    adx: list[float | None] = Field(default_factory=list)
    atr: list[float | None] = Field(default_factory=list)
    signal_markers: list[DecisionDashboardTimeseriesMarkerOut] = Field(default_factory=list)
    cross_markers: list[DecisionDashboardTimeseriesMarkerOut] = Field(default_factory=list)


class DecisionDashboardOut(BaseModel):
    decision_summary: Dict[str, Any] = Field(default_factory=dict)
    strategy_params: list[DecisionDashboardParamOut] = Field(default_factory=list)
    derived_metrics: Dict[str, Any] = Field(default_factory=dict)
    regime: Dict[str, Any] = Field(default_factory=dict)
    signal_debug: DecisionDashboardRuleOut
    levels: Dict[str, Any] = Field(default_factory=dict)
    confidence_layers: list[Dict[str, Any]] = Field(default_factory=list)
    framework_comparison: Dict[str, Any] = Field(default_factory=dict)
    timeseries: DecisionDashboardTimeseriesOut
