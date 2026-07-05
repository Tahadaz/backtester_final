from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


DashboardEdgeSource = Literal["signal_engine", "wfo", "auto", "sfc"]
DashboardSidePolicy = Literal["long_only", "long_short"]
DashboardPriceSource = Literal["official_close", "live_if_fresh"]
DashboardEffectivePriceSource = Literal["official_close", "live"]
DashboardTradeAction = Literal["BUY", "SELL", "SELL_SHORT", "COVER"]
DashboardPortfolioAllocationMethod = Literal["share_quantities", "hrp"]
DashboardPortfolioDisplayMode = Literal["trade_opportunities", "technical_directions"]
DashboardPortfolioTechnicalDirectionMode = Literal["best", "classic"]


class DashboardPortfolioTicketRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list, min_length=1, max_length=25)
    horizon: str = Field(default="monthly")
    source: DashboardEdgeSource = "signal_engine"
    side_policy: DashboardSidePolicy = "long_only"
    total_capital_mad: float = Field(default=1_000_000.0, gt=0)
    cash_buffer_pct: float = Field(default=10.0, ge=0.0, le=95.0)
    max_position_pct: float = Field(default=20.0, ge=1.0, le=100.0)
    max_sector_pct: float = Field(default=40.0, ge=1.0, le=100.0)
    adv_participation_pct: float = Field(default=5.0, ge=0.0, le=100.0)
    kelly_fraction: float = Field(default=0.25, ge=0.0, le=1.0)
    require_proven_edge: bool = False
    timeframe: str = Field(default="1D", min_length=1)
    lookback_bars: int = Field(default=252, ge=20, le=2000)
    entry_threshold: float = Field(default=20.0, ge=0.0, le=100.0)
    atr_multiplier: float = Field(default=1.5, ge=0.1, le=10.0)
    buffer_pct: float = Field(default=0.005, ge=0.0, le=0.1)
    min_rr: float = Field(default=1.5, ge=0.1, le=20.0)
    price_source: DashboardPriceSource = "live_if_fresh"
    max_live_quote_age_seconds: int = Field(default=60, ge=0, le=3600)


class DashboardPortfolioTicketRow(BaseModel):
    symbol: str
    display_name: str | None = None
    sector: str | None = None
    direction: str | None = None
    action: str
    status: str
    signal_bucket: str | None = None
    signal_score: float | None = None
    proven_edge: bool = False
    holding_period_bars: int | None = None
    return_calc_method: str | None = None
    action_expected_return_net: float | None = None
    stock_expected_return: float | None = None
    allocation_eligible: bool = False
    allocation_reason: str | None = None
    base_hrp_weight_pct: float = 0.0
    final_weight_pct: float = 0.0
    size_mad: float = 0.0
    shares: int = 0
    entry_timing: str = "next_open"
    entry_reference_price_type: str = "last_close_proxy"
    price_source: DashboardEffectivePriceSource = "official_close"
    live_quote_age_seconds: float | None = None
    execution_condition: str = "execute_next_open_only_if_open_remains_in_entry_zone"
    entry_reference_price: float | None = None
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    stop_loss: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    rr_ratio: float | None = None
    atr_14: float | None = None
    adv20: float | None = None
    max_liquidity_size_mad: float | None = None
    execution_explain: str | None = None
    warnings: list[str] = Field(default_factory=list)
    proof_url: str


class DashboardPortfolioTicketSummary(BaseModel):
    horizon: str
    source: DashboardEdgeSource
    side_policy: DashboardSidePolicy
    entry_timing: str = "next_open"
    total_capital_mad: float
    deployable_capital_mad: float
    allocated_capital_mad: float
    cash_buffer_mad: float
    expected_action_return_mad: float | None = None
    expected_action_return_pct: float | None = None
    selected_count: int
    allocated_count: int = 0
    tradable_count: int


class DashboardPortfolioTicketResponse(BaseModel):
    summary: DashboardPortfolioTicketSummary
    rows: list[DashboardPortfolioTicketRow]


