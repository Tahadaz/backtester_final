# Data Layer — Worker Tasks

Two RQ worker tasks handle data processing asynchronously.

---

## 1. Excel Ingestion — `ingest_excel_to_store`

**File:** `services/worker/tasks/ingest_market_data.py`
**Queue:** `"runs"` (shared with backtest jobs)
**Triggered by:** `POST /market-data/excel`

### Step-by-Step Flow

```
1. Load dataset metadata from DB (Dataset row)
2. Download raw file from S3 (datasets/{hash}/{filename})
3. Parse Excel workbook → extract sheet names
4. For each detected symbol (from meta_json.detected_symbols or sheet names):
   │
   ├─ 4a. Ticker Resolution (UPDATE-ONLY)
   │      Query market_data_store (priority), then stock_master
   │      If not found → log error, skip symbol (unknown tickers are NOT auto-created)
   │
   ├─ 4b. Sheet Loading
   │      Case-insensitive match on sheet name
   │
   ├─ 4c. Column Detection & Rename
   │      _detect_and_rename_columns() handles:
   │        Old BMCE format: Ouvt, '+Haut, '+Bas, Clôture, Volume
   │        New format: Séance, Ouverture, Dernier Cours, +haut du jour, +bas du jour, Nombre de titres échangés
   │      Normalized matching: lowercase + collapse-spaces
   │
   ├─ 4d. French Numeric Cleaning
   │      _clean_french_numeric_series(): "1 052,00" → 1052.0
   │      Handles space thousands + comma decimal + mojibake variants
   │
   ├─ 4e. OHLCV Standardization
   │      _standardize_ohlcv(): DatetimeIndex, required OHLC columns, numeric coercion
   │
   ├─ 4f. Merge with Existing Data
   │      Load existing parquet from S3 (if exists)
   │      _merge_overwrite_if_different(): deduplicate by index (keep='last')
   │      Only overwrites rows that actually differ
   │
   ├─ 4g. Save & Upsert
   │      Save merged parquet → S3: market_data/{symbol}/1D.parquet
   │      Upsert market_data_store row (source_provider="bmce_excel")
   │
   └─ 4h. Generate Per-Symbol Report
          status, detected_format, row counts at each stage

5. Save ingest_report.json → S3: market_data/uploads/{dataset_id}/ingest_report.json
```

### Column Rename Maps

**Old BMCE format:**
| French | English |
|--------|---------|
| Ouvt | Open |
| '+Haut | High |
| '+Bas | Low |
| Clôture | Close |
| Volume | Volume |

**New BMCE format:**
| French | English |
|--------|---------|
| Séance | Date |
| Ouverture | Open |
| Dernier Cours | Close |
| +haut du jour | High |
| +bas du jour | Low |
| Nombre de titres échangés | Volume |

### Key Helpers

- `_resolve_canonical_symbol(db, symbol)` — priority-based ticker resolution (market_data_store first, then stock_master). Returns None if unknown.
- `_detect_and_rename_columns(df)` — detects old/new BMCE format via normalized column matching, applies rename map
- `_clean_french_numeric_series(s)` — converts French number format: space thousands, comma decimal
- `_merge_overwrite_if_different(old_df, new_df)` — compares OHLCV rows, returns merged DF + summary dict
- `_save_parquet(df, object_key)` — write DataFrame to S3 as parquet
- `_save_json(data, object_key)` — write dict to S3 as JSON

---

## 2. Market Refresh — `refresh_single_symbol` / `refresh_all_tracked_symbols`

**File:** `services/worker/tasks/refresh_market_data.py`
**Queue:** `"market_refresh"` (dedicated queue, separate from backtest jobs)
**Triggered by:** `POST /market-data/refresh` or `POST /market-data/stocks/{symbol}/refresh`

### Single Symbol Flow

```
refresh_single_symbol(refresh_run_id, symbol, timeframe="1D", source)
│
├─ 1. Set MarketRefreshRun status → "running"
│
├─ 2. _do_refresh_symbol(db, run_id, symbol, timeframe, source)
│     │
│     ├─ 2a. Resolve provider_symbol
│     │      Query provider_symbol_map table
│     │      Fallback: {symbol}.CS for Yahoo, {symbol} for bourse_direct
│     │
│     ├─ 2b. Pick adapter
│     │      track_source == "bourse_direct" → BourseDirectAdapter (or BDCSessionAdapter)
│     │      track_source == "yahoo" → YFinanceMoroccoAdapter
│     │
│     ├─ 2c. Incremental fetch
│     │      Look up existing market_data_store.end_ts
│     │      Fetch from end_ts + 1 day onwards (avoid re-fetching)
│     │
│     ├─ 2d. Validate & normalize
│     │      _validate_ohlcv(): OHLC integrity checks (High ≥ max(O,C), Low ≤ min(O,C))
│     │      Keep only canonical columns: Open, High, Low, Close, Volume
│     │
│     ├─ 2e. Merge with existing parquet
│     │      Load existing from S3 → _merge_overwrite_if_different()
│     │      Deduplicate by DatetimeIndex (keep='last')
│     │
│     ├─ 2f. Save & upsert
│     │      Save merged parquet → S3: market_data/{symbol}/1D.parquet
│     │      Upsert market_data_store row with new timestamps
│     │
│     └─ Returns: result dict {status, inserted_count, overwritten_overlap_count, object_key, timestamps}
│
├─ 3. On success: set status → "succeeded"
└─ 4. On error: log to market_refresh_error, set status → "failed"
```

### Bulk Refresh Flow

```
refresh_all_tracked_symbols(refresh_run_id, timeframe="1D", source_override, include_unverified)
│
├─ 1. Set status → "running"
├─ 2. Query stock_master WHERE is_active=TRUE
├─ 3. Update symbols_total
├─ 4. For each symbol (sequential):
│     ├─ Call _do_refresh_symbol()
│     ├─ On success: increment symbols_done
│     ├─ On error: log to market_refresh_error, increment symbols_failed
│     └─ Commit progress after each symbol
├─ 5. Final status:
│     ├─ "succeeded" — 0 failures
│     ├─ "partial" — some failures, some successes
│     └─ "failed" — all symbols failed
└─ Returns: aggregated results dict
```

### Data Source Adapters (used by refresh)

| Adapter | Source | Symbol Transform | Notes |
|---------|--------|-----------------|-------|
| `BourseDirectAdapter` | Bourse de Casablanca download endpoint | none | Rate limited (0.5s delay). URL from env `BOURSE_DIRECT_URL_TEMPLATE` |
| `BDCSessionAdapter` | Bourse de Casablanca live page scraping | none | Returns single-row DF (current session only). Regex-parses HTML. |
| `YFinanceMoroccoAdapter` | Yahoo Finance | appends `.CS` suffix | Strips suffix from returned keys |

### Key Helpers

- `_resolve_provider_symbol(db, symbol, provider)` — query `provider_symbol_map` or fallback
- `_upsert_market_data_store(db, symbol, timeframe, object_key, start_ts, end_ts, row_count, source_provider)` — INSERT ON CONFLICT DO UPDATE
- `_set_run_status(db, run_id, status, **extra_fields)` — dynamic SQL builder for MarketRefreshRun updates
- `_log_error(db, run_id, symbol, provider, error_type, error_message, raw_response)` — insert MarketRefreshError row
