from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DashboardCustomIndexCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    symbols: list[str] = Field(..., min_length=1)


class DashboardCustomIndexUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    symbols: list[str] = Field(..., min_length=1)


class DashboardCustomIndexOut(BaseModel):
    id: str
    name: str
    symbols: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    portfolio_edge: dict[str, Any] | None = None

