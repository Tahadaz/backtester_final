from __future__ import annotations

import math
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.horizons import canonical_horizon
from core.quant_core.strategy_plan.allocation import compute_hrp_weights
from core.quant_core.strategy_plan.execution import compute_execution_plan
from core.quant_core.strategy_plan.execution_policy import build_execution_horizon_policy
from core.quant_core.strategy_plan.levels import compute_atr, detect_swing_levels

from .. import models
from ..market_data_loader import load_ohlcv_for_symbol
from ..schemas.dashboard_portfolio import (
    DashboardDailyBlotterRequest,
    DashboardDailyBlotterResponse,
    DashboardDailyBlotterRow,
    DashboardDailyBlotterSummary,
    DashboardManualPosition,
    DashboardPortfolioTicketRequest,
    DashboardPortfolioTicketResponse,
    DashboardPortfolioTicketRow,
    DashboardPortfolioTicketSummary,
    DashboardPortfolioPositionsRequest,
    DashboardPortfolioPositionsResponse,
)
from .dashboard_builder import _build_best_signal_payload, build_dashboard_payload


def _legacy_execution_horizon(horizon: str) -> str:
    if horizon == "weekly":
        return "short"
    if horizon == "quarterly":
        return "long"
    return "medium"


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _current_score(stock_payload: dict[str, Any] | None, source: str) -> float | None:
    if not stock_payload:
        return None
    scores = stock_payload.get("scores") or {}
    if source == "wfo":
        wfo = scores.get("wfo") or {}
        return _safe_float(wfo.get("aggregate_score_pct"))
    se = scores.get("signal_engine") or {}
    return _safe_float(se.get("expanded_aggregate_score_pct") or se.get("aggregate_score_pct"))


def _score_from_edge_bucket(edge: Any | None) -> float | None:
    if edge is None:
        return None
    bucket = str(getattr(edge, "bucket", "") or "")
    return {
        "strong_buy": 100.0,
        "buy": 35.0,
        "hold": 0.0,
        "sell": -35.0,
        "strong_sell": -100.0,
    }.get(bucket)


def _full_kelly_from_expectancy(edge: Any) -> float | None:
    exp = getattr(edge, "expectancy_net", None)
    if exp is None:
        return None
    p_win = _safe_float(getattr(exp, "p_win", None))
    avg_win = _safe_float(getattr(exp, "avg_win", None))
    avg_loss = _safe_float(getattr(exp, "avg_loss", None))
    if p_win is None or avg_win is None or avg_loss is None:
        return None
    loss = abs(avg_loss)
    if p_win <= 0.0 or p_win >= 1.0 or avg_win <= 0.0 or loss <= 0.0:
        return None
    b = avg_win / loss
    if b <= 0.0:
        return None
    q = 1.0 - p_win
    return max(0.0, (p_win * b - q) / b)


def _apply_sector_caps(
    weights: dict[str, float],
    sectors: dict[str, str],
    max_sector_frac: float,
) -> dict[str, float]:
    if not weights or max_sector_frac >= 1.0:
        return weights
    capped = dict(weights)
    for _ in range(10):
        changed = False
        by_sector: dict[str, list[str]] = {}
        for symbol in capped:
            by_sector.setdefault(sectors.get(symbol) or "Other", []).append(symbol)
        for symbols in by_sector.values():
            sector_weight = sum(capped.get(symbol, 0.0) for symbol in symbols)
            if sector_weight > max_sector_frac and sector_weight > 0:
                scale = max_sector_frac / sector_weight
                for symbol in symbols:
                    capped[symbol] *= scale
                changed = True
        if not changed:
            break
    return capped


def _ticket_action(direction: str | None, side_policy: str) -> str:
    if direction == "long":
        return "buy"
    if direction == "short":
        return "sell_short" if side_policy == "long_short" else "avoid_or_exit"
    return "no_trade"


def _proof_url(
    symbol: str,
    horizon: str,
    source: str,
    side_policy: str,
    variant: str | None = None,
) -> str:
    view = variant or "expanded_ta_simple"
    url = (
        f"/signals?symbol={symbol}&horizon={horizon}"
        f"&view={view}&source={source}&side={side_policy}&tab=evidence"
    )
    return url


