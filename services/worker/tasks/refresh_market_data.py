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

import pandas as pd
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
    BMCECapitalLiveAdapter,
    BoursenovaHistoryAdapter,
    BoursenovaIndicesAdapter,
    boursenova_today,
)
from core.quant_core.s3_keys import build_market_store_object_key
from core.quant_core.signal_engine.modes import ALL_SIGNAL_MODE_NAMES

# Reuse merge helper from the existing ingest task
from services.worker.tasks.ingest_market_data import (
    _compute_adv_20d_value,
    _merge_overwrite_if_different,
    _try_load_existing_parquet,
    _save_parquet,
)
from services.api.app.services.weekly_recompute_policy import (
    is_friday_market_refresh,
    iter_signal_engine_weekly_stale_tuples,
    iter_wfo_weekly_stale_tuples,
)


DASHBOARD_SNAPSHOT_JOB_TIMEOUT_SECONDS = 3600
BEST_SIGNAL_EVIDENCE_SNAPSHOT_JOB_TIMEOUT_SECONDS = 7200


def _finite_float(value) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def _positive_int(value) -> int | None:
    number = _finite_float(value)
    if number is None:
        return None
    rounded = int(round(number))
    return rounded if rounded > 0 else None


def _update_stock_share_count_from_frame(
    db: Session,
    symbol: str,
    frame,
    *,
    source: str,
) -> None:
    """Persist the latest Bourse ``NombreTitres`` value without breaking refreshes."""
    if frame is None or "NombreTitres" not in getattr(frame, "columns", []):
        return

    share_count: int | None = None
    share_as_of: datetime.date | None = None
    try:
        for ts, value in reversed(list(frame["NombreTitres"].items())):
            share_count = _positive_int(value)
            if share_count is None:
                continue
            share_as_of = ts.date() if hasattr(ts, "date") else None
            break
    except Exception:
        return

    if share_count is None:
        return

    try:
        db.execute(
            text(
                """
                UPDATE stock_master
                SET
                  shares_outstanding = :shares_outstanding,
                  shares_source = :shares_source,
                  shares_as_of = :shares_as_of,
                  shares_updated_at = now(),
                  updated_at = now()
                WHERE symbol = :symbol
                """
            ),
            {
                "symbol": symbol,
                "shares_outstanding": share_count,
                "shares_source": source,
                "shares_as_of": share_as_of,
            },
        )
        db.commit()
    except Exception:
        db.rollback()


def _enqueue_signal_layers_after_refresh(
    symbol: str,
    *,
    db: Session | None = None,
    now: datetime.datetime | None = None,
) -> list[str]:
    """Best-effort: enqueue post-refresh signal-layer jobs.

    Daily market refresh keeps the same representative sets but recomputes each
    saved representative's current signal/value for both Signal Engine and WFO.
    Set SIGNAL_ENGINE_REFRESH_ON_MARKET_REFRESH=0 to disable Signal Engine's
    representative refresh on market updates.
    """
    job_ids: list[str] = []
    try:
        from services.worker.tasks.wfo_signal_batch import enqueue_wfo_refresh_for_symbol_horizon
        from services.worker.tasks.wfo_signal_batch import enqueue_wfo_full_for_symbol_horizon
        if _SIGNAL_ENGINE_REFRESH_ON_MARKET_REFRESH:
            from services.worker.tasks.signal_engine_batch import enqueue_signal_engine_refresh_for_symbol
        from services.worker.tasks.signal_engine_batch import enqueue_signal_engine_for_symbol

        for horizon in ("weekly", "monthly", "quarterly"):
            for variant in ALL_SIGNAL_MODE_NAMES:
                if _SIGNAL_ENGINE_REFRESH_ON_MARKET_REFRESH:
                    job_id = enqueue_signal_engine_refresh_for_symbol(
                        symbol,
                        horizon,
                        variant=variant,
                        triggered_by="market_refresh",
                    )
                    if job_id:
                        job_ids.append(str(job_id))
                job_id = enqueue_wfo_refresh_for_symbol_horizon(
                    symbol,
                    horizon,
                    variant=variant,
                    triggered_by="market_refresh",
                )
                if job_id:
                    job_ids.append(str(job_id))
        if db is not None and is_friday_market_refresh(now):
            for _, horizon, variant in iter_signal_engine_weekly_stale_tuples(
                db,
                symbols=[symbol],
                now=now,
            ):
                job_id = enqueue_signal_engine_for_symbol(
                    symbol,
                    horizon,
                    variant=variant,
                    triggered_by="weekly_market_refresh",
                )
                if job_id:
                    job_ids.append(str(job_id))
            for _, horizon, variant in iter_wfo_weekly_stale_tuples(
                db,
                symbols=[symbol],
                now=now,
            ):
                job_id = enqueue_wfo_full_for_symbol_horizon(
                    symbol,
                    horizon,
                    variant=variant,
                    triggered_by="weekly_market_refresh",
                )
                if job_id:
                    job_ids.append(str(job_id))
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Could not enqueue signal-layer refresh after market update for %s — skipping.", symbol
        )
    return job_ids


