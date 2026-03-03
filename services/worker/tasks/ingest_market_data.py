from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import json
import traceback
from uuid import UUID, uuid4

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.worker.db import SessionLocal
from services.worker.config import settings
from services.worker.storage import s3_client, ensure_bucket

# Reuse your core normalizer (keeps canonical OHLCV rules identical)
from core.quant_core.data import _standardize_ohlcv
from core.quant_core.s3_keys import build_dataset_object_key


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_object_key(symbol: str) -> str:
    sym = str(symbol).strip().upper()
    return f"market_data/symbols/{sym}/ohlcv.parquet"


def _report_object_key(dataset_id: UUID) -> str:
    return f"market_data/uploads/{dataset_id}/ingest_report.json"


def _download_dataset_bytes(*, filename: str, data_hash: str, object_key: str | None = None) -> bytes:
    s3 = s3_client()
    # Prefer the stored object_key; fall back to canonical reconstruction for legacy rows.
    key = object_key or build_dataset_object_key(data_hash=data_hash, filename=filename)
    return s3.get_object(Bucket=settings.S3_BUCKET, Key=key)["Body"].read()


def _try_load_existing_parquet(object_key: str) -> pd.DataFrame | None:
    s3 = s3_client()
    try:
        obj = s3.get_object(Bucket=settings.S3_BUCKET, Key=object_key)
    except Exception:
        return None
    b = obj["Body"].read()
    if not b:
        return None
    df = pd.read_parquet(BytesIO(b))
    # Ensure DatetimeIndex (you want datetime_index)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(f"Existing parquet at {object_key} does not have a DatetimeIndex.")
    return df


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


def _save_json(object_key: str, payload: dict) -> None:
    ensure_bucket()
    b = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    s3 = s3_client()
    s3.put_object(
        Bucket=settings.S3_BUCKET,
        Key=object_key,
        Body=b,
        ContentType="application/json",
    )


def _diff_overlap(old: pd.DataFrame, new: pd.DataFrame, overlap_idx: pd.DatetimeIndex) -> int:
    """
    Count how many overlapping timestamps actually differ in OHLCV.
    We only overwrite those rows (overwrite_if_different policy).
    """
    if len(overlap_idx) == 0:
        return 0
    old_slice = old.loc[overlap_idx, ["Open", "High", "Low", "Close", "Volume"]]
    new_slice = new.loc[overlap_idx, ["Open", "High", "Low", "Close", "Volume"]]
    # any difference per row
    diff_mask = (old_slice != new_slice).any(axis=1)
    return int(diff_mask.sum())