def _position_to_schema(row: Any) -> DashboardManualPosition:
    return DashboardManualPosition(
        symbol=str(row.symbol).upper(),
        side=row.side or "long",
        quantity=float(row.quantity or 0.0),
        average_price_mad=_safe_float(row.average_price_mad),
        opened_at=row.opened_at,
        planned_holding_bars=row.planned_holding_bars,
        stop_loss=_safe_float(row.stop_loss),
        target_1=_safe_float(row.target_1),
        notes=row.notes,
    )


def _normalize_position(position: DashboardManualPosition) -> DashboardManualPosition:
    return position.model_copy(update={"symbol": position.symbol.strip().upper()})


def list_dashboard_positions(db: Session, *, owner_user_id: str) -> DashboardPortfolioPositionsResponse:
    rows = (
        db.query(models.DeskPortfolioPosition)
        .filter(models.DeskPortfolioPosition.owner_user_id == owner_user_id)
        .filter(models.DeskPortfolioPosition.status == "active")
        .order_by(models.DeskPortfolioPosition.symbol.asc())
        .all()
    )
    return DashboardPortfolioPositionsResponse(
        positions=[_position_to_schema(row) for row in rows if float(row.quantity or 0.0) > 0.0]
    )


def replace_dashboard_positions(
    db: Session,
    body: DashboardPortfolioPositionsRequest,
    *,
    owner_user_id: str,
) -> DashboardPortfolioPositionsResponse:
    incoming = {
        (pos.symbol.strip().upper(), pos.side): _normalize_position(pos)
        for pos in body.positions
        if pos.symbol.strip() and pos.quantity > 0.0
    }
    existing_rows = (
        db.query(models.DeskPortfolioPosition)
        .filter(models.DeskPortfolioPosition.owner_user_id == owner_user_id)
        .all()
    )
    existing = {(row.symbol.upper(), row.side): row for row in existing_rows}

    for key, row in existing.items():
        if key not in incoming and row.status == "active":
            row.status = "inactive"
            row.quantity = 0.0

    for key, pos in incoming.items():
        row = existing.get(key)
        if row is None:
            row = models.DeskPortfolioPosition(owner_user_id=owner_user_id, symbol=pos.symbol, side=pos.side)
            db.add(row)
        row.status = "active"
        row.quantity = float(pos.quantity)
        row.average_price_mad = pos.average_price_mad
        row.opened_at = pos.opened_at
        row.planned_holding_bars = pos.planned_holding_bars
        row.stop_loss = pos.stop_loss
        row.target_1 = pos.target_1
        row.notes = pos.notes

    db.commit()
    return list_dashboard_positions(db, owner_user_id=owner_user_id)


def _edge_for_symbol(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    cost_bps: float,
    variant: str | None = None,
) -> Any | None:
    from ..routers.analytics import _build_edge_metrics_from_db

    return _build_edge_metrics_from_db(
        symbol=symbol,
        horizon=horizon,
        source=source,
        variant=variant,
        cost_bps=cost_bps,
        db=db,
    )


def _selected_edge_for_symbol(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    cost_bps: float,
) -> tuple[Any | None, str, str | None]:
    selected_source = source
    selected_variant: str | None = None
    if source == "auto":
        best = _build_best_signal_payload(db, symbol, horizon)
        if not best:
            return None, "auto", None
        selected_source = "wfo"
        selected_variant = str(best.get("variant") or "") or None

    edge = _edge_for_symbol(
        db,
        symbol=symbol,
        horizon=horizon,
        source=selected_source,
        variant=selected_variant,
        cost_bps=cost_bps,
    )
    return edge, selected_source, selected_variant


def _manual_positions_for_blotter(
    db: Session,
    body: DashboardDailyBlotterRequest,
    *,
    owner_user_id: str | None = None,
) -> dict[str, DashboardManualPosition]:
    if body.positions is None:
        positions = list_dashboard_positions(db, owner_user_id=owner_user_id).positions if owner_user_id else []
    else:
        positions = body.positions
    out: dict[str, DashboardManualPosition] = {}
    for position in positions:
        normalized = _normalize_position(position)
        if normalized.quantity > 0.0:
            out[normalized.symbol] = normalized
    return out


