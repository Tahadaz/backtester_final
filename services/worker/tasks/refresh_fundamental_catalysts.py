from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from core.quant_core.fundamentals.catalysts import normalize_yfinance_calendar

from services.api.app import models
from services.api.app.json_sanitize import sanitize_json_compatible
from services.worker.db import SessionLocal


logger = logging.getLogger(__name__)


def _selected_symbols(db, symbols: list[str] | None = None) -> list[str]:
    query = db.query(models.StockMaster).filter(models.StockMaster.is_active.is_(True))
    if symbols:
        query = query.filter(models.StockMaster.symbol.in_([symbol.upper() for symbol in symbols]))
    return [row.symbol for row in query.order_by(models.StockMaster.symbol.asc()).all()]


def _same_event_query(db, row: dict[str, Any]):
    return db.query(models.FundamentalCatalyst).filter(
        models.FundamentalCatalyst.symbol == row["symbol"],
        models.FundamentalCatalyst.event_type == row["event_type"],
        models.FundamentalCatalyst.source == row["source"],
        models.FundamentalCatalyst.is_active.is_(True),
    )


def _upsert_catalyst(db, row: dict[str, Any]) -> str:
    exact = _same_event_query(db, row).filter(models.FundamentalCatalyst.event_date == row["event_date"]).first()
    if exact is not None:
        exact.event_date_confidence = row["event_date_confidence"]
        exact.impact_tier = row["impact_tier"]
        exact.expected_direction = row.get("expected_direction")
        exact.title = row["title"]
        exact.notes = row.get("notes")
        exact.source_payload_json = sanitize_json_compatible(row.get("source_payload") or {})
        db.add(exact)
        return "updated"
    near = (
        _same_event_query(db, row)
        .filter(
            models.FundamentalCatalyst.event_date >= row["event_date"] - dt.timedelta(days=14),
            models.FundamentalCatalyst.event_date <= row["event_date"] + dt.timedelta(days=14),
        )
        .order_by(models.FundamentalCatalyst.event_date.desc())
        .first()
    )
    if near is not None:
        near.event_date = row["event_date"]
        near.event_date_confidence = row["event_date_confidence"]
        near.impact_tier = row["impact_tier"]
        near.expected_direction = row.get("expected_direction")
        near.title = row["title"]
        near.notes = row.get("notes")
        near.source_payload_json = sanitize_json_compatible(row.get("source_payload") or {})
        db.add(near)
        return "updated"
    new_row = models.FundamentalCatalyst(
        symbol=row["symbol"],
        event_type=row["event_type"],
        event_date=row["event_date"],
        event_date_confidence=row["event_date_confidence"],
        impact_tier=row["impact_tier"],
        expected_direction=row.get("expected_direction"),
        title=row["title"],
        notes=row.get("notes"),
        source=row["source"],
        source_payload_json=sanitize_json_compatible(row.get("source_payload") or {}),
        is_active=True,
    )
    older = _same_event_query(db, row).order_by(models.FundamentalCatalyst.event_date.desc()).first()
    db.add(new_row)
    db.flush()
    if older is not None and abs((older.event_date - row["event_date"]).days) > 14:
        older.is_active = False
        older.superseded_by_id = new_row.id
        db.add(older)
        return "superseded"
    return "created"


def refresh_fundamental_catalysts(symbols: list[str] | None = None) -> dict[str, Any]:
    import yfinance as yf

    db = SessionLocal()
    counts = {"created": 0, "updated": 0, "superseded": 0, "failed": 0}
    try:
        for symbol in _selected_symbols(db, symbols):
            try:
                ticker = yf.Ticker(symbol)
                rows = normalize_yfinance_calendar(symbol, getattr(ticker, "calendar", None), getattr(ticker, "dividends", None))
                for row in rows:
                    outcome = _upsert_catalyst(db, row)
                    counts[outcome] = counts.get(outcome, 0) + 1
                db.commit()
            except Exception:
                counts["failed"] += 1
                db.rollback()
                logger.debug("catalyst refresh failed for %s", symbol, exc_info=True)
        return counts
    finally:
        db.close()


if __name__ == "__main__":
    print(refresh_fundamental_catalysts())
