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
    BMCECapitalLiveAdapter,
    CasablancaBourseIndicesAdapter,
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


def _parse_bourse_french_number(value: str) -> float | None:
    normalized = (
        str(value or "")
        .replace("\u00a0", "")
        .replace(" ", "")
        .replace(",", ".")
        .strip()
    )
    return _finite_float(normalized)


def _parse_bourse_session_date(html: str) -> datetime.date | None:
    import re

    date_m = re.search(
        r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"
        r"\s+(\d{1,2})\s+"
        r"(janvier|f[e\u00e9]vrier|mars|avril|mai|juin|juillet|ao[u\u00fb]t"
        r"|septembre|octobre|novembre|d[e\u00e9]cembre)\s+(\d{4})",
        html,
        re.IGNORECASE,
    )
    if not date_m:
        return None
    month = BDCSessionAdapter._MONTH_MAP.get(date_m.group(2).lower())
    if month is None:
        return None
    return datetime.date(int(date_m.group(3)), month, int(date_m.group(1)))


def _parse_bourse_share_count(html: str) -> int | None:
    import re

    match = re.search(
        r"<th[^>]*>\s*Nombre de titres[^<]*</th>\s*<td[^>]*>.*?"
        r"<span\s+dir=[\"']ltr[\"']>([^<]+)</span>",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None
    return _positive_int(_parse_bourse_french_number(match.group(1)))


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


def _update_stock_metadata_from_bourse(db: Session, symbol: str, provider_symbol: str) -> None:
    """Best-effort enrichment from the live Bourse instrument page."""
    import html as _html
    import re as _re

    try:
        import requests
    except ImportError:
        return

    try:
        url = f"https://www.casablanca-bourse.com/fr/live-market/instruments/{provider_symbol}?pwa=1"
        resp = requests.get(
            url,
            timeout=10,
            verify=False,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
        )
        if resp.status_code != 200:
            return
        html = resp.text
        isin_match = _re.search(r"\b(MA[A-Z0-9]{10})\b", html)
        sector_match = _re.search(
            r"<th[^>]*>\s*Secteur\s*</th>\s*<td[^>]*>(?:<[^>]+>)*([^<]+)",
            html,
            _re.IGNORECASE | _re.DOTALL,
        )
        name_match = _re.search(
            rf'href=["\']/fr/live-market/instruments/{_re.escape(provider_symbol)}\?pwa[^"\']*["\'][^>]*>([^<]+)<',
            html,
            _re.IGNORECASE,
        )
        isin = isin_match.group(1) if isin_match else None
        sector = _html.unescape(sector_match.group(1)).strip() if sector_match else None
        display_name = _html.unescape(name_match.group(1)).strip() if name_match else None
        share_count = _parse_bourse_share_count(html)
        share_as_of = _parse_bourse_session_date(html)

        db.execute(
            text(
                """
                UPDATE stock_master
                SET
                  isin = COALESCE(NULLIF(isin, ''), :isin),
                  sector = COALESCE(NULLIF(sector, ''), :sector),
                  display_name = COALESCE(NULLIF(display_name, ''), :display_name),
                  bourse_url = COALESCE(NULLIF(bourse_url, ''), :bourse_url),
                  shares_outstanding = CASE
                    WHEN :shares_outstanding IS NOT NULL THEN :shares_outstanding
                    ELSE shares_outstanding
                  END,
                  shares_source = CASE
                    WHEN :shares_outstanding IS NOT NULL THEN :shares_source
                    ELSE shares_source
                  END,
                  shares_as_of = CASE
                    WHEN :shares_outstanding IS NOT NULL THEN :shares_as_of
                    ELSE shares_as_of
                  END,
                  shares_updated_at = CASE
                    WHEN :shares_outstanding IS NOT NULL THEN now()
                    ELSE shares_updated_at
                  END,
                  updated_at = now()
                WHERE symbol = :symbol
                """
            ),
            {
                "symbol": symbol,
                "isin": isin,
                "sector": sector,
                "display_name": display_name if display_name and display_name.upper() != provider_symbol else None,
                "bourse_url": url,
                "shares_outstanding": share_count,
                "shares_source": "bourse_direct",
                "shares_as_of": share_as_of,
            },
        )
        db.commit()
    except Exception:
        db.rollback()


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
    if is_bourse_source(source):
        _update_stock_metadata_from_bourse(db, symbol, provider_symbol)

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

    # Pick adapter
    use_session_adapter = False
    if source == "yahoo":
        adapter = YFinanceMoroccoAdapter(timezone="UTC", use_cache=False)
        # Pass the provider_symbol directly via map so YFinanceMoroccoAdapter uses it
        adapter.provider_map = {symbol: provider_symbol}
    elif source == "bmce_excel":
        # "bmce_excel" tracked symbols have no automated Casablanca Bourse
        # scrape path (that source name was originally only used for manual
        # BMCEDataSource Excel/CSV uploads). Use the BMCE Capital Bourse
        # live-market details page instead — a separate host from
        # casablanca-bourse.com, useful as an automated source in its own
        # right and as a fallback when the exchange site is unreachable.
        adapter = BMCECapitalLiveAdapter(timezone="UTC", use_cache=False)
        use_session_adapter = True
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
    close_last = _finite_float(merged["Close"].iloc[-1]) if "Close" in merged.columns and len(merged) >= 1 else None
    prev_close = _finite_float(merged["Close"].iloc[-2]) if "Close" in merged.columns and len(merged) >= 2 else None
    adv_20d = _compute_adv_20d_value(merged)

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
        close_last=close_last,
        prev_close=prev_close,
        adv_20d=adv_20d,
    )
    _update_stock_share_count_from_frame(db, symbol, df_new, source=source)

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
