from __future__ import annotations

import datetime as dt
import logging
import math
import hashlib
import json
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.horizons import canonical_horizon
from core.quant_core.research.fundamental_portfolio import SfcPortfolioMember, build_sfc_target_weights, sfc_direction
from core.quant_core.strategy_plan.allocation import compute_hrp_weights
from core.quant_core.strategy_plan.execution import compute_execution_plan
from core.quant_core.strategy_plan.execution_policy import build_execution_horizon_policy
from core.quant_core.strategy_plan.levels import compute_atr, detect_swing_levels

from .. import models
from ..config import settings
from ..market_data_loader import load_ohlcv_for_symbol
from ..queue import get_queue
from ..schemas.dashboard_portfolio import (
    DashboardDailyBlotterRequest,
    DashboardDailyBlotterResponse,
    DashboardDailyBlotterRow,
    DashboardDailyBlotterSummary,
    DashboardManualPosition,
    DashboardPortfolioBacktestRunResponse,
    DashboardPortfolioCreate,
    DashboardPortfolioFromHistoryRequest,
    DashboardPortfolioListResponse,
    DashboardPortfolioOut,
    DashboardPortfolioReplayRequest,
    DashboardPortfolioReplayResponse,
    DashboardPortfolioTicketRequest,
    DashboardPortfolioTicketResponse,
    DashboardPortfolioTicketRow,
    DashboardPortfolioTicketSummary,
    DashboardPortfolioUpdate,
    DashboardPortfolioPositionsRequest,
    DashboardPortfolioPositionsResponse,
    DashboardPortfolioSummaryOut,
    DashboardPortfolioTradeIn,
    DashboardPortfolioTradeOut,
    DashboardPortfolioPositionMarkOut,
)
from .bourse_live_quotes import (
    LiveQuoteView,
    effective_price_from_quote,
    get_or_refresh_live_quotes,
    get_cached_live_quotes,
)
from .dashboard_builder import _build_best_signal_payload, build_dashboard_payload
from .fundamental_cross_section import SFC_CONFIG_HASH, SFC_METHODOLOGY_VERSION, latest_sfc_as_of


logger = logging.getLogger(__name__)


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


def _sfc_proof_url(symbol: str) -> str:
    return f"/signals?mode=fundamental&symbol={symbol}&fund_tab=synthese"


def _sfc_rows_for_symbols(db: Session, symbols: list[str]) -> tuple[dt.date | None, dict[str, models.FundamentalCrossSectionScore]]:
    as_of = latest_sfc_as_of(db)
    if as_of is None or not symbols:
        return as_of, {}
    rows = (
        db.query(models.FundamentalCrossSectionScore)
        .filter(
            models.FundamentalCrossSectionScore.as_of_date == as_of,
            models.FundamentalCrossSectionScore.methodology_version == SFC_METHODOLOGY_VERSION,
            models.FundamentalCrossSectionScore.config_hash == SFC_CONFIG_HASH,
            models.FundamentalCrossSectionScore.symbol.in_(symbols),
        )
        .all()
    )
    return as_of, {str(row.symbol).upper(): row for row in rows}


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


