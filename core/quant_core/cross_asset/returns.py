from __future__ import annotations

from datetime import date
from typing import Literal

import pandas as pd

ReturnKind = Literal["fx_excess", "futures_excess", "bond_duration"]


def fx_excess_return(
    spot: pd.Series,
    r_base: pd.Series,
    r_quote: pd.Series,
    daycount: float = 1 / 12,
) -> pd.Series:
    values = spot.astype(float).pct_change(fill_method=None) + (r_base.astype(float) - r_quote.astype(float)).shift(1) * daycount
    values.name = spot.name
    return values


def _date_key(value: object) -> date:
    return pd.Timestamp(value).date()


def _roll_return(front: pd.Series, roll_dates: list[date], next_on_roll: dict[date, float]) -> pd.Series:
    rolls = pd.Series(0.0, index=front.index, dtype=float)
    expected = {_date_key(value) for value in roll_dates}
    missing = expected - {_date_key(value) for value in next_on_roll}
    if missing:
        raise ValueError(f"missing next contract prices for roll dates: {sorted(missing)}")
    for timestamp in front.index:
        key = _date_key(timestamp)
        if key in expected:
            current = float(front.loc[timestamp])
            if current == 0:
                raise ValueError(f"zero front price on roll date {key}")
            rolls.loc[timestamp] = float(next_on_roll[key]) / current - 1.0
    return rolls


def futures_excess_return(
    front: pd.Series,
    roll_dates: list[date],
    next_on_roll: dict[date, float],
    collateral_rate: pd.Series,
    daycount: float = 1 / 252,
) -> pd.Series:
    price_and_roll = front.astype(float).pct_change(fill_method=None) + _roll_return(front, roll_dates, next_on_roll)
    result = price_and_roll + collateral_rate.astype(float).shift(1) * daycount
    result.name = front.name
    return result


def back_adjusted_series(
    front: pd.Series,
    roll_dates: list[date],
    next_on_roll: dict[date, float],
) -> pd.Series:
    """Display-only series whose returns include the explicit roll return."""
    if front.empty:
        return front.astype(float).copy()
    reconstructed = front.astype(float).pct_change(fill_method=None) + _roll_return(front, roll_dates, next_on_roll)
    result = (1.0 + reconstructed.fillna(0.0)).cumprod() * float(front.iloc[0])
    result.iloc[0] = float(front.iloc[0])
    result.name = front.name
    return result


def to_base_ccy(
    returns: pd.Series,
    instrument_ccy: str,
    base_ccy: str,
    fx: dict[str, pd.Series],
) -> pd.Series:
    if instrument_ccy == base_ccy:
        return returns.astype(float).copy()
    direct_keys = (f"{instrument_ccy}{base_ccy}", f"{instrument_ccy}/{base_ccy}")
    inverse_keys = (f"{base_ccy}{instrument_ccy}", f"{base_ccy}/{instrument_ccy}")
    conversion = next((fx[key] for key in direct_keys if key in fx), None)
    if conversion is not None:
        fx_return = conversion.astype(float).pct_change(fill_method=None)
    else:
        conversion = next((fx[key] for key in inverse_keys if key in fx), None)
        if conversion is None:
            raise KeyError(f"missing FX conversion {instrument_ccy}/{base_ccy}")
        fx_return = (1.0 / conversion.astype(float)).pct_change(fill_method=None)
    aligned_return, aligned_fx = returns.astype(float).align(fx_return, join="left")
    return (1.0 + aligned_return) * (1.0 + aligned_fx) - 1.0


def build_return(kind: ReturnKind, **kwargs: object) -> pd.Series:
    if kind == "fx_excess":
        return fx_excess_return(**kwargs)  # type: ignore[arg-type]
    if kind == "futures_excess":
        return futures_excess_return(**kwargs)  # type: ignore[arg-type]
    if kind == "bond_duration":
        raise NotImplementedError("bond_duration: Brief 4")
    raise ValueError(f"unsupported return kind: {kind}")
