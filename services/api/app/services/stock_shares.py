from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from .. import models
from ..masi_tickers import get_masi_info, is_masi_ticker


@dataclass(frozen=True)
class StockShareRecord:
    symbol: str
    display_name: str | None
    shares_outstanding: int | None
    shares_as_of: dt.date | None
    shares_source: str | None
    shares_updated_at: dt.datetime | None


def _positive_int(value: object) -> int | None:
    try:
        out = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def list_stock_share_records(
    db: Session,
    *,
    symbols: Iterable[str] | None = None,
    active_only: bool = True,
    masi_only: bool = True,
    require_shares: bool = False,
) -> list[StockShareRecord]:
    target_symbols = {
        str(symbol or "").strip().upper()
        for symbol in (symbols or [])
        if str(symbol or "").strip()
    }

    query = db.query(models.StockMaster)
    if active_only:
        query = query.filter(models.StockMaster.is_active.is_(True))
    if target_symbols:
        query = query.filter(models.StockMaster.symbol.in_(target_symbols))

    records: list[StockShareRecord] = []
    for stock in query.order_by(models.StockMaster.symbol.asc()).all():
        symbol = str(stock.symbol or "").strip().upper()
        if not symbol:
            continue
        if masi_only and not is_masi_ticker(symbol):
            continue

        shares = _positive_int(getattr(stock, "shares_outstanding", None))
        if require_shares and shares is None:
            continue

        masi_info = get_masi_info(symbol)
        display_name = stock.display_name or (masi_info.get("display_name") if masi_info else None)
        records.append(
            StockShareRecord(
                symbol=symbol,
                display_name=display_name,
                shares_outstanding=shares,
                shares_as_of=getattr(stock, "shares_as_of", None),
                shares_source=getattr(stock, "shares_source", None),
                shares_updated_at=getattr(stock, "shares_updated_at", None),
            )
        )

    return records


def stock_shares_by_symbol(
    db: Session,
    *,
    symbols: Iterable[str] | None = None,
    require_shares: bool = True,
) -> dict[str, int]:
    return {
        record.symbol: int(record.shares_outstanding)
        for record in list_stock_share_records(
            db,
            symbols=symbols,
            require_shares=require_shares,
        )
        if record.shares_outstanding is not None
    }
