# Data Layer — Backend API Endpoints

**File:** `services/api/app/routers/market_data.py`
**Router prefix:** `/market-data`
**All endpoints require `x-api-key` header** (injected by Next.js proxy automatically).

---

## Endpoint Index

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| GET | `/market-data/catalog` | 200 | Unified data page view (full-outer-join) |
| GET | `/market-data/symbols` | 200 | List ingested symbols from market_data_store |
| GET | `/market-data/health` | 200 | Freshness summary counts |
| GET | `/market-data/stocks` | 200 | List tracked stocks (stock_master + freshness) |
| POST | `/market-data/stocks` | **201** | Add stock to registry |
| PATCH | `/market-data/stocks/{symbol}` | 200 | Update stock metadata |
| GET | `/market-data/stocks/{symbol}/mappings` | 200 | List provider symbol mappings |
| PATCH | `/market-data/stocks/{symbol}/mappings/{provider}` | 200 | Update provider mapping |
| GET | `/market-data/stocks/{symbol}/bourse-lookup` | 200 | Scrape Bourse de Casablanca for metadata |
| GET | `/market-data/stocks/{symbol}/ohlcv-preview` | 200/404 | Last N bars from parquet |
| POST | `/market-data/excel` | 200 | Upload Excel file, trigger ingestion |
| GET | `/market-data/uploads/{dataset_id}/report-url` | 200 | Presigned URL to ingestion report |
| POST | `/market-data/refresh` | **202** | Trigger refresh for ALL active stocks |
| POST | `/market-data/stocks/{symbol}/refresh` | **202** | Trigger refresh for ONE stock |
| GET | `/market-data/refresh` | 200 | List recent refresh runs |
| GET | `/market-data/refresh/{refresh_run_id}` | 200/404 | Get single refresh run status |
| POST | `/market-data/technical-study/sma` | 200 | SMA consensus signals |

---

## `GET /market-data/catalog`

**Purpose:** Unified view for the `/data` page. Full-outer-join of `market_data_store` + `stock_master`.

**Returns:** `list[MarketCatalogRowOut]`

Each row has:
- Stock metadata from `stock_master` (display_name, isin, sector, bourse_url, etc.) — null if symbol only in market_data_store
- OHLCV metadata from `market_data_store` (start_ts, end_ts, row_count, source_provider, data_as_of) — null if tracked but not yet ingested
- Derived flags: `is_tracked` (has stock_master row), `has_canonical_data` (has market_data_store row), `is_stale` (data_as_of older than 2 business days)

**Logic:**
1. Query all `market_data_store` rows LEFT JOIN `stock_master` ON symbol
2. Query `stock_master` rows that have NO corresponding `market_data_store` row
3. Union both result sets

---

## `GET /market-data/symbols`

**Query params:** `timeframe` (default "1D")

**Returns:** `list[dict]` — `{symbol, timeframe, object_key, start_ts, end_ts, row_count, source_provider, updated_at}`

Simple read from `market_data_store` filtered by timeframe, ordered by symbol ASC.

---

## `GET /market-data/health`

**Returns:** `MarketHealthOut`

```json
{
  "total_tracked": 45,
  "up_to_date": 30,
  "stale": 10,
  "very_stale": 3,
  "never_ingested": 2,
  "last_refresh_run": { ... },
  "last_successful_refresh": "2026-03-11T14:30:00Z"
}
```

**Staleness logic** (`_is_stale`): a stock is stale if `data_as_of < 2 business days ago` (Mon-Fri only). `very_stale` = older than 7 days.

---

## `POST /market-data/stocks`

**Body:** `StockMasterCreate`
```json
{
  "symbol": "ATW",
  "display_name": "Attijariwafa Bank",
  "track_source": "bourse_direct",
  "sector": "Banques"
}
```

**Returns:** 201 + `StockMasterOut`

**Logic:**
1. Create `stock_master` row
2. `db.flush()` — **critical**: FK constraint requires stock_master row to exist before children
3. Create two `provider_symbol_map` rows:
   - yahoo: `{symbol}.CS`, confidence=0.9
   - bourse_direct: `{symbol}`, confidence=1.0
4. Commit

**Errors:** 409 if symbol already exists.

---

