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
import os
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
    _standardize_ohlcv_index,
    _validate_ohlcv,
    BourseDirectAdapter,
    YFinanceMoroccoAdapter,
    BDCSessionAdapter,
    CasablancaBourseIndicesAdapter,
)
from core.quant_core.s3_keys import build_market_store_object_key

# Reuse merge helper from the existing ingest task
from services.worker.tasks.ingest_market_data import (
    _merge_overwrite_if_different,
    _try_load_existing_parquet,
    _save_parquet,
)
from services.worker.tasks.dashboard_snapshot import regenerate_dashboard_snapshot
from services.api.app.services.weekly_recompute_policy import (
    is_friday_market_refresh,
    iter_signal_engine_weekly_stale_tuples,
    iter_wfo_weekly_stale_tuples,
)


def _enqueue_signal_layers_after_refresh(
    symbol: str,
    *,
    db: Session | None = None,
    now: datetime.datetime | None = None,
) -> None:
    """Best-effort: enqueue post-refresh signal-layer jobs.

    Daily market refresh keeps the same representative sets but recomputes each
    saved representative's current signal/value for both Signal Engine and WFO.
    Set SIGNAL_ENGINE_REFRESH_ON_MARKET_REFRESH=0 to disable Signal Engine's
    representative refresh on market updates.
    """
    try:
        from services.worker.tasks.wfo_signal_batch import enqueue_wfo_refresh_for_symbol_horizon
        from services.worker.tasks.wfo_signal_batch import enqueue_wfo_full_for_symbol_horizon
        if _SIGNAL_ENGINE_REFRESH_ON_MARKET_REFRESH:
            from services.worker.tasks.signal_engine_batch import enqueue_signal_engine_refresh_for_symbol
        from services.worker.tasks.signal_engine_batch import enqueue_signal_engine_for_symbol

        for horizon in ("short", "medium", "long"):
            for variant in ("legacy", "expanded"):
                if _SIGNAL_ENGINE_REFRESH_ON_MARKET_REFRESH:
                    enqueue_signal_engine_refresh_for_symbol(
                        symbol,
                        horizon,
                        variant=variant,
                        triggered_by="market_refresh",
                    )
                enqueue_wfo_refresh_for_symbol_horizon(
                    symbol,
                    horizon,
                    variant=variant,
                    triggered_by="market_refresh",
                )
        if db is not None and is_friday_market_refresh(now):
            for _, horizon, variant in iter_signal_engine_weekly_stale_tuples(
                db,
                symbols=[symbol],
                now=now,
            ):
                enqueue_signal_engine_for_symbol(
                    symbol,
                    horizon,
                    variant=variant,
                    triggered_by="weekly_market_refresh",
                )
            for _, horizon, variant in iter_wfo_weekly_stale_tuples(
                db,
                symbols=[symbol],
                now=now,
            ):
                enqueue_wfo_full_for_symbol_horizon(
                    symbol,
                    horizon,
                    variant=variant,
                    triggered_by="weekly_market_refresh",
                )
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Could not enqueue signal-layer refresh after market update for %s — skipping.", symbol
        )
from services.api.app.market_refresh_window import (
    BOURSE_REFRESH_CUTOFF_LABEL,
    needs_bourse_refresh,
    is_before_bourse_refresh_cutoff,
    is_bourse_source,
)

