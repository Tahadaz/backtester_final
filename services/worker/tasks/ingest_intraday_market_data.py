"""
ingest_intraday_market_data.py — MANUAL / on-demand intraday OHLCV backfill for
Casablanca/MASI equities via TradingView (unofficial `tvdatafeed` scraper).

*** IMPORTANT ***
tvdatafeed (https://github.com/rongardF/tvdatafeed) is an UNOFFICIAL TradingView
scraper. There is no official API and no ToS sanction for this usage. This
module is therefore intentionally NOT wired into
services/worker/tasks/scheduler_dispatch.py or any cron/Celery-beat config.
It is a manual/on-demand ingestion path only — invoke the functions below
directly (e.g. from a one-off script or a REPL) when you need fresh intraday
bars. Do not add automatic scheduling for this without a ToS review.

Object storage note: existing daily ("1D") OHLCV parquet objects are keyed by
core.quant_core.s3_keys.build_market_store_object_key(symbol, timeframe), which
today ignores the `timeframe` argument entirely and always resolves to
`market_data/symbols/{symbol}/ohlcv.parquet`. Reusing that helper for a "1H"
timeframe would silently collide with (and corrupt) the existing daily parquet
object. To avoid that, this module builds its own timeframe-qualified object
key (see `_intraday_object_key` below) instead of reusing
build_market_store_object_key for non-daily timeframes.
"""

from __future__ import annotations

import datetime
import time
from typing import List

from sqlalchemy.orm import Session

from services.worker.db import SessionLocal
from services.worker.storage import ensure_bucket

from core.quant_core.data import _validate_ohlcv
from core.quant_core.tv_intraday_adapter import TradingViewIntradayAdapter

from services.worker.tasks.ingest_market_data import (
    _compute_adv_20d_value,
    _merge_overwrite_if_different,
    _try_load_existing_parquet,
    _save_parquet,
)
from services.worker.tasks.refresh_market_data import _upsert_market_data_store, _finite_float


def _intraday_object_key(symbol: str, timeframe: str) -> str:
    """Timeframe-qualified S3 key for intraday OHLCV parquet.

    Deliberately distinct from build_market_store_object_key(), which is not
    timeframe-aware and would otherwise collide with the daily ("1D") object
    for the same symbol.
    """
    suffix = timeframe.strip().lower() or "1h"
    return f"market_data/symbols/{symbol}/ohlcv_{suffix}.parquet"


def refresh_symbol_intraday(
    db: Session,
    symbol: str,
    timeframe: str = "1H",
    n_bars: int = 5000,
    source_provider: str = "tradingview",
) -> dict:
    """Fetch, merge, and persist intraday OHLCV for one symbol via TradingView.

    Mirrors refresh_market_data.py's _do_refresh_symbol tail: load via adapter
    -> validate -> merge with existing parquet -> save parquet -> upsert
    market_data_store row. Returns a small status dict.
    """
    try:
        adapter = TradingViewIntradayAdapter()
        market_data = adapter.load(symbols=[symbol], interval="1h", n_bars=n_bars)
    except Exception as exc:
        return {
            "symbol": symbol,
            "status": "error",
            "error": repr(exc),
            "row_count": 0,
            "start_ts": None,
            "end_ts": None,
        }

    df_new = market_data.bars.get(symbol)
    if df_new is None or df_new.empty:
        return {
            "symbol": symbol,
            "status": "no_data",
            "row_count": 0,
            "start_ts": None,
            "end_ts": None,
        }

    df_new = _validate_ohlcv(df_new, symbol=symbol)
    if df_new.empty:
        return {
            "symbol": symbol,
            "status": "invalid_data",
            "row_count": 0,
            "start_ts": None,
            "end_ts": None,
        }

    keep_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df_new.columns]
    df_new = df_new[keep_cols]

    object_key = _intraday_object_key(symbol, timeframe)
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
        source_provider=source_provider,
        data_as_of=data_as_of,
        close_last=close_last,
        prev_close=prev_close,
        adv_20d=adv_20d,
    )

    return {
        "symbol": symbol,
        "status": summary["status"],
        "row_count": int(len(merged)),
        "start_ts": start_ts.isoformat(),
        "end_ts": end_ts.isoformat(),
        "object_key": object_key,
    }


def run_intraday_backfill(
    symbols: List[str],
    timeframe: str = "1H",
    n_bars: int = 5000,
) -> List[dict]:
    """Manual/on-demand batch backfill entry point. Loops refresh_symbol_intraday
    over `symbols`, opening its own DB session, with a short polite delay
    between symbols. Prints a summary table and returns the list of per-symbol
    result dicts.
    """
    results: List[dict] = []
    db = SessionLocal()
    try:
        for i, symbol in enumerate(symbols):
            print(f"[intraday backfill] fetching {symbol} ({i + 1}/{len(symbols)}) ...")
            result = refresh_symbol_intraday(db, symbol, timeframe=timeframe, n_bars=n_bars)
            results.append(result)
            print(f"[intraday backfill] {symbol} -> {result}")
            if i < len(symbols) - 1:
                time.sleep(1.5)
    finally:
        db.close()

    print("\n=== Intraday backfill summary ===")
    print(f"{'symbol':8s} {'status':14s} {'rows':>6s}  {'start_ts':25s} {'end_ts':25s}")
    for r in results:
        print(
            f"{r['symbol']:8s} {r['status']:14s} {r['row_count']:6d}  "
            f"{str(r.get('start_ts')):25s} {str(r.get('end_ts')):25s}"
        )

    return results


if __name__ == "__main__":
    run_intraday_backfill(["ATW", "IAM", "BCP", "BOA", "ADH"], timeframe="1H")
