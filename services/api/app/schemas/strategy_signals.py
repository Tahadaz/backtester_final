"""Pydantic schemas for the strategy signals API."""

from pydantic import BaseModel, Field


class SmaEnsembleRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D", min_length=1)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)


class FamilyEnsembleRequest(BaseModel):
    family: str = Field(..., pattern=r"^(sma|rsi|macd|obv)$")
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D", min_length=1)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)


class VariantDetailRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D", min_length=1)
    variant_id: str = Field(..., min_length=1)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)


class VariantBacktestRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    variant_id: str = Field(..., min_length=1)
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D", min_length=1)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)


class BatchScoresRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1)
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D", min_length=1)
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)
