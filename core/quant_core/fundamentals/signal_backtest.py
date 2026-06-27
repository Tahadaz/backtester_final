from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

import numpy as np
import pandas as pd

from ..research.stats.portfolio_stats import (
    assign_quintiles,                             # re-exported; tests import it from here
    equity_curve_with_stats as _equity_curve_with_stats,
    forward_return as _forward_return,
    forward_return_horizon as _forward_return_horizon,
    price_at_or_before as _price_at_or_before,
    quintile_return_summary as _quintile_return_summary,
    rebalance_dates as _rebalance_dates,
)


FundamentalSignalName = Literal["upside_pct", "pillar_score"]


@dataclass(frozen=True)
class PITSignalSnapshot:
    symbol: str
    as_of_date: dt.date
    upside_pct: float | None = None
    pillar_score: float | None = None
    source_id: str | None = None


@dataclass(frozen=True)
class SignalBacktestConfig:
    signal: FundamentalSignalName = "upside_pct"
    universe: str = "masi20"
    start: dt.date | None = None
    end: dt.date | None = None
    rebalance: str = "M"
    transaction_cost_bps: float = 25.0
    long_short: bool = False
    quintiles: int = 5
    ic_horizons: tuple[int, ...] = (21, 63, 126)


@dataclass(frozen=True)
class SignalBacktestResult:
    run_id: str
    signal: str
    universe: str
    rebalance: str
    as_of: dt.datetime
    params: dict[str, Any]
    quintile_returns: list[dict[str, Any]]
    ic: dict[str, Any]
    equity_curve: list[dict[str, Any]]
    turnover: list[dict[str, Any]]
    holdings: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "signal": self.signal,
            "universe": self.universe,
            "rebalance": self.rebalance,
            "as_of": self.as_of.isoformat(),
            "params": self.params,
            "quintile_returns": self.quintile_returns,
            "ic": self.ic,
            "equity_curve": self.equity_curve,
            "turnover": self.turnover,
            "holdings": self.holdings,
            "warnings": self.warnings,
        }


def run_signal_backtest(
    *,
    price_history: Mapping[str, pd.Series],
    snapshots_by_symbol: Mapping[str, list[PITSignalSnapshot]],
    config: SignalBacktestConfig | None = None,
    run_id: str = "fixture",
) -> SignalBacktestResult:
    config = config or SignalBacktestConfig()
    symbols = sorted({symbol.upper() for symbol in price_history} & {symbol.upper() for symbol in snapshots_by_symbol})
    clean_prices = {symbol: _clean_close_series(price_history[symbol]) for symbol in symbols}
    clean_prices = {symbol: series for symbol, series in clean_prices.items() if not series.empty}
    if not clean_prices:
        return _empty_result(run_id, config, ["no_price_history"])
    start = pd.Timestamp(config.start or min(series.index.min().date() for series in clean_prices.values()))
    end = pd.Timestamp(config.end or max(series.index.max().date() for series in clean_prices.values()))
    rebalance_dates = _rebalance_dates(clean_prices, start=start, end=end)
    if len(rebalance_dates) < 2:
        return _empty_result(run_id, config, ["not_enough_rebalance_dates"])

    period_records: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    turnover_rows: list[dict[str, Any]] = []
    previous_top: set[str] = set()
    equity = 1.0
    cost = float(config.transaction_cost_bps) / 10_000.0

    for entry_date, exit_date in zip(rebalance_dates[:-1], rebalance_dates[1:]):
        signal_rows: list[dict[str, Any]] = []
        for symbol in sorted(clean_prices):
            snapshot = latest_snapshot_as_of(snapshots_by_symbol.get(symbol, []), entry_date.date())
            if snapshot is None:
                continue
            signal_value = _signal_value(snapshot, config.signal)
            if signal_value is None:
                continue
            forward_return = _forward_return(clean_prices[symbol], entry_date, exit_date)
            if forward_return is None:
                continue
            signal_rows.append(
                {
                    "date": entry_date.date().isoformat(),
                    "exit_date": exit_date.date().isoformat(),
                    "symbol": symbol,
                    "as_of_date": snapshot.as_of_date.isoformat(),
                    "signal": signal_value,
                    "forward_return": forward_return,
                    "source_id": snapshot.source_id,
                }
            )
        if not signal_rows:
            continue
        quintiles = assign_quintiles({row["symbol"]: row["signal"] for row in signal_rows}, n=max(1, int(config.quintiles)))
        for row in signal_rows:
            row["quintile"] = quintiles[row["symbol"]]
            period_records.append(row)
        max_q = max(quintiles.values())
        min_q = min(quintiles.values())
        top = [row for row in signal_rows if row["quintile"] == max_q]
        bottom = [row for row in signal_rows if row["quintile"] == min_q]
        gross_return = _mean(row["forward_return"] for row in top)
        if config.long_short and bottom:
            gross_return -= _mean(row["forward_return"] for row in bottom)
            net_return = gross_return - 2.0 * cost
        else:
            net_return = gross_return - cost
        current_top = {row["symbol"] for row in top}
        turnover = 1.0 if not previous_top else 1.0 - len(current_top & previous_top) / max(len(current_top), 1)
        previous_top = current_top
        equity *= 1.0 + net_return
        equity_curve.append(
            {
                "date": exit_date.date().isoformat(),
                "gross_return": gross_return,
                "net_return": net_return,
                "equity": equity,
                "top_quintile_count": len(top),
                "bottom_quintile_count": len(bottom),
            }
        )
        turnover_rows.append({"date": entry_date.date().isoformat(), "turnover": turnover})
        holdings.append(
            {
                "date": entry_date.date().isoformat(),
                "top_quintile": sorted(current_top),
                "bottom_quintile": sorted({row["symbol"] for row in bottom}),
            }
        )

    return SignalBacktestResult(
        run_id=run_id,
        signal=config.signal,
        universe=config.universe,
        rebalance=config.rebalance,
        as_of=dt.datetime.now(dt.timezone.utc),
        params=_config_params(config),
        quintile_returns=_quintile_return_summary(period_records),
        ic=_ic_summary(period_records, clean_prices, config),
        equity_curve=_equity_curve_with_stats(equity_curve),
        turnover=turnover_rows,
        holdings=holdings,
        warnings=[] if period_records else ["no_rebalance_records"],
    )


