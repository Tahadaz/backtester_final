from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class StrategyVoteItem(BaseModel):
    strategy_kind: str
    signal_label: str
    signal_today: float
    cagr: Optional[float] = None
    weight: Optional[float] = None


class StockSummaryOut(BaseModel):
    run_id: UUID
    symbol: str
    majority_vote: str
    weighted_vote: str
    majority_buys: int
    majority_sells: int
    majority_holds: int
    weighted_score: float
    strategy_count: int


class StockDetailOut(BaseModel):
    run_id: UUID
    symbol: str
    majority_vote: str
    weighted_vote: str
    majority_buys: int
    majority_sells: int
    majority_holds: int
    weighted_score: float
    strategies: list[dict[str, Any]]
    generated_at: datetime