DashboardPositionSide = Literal["long", "short"]
DashboardBlotterAction = Literal[
    "BUY",
    "SELL_SHORT",
    "HOLD",
    "REDUCE",
    "COVER",
    "EXIT",
    "AVOID",
    "WATCH",
    "REVIEW",
]


class DashboardManualPosition(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: DashboardPositionSide = "long"
    quantity: float = Field(ge=0.0)
    average_price_mad: float | None = Field(default=None, gt=0.0)
    opened_at: date | None = None
    planned_holding_bars: int | None = Field(default=None, ge=1, le=500)
    stop_loss: float | None = Field(default=None, gt=0.0)
    target_1: float | None = Field(default=None, gt=0.0)
    notes: str | None = Field(default=None, max_length=500)


class DashboardPortfolioPositionsRequest(BaseModel):
    positions: list[DashboardManualPosition] = Field(default_factory=list, max_length=200)


class DashboardPortfolioPositionsResponse(BaseModel):
    positions: list[DashboardManualPosition]


class DashboardDailyBlotterRequest(DashboardPortfolioTicketRequest):
    symbols: list[str] = Field(default_factory=list, max_length=50)
    positions: list[DashboardManualPosition] | None = Field(default=None, max_length=200)


class DashboardDailyBlotterRow(DashboardPortfolioTicketRow):
    blotter_action: DashboardBlotterAction
    current_side: DashboardPositionSide | None = None
    current_quantity: float = 0.0
    current_average_price_mad: float | None = None
    current_market_value_mad: float | None = None
    current_unrealized_pnl_mad: float | None = None
    target_quantity: int = 0
    delta_quantity: int = 0
    delta_notional_mad: float = 0.0
    valid_for_session: str = "next_open"
    no_trade_reasons: list[str] = Field(default_factory=list)
    execution_notes: str


class DashboardDailyBlotterSummary(BaseModel):
    horizon: str
    source: DashboardEdgeSource
    side_policy: DashboardSidePolicy
    entry_timing: str = "next_open"
    selected_count: int
    position_count: int
    actionable_count: int
    buy_count: int
    exit_count: int
    watch_count: int
    total_delta_notional_mad: float
    generated_for: str = "next_session"


class DashboardDailyBlotterResponse(BaseModel):
    summary: DashboardDailyBlotterSummary
    ticket: DashboardPortfolioTicketResponse
    rows: list[DashboardDailyBlotterRow]


class DashboardPortfolioTradeIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    action: DashboardTradeAction
    quantity: float = Field(gt=0.0)
    price_mad: float = Field(gt=0.0)
    timestamp: date | None = None
    fees_mad: float = Field(default=0.0, ge=0.0)
    notes: str | None = Field(default=None, max_length=500)


class DashboardPortfolioComponent(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    shares: int = Field(default=1, ge=1)
    enabled: bool = True


class DashboardPortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    symbols: list[str] = Field(default_factory=list, max_length=100)
    components: list[DashboardPortfolioComponent] | None = Field(default=None, max_length=100)
    component_shares: dict[str, int] = Field(default_factory=dict)
    allocation_method: DashboardPortfolioAllocationMethod = "share_quantities"
    side_policy: DashboardSidePolicy = "long_only"
    total_capital_mad: float = Field(default=1_000_000.0, gt=0.0)
    cash_buffer_pct: float = Field(default=0.0, ge=0.0, le=95.0)
    stop_loss_pct: float | None = Field(default=None, gt=0.0, le=95.0)
    take_profit_pct: float | None = Field(default=None, gt=0.0, le=1000.0)
    display_mode: DashboardPortfolioDisplayMode = "trade_opportunities"
    technical_direction_mode: DashboardPortfolioTechnicalDirectionMode = "best"
    horizon: str = "monthly"


class DashboardPortfolioUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    symbols: list[str] | None = Field(default=None, max_length=100)
    components: list[DashboardPortfolioComponent] | None = Field(default=None, max_length=100)
    component_shares: dict[str, int] | None = None
    allocation_method: DashboardPortfolioAllocationMethod | None = None
    side_policy: DashboardSidePolicy | None = None
    total_capital_mad: float | None = Field(default=None, gt=0.0)
    cash_buffer_pct: float | None = Field(default=None, ge=0.0, le=95.0)
    stop_loss_pct: float | None = Field(default=None, gt=0.0, le=95.0)
    take_profit_pct: float | None = Field(default=None, gt=0.0, le=1000.0)
    display_mode: DashboardPortfolioDisplayMode | None = None
    technical_direction_mode: DashboardPortfolioTechnicalDirectionMode | None = None
    horizon: str | None = None


class DashboardPortfolioOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    symbols: list[str] = Field(default_factory=list)
    component_shares: dict[str, int] = Field(default_factory=dict)
    components: list[DashboardPortfolioComponent] = Field(default_factory=list)
    allocation_method: DashboardPortfolioAllocationMethod = "share_quantities"
    side_policy: DashboardSidePolicy = "long_only"
    total_capital_mad: float = 1_000_000.0
    cash_buffer_pct: float = 0.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    display_mode: DashboardPortfolioDisplayMode = "trade_opportunities"
    technical_direction_mode: DashboardPortfolioTechnicalDirectionMode = "best"
    horizon: str = "monthly"
    is_default: bool = False
    replay_start_date: date | None = None
    replay_end_date: date | None = None
    replay_generated_at: datetime | None = None
    last_replay: dict = Field(default_factory=dict)
    summary: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DashboardPortfolioListResponse(BaseModel):
    portfolios: list[DashboardPortfolioOut] = Field(default_factory=list)


class DashboardPortfolioReplayRequest(BaseModel):
    start_date: date
    end_date: date
    symbols: list[str] = Field(default_factory=list, max_length=100)
    components: list[DashboardPortfolioComponent] | None = Field(default=None, max_length=100)
    component_shares: dict[str, int] = Field(default_factory=dict)
    allocation_method: DashboardPortfolioAllocationMethod = "share_quantities"
    side_policy: DashboardSidePolicy = "long_only"
    total_capital_mad: float = Field(default=1_000_000.0, gt=0.0)
    cash_buffer_pct: float = Field(default=0.0, ge=0.0, le=95.0)
    stop_loss_pct: float | None = Field(default=None, gt=0.0, le=95.0)
    take_profit_pct: float | None = Field(default=None, gt=0.0, le=1000.0)
    display_mode: DashboardPortfolioDisplayMode = "trade_opportunities"
    technical_direction_mode: DashboardPortfolioTechnicalDirectionMode = "best"
    horizon: str = "monthly"
    persist: bool = True


class DashboardPortfolioFromHistoryRequest(DashboardPortfolioCreate):
    start_date: date
    end_date: date


class DashboardPortfolioReplayResponse(BaseModel):
    portfolio: DashboardPortfolioOut
    summary: dict[str, Any] = Field(default_factory=dict)
    replay: dict = Field(default_factory=dict)


class DashboardPortfolioBacktestRunResponse(BaseModel):
    strategy_id: str
    run_id: str
    status: str
    mode: str = "portfolio_replay"
    title: str


class DashboardPortfolioTradeOut(BaseModel):
    id: str
    symbol: str
    action: DashboardTradeAction
    quantity: float
    price_mad: float
    timestamp: date | None = None
    fees_mad: float = 0.0
    realized_pnl_mad: float = 0.0
    notes: str | None = None


class DashboardPortfolioPositionMarkOut(BaseModel):
    symbol: str
    side: DashboardPositionSide
    quantity: float
    cmp_mad: float | None = None
    mark_price_mad: float | None = None
    mark_source: str = "official_close"
    market_value_mad: float | None = None
    unrealized_pnl_mad: float | None = None
    realized_pnl_mad: float = 0.0
    updated_at: datetime | None = None
    live_quote_age_seconds: float | None = None


class DashboardPortfolioSummaryOut(BaseModel):
    positions: list[DashboardPortfolioPositionMarkOut] = Field(default_factory=list)
    trades: list[DashboardPortfolioTradeOut] = Field(default_factory=list)
    total_market_value_mad: float = 0.0
    total_unrealized_pnl_mad: float = 0.0
    total_realized_pnl_mad: float = 0.0
