from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class CurveCarry:
    front_second: float | None
    front_fourth: float | None
    units: str = "decimal annualized"


def curve_snapshot(quotes: pd.DataFrame, as_of: date) -> pd.DataFrame:
    required = {"date", "contract_expiry", "settle"}
    missing = sorted(required - set(quotes.columns))
    if missing:
        raise ValueError(f"curve quotes missing columns: {', '.join(missing)}")
    frame = quotes.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    frame["contract_expiry"] = pd.to_datetime(frame["contract_expiry"], errors="raise")
    selected = frame.loc[frame["date"].dt.date == as_of].sort_values("contract_expiry")
    if selected.empty:
        raise ValueError(f"no curve observations for {as_of}")
    return selected.reset_index(drop=True)


def nominal_carry(front: float, deferred: float, months_between: float) -> float:
    if front <= 0 or deferred <= 0:
        raise ValueError("curve prices must be positive")
    if months_between <= 0:
        raise ValueError("months_between must be positive")
    return (front / deferred - 1.0) * (12.0 / months_between)


def curve_carry(snapshot: pd.DataFrame) -> CurveCarry:
    if len(snapshot) < 2:
        return CurveCarry(None, None)
    expiries = pd.to_datetime(snapshot["contract_expiry"])
    prices = snapshot["settle"].astype(float).reset_index(drop=True)

    def span_months(index: int) -> float:
        return max((expiries.iloc[index] - expiries.iloc[0]).days * 12.0 / 365.25, 1 / 30)

    second = nominal_carry(float(prices.iloc[0]), float(prices.iloc[1]), span_months(1))
    fourth = nominal_carry(float(prices.iloc[0]), float(prices.iloc[3]), span_months(3)) if len(snapshot) >= 4 else None
    return CurveCarry(second, fourth)