def _merge_overwrite_if_different(old: pd.DataFrame | None, incoming: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Returns merged_df and a summary:
      inserted_dates_count, overwritten_overlap_count, inserted_min/max, etc.
    """
    incoming = incoming.sort_index()
    incoming = incoming[~incoming.index.duplicated(keep="last")]

    if old is None or old.empty:
        merged = incoming
        return merged, {
            "inserted_count": int(len(incoming)),
            "overwritten_overlap_count": 0,
            "status": "created",
        }

    old = old.sort_index()
    old = old[~old.index.duplicated(keep="last")]

    incoming_idx = incoming.index
    old_idx = old.index

    inserted_idx = incoming_idx.difference(old_idx)
    overlap_idx = incoming_idx.intersection(old_idx)

    overwritten_overlap_count = _diff_overlap(old, incoming, overlap_idx)

    merged = old.copy()
    if len(inserted_idx) > 0:
        merged = pd.concat([merged, incoming.loc[inserted_idx]], axis=0)

    if overwritten_overlap_count > 0:
        # overwrite only rows that differ
        old_slice = merged.loc[overlap_idx, ["Open", "High", "Low", "Close", "Volume"]]
        new_slice = incoming.loc[overlap_idx, ["Open", "High", "Low", "Close", "Volume"]]
        diff_rows = (old_slice != new_slice).any(axis=1)
        rows_to_overwrite = overlap_idx[diff_rows.values]
        merged.loc[rows_to_overwrite, ["Open", "High", "Low", "Close", "Volume"]] = incoming.loc[
            rows_to_overwrite, ["Open", "High", "Low", "Close", "Volume"]
        ].values

    merged = merged.sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]

    status = "unchanged"
    if len(inserted_idx) > 0 or overwritten_overlap_count > 0:
        status = "updated"

    summary = {
        "status": status,
        "inserted_count": int(len(inserted_idx)),
        "overwritten_overlap_count": int(overwritten_overlap_count),
    }
    return merged, summary


def ingest_excel_to_store(dataset_id: str) -> dict:
    """
    Worker task:
      - loads raw excel dataset from MinIO
      - parses each sheet as a symbol
      - standardizes OHLCV
      - merges into canonical parquet store per symbol (overwrite_if_different)
      - updates market_data_store table
      - writes ingest_report.json to MinIO
    """
    db: Session = SessionLocal()
    rid = UUID(dataset_id)

    report: dict = {
        "dataset_id": str(rid),
        "generated_at": _utcnow().isoformat(),
        "symbols": {},
        "errors": [],
    }

    try:
        # Load dataset metadata
        row = db.execute(
            text("""
                select id, data_hash, filename, object_key, meta_json
                from dataset
                where id = :id
            """),
            {"id": rid},
        ).mappings().first()
        if not row:
            raise RuntimeError(f"Dataset not found: {rid}")

        filename = str(row["filename"] or "upload.xlsx")
        data_hash = str(row["data_hash"])
        stored_key = str(row["object_key"]) if row.get("object_key") else None
        meta = dict(row.get("meta_json") or {})
        detected = meta.get("detected_symbols") or []

        # Download excel — prefer stored object_key; fall back to canonical reconstruction.
        payload = _download_dataset_bytes(filename=filename, data_hash=data_hash, object_key=stored_key)

        # Parse workbook
        with pd.ExcelFile(BytesIO(payload)) as xls:
            sheet_names = xls.sheet_names

        # If detected symbols empty, fall back to sheet names
        symbols = [str(s).strip().upper() for s in (detected or sheet_names) if str(s).strip()]
        symbols = list(dict.fromkeys(symbols))  # preserve order, unique

        ensure_bucket()

        for sym in symbols:
            try:
                # Find matching sheet name case-insensitively
                with pd.ExcelFile(BytesIO(payload)) as xls:
                    sheet_map = {str(n).strip().upper(): str(n) for n in xls.sheet_names}
                    if sym not in sheet_map:
                        report["symbols"][sym] = {"status": "error", "error": f"sheet not found. available={xls.sheet_names}"}
                        continue
                    sheet_name = sheet_map[sym]
                    df_raw = pd.read_excel(xls, sheet_name=sheet_name, engine="openpyxl")

                # Expect a 'Date' column like your BMCE loader
                df_raw.columns = df_raw.columns.astype(str).str.strip()
                if "Date" not in df_raw.columns:
                    raise ValueError(f"Sheet {sheet_name}: missing 'Date' column. Found: {list(df_raw.columns)}")

                df_raw["Date"] = pd.to_datetime(df_raw["Date"], errors="coerce")
                df_raw = df_raw.dropna(subset=["Date"]).set_index("Date")

                # Rename BMCE variants if needed (same as your BMCEDataSource)
                rename = {
                    "Ouvt": "Open",
                    "'+Haut": "High",
                    "'+Bas": "Low",
                    "Clôture": "Close",
                    "Volume": "Volume",
                }
                df_raw = df_raw.rename(columns=rename)

                # Standardize (store in UTC so it’s consistent)
                df_std = _standardize_ohlcv(df_raw, tz="UTC", require_ohlc=True, fill_adj_close=False)
                df_std = df_std[["Open", "High", "Low", "Close", "Volume"]]
                if df_std.empty:
                    report["symbols"][sym] = {"status": "unchanged", "note": "empty after standardization"}
                    continue

                object_key = _canonical_object_key(sym)
                old = _try_load_existing_parquet(object_key)

                merged, summary = _merge_overwrite_if_different(old, df_std)

                if summary["status"] != "unchanged":
                    _save_parquet(object_key, merged)

                # Update DB metadata row
                start_ts = merged.index.min().to_pydatetime()
                end_ts = merged.index.max().to_pydatetime()
                row_count = int(len(merged))

                db.execute(
                    text("""
                        insert into market_data_store(
                            symbol, timeframe, object_key, start_ts, end_ts, row_count, last_dataset_id, created_at, updated_at
                        ) values (
                            :symbol, :timeframe, :object_key, :start_ts, :end_ts, :row_count, :last_dataset_id, now(), now()
                        )
                        on conflict (symbol, timeframe)
                        do update set
                            object_key = excluded.object_key,
                            start_ts = excluded.start_ts,
                            end_ts = excluded.end_ts,
                            row_count = excluded.row_count,
                            last_dataset_id = excluded.last_dataset_id,
                            updated_at = now()
                    """),
                    {
                        "symbol": sym,
                        "timeframe": "1D",
                        "object_key": object_key,
                        "start_ts": start_ts,
                        "end_ts": end_ts,
                        "row_count": row_count,
                        "last_dataset_id": rid,
                    },
                )

                report["symbols"][sym] = {
                    **summary,
                    "object_key": object_key,
                    "start_ts": start_ts.isoformat(),
                    "end_ts": end_ts.isoformat(),
                    "row_count": row_count,
                }

            except Exception as exc:
                report["symbols"][sym] = {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }

        db.commit()

        # Save report
        report_key = _report_object_key(rid)
        _save_json(report_key, report)

        return {"dataset_id": str(rid), "report_object_key": report_key, "symbols": report["symbols"]}

    except Exception as exc:
        db.rollback()
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        report["traceback"] = traceback.format_exc()

        report_key = _report_object_key(rid)
        try:
            _save_json(report_key, report)
        except Exception:
            pass

        raise

    finally:
        db.close()