def _market_refresh_queue():
    from rq import Queue

    from services.worker.redis_utils import connect_redis_with_fallback

    redis = connect_redis_with_fallback(settings.REDIS_URL, decode_responses=False)
    return Queue(settings.MARKET_REFRESH_QUEUE_NAME, connection=redis)


def _signal_backtest_queue():
    from rq import Queue

    from services.worker.redis_utils import connect_redis_with_fallback

    redis = connect_redis_with_fallback(settings.REDIS_URL, decode_responses=False)
    return Queue(settings.SIGNAL_BACKTEST_QUEUE_NAME, connection=redis)


def _dashboard_snapshot_dependency(job_ids: list[str]):
    from rq.job import Dependency

    return Dependency(job_ids, allow_failure=True)


def _enqueue_dashboard_snapshot_after_signal_jobs(
    signal_job_ids: list[str],
    *,
    symbols: list[str],
    triggered_by: str,
) -> str | None:
    """Queue a dashboard snapshot after post-refresh signal jobs settle."""
    unique_job_ids = list(dict.fromkeys(str(job_id) for job_id in signal_job_ids if str(job_id).strip()))
    try:
        dependency = _dashboard_snapshot_dependency(unique_job_ids) if unique_job_ids else None
        job = _market_refresh_queue().enqueue(
            "services.worker.tasks.dashboard_snapshot.refresh_dashboard_snapshot",
            None,
            job_timeout=DASHBOARD_SNAPSHOT_JOB_TIMEOUT_SECONDS,
            depends_on=dependency,
            meta={
                "triggered_by": triggered_by,
                "updated_symbols_count": len(symbols),
                "updated_symbols_sample": symbols[:20],
                "signal_dependency_count": len(unique_job_ids),
            },
        )
        return str(job.id)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Could not enqueue dashboard snapshot after market refresh signal jobs.",
            exc_info=True,
        )
        return None


def _enqueue_best_evidence_snapshot_after_signal_jobs(
    signal_job_ids: list[str],
    *,
    symbols: list[str],
    triggered_by: str,
) -> str | None:
    unique_job_ids = list(dict.fromkeys(str(job_id) for job_id in signal_job_ids if str(job_id).strip()))
    try:
        dependency = _dashboard_snapshot_dependency(unique_job_ids) if unique_job_ids else None
        job = _signal_backtest_queue().enqueue(
            "services.worker.tasks.signal_best_evidence_snapshot.refresh_signal_best_evidence_snapshot",
            symbols[0] if len(symbols) == 1 else None,
            None,
            0,
            job_timeout=BEST_SIGNAL_EVIDENCE_SNAPSHOT_JOB_TIMEOUT_SECONDS,
            depends_on=dependency,
            meta={
                "triggered_by": triggered_by,
                "updated_symbols_count": len(symbols),
                "updated_symbols_sample": symbols[:20],
                "signal_dependency_count": len(unique_job_ids),
            },
        )
        return str(job.id)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Could not enqueue best signal evidence snapshot after market refresh signal jobs.",
            exc_info=True,
        )
        return None


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
    close_last: float | None = None,
    prev_close: float | None = None,
    adv_20d: float | None = None,
) -> None:
    params = {
        "symbol": symbol,
        "timeframe": timeframe,
        "object_key": object_key,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "row_count": row_count,
        "source_provider": source_provider,
        "data_as_of": data_as_of,
        "close_last": close_last,
        "prev_close": prev_close,
        "adv_20d": adv_20d,
    }
    try:
        db.execute(
            text("""
            INSERT INTO market_data_store
                (symbol, timeframe, object_key, start_ts, end_ts, row_count,
                 source_provider, data_as_of, close_last, prev_close, adv_20d,
                 created_at, updated_at)
            VALUES
                (:symbol, :timeframe, :object_key, :start_ts, :end_ts, :row_count,
                 :source_provider, :data_as_of, :close_last, :prev_close, :adv_20d,
                 now(), now())
            ON CONFLICT (symbol, timeframe)
            DO UPDATE SET
                object_key      = excluded.object_key,
                start_ts        = excluded.start_ts,
                end_ts          = excluded.end_ts,
                row_count       = excluded.row_count,
                source_provider = excluded.source_provider,
                data_as_of      = excluded.data_as_of,
                close_last      = excluded.close_last,
                prev_close      = excluded.prev_close,
                adv_20d         = excluded.adv_20d,
                updated_at      = now()
            """),
            params,
        )
    except Exception as exc:
        if "close_last" not in str(exc) and "adv_20d" not in str(exc):
            raise
        db.rollback()
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
            params,
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


