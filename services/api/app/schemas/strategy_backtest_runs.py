from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, Field

from .strategy import BacktestCostModelIn, BacktestVolumeGateIn


class StrategyBacktestRunWfoConfig(BaseModel):
    window_policy: Literal["strict_fold_driven", "legacy_ratio_scan"] = "strict_fold_driven"
    top_k_folds: int = Field(default=12, ge=1, le=50)
    strict_fallback_enabled: bool = True
    strict_fallback_floor: int = Field(default=1, ge=1, le=50)
    is_oos_ratios: list[float] = Field(default_factory=lambda: [0.25, 0.30, 0.35])
    min_walk_forwards: int = Field(default=5, ge=1, le=50)
    test_period_start: str | None = None
    test_period_end: str | None = None
    n_monte_carlo_paths: int = Field(default=1000, ge=100, le=5000)
    monte_carlo_block_length: int | None = Field(default=None, ge=1, le=252)


class StrategyBacktestRunCreateRequest(BaseModel):
    strategy_id: str = Field(..., min_length=1)
    mode: str = Field(default="direct", pattern=r"^(direct|wfo|portfolio_replay)$")
    start_date: str | None = None
    end_date: str | None = None
    timeframe: str = Field(default="1D", min_length=1)
    cost_model: BacktestCostModelIn = Field(default_factory=BacktestCostModelIn)
    volume_gate: BacktestVolumeGateIn = Field(default_factory=BacktestVolumeGateIn)
    cooldown_bars: int = Field(default=0, ge=0, le=252)
    family_history_mode: str = Field(default="static_current_reps", pattern=r"^(static_current_reps|dynamic_point_in_time)$")
    wfo_config: StrategyBacktestRunWfoConfig | None = None


class StrategyBacktestRunCreateResponse(BaseModel):
    run_id: str
    status: str
    mode: str
    title: str
    reused: bool = False


class StrategyBacktestRunListItemOut(BaseModel):
    run_id: str
    title: str
    strategy_id: str
    strategy_name: str
    mode: str
    status: str
    horizon: str
    start_date: str | None = None
    end_date: str | None = None
    basket_count: int = 0
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    completed_at: str | None = None


class StrategyBacktestRunUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class StrategyBacktestStockSummaryOut(BaseModel):
    symbol: str
    status: str = "queued"
    summary: dict[str, Any] = Field(default_factory=dict)
    error_text: str | None = None


class StrategyBacktestRunOut(BaseModel):
    run_id: str
    title: str
    strategy_id: str
    strategy_name: str
    mode: str
    status: str
    horizon: str
    strategy_snapshot: dict[str, Any] = Field(default_factory=dict)
    data_snapshot: dict[str, Any] = Field(default_factory=dict)
    request: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    progress: dict[str, Any] = Field(default_factory=dict)
    stocks: list[StrategyBacktestStockSummaryOut] = Field(default_factory=list)
    error_text: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None


class StrategyBacktestStockDetailOut(BaseModel):
    run_id: str
    symbol: str
    status: str
    summary: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error_text: str | None = None


class StrategyBacktestWindowDetailOut(BaseModel):
    run_id: str
    symbol: str
    window_index: int
    summary: dict[str, Any] = Field(default_factory=dict)
    detail: dict[str, Any] = Field(default_factory=dict)
