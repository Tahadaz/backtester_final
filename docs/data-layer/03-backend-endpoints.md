# 03 — Backend Endpoints

**File**: `services/api/app/routers/market_data.py`
**Prefix**: `/market-data`

---

## Catalog & Health

### GET /market-data/catalog
Core data page endpoint. Returns full-outer-join of stock_master + market_data_store. Every symbol in the system appears exactly once.

**Response**: `list[MarketCatalogRowOut]` — symbol + tracking metadata + OHLCV range + `is_tracked`, `has_canonical_data`, `market`, `is_stale`.

### GET /market-data/health
Quality snapshot: total_tracked, up_to_date (<2 biz days), stale, very_stale (<7 days), never_ingested, last_refresh_run, last_successful_refresh.

### GET /market-data/masi-tickers
93 MASI tickers (symbol, display_name, sector) for frontend autocomplete.

### GET /market-data/symbols?timeframe=1D
All symbols in market_data_store with OHLCV range and object_key.

---

## Stock Registry CRUD

### GET /market-data/stocks?is_active=true
Tracked stocks with OHLCV metadata. LEFT JOINs stock_master ↔ market_data_store.

### POST /market-data/stocks
Register new stock. Auto-fills display_name/sector from MASI registry. Auto-creates provider_symbol_map (yahoo `.CS`, bourse_direct).
For MASI symbols, `display_name` is canonical and taken from the registry even if the caller sends a different value.

### PATCH /market-data/stocks/{symbol}
Update: isin, sector, is_active, track_source, bourse_url, notes.

### DELETE /market-data/symbols/{symbol}
Cascade delete: market_data_store + provider_symbol_map + stock_master. Best-effort S3 cleanup.

---

## Provider Mappings

### GET /market-data/stocks/{symbol}/mappings
List provider maps (yahoo, bourse_direct) with confidence and verification status.

### PATCH /market-data/stocks/{symbol}/mappings/{provider}
Update provider_symbol, is_verified, override_reason. Verified → confidence=1.0.

---

## Bourse Lookup

### GET /market-data/stocks/{symbol}/bourse-lookup
Scrapes Bourse de Casablanca detail page. Extracts display_name (from `<title>`), ISIN (regex `MA[A-Z0-9]{10}`), sector. Returns URL even if scraping fails. Scraped names are informational; MASI registry names remain canonical for tracked MASI symbols.

---

## OHLCV Data

### GET /market-data/stocks/{symbol}/ohlcv-preview?limit=30
Last N bars via `load_ohlcv_for_symbol()`. Returns `OhlcvPreviewOut`.

### GET /market-data/stocks/{symbol}/ohlcv-history
Full historical OHLCV. Returns `OhlcvHistoryOut` with bars list, source_provider, data_as_of, row_count.

---

## Availability Calendar

### GET /market-data/stocks/{symbol}/availability-calendar
Date-by-date coverage map from first_date to last_date.

**Per-day classification logic**:
1. Load parquet → extract present dates set
2. For each calendar day in range:
   - Weekend → `weekend`
   - In holiday calendar (confirmed) → `market_holiday`
   - In holiday calendar (tentative) → `tentative_market_holiday`
   - Weekday + not holiday + no data → `missing_expected_day`
   - Has data → `present_data`
3. Detect partial bars (missing OHLCV fields)

**Response**: `AvailabilityCalendarOut` with days list + counts + default_month (1yr before last_date).

---

## Excel Upload

### POST /market-data/excel
Multipart upload. Validates size + extension. SHA256 → S3 key. Detects symbols from sheet names (filters generic: FEUIL1, SHEET1, DONNÉES, DATA). Creates Dataset row, enqueues `ingest_excel_to_store`.

### GET /market-data/uploads/{dataset_id}/status
Poll: checks S3 for ingest_report.json. Returns `{status: "processing"}` or `{status: "done", report: {...}}`.

### GET /market-data/uploads/{dataset_id}/report-url
Presigned S3 URL for ingest report.

---

## Format Reference

### GET /market-data/upload-format-reference
Self-documenting: canonical_fields, 3 format specs with aliases/examples/notes, validation rules. Called by ExcelUploadDialog to display accepted formats.

---

## Market Refresh

### POST /market-data/refresh
Trigger all-symbol refresh. Creates MarketRefreshRun (queued), enqueues `refresh_all_tracked_symbols`. Body: timeframe, source_override, include_unverified.

### POST /market-data/stocks/{symbol}/refresh
Single-symbol refresh. Same pattern.

### GET /market-data/refresh?limit=20&offset=0
List refresh runs (desc created_at).

### GET /market-data/refresh/{refresh_run_id}
Single run: status, progress (done/total/failed), timestamps, error_message.

---

## Technical Study (Legacy)

### POST /market-data/technical-study/sma
Pre-signal-engine SMA consensus endpoint. Computes rolling SMAs, signals per window, returns consensus %. May be superseded by signal engine endpoints.