def _update_stock_metadata_from_bourse(db: Session, symbol: str, display_name: str | None) -> None:
    """Best-effort: fill an empty stock_master.display_name from the exchange label.

    ISIN/sector are not exposed by the boursenova history API; share counts are
    persisted separately from the same response (NombreTitres). Never raises.
    """
    name = (display_name or "").strip()
    if not name:
        return
    try:
        db.execute(
            text(
                """
                UPDATE stock_master
                SET display_name = COALESCE(NULLIF(display_name, ''), :display_name),
                    updated_at = now()
                WHERE symbol = :symbol
                """
            ),
            {"symbol": symbol, "display_name": name},
        )
        db.commit()
    except Exception:
        db.rollback()


def refresh_lookback_days() -> int:
    """Calendar days re-fetched on every refresh so holes and late corrections self-heal."""
    try:
        return max(1, int(os.getenv("REFRESH_LOOKBACK_DAYS", "45")))
    except ValueError:
        return 45


_CALENDAR_CACHE: dict = {}


def exchange_session_dates(start: datetime.date, *, today: datetime.date | None = None) -> set[datetime.date]:
    """Casablanca session dates since ``start`` = the MASI index's ``seance`` dates.

    Cached per (today, start) so a full refresh pays one request. Empty set if unavailable.
    """
    today = today or boursenova_today()
    key = (today, start)
    if key not in _CALENDAR_CACHE:
        try:
            frame = BoursenovaIndicesAdapter().fetch(["MASI"], start=start, end=today).get("MASI")
            dates = {ts.date() for ts in frame.index} if frame is not None else set()
        except Exception:
            dates = set()
        if dates:
            _CALENDAR_CACHE.clear()
            _CALENDAR_CACHE[key] = dates
        return dates
    return _CALENDAR_CACHE[key]


def missing_sessions(
    stored_dates: set[datetime.date],
    calendar: set[datetime.date],
    *,
    window_start: datetime.date,
    window_end: datetime.date,
) -> list[datetime.date]:
    """Calendar sessions in [window_start, window_end] absent from the store, never
    before the first stored bar (pre-history is not a hole)."""
    if not stored_dates:
        return []
    lo = max(window_start, min(stored_dates))
    return sorted(d for d in calendar if lo <= d <= window_end and d not in stored_dates)


def _align_tz(frame: pd.DataFrame, like: pd.DataFrame | None) -> pd.DataFrame:
    """Give ``frame`` the same tz-awareness as ``like`` so the two index sets compare."""
    if like is None or like.empty or frame.empty:
        return frame
    tz = like.index.tz
    out = frame.copy()
    if tz is None and out.index.tz is not None:
        out.index = out.index.tz_localize(None)
    elif tz is not None:
        out.index = out.index.tz_localize(tz) if out.index.tz is None else out.index.tz_convert(tz)
    return out


def synthesize_index_open(old: pd.DataFrame | None, incoming: pd.DataFrame) -> pd.DataFrame:
    """Open = previous session's close within the merged (old + incoming) series.

    Incoming closes win on shared dates; the first bar overall falls back to its own close.
    """
    incoming = _align_tz(incoming, old)
    closes = incoming["Close"]
    if old is not None and not old.empty:
        closes = pd.concat([old["Close"], closes])
    closes = closes[~closes.index.duplicated(keep="last")].sort_index()
    out = incoming.copy()
    out["Open"] = closes.shift(1).reindex(out.index).fillna(out["Close"])
    return out


