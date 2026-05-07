from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..schemas.dashboard_indices import (
    DashboardCustomIndexCreate,
    DashboardCustomIndexOut,
    DashboardCustomIndexUpdate,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="name cannot be empty")
    return normalized


def _normalize_symbols(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in symbols:
        token = str(raw or "").strip().upper()
        if not token or token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    if not normalized:
        raise HTTPException(status_code=422, detail="symbols must include at least one valid symbol")
    return normalized


def _to_out(row: models.DashboardCustomIndex) -> DashboardCustomIndexOut:
    return DashboardCustomIndexOut(
        id=str(row.id),
        name=row.name,
        symbols=[str(item).strip().upper() for item in (row.symbols or []) if str(item).strip()],
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


def _parse_uuid(index_id: str) -> UUID:
    try:
        return UUID(index_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Index not found")


@router.get("/indices", response_model=list[DashboardCustomIndexOut])
def list_dashboard_indices(db: Session = Depends(get_db)) -> list[DashboardCustomIndexOut]:
    rows = (
        db.query(models.DashboardCustomIndex)
        .order_by(models.DashboardCustomIndex.updated_at.desc(), models.DashboardCustomIndex.name.asc())
        .all()
    )
    return [_to_out(row) for row in rows]


@router.post("/indices", response_model=DashboardCustomIndexOut, status_code=status.HTTP_201_CREATED)
def create_dashboard_index(
    body: DashboardCustomIndexCreate,
    db: Session = Depends(get_db),
) -> DashboardCustomIndexOut:
    name = _normalize_name(body.name)
    symbols = _normalize_symbols(body.symbols)

    duplicate = (
        db.query(models.DashboardCustomIndex)
        .filter(func.lower(models.DashboardCustomIndex.name) == name.lower())
        .one_or_none()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Index name already exists")

    row = models.DashboardCustomIndex(
        name=name,
        symbols=symbols,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.put("/indices/{index_id}", response_model=DashboardCustomIndexOut)
def update_dashboard_index(
    index_id: str,
    body: DashboardCustomIndexUpdate,
    db: Session = Depends(get_db),
) -> DashboardCustomIndexOut:
    index_uuid = _parse_uuid(index_id)
    row = (
        db.query(models.DashboardCustomIndex)
        .filter(models.DashboardCustomIndex.id == index_uuid)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Index not found")

    name = _normalize_name(body.name)
    symbols = _normalize_symbols(body.symbols)

    duplicate = (
        db.query(models.DashboardCustomIndex)
        .filter(func.lower(models.DashboardCustomIndex.name) == name.lower())
        .filter(models.DashboardCustomIndex.id != row.id)
        .one_or_none()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Index name already exists")

    row.name = name
    row.symbols = symbols
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.delete("/indices/{index_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dashboard_index(index_id: str, db: Session = Depends(get_db)) -> Response:
    index_uuid = _parse_uuid(index_id)
    row = (
        db.query(models.DashboardCustomIndex)
        .filter(models.DashboardCustomIndex.id == index_uuid)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Index not found")

    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