## `PATCH /market-data/stocks/{symbol}`

**Body:** `StockMasterUpdate` (all fields optional)

Updates any subset of: display_name, isin, sector, market_cap_class, is_active, track_source, bourse_url, notes.

---

## `GET /market-data/stocks/{symbol}/bourse-lookup`

**Purpose:** Scrape the Bourse de Casablanca stock page for auto-fill metadata.

**Returns:** `BourseStockLookupOut`
```json
{
  "symbol": "ATW",
  "bourse_url": "https://www.casablanca-bourse.com/...",
  "display_name": "ATTIJARIWAFA BANK",
  "sector": "Banques",
  "isin": "MA0000011926",
  "found": true
}
```

**Logic:**
1. Build URL from env `BOURSE_STOCK_PAGE_URL` template (default: casablanca-bourse.com)
2. Fetch HTML page
3. Regex extract: `<title>` → display_name, `MA[A-Z0-9]{10}` → ISIN, "Secteur:" → sector
4. Always returns `bourse_url` even if scraping fails (silently caught)

---

## `GET /market-data/stocks/{symbol}/ohlcv-preview`

**Query params:** `timeframe` (default "1D"), `limit` (default 30, max 500)

**Returns:** `OhlcvPreviewOut` — symbol, timeframe, bars (last N bars), source_provider, data_as_of, row_count

**Returns 404** if symbol has no `market_data_store` row.

**Logic:** Loads parquet from S3 via `object_key`, normalizes to DatetimeIndex, returns last N bars sorted ascending.

---

## `POST /market-data/excel`

**Body:** Multipart form: `file` (required) + `metadata_json` (optional JSON string)

**Returns:**
```json
{
  "dataset_id": "uuid",
  "job_id": "rq-job-id",
  "raw_object_key": "datasets/{sha256}/{filename}"
}
```

**Logic:**
1. Validate: non-empty, size < `DATASET_MAX_UPLOAD_BYTES` (100 MiB), extension `.xlsx`/`.xls`
2. SHA-256 hash → `object_key = datasets/{hash}/{filename}`
3. Store raw bytes in S3
4. Create `Dataset` row (source="uploaded_file")
5. Enqueue RQ job: `ingest_excel_to_store(dataset_id)` on the `"runs"` queue

---

## `POST /market-data/refresh`

**Body:** `MarketRefreshTriggerRequest`
```json
{
  "timeframe": "1D",
  "source_override": null,
  "include_unverified": false
}
```

**Returns:** 202
```json
{
  "refresh_run_id": "uuid",
  "status": "queued",
  "symbols_total": 45,
  "job_id": "rq-job-id"
}
```

**Logic:**
1. Count active stocks in `stock_master`
2. Create `MarketRefreshRun` (scope="all", status="queued")
3. Enqueue RQ job: `refresh_all_tracked_symbols(run_id, ...)` on `"market_refresh"` queue

---

## `POST /market-data/stocks/{symbol}/refresh`

Same as above but scope="single", enqueues `refresh_single_symbol(run_id, symbol, ...)`.

**Requires:** symbol must exist in `stock_master` (404 otherwise). The frontend auto-adds it first.

---

## `GET /market-data/refresh/{refresh_run_id}`

**Returns:** `MarketRefreshRunOut` — all fields including symbols_done/failed for progress tracking.

Frontend polls this every 2s while status is "queued" or "running".

---

## `POST /market-data/technical-study/sma`

**Body:**
```json
{
  "symbols": ["ATW", "BCP", "IAM"],
  "windows": [5, 10, 14, 20, 30, 50, 100, 200],
  "timeframe": "1D"
}
```

**Returns:** Per-symbol SMA consensus with per-window variations.

**Logic for each symbol:**
1. Load close series from `market_data_store` (preferred) OR latest `dataset` (fallback)
2. For each window: compute SMA, compare close vs SMA → BUY/SELL/HOLD signal
3. Consensus = majority vote; score_pct = agreement percentage
4. Returns: consensus_signal, score_pct, agreement_count, buy/sell/hold counts, per-window variations

**Data source priority:**
1. `market_data_store` → read parquet from S3
2. Fallback: latest `dataset` for symbol → read Excel sheet from S3