def _persist_stock_frame(
    db: Session,
    symbol: str,
    timeframe: str,
    object_key: str,
    merged: pd.DataFrame,
    source: str,
) -> dict:
    """Write the merged stock frame's store row (close_last/prev_close/adv_20d consistent)."""
    start_ts = merged.index.min().to_pydatetime()
    end_ts = merged.index.max().to_pydatetime()
    close_last = _finite_float(merged["Close"].iloc[-1]) if "Close" in merged.columns and len(merged) >= 1 else None
    prev_close = _finite_float(merged["Close"].iloc[-2]) if "Close" in merged.columns and len(merged) >= 2 else None
    _upsert_market_data_store(
        db=db,
        symbol=symbol,
        timeframe=timeframe,
        object_key=object_key,
        start_ts=start_ts,
        end_ts=end_ts,
        row_count=int(len(merged)),
        source_provider=source,
        data_as_of=end_ts.date(),
        close_last=close_last,
        prev_close=prev_close,
        adv_20d=_compute_adv_20d_value(merged),
    )
    return {
        "object_key": object_key,
        "start_ts": start_ts.isoformat(),
        "end_ts": end_ts.isoformat(),
        "row_count": int(len(merged)),
    }


def _has_recent_hole(object_key: str, today: datetime.date, *, before_cutoff: bool) -> bool:
    """True when the stored series misses an exchange session inside the lookback window."""
    window_start = today - datetime.timedelta(days=refresh_lookback_days())
    calendar = exchange_session_dates(window_start, today=today)
    if not calendar:
        return False
    old_df = _try_load_existing_parquet(object_key)
    if old_df is None or old_df.empty:
        return True
    stored = {ts.date() for ts in old_df.index}
    window_end = today - datetime.timedelta(days=1) if before_cutoff else today
    return bool(missing_sessions(stored, calendar, window_start=window_start, window_end=window_end))


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

    provider_symbol = _resolve_provider_symbol(db, symbol, source)
    object_key = build_market_store_object_key(symbol, timeframe)

    if (
        is_bourse_source(source)
        and is_before_bourse_refresh_cutoff()
        and not needs_bourse_refresh(existing_data_as_of)
        and not _has_recent_hole(object_key, boursenova_today(), before_cutoff=True)
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

    # Pick adapter. Every Moroccan equity source (bourse_direct, bmce_excel, ...)
    # reads the boursenova history API; fallbacks only run if it returns nothing.
    fallbacks: list = []
    is_boursenova = source != "yahoo"
    if source == "yahoo":
        adapter = YFinanceMoroccoAdapter(timezone="UTC", use_cache=False)
        # Pass the provider_symbol directly via map so YFinanceMoroccoAdapter uses it
        adapter.provider_map = {symbol: provider_symbol}
    else:
        adapter = BoursenovaHistoryAdapter(timezone="UTC", use_cache=False)
        if source != "bmce_excel" and os.environ.get("BOURSE_DIRECT_URL_TEMPLATE", "").strip():
            fallbacks.append(BourseDirectAdapter(timezone="UTC", use_cache=False))
        if BMCECapitalLiveAdapter.listing_id_for(symbol) is not None:
            fallbacks.append(BMCECapitalLiveAdapter(timezone="UTC", use_cache=False))

    # Fetch start. Yahoo keeps the incremental tail fetch. Exchange sources re-fetch
    # a rolling lookback window ending today so interior holes and late corrections
    # self-heal (the merge inserts missing dates and overwrites differing ones).
    fetch_start: Optional[str] = None
    if existing_store_row and existing_store_row["end_ts"]:
        last_dt: datetime.datetime = existing_store_row["end_ts"]
        if is_boursenova:
            anchor = min(last_dt.date(), boursenova_today())
            fetch_start = (anchor - datetime.timedelta(days=refresh_lookback_days())).isoformat()
        else:
            fetch_start = (last_dt + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    market_data = adapter.load(symbols=[symbol], start=fetch_start, end=None, interval="1d")
    df_new = market_data.bars.get(symbol)
    if (df_new is None or df_new.empty) and is_boursenova:
        for fallback in fallbacks:
            try:
                df_new = fallback.load(symbols=[symbol], start=fetch_start, end=None, interval="1d").bars.get(symbol)
            except Exception:
                df_new = None
            if df_new is not None and not df_new.empty:
                break
    if df_new is None or df_new.empty:
        return {"status": "no_new_data", "inserted_count": 0, "overwritten_overlap_count": 0}

    if is_boursenova:
        _update_stock_metadata_from_bourse(
            db, symbol, (getattr(adapter, "meta", {}).get(symbol) or {}).get("display_name")
        )

    # Validate
    df_new = _validate_ohlcv(df_new, symbol=symbol)
    if df_new.empty:
        return {"status": "invalid_data", "inserted_count": 0, "overwritten_overlap_count": 0}

    # Keep only canonical columns
    keep_cols = [c for c in ["Open", "High", "Low", "Close", "Volume", "NombreTitres"] if c in df_new.columns]
    df_new = df_new[keep_cols]

    # Load existing parquet and merge
    ensure_bucket()
    old_df = _try_load_existing_parquet(object_key)
    merged, summary = _merge_overwrite_if_different(old_df, _align_tz(df_new, old_df))

    if summary["status"] != "unchanged":
        _save_parquet(object_key, merged)

    persisted = _persist_stock_frame(db, symbol, timeframe, object_key, merged, source)
    _update_stock_share_count_from_frame(db, symbol, df_new, source=source)

    return {
        "status": summary["status"],
        "inserted_count": summary["inserted_count"],
        "overwritten_overlap_count": summary["overwritten_overlap_count"],
        **persisted,
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
        dashboard_snapshot_job_id: str | None = None
        best_evidence_snapshot_job_id: str | None = None
        if result["status"] in {"created", "updated"}:
            # Enqueue lightweight signal refresh so DB-cached results stay aligned with latest close.
            signal_job_ids = _enqueue_signal_layers_after_refresh(symbol, db=db, now=refresh_now)
            dashboard_snapshot_job_id = _enqueue_dashboard_snapshot_after_signal_jobs(
                signal_job_ids,
                symbols=[symbol],
                triggered_by="market_refresh_single",
            )
            best_evidence_snapshot_job_id = _enqueue_best_evidence_snapshot_after_signal_jobs(
                signal_job_ids,
                symbols=[symbol],
                triggered_by="market_refresh_single",
            )

        _set_run_status(
            db, run_id, "succeeded",
            finished_at=_utcnow(),
            symbols_done=1,
            symbols_failed=0,
        )
        payload = {"refresh_run_id": refresh_run_id, "symbol": symbol, **result}
        if dashboard_snapshot_job_id:
            payload["dashboard_snapshot_job_id"] = dashboard_snapshot_job_id
        if best_evidence_snapshot_job_id:
            payload["best_evidence_snapshot_job_id"] = best_evidence_snapshot_job_id
        return payload

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

        dashboard_snapshot_job_id: str | None = None
        best_evidence_snapshot_job_id: str | None = None
        signal_job_ids: list[str] = []
        if updated_symbols > 0:
            for symbol in refreshed_symbols:
                signal_job_ids.extend(_enqueue_signal_layers_after_refresh(symbol, db=db, now=refresh_now))
            dashboard_snapshot_job_id = _enqueue_dashboard_snapshot_after_signal_jobs(
                signal_job_ids,
                symbols=refreshed_symbols,
                triggered_by="market_refresh_all",
            )
            best_evidence_snapshot_job_id = _enqueue_best_evidence_snapshot_after_signal_jobs(
                signal_job_ids,
                symbols=refreshed_symbols,
                triggered_by="market_refresh_all",
            )

        _set_run_status(
            db, run_id, final_status,
            finished_at=_utcnow(),
            symbols_done=done,
            symbols_failed=failed,
        )
        payload = {
            "refresh_run_id": refresh_run_id,
            "status": final_status,
            "symbols_done": done,
            "symbols_failed": failed,
            "results": results,
        }
        if dashboard_snapshot_job_id:
            payload["dashboard_snapshot_job_id"] = dashboard_snapshot_job_id
        if best_evidence_snapshot_job_id:
            payload["best_evidence_snapshot_job_id"] = best_evidence_snapshot_job_id
        return payload

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
# Moroccan index refresh (Casablanca Bourse boursenova API)
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
    RQ task: fetch the last REFRESH_LOOKBACK_DAYS of history for all active indices from
    the Casablanca Bourse boursenova API and merge into each index's canonical parquet store.

    One request per index; each is merged individually. Indices without a boursenova
    code (e.g. FTSE CSE Morocco) are reported as no_new_data.
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

        # Fetch every mapped index over the rolling lookback window (one request per index)
        adapter = BoursenovaIndicesAdapter()
        fetched: dict = {}
        try:
            today = boursenova_today()
            fetched = adapter.fetch(
                symbols, start=today - datetime.timedelta(days=refresh_lookback_days()), end=today
            )
        except Exception as exc:
            err_msg = f"Failed to fetch indices: {type(exc).__name__}: {exc}"
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

                object_key = build_market_store_object_key(symbol, "1D")
                ensure_bucket()
                old_df = _try_load_existing_parquet(object_key)

                # Open = previous close within the merged series (per bar, not one scalar)
                df_std = synthesize_index_open(old_df, _standardize_ohlcv_index(df_new))
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
