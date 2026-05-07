"""Pydantic schemas for the strategy plan API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------

class UniverseFilterRequest(BaseModel):
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D", min_length=1)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)
    min_bars: int = Field(default=252, ge=0)
    min_abs_signal: float = Field(default=0.0, ge=0, le=100)
    min_adv20: float = Field(default=0.0, ge=0)
    sector_filter: list[str] | None = None
    sort_by: str = Field(default="adv20", pattern=r"^(adv20|signal_score)$")
    sort_dir: str = Field(default="desc", pattern=r"^(asc|desc)$")


class UniverseStockOut(BaseModel):
    symbol: str
    display_name: str | None = None
    sector: str | None = None
    market_cap_class: str | None = None
    row_count: int | None = None
    data_as_of: str | None = None
    adv20: float | None = None
    signal_score: float | None = None
    signal_label: str | None = None
    per_family: dict[str, Any] | None = None
    eligible: bool
    exclusion_reason: str | None = None


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------

class StrategyAllocationRequest(BaseModel):
    symbols: list[str] = []
    total_capital_mad: float = Field(default=1_000_000, ge=0)
    method: str = Field(default="hrp", pattern=r"^(hrp)$")
    timeframe: str = Field(default="1D", min_length=1)
    lookback_bars: int = Field(default=252, ge=20, le=2000)
    manual_overrides_by_symbol: dict[str, float] = Field(default_factory=dict)


class StrategyAllocationRowOut(BaseModel):
    symbol: str
    source: str = "hrp"
    hrp_weight_pct: float = 0.0
    weight_pct: float = 0.0
    capital_mad: float = 0.0


class StrategyAllocationOut(BaseModel):
    rows: list[StrategyAllocationRowOut] = []
    total_capital_mad: float = 0.0
    allocated_capital_mad: float = 0.0
    remaining_capital_mad: float = 0.0
    explain: str = ""


# ---------------------------------------------------------------------------
# Levels (S/R + ATR + Pivots)
# ---------------------------------------------------------------------------

class LevelsRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D", min_length=1)
    execution_holding_bars: int | None = Field(default=None, ge=2, le=252)
    left_bars: int | None = Field(default=None, ge=2, le=30)
    right_bars: int | None = Field(default=None, ge=2, le=30)
    lookback: int | None = Field(default=None, ge=20, le=500)
    max_levels: int | None = Field(default=None, ge=1, le=20)


class SRLevel(BaseModel):
    price: float
    bar_index: int
    date: str | None = None
    strength: int = 0


class PivotPoints(BaseModel):
    pp: float
    s1: float
    s2: float
    r1: float
    r2: float


class LevelsOut(BaseModel):
    symbol: str
    current_close: float
    atr_14: float | None = None
    atr_pct: float | None = None
    supports: list[SRLevel] = []
    resistances: list[SRLevel] = []
    nearest_support: float | None = None
    nearest_resistance: float | None = None
    pivot: PivotPoints | None = None
    explain: str = ""


# ---------------------------------------------------------------------------
# Saved Strategy CRUD
# ---------------------------------------------------------------------------

class SavedStrategyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    note: str | None = None
    side_policy: str = Field(default="long_only", pattern=r"^(long_only|long_short)$")
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")


class SavedStrategyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = None
    side_policy: str | None = Field(default=None, pattern=r"^(long_only|long_short)$")
    horizon: str | None = Field(default=None, pattern=r"^(short|medium|long)$")
    config_json: dict[str, Any] | None = None
    status: str | None = Field(default=None, pattern=r"^(draft|modified|saved)$")


class SavedStrategyOut(BaseModel):
    id: str
    name: str
    note: str | None = None
    status: str
    side_policy: str
    horizon: str
    config_json: dict[str, Any] = {}
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class SavedStrategyListItem(BaseModel):
    id: str
    name: str
    status: str
    side_policy: str
    horizon: str
    basket_count: int = 0
    updated_at: str

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Direct Strategy Backtest
# ---------------------------------------------------------------------------


class BacktestCostModelIn(BaseModel):
    brokerage_bps: float = Field(default=0.2, ge=0)
    comm_bourse_bps: float = Field(default=0.1, ge=0)
    reg_liv_bps: float = Field(default=0.0, ge=0)
    slippage_bps: float = Field(default=0.0, ge=0)
    tva_rate: float = Field(default=0.1, ge=0)


class BacktestVolumeGateIn(BaseModel):
    enabled: bool = False
    kind: str = Field(default="min_ratio_adv", pattern=r"^(min_abs|min_ratio_adv)$")
    min_volume_abs: float = Field(default=0.0, ge=0)
    min_volume_ratio_adv: float = Field(default=0.0, ge=0)
    adv_window: int = Field(default=20, ge=1, le=252)


class StrategyBacktestRequest(BaseModel):
    strategy_id: str = Field(..., min_length=1)
    start_date: str = Field(..., min_length=1)
    end_date: str = Field(..., min_length=1)
    timeframe: str = Field(default="1D", min_length=1)
    cost_model: BacktestCostModelIn = Field(default_factory=BacktestCostModelIn)
    volume_gate: BacktestVolumeGateIn = Field(default_factory=BacktestVolumeGateIn)
    cooldown_bars: int = Field(default=0, ge=0, le=252)
    family_history_mode: str = Field(default="static_current_reps", pattern=r"^(static_current_reps|dynamic_point_in_time)$")


class MetricValueRow(BaseModel):
    metric: str
    value: Any


class StrategyBacktestCalibrationBucketRow(BaseModel):
    score_low: float
    score_high: float
    n_observations: int
    avg_r_multiple: float
    avg_net_return: float
    win_rate: float
    target_exposure_pct: int


class StrategyBacktestCalibration(BaseModel):
    status: str = "fallback"
    lookback_bars: int = 0
    window_start: str | None = None
    window_end: str | None = None
    n_observations: int = 0
    primary_metric: str = "avg_r_multiple"
    bucket_rows: list[StrategyBacktestCalibrationBucketRow] = Field(default_factory=list)
    ladder: list[dict[str, Any]] = Field(default_factory=list)
    plot: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class StrategyBacktestAllocationRow(BaseModel):
    symbol: str
    source: str = "hrp"
    hrp_weight_pct: float = 0.0
    weight_pct: float = 0.0
    capital_mad: float = 0.0


class StrategyBacktestGeneralResults(BaseModel):
    metrics: dict[str, Any] = Field(default_factory=dict)
    trade_performance: list[MetricValueRow] = Field(default_factory=list)
    calibration: StrategyBacktestCalibration = Field(default_factory=StrategyBacktestCalibration)
    plots: dict[str, Any] = Field(default_factory=dict)


class StrategyBacktestStockResults(BaseModel):
    symbol: str
    allocation: dict[str, Any] = Field(default_factory=dict)
    summary_metrics: dict[str, Any] = Field(default_factory=dict)
    price_chart: dict[str, Any] = Field(default_factory=dict)
    trade_ledger: list[dict[str, Any]] = Field(default_factory=list)
    trade_performance: list[MetricValueRow] = Field(default_factory=list)


class StrategyBacktestResponse(BaseModel):
    strategy: dict[str, Any] = Field(default_factory=dict)
    assumptions: dict[str, Any] = Field(default_factory=dict)
    general_results: StrategyBacktestGeneralResults = Field(default_factory=StrategyBacktestGeneralResults)
    stocks: list[StrategyBacktestStockResults] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Strategy V2 Review / Handoff
# ---------------------------------------------------------------------------


class ReviewRequest(BaseModel):
    config_json: dict[str, Any] = Field(default_factory=dict)
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")


class ReviewStockReadiness(BaseModel):
    symbol: str
    has_signal: bool = False
    has_entry_rules: bool = False
    has_exit_rules: bool = False
    has_risk: bool = False
    wfo_param_count: int = 0
    ready: bool = False
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)


class ReviewOut(BaseModel):
    total_wfo_param_count: int = 0
    wfo_param_severity: str = "ok"
    pardo_df_ok: bool = True
    pardo_df_message: str = ""
    stocks: list[ReviewStockReadiness] = Field(default_factory=list)
    global_warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    ready: bool = False


class WFOParamManifestEntry(BaseModel):
    stock: str
    section: str
    param_path: str
    scan_min: float
    scan_max: float
    scan_step: float


class WFOParamManifestOut(BaseModel):
    params: list[WFOParamManifestEntry] = Field(default_factory=list)


class HandoffOut(BaseModel):
    strategy_id: str
    strategy_name: str
    portfolio: dict[str, Any] = Field(default_factory=dict)
    stocks: dict[str, Any] = Field(default_factory=dict)
    wfo_params: WFOParamManifestOut = Field(default_factory=WFOParamManifestOut)
    total_wfo_param_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    ready: bool = False
    blocking_issues: list[str] = Field(default_factory=list)
    schema_version: int = 3
    app_domain: str = "four_pages"


class SignalConstructionPreviewRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D", min_length=1)
    stock_config: dict[str, Any] = Field(default_factory=dict)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)
    family_history_mode: str = Field(default="static_current_reps", pattern=r"^(static_current_reps|dynamic_point_in_time)$")


class ActiveScoreChipOut(BaseModel):
    score_key: str
    label: str
    family: str
    source_kind: str
    score: float | None = None
    signal_label: str | None = None


class SignalConstructionPreviewOut(BaseModel):
    active_scores: list[ActiveScoreChipOut] = Field(default_factory=list)
    score_snapshot: dict[str, float | None] = Field(default_factory=dict)
    variable_catalog: list[dict[str, str]] = Field(default_factory=list)
    zone_chart: dict[str, Any] = Field(default_factory=dict)
    explain: str = ""


class RulePreviewRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D", min_length=1)
    stock_config: dict[str, Any] = Field(default_factory=dict)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)


class RulePreviewRow(BaseModel):
    id: str
    label: str
    config_option: str = "A"
    condition_count: int = 0
    triggered: bool = False
    conditions: list[str] = Field(default_factory=list)


class RulePreviewOut(BaseModel):
    symbol: str
    score_snapshot: dict[str, float | None] = Field(default_factory=dict)
    rules: list[RulePreviewRow] = Field(default_factory=list)
    explain: str = ""


class RiskPreviewRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D", min_length=1)
    stock_config: dict[str, Any] = Field(default_factory=dict)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)


class RiskPreviewOut(BaseModel):
    symbol: str
    current_close: float | None = None
    atr_14: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    rr_ratio: float | None = None
    cooldown_bars: int = 0
    time_stop_bars: int | None = None
    explain: str = ""


# ---------------------------------------------------------------------------
# Signal Consensus
# ---------------------------------------------------------------------------

class SignalConsensusRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    enabled_families: list[str] = Field(default=["sma", "rsi", "macd", "obv"])
    timeframe: str = Field(default="1D", min_length=1)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)


class FamilyScoreOut(BaseModel):
    score_pct: float
    label: str
    weight: float


class SignalConsensusOut(BaseModel):
    symbol: str
    final_consensus: float | None = None
    final_consensus_label: str | None = None
    enabled_families: list[str] = []
    family_weights: dict[str, float] = {}
    per_family: dict[str, FamilyScoreOut] = {}
    explain: str = ""


# ---------------------------------------------------------------------------
# Execution Plan
# ---------------------------------------------------------------------------

class ExecutionRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D", min_length=1)
    enabled_families: list[str] = Field(default=["sma", "rsi", "macd", "obv"])
    execution_holding_bars: int | None = Field(default=None, ge=2, le=252)
    side_policy: str = Field(default="long_only", pattern=r"^(long_only|long_short)$")
    entry_threshold: float = Field(default=20.0, ge=0, le=100)
    atr_multiplier: float = Field(default=1.5, ge=0.1, le=10.0)
    buffer_pct: float = Field(default=0.005, ge=0, le=0.1)
    min_rr: float = Field(default=1.5, ge=0.1, le=20.0)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)
    consensus_override: float | None = None


class ExecutionPlanOut(BaseModel):
    symbol: str
    direction: str | None = None
    status: str = "no_setup"
    entry_price: float | None = None
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    stop_loss: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    rr_ratio: float | None = None
    atr_14: float | None = None
    adjusted_consensus: float | None = None
    explain: str = ""


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------

class StockSizingInput(BaseModel):
    symbol: str
    entry_price: float = Field(ge=0)
    stop_price: float = Field(ge=0)
    atr_pct: float = Field(default=0.0, ge=0)
    consensus: float = Field(default=0.0)
    sector: str = Field(default="Other")
    status: str = Field(default="no_setup")


class SizingRequest(BaseModel):
    stocks: list[StockSizingInput] = []
    account_equity: float = Field(default=1_000_000, ge=0)
    kelly_modifier: float = Field(default=0.5, ge=0, le=1.0)
    allocation_method: str = Field(
        default="equal_weight",
        pattern=r"^(equal_weight|inverse_volatility|signal_weighted)$",
    )
    max_position_pct: float = Field(default=20.0, ge=1, le=100)
    max_sector_pct: float = Field(default=40.0, ge=1, le=100)
    win_rate: float = Field(default=0.55, ge=0.01, le=0.99)
    avg_wl_ratio: float = Field(default=1.5, ge=0.01)
    # Optional: focused stock for individual Kelly display
    focused_symbol: str | None = None


class StockSizingRow(BaseModel):
    symbol: str
    weight_pct: float = 0.0
    shares: int = 0
    position_value: float = 0.0
    trade_risk: float = 0.0
    status: str = "no_setup"


class FocusedKellyOut(BaseModel):
    full_kelly_pct: float = 0.0
    modified_kelly_pct: float = 0.0
    position_size_shares: int = 0
    position_value: float = 0.0
    trade_risk: float = 0.0
    pct_of_account_risked: float = 0.0


class SizingOut(BaseModel):
    focused_kelly: FocusedKellyOut | None = None
    portfolio_table: list[StockSizingRow] = []
    total_exposure_pct: float = 0.0
    total_risk_pct: float = 0.0
    capital_deployed: float = 0.0
    explain: str = ""