def latest_snapshot_as_of(snapshots: list[PITSignalSnapshot], as_of: dt.date) -> PITSignalSnapshot | None:
    eligible = [snapshot for snapshot in snapshots if snapshot.as_of_date <= as_of]
    if not eligible:
        return None
    return sorted(eligible, key=lambda item: (item.as_of_date, item.source_id or ""))[-1]


def _empty_result(run_id: str, config: SignalBacktestConfig, warnings: list[str]) -> SignalBacktestResult:
    return SignalBacktestResult(
        run_id=run_id,
        signal=config.signal,
        universe=config.universe,
        rebalance=config.rebalance,
        as_of=dt.datetime.now(dt.timezone.utc),
        params=_config_params(config),
        quintile_returns=[],
        ic={"rank_ic": None, "ic_by_date": [], "ic_decay": []},
        equity_curve=[],
        turnover=[],
        holdings=[],
        warnings=warnings,
    )


def _config_params(config: SignalBacktestConfig) -> dict[str, Any]:
    return {
        "start": config.start.isoformat() if config.start else None,
        "end": config.end.isoformat() if config.end else None,
        "transaction_cost_bps": config.transaction_cost_bps,
        "long_short": config.long_short,
        "quintiles": config.quintiles,
        "ic_horizons": list(config.ic_horizons),
    }


def _clean_close_series(series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce").dropna()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    if isinstance(out.index, pd.DatetimeIndex) and out.index.tz is not None:
        out.index = out.index.tz_convert(None)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def _signal_value(snapshot: PITSignalSnapshot, signal: str) -> float | None:
    if signal == "pillar_score":
        return snapshot.pillar_score
    return snapshot.upside_pct


def _ic_summary(records: list[dict[str, Any]], price_history: Mapping[str, pd.Series], config: SignalBacktestConfig) -> dict[str, Any]:
    ic_by_date: list[dict[str, Any]] = []
    for date in sorted({str(row["date"]) for row in records}):
        rows = [row for row in records if row["date"] == date]
        ic = _spearman(
            pd.Series({row["symbol"]: row["signal"] for row in rows}, dtype=float),
            pd.Series({row["symbol"]: row["forward_return"] for row in rows}, dtype=float),
        )
        ic_by_date.append({"date": date, "ic": ic, "n": len(rows)})
    ic_values = [row["ic"] for row in ic_by_date if row["ic"] is not None and _finite(row["ic"])]
    decay: list[dict[str, Any]] = []
    for horizon in config.ic_horizons:
        horizon_ics: list[float] = []
        for date in sorted({str(row["date"]) for row in records}):
            entry = pd.Timestamp(date)
            rows = [row for row in records if row["date"] == date]
            forward = {
                row["symbol"]: _forward_return_horizon(price_history[row["symbol"]], entry, int(horizon))
                for row in rows
                if row["symbol"] in price_history
            }
            aligned_symbols = [symbol for symbol, value in forward.items() if value is not None]
            if len(aligned_symbols) < 3:
                continue
            ic = _spearman(
                pd.Series({row["symbol"]: row["signal"] for row in rows if row["symbol"] in aligned_symbols}, dtype=float),
                pd.Series({symbol: forward[symbol] for symbol in aligned_symbols}, dtype=float),
            )
            if ic is not None and _finite(ic):
                horizon_ics.append(ic)
        decay.append({"horizon_days": int(horizon), "ic": _mean(horizon_ics) if horizon_ics else None, "n": len(horizon_ics)})
    return {
        "rank_ic": _mean(ic_values) if ic_values else None,
        "ic_by_date": ic_by_date,
        "ic_decay": decay,
    }


def _spearman(signal: pd.Series, returns: pd.Series) -> float | None:
    aligned = pd.concat([signal.rename("signal"), returns.rename("return")], axis=1).dropna()
    if len(aligned) < 3:
        return None
    ranked = aligned.rank()
    if ranked["signal"].nunique() < 2 or ranked["return"].nunique() < 2:
        return None
    corr = ranked["signal"].corr(ranked["return"])
    return float(corr) if corr is not None and _finite(corr) else None


def _annualized_sharpe(returns: np.ndarray, *, periods_per_year: int) -> float:
    if len(returns) < 2:
        return 0.0
    sigma = float(np.std(returns, ddof=1))
    if sigma <= 0:
        return 0.0
    return float(np.mean(returns) / sigma * math.sqrt(periods_per_year))


def _mean(values: Any) -> float:
    clean = [float(value) for value in values if _finite(value)]
    return float(np.mean(clean)) if clean else 0.0


def _finite(value: Any) -> bool:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(out)