def _clean_symbols(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in symbols:
        symbol = str(raw or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _clean_component_shares(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for raw_symbol, raw_shares in raw.items():
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol:
            continue
        try:
            shares = int(raw_shares)
        except (TypeError, ValueError):
            continue
        if shares > 0:
            out[symbol] = shares
    return out


def _components_to_symbols_and_shares(
    *,
    symbols: list[str] | None,
    components: list[Any] | None,
    component_shares: dict[str, int] | None,
) -> tuple[list[str], dict[str, int]]:
    if components is not None:
        seen: set[str] = set()
        out_symbols: list[str] = []
        out_shares: dict[str, int] = {}
        for component in components:
            symbol = str(getattr(component, "symbol", "") or "").strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            enabled = bool(getattr(component, "enabled", True))
            if not enabled:
                continue
            shares = int(getattr(component, "shares", 1) or 1)
            out_symbols.append(symbol)
            out_shares[symbol] = max(1, shares)
        return out_symbols, out_shares

    out_symbols = _clean_symbols(symbols or [])
    shares = _clean_component_shares(component_shares or {})
    for symbol in out_symbols:
        shares.setdefault(symbol, 1)
    return out_symbols, {symbol: shares[symbol] for symbol in out_symbols if shares.get(symbol, 0) > 0}


def _portfolio_components(row: models.DashboardPortfolio) -> list[dict[str, Any]]:
    symbols = _clean_symbols([str(item) for item in (row.symbols or [])])
    shares = _clean_component_shares(row.component_shares or {})
    return [
        {"symbol": symbol, "shares": int(shares.get(symbol, 1) or 1), "enabled": True}
        for symbol in symbols
    ]


def _portfolio_to_out(
    row: models.DashboardPortfolio,
    *,
    summary: DashboardPortfolioSummaryOut | None = None,
) -> DashboardPortfolioOut:
    symbols = _clean_symbols([str(item) for item in (row.symbols or [])])
    shares = _clean_component_shares(row.component_shares or {})
    return DashboardPortfolioOut(
        id=str(row.id),
        name=row.name,
        description=row.description,
        symbols=symbols,
        component_shares={symbol: int(shares.get(symbol, 1) or 1) for symbol in symbols},
        components=_portfolio_components(row),
        allocation_method=row.allocation_method or "share_quantities",
        side_policy=row.side_policy or "long_only",
        total_capital_mad=float(row.total_capital_mad or 0.0),
        cash_buffer_pct=float(row.cash_buffer_pct or 0.0),
        stop_loss_pct=_safe_float(row.stop_loss_pct),
        take_profit_pct=_safe_float(row.take_profit_pct),
        display_mode=row.display_mode or "trade_opportunities",
        technical_direction_mode=row.technical_direction_mode or "best",
        horizon=row.horizon or "monthly",
        is_default=bool(row.is_default),
        replay_start_date=row.replay_start_date,
        replay_end_date=row.replay_end_date,
        replay_generated_at=row.replay_generated_at,
        last_replay=row.last_replay_json if isinstance(row.last_replay_json, dict) else {},
        summary=summary.model_dump(mode="json") if summary is not None else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _resolve_portfolio_id(portfolio_id: str | UUID | None) -> UUID | None:
    if portfolio_id is None:
        return None
    if isinstance(portfolio_id, UUID):
        return portfolio_id
    try:
        return UUID(str(portfolio_id))
    except ValueError as exc:
        raise ValueError("Portfolio not found") from exc


def ensure_default_dashboard_portfolio(db: Session, *, owner_user_id: str) -> models.DashboardPortfolio:
    row = (
        db.query(models.DashboardPortfolio)
        .filter(models.DashboardPortfolio.owner_user_id == owner_user_id)
        .filter(models.DashboardPortfolio.is_default.is_(True))
        .order_by(models.DashboardPortfolio.created_at.asc())
        .first()
    )
    if row is not None:
        return row
    row = (
        db.query(models.DashboardPortfolio)
        .filter(models.DashboardPortfolio.owner_user_id == owner_user_id)
        .order_by(models.DashboardPortfolio.created_at.asc())
        .first()
    )
    if row is not None:
        row.is_default = True
        db.flush()
        return row
    row = models.DashboardPortfolio(
        owner_user_id=owner_user_id,
        name="Default portfolio",
        symbols=[],
        component_shares={},
        is_default=True,
    )
    db.add(row)
    db.flush()
    return row


def _get_portfolio(
    db: Session,
    *,
    owner_user_id: str,
    portfolio_id: str | UUID | None = None,
) -> models.DashboardPortfolio:
    if portfolio_id is None:
        return ensure_default_dashboard_portfolio(db, owner_user_id=owner_user_id)
    parsed = _resolve_portfolio_id(portfolio_id)
    row = (
        db.query(models.DashboardPortfolio)
        .filter(models.DashboardPortfolio.id == parsed)
        .filter(models.DashboardPortfolio.owner_user_id == owner_user_id)
        .one_or_none()
    )
    if row is None:
        raise ValueError("Portfolio not found")
    return row


def _apply_portfolio_payload(row: models.DashboardPortfolio, body: DashboardPortfolioCreate | DashboardPortfolioUpdate) -> None:
    fields_set = set(getattr(body, "model_fields_set", set(body.model_dump().keys())))
    if "name" in fields_set and getattr(body, "name", None) is not None:
        name = str(body.name or "").strip()
        if not name:
            raise ValueError("Portfolio name cannot be empty")
        row.name = name
    if "description" in fields_set:
        row.description = body.description
    components = getattr(body, "components", None)
    symbols_value = getattr(body, "symbols", None)
    shares_value = getattr(body, "component_shares", None)
    if "components" in fields_set or "symbols" in fields_set or "component_shares" in fields_set:
        symbols, component_shares = _components_to_symbols_and_shares(
            symbols=symbols_value if symbols_value is not None else list(row.symbols or []),
            components=components,
            component_shares=shares_value if shares_value is not None else dict(row.component_shares or {}),
        )
        row.symbols = symbols
        row.component_shares = component_shares
    for field in (
        "allocation_method",
        "side_policy",
        "total_capital_mad",
        "cash_buffer_pct",
        "stop_loss_pct",
        "take_profit_pct",
        "display_mode",
        "technical_direction_mode",
        "horizon",
    ):
        if field in fields_set:
            setattr(row, field, getattr(body, field, None))


def list_dashboard_portfolios(
    db: Session,
    *,
    owner_user_id: str,
    include_summary: bool = True,
) -> DashboardPortfolioListResponse:
    ensure_default_dashboard_portfolio(db, owner_user_id=owner_user_id)
    rows = (
        db.query(models.DashboardPortfolio)
        .filter(models.DashboardPortfolio.owner_user_id == owner_user_id)
        .order_by(models.DashboardPortfolio.updated_at.desc(), models.DashboardPortfolio.name.asc())
        .all()
    )
    portfolios: list[DashboardPortfolioOut] = []
    for row in rows:
        summary = (
            build_dashboard_portfolio_summary(
                db,
                owner_user_id=owner_user_id,
                portfolio_id=row.id,
                price_source="live_if_fresh",
                max_live_quote_age_seconds=60,
            )
            if include_summary
            else None
        )
        portfolios.append(_portfolio_to_out(row, summary=summary))
    db.commit()
    return DashboardPortfolioListResponse(portfolios=portfolios)


def create_dashboard_portfolio(
    db: Session,
    body: DashboardPortfolioCreate,
    *,
    owner_user_id: str,
) -> DashboardPortfolioOut:
    name = str(body.name or "").strip()
    if not name:
        raise ValueError("Portfolio name cannot be empty")
    duplicate = (
        db.query(models.DashboardPortfolio)
        .filter(models.DashboardPortfolio.owner_user_id == owner_user_id)
        .filter(func.lower(models.DashboardPortfolio.name) == name.lower())
        .one_or_none()
    )
    if duplicate is not None:
        raise ValueError("Portfolio name already exists")
    symbols, component_shares = _components_to_symbols_and_shares(
        symbols=body.symbols,
        components=body.components,
        component_shares=body.component_shares,
    )
    row = models.DashboardPortfolio(
        owner_user_id=owner_user_id,
        name=name,
        description=body.description,
        symbols=symbols,
        component_shares=component_shares,
        allocation_method=body.allocation_method,
        side_policy=body.side_policy,
        total_capital_mad=float(body.total_capital_mad),
        cash_buffer_pct=float(body.cash_buffer_pct),
        stop_loss_pct=body.stop_loss_pct,
        take_profit_pct=body.take_profit_pct,
        display_mode=body.display_mode,
        technical_direction_mode=body.technical_direction_mode,
        horizon=body.horizon,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _portfolio_to_out(row)


def update_dashboard_portfolio(
    db: Session,
    portfolio_id: str,
    body: DashboardPortfolioUpdate,
    *,
    owner_user_id: str,
) -> DashboardPortfolioOut:
    row = _get_portfolio(db, owner_user_id=owner_user_id, portfolio_id=portfolio_id)
    next_name = str(body.name or row.name or "").strip()
    duplicate = (
        db.query(models.DashboardPortfolio)
        .filter(models.DashboardPortfolio.owner_user_id == owner_user_id)
        .filter(func.lower(models.DashboardPortfolio.name) == next_name.lower())
        .filter(models.DashboardPortfolio.id != row.id)
        .one_or_none()
    )
    if duplicate is not None:
        raise ValueError("Portfolio name already exists")
    _apply_portfolio_payload(row, body)
    db.commit()
    db.refresh(row)
    return _portfolio_to_out(row)


def delete_dashboard_portfolio(db: Session, portfolio_id: str, *, owner_user_id: str) -> None:
    row = _get_portfolio(db, owner_user_id=owner_user_id, portfolio_id=portfolio_id)
    if row.is_default:
        raise ValueError("Default portfolio cannot be deleted")
    db.delete(row)
    db.commit()


def get_dashboard_portfolio_out(
    db: Session,
    portfolio_id: str,
    *,
    owner_user_id: str,
) -> DashboardPortfolioOut:
    row = _get_portfolio(db, owner_user_id=owner_user_id, portfolio_id=portfolio_id)
    summary = build_dashboard_portfolio_summary(db, owner_user_id=owner_user_id, portfolio_id=row.id)
    return _portfolio_to_out(row, summary=summary)


def list_dashboard_positions(
    db: Session,
    *,
    owner_user_id: str,
    portfolio_id: str | UUID | None = None,
) -> DashboardPortfolioPositionsResponse:
    portfolio = _get_portfolio(db, owner_user_id=owner_user_id, portfolio_id=portfolio_id)
    rows = (
        db.query(models.DeskPortfolioPosition)
        .filter(models.DeskPortfolioPosition.owner_user_id == owner_user_id)
        .filter(models.DeskPortfolioPosition.portfolio_id == portfolio.id)
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
    portfolio_id: str | UUID | None = None,
) -> DashboardPortfolioPositionsResponse:
    portfolio = _get_portfolio(db, owner_user_id=owner_user_id, portfolio_id=portfolio_id)
    incoming = {
        (pos.symbol.strip().upper(), pos.side): _normalize_position(pos)
        for pos in body.positions
        if pos.symbol.strip() and pos.quantity > 0.0
    }
    existing_rows = (
        db.query(models.DeskPortfolioPosition)
        .filter(models.DeskPortfolioPosition.owner_user_id == owner_user_id)
        .filter(models.DeskPortfolioPosition.portfolio_id == portfolio.id)
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
            row = models.DeskPortfolioPosition(
                owner_user_id=owner_user_id,
                portfolio_id=portfolio.id,
                symbol=pos.symbol,
                side=pos.side,
            )
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
    return list_dashboard_positions(db, owner_user_id=owner_user_id, portfolio_id=portfolio.id)


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
    portfolio_id: str | UUID | None = None,
) -> dict[str, DashboardManualPosition]:
    if body.positions is None:
        positions = (
            list_dashboard_positions(db, owner_user_id=owner_user_id, portfolio_id=portfolio_id).positions
            if owner_user_id
            else []
        )
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


def _official_price_from_payload(stock_payload: dict[str, Any] | None) -> float | None:
    if not stock_payload:
        return None
    return _safe_float(
        stock_payload.get("last_price")
        or ((stock_payload.get("scores") or {}).get("signal_engine") or {}).get("technical_levels", {}).get("close_used")
        or stock_payload.get("prev_close")
    )


def _live_quote_by_symbol(
    db: Session,
    symbols: list[str],
    *,
    price_source: str,
    max_age_seconds: int,
    refresh: bool,
) -> dict[str, LiveQuoteView]:
    if price_source != "live_if_fresh":
        return {}
    try:
        if refresh:
            return get_or_refresh_live_quotes(db, symbols, max_age_seconds=max_age_seconds)
        return get_cached_live_quotes(db, symbols, max_age_seconds=max_age_seconds)
    except Exception:
        logger.debug("live quote overlay unavailable", exc_info=True)
        rollback = getattr(db, "rollback", None)
        if callable(rollback):
            rollback()
        return {}


def _effective_price(
    official_price: float | None,
    quote: LiveQuoteView | None,
    *,
    price_source: str,
) -> tuple[float | None, str, float | None]:
    price, source = effective_price_from_quote(
        official_price=official_price,
        quote=quote,
        live_if_fresh=price_source == "live_if_fresh",
    )
    return price, source, quote.age_seconds if source == "live" and quote is not None else None


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
        if action == "avoid":
            return "EXIT", 0, warnings
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
        if action == "avoid":
            warnings.append("short_position_requires_review")
            return "REVIEW", int(round(current_signed)), warnings
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
    if action == "avoid":
        return "AVOID", 0, warnings
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
    portfolio_id: str | UUID | None = None,
) -> DashboardDailyBlotterResponse:
    positions = _manual_positions_for_blotter(db, body, owner_user_id=owner_user_id, portfolio_id=portfolio_id)
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
    sfc_mode = body.source == "sfc"
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
    live_quotes = _live_quote_by_symbol(
        db,
        symbols,
        price_source=body.price_source,
        max_age_seconds=body.max_live_quote_age_seconds,
        refresh=True,
    )

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
    sfc_as_of, sfc_rows = _sfc_rows_for_symbols(db, symbols) if sfc_mode else (None, {})

    exec_horizon = _legacy_execution_horizon(horizon)
    policy = build_execution_horizon_policy(exec_horizon, timeframe=body.timeframe)

    for symbol in symbols:
        meta = metadata.get(symbol)
        stock_payload = dashboard_by_symbol.get(symbol)
        official_price = _official_price_from_payload(stock_payload)
        current_price, current_price_source, current_quote_age = _effective_price(
            official_price,
            live_quotes.get(symbol),
            price_source=body.price_source,
        )
        sector = (getattr(meta, "sector", None) or (stock_payload or {}).get("sector") or "Other")
        sectors[symbol] = str(sector)
        warnings: list[str] = []
        if body.price_source == "live_if_fresh" and current_price_source != "live":
            warnings.append("live_price_unavailable_using_official_close")

        sfc_row = sfc_rows.get(symbol)
        if sfc_mode:
            edge, selected_source, selected_variant = None, "sfc", None
        else:
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
        if sfc_mode and sfc_row is None:
            warnings.append("sfc_unavailable")
        if not sfc_mode and edge is None:
            warnings.append("edge_unavailable")

        proven = True if sfc_mode and sfc_row is not None else (bool(edge.proven_edge_net) if edge is not None else False)
        if sfc_mode:
            sfc_intent = sfc_direction(getattr(sfc_row, "tercile", None) if sfc_row is not None else None)
            direction = "long" if sfc_intent in {"long", "neutral"} else None
            if sfc_as_of is not None:
                warnings.append(f"sfc_as_of_{sfc_as_of.isoformat()}")
            if sfc_intent == "avoid":
                warnings.append("sfc_bottom_tercile_avoid")
        else:
            direction = edge.direction if edge is not None else None
        if not sfc_mode and edge is not None and not proven:
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
        if sfc_mode:
            entry_ref = _safe_float(current_price)
            plan = {
                "direction": direction,
                "status": "entry_zone" if direction == "long" and entry_ref not in (None, 0.0) else "no_setup",
                "entry_price": entry_ref,
                "entry_zone_low": entry_ref,
                "entry_zone_high": entry_ref,
                "stop_loss": None,
                "target_1": None,
                "target_2": None,
                "rr_ratio": None,
                "atr_14": None,
                "explain": "SFC publication-window rebalance target.",
            }
            if entry_ref in (None, 0.0):
                warnings.append("entry_price_unavailable")
        elif bars.empty or not {"High", "Low", "Close"}.issubset(set(map(str, bars.columns))):
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
                current_close=float(current_price or close[-1]),
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
        strict_edge_blocked = bool((not sfc_mode) and body.require_proven_edge and edge is not None and not proven)
        side_blocked = bool(body.side_policy == "long_only" and plan_direction == "short")
        allocation_eligible = (
            (sfc_row is not None if sfc_mode else edge is not None)
            and not strict_edge_blocked
            and not side_blocked
            and plan_direction in ({"long"} if sfc_mode else {"long", "short"})
            and plan_status in {"entry_zone", "watching"}
            and entry_price_value not in (None, 0.0)
        )
        if allocation_eligible:
            eligible_symbols.append(symbol)

        if allocation_eligible:
            allocation_reason = "entry_zone" if plan_status == "entry_zone" else "waiting_for_entry_zone"
        elif sfc_mode and sfc_row is None:
            allocation_reason = "sfc_unavailable"
        elif not sfc_mode and edge is None:
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
            "score": _safe_float(getattr(sfc_row, "sfc", None)) if sfc_mode else ((None if body.source == "auto" else _current_score(stock_payload, selected_source)) or _score_from_edge_bucket(edge)),
            "allocation_eligible": allocation_eligible,
            "allocation_reason": allocation_reason,
            "price_source": current_price_source,
            "live_quote_age_seconds": current_quote_age,
            "sfc_row": sfc_row,
        }

    if sfc_mode:
        base_weights = build_sfc_target_weights(
            [
                SfcPortfolioMember(
                    symbol=symbol,
                    tercile=str(getattr(sfc_rows.get(symbol), "tercile", "unavailable")),
                    sfc=_safe_float(getattr(sfc_rows.get(symbol), "sfc", None)),
                )
                for symbol in symbols
            ],
            active_cap=0.03,
        )
    else:
        base_weights = compute_hrp_weights(price_history, eligible_symbols, lookback_bars=body.lookback_bars)
    if not base_weights and eligible_symbols:
        base_weights = {symbol: 1.0 / len(eligible_symbols) for symbol in eligible_symbols}

    max_position_frac = body.max_position_pct / 100.0
    max_sector_frac = body.max_sector_pct / 100.0
    raw_weights: dict[str, float] = {}
    for symbol in eligible_symbols:
        edge = edges.get(symbol)
        hrp_weight = float(base_weights.get(symbol, 0.0))
        kelly_full = None if sfc_mode else _full_kelly_from_expectancy(edge)
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
            action=("avoid" if sfc_mode and sfc_direction(getattr(item.get("sfc_row"), "tercile", None)) == "avoid" else _ticket_action(plan.get("direction"), body.side_policy)),
            status=str(plan.get("status") or "no_setup"),
            signal_bucket=str(getattr(item.get("sfc_row"), "tercile", "")) if sfc_mode and item.get("sfc_row") is not None else (getattr(edge, "bucket", None) if edge is not None else None),
            signal_score=item["score"],
            proven_edge=bool(sfc_mode and item.get("sfc_row") is not None) or (bool(getattr(edge, "proven_edge_net", False)) if edge is not None else False),
            holding_period_bars=None if sfc_mode else (getattr(edge, "fwd_horizon_bars", None) if edge is not None else None),
            return_calc_method="sfc_publication_window" if sfc_mode else (getattr(edge, "return_calc_method", None) if edge is not None else None),
            action_expected_return_net=action_er,
            stock_expected_return=_safe_float(getattr(edge, "stock_expected_return", None) if edge is not None else None),
            allocation_eligible=bool(item["allocation_eligible"]),
            allocation_reason=str(item["allocation_reason"]),
            base_hrp_weight_pct=round(float(base_weights.get(symbol, 0.0)) * 100.0, 4),
            final_weight_pct=round((size_mad / body.total_capital_mad) * 100.0, 4) if body.total_capital_mad > 0 else 0.0,
            size_mad=round(size_mad, 2),
            shares=shares,
            entry_reference_price=entry_price,
            price_source=item["price_source"],
            live_quote_age_seconds=item["live_quote_age_seconds"],
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
            proof_url=_sfc_proof_url(symbol) if sfc_mode else _proof_url(
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


# ---------------------------------------------------------------------------
# Portfolio trade ledger and mark-to-market
# ---------------------------------------------------------------------------

def _owner_filter(query: Any, owner_user_id: str):
    return query.filter(models.DeskPortfolioPosition.owner_user_id == owner_user_id)


def _fill_owner_filter(query: Any, owner_user_id: str):
    return query.filter(models.DeskPortfolioFill.owner_user_id == owner_user_id)


def _position_realized(row: models.DeskPortfolioPosition | None) -> float:
    if row is None or not isinstance(row.meta_json, dict):
        return 0.0
    return _safe_float(row.meta_json.get("realized_pnl_mad")) or 0.0


def _set_position_realized(row: models.DeskPortfolioPosition, realized: float) -> None:
    meta = dict(row.meta_json or {})
    meta["realized_pnl_mad"] = round(realized, 2)
    row.meta_json = meta


def _position_row(
    db: Session,
    *,
    owner_user_id: str,
    portfolio_id: str | UUID,
    symbol: str,
    side: str,
    create: bool = False,
) -> models.DeskPortfolioPosition | None:
    row = (
        db.query(models.DeskPortfolioPosition)
        .filter(models.DeskPortfolioPosition.owner_user_id == owner_user_id)
        .filter(models.DeskPortfolioPosition.portfolio_id == portfolio_id)
        .filter(models.DeskPortfolioPosition.symbol == symbol)
        .filter(models.DeskPortfolioPosition.side == side)
        .first()
    )
    if row is None and create:
        row = models.DeskPortfolioPosition(
            owner_user_id=owner_user_id,
            portfolio_id=portfolio_id,
            symbol=symbol,
            side=side,
        )
        db.add(row)
    return row


def _apply_trade_to_position(
    row: models.DeskPortfolioPosition,
    *,
    action: str,
    quantity: float,
    price: float,
    fees: float,
) -> float:
    current_qty = float(row.quantity or 0.0)
    current_cmp = _safe_float(row.average_price_mad)
    realized_delta = 0.0

    if action in {"BUY", "SELL_SHORT"}:
        new_qty = current_qty + quantity
        if new_qty <= 0:
            raise ValueError("Position quantity must remain positive after entry")
        weighted_cost = ((current_cmp or 0.0) * current_qty) + (price * quantity)
        row.quantity = new_qty
        row.average_price_mad = round(weighted_cost / new_qty, 6)
        row.status = "active"
        return round(-fees, 2)

    if current_qty <= 0 or current_cmp is None:
        raise ValueError("Cannot exit a position with no active quantity")
    if quantity > current_qty + 1e-9:
        raise ValueError("Exit quantity exceeds active position")

    if action == "SELL":
        realized_delta = (price - current_cmp) * quantity - fees
    elif action == "COVER":
        realized_delta = (current_cmp - price) * quantity - fees
    else:
        raise ValueError(f"Unsupported trade action: {action}")

    new_qty = max(0.0, current_qty - quantity)
    row.quantity = new_qty
    row.status = "inactive" if new_qty <= 1e-9 else "active"
    if row.status == "inactive":
        row.quantity = 0.0
        row.average_price_mad = None
    return round(realized_delta, 2)


def record_dashboard_portfolio_trade(
    db: Session,
    body: DashboardPortfolioTradeIn,
    *,
    owner_user_id: str,
    portfolio_id: str | UUID | None = None,
) -> DashboardPortfolioTradeOut:
    symbol = body.symbol.strip().upper()
    action = body.action
    side = "short" if action in {"SELL_SHORT", "COVER"} else "long"
    portfolio = _get_portfolio(db, owner_user_id=owner_user_id, portfolio_id=portfolio_id)
    try:
        row = _position_row(
            db,
            owner_user_id=owner_user_id,
            portfolio_id=portfolio.id,
            symbol=symbol,
            side=side,
            create=action in {"BUY", "SELL_SHORT"},
        )
        if row is None:
            raise ValueError("Cannot exit a position with no active quantity")

        realized_delta = _apply_trade_to_position(
            row,
            action=action,
            quantity=float(body.quantity),
            price=float(body.price_mad),
            fees=float(body.fees_mad or 0.0),
        )
        cumulative_realized = _position_realized(row) + realized_delta
        _set_position_realized(row, cumulative_realized)

        timestamp = (
            dt.datetime.combine(body.timestamp, dt.time.min, tzinfo=dt.timezone.utc)
            if body.timestamp is not None
            else dt.datetime.now(dt.timezone.utc)
        )
        fill = models.DeskPortfolioFill(
            owner_user_id=owner_user_id,
            portfolio_id=portfolio.id,
            timestamp=timestamp,
            symbol=symbol,
            side=action,
            quantity=float(body.quantity),
            price_mad=float(body.price_mad),
            fees_mad=float(body.fees_mad or 0.0),
            notes=body.notes,
            meta_json={"realized_pnl_mad": realized_delta},
        )
        db.add(fill)
        db.commit()
        db.refresh(fill)
        return _trade_out(fill)
    except Exception:
        db.rollback()
        raise


def _trade_out(row: models.DeskPortfolioFill) -> DashboardPortfolioTradeOut:
    meta = row.meta_json if isinstance(row.meta_json, dict) else {}
    ts = row.timestamp.date() if row.timestamp is not None else None
    return DashboardPortfolioTradeOut(
        id=str(row.id),
        symbol=str(row.symbol).upper(),
        action=str(row.side),
        quantity=float(row.quantity or 0.0),
        price_mad=float(row.price_mad or 0.0),
        timestamp=ts,
        fees_mad=float(row.fees_mad or 0.0),
        realized_pnl_mad=round(_safe_float(meta.get("realized_pnl_mad")) or 0.0, 2),
        notes=row.notes,
    )


def _official_prices_for_symbols(db: Session, symbols: list[str]) -> dict[str, float | None]:
    if not symbols:
        return {}
    rows = (
        db.query(models.MarketDataStore)
        .filter(models.MarketDataStore.symbol.in_(symbols))
        .filter(models.MarketDataStore.timeframe.in_(["1D", "1d"]))
        .all()
    )
    out: dict[str, float | None] = {}
    for row in rows:
        out[row.symbol] = _safe_float(getattr(row, "close_last", None))
    return out


def build_dashboard_portfolio_summary(
    db: Session,
    *,
    owner_user_id: str,
    portfolio_id: str | UUID | None = None,
    price_source: str = "live_if_fresh",
    max_live_quote_age_seconds: int = 60,
) -> DashboardPortfolioSummaryOut:
    portfolio = _get_portfolio(db, owner_user_id=owner_user_id, portfolio_id=portfolio_id)
    position_rows = (
        db.query(models.DeskPortfolioPosition)
        .filter(models.DeskPortfolioPosition.owner_user_id == owner_user_id)
        .filter(models.DeskPortfolioPosition.portfolio_id == portfolio.id)
        .filter(models.DeskPortfolioPosition.status == "active")
        .order_by(models.DeskPortfolioPosition.symbol.asc(), models.DeskPortfolioPosition.side.asc())
        .all()
    )
    symbols = [str(row.symbol).upper() for row in position_rows if float(row.quantity or 0.0) > 0.0]
    official_prices = _official_prices_for_symbols(db, symbols)
    live_quotes = _live_quote_by_symbol(
        db,
        symbols,
        price_source=price_source,
        max_age_seconds=max_live_quote_age_seconds,
        refresh=True,
    )

    positions: list[DashboardPortfolioPositionMarkOut] = []
    total_value = 0.0
    total_unrealized = 0.0
    total_realized = 0.0
    for row in position_rows:
        qty = float(row.quantity or 0.0)
        if qty <= 0:
            continue
        symbol = str(row.symbol).upper()
        row_meta = row.meta_json if isinstance(row.meta_json, dict) else {}
        fallback_mark = _safe_float(row_meta.get("last_mark_price_mad"))
        mark, mark_source, quote_age = _effective_price(
            official_prices.get(symbol) if official_prices.get(symbol) is not None else fallback_mark,
            live_quotes.get(symbol),
            price_source=price_source,
        )
        if official_prices.get(symbol) is None and fallback_mark is not None and mark_source == "official_close":
            mark_source = "replay_close"
        value, unrealized = _mark_to_market(_position_to_schema(row), mark)
        realized = _position_realized(row)
        total_value += value or 0.0
        total_unrealized += unrealized or 0.0
        total_realized += realized
        positions.append(DashboardPortfolioPositionMarkOut(
            symbol=symbol,
            side=row.side or "long",
            quantity=qty,
            cmp_mad=_safe_float(row.average_price_mad),
            mark_price_mad=mark,
            mark_source=mark_source,
            market_value_mad=value,
            unrealized_pnl_mad=unrealized,
            realized_pnl_mad=round(realized, 2),
            updated_at=row.updated_at,
            live_quote_age_seconds=quote_age,
        ))

    trade_rows = (
        _fill_owner_filter(db.query(models.DeskPortfolioFill), owner_user_id)
        .filter(models.DeskPortfolioFill.portfolio_id == portfolio.id)
        .order_by(models.DeskPortfolioFill.timestamp.desc())
        .limit(250)
        .all()
    )
    return DashboardPortfolioSummaryOut(
        positions=positions,
        trades=[_trade_out(row) for row in trade_rows],
        total_market_value_mad=round(total_value, 2),
        total_unrealized_pnl_mad=round(total_unrealized, 2),
        total_realized_pnl_mad=round(total_realized, 2),
    )


# ---------------------------------------------------------------------------
# Historical portfolio replay
# ---------------------------------------------------------------------------

def _score_history_sources(display_mode: str, technical_direction_mode: str) -> tuple[str, list[str]]:
    if display_mode == "trade_opportunities":
        return "wfo", ["wfo%"]
    if technical_direction_mode == "classic":
        return "engine_classic", ["engine_legacy%", "engine:legacy%", "signal_engine_legacy%"]
    return "engine_best", ["engine%", "signal_engine%"]


def _signal_direction(score: float | None) -> str:
    if score is None:
        return "none"
    if score >= 20.0:
        return "long"
    if score <= -20.0:
        return "short"
    return "none"


def _load_score_map(
    db: Session,
    *,
    symbols: list[str],
    start_date: dt.date,
    end_date: dt.date,
    horizon: str,
    display_mode: str,
    technical_direction_mode: str,
) -> dict[tuple[str, dt.date], float | None]:
    _source_label, source_patterns = _score_history_sources(display_mode, technical_direction_mode)
    query = (
        db.query(models.SignalScoreHistory)
        .filter(models.SignalScoreHistory.symbol.in_(symbols))
        .filter(models.SignalScoreHistory.date >= start_date)
        .filter(models.SignalScoreHistory.date <= end_date)
        .filter(models.SignalScoreHistory.horizon == canonical_horizon(horizon, allow_legacy=True))
    )
    clauses = [models.SignalScoreHistory.source.like(pattern) for pattern in source_patterns]
    if len(clauses) == 1:
        query = query.filter(clauses[0])
    else:
        from sqlalchemy import or_
        query = query.filter(or_(*clauses))
    raw: dict[tuple[str, dt.date], list[float]] = {}
    for row in query.all():
        score = _safe_float(row.score_pct)
        if score is None:
            continue
        raw.setdefault((str(row.symbol).upper(), row.date), []).append(score)
    return {
        key: (sum(values) / len(values) if values else None)
        for key, values in raw.items()
    }


def _clean_bars(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    bars = drop_incomplete_ohlcv_rows(frame).sort_index()
    if bars.empty:
        return bars
    normalized_index = pd.to_datetime(bars.index).date
    bars = bars.copy()
    bars.index = normalized_index
    return bars


def _bar_value(bars: pd.DataFrame, session: dt.date, column: str) -> float | None:
    if bars.empty or session not in bars.index or column not in bars.columns:
        return None
    return _safe_float(bars.loc[session, column])


def _execution_price(bars: pd.DataFrame, session: dt.date) -> float | None:
    return _bar_value(bars, session, "Open") or _bar_value(bars, session, "Close")


def _next_session(dates: list[dt.date], after_date: dt.date) -> dt.date | None:
    for session in dates:
        if session > after_date:
            return session
    return None


def _portfolio_metrics(equity_curve: list[dict[str, Any]], fills: list[dict[str, Any]], total_capital: float) -> dict[str, Any]:
    if not equity_curve:
        return {
            "net_pnl": 0.0,
            "total_return": 0.0,
            "number_of_trades": len(fills),
            "max_drawdown": 0.0,
        }
    values = [float(row.get("equity_mad") or 0.0) for row in equity_curve]
    final_equity = values[-1]
    peak = values[0]
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = min(max_drawdown, (value - peak) / peak)
    net_pnl = final_equity - total_capital
    return {
        "net_pnl": round(net_pnl, 2),
        "total_return": round(net_pnl / total_capital, 6) if total_capital > 0 else 0.0,
        "number_of_trades": len(fills),
        "max_drawdown": round(max_drawdown, 6),
        "ending_equity_mad": round(final_equity, 2),
    }


def _make_fill(
    *,
    session: dt.date,
    symbol: str,
    action: str,
    quantity: float,
    price: float,
    realized_pnl: float,
    source: str,
) -> dict[str, Any]:
    return {
        "timestamp": session.isoformat(),
        "symbol": symbol,
        "action": action,
        "quantity": round(float(quantity), 8),
        "price_mad": round(float(price), 6),
        "fees_mad": 0.0,
        "realized_pnl_mad": round(float(realized_pnl), 2),
        "source": source,
    }


def _close_position(
    positions: dict[str, dict[str, Any]],
    *,
    symbol: str,
    quantity: float,
    price: float,
    session: dt.date,
    fills: list[dict[str, Any]],
    source: str,
) -> None:
    pos = positions.get(symbol)
    if not pos:
        return
    signed = float(pos.get("signed_qty") or 0.0)
    if abs(signed) <= 1e-9:
        return
    qty = min(abs(signed), float(quantity))
    avg = float(pos.get("avg_price") or price)
    if signed > 0:
        realized = (price - avg) * qty
        action = "SELL"
        signed_after = signed - qty
    else:
        realized = (avg - price) * qty
        action = "COVER"
        signed_after = signed + qty
    pos["realized_pnl_mad"] = float(pos.get("realized_pnl_mad") or 0.0) + realized
    pos["signed_qty"] = 0.0 if abs(signed_after) <= 1e-9 else signed_after
    if abs(float(pos["signed_qty"])) <= 1e-9:
        pos["avg_price"] = None
    fills.append(
        _make_fill(
            session=session,
            symbol=symbol,
            action=action,
            quantity=qty,
            price=price,
            realized_pnl=realized,
            source=source,
        )
    )


def _open_or_add_position(
    positions: dict[str, dict[str, Any]],
    *,
    symbol: str,
    signed_delta: float,
    price: float,
    session: dt.date,
    fills: list[dict[str, Any]],
    source: str,
) -> None:
    if abs(signed_delta) <= 1e-9:
        return
    pos = positions.setdefault(symbol, {"signed_qty": 0.0, "avg_price": None, "realized_pnl_mad": 0.0, "opened_at": session})
    current = float(pos.get("signed_qty") or 0.0)
    current_abs = abs(current)
    add_abs = abs(signed_delta)
    weighted = ((float(pos.get("avg_price") or 0.0) * current_abs) + (price * add_abs)) / max(current_abs + add_abs, 1e-9)
    pos["signed_qty"] = current + signed_delta
    pos["avg_price"] = round(weighted, 6)
    pos.setdefault("opened_at", session)
    fills.append(
        _make_fill(
            session=session,
            symbol=symbol,
            action="BUY" if signed_delta > 0 else "SELL_SHORT",
            quantity=add_abs,
            price=price,
            realized_pnl=0.0,
            source=source,
        )
    )


def _rebalance_to_target(
    positions: dict[str, dict[str, Any]],
    *,
    symbol: str,
    target_signed: float,
    price: float,
    session: dt.date,
    fills: list[dict[str, Any]],
) -> None:
    pos = positions.setdefault(symbol, {"signed_qty": 0.0, "avg_price": None, "realized_pnl_mad": 0.0, "opened_at": session})
    current = float(pos.get("signed_qty") or 0.0)
    if abs(current - target_signed) <= 1e-9:
        return
    if current and target_signed and (current > 0) != (target_signed > 0):
        _close_position(positions, symbol=symbol, quantity=abs(current), price=price, session=session, fills=fills, source="rebalance_flip")
        current = 0.0
    if abs(target_signed) < abs(current):
        _close_position(
            positions,
            symbol=symbol,
            quantity=abs(current) - abs(target_signed),
            price=price,
            session=session,
            fills=fills,
            source="rebalance_reduce",
        )
    elif abs(target_signed) > abs(current):
        delta = target_signed - current
        _open_or_add_position(
            positions,
            symbol=symbol,
            signed_delta=delta,
            price=price,
            session=session,
            fills=fills,
            source="rebalance_entry",
        )


def _apply_replay_risk(
    positions: dict[str, dict[str, Any]],
    *,
    symbol: str,
    bars: pd.DataFrame,
    session: dt.date,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
    fills: list[dict[str, Any]],
) -> None:
    pos = positions.get(symbol)
    if not pos:
        return
    signed = float(pos.get("signed_qty") or 0.0)
    avg = _safe_float(pos.get("avg_price"))
    if abs(signed) <= 1e-9 or avg is None:
        return
    high = _bar_value(bars, session, "High")
    low = _bar_value(bars, session, "Low")
    if high is None or low is None:
        return
    stop_frac = (stop_loss_pct or 0.0) / 100.0 if stop_loss_pct else None
    target_frac = (take_profit_pct or 0.0) / 100.0 if take_profit_pct else None
    exit_price: float | None = None
    source = "risk_exit"
    if signed > 0:
        if stop_frac is not None and low <= avg * (1.0 - stop_frac):
            exit_price = avg * (1.0 - stop_frac)
            source = "stop_loss"
        elif target_frac is not None and high >= avg * (1.0 + target_frac):
            exit_price = avg * (1.0 + target_frac)
            source = "take_profit"
    else:
        if stop_frac is not None and high >= avg * (1.0 + stop_frac):
            exit_price = avg * (1.0 + stop_frac)
            source = "stop_loss"
        elif target_frac is not None and low <= avg * (1.0 - target_frac):
            exit_price = avg * (1.0 - target_frac)
            source = "take_profit"
    if exit_price is not None:
        _close_position(
            positions,
            symbol=symbol,
            quantity=abs(signed),
            price=exit_price,
            session=session,
            fills=fills,
            source=source,
        )


def run_dashboard_portfolio_replay(
    db: Session,
    body: DashboardPortfolioReplayRequest,
    *,
    owner_user_id: str,
    portfolio_id: str | UUID | None = None,
) -> tuple[models.DashboardPortfolio, dict[str, Any]]:
    if body.end_date < body.start_date:
        raise ValueError("end_date must be greater than or equal to start_date")
    portfolio = _get_portfolio(db, owner_user_id=owner_user_id, portfolio_id=portfolio_id)
    symbols, component_shares = _components_to_symbols_and_shares(
        symbols=body.symbols or portfolio.symbols or [],
        components=body.components,
        component_shares=body.component_shares or portfolio.component_shares or {},
    )
    if not symbols:
        raise ValueError("Portfolio replay requires at least one symbol")

    bars_by_symbol: dict[str, pd.DataFrame] = {}
    symbol_dates: dict[str, list[dt.date]] = {}
    close_history: dict[str, pd.Series] = {}
    all_dates: set[dt.date] = set()
    for symbol in symbols:
        try:
            bars = _clean_bars(load_ohlcv_for_symbol(db, symbol, "1D"))
        except Exception:
            bars = pd.DataFrame()
        bars_by_symbol[symbol] = bars
        dates = sorted([item for item in bars.index if isinstance(item, dt.date)])
        symbol_dates[symbol] = dates
        all_dates.update(dates)
        if not bars.empty and "Close" in bars.columns:
            close_history[symbol] = bars["Close"].astype(float)

    if not all_dates:
        raise ValueError("No usable OHLCV rows for selected symbols")

    score_map = _load_score_map(
        db,
        symbols=symbols,
        start_date=body.start_date,
        end_date=body.end_date,
        horizon=body.horizon,
        display_mode=body.display_mode,
        technical_direction_mode=body.technical_direction_mode,
    )

    signal_dates = [session for session in sorted(all_dates) if body.start_date <= session <= body.end_date]
    event_targets: dict[dt.date, dict[str, float]] = {}
    deployable_capital = float(body.total_capital_mad) * max(0.0, 1.0 - float(body.cash_buffer_pct or 0.0) / 100.0)
    for signal_date in signal_dates:
        raw_directions = {
            symbol: _signal_direction(score_map.get((symbol, signal_date)))
            for symbol in symbols
        }
        target_symbols = [
            symbol
            for symbol, direction in raw_directions.items()
            if direction == "long" or (direction == "short" and body.side_policy == "long_short")
        ]
        hrp_weights: dict[str, float] = {}
        if body.allocation_method == "hrp" and target_symbols:
            history_to_date = {
                symbol: series[series.index <= signal_date]
                for symbol, series in close_history.items()
                if symbol in target_symbols
            }
            hrp_weights = compute_hrp_weights(history_to_date, target_symbols, lookback_bars=252)
            if not hrp_weights:
                hrp_weights = {symbol: 1.0 / len(target_symbols) for symbol in target_symbols}
        for symbol in symbols:
            execution_date = _next_session(symbol_dates.get(symbol, []), signal_date)
            if execution_date is None:
                continue
            direction = raw_directions.get(symbol, "none")
            target_signed = 0.0
            if direction == "long":
                price = _execution_price(bars_by_symbol[symbol], execution_date)
                if body.allocation_method == "hrp" and price:
                    target_signed = math.floor((deployable_capital * float(hrp_weights.get(symbol, 0.0))) / price)
                else:
                    target_signed = float(component_shares.get(symbol, 1))
            elif direction == "short" and body.side_policy == "long_short":
                price = _execution_price(bars_by_symbol[symbol], execution_date)
                if body.allocation_method == "hrp" and price:
                    target_signed = -math.floor((deployable_capital * float(hrp_weights.get(symbol, 0.0))) / price)
                else:
                    target_signed = -float(component_shares.get(symbol, 1))
            event_targets.setdefault(execution_date, {})[symbol] = target_signed

    positions: dict[str, dict[str, Any]] = {}
    fills: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    simulation_dates = [session for session in sorted(all_dates) if session >= body.start_date]
    cash = float(body.total_capital_mad)

    for session in simulation_dates:
        targets = event_targets.get(session, {})
        for symbol, target_signed in targets.items():
            price = _execution_price(bars_by_symbol[symbol], session)
            if price is None:
                continue
            before_fills = len(fills)
            _rebalance_to_target(
                positions,
                symbol=symbol,
                target_signed=target_signed,
                price=price,
                session=session,
                fills=fills,
            )
            for fill in fills[before_fills:]:
                notional = float(fill["quantity"]) * float(fill["price_mad"])
                if fill["action"] in {"SELL", "SELL_SHORT"}:
                    cash += notional
                else:
                    cash -= notional

        for symbol in symbols:
            before_fills = len(fills)
            _apply_replay_risk(
                positions,
                symbol=symbol,
                bars=bars_by_symbol[symbol],
                session=session,
                stop_loss_pct=body.stop_loss_pct,
                take_profit_pct=body.take_profit_pct,
                fills=fills,
            )
            for fill in fills[before_fills:]:
                notional = float(fill["quantity"]) * float(fill["price_mad"])
                if fill["action"] in {"SELL", "SELL_SHORT"}:
                    cash += notional
                else:
                    cash -= notional

        market_value = 0.0
        for symbol, pos in positions.items():
            signed = float(pos.get("signed_qty") or 0.0)
            if abs(signed) <= 1e-9:
                continue
            mark = _bar_value(bars_by_symbol.get(symbol, pd.DataFrame()), session, "Close")
            if mark is not None:
                market_value += signed * mark
                pos["last_mark_price_mad"] = mark
                pos["last_mark_date"] = session.isoformat()
        equity_curve.append(
            {
                "date": session.isoformat(),
                "cash_mad": round(cash, 2),
                "market_value_mad": round(market_value, 2),
                "equity_mad": round(cash + market_value, 2),
            }
        )

    active_positions: list[dict[str, Any]] = []
    realized_total = 0.0
    unrealized_total = 0.0
    market_value_total = 0.0
    for symbol, pos in positions.items():
        signed = float(pos.get("signed_qty") or 0.0)
        realized_total += float(pos.get("realized_pnl_mad") or 0.0)
        if abs(signed) <= 1e-9:
            continue
        mark = _safe_float(pos.get("last_mark_price_mad"))
        avg = _safe_float(pos.get("avg_price"))
        qty = abs(signed)
        side = "long" if signed > 0 else "short"
        market_value = qty * mark if mark is not None else 0.0
        unrealized = 0.0
        if mark is not None and avg is not None:
            unrealized = (mark - avg) * qty if side == "long" else (avg - mark) * qty
        market_value_total += market_value
        unrealized_total += unrealized
        active_positions.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": qty,
                "average_price_mad": avg,
                "market_value_mad": round(market_value, 2),
                "unrealized_pnl_mad": round(unrealized, 2),
                "realized_pnl_mad": round(float(pos.get("realized_pnl_mad") or 0.0), 2),
                "last_mark_price_mad": mark,
                "last_mark_date": pos.get("last_mark_date"),
                "opened_at": pos.get("opened_at").isoformat() if isinstance(pos.get("opened_at"), dt.date) else None,
            }
        )

    replay = {
        "start_date": body.start_date.isoformat(),
        "end_date": body.end_date.isoformat(),
        "generated_through_date": max(all_dates).isoformat(),
        "symbols": symbols,
        "component_shares": component_shares,
        "allocation_method": body.allocation_method,
        "side_policy": body.side_policy,
        "display_mode": body.display_mode,
        "technical_direction_mode": body.technical_direction_mode,
        "horizon": body.horizon,
        "stop_loss_pct": body.stop_loss_pct,
        "take_profit_pct": body.take_profit_pct,
        "fills": fills,
        "positions": active_positions,
        "equity_curve": equity_curve,
        "metrics": _portfolio_metrics(equity_curve, fills, float(body.total_capital_mad)),
        "summary": {
            "total_market_value_mad": round(market_value_total, 2),
            "total_unrealized_pnl_mad": round(unrealized_total, 2),
            "total_realized_pnl_mad": round(realized_total, 2),
            "fill_count": len(fills),
            "active_position_count": len(active_positions),
        },
    }

    if body.persist:
        (
            db.query(models.DeskPortfolioFill)
            .filter(models.DeskPortfolioFill.owner_user_id == owner_user_id)
            .filter(models.DeskPortfolioFill.portfolio_id == portfolio.id)
            .delete(synchronize_session=False)
        )
        (
            db.query(models.DeskPortfolioPosition)
            .filter(models.DeskPortfolioPosition.owner_user_id == owner_user_id)
            .filter(models.DeskPortfolioPosition.portfolio_id == portfolio.id)
            .delete(synchronize_session=False)
        )
        for fill in fills:
            timestamp = dt.datetime.combine(dt.date.fromisoformat(str(fill["timestamp"])), dt.time.min, tzinfo=dt.timezone.utc)
            db.add(
                models.DeskPortfolioFill(
                    owner_user_id=owner_user_id,
                    portfolio_id=portfolio.id,
                    timestamp=timestamp,
                    symbol=str(fill["symbol"]),
                    side=str(fill["action"]),
                    quantity=float(fill["quantity"]),
                    price_mad=float(fill["price_mad"]),
                    fees_mad=float(fill.get("fees_mad") or 0.0),
                    notes="historical replay",
                    meta_json={
                        "source": fill.get("source"),
                        "realized_pnl_mad": fill.get("realized_pnl_mad", 0.0),
                    },
                )
            )
        for position in active_positions:
            avg = _safe_float(position.get("average_price_mad"))
            side = str(position.get("side") or "long")
            stop = None
            target = None
            if avg is not None and body.stop_loss_pct is not None:
                stop = avg * (1.0 - body.stop_loss_pct / 100.0) if side == "long" else avg * (1.0 + body.stop_loss_pct / 100.0)
            if avg is not None and body.take_profit_pct is not None:
                target = avg * (1.0 + body.take_profit_pct / 100.0) if side == "long" else avg * (1.0 - body.take_profit_pct / 100.0)
            db.add(
                models.DeskPortfolioPosition(
                    owner_user_id=owner_user_id,
                    portfolio_id=portfolio.id,
                    symbol=str(position["symbol"]),
                    side=side,
                    quantity=float(position["quantity"]),
                    average_price_mad=avg,
                    opened_at=dt.date.fromisoformat(str(position["opened_at"])) if position.get("opened_at") else None,
                    stop_loss=stop,
                    target_1=target,
                    status="active",
                    notes="historical replay",
                    meta_json={
                        "source": "historical_replay",
                        "realized_pnl_mad": position.get("realized_pnl_mad", 0.0),
                        "last_mark_price_mad": position.get("last_mark_price_mad"),
                        "last_mark_date": position.get("last_mark_date"),
                    },
                )
            )
        portfolio.symbols = symbols
        portfolio.component_shares = component_shares
        portfolio.allocation_method = body.allocation_method
        portfolio.side_policy = body.side_policy
        portfolio.total_capital_mad = float(body.total_capital_mad)
        portfolio.cash_buffer_pct = float(body.cash_buffer_pct)
        portfolio.stop_loss_pct = body.stop_loss_pct
        portfolio.take_profit_pct = body.take_profit_pct
        portfolio.display_mode = body.display_mode
        portfolio.technical_direction_mode = body.technical_direction_mode
        portfolio.horizon = body.horizon
        portfolio.replay_start_date = body.start_date
        portfolio.replay_end_date = body.end_date
        portfolio.replay_generated_at = dt.datetime.now(dt.timezone.utc)
        portfolio.last_replay_json = replay
        db.commit()
        db.refresh(portfolio)
    return portfolio, replay


def create_dashboard_portfolio_from_history(
    db: Session,
    body: DashboardPortfolioFromHistoryRequest,
    *,
    owner_user_id: str,
) -> DashboardPortfolioReplayResponse:
    create_body = DashboardPortfolioCreate(**body.model_dump(exclude={"start_date", "end_date"}))
    portfolio_out = create_dashboard_portfolio(db, create_body, owner_user_id=owner_user_id)
    replay_body = DashboardPortfolioReplayRequest(
        **create_body.model_dump(),
        start_date=body.start_date,
        end_date=body.end_date,
        persist=True,
    )
    try:
        portfolio, replay = run_dashboard_portfolio_replay(
            db,
            replay_body,
            owner_user_id=owner_user_id,
            portfolio_id=portfolio_out.id,
        )
    except Exception:
        db.rollback()
        row = db.get(models.DashboardPortfolio, _resolve_portfolio_id(portfolio_out.id))
        if row is not None and row.owner_user_id == owner_user_id:
            db.delete(row)
            db.commit()
        raise
    summary = build_dashboard_portfolio_summary(db, owner_user_id=owner_user_id, portfolio_id=portfolio.id)
    return DashboardPortfolioReplayResponse(
        portfolio=_portfolio_to_out(portfolio, summary=summary),
        summary=summary.model_dump(mode="json"),
        replay=replay,
    )


def replay_dashboard_portfolio(
    db: Session,
    portfolio_id: str,
    body: DashboardPortfolioReplayRequest,
    *,
    owner_user_id: str,
) -> DashboardPortfolioReplayResponse:
    portfolio, replay = run_dashboard_portfolio_replay(
        db,
        body,
        owner_user_id=owner_user_id,
        portfolio_id=portfolio_id,
    )
    summary = build_dashboard_portfolio_summary(db, owner_user_id=owner_user_id, portfolio_id=portfolio.id)
    return DashboardPortfolioReplayResponse(
        portfolio=_portfolio_to_out(portfolio, summary=summary),
        summary=summary.model_dump(mode="json"),
        replay=replay,
    )


def create_dashboard_portfolio_backtest_run(
    db: Session,
    portfolio_id: str,
    *,
    owner_user_id: str,
) -> DashboardPortfolioBacktestRunResponse:
    portfolio = _get_portfolio(db, owner_user_id=owner_user_id, portfolio_id=portfolio_id)
    replay = portfolio.last_replay_json if isinstance(portfolio.last_replay_json, dict) else {}
    start_date = portfolio.replay_start_date
    end_date = portfolio.replay_end_date
    if start_date is None or end_date is None:
        raise ValueError("Generate a historical replay before launching a portfolio backtest")
    symbols = _clean_symbols([str(item) for item in (portfolio.symbols or [])])
    if not symbols:
        raise ValueError("Portfolio backtest requires at least one component")

    horizon = canonical_horizon(portfolio.horizon or "monthly", allow_legacy=True)
    strategy = models.SavedStrategy(
        name=f"{portfolio.name} replay",
        note=f"Generated from dashboard portfolio {portfolio.name}",
        status="saved",
        side_policy=portfolio.side_policy or "long_only",
        horizon=horizon,
        config_json={
            "schema_version": 3,
            "app_domain": "dashboard_portfolio",
            "portfolio": {
                "total_capital_mad": float(portfolio.total_capital_mad or 0.0),
                "universe": {
                    "basket": symbols,
                    "selection_mode": "dashboard_portfolio",
                },
                "allocation": {
                    "method": portfolio.allocation_method or "share_quantities",
                    "component_shares": _clean_component_shares(portfolio.component_shares or {}),
                },
            },
            "dashboard_portfolio_replay": replay,
        },
    )
    db.add(strategy)
    db.flush()

    request_json = {
        "mode": "portfolio_replay",
        "portfolio_id": str(portfolio.id),
        "owner_user_id": owner_user_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "timeframe": "1D",
        "replay": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "symbols": symbols,
            "component_shares": _clean_component_shares(portfolio.component_shares or {}),
            "allocation_method": portfolio.allocation_method or "share_quantities",
            "side_policy": portfolio.side_policy or "long_only",
            "total_capital_mad": float(portfolio.total_capital_mad or 0.0),
            "cash_buffer_pct": float(portfolio.cash_buffer_pct or 0.0),
            "stop_loss_pct": _safe_float(portfolio.stop_loss_pct),
            "take_profit_pct": _safe_float(portfolio.take_profit_pct),
            "display_mode": portfolio.display_mode or "trade_opportunities",
            "technical_direction_mode": portfolio.technical_direction_mode or "best",
            "horizon": portfolio.horizon or "monthly",
            "persist": False,
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(request_json, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    title = f"{portfolio.name} - Portfolio Replay"
    run = models.StrategyBacktestRun(
        strategy_id=strategy.id,
        title=title,
        mode="portfolio_replay",
        status="queued",
        horizon=horizon,
        execution_fingerprint=fingerprint,
        strategy_snapshot_json={
            "strategy_name": strategy.name,
            "side_policy": strategy.side_policy,
            "horizon": horizon,
            "basket": symbols,
            "config_json": strategy.config_json,
        },
        data_snapshot_json={"timeframe": "1D", "symbols": symbols},
        request_json=request_json,
        progress_json={"completed": 0, "total": len(symbols), "message": "Queued"},
    )
    db.add(run)
    db.flush()
    for symbol in symbols:
        db.add(models.StrategyBacktestStock(run_id=run.id, symbol=symbol, status="queued"))
    job = get_queue().enqueue(
        "services.worker.tasks.strategy_backtest_runs.execute_strategy_backtest_run",
        str(run.id),
        job_timeout=int(settings.RUN_JOB_TIMEOUT_SECONDS),
        result_ttl=int(settings.RUN_JOB_RESULT_TTL_SECONDS),
        failure_ttl=int(settings.RUN_JOB_FAILURE_TTL_SECONDS),
    )
    run.rq_job_id = str(job.id)
    db.commit()
    return DashboardPortfolioBacktestRunResponse(
        strategy_id=str(strategy.id),
        run_id=str(run.id),
        status=run.status,
        mode=run.mode,
        title=title,
    )
