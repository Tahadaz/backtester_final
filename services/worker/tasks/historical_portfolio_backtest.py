"""Persisted background execution for the historical opportunity portfolio."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
import time
from uuid import UUID
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import func

from core.quant_core.historical_portfolio import (
    CAPACITY_SCENARIOS,
    DECISION_HORIZONS,
    METHODOLOGY_VERSION,
    V5_DECISION_EDGE_COST_BPS,
    HistoricalOpportunity,
    PortfolioBacktestConfig,
    SelectionObservation,
    benchmark_curves,
    combine_sleeves_equal_risk,
    provenance_hash,
    simulate_sleeve,
    snapshot_audit,
    weekly_decision_dates,
    half_kelly_from_selection_sample,
)
from core.quant_core.signal_ranking import AsOfDecision, AsOfInputs, build_asof_decision
from core.quant_core.pit_watermark import source_watermark_v1
from core.quant_core.edge_policy import DEFAULT_EDGE_CONDITIONS, passes_edge_policy
from core.quant_core.horizons import HORIZON_SPECS
from core.quant_core.research.score_history import _bucket_for
from core.quant_core.research.edge import METHODOLOGY_VERSION as EDGE_METHODOLOGY_VERSION, build_edge_payload
from core.quant_core.research.oos_index import OosSample, OosWindow
from core.quant_core.signal_engine.modes import TECHNICAL_SIGNAL_MODE_NAMES, signal_mode_read_names


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _price_col(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out.index = pd.DatetimeIndex(out.index)
    if out.index.tz is not None:
        out.index = out.index.tz_convert(None)
    out.index = out.index.normalize()
    return out[~out.index.duplicated(keep="last")].sort_index()


def _finite_price(value: Any) -> float | None:
    """Return a strictly positive finite execution/mark price, otherwise ``None``."""

    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if np.isfinite(price) and price > 0 else None


def _sanitize_json(value: Any) -> Any:
    """Return a JSON-safe copy with every non-finite floating value replaced by ``None``."""

    if isinstance(value, dict):
        return {key: _sanitize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _direction(bucket: str) -> str | None:
    if bucket in {"buy", "strong_buy"}:
        return "long"
    if bucket in {"sell", "strong_sell"}:
        return "short"
    return None


def _trade_observation(
    frame: pd.DataFrame, decision: pd.Timestamp, direction: str, exit_lag: int,
    cost_bps: float, slippage_bps: float,
) -> SelectionObservation | None:
    loc = int(frame.index.searchsorted(decision, side="right")) - 1
    entry_pos, exit_pos = loc + 1, loc + int(exit_lag)
    if loc < 0 or entry_pos >= len(frame) or exit_pos >= len(frame):
        return None
    open_col = _price_col(frame, ("Open", "open"))
    if open_col is None:
        return None
    entry = float(frame.iloc[entry_pos][open_col])
    exit_price = float(frame.iloc[exit_pos][open_col])
    if not np.isfinite(entry) or not np.isfinite(exit_price) or entry <= 0:
        return None
    gross = (exit_price / entry - 1.0) * (1.0 if direction == "long" else -1.0)
    net = gross - 2.0 * (float(cost_bps) + float(slippage_bps)) * 1e-4
    return SelectionObservation(frame.index[exit_pos].date().isoformat(), float(net))


def _edge_oos_sample(horizon: str, dates: pd.DatetimeIndex) -> OosSample:
    ordered = pd.DatetimeIndex(dates).dropna().sort_values().unique()
    windows = () if len(ordered) == 0 else (
        OosWindow(fold_id=None, start=pd.Timestamp(ordered[0]), end=pd.Timestamp(ordered[-1])),
    )
    return OosSample(
        source="wfo", horizon=horizon, windows=windows, dates=ordered,
        score_mode="fold_scoped_winner",
    )


def _build_selector(score_series: dict[tuple[str, str], dict[str, pd.Series]], config: dict[str, Any]):
    seed = int(config.get("bootstrap_seed", 5107))
    edge_mc_iterations = max(100, int(config.get("edge_mc_iterations", 500)))

    def selector(as_of: pd.Timestamp, horizon: str, variant: str, market: dict[str, pd.DataFrame]):
        decisions: list[tuple[str, AsOfDecision]] = []
        for symbol in config.get("resolved_universe") or config.get("symbols") or sorted(market):
            frame = market.get(symbol)
            categories = score_series.get((symbol, variant), {})
            oos_dates = sorted({pd.Timestamp(value) for series in categories.values() for value in series.index})
            decisions.append((symbol, build_asof_decision(AsOfInputs(
                symbol=symbol, horizon=horizon, variant=variant, as_of=as_of,
                category_series=categories, prices=frame, oos=tuple(oos_dates),
                decision_edge_cost_bps=V5_DECISION_EDGE_COST_BPS,
                mc_iterations=edge_mc_iterations, mc_seed=seed,
            ))))
        return decisions

    return selector


def _load_inputs(db, config: dict[str, Any]):
    from services.api.app import models
    from services.api.app.market_data_loader import load_ohlcv_for_symbol

    requested = list(config.get("resolved_universe") or config.get("symbols") or [])
    if requested:
        symbols = sorted({str(symbol).upper() for symbol in requested})
    else:
        query = db.query(models.SignalScoreHistory.symbol).filter(models.SignalScoreHistory.is_oos.is_(True)).distinct()
        symbols = sorted({row[0].upper() for row in query.all()})
    prices: dict[str, pd.DataFrame] = {}
    end = pd.Timestamp(config["end_date"])
    for symbol in symbols:
        try:
            frame = _clean_frame(load_ohlcv_for_symbol(db, symbol))
            frame = frame.loc[frame.index <= end]
            if not frame.empty:
                prices[symbol] = frame
        except Exception:
            continue

    score_series: dict[tuple[str, str], dict[str, pd.Series]] = {}
    for symbol in symbols:
        for variant in TECHNICAL_SIGNAL_MODE_NAMES:
            sources = tuple(f"wfo:{name}" for name in signal_mode_read_names(variant))
            if variant == "expanded_ta_simple":
                sources = (*sources, "wfo")
            rows = db.query(models.SignalScoreHistory).filter(
                models.SignalScoreHistory.symbol == symbol,
                models.SignalScoreHistory.source.in_(sources),
                models.SignalScoreHistory.is_oos.is_(True),
                models.SignalScoreHistory.horizon.in_(DECISION_HORIZONS),
                models.SignalScoreHistory.date <= end.date(),
            ).order_by(models.SignalScoreHistory.date.asc()).all()
            by_category: dict[str, dict[pd.Timestamp, float]] = {}
            for row in rows:
                # Horizon-specific rows are loaded later by the selector's closure
                # through distinct variant keys; preserve horizon in category key.
                by_category.setdefault(f"{row.horizon}:{row.category}", {})[pd.Timestamp(row.date)] = float(row.score_pct)
            # Split is done here to avoid mixing horizon series.
            for horizon in DECISION_HORIZONS:
                selected = {
                    key.split(":", 1)[1]: pd.Series(values).sort_index()
                    for key, values in by_category.items() if key.startswith(f"{horizon}:")
                }
                if selected:
                    score_series[(f"{symbol}|{horizon}", variant)] = selected
    return prices, score_series


def _load_weekly_masi_calendar(db, config: dict[str, Any]) -> pd.DatetimeIndex:
    """Canonical weekly decision dates from the MASI index trading calendar."""

    from services.api.app.market_data_loader import load_ohlcv_for_symbol

    frame = _clean_frame(load_ohlcv_for_symbol(db, "MASI"))
    return weekly_decision_dates(frame.index, config["start_date"], config["end_date"])


def _load_prices(db, symbols: list[str]) -> dict[str, pd.DataFrame]:
    from services.api.app.market_data_loader import load_ohlcv_for_symbol

    prices: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            frame = _clean_frame(load_ohlcv_for_symbol(db, symbol))
            if not frame.empty:
                prices[symbol] = frame
        except Exception:
            continue
    return prices


def _opportunity_from_json(payload: dict[str, Any]) -> HistoricalOpportunity:
    raw = dict(payload)
    raw["rank"] = tuple(raw.get("rank") or ())
    raw["selection_observations"] = tuple(
        SelectionObservation(**item) for item in (raw.get("selection_observations") or [])
    )
    return HistoricalOpportunity(**raw)


_EXECUTION_EVENT_KEYS = (
    "methodology_version", "scenario", "decision_date", "action_date", "symbol", "horizon",
    "winner_variant", "signal_direction", "actionable", "execution_eligible",
    "execution_action", "reason", "position_before", "position_after",
    "opportunity_input_hash", "fill_price", "quantity", "notional", "delay_sessions",
)


def _event(**values: Any) -> dict[str, Any]:
    payload = {key: None for key in _EXECUTION_EVENT_KEYS}
    payload.update(values)
    return payload


def _simulate_winner_sleeve(
    decision_rows: list[dict[str, Any]],
    prices: dict[str, pd.DataFrame],
    config: PortfolioBacktestConfig,
    *,
    horizon: str,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    scenario: str = "baseline",
    clean_prices: dict[str, pd.DataFrame] | None = None,
    all_dates: list[pd.Timestamp] | None = None,
) -> dict[str, Any]:
    """Winner-only MASI cash-equity replay with position-aware short liquidation.

    ``clean_prices`` and ``all_dates`` are pure functions of ``prices`` and identical across every
    (horizon, scenario) call, so the caller computes them once and injects them; they default to
    per-call derivation only for standalone/test callers.
    """

    config.validate()
    rows = sorted(
        (row for row in decision_rows if row["horizon"] == horizon),
        key=lambda row: (row["decision_date"], row["symbol"]),
    )
    if clean_prices is None:
        clean_prices = {symbol: _clean_frame(frame) for symbol, frame in prices.items()}
    scheduled_actions: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    events: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in rows:
        frame = clean_prices.get(row["symbol"])
        decision_date = pd.Timestamp(row["decision_date"])
        action_date = None
        delay = None
        if frame is not None:
            pos = int(frame.index.searchsorted(decision_date, side="right"))
            if pos < len(frame):
                action_date = pd.Timestamp(frame.index[pos])
                delay = 1
                if row.get("opportunity") is not None and row.get("signal_direction") == "long":
                    opportunity: HistoricalOpportunity = row["opportunity"]
                    decision_pos = int(frame.index.searchsorted(decision_date, side="right")) - 1
                    entry_pos = decision_pos + int(opportunity.entry_lag_bars)
                    if 0 <= entry_pos < len(frame):
                        action_date = pd.Timestamp(frame.index[entry_pos])
                        delay = max(1, entry_pos - decision_pos)
        row = {**row, "action_date": action_date, "delay_sessions": delay}
        if action_date is None:
            events.append(_event(
                methodology_version=METHODOLOGY_VERSION, scenario=scenario,
                decision_date=decision_date.date().isoformat(), symbol=row["symbol"], horizon=horizon,
                winner_variant=row.get("winner_variant"), signal_direction=row.get("signal_direction"),
                actionable=bool(row.get("actionable")), execution_eligible=bool(row.get("execution_eligible")),
                execution_action="skip", reason="missing_next_available_open", position_before="flat",
                position_after="flat", opportunity_input_hash=row.get("input_hash"),
            ))
        else:
            scheduled_actions.setdefault(action_date, []).append(row)

    if not clean_prices:
        return {
            "horizon": horizon, "equity_curve": [], "trades": [], "rejected_trades": rejected,
            "statistics": {"available": False, "reason": "no_market_data"},
            "assumptions": {}, "execution_events": events, "liquidations": [],
        }

    if all_dates is None:
        all_dates = sorted({timestamp for frame in clean_prices.values() for timestamp in frame.index})
    # Precompute each symbol's close-price series once as (index, values) arrays. Daily
    # mark-to-market then finds "last close <= day" by searchsorted (O(log n)) instead of masking
    # the whole frame per lot per day — the difference between seconds and tens of minutes over a
    # multi-year window with many open lots.
    mark_series: dict[str, dict[str, Any]] = {}
    for symbol, frame in clean_prices.items():
        close_col = _price_col(frame, ("Close", "close", "Adj Close"))
        if close_col:
            # A zero-volume/non-trading row may have no OHLC values. Mark open lots at the last
            # real close; never allow such a row to poison every subsequent equity point.
            closes = pd.to_numeric(frame[close_col], errors="coerce")
            closes = closes.where(np.isfinite(closes) & (closes > 0)).ffill()
            mark_series[symbol] = {
                "index": frame.index,
                "values": closes.to_numpy(dtype=float),
            }
    cash = float(config.initial_capital)
    lots: dict[tuple[str, str], dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []
    liquidations: list[dict[str, Any]] = []
    total_cost = 0.0
    turnover = 0.0
    cost_rate = (config.cost_bps_per_side + config.slippage_bps_per_side) * 1e-4

    def price_row(symbol: str, day: pd.Timestamp):
        frame = clean_prices[symbol]
        return frame.loc[day] if day in frame.index else None

    def close_lot(key: tuple[str, str], day: pd.Timestamp, fill: float, reason: str) -> dict[str, Any] | None:
        nonlocal cash, total_cost, turnover
        fill = _finite_price(fill)
        if fill is None:
            return None
        lot = lots.pop(key, None)
        if lot is None:
            return None
        exit_cost = lot["notional"] * cost_rate
        proceeds = lot["quantity"] * fill - exit_cost
        cash += proceeds
        total_cost += exit_cost
        turnover += lot["notional"]
        gross_return = fill / lot["entry_price"] - 1.0
        realized = proceeds - lot["notional"] - lot["entry_cost"]
        trade = lot["trade"]
        trade.update({
            "exit_date": day.date().isoformat(), "exit_price": fill,
            "gross_return": gross_return, "net_return": realized / lot["notional"],
            "realized_pnl": realized, "exit_cost": exit_cost, "exit_reason": reason,
            "status": "executed",
        })
        return lot

    for day in all_dates:
        day_actions = sorted(scheduled_actions.get(day, []), key=lambda row: row["symbol"])
        # Risk reduction has same-open precedence over scheduled and barrier exits.
        for action in [item for item in day_actions if item.get("signal_direction") == "short"]:
            key = (action["symbol"], horizon)
            before = "long" if key in lots else "flat"
            fill = None
            quantity = None
            notional = None
            if key in lots:
                row_price = price_row(action["symbol"], day)
                open_col = _price_col(clean_prices[action["symbol"]], ("Open", "open"))
                fill = _finite_price(row_price[open_col]) if row_price is not None and open_col else None
                marked_equity = cash
                for open_lot in lots.values():
                    marked_row = price_row(open_lot["symbol"], day)
                    marked_col = _price_col(clean_prices[open_lot["symbol"]], ("Open", "open"))
                    if marked_row is not None and marked_col is not None:
                        marked_price = _finite_price(marked_row[marked_col])
                        if marked_price is not None:
                            marked_equity += open_lot["quantity"] * marked_price
                lot = close_lot(key, day, fill, "short_signal_liquidation") if fill is not None else None
                if lot:
                    quantity, notional = lot["quantity"], lot["notional"]
                    scheduled_day = lot["scheduled_exit_date"]
                    counterfactual: float | str = "unavailable"
                    if scheduled_day in clean_prices[action["symbol"]].index:
                        scheduled_row = clean_prices[action["symbol"]].loc[scheduled_day]
                        exit_col = _price_col(clean_prices[action["symbol"]], ("Open", "open"))
                        if exit_col:
                            scheduled_fill = _finite_price(scheduled_row[exit_col])
                            if scheduled_fill is not None:
                                counterfactual = scheduled_fill / lot["entry_price"] - 1.0 - 2 * cost_rate
                    actual_return = lot["trade"]["net_return"]
                    liquidations.append({
                        "symbol": action["symbol"], "horizon": horizon,
                        "decision_date": action["decision_date"], "action_date": day.date().isoformat(),
                        "realized_pnl": lot["trade"]["realized_pnl"], "liquidated_notional": notional,
                        "equity_at_fill": marked_equity,
                        "exposure_reduction_pct_of_equity_at_fill": (
                            float(notional) / marked_equity if marked_equity > 0 else None
                        ),
                        "counterfactual_scheduled_exit_return": counterfactual,
                        "pnl_delta_return": (
                            actual_return - counterfactual if isinstance(counterfactual, float) else None
                        ),
                    })
            events.append(_event(
                methodology_version=METHODOLOGY_VERSION, scenario=scenario,
                decision_date=action["decision_date"], action_date=day.date().isoformat(),
                symbol=action["symbol"], horizon=horizon, winner_variant=action.get("winner_variant"),
                signal_direction="short", actionable=True, execution_eligible=False,
                execution_action="exit_long" if before == "long" else "no_action",
                reason="short_signal_liquidation" if before == "long" else "short_entry_not_supported_masi",
                position_before=before, position_after="flat", opportunity_input_hash=action.get("input_hash"),
                fill_price=fill, quantity=quantity, notional=notional,
                delay_sessions=action.get("delay_sessions"),
            ))

        # Scheduled exits execute on their stored exit day; barrier checks are strictly before it.
        for key, lot in list(lots.items()):
            if day >= lot["scheduled_exit_date"]:
                row_price = price_row(lot["symbol"], day)
                exit_col = _price_col(clean_prices[lot["symbol"]], ("Open", "open"))
                if row_price is not None and exit_col:
                    fill = _finite_price(row_price[exit_col])
                    if fill is not None:
                        close_lot(key, day, fill, "scheduled_exit")
        if stop_loss_pct is not None or take_profit_pct is not None:
            for key, lot in list(lots.items()):
                if not (lot["entry_date"] < day < lot["scheduled_exit_date"]):
                    continue
                bar = price_row(lot["symbol"], day)
                if bar is None:
                    continue
                frame = clean_prices[lot["symbol"]]
                open_col = _price_col(frame, ("Open", "open"))
                low_col = _price_col(frame, ("Low", "low"))
                high_col = _price_col(frame, ("High", "high"))
                if not open_col or not low_col or not high_col:
                    continue
                open_price = _finite_price(bar[open_col])
                low = _finite_price(bar[low_col])
                high = _finite_price(bar[high_col])
                if open_price is None or low is None or high is None:
                    continue
                stop = lot["entry_price"] * (1.0 - stop_loss_pct) if stop_loss_pct else None
                take = lot["entry_price"] * (1.0 + take_profit_pct) if take_profit_pct else None
                fill = reason = None
                if stop is not None and open_price <= stop:
                    fill, reason = open_price, "stop_loss_gap"
                elif take is not None and open_price >= take:
                    fill, reason = open_price, "take_profit_gap"
                elif stop is not None and low <= stop:
                    fill, reason = stop, "stop_loss"
                elif take is not None and high >= take:
                    fill, reason = take, "take_profit"
                if fill is not None:
                    closed = close_lot(key, day, float(fill), str(reason))
                    if closed is not None:
                        events.append(_event(
                            methodology_version=METHODOLOGY_VERSION, scenario=scenario,
                            decision_date=closed["decision_date"], action_date=day.date().isoformat(),
                            symbol=closed["symbol"], horizon=horizon,
                            winner_variant=closed.get("winner_variant"), signal_direction="long",
                            actionable=True, execution_eligible=True, execution_action="exit_long",
                            reason=reason, position_before="long", position_after="flat",
                            opportunity_input_hash=closed.get("input_hash"), fill_price=float(fill),
                            quantity=closed["quantity"], notional=closed["notional"], delay_sessions=None,
                        ))

        for action in [item for item in day_actions if item.get("signal_direction") != "short"]:
            key = (action["symbol"], horizon)
            before = "long" if key in lots else "flat"
            execution_action = "no_action"
            reason = "no_actionable_winner"
            fill = quantity = notional = None
            opportunity = action.get("opportunity")
            if action.get("winner_variant") is None:
                if before == "long":
                    execution_action, reason = "hold", "hold_existing_exposure"
            elif before == "long":
                execution_action, reason = "hold", "one_live_lot"
            elif not action.get("gate_pass", True):
                reason = "user_gate_rejected_winner"
            elif opportunity is None:
                execution_action, reason = "skip", "missing_opportunity_payload"
            else:
                kelly = half_kelly_from_selection_sample(
                    opportunity.selection_observations,
                    decision_date=opportunity.decision_date,
                    multiplier=config.half_kelly_multiplier,
                    minimum_observations=config.minimum_kelly_observations,
                )
                if kelly is None:
                    execution_action, reason = "skip", "insufficient_point_in_time_kelly_history"
                elif kelly <= 0:
                    execution_action, reason = "skip", "non_positive_kelly"
                else:
                    bar = price_row(action["symbol"], day)
                    frame = clean_prices[action["symbol"]]
                    open_col = _price_col(frame, ("Open", "open"))
                    fill = _finite_price(bar[open_col]) if bar is not None and open_col else None
                    if fill is None:
                        execution_action, reason = "skip", "invalid_entry_open"
                    else:
                        equity = cash + sum(lot["quantity"] * lot["entry_price"] for lot in lots.values())
                        desired = min(equity * kelly, equity * config.max_position_fraction)
                        volume_col = _price_col(frame, ("Volume", "volume"))
                        decision_date = pd.Timestamp(action["decision_date"])
                        # Positional tail-20 window instead of masking the whole frame per entry
                        # (the second O(frame×entries) hot spot alongside daily mark-to-market).
                        hist_end = int(frame.index.searchsorted(decision_date, side="right"))
                        adv20 = None
                        if volume_col and hist_end >= 20:
                            close_col = _price_col(frame, ("Close", "close", "Adj Close"))
                            if close_col:
                                window = frame.iloc[max(0, hist_end - 20):hist_end]
                                adv20 = float((window[volume_col] * window[close_col]).mean())
                        if not adv20 or adv20 <= 0:
                            execution_action, reason = "skip", "adv20_unavailable"
                        else:
                            capacity = adv20 * config.capacity_fraction
                            if desired > capacity and not config.allow_partial_fills:
                                execution_action, reason = "skip", "capacity_rejected"
                            else:
                                notional = min(desired, capacity, cash / (1.0 + cost_rate))
                                quantity = notional / fill if notional > 0 else 0.0
                                if quantity <= 0:
                                    execution_action, reason = "skip", "insufficient_cash"
                                else:
                                    entry_cost = notional * cost_rate
                                    cash -= notional + entry_cost
                                    total_cost += entry_cost
                                    turnover += notional
                                    frame_pos = int(frame.index.get_loc(day))
                                    decision_pos = int(frame.index.searchsorted(pd.Timestamp(action["decision_date"]), side="right")) - 1
                                    exit_pos = decision_pos + int(opportunity.exit_lag_bars)
                                    scheduled_exit = frame.index[min(exit_pos, len(frame) - 1)]
                                    trade = {
                                        "symbol": action["symbol"], "horizon": horizon,
                                        "variant": opportunity.variant, "direction": "long",
                                        "decision_date": action["decision_date"], "entry_date": day.date().isoformat(),
                                        "entry_price": fill, "entry_notional": notional, "entry_cost": entry_cost,
                                        "quantity": quantity, "kelly_fraction": kelly, "status": "open",
                                    }
                                    trades.append(trade)
                                    lots[key] = {
                                        "symbol": action["symbol"], "horizon": horizon, "quantity": quantity,
                                        "notional": notional, "entry_price": fill, "entry_cost": entry_cost,
                                        "entry_date": day, "scheduled_exit_date": scheduled_exit, "trade": trade,
                                        "decision_date": action["decision_date"],
                                        "winner_variant": action.get("winner_variant"),
                                        "input_hash": action.get("input_hash"),
                                    }
                                    execution_action, reason = "enter_long", "long_entry"
            events.append(_event(
                methodology_version=METHODOLOGY_VERSION, scenario=scenario,
                decision_date=action["decision_date"], action_date=day.date().isoformat(),
                symbol=action["symbol"], horizon=horizon, winner_variant=action.get("winner_variant"),
                signal_direction=action.get("signal_direction"), actionable=bool(action.get("actionable")),
                execution_eligible=bool(action.get("execution_eligible")), execution_action=execution_action,
                reason=reason, position_before=before,
                position_after="long" if key in lots else "flat", opportunity_input_hash=action.get("input_hash"),
                fill_price=fill, quantity=quantity, notional=notional, delay_sessions=action.get("delay_sessions"),
            ))
            if execution_action == "skip":
                rejected.append({"decision_date": action["decision_date"], "symbol": action["symbol"], "reason": reason})

        market_value = 0.0
        for lot in lots.values():
            marks = mark_series.get(lot["symbol"])
            mark = lot["entry_price"]
            if marks is not None:
                pos = int(marks["index"].searchsorted(day, side="right")) - 1
                if pos >= 0:
                    candidate = _finite_price(marks["values"][pos])
                    if candidate is not None:
                        mark = candidate
            market_value += lot["quantity"] * mark
        equity = cash + market_value
        if not all(np.isfinite(value) for value in (cash, market_value, equity)) or equity <= 0:
            raise RuntimeError(f"non-finite portfolio accounting state on {day.date().isoformat()}")
        curve.append({
            "date": day.date().isoformat(), "cash": cash, "market_value": market_value,
            "equity": equity, "exposure": market_value / equity if equity > 0 else 0.0,
            "open_lots": len(lots),
        })

    for lot in lots.values():
        lot["trade"]["status"] = "open_at_end"
    from core.quant_core.historical_portfolio import portfolio_statistics, execution_assumptions

    return {
        "horizon": horizon, "equity_curve": curve, "trades": trades, "rejected_trades": rejected,
        "statistics": portfolio_statistics(curve, trades, rejected, config, total_cost, turnover),
        "assumptions": execution_assumptions(config), "execution_events": events,
        "liquidations": liquidations,
    }


def _decision_json(decision: AsOfDecision) -> dict[str, Any]:
    direction = decision.signal_direction
    execution_eligible = bool(decision.actionable and direction == "long")
    return {
        "status": decision.status,
        "signal_direction": direction,
        "actionable": decision.actionable,
        "actionability_reasons": list(decision.actionability_reasons),
        "rank": list(decision.rank) if decision.rank is not None else None,
        "category_scores": dict(decision.category_scores),
        "aggregate_score": decision.aggregate_score,
        "bucket": decision.bucket,
        "computation_rejection_reasons": list(decision.computation_rejection_reasons),
        "execution_eligible": execution_eligible,
        "execution_rejection_reason": (
            "short_entry_not_supported_masi"
            if decision.actionable and direction == "short"
            else None
        ),
        "evidence": decision.evidence,
    }


def _source_records(
    *,
    config: dict[str, Any],
    prices: dict[str, pd.DataFrame],
    scores: dict[tuple[str, str], dict[str, pd.Series]],
    decision_dates: pd.DatetimeIndex,
) -> list[tuple[str, list[Any], Any]]:
    records: list[tuple[str, list[Any], Any]] = [
        ("methodology", [METHODOLOGY_VERSION], METHODOLOGY_VERSION),
    ]
    for symbol in sorted(config.get("resolved_universe") or config.get("symbols") or []):
        records.append(("universe", [symbol], True))
    for value in decision_dates:
        records.append(("weekly_calendar", [pd.Timestamp(value).date()], True))
    for symbol, frame in sorted(prices.items()):
        clean = _clean_frame(frame)
        for timestamp, row in clean.iterrows():
            records.append((
                "ohlcv", [symbol, pd.Timestamp(timestamp).date()],
                {str(column): row[column] for column in clean.columns},
            ))
    for (symbol_horizon, variant), categories in sorted(scores.items()):
        symbol, horizon = symbol_horizon.split("|", 1)
        oos_dates: set[pd.Timestamp] = set()
        for category, series in sorted(categories.items()):
            for timestamp, value in series.sort_index().items():
                date_value = pd.Timestamp(timestamp).date()
                records.append((
                    "score_history", [symbol, horizon, variant, category, date_value], value,
                ))
                oos_dates.add(pd.Timestamp(timestamp))
        for timestamp in sorted(oos_dates):
            records.append(("persisted_oos", [symbol, horizon, variant, timestamp.date()], True))
    return records


def _validate_decision_grid(
    rows: list[tuple[pd.Timestamp, str, str, str, AsOfDecision]],
    *,
    expected_size: int,
) -> None:
    if not rows or len(rows) != expected_size:
        raise ValueError(f"grid_size invariant: expected {expected_size}, got {len(rows)}")
    keys = [(date.date(), symbol.upper(), horizon, variant) for date, symbol, horizon, variant, _ in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("natural_key_uniqueness invariant")
    winners: dict[tuple[Any, str, str], int] = {}
    for date_value, symbol, horizon, _variant, decision in rows:
        if decision.status not in {
            "no_price_data", "no_score_data", "stale_score", "insufficient_history",
            "evidence_unavailable", "evaluated",
        }:
            raise ValueError("status_enum invariant")
        if set(decision.category_scores) != {"tendance", "momentum", "oscillation", "volume"}:
            raise ValueError("category_scores_schema invariant")
        if decision.status == "evaluated" and decision.evidence is None:
            raise ValueError("evaluated_evidence invariant")
        if decision.actionable:
            if decision.status != "evaluated" or decision.actionability_reasons or decision.opportunity is None:
                raise ValueError("actionable_payload invariant")
            evidence = decision.evidence or {}
            provenance = dict(decision.opportunity.provenance)
            for field in (
                "edge_score", "expected_return_net", "action_expected_return_net",
                "action_expected_return_net_ci_lower", "hit_ci_lower", "proven_edge_net", "gates",
                "mc_luck_pvalue_net_adj", "label_shuffle_pvalue_net_adj", "freshness_status",
            ):
                if evidence.get(field) != provenance.get(field):
                    raise ValueError(f"evidence_provenance_equality invariant: {field}")
        elif decision.opportunity is not None:
            raise ValueError("non_actionable_opportunity_null invariant")
        if decision.evidence is not None and decision.evidence.get("decision_edge_cost_bps") != V5_DECISION_EDGE_COST_BPS:
            raise ValueError("decision_edge_cost invariant")
        if decision.actionable:
            key = (date_value.date(), symbol.upper(), horizon)
            winners[key] = winners.get(key, 0) + 1


def _has_newer_successful_overlap(db, models, run, config: dict[str, Any]) -> bool:
    start = pd.Timestamp(config["start_date"]).date()
    end = pd.Timestamp(config["end_date"]).date()
    candidates = db.query(models.HistoricalOpportunityMaterializationRun).filter(
        models.HistoricalOpportunityMaterializationRun.status == "succeeded",
        models.HistoricalOpportunityMaterializationRun.methodology_version == METHODOLOGY_VERSION,
        models.HistoricalOpportunityMaterializationRun.id != run.id,
    ).all()
    for candidate in candidates:
        if (candidate.created_at, str(candidate.id)) <= (run.created_at, str(run.id)):
            continue
        stored = candidate.config_json or {}
        try:
            other_start = pd.Timestamp(stored["start_date"]).date()
            other_end = pd.Timestamp(stored["end_date"]).date()
        except (KeyError, TypeError, ValueError):
            continue
        if other_start <= end and other_end >= start:
            return True
    return False


def materialize_historical_opportunities(materialization_run_id: str) -> None:
    """Build PIT candidates once and replace only the requested date/symbol slice."""

    from services.api.app import models
    from services.api.app.db import _ensure_session_factory

    Session = _ensure_session_factory()
    db = Session()
    run = None
    started_clock = time.perf_counter()
    stage_times: dict[str, float] = {}
    try:
        run = db.query(models.HistoricalOpportunityMaterializationRun).filter_by(
            id=UUID(materialization_run_id)
        ).with_for_update().first()
        if run is None or run.status not in {"queued", "running"}:
            return
        run.status = "running"
        run.started_at = _utcnow()
        run.progress_json = {"stage": "loading_fold_scoped_oos_history", "progress_pct": 1}
        db.commit()

        config = dict(run.config_json or {})
        load_started = time.perf_counter()
        prices, raw_scores = _load_inputs(db, config)
        stage_times["initial_input_load_seconds"] = time.perf_counter() - load_started
        dates = _load_weekly_masi_calendar(db, config)
        if len(dates) == 0:
            raise ValueError("grid_calendar invariant: MASI weekly calendar is empty")
        hash_started = time.perf_counter()
        initial_records = _source_records(
            config=config, prices=prices, scores=raw_scores, decision_dates=dates,
        )
        captured_watermark = source_watermark_v1(initial_records)
        stage_times["initial_source_hash_seconds"] = time.perf_counter() - hash_started
        config["_system"] = {
            **dict(config.get("_system") or {}),
            "source_watermark_v1": captured_watermark,
        }
        run.config_json = config
        db.commit()
        selectors = {}
        for horizon in DECISION_HORIZONS:
            keyed = {
                (symbol, mode): raw_scores.get((f"{symbol}|{horizon}", mode), {})
                for symbol in prices for mode in TECHNICAL_SIGNAL_MODE_NAMES
            }
            selectors[horizon] = _build_selector(keyed, config)

        computation_started = time.perf_counter()
        decision_rows: list[tuple[pd.Timestamp, str, str, str, AsOfDecision]] = []
        total = max(1, len(dates) * len(DECISION_HORIZONS) * len(TECHNICAL_SIGNAL_MODE_NAMES))
        completed = 0
        for decision in dates:
            sliced = {symbol: frame.loc[frame.index <= decision].copy() for symbol, frame in prices.items()}
            for horizon in DECISION_HORIZONS:
                for variant in TECHNICAL_SIGNAL_MODE_NAMES:
                    for symbol, result in selectors[horizon](decision, horizon, variant, sliced):
                        decision_rows.append((decision, symbol, horizon, variant, result))
                    completed += 1
            if completed % 96 == 0:
                run.progress_json = {
                    "stage": "evaluating_point_in_time_candidates",
                    "progress_pct": min(90, round(completed / total * 90)),
                    "decision_dates_completed": int(completed / (len(DECISION_HORIZONS) * len(TECHNICAL_SIGNAL_MODE_NAMES))),
                    "decision_dates_total": len(dates),
                }
                db.commit()

        stage_times["grid_computation_seconds"] = time.perf_counter() - computation_started
        universe = config.get("resolved_universe") or config.get("symbols") or sorted(prices)
        expected_grid_size = (
            len(universe) * len(dates) * len(DECISION_HORIZONS) * len(TECHNICAL_SIGNAL_MODE_NAMES)
        )
        _validate_decision_grid(decision_rows, expected_size=expected_grid_size)

        winner_keys: set[tuple[str, str, str, str]] = set()
        best: dict[tuple[str, str, str], tuple[str, tuple[int, float, float, float]]] = {}
        pending_hashes: list[tuple[dict[str, Any], str]] = []
        for decision_date, symbol, horizon, variant, result in decision_rows:
            if not result.actionable or result.rank is None:
                continue
            key = (decision_date.date().isoformat(), symbol.upper(), horizon)
            previous = best.get(key)
            if previous is None or result.rank > previous[1]:
                best[key] = (variant, result.rank)
        for key, (variant, _rank) in best.items():
            winner_keys.add((*key, variant))

        # Evidence computation is intentionally unlocked. Only the authoritative
        # source recheck and atomic replace are serialized.
        if db.get_bind().dialect.name == "postgresql":
            from sqlalchemy import text

            db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:version))"), {"version": METHODOLOGY_VERSION})
        final_load_started = time.perf_counter()
        final_prices, final_scores = _load_inputs(db, config)
        final_dates = _load_weekly_masi_calendar(db, config)
        final_records = _source_records(
            config=config, prices=final_prices, scores=final_scores, decision_dates=final_dates,
        )
        final_watermark = source_watermark_v1(final_records)
        stage_times["final_input_reload_and_hash_seconds"] = time.perf_counter() - final_load_started
        if final_watermark != captured_watermark:
            raise RuntimeError("stale_input: source watermark changed during computation")
        if _has_newer_successful_overlap(db, models, run, config):
            raise RuntimeError("stale_input: newer successful overlapping v5 materialization exists")

        transaction_started = time.perf_counter()
        start = pd.Timestamp(config["start_date"]).date()
        end = pd.Timestamp(config["end_date"]).date()
        delete_query = db.query(models.HistoricalTradeOpportunity).filter(
            models.HistoricalTradeOpportunity.methodology_version == METHODOLOGY_VERSION,
            models.HistoricalTradeOpportunity.decision_date >= start,
            models.HistoricalTradeOpportunity.decision_date <= end,
        )
        requested_symbols = list(config.get("symbols") or [])
        if requested_symbols:
            delete_query = delete_query.filter(models.HistoricalTradeOpportunity.symbol.in_(requested_symbols))
        delete_query.delete(synchronize_session=False)
        db.flush()

        for decision_date, symbol, horizon, variant, result in decision_rows:
            decision_payload = _decision_json(result)
            opportunity_payload = asdict(result.opportunity) if result.opportunity is not None else None
            key = (decision_date.date().isoformat(), symbol.upper(), horizon, variant)
            hash_payload = {
                "methodology_version": METHODOLOGY_VERSION,
                "decision_date": key[0], "symbol": key[1], "horizon": horizon,
                "variant": variant, "decision": decision_payload,
            }
            input_hash = provenance_hash(hash_payload)
            pending_hashes.append((hash_payload, input_hash))
            db.add(models.HistoricalTradeOpportunity(
                methodology_version=METHODOLOGY_VERSION,
                decision_date=decision_date.date(), symbol=symbol.upper(), horizon=horizon, variant=variant,
                accepted=False, status=result.status, actionable=result.actionable,
                reconstructed_dashboard_winner=key in winner_keys,
                rank_json=list(result.rank or ()), decision_json=decision_payload,
                opportunity_json=opportunity_payload,
                input_hash=input_hash, materialization_run_id=run.id,
            ))
        sample_count = min(200, len(pending_hashes))
        if sample_count:
            step = max(1, len(pending_hashes) // sample_count)
            sample = pending_hashes[::step][:sample_count]
            if any(provenance_hash(payload) != stored_hash for payload, stored_hash in sample):
                raise ValueError("input_hash_recomputation invariant")
        run.status = "succeeded"
        run.completed_at = _utcnow()
        run.progress_json = {
            "stage": "completed", "progress_pct": 100,
            "candidate_count": len(decision_rows), "winner_count": len(winner_keys),
            "stage_elapsed_seconds": stage_times,
            "input_record_count": len(initial_records),
            "output_row_count": len(decision_rows),
        }
        run.coverage_json = {
            "start": start.isoformat(), "end": end.isoformat(),
            "symbols": sorted(prices), "decision_date_count": len(dates),
            "horizons": list(DECISION_HORIZONS), "variants": list(TECHNICAL_SIGNAL_MODE_NAMES),
            "grid_size": len(decision_rows),
        }
        stage_times["final_transaction_seconds"] = time.perf_counter() - transaction_started
        run.progress_json["total_elapsed_seconds"] = time.perf_counter() - started_clock
        db.commit()
    except Exception as exc:
        db.rollback()
        if run is None:
            run = db.query(models.HistoricalOpportunityMaterializationRun).filter_by(
                id=UUID(materialization_run_id)
            ).first()
        if run is not None:
            run.status = "failed"
            run.error_message = f"{type(exc).__name__}: {exc}"[:4000]
            run.completed_at = _utcnow()
            stale = "stale_input" in str(exc)
            run.progress_json = {
                "stage": "failed",
                "progress_pct": (run.progress_json or {}).get("progress_pct", 0),
                "failure_reason": "stale_input" if stale else "validation_or_computation_failure",
                "stage_elapsed_seconds": stage_times,
                "total_elapsed_seconds": time.perf_counter() - started_clock,
            }
            db.commit()
    finally:
        db.close()


def execute_historical_portfolio_backtest(run_id: str) -> None:
    from services.api.app import models
    from services.api.app.db import _ensure_session_factory
    from services.api.app.market_data_loader import load_ohlcv_for_symbol

    Session = _ensure_session_factory()
    db = Session()
    row = None
    try:
        row = db.query(models.HistoricalPortfolioBacktestRun).filter_by(id=UUID(run_id)).with_for_update().first()
        if row is None:
            return
        if row.status not in {"queued", "running"}:
            return
        row.status = "running"
        row.started_at = _utcnow()
        row.error_message = None
        row.diagnostics_json = {"stage": "loading_materialized_pit_opportunities", "progress_pct": 5}
        db.commit()

        config = dict(row.config_json or {})
        from services.api.app.services.historical_opportunity_store import opportunity_store_coverage
        coverage = opportunity_store_coverage(db, config)
        if not coverage["available"]:
            start = pd.Timestamp(config["start_date"]).date()
            end = pd.Timestamp(config["end_date"]).date()
            materialization_error = None
            failed_runs = db.query(models.HistoricalOpportunityMaterializationRun).filter_by(
                status="failed", methodology_version=METHODOLOGY_VERSION,
            ).order_by(models.HistoricalOpportunityMaterializationRun.completed_at.desc()).all()
            for failed_run in failed_runs:
                failed_config = failed_run.config_json or {}
                try:
                    failed_start = pd.Timestamp(failed_config["start_date"]).date()
                    failed_end = pd.Timestamp(failed_config["end_date"]).date()
                except (KeyError, TypeError, ValueError):
                    continue
                if failed_start <= end and failed_end >= start:
                    materialization_error = failed_run.error_message
                    break
            message = "PIT opportunity store does not cover the requested period; materialization failed"
            if materialization_error:
                message += f": {materialization_error}"
            raise ValueError(message)
        start = pd.Timestamp(config["start_date"]).date()
        end = pd.Timestamp(config["end_date"]).date()
        requested_symbols = list(config.get("symbols") or [])
        requested_horizons = tuple(
            item for item in DECISION_HORIZONS if item in set(config.get("horizons") or DECISION_HORIZONS)
        )
        if not requested_horizons:
            raise ValueError("At least one decision horizon is required")

        def _scoped(query):
            query = query.filter(
                models.HistoricalTradeOpportunity.methodology_version == METHODOLOGY_VERSION,
                models.HistoricalTradeOpportunity.decision_date >= start,
                models.HistoricalTradeOpportunity.decision_date <= end,
                models.HistoricalTradeOpportunity.horizon.in_(requested_horizons),
            )
            if requested_symbols:
                query = query.filter(models.HistoricalTradeOpportunity.symbol.in_(requested_symbols))
            return query

        # The ledger is loaded in three scoped passes rather than one blanket .all(): the full
        # grid is ~50x the winner count and carries every decision_json, which dominates both
        # runtime and memory. Keys must still be enumerated in full — replay emits one baseline
        # execution event per (decision_date, symbol, horizon) INCLUDING keys with no winner.
        key_rows = _scoped(db.query(
            models.HistoricalTradeOpportunity.decision_date,
            models.HistoricalTradeOpportunity.symbol,
            models.HistoricalTradeOpportunity.horizon,
        )).distinct().all()
        winner_rows = _scoped(db.query(models.HistoricalTradeOpportunity).filter(
            models.HistoricalTradeOpportunity.reconstructed_dashboard_winner.is_(True),
        )).all()
        stored_candidate_count = _scoped(
            db.query(func.count(models.HistoricalTradeOpportunity.decision_date))
        ).scalar() or 0
        min_edge_score = float(config.get("min_edge_score", 50.0))
        configured_conditions = config.get("required_edge_conditions")
        required_edge_conditions = list(
            DEFAULT_EDGE_CONDITIONS if configured_conditions is None else configured_conditions
        )
        winners_by_key: dict[tuple[Any, str, str], Any] = {}
        for item in winner_rows:
            key = (item.decision_date, item.symbol.upper(), item.horizon)
            if key in winners_by_key:
                raise ValueError(f"winner uniqueness violated for {key}")
            winners_by_key[key] = item
        keys = sorted({(item[0], str(item[1]).upper(), item[2]) for item in key_rows})
        replay_decisions: list[dict[str, Any]] = []
        opportunities: list[HistoricalOpportunity] = []
        for key in keys:
            winner = winners_by_key.get(key)
            decision = dict(winner.decision_json or {}) if winner is not None else {}
            opportunity = (
                _opportunity_from_json(winner.opportunity_json)
                if winner is not None and winner.opportunity_json is not None
                else None
            )
            if opportunity is not None:
                opportunities.append(opportunity)
            evidence = decision.get("evidence") if isinstance(decision.get("evidence"), dict) else {}
            gate_pass = bool(winner is not None and passes_edge_policy(
                evidence, min_edge_score=min_edge_score, required_conditions=required_edge_conditions,
            ))
            replay_decisions.append({
                "decision_date": key[0].isoformat(), "symbol": key[1], "horizon": key[2],
                "winner_variant": winner.variant if winner is not None else None,
                "signal_direction": decision.get("signal_direction") if winner is not None else None,
                "actionable": bool(winner.actionable) if winner is not None else False,
                "execution_eligible": bool(decision.get("execution_eligible")) if winner is not None else False,
                "input_hash": winner.input_hash if winner is not None else None,
                "opportunity": opportunity, "gate_pass": gate_pass,
            })
        # The literal-snapshot audit only ever looks up the ~13 DashboardSnapshot dates, so the
        # candidate pool is scoped to those dates instead of every actionable row in the window.
        snapshot_dates = [
            value for (value,) in db.query(models.DashboardSnapshot.as_of_date).filter(
                models.DashboardSnapshot.as_of_date >= start,
                models.DashboardSnapshot.as_of_date <= end,
            ).distinct().all()
        ]
        candidate_rows = _scoped(db.query(models.HistoricalTradeOpportunity).filter(
            models.HistoricalTradeOpportunity.decision_date.in_(snapshot_dates),
        )).all() if snapshot_dates else []
        candidate_lookup = {
            (item.decision_date.isoformat(), item.horizon, item.symbol.upper(), item.variant):
                _opportunity_from_json(item.opportunity_json)
            for item in candidate_rows if item.opportunity_json is not None
        }
        symbols = sorted({key[1] for key in keys})
        prices = _load_prices(db, symbols)
        if not prices:
            raise ValueError("Market data for materialized PIT opportunities is unavailable")
        # Clean prices and the trading-day union once: both are identical across all 12
        # (horizon × capacity-scenario) sleeve simulations, so deriving them per call was
        # ~92% wasted work on a full-universe run.
        clean_prices = {symbol: _clean_frame(frame) for symbol, frame in prices.items()}
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        all_dates = sorted({
            timestamp for frame in clean_prices.values() for timestamp in frame.index
            if start_ts <= timestamp <= end_ts
        })
        row.diagnostics_json = {
            "stage": "simulating_stored_opportunities", "progress_pct": 15,
            "stored_candidate_count": stored_candidate_count,
            "winner_opportunity_count": len(opportunities),
        }
        db.commit()

        all_scenarios: dict[str, Any] = {}
        for scenario_idx, cap in enumerate(CAPACITY_SCENARIOS):
            engine_config = PortfolioBacktestConfig(
                initial_capital=float(config.get("initial_capital", 100_000.0)),
                cost_bps_per_side=float(config.get("cost_bps_per_side", 33.0)),
                slippage_bps_per_side=float(config.get("slippage_bps_per_side", 5.0)),
                half_kelly_multiplier=float(config.get("half_kelly_multiplier", 0.5)),
                max_position_fraction=float(config.get("max_position_fraction", 0.25)),
                capacity_fraction=cap, allow_partial_fills=bool(config.get("allow_partial_fills", True)),
                bootstrap_seed=int(config.get("bootstrap_seed", 5107)),
                bootstrap_samples=int(config.get("bootstrap_samples", 1000)),
            )
            sleeves = {
                horizon: _simulate_winner_sleeve(
                    replay_decisions, prices, engine_config, horizon=horizon,
                    clean_prices=clean_prices, all_dates=all_dates,
                )
                for horizon in requested_horizons
            }
            combined = combine_sleeves_equal_risk(sleeves, engine_config.initial_capital)
            all_scenarios[str(cap)] = {"sleeves": sleeves, "combined": combined}
            row.diagnostics_json = {"stage": "simulating_capacity_scenarios", "progress_pct": 35 + scenario_idx * 10}
            db.commit()

        selected_key = str(float(config.get("capacity_fraction", 0.01)))
        selected = all_scenarios[selected_key]
        selected_config = replace(engine_config, capacity_fraction=float(config.get("capacity_fraction", 0.01)))
        baseline_events = [
            event for sleeve in selected["sleeves"].values() for event in sleeve.get("execution_events", [])
        ]
        liquidation_rows = [
            item for sleeve in selected["sleeves"].values() for item in sleeve.get("liquidations", [])
        ]
        barrier_scenario = None
        barrier_events: list[dict[str, Any]] = []
        stop_loss_pct = config.get("stop_loss_pct")
        take_profit_pct = config.get("take_profit_pct")
        if stop_loss_pct is not None or take_profit_pct is not None:
            barrier_sleeves = {
                horizon: _simulate_winner_sleeve(
                    replay_decisions, prices, selected_config, horizon=horizon,
                    stop_loss_pct=float(stop_loss_pct) if stop_loss_pct is not None else None,
                    take_profit_pct=float(take_profit_pct) if take_profit_pct is not None else None,
                    scenario="barrier",
                    clean_prices=clean_prices, all_dates=all_dates,
                )
                for horizon in requested_horizons
            }
            barrier_combined = combine_sleeves_equal_risk(barrier_sleeves, selected_config.initial_capital)
            baseline_by_key = {
                (item["decision_date"], item["symbol"], item["horizon"]): item
                for item in baseline_events
            }
            for sleeve in barrier_sleeves.values():
                for event in sleeve.get("execution_events", []):
                    baseline = baseline_by_key.get((event["decision_date"], event["symbol"], event["horizon"]))
                    if baseline is None or any(
                        event.get(field) != baseline.get(field)
                        for field in ("execution_action", "reason", "action_date", "fill_price", "position_after")
                    ):
                        barrier_events.append(event)
            barrier_scenario = {
                "config": {"stop_loss_pct": stop_loss_pct, "take_profit_pct": take_profit_pct},
                "capacity_fraction": selected_config.capacity_fraction,
                "sleeves": barrier_sleeves, "combined": barrier_combined,
            }
        masi = pd.Series(dtype=float)
        try:
            masi_frame = _clean_frame(load_ohlcv_for_symbol(db, "MASI", "1D"))
            close_col = _price_col(masi_frame, ("Close", "close", "Adj Close"))
            if close_col:
                masi = masi_frame[close_col]
        except Exception:
            pass
        benchmarks = benchmark_curves(selected["combined"]["equity_curve"], masi)
        combined_stats = dict(selected["combined"].get("statistics", {}))
        if benchmarks.get("available"):
            full_return = benchmarks["full_investment_masi"]["total_return"]
            matched_return = benchmarks["exposure_matched_masi"]["total_return"]
            strategy_return = combined_stats.get("absolute_return")
            combined_stats.update({
                "full_investment_masi_return": full_return,
                "exposure_matched_masi_return": matched_return,
                "excess_return_vs_full_investment_masi": (
                    float(strategy_return) - float(full_return) if strategy_return is not None else None
                ),
                "excess_return_vs_exposure_matched_masi": (
                    float(strategy_return) - float(matched_return) if strategy_return is not None else None
                ),
            })

        snapshots = db.query(models.DashboardSnapshot).filter(
            models.DashboardSnapshot.as_of_date >= pd.Timestamp(config["start_date"]).date(),
            models.DashboardSnapshot.as_of_date <= pd.Timestamp(config["end_date"]).date(),
        ).order_by(models.DashboardSnapshot.as_of_date.asc()).all()
        audit = snapshot_audit(opportunities, [{
            "as_of_date": item.as_of_date, "horizon": item.horizon, "payload_jsonb": item.payload_jsonb,
        } for item in snapshots])
        literal_opportunities: list[HistoricalOpportunity] = []
        literal_unavailable: list[dict[str, Any]] = []
        for snapshot in snapshots:
            payload = snapshot.payload_jsonb if isinstance(snapshot.payload_jsonb, dict) else {}
            stocks = payload.get("stocks") if isinstance(payload.get("stocks"), list) else []
            for stock in stocks:
                best = stock.get("best_signal") if isinstance(stock, dict) else None
                symbol = str(stock.get("symbol") or "").strip().upper() if isinstance(stock, dict) else ""
                variant = str(best.get("variant") or "").strip() if isinstance(best, dict) else ""
                if not symbol or variant not in TECHNICAL_SIGNAL_MODE_NAMES:
                    continue
                candidate = candidate_lookup.get((snapshot.as_of_date.isoformat(), snapshot.horizon, symbol, variant))
                if candidate is None:
                    literal_unavailable.append({
                        "as_of_date": snapshot.as_of_date.isoformat(), "horizon": snapshot.horizon,
                        "symbol": symbol, "variant": variant,
                        "reason": "point_in_time_selection_sample_unavailable",
                    })
                    continue
                direction = str(best.get("direction") or candidate.direction).strip().lower()
                if direction not in {"long", "short"}:
                    continue
                literal_opportunities.append(HistoricalOpportunity(
                    **{
                        **candidate.__dict__,
                        "direction": direction,
                        "bucket": str(best.get("bucket") or candidate.bucket),
                        "entry_lag_bars": int(best.get("entry_lag_bars") or candidate.entry_lag_bars),
                        "exit_lag_bars": int(best.get("exit_lag_bars") or candidate.exit_lag_bars),
                        "entry_price_kind": str(best.get("entry_price_kind") or candidate.entry_price_kind),
                        "exit_price_kind": str(best.get("exit_price_kind") or candidate.exit_price_kind),
                        "provenance": {
                            **dict(candidate.provenance),
                            "literal_dashboard_snapshot": True,
                            "snapshot_as_of_date": snapshot.as_of_date.isoformat(),
                            "snapshot_computed_at": snapshot.computed_at.isoformat() if snapshot.computed_at else None,
                        },
                    }
                ))
        audit["literal_opportunity_count"] = len(literal_opportunities)
        audit["unavailable_opportunities"] = literal_unavailable

        opportunity_payload = [asdict(item) for item in opportunities]
        provenance = {
            "methodology_version": METHODOLOGY_VERSION,
            "signal_modes": list(TECHNICAL_SIGNAL_MODE_NAMES),
            "horizons": list(requested_horizons),
            "source": "persisted fold-scoped WFO out-of-sample score history; current WfoGlobalSignal and SignalBestEvidenceSnapshot rows are not read",
            "score_history_requires_is_oos": True,
            "data_symbols": sorted(prices),
            "coverage_start": coverage["requested_start"],
            "coverage_end": coverage["requested_end"],
            "edge_policy": {
                "min_edge_score": min_edge_score,
                "required_conditions": required_edge_conditions,
                "side_policy": "winner_only_masi_cash_equity",
            },
            "opportunity_store_materialization_runs": coverage["materialization_run_ids"],
            "input_hash": provenance_hash({"config": config, "opportunities": opportunity_payload}),
        }
        validation = {
            "all_eight_variants_evaluated": list(TECHNICAL_SIGNAL_MODE_NAMES),
            "cutoffs_precede_decision": all(
                (item.training_end is None or item.training_end < item.decision_date)
                and (item.selection_sample_end is None or item.selection_sample_end < item.decision_date)
                for item in opportunities
            ),
            "modeled_fills": True,
            "capacity_scenarios": list(CAPACITY_SCENARIOS),
            "horizons": list(requested_horizons),
        }
        trades = [trade for sleeve in selected["sleeves"].values() for trade in sleeve["trades"]]
        closed_trade_returns = [
            float(item["net_return"]) for item in trades if item.get("net_return") is not None
        ]
        combined_stats.update({
            "trade_count": len(trades),
            "hit_rate": (
                sum(value > 0 for value in closed_trade_returns) / len(closed_trade_returns)
                if closed_trade_returns else None
            ),
            "cost_impact_mad": sum(
                float(sleeve.get("statistics", {}).get("cost_impact_mad") or 0.0)
                for sleeve in selected["sleeves"].values()
            ),
            "rejected_trade_count": sum(
                int(sleeve.get("statistics", {}).get("rejected_trade_count") or 0)
                for sleeve in selected["sleeves"].values()
            ),
        })
        by_horizon: dict[str, dict[str, Any]] = {}
        for horizon in requested_horizons:
            items = [item for item in liquidation_rows if item["horizon"] == horizon]
            by_horizon[horizon] = {
                "count": len(items),
                "realized_pnl": sum(float(item["realized_pnl"]) for item in items),
                "liquidated_notional": sum(float(item["liquidated_notional"]) for item in items),
                "exposure_reduction_pct_of_equity_at_fill": sum(
                    float(item["exposure_reduction_pct_of_equity_at_fill"])
                    for item in items if item.get("exposure_reduction_pct_of_equity_at_fill") is not None
                ),
                "liquidation_policy_pnl_delta": sum(
                    float(item["pnl_delta_return"]) * float(item["liquidated_notional"])
                    for item in items if item.get("pnl_delta_return") is not None
                ),
            }
        liquidation_diagnostics = {
            "total": {
                "count": len(liquidation_rows),
                "realized_pnl": sum(float(item["realized_pnl"]) for item in liquidation_rows),
                "liquidated_notional": sum(float(item["liquidated_notional"]) for item in liquidation_rows),
                "exposure_reduction_pct_of_equity_at_fill": sum(
                    float(item["exposure_reduction_pct_of_equity_at_fill"])
                    for item in liquidation_rows if item.get("exposure_reduction_pct_of_equity_at_fill") is not None
                ),
                "liquidation_policy_pnl_delta": sum(
                    float(item["pnl_delta_return"]) * float(item["liquidated_notional"])
                    for item in liquidation_rows if item.get("pnl_delta_return") is not None
                ),
            },
            "by_horizon": by_horizon,
            "lots": liquidation_rows,
        }
        warnings = [
            "Fills are modeled because no historical fill dataset exists.",
            "DashboardSnapshot coverage is short and the literal audit is not statistically equivalent to the reconstruction.",
        ]
        if not audit["snapshot_dates"]:
            warnings.append("No DashboardSnapshot rows existed in the requested period; literal audit unavailable.")
        if not benchmarks.get("available"):
            warnings.append("MASI benchmark unavailable or has insufficient overlap.")

        row.provenance_json = provenance
        row.diagnostics_json = _sanitize_json({
            "stage": "completed", "progress_pct": 100, "opportunity_count": len(opportunities),
            "trade_count": len(trades), "execution_events_v1": [*baseline_events, *barrier_events],
            "liquidation_diagnostics_v1": liquidation_diagnostics,
            "winner_semantics": "v5_reconstructed_dashboard_winner",
        })
        row.opportunities_json = _sanitize_json(opportunity_payload)
        row.trades_json = _sanitize_json(trades)
        row.equity_curves_json = _sanitize_json({
            **all_scenarios,
            **({"barrier_scenario": barrier_scenario} if barrier_scenario is not None else {}),
        })
        row.benchmark_curves_json = _sanitize_json(benchmarks)
        row.statistics_json = _sanitize_json({
            "selected_capacity_fraction": float(config.get("capacity_fraction", 0.01)),
            "sleeves": {key: value["statistics"] for key, value in selected["sleeves"].items()},
            "combined": combined_stats,
        })
        row.validation_json = _sanitize_json(validation)
        row.snapshot_audit_json = _sanitize_json(audit)
        row.warnings_json = warnings
        row.status = "succeeded"
        row.completed_at = _utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        if row is None:
            row = db.query(models.HistoricalPortfolioBacktestRun).filter_by(id=UUID(run_id)).first()
        if row is not None:
            row.status = "failed"
            row.error_message = str(exc)[:4000]
            row.completed_at = _utcnow()
            row.diagnostics_json = {"stage": "failed", "progress_pct": (row.diagnostics_json or {}).get("progress_pct", 0)}
            db.commit()
    finally:
        db.close()
