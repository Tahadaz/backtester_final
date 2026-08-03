from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class BondDefinitionIn(BaseModel):
    face_value: float = Field(default=100.0, gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    coupon_rate: float = Field(ge=0)
    coupon_frequency: Literal[1, 2] = 1
    maturity_date: date
    day_count: Literal["30E/360", "ACT/ACT-ICMA", "ACT/365F"] = "30E/360"
    redemption: float = Field(default=100.0, gt=0)


class BondQuoteIn(BaseModel):
    type: Literal["yield", "clean_price", "dirty_price"]
    value: float

    @model_validator(mode="after")
    def validate_price(self):
        if self.type != "yield" and self.value <= 0:
            raise ValueError("quote.value must be positive for a price quote")
        return self


class BondAnalyticsRequest(BaseModel):
    bond: BondDefinitionIn
    settlement_date: date
    quote: BondQuoteIn
    notional: float = Field(default=1_000_000, gt=0)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.settlement_date >= self.bond.maturity_date:
            raise ValueError("settlement_date must be before bond.maturity_date")
        return self


class BondScenariosRequest(BondAnalyticsRequest):
    shocks_bp: list[float] = Field(default_factory=lambda: [-100, -50, -25, -10, -1, 0, 1, 10, 25, 50, 100])
    holding_period_days: int | None = Field(default=None, ge=0)
