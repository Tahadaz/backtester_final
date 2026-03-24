"""
refresh_market_data.py — Worker tasks for scheduled/manual market data refresh.

Two entry points:
  refresh_all_tracked_symbols(refresh_run_id, timeframe, source_override, include_unverified)
  refresh_single_symbol(refresh_run_id, symbol, timeframe, source)

Both update market_refresh_run status in the DB and log per-symbol errors
into market_refresh_error. Parquet storage reuses the merge logic from
ingest_market_data.py to stay consistent with the manual upload flow.
"""
from __future__ import annotations

import datetime
import traceback
from io import BytesIO
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.worker.db import SessionLocal
from services.worker.config import settings
from services.worker.storage import s3_client, ensure_bucket

# Reuse core normalizer and merge logic
from core.quant_core.data import (
    _standardize_ohlcv,
    _validate_ohlcv,
    BourseDirectAdapter,
    YFinanceMoroccoAdapter,
    BDCSessionAdapter,
)
from core.quant_core.s3_keys import build_market_store_object_key

# Reuse merge helper from the existing ingest task
from services.worker.tasks.ingest_market_data import (
    _merge_overwrite_if_different,
    _try_load_existing_parquet,
    _save_parquet,
)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _set_run_status(
    db: Session,
    run_id: UUID,
    status: str,
    *,
    started_at: Optional[datetime.datetime] = None,
    finished_at: Optional[datetime.datetime] = None,
    symbols_done: Optional[int] = None,
    symbols_failed: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    params: dict = {"id": run_id, "status": status}
    set_clauses = ["status = :status"]

    if started_at is not None:
        params["started_at"] = started_at
        set_clauses.append("started_at = :started_at")
    if finished_at is not None:
        params["finished_at"] = finished_at
        set_clauses.append("finished_at = :finished_at")
    if symbols_done is not None:
        params["symbols_done"] = symbols_done
        set_clauses.append("symbols_done = :symbols_done")
    if symbols_failed is not None:
        params["symbols_failed"] = symbols_failed
        set_clauses.append("symbols_failed = :symbols_failed")
    if error_message is not None:
        params["error_message"] = error_message
        set_clauses.append("error_message = :error_message")

    db.execute(
        text(f"UPDATE market_refresh_run SET {', '.join(set_clauses)} WHERE id = :id"),
        params,
    )
    db.commit()


def _log_error(
    db: Session,
    run_id: UUID,
    symbol: str,
    provider: str,
    error_type: str,
    error_message: str,
    raw_response: Optional[str] = None,
) -> None:
    db.execute(
        text("""
            INSERT INTO market_refresh_error
                (refresh_run_id, symbol, provider, error_type, error_message, raw_response, created_at)
            VALUES
                (:run_id, :symbol, :provider, :error_type, :error_message, :raw_response, now())
        """),
        {
            "run_id": run_id,
            "symbol": symbol,
            "provider": provider,
            "error_type": error_type,
            "error_message": error_message[:4000] if error_message else None,
            "raw_response": (raw_response or "")[:2000] or None,
        },
    )
    db.commit()


def _upsert_market_data_store(
    db: Session,
    symbol: str,
    timeframe: str,
    object_key: str,
    start_ts: datetime.datetime,
    end_ts: datetime.datetime,
    row_count: int,
    source_provider: str,
    data_as_of: datetime.date,
) -> None:
    db.execute(
        text("""
            INSERT INTO market_data_store
                (symbol, timeframe, object_key, start_ts, end_ts, row_count,
                 source_provider, data_as_of, created_at, updated_at)
            VALUES
                (:symbol, :timeframe, :object_key, :start_ts, :end_ts, :row_count,
                 :source_provider, :data_as_of, now(), now())
            ON CONFLICT (symbol, timeframe)
            DO UPDATE SET
                object_key      = excluded.object_key,
                start_ts        = excluded.start_ts,
                end_ts          = excluded.end_ts,
                row_count       = excluded.row_count,
                source_provider = excluded.source_provider,
                data_as_of      = excluded.data_as_of,
                updated_at      = now()
        """),
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "object_key": object_key,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "row_count": row_count,
            "source_provider": source_provider,
            "data_as_of": data_as_of,
        },
    )
    db.commit()