_SIGNAL_ENGINE_REFRESH_ON_MARKET_REFRESH = (
    os.getenv("SIGNAL_ENGINE_REFRESH_ON_MARKET_REFRESH", "1").strip().lower()
    not in {"0", "false", "no", "off", ""}
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
    existing_store_row = db.execute(
        text(
            """
            SELECT end_ts, data_as_of
            FROM market_data_store
            WHERE symbol = :s AND timeframe = :tf
            """
        ),
        {"s": symbol, "tf": timeframe},
    ).mappings().first()

    existing_data_as_of = None
    if existing_store_row:
        existing_data_as_of = existing_store_row["data_as_of"]
        if isinstance(existing_data_as_of, datetime.datetime):
            existing_data_as_of = existing_data_as_of.date()

    if (
        is_bourse_source(source)
        and is_before_bourse_refresh_cutoff()
        and not needs_bourse_refresh(existing_data_as_of)
    ):
        return {
            "status": "skipped_preclose_current",
            "reason": (
                "Latest completed Bourse session is already loaded. "
                f"Next intraday Bourse refresh is available after {BOURSE_REFRESH_CUTOFF_LABEL} "
                "Africa/Casablanca."
            ),
            "inserted_count": 0,
            "overwritten_overlap_count": 0,
        }

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
    fetch_start: Optional[str] = None
    if existing_store_row and existing_store_row["end_ts"]:
        # The live Bourse session scraper returns only the current/last trading day.
        # Re-fetch the last stored day so an in-flight session bar can be overwritten
        # when the exchange page updates intraday.
        last_dt: datetime.datetime = existing_store_row["end_ts"]
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
    keep_cols = [c for c in ["Open", "High", "Low", "Close", "Volume", "NombreTitres"] if c in df_new.columns]
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
        refresh_now = _utcnow()

        result = _do_refresh_symbol(db, run_id, symbol, timeframe, source)
        if result["status"] in {"created", "updated"}:
            pass
            # Enqueue lightweight signal refresh so DB-cached results stay aligned with latest close.
            _enqueue_signal_layers_after_refresh(symbol, db=db, now=refresh_now)

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
        refresh_now = _utcnow()

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
        updated_symbols = 0
        refreshed_symbols: list[str] = []
        results: dict = {}

        for symbol, track_source in symbols:
            source = source_override or track_source
            try:
                result = _do_refresh_symbol(db, run_id, symbol, timeframe, source)
                results[symbol] = result
                done += 1
                if result["status"] in {"created", "updated"}:
                    updated_symbols += 1
                    refreshed_symbols.append(symbol)
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

        if updated_symbols > 0:
            pass
            for symbol in refreshed_symbols:
                _enqueue_signal_layers_after_refresh(symbol, db=db, now=refresh_now)

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


# ---------------------------------------------------------------------------
# Moroccan index refresh (Casablanca Bourse live page)
# ---------------------------------------------------------------------------

def _upsert_market_data_store_index(
    db: Session,
    symbol: str,
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
                 source_provider, data_as_of, asset_class, created_at, updated_at)
            VALUES
                (:symbol, '1D', :object_key, :start_ts, :end_ts, :row_count,
                 :source_provider, :data_as_of, 'index', now(), now())
            ON CONFLICT (symbol, timeframe)
            DO UPDATE SET
                object_key      = excluded.object_key,
                start_ts        = excluded.start_ts,
                end_ts          = excluded.end_ts,
                row_count       = excluded.row_count,
                source_provider = excluded.source_provider,
                data_as_of      = excluded.data_as_of,
                asset_class     = excluded.asset_class,
                updated_at      = now()
        """),
        {
            "symbol": symbol,
            "object_key": object_key,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "row_count": row_count,
            "source_provider": source_provider,
            "data_as_of": data_as_of,
        },
    )
    db.commit()


def refresh_all_tracked_indices(refresh_run_id: str) -> dict:
    """
    RQ task: fetch current-session data for all active indices from the Casablanca Bourse
    indices page and merge into each index's canonical parquet store.

    One HTTP call retrieves all indices at once; each is then merged individually.
    Uses scope='indices' on the MarketRefreshRun row.
    """
    run_id = UUID(refresh_run_id)
    db: Session = SessionLocal()

    try:
        _set_run_status(db, run_id, "running", started_at=_utcnow())

        # Load active index symbols from index_master
        rows = db.execute(
            text("SELECT symbol FROM index_master WHERE is_active = true ORDER BY symbol"),
        ).mappings().all()
        symbols = [str(r["symbol"]) for r in rows]

        db.execute(
            text("UPDATE market_refresh_run SET symbols_total = :n WHERE id = :id"),
            {"n": len(symbols), "id": run_id},
        )
        db.commit()

        # Fetch all indices in a single HTTP call
        adapter = CasablancaBourseIndicesAdapter()
        fetched: dict = {}
        try:
            fetched = adapter.fetch()
        except Exception as exc:
            err_msg = f"Failed to fetch indices page: {type(exc).__name__}: {exc}"
            _set_run_status(
                db, run_id, "failed",
                finished_at=_utcnow(),
                symbols_done=0,
                symbols_failed=len(symbols),
                error_message=err_msg[:2000],
            )
            return {"refresh_run_id": refresh_run_id, "status": "failed", "error": err_msg}

        done = 0
        failed = 0
        results: dict = {}

        for symbol in symbols:
            try:
                df_new = fetched.get(symbol)
                if df_new is None or df_new.empty:
                    results[symbol] = {"status": "no_new_data", "inserted_count": 0}
                    done += 1
                    continue

                # Drop display_name column before standardizing (only needed for index_master)
                df_new = df_new.drop(columns=["display_name"], errors="ignore")

                # Synthesize open from previous close using existing history
                object_key = build_market_store_object_key(symbol, "1D")
                ensure_bucket()
                old_df = _try_load_existing_parquet(object_key)

                # Apply index standardization (synthesizes Open from prev close in the df)
                # For a single new bar, Open = prev stored close (if any) or same close
                df_std = _standardize_ohlcv_index(df_new)

                if old_df is not None and not old_df.empty:
                    # Override Open for the new bar: use last stored close
                    prev_close = float(old_df["Close"].iloc[-1])
                    df_std["Open"] = prev_close

                merged, summary = _merge_overwrite_if_different(old_df, df_std)

                if summary["status"] != "unchanged":
                    _save_parquet(object_key, merged)

                start_ts = merged.index.min().to_pydatetime()
                end_ts = merged.index.max().to_pydatetime()

                _upsert_market_data_store_index(
                    db=db,
                    symbol=symbol,
                    object_key=object_key,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    row_count=int(len(merged)),
                    source_provider="casablanca_bourse",
                    data_as_of=end_ts.date(),
                )

                results[symbol] = {
                    "status": summary["status"],
                    "inserted_count": summary["inserted_count"],
                    "overwritten_overlap_count": summary["overwritten_overlap_count"],
                    "row_count": int(len(merged)),
                }
                done += 1

            except Exception as exc:
                err_msg = f"{type(exc).__name__}: {exc}"
                results[symbol] = {"status": "error", "error": err_msg}
                failed += 1

            db.execute(
                text("UPDATE market_refresh_run SET symbols_done = :done, symbols_failed = :failed WHERE id = :id"),
                {"done": done, "failed": failed, "id": run_id},
            )
            db.commit()

        final_status = "succeeded" if failed == 0 else ("failed" if done == 0 else "partial")
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
