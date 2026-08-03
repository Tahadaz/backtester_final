from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from .instruments import FuturesContract


@dataclass(frozen=True)
class FuturesChainResult:
    held_contract: pd.Series
    roll_dates: tuple[date, ...]
    warnings: tuple[str, ...]


def _roll_trigger(contract: FuturesContract) -> date:
    if contract.expiry is None:
        raise ValueError(f"{contract.symbol}: expiry is required")
    if contract.roll_rule == "first_notice":
        if contract.first_notice is None:
            raise ValueError(f"{contract.symbol}: first_notice is required for first_notice roll")
        return contract.first_notice
    if contract.roll_rule.startswith("n_days_before_expiry"):
        parts = contract.roll_rule.split(":", 1)
        days = int(parts[1]) if len(parts) == 2 else 5
        if days < 0:
            raise ValueError("roll days cannot be negative")
        trigger = contract.expiry - timedelta(days=days)
        return min(trigger, contract.first_notice) if contract.first_notice else trigger
    if contract.roll_rule == "volume_crossover":
        return contract.first_notice or contract.expiry
    raise ValueError(f"unsupported roll rule: {contract.roll_rule}")


def build_futures_chain(
    contracts: list[FuturesContract],
    dates: pd.DatetimeIndex,
    *,
    prices: pd.DataFrame | None = None,
    volumes: pd.DataFrame | None = None,
) -> FuturesChainResult:
    """Construct an explicit held-contract sequence without delivery exposure."""
    if dates.has_duplicates:
        raise ValueError("chain dates must be unique")
    ordered = sorted(contracts, key=lambda item: item.expiry or date.max)
    if not ordered:
        raise ValueError("at least one futures contract is required")
    for contract in ordered:
        if contract.expiry is None:
            raise ValueError(f"{contract.symbol}: expiry is required")
        if contract.first_notice and contract.first_notice > contract.expiry:
            raise ValueError(f"{contract.symbol}: first_notice cannot follow expiry")
    held = pd.Series(index=dates, dtype=object, name="held_contract")
    warnings: list[str] = []
    current = 0
    previous_symbol: str | None = None
    roll_dates: list[date] = []
    for timestamp in dates:
        day = pd.Timestamp(timestamp).date()
        while current < len(ordered) - 1:
            active = ordered[current]
            forced = _roll_trigger(active)
            crossover = False
            if active.roll_rule == "volume_crossover" and volumes is not None:
                next_contract = ordered[current + 1]
                if active.symbol in volumes and next_contract.symbol in volumes and timestamp in volumes.index:
                    active_volume = volumes.at[timestamp, active.symbol]
                    next_volume = volumes.at[timestamp, next_contract.symbol]
                    crossover = pd.notna(active_volume) and pd.notna(next_volume) and float(next_volume) > float(active_volume)
            if day >= forced or crossover:
                current += 1
                continue
            break
        active = ordered[current]
        delivery_cutoff = active.first_notice or active.expiry
        available = prices is None or (active.symbol in prices and timestamp in prices.index and pd.notna(prices.at[timestamp, active.symbol]))
        if day >= delivery_cutoff:
            warnings.append(f"{day}: no delivery-safe successor after {active.symbol}; contract gap left missing")
            symbol = None
        elif not available:
            warnings.append(f"{day}: {active.symbol} price unavailable; contract gap left missing")
            symbol = None
        else:
            symbol = active.symbol
        held.at[timestamp] = symbol
        if symbol is not None and previous_symbol is not None and symbol != previous_symbol:
            roll_dates.append(day)
        if symbol is not None:
            previous_symbol = symbol
    return FuturesChainResult(held, tuple(roll_dates), tuple(dict.fromkeys(warnings)))
