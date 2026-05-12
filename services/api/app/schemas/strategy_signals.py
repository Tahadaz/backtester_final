"""Pydantic schemas for the strategy signals API."""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from core.quant_core.horizons import canonical_horizon
from core.quant_core.signal_engine.modes import accepted_signal_mode_pattern

SIGNAL_MODE_PATTERN = accepted_signal_mode_pattern()
BASE_SIGNAL_FAMILIES = (
    "sma|ema|ema_cross|ichimoku|psar|macd|roc|trix|adx|tsi|rsi|stochastic|cci|mfi|uo|obv|cmf|ad|vwap|fi"
)
COMBO_SIGNAL_FAMILIES = (
    "legacy_ta_combo_tendance|legacy_ta_combo_momentum|legacy_ta_combo_oscillation|legacy_ta_combo_volume|"
    "expanded_ta_combo_tendance|expanded_ta_combo_momentum|expanded_ta_combo_oscillation|expanded_ta_combo_volume|"
    "legacy_fx_combo_tendance|legacy_fx_combo_momentum|legacy_fx_combo_oscillation|legacy_fx_combo_volume|"
    "expanded_fx_combo_tendance|expanded_fx_combo_momentum|expanded_fx_combo_oscillation|expanded_fx_combo_volume"
)
SIGNAL_FAMILY_PATTERN = f"^({BASE_SIGNAL_FAMILIES}|{COMBO_SIGNAL_FAMILIES})$"


class StrategySignalRequestBase(BaseModel):
    @field_validator("horizon", mode="before", check_fields=False)
    @classmethod
    def _canonicalize_horizon(cls, value: Any) -> str:
        return canonical_horizon(str(value), allow_legacy=True)


class SmaEnsembleRequest(StrategySignalRequestBase):
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="monthly", pattern=r"^(weekly|monthly|quarterly)$")
    timeframe: str = Field(default="1D", min_length=1)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)


class FamilyEnsembleRequest(StrategySignalRequestBase):
    family: str = Field(..., pattern=SIGNAL_FAMILY_PATTERN)
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="monthly", pattern=r"^(weekly|monthly|quarterly)$")
    timeframe: str = Field(default="1D", min_length=1)
    variant: str = Field(default="expanded", pattern=SIGNAL_MODE_PATTERN)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)


class SupportResistanceRequest(StrategySignalRequestBase):
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="monthly", pattern=r"^(weekly|monthly|quarterly)$")
    timeframe: str = Field(default="1D", min_length=1)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)


class SupportResistanceMethodDetailRequest(SupportResistanceRequest):
    method_id: str = Field(
        ...,
        pattern=r"^(ma_anchor|score_inversion|swing_levels|pivot_points|quantile_extrema_atr)$",
    )


class SupportResistanceVariantRequest(SupportResistanceRequest):
    variant_id: str = Field(..., min_length=1)


class VariantDetailRequest(StrategySignalRequestBase):
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="monthly", pattern=r"^(weekly|monthly|quarterly)$")
    timeframe: str = Field(default="1D", min_length=1)
    variant: str = Field(default="expanded", pattern=SIGNAL_MODE_PATTERN)
    variant_id: str = Field(..., min_length=1)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)


class VariantBacktestRequest(StrategySignalRequestBase):
    symbol: str = Field(..., min_length=1)
    variant_id: str = Field(..., min_length=1)
    horizon: str = Field(default="monthly", pattern=r"^(weekly|monthly|quarterly)$")
    timeframe: str = Field(default="1D", min_length=1)
    variant: str = Field(default="expanded", pattern=SIGNAL_MODE_PATTERN)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)
    trade_cooldown_bars: int = Field(default=0, ge=0, le=252)
    mc_config: dict[str, Any] | None = None


class BatchScoresRequest(StrategySignalRequestBase):
    symbols: list[str] = Field(..., min_length=1)
    horizon: str = Field(default="monthly", pattern=r"^(weekly|monthly|quarterly)$")
    timeframe: str = Field(default="1D", min_length=1)
    variant: str = Field(default="expanded", pattern=SIGNAL_MODE_PATTERN)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)