def _resolve_provider_symbol(db: Session, symbol: str, provider: str) -> str:
    """Return the provider-specific ticker for an internal symbol.

    Falls back to the internal symbol itself if no mapping is found.
    """
    row = db.execute(
        text("""
            SELECT provider_symbol FROM provider_symbol_map
            WHERE symbol = :symbol AND provider = :provider
        """),
        {"symbol": symbol, "provider": provider},
    ).mappings().first()
    if row:
        return str(row["provider_symbol"])
    # Default fallbacks
    if provider == "yahoo":
        return f"{symbol}.CS"
    return symbol


def _do_refresh_symbol(
    db: Session,
    run_id: UUID,
    symbol: str,
    timeframe: str,
    source: str,
) -> dict:
    """
    Fetch, merge, and persist OHLCV for one symbol.
    Returns a result dict with status and counts.
    Raises on unrecoverable errors (caller catches and logs).
    """
    provider_symbol = _resolve_provider_symbol(db, symbol, source)

    # Pick adapter
    use_session_adapter = False

    if source == "yahoo":
        adapter = YFinanceMoroccoAdapter(timezone="UTC", use_cache=False)
        # Pass the provider_symbol directly via map so YFinanceMoroccoAdapter uses it
        adapter.provider_map = {symbol: provider_symbol}
    else:
        # bourse_direct (or any other source): prefer the downloadable-file adapter
        # when a URL template is explicitly configured; otherwise use the BDC public
        # session page scraper (Données de la séance — server-rendered HTML).
        import os
        if os.environ.get("BOURSE_DIRECT_URL_TEMPLATE", "").strip():
            adapter = BourseDirectAdapter(timezone="UTC", use_cache=False)
        else:
            adapter = BDCSessionAdapter(timezone="UTC", use_cache=False)
            use_session_adapter = True

    # Determine fetch start: use existing end_ts to do incremental fetch
    existing_end_ts_row = db.execute(
        text("SELECT end_ts FROM market_data_store WHERE symbol = :s AND timeframe = :tf"),
        {"s": symbol, "tf": timeframe},
    ).mappings().first()

    fetch_start: Optional[str] = None
    if existing_end_ts_row and existing_end_ts_row["end_ts"]:
        # The live Bourse session scraper returns only the current/last trading day.
        # Re-fetch the last stored day so an in-flight session bar can be overwritten
        # when the exchange page updates intraday.
        last_dt: datetime.datetime = existing_end_ts_row["end_ts"]
        if use_session_adapter:
            fetch_start = last_dt.strftime("%Y-%m-%d")
        else:
            # Historical adapters can safely start from the next day to avoid
            # re-fetching the full already-materialized range.
            fetch_start = (last_dt + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    # Load data from adapter
    market_data = adapter.load(
        symbols=[symbol],
        start=fetch_start,
        end=None,
        interval="1d",
    )

    df_new = market_data.bars.get(symbol)
    if df_new is None or df_new.empty:
        return {"status": "no_new_data", "inserted_count": 0, "overwritten_overlap_count": 0}

    # Validate
    df_new = _validate_ohlcv(df_new, symbol=symbol)
    if df_new.empty:
        return {"status": "invalid_data", "inserted_count": 0, "overwritten_overlap_count": 0}

    # Keep only canonical columns
    keep_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df_new.columns]
    df_new = df_new[keep_cols]

    # Load existing parquet and merge
    object_key = build_market_store_object_key(symbol, timeframe)
    ensure_bucket()
    old_df = _try_load_existing_parquet(object_key)
    merged, summary = _merge_overwrite_if_different(old_df, df_new)

    if summary["status"] != "unchanged":
        _save_parquet(object_key, merged)

    start_ts = merged.index.min().to_pydatetime()
    end_ts = merged.index.max().to_pydatetime()
    data_as_of = end_ts.date()

    _upsert_market_data_store(
        db=db,
        symbol=symbol,
        timeframe=timeframe,
        object_key=object_key,
        start_ts=start_ts,
        end_ts=end_ts,
        row_count=int(len(merged)),
        source_provider=source,
        data_as_of=data_as_of,
    )

    return {
        "status": summary["status"],
        "inserted_count": summary["inserted_count"],
        "overwritten_overlap_count": summary["overwritten_overlap_count"],
        "object_key": object_key,
        "start_ts": start_ts.isoformat(),
        "end_ts": end_ts.isoformat(),
        "row_count": int(len(merged)),
    }


