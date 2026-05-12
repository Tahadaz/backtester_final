from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import json
import re
import traceback
from uuid import UUID, uuid4

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.api.app.market_data_formats import (
    CANONICAL_OHLCV_FIELDS,
    detect_upload_format,
    market_today_local,
    parse_datetime_series,
    parse_numeric_series,
    rename_columns_for_upload,
)
from services.api.app.masi_tickers import get_masi_info, is_masi_ticker
from services.worker.db import SessionLocal
from services.worker.config import settings
from services.worker.storage import s3_client, ensure_bucket

# Reuse your core normalizer (keeps canonical OHLCV rules identical)
from core.quant_core.data import _standardize_ohlcv, _standardize_ohlcv_index, _slugify_index_name
from core.quant_core.s3_keys import build_dataset_object_key, build_market_store_object_key
from services.worker.tasks.dashboard_snapshot import regenerate_dashboard_snapshot


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _finite_float(value) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if np.isfinite(out) else None


def _compute_adv_20d_value(frame: pd.DataFrame) -> float | None:
    if frame.empty or "Close" not in frame.columns or "Volume" not in frame.columns:
        return None
    recent = frame.tail(20)
    close = pd.to_numeric(recent["Close"], errors="coerce")
    volume = pd.to_numeric(recent["Volume"], errors="coerce")
    traded_value = (close * volume).replace([np.inf, -np.inf], np.nan).dropna()
    if traded_value.empty:
        return None
    return _finite_float(traded_value.mean())


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
    # NaN-safe comparison: treat NaN == NaN as equal, NaN != value as different
    diff_mask = (old_slice.fillna("__NA__") != new_slice.fillna("__NA__")).any(axis=1)
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
    return parse_numeric_series(s, number_style="french", allow_suffixes=True)


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

