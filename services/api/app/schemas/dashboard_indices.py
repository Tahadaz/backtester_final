from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DashboardIndexComponent(BaseModel):
    symbol: str = Field(..., min_length=1)
    shares: int = Field(..., ge=1)


class DashboardCustomIndexCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    symbols: list[str] | None = None
    components: list[DashboardIndexComponent] | None = None
    use_available_shares: bool = False


class DashboardCustomIndexUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    symbols: list[str] | None = None
    components: list[DashboardIndexComponent] | None = None
    use_available_shares: bool = False


class DashboardCustomIndexOut(BaseModel):
    id: str
    name: str
    symbols: list[str] = Field(default_factory=list)
    component_shares: dict[str, int] = Field(default_factory=dict)
    components: list[DashboardIndexComponent] = Field(default_factory=list)
    is_weighted_complete: bool = False
    created_at: str
    updated_at: str
    portfolio_edge: dict[str, Any] | None = None

