# Data Layer — Database Models

**File:** `services/api/app/models.py`
**Migrations:** `services/api/alembic/versions/`

---

## Table: `market_data_store`

The canonical OHLCV container. One row per (symbol, timeframe) pair. Points to a parquet file in S3.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `symbol` | VARCHAR | **PK** (composite) | e.g. "ATW", "BCP" |
| `timeframe` | VARCHAR | **PK** (composite), default "1d" | always "1D" for daily |
| `object_key` | VARCHAR | NOT NULL | S3 path: `market_data/{SYMBOL}/1D.parquet` |
| `start_ts` | TIMESTAMPTZ | nullable | earliest bar date |
| `end_ts` | TIMESTAMPTZ | nullable | latest bar date — drives freshness |
| `row_count` | INTEGER | nullable | total bars in parquet |
| `last_dataset_id` | UUID | FK → `dataset.id`, nullable | source dataset for last update |
| `source_provider` | VARCHAR | nullable | "bourse_direct" \| "yahoo" \| "bmce_excel" |
| `data_as_of` | DATE | nullable | denormalized `end_ts.date()` for freshness queries |
| `updated_at` | TIMESTAMPTZ | server_default=now(), onupdate | |
| `created_at` | TIMESTAMPTZ | server_default=now() | |

**Key behaviors:**
- Upserted via `INSERT ... ON CONFLICT (symbol, timeframe) DO UPDATE` in worker tasks
- `object_key` always follows pattern `market_data/{symbol}/{timeframe}.parquet`
- `data_as_of` is what the `/health` endpoint uses for staleness computation

---

## Table: `stock_master`

Registry of tracked Moroccan stocks. Created when a user adds a stock via the UI or when the Bourse refresh auto-adds one.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | UUID | **PK** | server_default=uuid4 |
| `symbol` | VARCHAR | **UNIQUE** | e.g. "ATW" |
| `display_name` | VARCHAR | nullable | e.g. "Attijariwafa Bank" |
| `isin` | VARCHAR | nullable | e.g. "MA0000011926" |
| `sector` | VARCHAR | nullable | "Banques", "Assurances", etc. |
| `market_cap_class` | VARCHAR | nullable | "large" \| "mid" \| "small" |
| `is_active` | BOOLEAN | default=True | false = stop tracking in refreshes |
| `track_source` | VARCHAR | default="bourse_direct" | determines which adapter the worker uses |
| `bourse_url` | VARCHAR | nullable | link to Bourse de Casablanca stock page |
| `notes` | TEXT | nullable | free-form text |
| `created_at` | TIMESTAMPTZ | server_default=now() | |
| `updated_at` | TIMESTAMPTZ | server_default=now(), onupdate | |

**Index:** `ix_stock_master_is_active` on `is_active`

**Key behaviors:**
- `track_source` drives adapter selection: `"bourse_direct"` → BourseDirectAdapter, `"yahoo"` → YFinanceMoroccoAdapter
- When creating a stock, `db.flush()` must be called before inserting `provider_symbol_map` children (FK constraint)

---

## Table: `provider_symbol_map`

Maps internal symbol → provider-specific ticker. Auto-created when a `stock_master` row is added.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | BIGINT | **PK**, autoincrement | |
| `symbol` | VARCHAR | FK → `stock_master.symbol` | |
| `provider` | VARCHAR | | "yahoo" \| "bourse_direct" \| "bmce_excel" |
| `provider_symbol` | VARCHAR | | e.g. "ATW.CS" (yahoo), "ATW" (bourse_direct) |
| `confidence` | FLOAT | default=1.0 | 0.0–1.0; set to 1.0 when is_verified=true |
| `is_verified` | BOOLEAN | default=False | user-verified mapping |
| `override_reason` | VARCHAR | nullable | why mapping was changed |
| `created_at` | TIMESTAMPTZ | server_default=now() | |

**Unique constraint:** `(symbol, provider)`

**Auto-created mappings** (when stock is added):
- Yahoo: `{symbol}.CS` with confidence=0.9
- Bourse Direct: `{symbol}` with confidence=1.0

---

## Table: `market_refresh_run`