# Investing.com / generic French export: Dernier, Ouv., Plus Haut, Plus Bas, Vol.
_INVESTING_FORMAT_INDICATORS: frozenset[str] = frozenset({
    "dernier",
    "ouv.",
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

_INVESTING_FORMAT_MAP: dict[str, str] = {
    "dernier":     "Close",
    "ouv.":        "Open",
    "plus haut":   "High",
    "plus bas":    "Low",
    "vol.":        "Volume",
    # "Variation %" is ignored — not needed for OHLCV
}


def _detect_and_rename_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """
    Auto-detect Excel column format and rename to canonical OHLCV names.

    Detection uses normalized (strip+lowercase) column labels so the match is
    case-insensitive and tolerates common accent/encoding variants (mojibake).

    Supported formats (checked in order):
      1. BMCE new:     Séance / Ouverture / Dernier Cours / +haut du jour / etc.
      2. Investing.com: Date / Dernier / Ouv. / Plus Haut / Plus Bas / Vol.
      3. BMCE old:     Date / Ouvt / '+Haut / '+Bas / Clôture / Volume

    Returns:
      (renamed_df, detected_format)
      detected_format = "new" | "investing" | "old" | "unknown"

    If no format is detected the DataFrame is returned unchanged so that
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

    # Investing.com: "dernier" (alone, not "dernier cours") or "ouv." with dot
    if norm_cols & _INVESTING_FORMAT_INDICATORS:
        rename_map = {
            norm_to_orig[n]: canonical
            for n, canonical in _INVESTING_FORMAT_MAP.items()
            if n in norm_to_orig
        }
        return df.rename(columns=rename_map), "investing"

    if norm_cols & _OLD_FORMAT_INDICATORS:
        rename_map = {
            norm_to_orig[n]: canonical
            for n, canonical in _OLD_FORMAT_MAP.items()
            if n in norm_to_orig
        }
        return df.rename(columns=rename_map), "old"

    # Unknown format — return unchanged; _standardize_ohlcv will raise on missing columns
    return df, "unknown"


def _detect_and_rename_columns_with_aliases(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, str, dict[str, dict[str, str]]]:
    return rename_columns_for_upload(df)


def _strict_valid_ohlcv_rows(df: pd.DataFrame) -> pd.DataFrame:
    if "Close" not in df.columns:
        return df.iloc[0:0]
    return df.dropna(subset=["Close"])


def _drop_future_dated_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cutoff = market_today_local()
    mask = pd.Index(df.index).map(lambda ts: ts.date() <= cutoff)
    return df.loc[mask]


def _normalize_upload_scope(meta: dict[str, object] | None) -> str:
    raw_scope = str((meta or {}).get("upload_scope") or "").strip().lower()
    return raw_scope if raw_scope in {"masi", "other"} else "other"


def _is_symbol_allowed_for_upload_scope(symbol: str, upload_scope: str) -> tuple[bool, str | None]:
    if upload_scope == "masi" and not is_masi_ticker(symbol):
        return False, "non_masi_symbol_rejected"
    return True, None


def _mark_ohlc_zeros_as_missing(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("Open", "High", "Low", "Close"):
        if col in out.columns:
            out[col] = out[col].where(out[col] != 0)
    return out


def _merge_overwrite_if_different(old: pd.DataFrame | None, incoming: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Returns merged_df and a summary:
      inserted_dates_count, overwritten_overlap_count, inserted_min/max, etc.
    """
    incoming = _drop_future_dated_rows(incoming)
    incoming = incoming.sort_index()
    incoming = incoming[~incoming.index.duplicated(keep="last")]

    if old is None or old.empty:
        merged = incoming
        return merged, {
            "inserted_count": int(len(incoming)),
            "overwritten_overlap_count": 0,
            "status": "created",
        }

    old = _drop_future_dated_rows(old)
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
        # Field-level merge: incoming non-NaN values overwrite existing;
        # incoming NaN values preserve existing (don't wipe out partial data).
        cols = ["Open", "High", "Low", "Close", "Volume"]
        old_slice = merged.loc[overlap_idx, cols]
        new_slice = incoming.loc[overlap_idx, cols]
        diff_rows = (old_slice.fillna("__NA__") != new_slice.fillna("__NA__")).any(axis=1)
        rows_to_overwrite = overlap_idx[diff_rows.values]
        if len(rows_to_overwrite) > 0:
            existing = merged.loc[rows_to_overwrite, cols]
            replacement = incoming.loc[rows_to_overwrite, cols]
            merged.loc[rows_to_overwrite, cols] = np.where(
                pd.notna(replacement), replacement, existing,
            )

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
        upload_scope = _normalize_upload_scope(meta)

        # Download excel — prefer stored object_key; fall back to canonical reconstruction.
        payload = _download_dataset_bytes(filename=filename, data_hash=data_hash, object_key=stored_key)

        # Parse workbook
        with pd.ExcelFile(BytesIO(payload)) as xls:
            sheet_names = xls.sheet_names

        # If detected symbols empty, fall back to sheet names (filter generic names)
        _GENERIC_SHEETS = {"FEUIL1", "FEUIL2", "FEUIL3", "SHEET1", "SHEET2", "SHEET3", "DONNÉES", "DATA"}
        raw_candidates = [str(s).strip().upper() for s in (detected or sheet_names) if str(s).strip()]
        symbols = [s for s in raw_candidates if s not in _GENERIC_SHEETS]
        symbols = list(dict.fromkeys(symbols))  # preserve order, unique

        # Also try to extract symbol from filename (e.g., "ATW_historique.xlsx" → "ATW")
        fname_stem = Path(filename).stem.upper()
        fname_parts = re.split(r'[_\-\s.]+', fname_stem)
        _SKIP_WORDS = {"UPLOAD", "HISTORIQUE", "DONNEES", "DATA", "EXPORT", "BOURSE", "BMCE"}
        for part in fname_parts:
            if (
                re.match(r'^[A-Z]{2,10}$', part)
                and part not in _SKIP_WORDS
                and part not in symbols
            ):
                symbols.append(part)
                break  # only take the first plausible ticker from filename

        ensure_bucket()

        for sym in symbols:
            # Initialize before try so the except block can reference them safely
            canonical_sym: str | None = None
            exists_in: str | None = None
            try:
                allowed, rejection_code = _is_symbol_allowed_for_upload_scope(sym, upload_scope)
                if not allowed:
                    report["symbols"][sym] = {
                        "canonical_symbol": None,
                        "exists_in": None,
                        "is_new_ticker": False,
                        "status": "error",
                        "final_status_reason": rejection_code,
                        "error_code": rejection_code,
                        "error": f"Symbol '{sym}' is not part of the MASI universe for this upload.",
                    }
                    continue

                # ── Step 1: Explicit ticker identity resolution ────────────────────────
                # Query market_data_store first, then stock_master.
                # Upload is UPDATE-ONLY: unknown tickers are rejected here, not created.
                canonical_sym, exists_in = _resolve_canonical_symbol(db, sym)

                if canonical_sym is None:
                    # Auto-create stock in stock_master + provider mappings
                    canonical_sym = sym  # already uppercased
                    masi_info = get_masi_info(canonical_sym)
                    display_name = masi_info["display_name"] if masi_info else canonical_sym
                    sector = masi_info["sector"] if masi_info else None
                    db.execute(
                        text("""
                            INSERT INTO stock_master (id, symbol, display_name, sector, is_active, track_source, created_at, updated_at)
                            VALUES (:id, :symbol, :display_name, :sector, true, 'bmce_excel', now(), now())
                            ON CONFLICT (symbol) DO NOTHING
                        """),
                        {"id": uuid4(), "symbol": canonical_sym, "display_name": display_name, "sector": sector},
                    )
                    # Yahoo provider mapping (.CS suffix for Casablanca)
                    db.execute(
                        text("""
                            INSERT INTO provider_symbol_map (symbol, provider, provider_symbol, confidence, is_verified)
                            VALUES (:symbol, 'yahoo', :yahoo_sym, 0.9, false)
                            ON CONFLICT (symbol, provider) DO NOTHING
                        """),
                        {"symbol": canonical_sym, "yahoo_sym": f"{canonical_sym}.CS"},
                    )
                    # Bourse Direct provider mapping
                    db.execute(
                        text("""
                            INSERT INTO provider_symbol_map (symbol, provider, provider_symbol, confidence, is_verified)
                            VALUES (:symbol, 'bourse_direct', :bd_sym, 1.0, false)
                            ON CONFLICT (symbol, provider) DO NOTHING
                        """),
                        {"symbol": canonical_sym, "bd_sym": canonical_sym},
                    )
                    db.flush()
                    exists_in = "stock_master"

                # ── Step 2: Load sheet (case-insensitive match on sheet name) ─────────
                with pd.ExcelFile(BytesIO(payload)) as xls:
                    sheet_map = {str(n).strip().upper(): str(n) for n in xls.sheet_names}
                    if sym in sheet_map:
                        sheet_name = sheet_map[sym]
                    elif len(xls.sheet_names) == 1:
                        # Single-sheet file: use it even if name doesn't match symbol
                        # (common for files like "ATW_historique.xlsx" with sheet "Feuil1")
                        sheet_name = xls.sheet_names[0]
                    else:
                        # Multi-sheet file where no sheet matches the symbol name.
                        # Common with BMCE exports that have generic sheets (Feuil1, Feuil2).
                        # If the symbol came from the filename (not from sheet names),
                        # try the first non-generic sheet, or fall back to the first sheet.
                        _GEN = {"FEUIL1", "FEUIL2", "FEUIL3", "SHEET1", "SHEET2", "SHEET3", "DONNÉES", "DATA"}
                        non_generic = [n for n in xls.sheet_names if str(n).strip().upper() not in _GEN]
                        if len(non_generic) == 1:
                            sheet_name = non_generic[0]
                        else:
                            # All sheets are generic (or multiple non-generic with no match):
                            # use the first sheet as best-effort fallback.
                            sheet_name = xls.sheet_names[0]
                    df_raw = pd.read_excel(xls, sheet_name=sheet_name, engine="openpyxl")

                # ── Step 3: Column detection and renaming ────────────────────────────
                # Capture raw column names before any rename for diagnostics.
                raw_columns = list(df_raw.columns.astype(str))
                row_count_raw = int(len(df_raw))

                # Strip column labels (handles ' +Haut' -> '+Haut' etc.) then detect
                # format via normalized lowercase matching.
                df_raw.columns = df_raw.columns.astype(str).str.strip()
                format_spec = detect_upload_format(list(df_raw.columns.astype(str)))
                df_raw, detected_format, matched_aliases = _detect_and_rename_columns_with_aliases(df_raw)

                # After renaming, Date may now be a plain column (new format: was Séance).
                if format_spec is None:
                    report["symbols"][sym] = {
                        "canonical_symbol":                  canonical_sym,
                        "exists_in":                         exists_in,
                        "is_new_ticker":                     False,
                        "status":                            "error",
                        "final_status_reason":               "unknown_format",
                        "error_code":                        "unknown_upload_format",
                        "error":                             f"Sheet '{sym}' does not match a supported upload format.",
                        "raw_columns":                       raw_columns,
                        "detected_format":                   detected_format,
                        "matched_aliases":                   matched_aliases,
                        "row_count_raw":                     row_count_raw,
                        "row_count_after_date_parse":        0,
                        "row_count_after_numeric_clean":     0,
                        "row_count_after_standardize":       0,
                        "row_count_after_strict_validation": 0,
                    }
                    continue

                if "Date" in df_raw.columns:
                    df_raw["Date"] = parse_datetime_series(
                        df_raw["Date"],
                        day_first=format_spec.day_first,
                        format_id=format_spec.format_id,
                    )
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
                        df_raw[col] = parse_numeric_series(
                            df_raw[col],
                            number_style=format_spec.number_style,
                            allow_suffixes=(col == "Volume"),
                        )
                df_raw = _mark_ohlc_zeros_as_missing(df_raw)

                row_count_after_numeric_clean = int(len(df_raw))

                # ── Step 5: Standardize to canonical OHLCV ───────────────────────────
                df_std = _standardize_ohlcv(df_raw, tz="UTC", require_ohlc=True, fill_adj_close=False)
                df_std = df_std[["Open", "High", "Low", "Close", "Volume"]]
                row_count_after_standardize = int(len(df_std))
                df_std = _strict_valid_ohlcv_rows(df_std)
                row_count_after_strict_validation = int(len(df_std))
                df_std = _drop_future_dated_rows(df_std)
                row_count_after_future_guard = int(len(df_std))

                if df_std.empty:
                    # Report as error (not "unchanged") so the caller can distinguish
                    # "nothing new to merge" from "data was present but unreadable".
                    report["symbols"][sym] = {
                        "canonical_symbol":              canonical_sym,
                        "exists_in":                     exists_in,
                        "is_new_ticker":                 False,
                        "status":                        "error",
                        "final_status_reason":           "empty_after_standardization",
                        "error_code":                    "empty_after_standardization",
                        "error":                         "No valid OHLCV rows remained after cleaning and validation.",
                        "raw_columns":                   raw_columns,
                        "detected_format":               detected_format,
                        "matched_aliases":               matched_aliases,
                        "row_count_raw":                 row_count_raw,
                        "row_count_after_date_parse":    row_count_after_date_parse,
                        "row_count_after_numeric_clean": row_count_after_numeric_clean,
                        "row_count_after_standardize":   row_count_after_standardize,
                        "row_count_after_strict_validation": row_count_after_strict_validation,
                        "row_count_after_future_guard":  row_count_after_future_guard,
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
                close_last = _finite_float(merged["Close"].iloc[-1]) if "Close" in merged.columns and len(merged) >= 1 else None
                prev_close = _finite_float(merged["Close"].iloc[-2]) if "Close" in merged.columns and len(merged) >= 2 else None
                adv_20d = _compute_adv_20d_value(merged)

                db.execute(
                    text("""
                        insert into market_data_store(
                            symbol, timeframe, object_key, start_ts, end_ts, row_count,
                            last_dataset_id, source_provider, data_as_of,
                            close_last, prev_close, adv_20d, created_at, updated_at
                        ) values (
                            :symbol, :timeframe, :object_key, :start_ts, :end_ts, :row_count,
                            :last_dataset_id, :source_provider, :data_as_of,
                            :close_last, :prev_close, :adv_20d, now(), now()
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
                            close_last      = excluded.close_last,
                            prev_close      = excluded.prev_close,
                            adv_20d         = excluded.adv_20d,
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
                        "close_last":      close_last,
                        "prev_close":      prev_close,
                        "adv_20d":         adv_20d,
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
                    "matched_aliases":               matched_aliases,
                    "row_count_raw":                 row_count_raw,
                    "row_count_after_date_parse":    row_count_after_date_parse,
                    "row_count_after_numeric_clean": row_count_after_numeric_clean,
                    "row_count_after_standardize":   row_count_after_standardize,
                    "row_count_after_strict_validation": row_count_after_strict_validation,
                    "row_count_after_future_guard":  row_count_after_future_guard,
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
        pass

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


# ---------------------------------------------------------------------------
# Moroccan index Excel ingestion
# ---------------------------------------------------------------------------

# Expected French column aliases in uploaded index Excel files
_INDEX_COLUMN_ALIASES: dict[str, list[str]] = {
    "date":    ["date", "séance", "seance", "date séance"],
    "close":   ["valeur indice", "valeur_indice", "valeur", "cours", "clôture"],
    "high":    ["plus haut", "plus_haut", "haut"],
    "low":     ["plus bas", "plus_bas", "bas"],
    "libelle": ["libellé indice", "libelle indice", "libellé", "libelle", "indice", "nom"],
}


def _rename_index_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map French/alias column names to canonical names for index OHLCV."""
    rename: dict[str, str] = {}
    for col in df.columns:
        col_lower = col.lower().strip()
        for canonical, aliases in _INDEX_COLUMN_ALIASES.items():
            if col_lower in aliases:
                rename[col] = canonical
                break
    return df.rename(columns=rename)


def _upsert_index_master(db, symbol: str, display_name: str) -> None:
    """Insert index_master row if it doesn't exist yet; update display_name if it does."""
    db.execute(
        text("""
            INSERT INTO index_master (symbol, display_name, source, is_active, created_at, updated_at)
            VALUES (:symbol, :display_name, 'casablanca_bourse', true, now(), now())
            ON CONFLICT (symbol)
            DO UPDATE SET display_name = excluded.display_name, updated_at = now()
        """),
        {"symbol": symbol, "display_name": display_name},
    )


def _upsert_market_data_store_index(
    db,
    symbol: str,
    object_key: str,
    start_ts,
    end_ts,
    row_count: int,
    dataset_id,
) -> None:
    db.execute(
        text("""
            INSERT INTO market_data_store(
                symbol, timeframe, object_key, start_ts, end_ts, row_count,
                last_dataset_id, source_provider, data_as_of, asset_class,
                created_at, updated_at
            ) VALUES (
                :symbol, '1D', :object_key, :start_ts, :end_ts, :row_count,
                :last_dataset_id, 'casablanca_bourse_excel', :data_as_of, 'index',
                now(), now()
            )
            ON CONFLICT (symbol, timeframe)
            DO UPDATE SET
                object_key      = excluded.object_key,
                start_ts        = excluded.start_ts,
                end_ts          = excluded.end_ts,
                row_count       = excluded.row_count,
                last_dataset_id = excluded.last_dataset_id,
                source_provider = excluded.source_provider,
                data_as_of      = excluded.data_as_of,
                asset_class     = excluded.asset_class,
                updated_at      = now()
        """),
        {
            "symbol":          symbol,
            "object_key":      object_key,
            "start_ts":        start_ts,
            "end_ts":          end_ts,
            "row_count":       row_count,
            "last_dataset_id": dataset_id,
            "data_as_of":      end_ts.date() if hasattr(end_ts, "date") else end_ts,
        },
    )


def ingest_excel_indices_to_store(dataset_id: str) -> dict:
    """
    Worker task: ingest a Moroccan index OHLCV Excel file.

    Expected sheet layout (one or many sheets, each with rows per date):
        Columns (French, case-insensitive): date, libellé indice, valeur indice, plus haut, plus bas

    Alternatively: a single sheet where each row is one index on one date.

    On first encounter, auto-creates index_master rows from the libellé.
    Open is synthesized as prev-close; Volume is set to 0.
    """
    db = SessionLocal()
    rid = UUID(dataset_id)

    report: dict = {
        "dataset_id": str(rid),
        "generated_at": _utcnow().isoformat(),
        "indices": {},
        "errors": [],
    }

    try:
        row = db.execute(
            text("SELECT id, data_hash, filename, object_key, meta_json FROM dataset WHERE id = :id"),
            {"id": rid},
        ).mappings().first()
        if not row:
            raise RuntimeError(f"Dataset not found: {rid}")

        filename = str(row["filename"] or "upload.xlsx")
        data_hash = str(row["data_hash"])
        stored_key = str(row["object_key"]) if row.get("object_key") else None

        payload = _download_dataset_bytes(filename=filename, data_hash=data_hash, object_key=stored_key)
        ensure_bucket()

        with pd.ExcelFile(BytesIO(payload)) as xls:
            sheet_names = xls.sheet_names

        # Collect per-index data across all sheets
        # Strategy: read all sheets, look for a "libelle" column to identify per-index rows,
        # or treat each sheet as one index (sheet name = symbol).
        index_frames: dict[str, tuple[str, pd.DataFrame]] = {}  # symbol -> (display_name, df)

        for sheet in sheet_names:
            try:
                raw = pd.read_excel(BytesIO(payload), sheet_name=sheet, header=0)
                if raw.empty:
                    continue
                raw = _rename_index_columns(raw)

                if "libelle" in raw.columns:
                    # Multi-index sheet: group by libelle
                    for libelle, grp in raw.groupby("libelle"):
                        symbol = _slugify_index_name(str(libelle))
                        grp = grp.drop(columns=["libelle"], errors="ignore").copy()
                        if symbol in index_frames:
                            index_frames[symbol] = (
                                str(libelle),
                                pd.concat([index_frames[symbol][1], grp], axis=0),
                            )
                        else:
                            index_frames[symbol] = (str(libelle), grp)
                else:
                    # Single-index sheet: use sheet name as display_name
                    symbol = _slugify_index_name(str(sheet))
                    display_name = str(sheet)
                    if symbol in index_frames:
                        index_frames[symbol] = (
                            display_name,
                            pd.concat([index_frames[symbol][1], raw], axis=0),
                        )
                    else:
                        index_frames[symbol] = (display_name, raw)
            except Exception as exc:
                report["errors"].append(f"Sheet '{sheet}': {type(exc).__name__}: {exc}")

        for symbol, (display_name, df) in index_frames.items():
            try:
                # Parse date index
                if "date" in df.columns:
                    from services.api.app.market_data_formats import parse_datetime_series
                    df["date"] = parse_datetime_series(df["date"])
                    df = df.dropna(subset=["date"]).set_index("date")
                    df.index.name = "Date"

                # Standardize
                df_std = _standardize_ohlcv_index(df)
                df_std = _drop_future_dated_rows(df_std)

                if df_std.empty:
                    report["indices"][symbol] = {"status": "error", "error": "empty_after_standardization"}
                    continue

                object_key = build_market_store_object_key(symbol, "1D")
                old = _try_load_existing_parquet(object_key)
                merged, summary = _merge_overwrite_if_different(old, df_std)

                if summary["status"] != "unchanged":
                    _save_parquet(object_key, merged)

                start_ts = merged.index.min().to_pydatetime()
                end_ts = merged.index.max().to_pydatetime()

                _upsert_index_master(db, symbol, display_name)
                _upsert_market_data_store_index(
                    db, symbol, object_key, start_ts, end_ts, int(len(merged)), rid
                )

                report["indices"][symbol] = {
                    "display_name": display_name,
                    "status": summary["status"],
                    "inserted_count": summary["inserted_count"],
                    "overwritten_overlap_count": summary["overwritten_overlap_count"],
                    "row_count": int(len(merged)),
                    "start_ts": start_ts.isoformat(),
                    "end_ts": end_ts.isoformat(),
                    "object_key": object_key,
                }
            except Exception as exc:
                report["indices"][symbol] = {
                    "display_name": display_name,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }

        db.commit()
        report_key = _report_object_key(rid)
        _save_json(report_key, report)
        return {"dataset_id": str(rid), "report_object_key": report_key, "indices": report["indices"]}

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

