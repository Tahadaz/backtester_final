"""Worker task: ingest macro factor series from yfinance.

Entry point called by RQ:
    ingest_macro_series(canonical_id, start, end)

Persists to:
    market_data_store with asset_class='factor'
    market_data/symbols/{canonical_id}/ohlcv.parquet
"""
from __future__ import annotations

import json
from io import BytesIO
from typing import Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.quant_core.macro import MACRO_SERIES_BY_ID, MacroSeriesSpec, fetch_macro_series
from core.quant_core.s3_keys import build_market_store_object_key
from services.worker.config import settings
from services.worker.db import SessionLocal
from services.worker.storage import s3_client, ensure_bucket


def _try_load_existing_parquet(object_key: str) -> pd.DataFrame | None:
    s3 = s3_client()
    try:
        obj = s3.get_object(Bucket=settings.S3_BUCKET, Key=object_key)
    except Exception:
        return None
    b = obj["Body"].read()
    if not b:
        return None
    return pd.read_parquet(BytesIO(b))


def _save_parquet(object_key: str, df: pd.DataFrame) -> None:
    ensure_bucket()
    buf = BytesIO()
    df.to_parquet(buf, index=True)
    buf.seek(0)
    s3 = s3_client()
    s3.put_object(
        Bucket=settings.S3_BUCKET,
        Key=object_key,
        Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )


def _merge(old: pd.DataFrame | None, incoming: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Merge incoming OHLCV into existing parquet with overwrite-if-different semantics."""
    if old is None or old.empty:
        return incoming, {"inserted": len(incoming), "updated": 0, "status": "created"}

    # Align to common index type
    for df in [old, incoming]:
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

    overlap = old.index.intersection(incoming.index)
    new_idx = incoming.index.difference(old.index)

    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in old.columns and c in incoming.columns]

    updated = 0
    if len(overlap) > 0:
        old_sl = old.loc[overlap, cols].fillna("__NA__")
        inc_sl = incoming.loc[overlap, cols].fillna("__NA__")
        diff_mask = (old_sl != inc_sl).any(axis=1)
        updated = int(diff_mask.sum())
        old.loc[overlap[diff_mask], cols] = incoming.loc[overlap[diff_mask], cols]

    if len(new_idx) > 0:
        old = pd.concat([old, incoming.loc[new_idx]])

    old = old.sort_index()
    inserted = len(new_idx)
    status = "unchanged" if inserted == 0 and updated == 0 else "updated"
    return old, {"inserted": inserted, "updated": updated, "status": status}


def _upsert_market_data_store(
    db: Session,
    canonical_id: str,
    object_key: str,
    df: pd.DataFrame,
) -> None:
    """Upsert market_data_store row for a factor series."""
    end_ts = df.index.max()
    start_ts = df.index.min()
    data_as_of = end_ts.date() if hasattr(end_ts, "date") else None
    row_count = len(df)

    db.execute(
        text("""
            INSERT INTO market_data_store
                (symbol, timeframe, object_key, start_ts, end_ts, row_count,
                 source_provider, data_as_of, asset_class, updated_at, created_at)
            VALUES
                (:sym, '1D', :key, :start_ts, :end_ts, :row_count,
                 'yahoo', :data_as_of, 'factor', NOW(), NOW())
            ON CONFLICT (symbol, timeframe) DO UPDATE SET
                object_key   = EXCLUDED.object_key,
                end_ts       = EXCLUDED.end_ts,
                start_ts     = EXCLUDED.start_ts,
                row_count    = EXCLUDED.row_count,
                data_as_of   = EXCLUDED.data_as_of,
                source_provider = EXCLUDED.source_provider,
                asset_class  = 'factor',
                updated_at   = NOW()
        """),
        {
            "sym": canonical_id,
            "key": object_key,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "row_count": row_count,
            "data_as_of": data_as_of,
        },
    )
    db.commit()


def ingest_macro_series(
    canonical_id: str,
    start: str = "2010-01-01",
    end: Optional[str] = None,
) -> dict:
    """RQ worker task: fetch macro series from yfinance and persist to S3 + DB.

    Args:
        canonical_id: one of VIX, SP500, BRENT, DXY, EURUSD, US10Y
        start: ISO date string for history start (default 2010-01-01)
        end: ISO date string for end (None = today)

    Returns:
        dict with status, rows inserted/updated, object_key
    """
    spec = MACRO_SERIES_BY_ID.get(canonical_id)
    if spec is None:
        raise ValueError(f"Unknown macro series canonical_id: {canonical_id!r}. "
                         f"Known: {list(MACRO_SERIES_BY_ID.keys())}")

    # Fetch from yfinance
    df = fetch_macro_series(spec, start=start, end=end)

    object_key = build_market_store_object_key(canonical_id, "1D")

    existing = _try_load_existing_parquet(object_key)
    merged, merge_summary = _merge(existing, df)

    _save_parquet(object_key, merged)

    db = SessionLocal()
    try:
        _upsert_market_data_store(db, canonical_id, object_key, merged)
    finally:
        db.close()

    return {
        "canonical_id": canonical_id,
        "yahoo_symbol": spec.symbol,
        "object_key": object_key,
        "rows_fetched": len(df),
        "rows_total": len(merged),
        **merge_summary,
    }


def ingest_all_macro_series(
    start: str = "2010-01-01",
    end: Optional[str] = None,
    canonical_ids: Optional[list[str]] = None,
) -> dict:
    """Ingest all (or a subset of) macro series.

    Args:
        canonical_ids: list of canonical IDs to ingest (None = all six)

    Returns:
        dict[canonical_id -> result_or_error]
    """
    from core.quant_core.macro import MACRO_SERIES

    ids = canonical_ids or [s.canonical_id for s in MACRO_SERIES]
    results = {}
    for cid in ids:
        try:
            results[cid] = ingest_macro_series(cid, start=start, end=end)
        except Exception as exc:
            results[cid] = {"error": str(exc)}
    return results