class PersistedSignalEngineSummariesRequest(StrategySignalRequestBase):
    symbols: list[str] = Field(..., min_length=1)
    horizon: str = Field(default="monthly", pattern=r"^(weekly|monthly|quarterly)$")
    variant: str = Field(default="expanded", pattern=SIGNAL_MODE_PATTERN)
    timeframe: str = Field(default="1D", min_length=1)


class RegimeConsensusRequest(StrategySignalRequestBase):
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="monthly", pattern=r"^(weekly|monthly|quarterly)$")
    timeframe: str = Field(default="1D", min_length=1)
    variant: str = Field(default="expanded", pattern=SIGNAL_MODE_PATTERN)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)


class SignalZoneChartRequest(StrategySignalRequestBase):
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="monthly", pattern=r"^(weekly|monthly|quarterly)$")
    timeframe: str = Field(default="1D", min_length=1)
    enabled_families: list[str] = Field(default=["sma", "rsi", "macd", "obv"])
    variant: str = Field(default="expanded", pattern=SIGNAL_MODE_PATTERN)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)
    family_history_mode: str = Field(default="static_current_reps", pattern=r"^(static_current_reps|dynamic_point_in_time)$")


class IndicatorSeriesRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    indicator: str = Field(..., pattern=r"^(sma|ema|ema_cross|ichimoku|psar|macd|roc|trix|adx|tsi|rsi|stochastic|cci|mfi|uo|obv|cmf|ad|vwap|fi)$")
    params: dict[str, float] = Field(default_factory=dict)
    timeframe: str = Field(default="1D", pattern=r"^1D$")


class IndicatorSeriesResponse(BaseModel):
    symbol: str
    indicator: str
    params: dict[str, float]
    dates: list[str]
    close: list[float | None]
    indicator_values: list[float | None]
    indicator_overlay: list[float | None] | None = None
    current_score: float
    current_label: str
    atr: float | None = None


class SupportResistanceMethod(BaseModel):
    id: str
    label: str
    support: float | None = None
    resistance: float | None = None
    status: str = Field(default="unavailable", pattern=r"^(available|ignored|unavailable)$")
    selected_for_support: bool = False
    selected_for_resistance: bool = False
    explanation: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)


class SupportResistanceResponse(BaseModel):
    symbol: str
    horizon: str
    timeframe: str
    as_of: str
    current_close: float
    trend_score_pct: float | None = None
    trend_label: str
    methods: list[SupportResistanceMethod] = Field(default_factory=list)
    preview_support: float | None = None
    preview_resistance: float | None = None
    preview_support_method_id: str | None = None
    preview_resistance_method_id: str | None = None
    optimal_support: float | None = None
    optimal_resistance: float | None = None
    optimal_variant_id: str | None = None
    optimal_status: str = Field(default="pending", pattern=r"^(pending|ready|unavailable)$")
    final_support: float | None = None
    final_resistance: float | None = None
    selected_support_method_id: str | None = None
    selected_resistance_method_id: str | None = None
    summary_explanation: str = ""


class SupportResistanceChartBar(BaseModel):
    date: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None


class SupportResistanceChartIndicator(BaseModel):
    type: str = "overlay"
    plot_kind: str = "line"
    plot_axis: str = "price"
    plot_values: list[float | None] = Field(default_factory=list)


class SupportResistanceChartSource(BaseModel):
    label: str
    indicator: SupportResistanceChartIndicator


class SupportResistanceChart(BaseModel):
    bars: list[SupportResistanceChartBar] = Field(default_factory=list)
    sources: list[SupportResistanceChartSource] = Field(default_factory=list)


class SupportResistanceMethodDetailResponse(BaseModel):
    symbol: str
    horizon: str
    timeframe: str
    as_of: str
    current_close: float
    trend_score_pct: float | None = None
    trend_label: str
    method_id: str
    method: SupportResistanceMethod
    chart: SupportResistanceChart | None = None
    preview_support: float | None = None
    preview_resistance: float | None = None
    preview_support_method_id: str | None = None
    preview_resistance_method_id: str | None = None
    optimal_support: float | None = None
    optimal_resistance: float | None = None
    optimal_variant_id: str | None = None
    optimal_status: str = Field(default="pending", pattern=r"^(pending|ready|unavailable)$")
    final_support: float | None = None
    final_resistance: float | None = None
    selected_support_method_id: str | None = None
    selected_resistance_method_id: str | None = None
    summary_explanation: str = ""
