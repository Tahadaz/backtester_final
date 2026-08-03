from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StrategyCreate(BaseModel):
    spec: dict[str, Any]


class DataQualityRequest(BaseModel):
    strategy_id: str | None = None
    spec: dict[str, Any] | None = None
    data: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=list)


class RunCreate(BaseModel):
    strategy_id: str
    data: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=list)
    dataset_id: str | None = None
    dataset_hash: str | None = None
    seed: int = 0


class CommodityCurveRequest(BaseModel):
    data: list[dict[str, Any]]
    as_of: str
    data_tier: str = Field(default="fixture", pattern=r"^(fixture|proxy|validated)$")


class RatesCurveLabRequest(BaseModel):
    observations: list[dict[str, Any]]
    long_notional: float = Field(default=1_000_000, gt=0)
    long_yield_change_bp: float = 0.0
    short_yield_change_bp: float = 0.0


class TransparencyEnvelope(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    methodology: dict[str, Any] = Field(default_factory=dict)
    data_source: str
    calculation_date: str
    assumptions: list[str] = Field(default_factory=list)
    units: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    results: Any = None
    interpretation: str