def refresh_single_symbol(
    refresh_run_id: str,
    symbol: str,
    timeframe: str = "1D",
    source: str = "bourse_direct",
) -> dict:
    """
    RQ task: refresh OHLCV for a single tracked symbol.
    Updates market_refresh_run status and logs errors.
    """
    run_id = UUID(refresh_run_id)
    db: Session = SessionLocal()

    try:
        _set_run_status(db, run_id, "running", started_at=_utcnow())

        result = _do_refresh_symbol(db, run_id, symbol, timeframe, source)

        _set_run_status(
            db, run_id, "succeeded",
            finished_at=_utcnow(),
            symbols_done=1,
            symbols_failed=0,
        )
        return {"refresh_run_id": refresh_run_id, "symbol": symbol, **result}

    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {exc}"
        _log_error(
            db, run_id, symbol, source,
            error_type="refresh_error",
            error_message=err_msg,
            raw_response=traceback.format_exc()[:2000],
        )
        _set_run_status(
            db, run_id, "failed",
            finished_at=_utcnow(),
            symbols_done=0,
            symbols_failed=1,
            error_message=err_msg[:2000],
        )
        raise

    finally:
        db.close()


def refresh_all_tracked_symbols(
    refresh_run_id: str,
    timeframe: str = "1D",
    source_override: Optional[str] = None,
    include_unverified: bool = False,
) -> dict:
    """
    RQ task: refresh OHLCV for all active tracked symbols sequentially.
    Updates market_refresh_run with per-symbol progress.
    Sets status to 'succeeded', 'partial', or 'failed'.
    """
    run_id = UUID(refresh_run_id)
    db: Session = SessionLocal()

    try:
        _set_run_status(db, run_id, "running", started_at=_utcnow())

        # Load active symbols
        rows = db.execute(
            text("SELECT symbol, track_source FROM stock_master WHERE is_active = true ORDER BY symbol"),
        ).mappings().all()
        symbols = [(str(r["symbol"]), str(r["track_source"])) for r in rows]

        # Update total count (may differ from what API estimated if stocks changed)
        db.execute(
            text("UPDATE market_refresh_run SET symbols_total = :n WHERE id = :id"),
            {"n": len(symbols), "id": run_id},
        )
        db.commit()

        done = 0
        failed = 0
        results: dict = {}

        for symbol, track_source in symbols:
            source = source_override or track_source
            try:
                result = _do_refresh_symbol(db, run_id, symbol, timeframe, source)
                results[symbol] = result
                done += 1
            except Exception as exc:
                err_msg = f"{type(exc).__name__}: {exc}"
                _log_error(
                    db, run_id, symbol, source,
                    error_type="refresh_error",
                    error_message=err_msg,
                    raw_response=traceback.format_exc()[:2000],
                )
                results[symbol] = {"status": "error", "error": err_msg}
                failed += 1

            # Update progress after each symbol
            db.execute(
                text("""
                    UPDATE market_refresh_run
                    SET symbols_done = :done, symbols_failed = :failed
                    WHERE id = :id
                """),
                {"done": done, "failed": failed, "id": run_id},
            )
            db.commit()

        if failed == 0:
            final_status = "succeeded"
        elif done == 0:
            final_status = "failed"
        else:
            final_status = "partial"

        _set_run_status(
            db, run_id, final_status,
            finished_at=_utcnow(),
            symbols_done=done,
            symbols_failed=failed,
        )
        return {
            "refresh_run_id": refresh_run_id,
            "status": final_status,
            "symbols_done": done,
            "symbols_failed": failed,
            "results": results,
        }

    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {exc}"
        _set_run_status(
            db, run_id, "failed",
            finished_at=_utcnow(),
            error_message=err_msg[:2000],
        )
        raise

    finally:
        db.close()
