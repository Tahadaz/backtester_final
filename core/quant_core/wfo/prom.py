from __future__ import annotations

from math import inf, sqrt
from statistics import mean
from typing import Iterable, Mapping, Protocol, runtime_checkable


@runtime_checkable
class SupportsNetPnl(Protocol):
    @property
    def net_pnl(self) -> float: ...


def _coerce_trade_pnl(trade: float | int | SupportsNetPnl | Mapping[str, float]) -> float:
    if isinstance(trade, (float, int)):
        return float(trade)
    if isinstance(trade, Mapping):
        value = trade.get("net_pnl")
        if value is None:
            raise KeyError("trade mapping is missing 'net_pnl'")
        return float(value)
    return float(trade.net_pnl)


def compute_prom(
    trades: Iterable[float | int | SupportsNetPnl | Mapping[str, float]],
    capital: float,
) -> float:
    if capital <= 0:
        raise ValueError("capital must be positive")

    pnls = [_coerce_trade_pnl(trade) for trade in trades]
    if not pnls:
        return -inf

    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [abs(pnl) for pnl in pnls if pnl <= 0]
    n_wt = len(wins)
    n_lt = len(losses)
    aw = mean(wins) if wins else 0.0
    al = mean(losses) if losses else 0.0
    adj_wins = aw * (n_wt - sqrt(n_wt)) if n_wt else 0.0
    adj_losses = al * (n_lt + sqrt(n_lt)) if n_lt else 0.0
    return (adj_wins - adj_losses) / capital

