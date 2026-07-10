from __future__ import annotations

import logging
import time
import traceback
from datetime import datetime, timezone

import pandas as pd
import requests

from services.worker.db import SessionLocal
from core.quant_core.data import _standardize_ohlcv_index
from services.worker.tasks.ingest_market_data import (
    _drop_future_dated_rows,
    _merge_overwrite_if_different,
    _save_parquet,
    _try_load_existing_parquet,
    _upsert_index_master,
    _upsert_market_data_store_index,
)
from core.quant_core.s3_keys import build_market_store_object_key

logger = logging.getLogger(__name__)

# tid -> (symbol, display_name)
CASABLANCA_INDEX_CODES: dict[str, tuple[str, str]] = {
    "512335": ("MASI", "MASI"),
    "512343": ("MASI_20", "MASI 20"),
    "512320": ("MASI_ESG", "MASI ESG"),
    "512323": ("FTSE_CSE_MOROCCO_15", "FTSE CSE Morocco 15 Index"),
    "512324": ("FTSE_CSE_MOROCCO_ALL_LIQUID", "FTSE CSE Morocco All-Liquid"),
    "512336": ("MASI_USD", "MASI (USD)"),
    "512337": ("MASI_EUR", "MASI (EUR)"),
    "512340": ("MASI_RENTABILITE_BRUT", "MASI RENTABILITE BRUT"),
    "512341": ("MASI_RENTABILITE_NET", "MASI RENTABILITE NET"),
    "512338": ("MASI_MID_AND_SMALL_CAP", "MASI Mid and Small Cap"),
}

_SEED_URL = "https://www.casablanca-bourse.com/fr/historique-des-indices"
_API_URL = "https://api.casablanca-bourse.com/fr/api/bourse_data/index_history"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

SOURCE_PROVIDER = "casablanca_bourse_api"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_session() -> requests.Session:
    """Build a requests.Session and seed the F5 BIG-IP WAF cookies.

    The Drupal JSON:API returns 403 HTML to anonymous clients that don't
    carry the TS012ee01b* cookies set by a prior visit to the historique page.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT})
    # The certifi CA bundle shipped in some envs does not carry the CA that
    # signs *.casablanca-bourse.com, so requests raises SSLError even though the
    # chain is valid (curl / OS trust store accept it). Every existing
    # casablanca-bourse.com fetcher in core/quant_core/data.py already fetches
    # this same host with verify=False; mirror that precedent here. Only public
    # index prices are read and no credentials are ever sent.
    session.verify = False
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    try:
        session.get(_SEED_URL, timeout=30)
    except Exception:
        logger.warning("ingest_casablanca_indices: WAF cookie seed request failed", exc_info=True)
    return session


def _fetch_page(session: requests.Session, tid: str, *, limit: int, offset: int) -> dict | None:
    params = {
        "filter[ic][condition][path]": "field_index_code.tid",
        "filter[ic][condition][operator]": "=",
        "filter[ic][condition][value]": tid,
        "sort": "-field_seance_date",
        "page[limit]": limit,
        "page[offset]": offset,
    }
    headers = {
        "Accept": "application/vnd.api+json",
        "Referer": _SEED_URL,
    }
    resp = session.get(_API_URL, params=params, headers=headers, timeout=30)
    try:
        return resp.json()
    except Exception:
        return None


def fetch_index_history(
    session: requests.Session,
    tid: str,
    *,
    page_limit: int = 250,
    max_offset: int = 1500,
) -> pd.DataFrame:
    """Paginate the Casablanca Bourse index_history JSON:API for a single index tid.

    Returns a DataFrame indexed by a datetime "Date" (ascending, deduped) with
    float columns close/high/low.
    """
    rows: list[dict] = []
    offset = 0
    reseeded = False

    while offset <= max_offset:
        payload = _fetch_page(session, tid, limit=page_limit, offset=offset)

        if payload is None or "data" not in payload:
            if not reseeded:
                logger.info(
                    "ingest_casablanca_indices: non-JSON/403 response for tid=%s offset=%s; re-seeding session",
                    tid, offset,
                )
                reseeded = True
                session = _new_session()
                payload = _fetch_page(session, tid, limit=page_limit, offset=offset)
                if payload is None or "data" not in payload:
                    break
            else:
                break

        data = payload.get("data") or []
        if not data:
            break

        for item in data:
            attrs = item.get("attributes") or {}
            date_str = attrs.get("field_seance_date")
            if not date_str:
                continue
            rows.append(
                {
                    "Date": date_str,
                    "close": attrs.get("field_index_value"),
                    "high": attrs.get("field_index_high_value"),
                    "low": attrs.get("field_index_low_value"),
                }
            )

        if len(data) < page_limit:
            break

        offset += page_limit

    if not rows:
        return pd.DataFrame(columns=["close", "high", "low"])

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    for col in ("close", "high", "low"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.set_index("Date")
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[["close", "high", "low"]]


def ingest_one(db, tid: str, symbol: str, display_name: str, df: pd.DataFrame, dataset_id) -> dict:
    if df.empty:
        return {
            "display_name": display_name,
            "status": "error",
            "error": "empty_after_fetch",
        }

    df_std = _standardize_ohlcv_index(df)
    df_std = _drop_future_dated_rows(df_std)

    if df_std.empty:
        return {
            "display_name": display_name,
            "status": "error",
            "error": "empty_after_standardization",
        }

    object_key = build_market_store_object_key(symbol, "1D")
    old = _try_load_existing_parquet(object_key)
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
    Drupal JSON:API into the market-data store.

    symbols: optional filter restricting the run to these index symbols
             (e.g. ["MASI", "MASI_20"]). If None, ingests all known indices.
    """
    db = SessionLocal()
    session = _new_session()

    wanted = set(symbols) if symbols else None

    report: dict = {
        "generated_at": _utcnow().isoformat(),
        "indices": {},
        "errors": [],
    }

    codes = [
        (tid, sym, name)
        for tid, (sym, name) in CASABLANCA_INDEX_CODES.items()
        if wanted is None or sym in wanted
    ]

    ok_count = 0
    fail_count = 0

    for i, (tid, symbol, display_name) in enumerate(codes):
        try:
            df = fetch_index_history(session, tid)
            result = ingest_one(db, tid, symbol, display_name, df, None)
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
                "display_name": display_name,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
            logger.error(
                "ingest_casablanca_indices: failed for symbol=%s tid=%s\n%s",
                symbol, tid, traceback.format_exc(),
            )
        if i < len(codes) - 1:
            time.sleep(0.5)

    db.close()

    if ok_count > 0 and fail_count == 0:
        status = "succeeded"
    elif ok_count > 0 and fail_count > 0:
        status = "partial"
    else:
        status = "failed"

    report["status"] = status
    return report
