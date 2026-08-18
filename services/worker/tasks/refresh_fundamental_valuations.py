from __future__ import annotations

from services.api.app.services.fundamentals import (
    VALUATION_SCENARIOS,
    latest_snapshot_rows_by_symbol,
    make_bulk_overrides_loader,
    recompute_symbol_valuations_all_scenarios,
)
from services.worker.db import SessionLocal


def refresh_fundamental_valuations(symbols: list[str]) -> dict[str, object]:
    """Recompute stale valuation trios, persisting each symbol independently."""

    normalized = sorted({str(symbol).strip().upper() for symbol in symbols if symbol and str(symbol).strip()})
    refreshed: list[str] = []
    skipped: list[str] = []
    failures: list[dict[str, str]] = []
    valuation_count = 0

    for symbol in normalized:
        db = SessionLocal()
        try:
            snapshot = latest_snapshot_rows_by_symbol(db, symbols=[symbol]).get(symbol)
            if snapshot is None:
                skipped.append(symbol)
                continue
            rows = recompute_symbol_valuations_all_scenarios(
                db,
                import_id=snapshot.import_id,
                symbol=symbol,
                scenarios=VALUATION_SCENARIOS,
                overrides_loader=make_bulk_overrides_loader(db, [symbol]),
            )
            db.commit()
            valuation_count += len(rows)
            refreshed.append(symbol)
        except Exception as exc:
            db.rollback()
            failures.append({"symbol": symbol, "error": str(exc)})
        finally:
            db.close()

    return {
        "requested": len(normalized),
        "refreshed": refreshed,
        "skipped": skipped,
        "failures": failures,
        "valuation_count": valuation_count,
    }
