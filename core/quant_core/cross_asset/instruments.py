from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: str
    currency: str
    quote_convention: str
    point_value: float = 1.0

    def __post_init__(self) -> None:
        if not self.symbol or not self.currency:
            raise ValueError("symbol and currency are required")
        if self.point_value <= 0:
            raise ValueError("point_value must be positive")


@dataclass(frozen=True)
class FxPair(Instrument):
    """FX pair where a long owns one unit of base versus quote currency."""

    base_ccy: str = ""
    quote_ccy: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.base_ccy or not self.quote_ccy:
            raise ValueError("base_ccy and quote_ccy are required")


@dataclass(frozen=True)
class FuturesContract(Instrument):
    root: str = ""
    expiry: date | None = None
    first_notice: date | None = None
    roll_rule: str = "first_notice"
    tick_size: float = 0.01

    def __post_init__(self) -> None:
        super().__post_init__()
        valid = self.roll_rule in {"first_notice", "volume_crossover"} or self.roll_rule.startswith(
            "n_days_before_expiry:"
        )
        if not valid:
            raise ValueError(f"unsupported roll_rule: {self.roll_rule}")
        if self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
