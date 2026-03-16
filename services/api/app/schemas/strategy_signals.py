"""Pydantic schemas for the strategy signals API."""

from pydantic import BaseModel, Field


class SmaEnsembleRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D", min_length=1)
