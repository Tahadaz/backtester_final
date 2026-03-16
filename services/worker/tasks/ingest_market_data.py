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
from core.quant_core.s3_keys import build_dataset_object_key, build_market_store_object_key


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


def _resolve_canonical_symbol(db: Session, candidate: str) -> tuple[str | None, str | None]:
    """
    Resolve a pre-normalized (strip+upper) ticker candidate against the DB.

    Priority:
      1. market_data_store  — already has OHLCV data for this symbol
      2. stock_master       — registered in the registry but no data yet

    UPPER(symbol) comparison ensures any legacy mixed-case rows are matched.

    Returns:
      (canonical_symbol, exists_in)
        exists_in = "market_data_store" | "stock_master" | None
        canonical_symbol = None when the ticker is not known (upload must reject it)
    """
    row = db.execute(
        text(
            "SELECT symbol FROM market_data_store "
            "WHERE UPPER(symbol) = :sym AND timeframe = '1D'"
        ),
        {"sym": candidate},
    ).mappings().first()
    if row:
        return str(row["symbol"]), "market_data_store"

    row = db.execute(
        text("SELECT symbol FROM stock_master WHERE UPPER(symbol) = :sym"),
        {"sym": candidate},
    ).mappings().first()
    if row:
        return str(row["symbol"]), "stock_master"

    return None, None


def _clean_french_numeric_series(s: pd.Series) -> pd.Series:
    """
    Convert French-formatted numeric strings to float.

    Handles:
      '1 052,00'  -> 1052.0   (thousands space + decimal comma)
      '5 249'     -> 5249.0   (thousands space, no decimal)
      '982'       -> 982.0    (plain integer string)
      '-'         -> NaN      (placeholder)
      ''          -> NaN      (blank cell)
      None/NaN    -> NaN

    Works on columns that are already numeric (Excel-parsed) as well as
    string-typed columns.
    """
    s = s.astype(str).str.strip()
    # Non-breaking space (U+00A0) used as thousands separator in some locales
    s = s.str.replace("\u00a0", "", regex=False)
    # Regular space as thousands separator (e.g. '1 052,00')
    s = s.str.replace(" ", "", regex=False)
    # French decimal comma to dot
    s = s.str.replace(",", ".", regex=False)
    # Replace placeholder / empty strings with None so pd.to_numeric sees NaN
    s = s.replace(["", "-", "nan", "none", "None", "NaN"], None)
    return pd.to_numeric(s, errors="coerce")


def _norm_col(c: str) -> str:
    """Normalize a column label for format detection: strip, lowercase, collapse spaces."""
    return " ".join(str(c).strip().lower().split())


# Normalized indicator keys used to detect which format a sheet is in
_NEW_FORMAT_INDICATORS: frozenset[str] = frozenset({
    "séance",    # proper UTF-8
    "seance",    # accent stripped
    "sã©ance",   # mojibake of Séance
})

_OLD_FORMAT_INDICATORS: frozenset[str] = frozenset({
    "clôture",   # proper UTF-8
    "cloture",   # accent stripped
    "clã´ture",  # mojibake of Clôture
    "ouvt",      # unambiguous old-format column
})

# Normalized rename maps: _norm_col(original_label) -> canonical column name
_OLD_FORMAT_MAP: dict[str, str] = {
    "ouvt":          "Open",
    "'+haut":        "High",   # original BMCE: apostrophe prefix  e.g. "'+Haut"
    "+haut":         "High",   # newer files: space prefix stripped e.g. " +Haut" -> "+Haut"
    "'+bas":         "Low",    # original BMCE: apostrophe prefix  e.g. "'+Bas"
    "+bas":          "Low",    # newer files: space prefix stripped e.g. " +Bas"  -> "+Bas"
    "clôture":       "Close",
    "cloture":       "Close",
    "clã´ture":      "Close",
    "volume":        "Volume",
}

_NEW_FORMAT_MAP: dict[str, str] = {
    "séance":                         "Date",
    "seance":                         "Date",
    "sã©ance":                        "Date",
    "ouverture":                      "Open",
    "dernier cours":                  "Close",
    "+haut du jour":                  "High",
    "+bas du jour":                   "Low",
    "nombre de titres échangés":      "Volume",
    "nombre de titres echanges":      "Volume",
    "nombre de titres ã©changã©s":    "Volume",
}


