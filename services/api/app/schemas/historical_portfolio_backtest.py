from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from core.quant_core.edge_policy import DEFAULT_EDGE_CONDITIONS, EDGE_CONDITIONS


class HistoricalPortfolioRunCreate(BaseModel):
    start_date: date
    end_date: date
    symbols: list[str] = Field(default_factory=list)
    horizons: list[Literal["weekly", "monthly", "quarterly"]] = Field(
        default_factory=lambda: ["weekly", "monthly", "quarterly"], min_length=1,
    )
    initial_capital: float = Field(100_000.0, gt=0)
    capacity_fraction: Literal[0.01, 0.025, 0.05, 0.1] = 0.01
    allow_partial_fills: bool = True
    cost_bps_per_side: float = Field(33.0, ge=0)
    slippage_bps_per_side: float = Field(5.0, ge=0)
    half_kelly_multiplier: float = Field(0.5, ge=0, le=1)
    max_position_fraction: float = Field(0.25, gt=0, le=1)
    bootstrap_seed: int = 5107
    bootstrap_samples: int = Field(1000, ge=100, le=10_000)
    min_edge_score: float = Field(50.0, ge=0, le=100)
    required_edge_conditions: list[str] = Field(default_factory=lambda: list(DEFAULT_EDGE_CONDITIONS))
    stop_loss_pct: float | None = Field(default=None, gt=0, lt=1)
    take_profit_pct: float | None = Field(default=None, gt=0, le=10)

    @model_validator(mode="before")
    @classmethod
    def reject_system_namespace(cls, value):
        if isinstance(value, dict) and "_system" in value:
            raise ValueError("_system is reserved for server-generated metadata")
        return value

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        self.symbols = sorted({str(symbol).strip().upper() for symbol in self.symbols if str(symbol).strip()})
        self.horizons = [
            item for item in ("weekly", "monthly", "quarterly") if item in set(self.horizons)
        ]
        invalid = sorted(set(self.required_edge_conditions) - set(EDGE_CONDITIONS))
        if invalid:
            raise ValueError(f"unknown Edge conditions: {invalid}")
        self.required_edge_conditions = [name for name in EDGE_CONDITIONS if name in self.required_edge_conditions]
        return self


class HistoricalPortfolioRunCreated(BaseModel):
    run_id: str
    status: Literal["queued", "succeeded"]
    reused: bool = False
    materialization_run_id: str | None = None


class HistoricalPortfolioRunStatus(BaseModel):
    run_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    methodology_version: str
    progress: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class HistoricalPortfolioRunResult(BaseModel):
    run_id: str
    status: Literal["succeeded"]
    methodology_version: str
    config: dict[str, Any]
    provenance: dict[str, Any]
    diagnostics: dict[str, Any]
    opportunities: list[dict[str, Any]]
    trades: list[dict[str, Any]]
    equity_curves: dict[str, Any]
    benchmark_curves: dict[str, Any]
    statistics: dict[str, Any]
    validation: dict[str, Any]
    snapshot_audit: dict[str, Any]
    warnings: list[str]
    winner_semantics: str | None = None
    barrier_scenario: dict[str, Any] | None = None
    liquidation_diagnostics: dict[str, Any] | None = None


class HistoricalOpportunityMaterializationCreate(BaseModel):
    start_date: date
    end_date: date
    symbols: list[str] = Field(default_factory=list)
    cost_bps_per_side: float = Field(33.0, ge=0)
    slippage_bps_per_side: float = Field(5.0, ge=0)
    bootstrap_seed: int = 5107

    @model_validator(mode="before")
    @classmethod
    def reject_system_namespace(cls, value):
        if isinstance(value, dict) and "_system" in value:
            raise ValueError("_system is reserved for server-generated metadata")
        return value

    @model_validator(mode="after")
    def validate_request(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        self.symbols = sorted({str(symbol).strip().upper() for symbol in self.symbols if str(symbol).strip()})
        return self


class HistoricalOpportunityMaterializationOut(BaseModel):
    materialization_run_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    methodology_version: str
    config: dict[str, Any]
    progress: dict[str, Any]
    coverage: dict[str, Any]
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
