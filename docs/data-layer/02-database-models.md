# 02 — Database Models

## Tables

### stock_master

Registry of all tracked symbols. A symbol exists here before it has any OHLCV data.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID (PK) | Auto-generated |
| symbol | VARCHAR (unique) | UPPERCASE canonical name (e.g., "ATW", "BCP") |
| display_name | VARCHAR (nullable) | Human-readable (e.g., "Attijariwafa Bank") |
| isin | VARCHAR (nullable) | International Securities Identification Number |
| sector | VARCHAR (nullable) | "Banques", "BTP", "Mines", "Assurances", etc. |
| market_cap_class | VARCHAR (nullable) | Size classification |
| is_active | BOOLEAN (default true) | Active = eligible for refresh |
| track_source | VARCHAR (nullable) | "manual", "bourse_direct", "excel_ingest" |
| bourse_url | VARCHAR (nullable) | Bourse de Casablanca detail page URL |
| notes | TEXT (nullable) | Free-form notes |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

**Auto-population**: On creation, if the symbol is a known MASI ticker (`masi_tickers.py`), `display_name` and `sector` are auto-filled.

### market_data_store

One row per (symbol, timeframe). Points to canonical parquet file in S3.

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL (PK) | |
| symbol | VARCHAR | UPPERCASE |
| timeframe | VARCHAR | Always "1D" currently |
| object_key | VARCHAR | S3 path: `market_data_store/{symbol}/1D` |
| start_ts | TIMESTAMP | First bar date |
| end_ts | TIMESTAMP | Last bar date |
| row_count | INTEGER | Number of OHLCV bars |
| last_dataset_id | UUID (nullable, FK) | Last dataset that contributed data |
| source_provider | VARCHAR | "bmce_excel", "yahoo", "bourse_direct" |
| data_as_of | TIMESTAMP | When data was last updated |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

**Unique**: (symbol, timeframe).

### provider_symbol_map

Maps canonical symbols to provider-specific identifiers.

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL (PK) | |
| symbol | VARCHAR (FK) | References stock_master |
| provider | VARCHAR | "yahoo" or "bourse_direct" |
| provider_symbol | VARCHAR | e.g., "ATW.CS" (Yahoo), "ATW" (Bourse) |
| confidence | FLOAT | 0.0–1.0 |
| is_verified | BOOLEAN | User-confirmed mapping |
| override_reason | TEXT (nullable) | |
| created_at | TIMESTAMP | |

**Unique**: (symbol, provider). Auto-created on stock registration: yahoo `{sym}.CS` (0.9), bourse_direct `{sym}` (1.0).

### market_refresh_run

Tracks each refresh operation.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID (PK) | |
| trigger_source | VARCHAR | "user_all", "user_single", "scheduled" |
| scope | VARCHAR | "all" or "single" |
| symbol | VARCHAR (nullable) | Only for single-symbol refresh |
| timeframe | VARCHAR | "1D" |
| status | VARCHAR | "queued" → "running" → "succeeded" / "partial" / "failed" |
| rq_job_id | VARCHAR (nullable) | |
| symbols_total | INTEGER (nullable) | |
| symbols_done | INTEGER (nullable) | |
| symbols_failed | INTEGER (nullable) | |
| started_at | TIMESTAMP (nullable) | |
| finished_at | TIMESTAMP (nullable) | |
| created_at | TIMESTAMP | |
| error_message | TEXT (nullable) | |
| meta_json | JSONB (nullable) | |

### market_refresh_error

Per-symbol error log within a refresh run.

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL (PK) | |
| refresh_run_id | UUID (FK) | |
| symbol | VARCHAR | |
| provider | VARCHAR | |
| error_type | VARCHAR | e.g., "adapter_error", "validation_error" |
| error_message | TEXT | Capped at 4,000 chars |
| raw_response | TEXT (nullable) | Capped at 2,000 chars |
| created_at | TIMESTAMP | |

### dataset

Records each uploaded file.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID (PK) | |
| source | VARCHAR | "upload" |
| symbol | VARCHAR (nullable) | May be null for multi-symbol Excel |
| timeframe | VARCHAR | "1D" |
| data_hash | VARCHAR | SHA256 of file content |
| filename | VARCHAR | Original filename |
| content_type | VARCHAR | MIME type |
| object_key | VARCHAR | S3: `datasets/{hash}/{filename}` |
| size_bytes | INTEGER | |
| meta_json | JSONB | `{detected_symbols, format_info}` |
| created_at | TIMESTAMP | |

## Catalog View

The `/market-data/catalog` endpoint produces a virtual full-outer-join:

- **Arm 1**: market_data_store LEFT JOIN stock_master → symbols with data
- **Arm 2**: stock_master minus data symbols → tracked but never ingested

Result: `MarketCatalogRowOut` with fields from both tables + derived flags (`is_tracked`, `has_canonical_data`, `market`).