def _signed_position(position: DashboardManualPosition | None) -> float:
    if position is None:
        return 0.0
    qty = float(position.quantity or 0.0)
    return qty if position.side == "long" else -qty


def _mark_to_market(
    position: DashboardManualPosition | None,
    mark_price: float | None,
) -> tuple[float | None, float | None]:
    if position is None or mark_price is None or position.quantity <= 0:
        return None, None
    value = float(position.quantity) * mark_price
    if position.average_price_mad is None:
        return value, None
    if position.side == "long":
        pnl = (mark_price - position.average_price_mad) * float(position.quantity)
    else:
        pnl = (position.average_price_mad - mark_price) * float(position.quantity)
    return round(value, 2), round(pnl, 2)


def _target_signed_for_row(
    row: DashboardPortfolioTicketRow,
    position: DashboardManualPosition | None,
    side_policy: str,
) -> tuple[str, int, list[str]]:
    current_signed = _signed_position(position)
    has_position = abs(current_signed) > 0.0
    warnings = list(row.warnings or [])
    row_shares = int(row.shares or 0)
    direction = row.direction
    action = row.action
    is_actionable_entry = row.status == "entry_zone" and row_shares > 0

    if has_position and current_signed > 0:
        if direction == "short":
            return "EXIT", 0, warnings
        if direction == "long":
            if row_shares > 0:
                target = row_shares
                if target < current_signed:
                    return "REDUCE", target, warnings
                if target > current_signed and is_actionable_entry:
                    return "BUY", target, warnings
            return "HOLD", int(round(current_signed)), warnings
        warnings.append("position_without_current_edge")
        return "REVIEW", int(round(current_signed)), warnings

    if has_position and current_signed < 0:
        if direction == "long":
            return "COVER", 0, warnings
        if direction == "short" and side_policy == "long_short":
            if row_shares > 0:
                target = -row_shares
                if abs(target) < abs(current_signed):
                    return "COVER", target, warnings
                if abs(target) > abs(current_signed) and is_actionable_entry:
                    return "SELL_SHORT", target, warnings
            return "HOLD", int(round(current_signed)), warnings
        warnings.append("short_position_requires_review")
        return "REVIEW", int(round(current_signed)), warnings

    if action == "buy" and is_actionable_entry:
        return "BUY", row_shares, warnings
    if action == "sell_short" and is_actionable_entry:
        return "SELL_SHORT", -row_shares, warnings
    if direction == "long":
        warnings.append("not_in_entry_zone" if row.status != "entry_zone" else "zero_target_size")
        return "WATCH", 0, warnings
    if direction == "short":
        warnings.append("short_blocked_by_long_only" if side_policy == "long_only" else "not_in_entry_zone")
        return "AVOID" if side_policy == "long_only" else "WATCH", 0, warnings
    warnings.append("no_executable_signal")
    return "AVOID", 0, warnings


def _execution_notes(action: str, row: DashboardPortfolioTicketRow) -> str:
    if action in {"BUY", "SELL_SHORT"}:
        return "Valid for next open only if the open remains inside the entry zone."
    if action in {"EXIT", "COVER", "REDUCE"}:
        return "Manual desk action required; daily data cannot enforce intraday execution."
    if action == "HOLD":
        return "Hold current position; review stop, target, and time stop after the next close."
    if action == "WATCH":
        return "No order now; watch because the setup is not executable at the current reference price."
    if action == "REVIEW":
        return "Position needs trader review because current holdings and edge state are not aligned."
    return "No order; keep as avoid unless the side policy or evidence changes."


