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
