from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SmaBucketIn(BaseModel):
    bucket_id: str
    low: int
    high: int


class SmaDiscoveryScoreSettingsIn(BaseModel):
    drawdown_weight: float = 0.5
    turnover_weight: float = 0.1
    mode_threshold: float = 0.20


class SmaDiscoverySignalParamsIn(BaseModel):
    buy_threshold_perc: float = 0.0
    sell_threshold_perc: float = 0.0
    cooldown_days: int = 0
    min_volume: float = 0.0


class SmaDiscoveryWalkForwardIn(BaseModel):
    train_window: int | None = None
    step_size: int | None = None
    use_test_window: bool | None = None
    test_window: int | None = None
    enforce_feasible_train_half: bool = True
    override_feasible_max_n: int | None = None


class SmaDiscoveryRequest(BaseModel):
    strategy_name: str = "sma_price"
    ticker: str | None = None
    dataset_id: UUID | None = None
    timeframe: str = "1D"
    start_date: str | None = None
    end_date: str | None = None
    horizon: str | None = None
    horizon_overrides: dict[str, Any] = Field(default_factory=dict)
    compute_all_horizons: bool = True

    walk_forward: SmaDiscoveryWalkForwardIn = Field(default_factory=SmaDiscoveryWalkForwardIn)
    buckets: list[SmaBucketIn] = Field(default_factory=list)
    score_settings: SmaDiscoveryScoreSettingsIn = Field(default_factory=SmaDiscoveryScoreSettingsIn)

    signal_params: SmaDiscoverySignalParamsIn = Field(default_factory=SmaDiscoverySignalParamsIn)
    use_net_after_costs: bool = False
    snap_to_nice: bool = True
    allow_short: bool = False
    signal_mode: str = "level"
    cost_model: dict[str, Any] = Field(default_factory=dict)


class DefaultsDiscoveryLaunchResponse(BaseModel):
    run_id: UUID
    status: str
    job_id: str | None = None


class DefaultsDiscoveryRunOut(BaseModel):
    run_id: UUID
    strategy_name: str
    status: str
    ticker: str | None = None
    dataset_id: UUID | None = None
    created_at: datetime
    finished_at: datetime | None = None
    params_json: dict[str, Any] = Field(default_factory=dict)
    results_json: dict[str, Any] | None = None
    artifacts_json: dict[str, Any] = Field(default_factory=dict)
    progress_pct: float | None = None
    progress_stage: str | None = None
    progress_message: str | None = None
    last_heartbeat_at: datetime | None = None
    rq_job_id: str | None = None
    error_message: str | None = None


class StrategyDefaultSetOut(BaseModel):
    id: int
    strategy_name: str
    source_run_id: UUID | None = None
    defaults_json: dict[str, Any] = Field(default_factory=dict)
    meta_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
