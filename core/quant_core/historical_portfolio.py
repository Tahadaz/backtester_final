"""Point-in-time trade-opportunity portfolio backtesting.

The module is deliberately independent from SQLAlchemy and the dashboard.  A
producer must supply opportunities whose selection/training cut-offs precede
the decision date.  The engine then enforces execution timing, point-in-time
Kelly sizing, liquidity, one-live-lot constraints and portfolio accounting.

This replaces the old portfolio-tab calculation which replayed the *current*
``SignalBestEvidenceSnapshot`` winner over its historical stitched trades.
That old calculation was internally cash-reconcilable, but was not a historical
test of what the dashboard would have selected on each decision date.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import hashlib
import math
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .horizons import DEFAULT_COST_BPS_PER_SIDE, HORIZON_SPECS
from .signal_engine.modes import TECHNICAL_SIGNAL_MODE_NAMES


CAPACITY_SCENARIOS = (0.01, 0.025, 0.05, 0.10)
DECISION_HORIZONS = ("weekly", "monthly", "quarterly")
METHODOLOGY_VERSION = "pit-dashboard-opportunity-portfolio-v1"


def _ts(value: Any) -> pd.Timestamp:
    out = pd.Timestamp(value)
    if out.tzinfo is not None:
        out = out.tz_convert(None)
    return out.normalize()


def _iso(value: Any) -> str:
    return _ts(value).date().isoformat()


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


@dataclass(frozen=True)
class SelectionObservation:
    """One return known before an opportunity is selected/sized."""

    exit_date: str
    net_return: float


@dataclass(frozen=True)
class HistoricalOpportunity:
    decision_date: str
    symbol: str
    horizon: str
    variant: str
    direction: str
    rank: tuple[float, ...] = ()
    bucket: str = ""
    training_end: str | None = None
    selection_sample_end: str | None = None
    proof_sample_end: str | None = None
    entry_lag_bars: int = 1
    exit_lag_bars: int = 5
    entry_price_kind: str = "open"
    exit_price_kind: str = "open"
    selection_observations: tuple[SelectionObservation, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def validate_point_in_time(self) -> None:
        decision = _ts(self.decision_date)
        if self.horizon not in HORIZON_SPECS:
            raise ValueError(f"unknown horizon: {self.horizon}")
        if self.variant not in TECHNICAL_SIGNAL_MODE_NAMES:
            raise ValueError(f"unknown technical signal mode: {self.variant}")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        for name in ("training_end", "selection_sample_end", "proof_sample_end"):
            value = getattr(self, name)
            if value is not None and _ts(value) >= decision:
                raise ValueError(f"{name} must precede decision_date")
        for observation in self.selection_observations:
            if _ts(observation.exit_date) >= decision:
                raise ValueError("Kelly selection observation was not known at decision_date")
        if self.entry_lag_bars < 1:
            raise ValueError("dashboard execution requires entry at J+1 or later")
        if self.exit_lag_bars < self.entry_lag_bars:
            raise ValueError("exit must not precede entry")


@dataclass(frozen=True)
class PortfolioBacktestConfig:
    initial_capital: float = 100_000.0
    cost_bps_per_side: float = DEFAULT_COST_BPS_PER_SIDE
    slippage_bps_per_side: float = 5.0
    half_kelly_multiplier: float = 0.5
    max_position_fraction: float = 0.25
    capacity_fraction: float = 0.01
    allow_partial_fills: bool = True
    minimum_kelly_observations: int = 3
    bootstrap_seed: int = 5107
    bootstrap_samples: int = 1000
    bootstrap_mean_block: int = 20

    def validate(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if self.capacity_fraction not in CAPACITY_SCENARIOS:
            raise ValueError("capacity_fraction must be one of 1%, 2.5%, 5%, 10% ADV20")
        if not 0 <= self.half_kelly_multiplier <= 1:
            raise ValueError("half_kelly_multiplier must be in [0, 1]")
        if not 0 < self.max_position_fraction <= 1:
            raise ValueError("max_position_fraction must be in (0, 1]")
        if self.minimum_kelly_observations < 1:
            raise ValueError("minimum_kelly_observations must be positive")


def half_kelly_from_selection_sample(
    observations: Sequence[SelectionObservation],
    *,
    decision_date: Any,
    multiplier: float = 0.5,
    minimum_observations: int = 3,
) -> float | None:
    """Kelly fraction using only outcomes known strictly before ``decision_date``.

    No starter or synthetic sample is used.  Insufficient history is represented
    by ``None`` and the opportunity is rejected explicitly by the simulator.
    """

    cutoff = _ts(decision_date)
    returns = [
        float(row.net_return)
        for row in observations
        if _ts(row.exit_date) < cutoff and _finite(row.net_return) is not None
    ]
    if len(returns) < int(minimum_observations):
        return None
    wins = [value for value in returns if value > 0]
    losses = [-value for value in returns if value <= 0]
    p = len(wins) / len(returns)
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    if avg_loss <= 0:
        raw = p
    elif avg_win <= 0:
        raw = 0.0
    else:
        raw = p - (1.0 - p) / (avg_win / avg_loss)
    return max(0.0, min(1.0, raw)) * float(multiplier)


def weekly_decision_dates(index: Iterable[Any], start: Any | None = None, end: Any | None = None) -> pd.DatetimeIndex:
    """Last available trading day of every ISO week (no fabricated calendar rows)."""

    idx = pd.DatetimeIndex([_ts(value) for value in index]).drop_duplicates().sort_values()
    if start is not None:
        idx = idx[idx >= _ts(start)]
    if end is not None:
        idx = idx[idx <= _ts(end)]
    if idx.empty:
        return idx
    series = pd.Series(idx, index=idx)
    return pd.DatetimeIndex(series.groupby(idx.to_period("W-FRI")).last().tolist())


def reconstruct_point_in_time(
    *,
    market_data: Mapping[str, pd.DataFrame],
    decision_dates: Iterable[Any],
    selector: Callable[[pd.Timestamp, str, str, Mapping[str, pd.DataFrame]], Iterable[HistoricalOpportunity]],
    horizons: Sequence[str] = DECISION_HORIZONS,
    variants: Sequence[str] = TECHNICAL_SIGNAL_MODE_NAMES,
) -> list[HistoricalOpportunity]:
    """Run a selector against immutable data slices ending at each decision date.

    The callback is invoked for every one of the eight technical modes.  It can
    never see a future market row, and returned provenance/cut-offs are checked.
    This contract is intentionally simple enough to test with a sentinel future
    row and is used by the persisted worker adapter.
    """

    if tuple(variants) != tuple(TECHNICAL_SIGNAL_MODE_NAMES):
        missing = sorted(set(TECHNICAL_SIGNAL_MODE_NAMES) - set(variants))
        if missing:
            raise ValueError(f"all eight technical modes are required; missing {missing}")
    opportunities: list[HistoricalOpportunity] = []
    for raw_date in sorted({_ts(value) for value in decision_dates}):
        sliced: dict[str, pd.DataFrame] = {}
        for symbol, frame in market_data.items():
            copy = frame.copy()
            copy.index = pd.DatetimeIndex([_ts(value) for value in copy.index])
            sliced[str(symbol).upper()] = copy.loc[copy.index <= raw_date].copy()
        for horizon in horizons:
            for variant in variants:
                for opportunity in selector(raw_date, horizon, variant, sliced):
                    opportunity.validate_point_in_time()
                    if _ts(opportunity.decision_date) != raw_date:
                        raise ValueError("selector returned an opportunity for another decision date")
                    if opportunity.horizon != horizon or opportunity.variant != variant:
                        raise ValueError("selector returned mismatched horizon/variant")
                    opportunities.append(opportunity)
    # Dashboard acceptance picks one best method per symbol/horizon/date.
    best: dict[tuple[str, str, str], HistoricalOpportunity] = {}
    for row in opportunities:
        key = (_iso(row.decision_date), row.symbol.upper(), row.horizon)
        previous = best.get(key)
        if previous is None or tuple(row.rank) > tuple(previous.rank):
            best[key] = row
    return sorted(best.values(), key=lambda row: (row.decision_date, row.horizon, row.symbol))


def _price_column(frame: pd.DataFrame, kind: str) -> str:
    candidates = ("Open", "open") if kind == "open" else ("Close", "close", "Adj Close")
    column = next((name for name in candidates if name in frame.columns), None)
    if column is None:
        raise ValueError(f"missing {kind} price column")
    return column


def _volume_column(frame: pd.DataFrame) -> str | None:
    return next((name for name in ("Volume", "volume") if name in frame.columns), None)


def _execution_details(opportunity: HistoricalOpportunity, frame: pd.DataFrame) -> dict[str, Any] | None:
    data = frame.copy()
    data.index = pd.DatetimeIndex([_ts(value) for value in data.index])
    data = data[~data.index.duplicated(keep="last")].sort_index()
    loc = int(data.index.searchsorted(_ts(opportunity.decision_date), side="right")) - 1
    if loc < 0 or data.index[loc] != _ts(opportunity.decision_date):
        return None
    entry_pos = loc + int(opportunity.entry_lag_bars)
    exit_pos = loc + int(opportunity.exit_lag_bars)
    if entry_pos >= len(data) or exit_pos >= len(data):
        return None
    entry_col = _price_column(data, opportunity.entry_price_kind)
    exit_col = _price_column(data, opportunity.exit_price_kind)
    entry_price = _finite(data.iloc[entry_pos][entry_col])
    exit_price = _finite(data.iloc[exit_pos][exit_col])
    if entry_price is None or exit_price is None or entry_price <= 0 or exit_price <= 0:
        return None
    volume_col = _volume_column(data)
    adv20 = None
    if volume_col is not None:
        # Capacity is known at the decision date; future entry volume is forbidden.
        hist = pd.to_numeric(data.iloc[: loc + 1][volume_col], errors="coerce").dropna().tail(20)
        if len(hist) == 20:
            close_col = _price_column(data, "close")
            close_hist = pd.to_numeric(data.iloc[: loc + 1][close_col], errors="coerce").dropna().tail(20)
            if len(close_hist) == 20:
                adv20 = float(np.mean(hist.to_numpy() * close_hist.to_numpy()))
    return {
        "entry_date": _iso(data.index[entry_pos]),
        "exit_date": _iso(data.index[exit_pos]),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "adv20_mad": adv20,
    }


def simulate_sleeve(
    opportunities: Sequence[HistoricalOpportunity],
    prices: Mapping[str, pd.DataFrame],
    config: PortfolioBacktestConfig,
    *,
    horizon: str,
) -> dict[str, Any]:
    """Simulate one horizon sleeve with executable, marked-to-market accounting."""

    config.validate()
    rows = [row for row in opportunities if row.horizon == horizon]
    for row in rows:
        row.validate_point_in_time()

    prepared: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for opportunity in rows:
        frame = prices.get(opportunity.symbol)
        if frame is None:
            frame = prices.get(opportunity.symbol.upper())
        if frame is None:
            rejected.append({"opportunity": asdict(opportunity), "reason": "missing_market_data"})
            continue
        execution = _execution_details(opportunity, frame)
        if execution is None:
            rejected.append({"opportunity": asdict(opportunity), "reason": "missing_j_plus_price"})
            continue
        prepared.append({"opportunity": opportunity, **execution})

    events: dict[pd.Timestamp, list[tuple[int, int, dict[str, Any]]]] = {}
    for idx, item in enumerate(prepared):
        events.setdefault(_ts(item["entry_date"]), []).append((1, idx, item))
        events.setdefault(_ts(item["exit_date"]), []).append((0, idx, item))

    if not events:
        return _empty_sleeve(horizon, config, rejected)

    all_price_dates = sorted({
        _ts(value)
        for frame in prices.values()
        for value in frame.index
        if min(events) <= _ts(value) <= max(events)
    })
    cash = float(config.initial_capital)
    lots: dict[tuple[str, str], dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    trade_by_id: dict[int, dict[str, Any]] = {}
    curve: list[dict[str, Any]] = []
    total_cost = 0.0
    turnover_notional = 0.0

    def mark(date_value: pd.Timestamp, lot: dict[str, Any]) -> float:
        frame = prices[lot["symbol"]]
        data = frame.copy()
        data.index = pd.DatetimeIndex([_ts(value) for value in data.index])
        available = data.loc[data.index <= date_value]
        if available.empty:
            return float(lot["entry_notional"])
        close = _finite(available.iloc[-1][_price_column(available, "close")])
        if close is None:
            return float(lot["entry_notional"])
        signed_return = (close / lot["entry_price"] - 1.0) * lot["direction_sign"]
        return float(lot["entry_notional"] * (1.0 + signed_return))

    for current_date in all_price_dates:
        day_events = sorted(events.get(current_date, []), key=lambda event: (event[0], event[1]))
        # Normal exits release cash before entries. Same-day lots are not possible
        # with the enforced J+1 entry and horizon exits.
        for event_type, idx, item in day_events:
            opportunity: HistoricalOpportunity = item["opportunity"]
            key = (opportunity.symbol.upper(), opportunity.horizon)
            if event_type == 0:
                lot = lots.pop(key, None)
                if lot is None or lot["trade_id"] != idx:
                    continue
                gross_return = (item["exit_price"] / item["entry_price"] - 1.0) * lot["direction_sign"]
                exit_cost = lot["entry_notional"] * (config.cost_bps_per_side + config.slippage_bps_per_side) * 1e-4
                proceeds = lot["entry_notional"] * (1.0 + gross_return) - exit_cost
                cash += proceeds
                total_cost += exit_cost
                turnover_notional += lot["entry_notional"]
                trade = trade_by_id[idx]
                trade.update({
                    "exit_date": item["exit_date"],
                    "exit_price": item["exit_price"],
                    "gross_return": gross_return,
                    "net_return": (proceeds - lot["entry_notional"] - lot["entry_cost"]) / lot["entry_notional"],
                    "realized_pnl": proceeds - lot["entry_notional"] - lot["entry_cost"],
                    "exit_cost": exit_cost,
                    "status": "executed",
                })
                continue

            if key in lots:
                rejected.append({"opportunity": asdict(opportunity), "reason": "one_live_lot"})
                continue
            kelly = half_kelly_from_selection_sample(
                opportunity.selection_observations,
                decision_date=opportunity.decision_date,
                multiplier=config.half_kelly_multiplier,
                minimum_observations=config.minimum_kelly_observations,
            )
            if kelly is None:
                rejected.append({"opportunity": asdict(opportunity), "reason": "insufficient_point_in_time_kelly_history"})
                continue
            if kelly <= 0:
                rejected.append({"opportunity": asdict(opportunity), "reason": "non_positive_kelly"})
                continue
            mtm = sum(mark(current_date, lot) for lot in lots.values())
            equity = cash + mtm
            desired = min(equity * kelly, equity * config.max_position_fraction)
            adv20 = item.get("adv20_mad")
            if adv20 is None or adv20 <= 0:
                rejected.append({"opportunity": asdict(opportunity), "reason": "adv20_unavailable"})
                continue
            capacity = float(adv20) * config.capacity_fraction
            if desired > capacity and not config.allow_partial_fills:
                rejected.append({"opportunity": asdict(opportunity), "reason": "capacity_rejected", "desired_notional": desired, "capacity_notional": capacity})
                continue
            notional = min(desired, capacity, cash / (1.0 + (config.cost_bps_per_side + config.slippage_bps_per_side) * 1e-4))
            if notional <= 0:
                rejected.append({"opportunity": asdict(opportunity), "reason": "insufficient_cash"})
                continue
            entry_cost = notional * (config.cost_bps_per_side + config.slippage_bps_per_side) * 1e-4
            cash -= notional + entry_cost
            total_cost += entry_cost
            turnover_notional += notional
            lot = {
                "trade_id": idx,
                "symbol": opportunity.symbol.upper(),
                "horizon": opportunity.horizon,
                "entry_notional": notional,
                "entry_price": item["entry_price"],
                "entry_cost": entry_cost,
                "direction_sign": 1.0 if opportunity.direction == "long" else -1.0,
            }
            lots[key] = lot
            trade = {
                "symbol": opportunity.symbol.upper(), "horizon": opportunity.horizon,
                "variant": opportunity.variant, "direction": opportunity.direction,
                "decision_date": opportunity.decision_date, "entry_date": item["entry_date"],
                "entry_price": item["entry_price"], "entry_notional": notional,
                "entry_cost": entry_cost, "adv20_mad": adv20,
                "capacity_fraction": config.capacity_fraction,
                "capacity_constrained": desired > capacity,
                "kelly_fraction": kelly, "provenance": dict(opportunity.provenance),
                "status": "open",
            }
            trades.append(trade)
            trade_by_id[idx] = trade

        market_value = sum(mark(current_date, lot) for lot in lots.values())
        equity = cash + market_value
        curve.append({
            "date": _iso(current_date), "cash": cash, "market_value": market_value,
            "equity": equity, "exposure": market_value / equity if equity > 0 else 0.0,
            "open_lots": len(lots),
        })

    if lots:
        for lot in lots.values():
            trade_by_id[lot["trade_id"]]["status"] = "open_at_end"
    stats = portfolio_statistics(curve, trades, rejected, config, total_cost, turnover_notional)
    return {
        "horizon": horizon, "equity_curve": curve, "trades": trades, "rejected_trades": rejected,
        "statistics": stats, "assumptions": execution_assumptions(config),
    }


def _empty_sleeve(horizon: str, config: PortfolioBacktestConfig, rejected: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "horizon": horizon, "equity_curve": [], "trades": [], "rejected_trades": rejected,
        "statistics": {"available": False, "reason": "no_executable_opportunities"},
        "assumptions": execution_assumptions(config),
    }


def execution_assumptions(config: PortfolioBacktestConfig) -> dict[str, Any]:
    return {
        "fills": "modeled_no_historical_fill_dataset",
        "entry": "decision date J+1 Open unless opportunity provenance specifies a later dashboard lag",
        "exit": "dashboard-selected J+ horizon and price kind",
        "cost_bps_per_side": config.cost_bps_per_side,
        "slippage_bps_per_side": config.slippage_bps_per_side,
        "capacity_fraction_adv20": config.capacity_fraction,
        "capacity_scenarios": list(CAPACITY_SCENARIOS),
        "adv20": "20 trading-day mean value traded, ending on the decision date",
        "sizing": "point-in-time half-Kelly; no synthetic starter sample",
        "one_live_lot": "one lot per symbol and horizon",
    }


def _drawdown(values: np.ndarray) -> float:
    if len(values) == 0:
        return float("nan")
    peaks = np.maximum.accumulate(values)
    return float(np.min(values / peaks - 1.0))


def portfolio_statistics(
    curve: Sequence[Mapping[str, Any]], trades: Sequence[Mapping[str, Any]],
    rejected: Sequence[Mapping[str, Any]], config: PortfolioBacktestConfig,
    total_cost: float, turnover_notional: float,
) -> dict[str, Any]:
    if len(curve) < 2:
        return {"available": False, "reason": "insufficient_history"}
    frame = pd.DataFrame(curve)
    frame["date"] = pd.to_datetime(frame["date"])
    equity = frame.set_index("date")["equity"].astype(float)
    daily = equity.pct_change().dropna()
    days = int((equity.index[-1] - equity.index[0]).days)
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0) if equity.iloc[0] > 0 else None
    cagr = None
    if days >= 365 and total_return is not None and equity.iloc[-1] > 0:
        cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (365.25 / days) - 1.0)
    volatility = float(daily.std(ddof=1) * math.sqrt(252)) if len(daily) >= 20 else None
    sharpe = None
    if volatility is not None and daily.std(ddof=1) > 0:
        sharpe = float(daily.mean() / daily.std(ddof=1) * math.sqrt(252))
    executed = [row for row in trades if row.get("status") == "executed"]
    hits = [float(row.get("realized_pnl") or 0.0) > 0 for row in executed]
    var_es = var_expected_shortfall(daily.to_numpy(), minimum=60)
    return {
        "available": True, "absolute_return": total_return, "cagr": cagr,
        "volatility": volatility, "sharpe": sharpe,
        "max_drawdown": abs(_drawdown(equity.to_numpy())),
        "turnover": turnover_notional / float(np.mean(equity)) if np.mean(equity) > 0 else None,
        "average_exposure": float(frame["exposure"].mean()),
        "maximum_exposure": float(frame["exposure"].max()),
        "hit_rate": float(np.mean(hits)) if hits else None,
        "trade_count": len(executed), "rejected_trade_count": len(rejected),
        "cost_impact_mad": total_cost,
        "cost_impact_return": total_cost / config.initial_capital,
        **var_es,
    }


def var_expected_shortfall(returns: np.ndarray, *, minimum: int = 60) -> dict[str, float | None]:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < minimum:
        return {"var_1d_95": None, "expected_shortfall_1d_95": None, "var_10d_95": None, "expected_shortfall_10d_95": None}
    q = float(np.quantile(values, 0.05))
    es = float(np.mean(values[values <= q]))
    rolling10 = np.convolve(values, np.ones(10), mode="valid")
    if len(rolling10) < minimum:
        return {"var_1d_95": -q, "expected_shortfall_1d_95": -es, "var_10d_95": None, "expected_shortfall_10d_95": None}
    q10 = float(np.quantile(rolling10, 0.05))
    es10 = float(np.mean(rolling10[rolling10 <= q10]))
    return {"var_1d_95": -q, "expected_shortfall_1d_95": -es, "var_10d_95": -q10, "expected_shortfall_10d_95": -es10}


def stationary_bootstrap_drawdown_risk(
    daily_returns: Sequence[float], *, seed: int = 5107, samples: int = 1000,
    mean_block: int = 20, window: int = 252,
) -> dict[str, Any]:
    """95th percentile maximum rolling-12m drawdown under stationary bootstrap."""

    values = np.asarray(daily_returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < window:
        return {"available": False, "reason": "requires_at_least_252_daily_returns", "drawdown_95": None}
    rng = np.random.default_rng(seed)
    p = 1.0 / max(1, int(mean_block))
    results = np.empty(int(samples), dtype=float)
    n = len(values)
    for sample in range(int(samples)):
        indices = np.empty(n, dtype=int)
        indices[0] = int(rng.integers(0, n))
        for pos in range(1, n):
            indices[pos] = int(rng.integers(0, n)) if rng.random() < p else (indices[pos - 1] + 1) % n
        boot = values[indices]
        equity = np.cumprod(1.0 + boot)
        worst = 0.0
        for end in range(window, n + 1):
            worst = max(worst, abs(_drawdown(equity[end - window:end])))
        results[sample] = worst
    return {
        "available": True, "criterion": "95th percentile of maximum rolling 12-month drawdown",
        "drawdown_95": float(np.quantile(results, 0.95)), "seed": int(seed),
        "samples": int(samples), "mean_block": int(mean_block),
    }


def benchmark_curves(curve: Sequence[Mapping[str, Any]], masi: pd.Series) -> dict[str, Any]:
    """Full-investment and strategy-exposure-matched MASI benchmarks."""

    if len(curve) < 2 or masi.empty:
        return {"available": False, "reason": "insufficient_overlap"}
    frame = pd.DataFrame(curve)
    frame.index = pd.to_datetime(frame.pop("date"))
    index = pd.Series(masi, dtype=float).copy()
    index.index = pd.DatetimeIndex([_ts(value) for value in index.index])
    joined = pd.concat([frame[["equity", "exposure"]], index.rename("masi")], axis=1).sort_index().ffill().dropna()
    if len(joined) < 2:
        return {"available": False, "reason": "insufficient_overlap"}
    initial = float(joined["equity"].iloc[0])
    masi_returns = joined["masi"].pct_change().fillna(0.0)
    full = initial * (1.0 + masi_returns).cumprod()
    # Exposure observed on day t may only be applied to the next return.
    matched = initial * (1.0 + masi_returns * joined["exposure"].shift(1).fillna(0.0)).cumprod()
    def payload(series: pd.Series) -> dict[str, Any]:
        return {
            "curve": [{"date": _iso(ts), "equity": float(value)} for ts, value in series.items()],
            "total_return": float(series.iloc[-1] / series.iloc[0] - 1.0),
        }
    return {"available": True, "full_investment_masi": payload(full), "exposure_matched_masi": payload(matched)}


def combine_sleeves_equal_risk(sleeves: Mapping[str, Mapping[str, Any]], initial_capital: float) -> dict[str, Any]:
    """Combine sleeves using prior 63-day inverse-volatility weights."""

    series: dict[str, pd.Series] = {}
    exposures: dict[str, pd.Series] = {}
    for horizon, payload in sleeves.items():
        curve = payload.get("equity_curve") or []
        if len(curve) >= 2:
            frame = pd.DataFrame(curve)
            indexed = frame.set_index(pd.to_datetime(frame["date"]))
            series[horizon] = indexed["equity"].astype(float).pct_change()
            exposures[horizon] = indexed["exposure"].astype(float)
    if not series:
        return {"equity_curve": [], "weights": [], "statistics": {"available": False, "reason": "no_sleeves"}}
    returns = pd.concat(series, axis=1).sort_index().fillna(0.0)
    vol = returns.rolling(63, min_periods=20).std().shift(1)
    weights = pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)
    for ts in returns.index:
        row = vol.loc[ts]
        valid = row[(row > 0) & row.notna()]
        if valid.empty:
            weights.loc[ts] = 1.0 / len(returns.columns)
        else:
            inv = 1.0 / valid
            normalized = inv / inv.sum()
            weights.loc[ts] = 0.0
            weights.loc[ts, normalized.index] = normalized
    combined_returns = (returns * weights).sum(axis=1)
    equity = float(initial_capital) * (1.0 + combined_returns).cumprod()
    exposure_panel = pd.concat(exposures, axis=1).reindex(returns.index).ffill().fillna(0.0)
    combined_exposure = (exposure_panel * weights).sum(axis=1).clip(0.0, 1.0)
    curve = [
        {"date": _iso(ts), "equity": float(value), "exposure": float(combined_exposure.loc[ts])}
        for ts, value in equity.items()
    ]
    return {
        "equity_curve": curve,
        "weights": [{"date": _iso(ts), **{key: float(value) for key, value in row.items()}} for ts, row in weights.iterrows()],
        "statistics": portfolio_statistics(curve, [], [], PortfolioBacktestConfig(initial_capital=initial_capital), 0.0, 0.0),
    }


def nested_capacity_frontier(
    candidate_returns: Mapping[float, pd.Series], *, risk_limit: float,
    seed: int = 5107, minimum_training: int = 252,
) -> dict[str, Any]:
    """Choose capacity caps in expanding outer folds without evaluating on the same fold."""

    caps = sorted(candidate_returns)
    if not caps:
        return {"available": False, "reason": "no_candidates", "folds": []}
    panel = pd.concat({cap: candidate_returns[cap] for cap in caps}, axis=1).sort_index()
    folds: list[dict[str, Any]] = []
    for test_start in range(minimum_training, len(panel), 63):
        train = panel.iloc[:test_start]
        test = panel.iloc[test_start:min(test_start + 63, len(panel))]
        eligible: list[tuple[float, float]] = []
        risks: dict[float, float | None] = {}
        for cap in caps:
            risk = stationary_bootstrap_drawdown_risk(train[cap].dropna(), seed=seed, samples=250)
            drawdown = risk.get("drawdown_95")
            risks[cap] = drawdown
            if drawdown is not None and drawdown <= risk_limit:
                eligible.append((float(train[cap].mean()), cap))
        selected = max(eligible)[1] if eligible else None
        folds.append({
            "train_end": _iso(train.index[-1]), "test_start": _iso(test.index[0]) if len(test) else None,
            "test_end": _iso(test.index[-1]) if len(test) else None, "selected_capacity_fraction": selected,
            "training_risk_by_capacity": {str(cap): risks[cap] for cap in caps},
            "evaluated_return": float((1.0 + test[selected].fillna(0.0)).prod() - 1.0) if selected is not None and len(test) else None,
        })
    return {"available": bool(folds), "risk_limit": risk_limit, "seed": seed, "folds": folds}


def snapshot_audit(
    reconstructed: Sequence[HistoricalOpportunity], snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare only literally persisted snapshot dates with reconstruction."""

    recon = {
        (_iso(row.decision_date), row.horizon, row.symbol.upper()): row.variant
        for row in reconstructed
    }
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        snapshot_date = snapshot.get("as_of_date")
        horizon = str(snapshot.get("horizon") or "")
        if not snapshot_date or horizon not in HORIZON_SPECS:
            continue
        payload = snapshot.get("payload") or snapshot.get("payload_jsonb") or {}
        stocks = payload.get("stocks") if isinstance(payload, Mapping) else []
        literal: dict[str, str] = {}
        for stock in stocks if isinstance(stocks, list) else []:
            best = stock.get("best_signal") if isinstance(stock, Mapping) else None
            if isinstance(best, Mapping) and best.get("variant"):
                literal[str(stock.get("symbol") or "").upper()] = str(best["variant"])
        date_key = _iso(snapshot_date)
        symbols = sorted(set(literal) | {key[2] for key in recon if key[:2] == (date_key, horizon)})
        for symbol in symbols:
            rebuilt = recon.get((date_key, horizon, symbol))
            shown = literal.get(symbol)
            rows.append({
                "as_of_date": date_key, "horizon": horizon, "symbol": symbol,
                "snapshot_variant": shown, "reconstructed_variant": rebuilt,
                "matches": shown == rebuilt,
            })
    dates = sorted({row["as_of_date"] for row in rows})
    return {
        "label": "short-window DashboardSnapshot audit",
        "statistically_equivalent_to_reconstruction": False,
        "coverage_start": dates[0] if dates else None, "coverage_end": dates[-1] if dates else None,
        "snapshot_dates": dates, "comparisons": rows,
        "discrepancy_count": sum(not row["matches"] for row in rows),
    }


def provenance_hash(payload: Mapping[str, Any]) -> str:
    import json
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