def build_dashboard_daily_blotter(
    db: Session,
    body: DashboardDailyBlotterRequest,
    *,
    cost_bps: float,
    owner_user_id: str | None = None,
) -> DashboardDailyBlotterResponse:
    positions = _manual_positions_for_blotter(db, body, owner_user_id=owner_user_id)
    requested_symbols = [symbol.strip().upper() for symbol in body.symbols if symbol.strip()]
    symbols = list(dict.fromkeys([*requested_symbols, *positions.keys()]))
    if not symbols:
        ticket_summary = DashboardPortfolioTicketSummary(
            horizon=canonical_horizon(body.horizon, allow_legacy=True),
            source=body.source,
            side_policy=body.side_policy,
            total_capital_mad=round(body.total_capital_mad, 2),
            deployable_capital_mad=round(body.total_capital_mad * max(0.0, 1.0 - body.cash_buffer_pct / 100.0), 2),
            allocated_capital_mad=0.0,
            cash_buffer_mad=round(body.total_capital_mad, 2),
            expected_action_return_mad=None,
            expected_action_return_pct=None,
            selected_count=0,
            allocated_count=0,
            tradable_count=0,
        )
        ticket = DashboardPortfolioTicketResponse(summary=ticket_summary, rows=[])
        summary = DashboardDailyBlotterSummary(
            horizon=ticket_summary.horizon,
            source=ticket_summary.source,
            side_policy=ticket_summary.side_policy,
            selected_count=0,
            position_count=0,
            actionable_count=0,
            buy_count=0,
            exit_count=0,
            watch_count=0,
            total_delta_notional_mad=0.0,
        )
        return DashboardDailyBlotterResponse(summary=summary, ticket=ticket, rows=[])
    ticket_body = DashboardPortfolioTicketRequest(
        **body.model_dump(exclude={"positions", "symbols"}),
        symbols=symbols,
    )
    ticket = build_dashboard_portfolio_ticket(db, ticket_body, cost_bps=cost_bps)

    rows: list[DashboardDailyBlotterRow] = []
    for row in ticket.rows:
        position = positions.get(row.symbol)
        blotter_action, target_signed, reasons = _target_signed_for_row(row, position, body.side_policy)
        current_signed = _signed_position(position)
        delta_signed = int(round(target_signed - current_signed))
        mark_price = row.entry_reference_price
        market_value, unrealized_pnl = _mark_to_market(position, mark_price)
        rows.append(DashboardDailyBlotterRow(
            **row.model_dump(),
            blotter_action=blotter_action,
            current_side=position.side if position is not None else None,
            current_quantity=float(position.quantity if position is not None else 0.0),
            current_average_price_mad=position.average_price_mad if position is not None else None,
            current_market_value_mad=market_value,
            current_unrealized_pnl_mad=unrealized_pnl,
            target_quantity=abs(int(round(target_signed))),
            delta_quantity=delta_signed,
            delta_notional_mad=round(delta_signed * mark_price, 2) if mark_price is not None else 0.0,
            no_trade_reasons=list(dict.fromkeys(reason for reason in reasons if reason)),
            execution_notes=_execution_notes(blotter_action, row),
        ))

    actionable = {"BUY", "SELL_SHORT", "REDUCE", "COVER", "EXIT"}
    summary = DashboardDailyBlotterSummary(
        horizon=ticket.summary.horizon,
        source=ticket.summary.source,
        side_policy=ticket.summary.side_policy,
        entry_timing=ticket.summary.entry_timing,
        selected_count=len(symbols),
        position_count=len(positions),
        actionable_count=sum(1 for row in rows if row.blotter_action in actionable),
        buy_count=sum(1 for row in rows if row.blotter_action in {"BUY", "SELL_SHORT"}),
        exit_count=sum(1 for row in rows if row.blotter_action in {"EXIT", "COVER", "REDUCE"}),
        watch_count=sum(1 for row in rows if row.blotter_action in {"WATCH", "REVIEW"}),
        total_delta_notional_mad=round(sum(row.delta_notional_mad for row in rows), 2),
    )
    return DashboardDailyBlotterResponse(summary=summary, ticket=ticket, rows=rows)


