from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Iterable, Mapping


@dataclass(frozen=True)
class TradeStats:
    n_trades: int
    n_wins: int
    n_losses: int
    win_rate: float
    avg_win: float
    avg_loss: float
    wl_ratio: float


@dataclass(frozen=True)
class KellyResult:
    fraction: float
    half_kelly: float
    win_rate: float
    wl_ratio: float
    n_trades: int
    reason: str | None = None
    warning: str | None = None


def _coerce_pnl(trade: float | int | Mapping[str, float]) -> float:
    if isinstance(trade, (float, int)):
        return float(trade)
    return float(trade["net_pnl"])


def compute_trade_stats(trades: Iterable[float | int | Mapping[str, float]]) -> TradeStats:
    pnls = [_coerce_pnl(trade) for trade in trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [abs(pnl) for pnl in pnls if pnl <= 0]
    avg_win = mean(wins) if wins else 0.0
    avg_loss = mean(losses) if losses else 1.0
    wl_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    return TradeStats(
        n_trades=len(pnls),
        n_wins=len(wins),
        n_losses=len(losses),
        win_rate=(len(wins) / len(pnls)) if pnls else 0.0,
        avg_win=avg_win,
        avg_loss=avg_loss,
        wl_ratio=wl_ratio,
    )


def compute_kelly_fraction(stats: TradeStats) -> KellyResult:
    if stats.n_trades == 0 or stats.wl_ratio <= 0 or stats.win_rate <= 0:
        return KellyResult(
            fraction=0.0,
            half_kelly=0.0,
            win_rate=stats.win_rate,
            wl_ratio=stats.wl_ratio,
            n_trades=stats.n_trades,
            reason="No positive expectancy",
            warning="Only 0 OOS trades." if stats.n_trades == 0 else None,
        )

    fraction = stats.win_rate - (1.0 - stats.win_rate) / stats.wl_ratio
    if fraction <= 0:
        return KellyResult(
            fraction=0.0,
            half_kelly=0.0,
            win_rate=stats.win_rate,
            wl_ratio=stats.wl_ratio,
            n_trades=stats.n_trades,
            reason="Negative Kelly - no edge",
            warning="Consider using no leverage until WFO improves.",
        )

    warning = None
    if stats.n_trades < 30:
        warning = (
            f"Only {stats.n_trades} OOS trades. Kelly estimate has high uncertainty. "
            "Consider using half-Kelly."
        )

    return KellyResult(
        fraction=fraction,
        half_kelly=fraction / 2.0,
        win_rate=stats.win_rate,
        wl_ratio=stats.wl_ratio,
        n_trades=stats.n_trades,
        warning=warning,
    )

