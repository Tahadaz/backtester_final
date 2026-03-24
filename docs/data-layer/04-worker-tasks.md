# 04 — Worker Tasks

Two RQ worker tasks handle data processing asynchronously. Both are enqueued by API endpoints and update database state as they progress.

---

## Task 1: Excel Ingestion (`ingest_market_data.py`)

**Entry point**: `ingest_excel_to_store(dataset_id: str) → dict`
**Triggered by**: `POST /market-data/excel`
**File**: `services/worker/tasks/ingest_market_data.py`

### Processing Pipeline

```
Step 1: LOAD DATASET
  → Fetch Dataset row (id, data_hash, filename, object_key, meta_json)
  → Download Excel bytes from S3 (prefers stored object_key; fallback to datasets/{hash}/{filename})

Step 2: DETECT SYMBOLS
  → Parse workbook sheet names
  → Fall back to detected_symbols from upload metadata
  → Filter generic names: FEUIL1, SHEET1, DONNÉES, DATA, DONNEES
  → Extract symbol from filename (e.g., "ATW_historique.xlsx" → "ATW")

Step 3: RESOLVE CANONICAL SYMBOL (per symbol)
  → _resolve_canonical_symbol(db, candidate)
  → Query market_data_store (1D) then stock_master (UPPER match)
  → If not found: auto-create stock_master + provider_symbol_map (yahoo .CS + bourse_direct)

Step 4: LOAD SHEET
  → Case-insensitive sheet name match against symbol
  → Fallback chain: single-sheet → first non-generic sheet → first sheet
  → Parse with openpyxl engine

Step 5: FORMAT DETECTION
  → _detect_and_rename_columns_with_aliases(df)
  → Calls rename_columns_for_upload() from market_data_formats.py
  → Detects format: bmce_new, bmce_old, investing, or unknown
  → Renames columns to canonical: Date, Open, High, Low, Close, Volume
  → Records matched aliases for diagnostics

Step 6: DATE PARSING
  → parse_datetime_series(values, day_first, format_id)
  → For "investing" format: sophisticated candidate resolution for ambiguous MM/DD vs DD/MM
  → Filters future-dated values (>= market_today_local)
  → Sets Date as DatetimeIndex, drops NaT rows

Step 7: NUMERIC CLEANING
  → For each OHLCV column: parse_numeric_series(values, number_style)
  → Handles French notation ("1 052,00"), English ("1,052.00")
  → Volume suffixes: K (×1,000), M (×1,000,000), B (×1,000,000,000)

Step 8: STANDARDIZATION
  → _standardize_ohlcv(df, tz="UTC", require_ohlc=True)
  → Validates/cleans columns → canonical: Open, High, Low, Close, Volume
  → Drops rows with NaN in OHLCV (except Volume)
  → Drops future-dated rows

Step 9: MERGE WITH EXISTING
  → _try_load_existing_parquet(object_key) → existing DataFrame or None
  → _merge_overwrite_if_different(old, new):
      - Removes future rows from both
      - inserted = new timestamps not in old
      - overwritten = same timestamp, different OHLCV values
      - Status: "created" (no existing), "updated" (changes), "unchanged"

Step 10: SAVE & UPDATE DB
  → Write merged parquet to S3 (market_data_store/{symbol}/1D)
  → Upsert market_data_store row (object_key, start_ts, end_ts, row_count, source_provider="bmce_excel", data_as_of)

Step 11: WRITE REPORT
  → Write ingest_report.json to market_data/uploads/{dataset_id}/ingest_report.json
  → Per-symbol: status, row_count, detected_format, matched_aliases, error details
```

### Error Handling

- **Per-symbol**: try/except catches and logs to report; processing continues for other symbols
- **Global**: traceback logged to report, exception re-raised
- **Return**: `{dataset_id, report_object_key, symbols: {sym: status}}`

### Merge Policy: Overwrite-If-Different

The `_merge_overwrite_if_different` function implements a safe incremental merge:

1. Remove future-dated rows from both old and new DataFrames
2. For overlapping timestamps: if OHLCV values differ, new data wins
3. For new timestamps: inserted
4. Result: union of all timestamps with latest values
5. Status computed from counts: created (no old data), updated (changes exist), unchanged (identical)

This ensures that re-uploading an Excel file with corrections automatically fixes the canonical store.

---

## Task 2: Market Refresh (`refresh_market_data.py`)

**Entry points**:
- `refresh_all_tracked_symbols(refresh_run_id, timeframe="1D", source_override, include_unverified)`
- `refresh_single_symbol(refresh_run_id, symbol, timeframe="1D", source)`

**Triggered by**: `POST /market-data/refresh` or `POST /market-data/stocks/{symbol}/refresh`
**File**: `services/worker/tasks/refresh_market_data.py`

### Per-Symbol Refresh (`_do_refresh_symbol`)

```
Step 1: RESOLVE PROVIDER
  → Query provider_symbol_map for symbol
  → Determine provider_symbol (e.g., "ATW.CS" for Yahoo)

Step 2: SELECT ADAPTER
  → source="yahoo": YFinanceMoroccoAdapter (provider_symbol = "{sym}.CS")
  → source="bourse_direct" + BOURSE_DIRECT_URL_TEMPLATE set: BourseDirectAdapter
  → source="bourse_direct" + no template: BDCSessionAdapter (live scraper)

Step 3: DETERMINE START DATE
  → Query market_data_store for existing end_ts
  → Session adapter: re-fetch last stored day (overwrite in-flight bars)
  → Historical adapter: start at end_ts + 1 day (avoid redundant fetch)

Step 4: FETCH DATA
  → adapter.load(symbols=[symbol], start=fetch_start, end=None, interval="1d")
  → Returns MarketData with bars dict keyed by symbol

Step 5: VALIDATE & MERGE
  → _validate_ohlcv(df_new, symbol)
  → Keep canonical columns (Open, High, Low, Close, Volume)
  → Merge with existing parquet (same merge logic as ingestion)

Step 6: UPDATE DB
  → _upsert_market_data_store() — insert or update market_data_store row
```

### All-Symbols Refresh

1. Load all `is_active=true` stocks from stock_master
2. Set run status to "running"
3. Loop per-symbol, calling `_do_refresh_symbol()`
4. After each symbol: update progress counters (`symbols_done`, `symbols_failed`)
5. Final status: "succeeded" (0 failures) / "partial" (some) / "failed" (all)

### Error Handling

- `_set_run_status(db, run_id, status, ...)` — Updates market_refresh_run
- `_log_error(db, run_id, symbol, provider, error_type, error_message, raw_response)` — Inserts market_refresh_error row (message capped at 4,000 chars, raw_response at 2,000)
- Per-symbol errors are logged but don't stop the run

### Adapter Selection

| Source | Adapter | Provider Symbol | Notes |
|--------|---------|-----------------|-------|
| yahoo | YFinanceMoroccoAdapter | `{sym}.CS` | Default suffix for Casablanca |
| bourse_direct | BourseDirectAdapter | `{sym}` | Requires `BOURSE_DIRECT_URL_TEMPLATE` env var |
| bourse_direct | BDCSessionAdapter | `{sym}` | Live session scraper (fallback if no template) |