def build_dashboard_portfolio_ticket(
    db: Session,
    body: DashboardPortfolioTicketRequest,
    *,
    cost_bps: float,
) -> DashboardPortfolioTicketResponse:
    horizon = canonical_horizon(body.horizon, allow_legacy=True)
    symbols = list(dict.fromkeys(symbol.strip().upper() for symbol in body.symbols if symbol.strip()))
    deployable_capital = body.total_capital_mad * max(0.0, 1.0 - body.cash_buffer_pct / 100.0)
    cash_buffer = body.total_capital_mad - deployable_capital

    metadata_rows = db.query(models.StockMaster).filter(models.StockMaster.symbol.in_(symbols)).all()
    metadata = {row.symbol: row for row in metadata_rows}

    dashboard_payload = build_dashboard_payload(db, horizon, include_edge=False)
    dashboard_by_symbol = {
        str(row.get("symbol") or "").upper(): row
        for row in list(dashboard_payload.get("stocks") or [])
        if isinstance(row, dict)
    }

    price_history: dict[str, pd.Series] = {}
    bars_by_symbol: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            bars = drop_incomplete_ohlcv_rows(load_ohlcv_for_symbol(db, symbol, body.timeframe)).sort_index()
        except Exception:
            bars = pd.DataFrame()
        bars_by_symbol[symbol] = bars
        if not bars.empty and "Close" in bars.columns:
            price_history[symbol] = bars["Close"].astype(float)

    edges: dict[str, Any | None] = {}
    edge_sources: dict[str, str] = {}
    edge_variants: dict[str, str | None] = {}
    prelim_rows: dict[str, dict[str, Any]] = {}
    eligible_symbols: list[str] = []
    sectors: dict[str, str] = {}

    exec_horizon = _legacy_execution_horizon(horizon)
    policy = build_execution_horizon_policy(exec_horizon, timeframe=body.timeframe)

    for symbol in symbols:
        meta = metadata.get(symbol)
        stock_payload = dashboard_by_symbol.get(symbol)
        sector = (getattr(meta, "sector", None) or (stock_payload or {}).get("sector") or "Other")
        sectors[symbol] = str(sector)
        warnings: list[str] = []

        edge, selected_source, selected_variant = _selected_edge_for_symbol(
            db,
            symbol=symbol,
            horizon=horizon,
            source=body.source,
            cost_bps=cost_bps,
        )
        edges[symbol] = edge
        edge_sources[symbol] = selected_source
        edge_variants[symbol] = selected_variant
        if edge is None:
            warnings.append("edge_unavailable")

        proven = bool(edge.proven_edge_net) if edge is not None else False
        direction = edge.direction if edge is not None else None
        if edge is not None and not proven:
            warnings.append("edge_not_proven")
        if body.side_policy == "long_only" and direction == "short":
            warnings.append("short_blocked_by_long_only")

        bars = bars_by_symbol.get(symbol, pd.DataFrame())
        plan: dict[str, Any] = {
            "direction": direction,
            "status": "no_setup",
            "entry_price": None,
            "entry_zone_low": None,
            "entry_zone_high": None,
            "stop_loss": None,
            "target_1": None,
            "target_2": None,
            "rr_ratio": None,
            "atr_14": None,
            "explain": "OHLCV unavailable.",
        }
        if bars.empty or not {"High", "Low", "Close"}.issubset(set(map(str, bars.columns))):
            warnings.append("ohlcv_unavailable")
        else:
            high = bars["High"].to_numpy(dtype="float64")
            low = bars["Low"].to_numpy(dtype="float64")
            close = bars["Close"].to_numpy(dtype="float64")
            atr_abs, _ = compute_atr(high, low, close, window=14)
            levels = detect_swing_levels(
                high,
                low,
                close,
                left_bars=policy.swing_left_bars,
                right_bars=policy.swing_right_bars,
                max_levels=policy.max_levels,
                lookback=policy.structural_lookback,
                max_distance_atr=policy.max_level_distance_atr,
            )
            live_score = None if body.source == "auto" else _current_score(stock_payload, selected_source)
            score = live_score
            if score is None:
                score = _score_from_edge_bucket(edge)
            if edge is not None and live_score is not None:
                if direction == "short" and live_score > 0:
                    warnings.append("score_edge_direction_mismatch")
                if direction == "long" and live_score < 0:
                    warnings.append("score_edge_direction_mismatch")
            if edge is not None and direction == "short" and score is not None and score > 0:
                score = -abs(score)
            if edge is not None and direction == "long" and score is not None and score < 0:
                score = abs(score)
            plan = compute_execution_plan(
                consensus=score,
                side_policy=body.side_policy,
                nearest_support=levels.get("nearest_support"),
                nearest_resistance=levels.get("nearest_resistance"),
                supports=list(levels.get("supports") or []),
                resistances=list(levels.get("resistances") or []),
                atr=atr_abs,
                current_close=float(close[-1]),
                entry_threshold=body.entry_threshold,
                atr_multiplier=body.atr_multiplier,
                buffer_pct=body.buffer_pct,
                min_rr=body.min_rr,
                holding_bars=policy.holding_bars,
            )
            if direction is not None and plan.get("direction") != direction:
                plan["direction"] = direction
            entry = _safe_float(plan.get("entry_price"))
            stop = _safe_float(plan.get("stop_loss"))
            target = _safe_float(plan.get("target_1"))
            geometry_bad = False
            if entry is not None and direction == "long":
                geometry_bad = (stop is not None and stop >= entry) or (target is not None and target <= entry)
            if entry is not None and direction == "short":
                geometry_bad = (stop is not None and stop <= entry) or (target is not None and target >= entry)
            if geometry_bad:
                warnings.append("direction_geometry_mismatch")
                plan["status"] = "no_setup"
            if plan.get("status") != "entry_zone":
                warnings.append(f"execution_{plan.get('status') or 'no_setup'}")

        entry_price_value = _safe_float(plan.get("entry_price"))
        plan_direction = str(plan.get("direction") or direction or "")
        plan_status = str(plan.get("status") or "no_setup")
        strict_edge_blocked = bool(body.require_proven_edge and edge is not None and not proven)
        side_blocked = bool(body.side_policy == "long_only" and plan_direction == "short")
        allocation_eligible = (
            edge is not None
            and not strict_edge_blocked
            and not side_blocked
            and plan_direction in {"long", "short"}
            and plan_status in {"entry_zone", "watching"}
            and entry_price_value not in (None, 0.0)
        )
        if allocation_eligible:
            eligible_symbols.append(symbol)

        if allocation_eligible:
            allocation_reason = "entry_zone" if plan_status == "entry_zone" else "waiting_for_entry_zone"
        elif edge is None:
            allocation_reason = "edge_unavailable"
        elif strict_edge_blocked:
            allocation_reason = "strict_edge_gate"
        elif side_blocked:
            allocation_reason = "short_blocked_by_long_only"
        elif plan_direction not in {"long", "short"}:
            allocation_reason = "no_directional_signal"
        elif entry_price_value in (None, 0.0):
            allocation_reason = "entry_price_unavailable"
        else:
            allocation_reason = f"execution_{plan_status}"

        prelim_rows[symbol] = {
            "meta": meta,
            "stock_payload": stock_payload,
            "plan": plan,
            "warnings": warnings,
            "sector": sector,
            "score": (None if body.source == "auto" else _current_score(stock_payload, selected_source)) or _score_from_edge_bucket(edge),
            "allocation_eligible": allocation_eligible,
            "allocation_reason": allocation_reason,
        }

    base_weights = compute_hrp_weights(price_history, eligible_symbols, lookback_bars=body.lookback_bars)
    if not base_weights and eligible_symbols:
        base_weights = {symbol: 1.0 / len(eligible_symbols) for symbol in eligible_symbols}

    max_position_frac = body.max_position_pct / 100.0
    max_sector_frac = body.max_sector_pct / 100.0
    raw_weights: dict[str, float] = {}
    for symbol in eligible_symbols:
        edge = edges.get(symbol)
        hrp_weight = float(base_weights.get(symbol, 0.0))
        kelly_full = _full_kelly_from_expectancy(edge)
        kelly_cap = kelly_full * body.kelly_fraction if kelly_full is not None else None
        cap = min(max_position_frac, kelly_cap) if kelly_cap is not None else max_position_frac
        raw_weights[symbol] = min(hrp_weight, cap)

    capped_weights = _apply_sector_caps(raw_weights, sectors, max_sector_frac)

    rows: list[DashboardPortfolioTicketRow] = []
    allocated = 0.0
    expected_return_mad = 0.0
    has_expected_return = False

    for symbol in symbols:
        item = prelim_rows[symbol]
        meta = item["meta"]
        stock_payload = item["stock_payload"] or {}
        plan = item["plan"]
        edge = edges.get(symbol)
        entry_price = _safe_float(plan.get("entry_price"))
        adv20 = _safe_float((stock_payload or {}).get("adv"))
        max_liquidity_size = None
        warnings = list(item["warnings"])
        target_size = deployable_capital * capped_weights.get(symbol, 0.0)
        if adv20 and body.adv_participation_pct > 0:
            max_liquidity_size = adv20 * (body.adv_participation_pct / 100.0)
            target_size = min(target_size, max_liquidity_size)
        elif body.adv_participation_pct > 0 and symbol in eligible_symbols:
            warnings.append("adv_unavailable")

        shares = int(math.floor(target_size / entry_price)) if entry_price and target_size > 0 else 0
        size_mad = float(shares * entry_price) if entry_price and shares > 0 else 0.0
        allocated += size_mad
        action_er = _safe_float(getattr(edge, "action_expected_return_net", None) if edge is not None else None)
        if action_er is not None and size_mad > 0:
            expected_return_mad += size_mad * action_er
            has_expected_return = True

        rows.append(DashboardPortfolioTicketRow(
            symbol=symbol,
            display_name=getattr(meta, "display_name", None) or stock_payload.get("display_name"),
            sector=item["sector"],
            direction=plan.get("direction"),
            action=_ticket_action(plan.get("direction"), body.side_policy),
            status=str(plan.get("status") or "no_setup"),
            signal_bucket=getattr(edge, "bucket", None) if edge is not None else None,
            signal_score=item["score"],
            proven_edge=bool(getattr(edge, "proven_edge_net", False)) if edge is not None else False,
            holding_period_bars=getattr(edge, "fwd_horizon_bars", None) if edge is not None else None,
            return_calc_method=getattr(edge, "return_calc_method", None) if edge is not None else None,
            action_expected_return_net=action_er,
            stock_expected_return=_safe_float(getattr(edge, "stock_expected_return", None) if edge is not None else None),
            allocation_eligible=bool(item["allocation_eligible"]),
            allocation_reason=str(item["allocation_reason"]),
            base_hrp_weight_pct=round(float(base_weights.get(symbol, 0.0)) * 100.0, 4),
            final_weight_pct=round((size_mad / body.total_capital_mad) * 100.0, 4) if body.total_capital_mad > 0 else 0.0,
            size_mad=round(size_mad, 2),
            shares=shares,
            entry_reference_price=entry_price,
            entry_zone_low=_safe_float(plan.get("entry_zone_low")),
            entry_zone_high=_safe_float(plan.get("entry_zone_high")),
            stop_loss=_safe_float(plan.get("stop_loss")),
            target_1=_safe_float(plan.get("target_1")),
            target_2=_safe_float(plan.get("target_2")),
            rr_ratio=_safe_float(plan.get("rr_ratio")),
            atr_14=_safe_float(plan.get("atr_14")),
            adv20=adv20,
            max_liquidity_size_mad=round(max_liquidity_size, 2) if max_liquidity_size is not None else None,
            execution_explain=str(plan.get("explain") or "") or None,
            warnings=warnings,
            proof_url=_proof_url(
                symbol,
                horizon,
                edge_sources.get(symbol, body.source),
                body.side_policy,
                edge_variants.get(symbol),
            ),
        ))

    summary = DashboardPortfolioTicketSummary(
        horizon=horizon,
        source=body.source,
        side_policy=body.side_policy,
        total_capital_mad=round(body.total_capital_mad, 2),
        deployable_capital_mad=round(deployable_capital, 2),
        allocated_capital_mad=round(allocated, 2),
        cash_buffer_mad=round(cash_buffer + max(deployable_capital - allocated, 0.0), 2),
        expected_action_return_mad=round(expected_return_mad, 2) if has_expected_return else None,
        expected_action_return_pct=round(expected_return_mad / body.total_capital_mad, 6) if has_expected_return else None,
        selected_count=len(symbols),
        allocated_count=sum(1 for row in rows if row.shares > 0),
        tradable_count=sum(1 for row in rows if row.shares > 0 and row.status == "entry_zone"),
    )
    return DashboardPortfolioTicketResponse(summary=summary, rows=rows)