def _detect_and_rename_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """
    Auto-detect old BMCE or new update Excel format and rename to canonical OHLCV names.

    Detection uses normalized (strip+lowercase) column labels so the match is
    case-insensitive and tolerates common accent/encoding variants (mojibake).

    Old format: Date column already present; Ouvt / +Haut / +Bas / Clôture / Volume.
    New format: Séance replaces Date; Ouverture / Dernier Cours / +haut du jour / etc.

    Returns:
      (renamed_df, detected_format)
      detected_format = "new" | "old" | "unknown"

    If neither format is detected the DataFrame is returned unchanged so that
    downstream validation surfaces the missing-column error.
    """
    norm_to_orig: dict[str, str] = {_norm_col(c): c for c in df.columns}
    norm_cols = set(norm_to_orig.keys())

    if norm_cols & _NEW_FORMAT_INDICATORS:
        rename_map = {
            norm_to_orig[n]: canonical
            for n, canonical in _NEW_FORMAT_MAP.items()
            if n in norm_to_orig
        }
        return df.rename(columns=rename_map), "new"

    if norm_cols & _OLD_FORMAT_INDICATORS:
        rename_map = {
            norm_to_orig[n]: canonical
            for n, canonical in _OLD_FORMAT_MAP.items()
            if n in norm_to_orig
        }
        return df.rename(columns=rename_map), "old"

    # Unknown format — return unchanged; _standardize_ohlcv will raise on missing columns
    return df, "unknown"


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
            # Initialize before try so the except block can reference them safely
            canonical_sym: str | None = None
            exists_in: str | None = None
            try:
                # ── Step 1: Explicit ticker identity resolution ────────────────────────
                # Query market_data_store first, then stock_master.
                # Upload is UPDATE-ONLY: unknown tickers are rejected here, not created.
                canonical_sym, exists_in = _resolve_canonical_symbol(db, sym)

                if canonical_sym is None:
                    report["symbols"][sym] = {
                        "canonical_symbol": None,
                        "exists_in": None,
                        "is_new_ticker": True,
                        "status": "error",
                        "error": (
                            "unknown ticker — upload is update-only; "
                            "register this symbol in stock_master before uploading data"
                        ),
                    }
                    continue

                # ── Step 2: Load sheet (case-insensitive match on sheet name) ─────────
                with pd.ExcelFile(BytesIO(payload)) as xls:
                    sheet_map = {str(n).strip().upper(): str(n) for n in xls.sheet_names}
                    if sym not in sheet_map:
                        report["symbols"][sym] = {
                            "canonical_symbol": canonical_sym,
                            "exists_in": exists_in,
                            "is_new_ticker": False,
                            "status": "error",
                            "error": f"sheet not found. available={xls.sheet_names}",
                        }
                        continue
                    sheet_name = sheet_map[sym]
                    df_raw = pd.read_excel(xls, sheet_name=sheet_name, engine="openpyxl")

                # ── Step 3: Column detection and renaming ────────────────────────────
                # Capture raw column names before any rename for diagnostics.
                raw_columns = list(df_raw.columns.astype(str))
                row_count_raw = int(len(df_raw))

                # Strip column labels (handles ' +Haut' -> '+Haut' etc.) then detect
                # format via normalized lowercase matching.
                df_raw.columns = df_raw.columns.astype(str).str.strip()
                df_raw, detected_format = _detect_and_rename_columns(df_raw)

                # After renaming, Date may now be a plain column (new format: was Séance).
                if "Date" in df_raw.columns:
                    df_raw["Date"] = pd.to_datetime(df_raw["Date"], errors="coerce")
                    df_raw = df_raw.dropna(subset=["Date"]).set_index("Date")
                elif not isinstance(df_raw.index, pd.DatetimeIndex):
                    raise ValueError(
                        f"Sheet {sheet_name}: no Date column found after format detection "
                        f"(detected_format={detected_format!r}). "
                        f"Columns present: {list(df_raw.columns)}"
                    )

                row_count_after_date_parse = int(len(df_raw))
                min_date_raw = df_raw.index.min().isoformat() if row_count_after_date_parse > 0 else None
                max_date_raw = df_raw.index.max().isoformat() if row_count_after_date_parse > 0 else None

                # ── Step 4: French numeric cleaning ──────────────────────────────────
                # Values like '1 052,00' or '5 249' are not parseable as floats by
                # pandas until the thousands separator (space) and decimal comma are
                # normalized.  Apply _clean_french_numeric_series to every OHLCV column
                # that is present BEFORE calling _standardize_ohlcv, which would
                # otherwise coerce all values to NaN and drop all rows.
                for col in ["Open", "High", "Low", "Close", "Volume"]:
                    if col in df_raw.columns:
                        df_raw[col] = _clean_french_numeric_series(df_raw[col])

                row_count_after_numeric_clean = int(len(df_raw))

                # ── Step 5: Standardize to canonical OHLCV ───────────────────────────
                df_std = _standardize_ohlcv(df_raw, tz="UTC", require_ohlc=True, fill_adj_close=False)
                df_std = df_std[["Open", "High", "Low", "Close", "Volume"]]
                row_count_after_standardize = int(len(df_std))

                if df_std.empty:
                    # Report as error (not "unchanged") so the caller can distinguish
                    # "nothing new to merge" from "data was present but unreadable".
                    report["symbols"][sym] = {
                        "canonical_symbol":              canonical_sym,
                        "exists_in":                     exists_in,
                        "is_new_ticker":                 False,
                        "status":                        "error",
                        "final_status_reason":           "empty_after_standardization",
                        "raw_columns":                   raw_columns,
                        "detected_format":               detected_format,
                        "row_count_raw":                 row_count_raw,
                        "row_count_after_date_parse":    row_count_after_date_parse,
                        "row_count_after_numeric_clean": row_count_after_numeric_clean,
                        "row_count_after_standardize":   row_count_after_standardize,
                        "min_date_raw":                  min_date_raw,
                        "max_date_raw":                  max_date_raw,
                    }
                    continue

                # ── Step 6: Load existing canonical parquet and merge ─────────────────
                # Always use canonical_sym (from DB) for the storage path — never the
                # raw sheet label — so casing variants never create a second parquet.
                object_key = build_market_store_object_key(canonical_sym, "1D")
                old = _try_load_existing_parquet(object_key)
                merged, summary = _merge_overwrite_if_different(old, df_std)

                if summary["status"] != "unchanged":
                    _save_parquet(object_key, merged)

                # ── Step 7: Upsert market_data_store for the canonical symbol ─────────
                start_ts = merged.index.min().to_pydatetime()
                end_ts = merged.index.max().to_pydatetime()
                row_count = int(len(merged))

                db.execute(
                    text("""
                        insert into market_data_store(
                            symbol, timeframe, object_key, start_ts, end_ts, row_count,
                            last_dataset_id, source_provider, data_as_of, created_at, updated_at
                        ) values (
                            :symbol, :timeframe, :object_key, :start_ts, :end_ts, :row_count,
                            :last_dataset_id, :source_provider, :data_as_of, now(), now()
                        )
                        on conflict (symbol, timeframe)
                        do update set
                            object_key      = excluded.object_key,
                            start_ts        = excluded.start_ts,
                            end_ts          = excluded.end_ts,
                            row_count       = excluded.row_count,
                            last_dataset_id = excluded.last_dataset_id,
                            source_provider = excluded.source_provider,
                            data_as_of      = excluded.data_as_of,
                            updated_at      = now()
                    """),
                    {
                        "symbol":          canonical_sym,
                        "timeframe":       "1D",
                        "object_key":      object_key,
                        "start_ts":        start_ts,
                        "end_ts":          end_ts,
                        "row_count":       row_count,
                        "last_dataset_id": rid,
                        "source_provider": "bmce_excel",
                        "data_as_of":      end_ts.date(),
                    },
                )

                # ── Step 8: Report entry ──────────────────────────────────────────────
                report["symbols"][sym] = {
                    "canonical_symbol":              canonical_sym,
                    "exists_in":                     exists_in,
                    "is_new_ticker":                 False,
                    **summary,
                    "final_status_reason":           summary["status"],
                    "raw_columns":                   raw_columns,
                    "detected_format":               detected_format,
                    "row_count_raw":                 row_count_raw,
                    "row_count_after_date_parse":    row_count_after_date_parse,
                    "row_count_after_numeric_clean": row_count_after_numeric_clean,
                    "row_count_after_standardize":   row_count_after_standardize,
                    "min_date_raw":                  min_date_raw,
                    "max_date_raw":                  max_date_raw,
                    "object_key":                    object_key,
                    "start_ts":                      start_ts.isoformat(),
                    "end_ts":                        end_ts.isoformat(),
                    "row_count":                     row_count,
                }

            except Exception as exc:
                report["symbols"][sym] = {
                    "canonical_symbol": canonical_sym,
                    "exists_in":        exists_in,
                    "is_new_ticker":    canonical_sym is None,
                    "status": "error",
                    "error":  f"{type(exc).__name__}: {exc}",
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