Tracks bulk or single-symbol refresh jobs. Created by the API, updated by the worker.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | UUID | **PK** | |
| `trigger_source` | VARCHAR | default="manual" | "manual" \| "scheduled" \| "api" |
| `scope` | VARCHAR | default="all" | "all" \| "single" |
| `symbol` | VARCHAR | nullable | populated if scope="single" |
| `timeframe` | VARCHAR | default="1D" | |
| `status` | VARCHAR | default="queued" | "queued" → "running" → "succeeded" \| "partial" \| "failed" |
| `rq_job_id` | VARCHAR | nullable | Redis Queue job ID |
| `symbols_total` | INTEGER | nullable | total symbols to refresh |
| `symbols_done` | INTEGER | nullable | incremented per symbol |
| `symbols_failed` | INTEGER | nullable | incremented on error |
| `started_at` | TIMESTAMPTZ | nullable | set when status → "running" |
| `finished_at` | TIMESTAMPTZ | nullable | set when terminal status |
| `created_at` | TIMESTAMPTZ | server_default=now() | |
| `error_message` | TEXT | nullable | top-level error (not per-symbol) |
| `meta_json` | JSONB | default={} | `{"source_override": "...", "include_unverified": false}` |

**Indexes:** `ix_market_refresh_run_status`, `ix_market_refresh_run_created_at`

**Terminal statuses:**
- `"succeeded"` — 0 failures
- `"partial"` — some failures, some successes
- `"failed"` — all symbols failed (or top-level error)

---

## Table: `market_refresh_error`

Per-symbol error log within a refresh run. FK cascade-deletes with the parent run.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | BIGINT | **PK**, autoincrement | |
| `refresh_run_id` | UUID | FK → `market_refresh_run.id`, ON DELETE CASCADE | |
| `symbol` | VARCHAR | | which symbol failed |
| `provider` | VARCHAR | default="bourse_direct" | which adapter was used |
| `error_type` | VARCHAR | nullable | "not_found" \| "parse_error" \| "network_error" \| "validation_error" |
| `error_message` | VARCHAR(4000) | nullable | |
| `raw_response` | VARCHAR(2000) | nullable | truncated response body for debugging |
| `created_at` | TIMESTAMPTZ | server_default=now() | |

**Indexes:** `ix_market_refresh_error_run`, `ix_market_refresh_error_symbol`

---

## Table: `dataset`

Uploaded data files (Excel, CSV). Used as raw input for ingestion.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | UUID | **PK** | |
| `source` | VARCHAR | | "BMCE_CSV" \| "Yahoo" \| "uploaded_file" |
| `symbol` | VARCHAR | | filename (for uploaded_file) or ticker |
| `timeframe` | VARCHAR | | "1D" |
| `data_hash` | VARCHAR | | SHA-256 of raw file bytes |
| `filename` | VARCHAR | nullable | original filename |
| `content_type` | VARCHAR | nullable | MIME type |
| `object_key` | VARCHAR | nullable | canonical S3 path: `datasets/{data_hash}/{filename}` |
| `size_bytes` | BIGINT | default=0 | |
| `meta_json` | JSONB | default={} | `{"detected_symbols": ["ATW", "BCP"], "filename": "..."}` |
| `start_ts` | TIMESTAMPTZ | nullable | |
| `end_ts` | TIMESTAMPTZ | nullable | |
| `created_at` | TIMESTAMPTZ | server_default=now() | |

---

## Entity Relationship Diagram

```
dataset ──────────────── market_data_store
  (1)  last_dataset_id FK   (symbol, timeframe) PK
                                    │
                                    │ symbol
                                    ▼
                             stock_master
                              symbol UNIQUE
                                    │
                                    │ symbol FK
                                    ▼
                          provider_symbol_map
                           (symbol, provider) UNIQUE

market_refresh_run
       │
       │ refresh_run_id FK (CASCADE)
       ▼
market_refresh_error
```

---

## Migrations

| File | What it does |
|------|-------------|
| `c788e94f3062_add_market_data_store.py` | Creates `market_data_store` (symbol+timeframe PK, object_key, timestamps) |
| `a1b2c3d4e5f6_add_morocco_market_data_tables.py` | Adds `source_provider`+`data_as_of` to market_data_store; creates `stock_master`, `provider_symbol_map`, `market_refresh_run`, `market_refresh_error` |
| `b2c3d4e5f6a7_add_bourse_url_to_stock_master.py` | Adds `bourse_url` column to `stock_master` |
