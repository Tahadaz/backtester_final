from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

import pandas as pd

from services.worker.db import SessionLocal
from core.quant_core.data import (
    BOURSENOVA_APP_SYMBOL_TO_CODE,
    BoursenovaIndicesAdapter,
    _standardize_ohlcv_index,
)
from services.worker.tasks.ingest_market_data import (
    _drop_future_dated_rows,
    _merge_overwrite_if_different,
    _save_parquet,
    _try_load_existing_parquet,
    _upsert_index_master,
    _upsert_market_data_store_index,
)
from services.worker.tasks.refresh_market_data import synthesize_index_open
from core.quant_core.s3_keys import build_market_store_object_key

logger = logging.getLogger(__name__)

# Index symbols this ingester creates/refreshes by default (index_master.symbol).
# Symbol -> boursenova code lives in core.quant_core.data.BOURSENOVA_APP_SYMBOL_TO_CODE;
# FTSE_CSE_MOROCCO_15 / _ALL_LIQUID have no boursenova code and are skipped.
CASABLANCA_INDEX_SYMBOLS: tuple[str, ...] = (
    "MASI",
    "MASI_20",
    "MASI_ESG",
    "FTSE_CSE_MOROCCO_15",
    "FTSE_CSE_MOROCCO_ALL_LIQUID",
    "MASI_USD",
    "MASI_EUR",
    "MASI_RENTABILITE_BRUT",
    "MASI_RENTABILITE_NET",
    "MASI_MID_AND_SMALL_CAP",
)

SOURCE_PROVIDER = "casablanca_bourse_api"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def fetch_index_history(symbol: str, adapter: BoursenovaIndicesAdapter | None = None) -> pd.DataFrame:
    """Full ~3-year daily history of one index from the boursenova API.

    Returns a DataFrame indexed by session date (ascending, deduped) with Close/High/Low
    and ``display_name``; empty if the symbol has no boursenova code or the API fails.
    """
    adapter = adapter or BoursenovaIndicesAdapter()
    return adapter.fetch([symbol]).get(symbol, pd.DataFrame())


def ingest_one(db, symbol: str, display_name: str, df: pd.DataFrame, dataset_id) -> dict:
    if df.empty:
        return {
            "display_name": display_name,
            "status": "error",
            "error": "empty_after_fetch",
        }

    object_key = build_market_store_object_key(symbol, "1D")
    old = _try_load_existing_parquet(object_key)

    df_std = _standardize_ohlcv_index(df.drop(columns=["display_name"], errors="ignore"))
    df_std = synthesize_index_open(old, df_std)
    df_std = _drop_future_dated_rows(df_std)

    if df_std.empty:
        return {
            "display_name": display_name,
            "status": "error",
            "error": "empty_after_standardization",
        }

    merged, summary = _merge_overwrite_if_different(old, df_std)

    if summary["status"] != "unchanged":
        _save_parquet(object_key, merged)

    start_ts = merged.index.min().to_pydatetime()
    end_ts = merged.index.max().to_pydatetime()

    _upsert_index_master(db, symbol, display_name)
    _upsert_market_data_store_index(
        db, symbol, object_key, start_ts, end_ts, int(len(merged)), dataset_id,
        source_provider=SOURCE_PROVIDER,
    )

    return {
        "display_name": display_name,
        "status": summary["status"],
        "inserted_count": summary["inserted_count"],
        "overwritten_overlap_count": summary["overwritten_overlap_count"],
        "row_count": int(len(merged)),
        "start_ts": start_ts.isoformat(),
        "end_ts": end_ts.isoformat(),
        "object_key": object_key,
    }


def run_casablanca_index_ingest(symbols: list[str] | None = None) -> dict:
    """
    Worker task: ingest Casablanca Bourse index OHLC history from the public
    boursenova JSON API into the market-data store (overwrite-if-different).

    symbols: optional filter restricting the run to these index symbols
             (e.g. ["MASI", "MASI_20"]). If None, ingests the default index set.
             For gap repair that never touches old bars use
             ``services.worker.tasks.backfill_bourse_history``.
    """
    db = SessionLocal()
    adapter = BoursenovaIndicesAdapter()

    report: dict = {
        "generated_at": _utcnow().isoformat(),
        "indices": {},
        "errors": [],
    }

    wanted = list(symbols) if symbols else list(CASABLANCA_INDEX_SYMBOLS)
    ok_count = 0
    fail_count = 0

    for symbol in wanted:
        if symbol not in BOURSENOVA_APP_SYMBOL_TO_CODE:
            report["indices"][symbol] = {"status": "skipped", "reason": "no_boursenova_code"}
            continue
        try:
            df = fetch_index_history(symbol, adapter)
            display_name = str(df["display_name"].iloc[-1]) if not df.empty else symbol
            result = ingest_one(db, symbol, display_name, df, None)
            report["indices"][symbol] = result
            if result.get("status") == "error":
                fail_count += 1
                db.rollback()
            else:
                ok_count += 1
                db.commit()
        except Exception as exc:
            db.rollback()
            fail_count += 1
            report["indices"][symbol] = {
                "display_name": symbol,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
            logger.error(
                "ingest_casablanca_indices: failed for symbol=%s\n%s",
                symbol, traceback.format_exc(),
            )

    db.close()

    if ok_count > 0 and fail_count == 0:
        status = "succeeded"
    elif ok_count > 0 and fail_count > 0:
        status = "partial"
    else:
        status = "failed"

    report["status"] = status
    return report
