from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..auth import AppUser, require_app_user, require_auth
from ..db import get_db
from ..schemas.dashboard_indices import (
    DashboardCustomIndexCreate,
    DashboardCustomIndexOut,
    DashboardCustomIndexUpdate,
    DashboardIndexComponent,
)
from ..services.dashboard_builder import (
    HORIZON_ALIASES,
    HORIZONS,
    build_dashboard_portfolio_edge_for_symbols,
)
from ..services.stock_shares import stock_shares_by_symbol

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="name cannot be empty")
    return normalized


def _clean_symbols(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in symbols:
        token = str(raw or "").strip().upper()
        if not token or token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    return normalized


def _normalize_symbols(symbols: list[str]) -> list[str]:
    normalized = _clean_symbols(symbols)
    if not normalized:
        raise HTTPException(status_code=422, detail="symbols must include at least one valid symbol")
    return normalized


def _normalize_horizon(raw: str) -> str:
    token = str(raw or "").strip().lower()
    normalized = HORIZON_ALIASES.get(token, token)
    if normalized not in HORIZONS:
        raise HTTPException(status_code=400, detail="Invalid horizon")
    return normalized


def _normalize_component_shares(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}

    normalized: dict[str, int] = {}
    for raw_symbol, raw_shares in raw.items():
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol:
            continue
        try:
            shares = int(raw_shares)
        except (TypeError, ValueError):
            continue
        if shares <= 0:
            continue
        normalized[symbol] = shares
    return normalized


def _normalize_components(components: list[DashboardIndexComponent]) -> tuple[list[str], dict[str, int]]:
    seen: set[str] = set()
    symbols: list[str] = []
    component_shares: dict[str, int] = {}
    for component in components:
        symbol = str(component.symbol or "").strip().upper()
        if not symbol:
            continue
        if symbol in seen:
            raise HTTPException(status_code=422, detail=f"duplicate component symbol: {symbol}")
        seen.add(symbol)
        symbols.append(symbol)
        component_shares[symbol] = int(component.shares)
    if not symbols:
        raise HTTPException(status_code=422, detail="components must include at least one valid symbol")
    return symbols, component_shares


def _normalize_definition_payload(
    *,
    db: Session,
    symbols: list[str] | None,
    components: list[DashboardIndexComponent] | None,
    use_available_shares: bool = False,
) -> tuple[list[str], dict[str, int]]:
    if use_available_shares:
        target_symbols = _clean_symbols(symbols or [])
        shares_by_symbol = stock_shares_by_symbol(
            db,
            symbols=target_symbols or None,
            require_shares=True,
        )
        if not shares_by_symbol:
            raise HTTPException(status_code=422, detail="No available stock share counts found")
        selected_symbols = target_symbols or sorted(shares_by_symbol)
        component_shares = {
            symbol: shares_by_symbol[symbol]
            for symbol in selected_symbols
            if symbol in shares_by_symbol
        }
        if not component_shares:
            raise HTTPException(status_code=422, detail="No selected symbols have available share counts")
        return list(component_shares.keys()), component_shares
    if components is not None:
        return _normalize_components(components)
    return _normalize_symbols(symbols or []), {}


def _weighted_complete(symbols: list[str], component_shares: dict[str, int]) -> bool:
    return bool(symbols) and all(int(component_shares.get(symbol, 0)) > 0 for symbol in symbols)


def _to_out(
    row: models.DashboardCustomIndex,
    *,
    portfolio_edge: dict | None = None,
) -> DashboardCustomIndexOut:
    symbols = _clean_symbols([str(item) for item in (row.symbols or [])])
    component_shares = _normalize_component_shares(getattr(row, "component_shares", None))
    components = [
        DashboardIndexComponent(symbol=symbol, shares=component_shares[symbol])
        for symbol in symbols
        if symbol in component_shares
    ]
    return DashboardCustomIndexOut(
        id=str(row.id),
        name=row.name,
        symbols=symbols,
        component_shares={symbol: component_shares[symbol] for symbol in symbols if symbol in component_shares},
        components=components,
        is_weighted_complete=_weighted_complete(symbols, component_shares),
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
        portfolio_edge=portfolio_edge,
    )


def _parse_uuid(index_id: str) -> UUID:
    try:
        return UUID(index_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Index not found")


@router.get("/indices", response_model=list[DashboardCustomIndexOut])
def list_dashboard_indices(
    horizon: str | None = Query(default=None),
    include_edge: bool = Query(default=False),
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[DashboardCustomIndexOut]:
    rows = (
        db.query(models.DashboardCustomIndex)
        .filter(models.DashboardCustomIndex.owner_user_id == user.id)
        .order_by(models.DashboardCustomIndex.updated_at.desc(), models.DashboardCustomIndex.name.asc())
        .all()
    )
    if not include_edge:
        return [_to_out(row) for row in rows]

    normalized_horizon = _normalize_horizon(horizon or "monthly")
    best_signal_cache: dict[str, dict | None] = {}
    member_cache: dict[tuple[str, str, str, str, str], object] = {}
    out: list[DashboardCustomIndexOut] = []
    for row in rows:
        edge = build_dashboard_portfolio_edge_for_symbols(
            db,
            normalized_horizon,
            [str(item) for item in (row.symbols or [])],
            best_signal_cache=best_signal_cache,
            member_cache=member_cache,
        )
        out.append(_to_out(row, portfolio_edge=edge))
    return out


@router.post("/indices", response_model=DashboardCustomIndexOut, status_code=status.HTTP_201_CREATED)
def create_dashboard_index(
    body: DashboardCustomIndexCreate,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardCustomIndexOut:
    name = _normalize_name(body.name)
    symbols, component_shares = _normalize_definition_payload(
        db=db,
        symbols=body.symbols,
        components=body.components,
        use_available_shares=body.use_available_shares,
    )

    duplicate = (
        db.query(models.DashboardCustomIndex)
        .filter(models.DashboardCustomIndex.owner_user_id == user.id)
        .filter(func.lower(models.DashboardCustomIndex.name) == name.lower())
        .one_or_none()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Index name already exists")

    row = models.DashboardCustomIndex(
        owner_user_id=user.id,
        name=name,
        symbols=symbols,
        component_shares=component_shares,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.put("/indices/{index_id}", response_model=DashboardCustomIndexOut)
def update_dashboard_index(
    index_id: str,
    body: DashboardCustomIndexUpdate,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardCustomIndexOut:
    index_uuid = _parse_uuid(index_id)
    row = (
        db.query(models.DashboardCustomIndex)
        .filter(models.DashboardCustomIndex.id == index_uuid)
        .filter(models.DashboardCustomIndex.owner_user_id == user.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Index not found")

    name = _normalize_name(body.name)
    symbols, component_shares = _normalize_definition_payload(
        db=db,
        symbols=body.symbols,
        components=body.components,
        use_available_shares=body.use_available_shares,
    )

    duplicate = (
        db.query(models.DashboardCustomIndex)
        .filter(models.DashboardCustomIndex.owner_user_id == user.id)
        .filter(func.lower(models.DashboardCustomIndex.name) == name.lower())
        .filter(models.DashboardCustomIndex.id != row.id)
        .one_or_none()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Index name already exists")

    row.name = name
    row.symbols = symbols
    row.component_shares = component_shares
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.delete("/indices/{index_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dashboard_index(
    index_id: str,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> Response:
    index_uuid = _parse_uuid(index_id)
    row = (
        db.query(models.DashboardCustomIndex)
        .filter(models.DashboardCustomIndex.id == index_uuid)
        .filter(models.DashboardCustomIndex.owner_user_id == user.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Index not found")

    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

