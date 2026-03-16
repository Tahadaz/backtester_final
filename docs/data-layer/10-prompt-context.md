# Data Layer — LLM Prompt Context Blocks

Pre-built context blocks you can paste into an LLM to perform specific data layer tasks. Each block is self-contained with the file paths, types, and architectural constraints needed.

---

## Context Block 1: Add a New Backend Endpoint

Use when: you need to add a new endpoint to the market data router.

```
### Architecture Context — Market Data Router

File: services/api/app/routers/market_data.py
Router prefix: /market-data
DB session: Depends(get_db) → SQLAlchemy Session

Models (services/api/app/models.py):
- MarketDataStore: PK=(symbol, timeframe), fields: object_key, start_ts, end_ts, row_count, source_provider, data_as_of
- StockMaster: PK=id(UUID), UNIQUE=symbol, fields: display_name, isin, sector, is_active, track_source, bourse_url, notes
- ProviderSymbolMap: UNIQUE=(symbol, provider), fields: provider_symbol, confidence, is_verified
- MarketRefreshRun: PK=id(UUID), fields: scope, status, symbols_total/done/failed, meta_json
- MarketRefreshError: FK=refresh_run_id (CASCADE), fields: symbol, error_type, error_message

Schemas (services/api/app/schemas/market_data.py):
- Input: StockMasterCreate, StockMasterUpdate, ProviderSymbolMapUpdate, MarketRefreshTriggerRequest
- Output: StockMasterOut, ProviderSymbolMapOut, MarketRefreshRunOut, MarketHealthOut, MarketCatalogRowOut, OhlcvPreviewOut, BourseStockLookupOut

S3 helpers: put_bytes(object_key, data, content_type), get_bytes(object_key), presign_get(object_key, expires)
Key builder: build_market_store_object_key(symbol, timeframe) → "market_data/{symbol}/{timeframe}.parquet"

Queue: get_market_refresh_queue() for async jobs on "market_refresh" queue
Enqueue pattern: q.enqueue("services.worker.tasks.refresh_market_data.task_name", arg1, arg2)

Existing endpoints: /catalog, /symbols, /health, /stocks CRUD, /stocks/{s}/bourse-lookup, /stocks/{s}/ohlcv-preview, /excel, /refresh, /refresh/{id}, /technical-study/sma
```

---

## Context Block 2: Add a New Frontend Component to /data

Use when: you need to add a new UI component to the data page.

```
### Architecture Context — Data Page Frontend

Page: quant-backtesting-frontend/app/data/page.tsx (client component, "use client")
Components dir: quant-backtesting-frontend/components/data/

Available hooks (hooks/use-api.ts):
- useMarketCatalog() → MarketCatalogRow[] (30s refresh)
- useTrackedStocks(params?) → StockMaster[] (60s refresh)
- useRefreshRun(id) → MarketRefreshRun (2s poll while active)
- useMarketHealth() → MarketHealth (30s refresh)
- useStockOhlcvPreview(symbol, {limit}) → OhlcvPreview (on-demand)
- useDatasets() → Dataset[] (15s refresh)
- useMarketSymbols(params?) → MarketSymbolRow[] (30s refresh)

Available API functions (lib/api.ts):
- listMarketCatalog(), listTrackedStocks(), addTrackedStock(body), updateTrackedStock(symbol, body)
- bourseLookupStock(symbol), getStockOhlcvPreview(symbol, params)
- uploadExcelFile(file), refreshAllStocks(body?), refreshSingleStock(symbol, body?)
- getRefreshRun(id), listRefreshRuns(params?), getMarketHealth()

Key types:
- MarketCatalogRow: { symbol, display_name, isin, sector, is_active, track_source, bourse_url, start_ts, end_ts, row_count, source_provider, data_as_of, is_stale, is_tracked, has_canonical_data }
- StockMaster: { symbol, display_name, isin, sector, is_active, track_source, bourse_url, start_ts, end_ts, row_count, is_stale }
- MarketRefreshRun: { id, status, scope, symbols_total, symbols_done, symbols_failed }
- OhlcvPreview: { symbol, timeframe, bars: OhlcvBar[], source_provider, data_as_of, row_count }

UI framework: shadcn/ui (Card, Table, Badge, Button, Sheet, Dialog, Skeleton, Tooltip, Progress, Select, Input, Label, Separator)
Icons: lucide-react
Toast: sonner (toast.success/error)
Charts: recharts (LineChart)
Language: French (all UI labels in French)

Existing components: StockDetailPanel, ExcelUploadDialog, FreshnessBadge, HealthCards, RefreshStatusBar, OhlcvMiniChart, AddStockDialog, StockTable
Unused but available: HealthCards, AddStockDialog, StockTable (not imported by page)
```

---

## Context Block 3: Add a New Data Source Adapter

Use when: you need to add a new adapter to fetch OHLCV from a new provider.

```
### Architecture Context — Data Source Adapters

File: core/quant_core/data.py

Base class:
class BaseDataSource:
    def __init__(self, timezone="GMT", cache_dir=None, use_cache=True)
    def load(self, symbols, start=None, end=None, interval="1d", align=False, align_how="inner", fill_method=None, **kwargs) -> MarketData
    def _load_impl(self, symbols, start, end, interval, **kwargs) -> Dict[str, pd.DataFrame]  # IMPLEMENT THIS

MarketData = dataclass(bars: Dict[str, pd.DataFrame], source: str, timezone: str, interval: str, meta: dict)

DataFrame contract:
- Index: DatetimeIndex (will be normalized by _standardize_ohlcv)
- Required columns: Open, High, Low, Close (case-insensitive, will be renamed)
- Optional columns: Volume, Adj Close

Normalization pipeline (automatic, called by base load()):
1. _standardize_ohlcv(df, tz) — DatetimeIndex, column rename, numeric coercion, dedup
2. _validate_ohlcv(df) — integrity checks (High >= max(O,C), Low <= min(O,C), Low >= 0)
3. slice_date_range(df, start, end) — filter by requested date range

Existing adapters:
- BMCEDataSource: local CSV/Excel files (BMCE column format)
- YahooFinanceDataSource: yfinance.download()
- YFinanceMoroccoAdapter(YahooFinanceDataSource): auto-appends .CS suffix
- BourseDirectAdapter: HTTP download from Bourse de Casablanca
- BDCSessionAdapter: scrapes live session from Bourse instrument page
- ParquetDataSource: reads parquet files

Symbol normalization: normalize_symbol(raw) → uppercase, strip exchange suffixes (.CS, .MA, .BVC)

To register for use in refresh worker:
- Add adapter selection logic in services/worker/tasks/refresh_market_data.py → _do_refresh_symbol()
- Match on stock_master.track_source value
```

---

## Context Block 4: Add a New Worker Task

Use when: you need to add a new async processing task.

```
### Architecture Context — Worker Tasks

Worker files:
- services/worker/tasks/ingest_market_data.py (Excel ingestion)
- services/worker/tasks/refresh_market_data.py (Bourse/Yahoo refresh)

Queue setup:
- API enqueues via: get_queue() for "runs" queue, get_market_refresh_queue() for "market_refresh" queue
- Enqueue: q.enqueue("services.worker.tasks.module_name.function_name", arg1, arg2)
- Worker config: services/worker/config.py → WORKER_QUEUES tuple must include the queue name

DB access in worker:
- from services.worker.db import get_db_session
- with get_db_session() as db: ...
- Models: from services.api.app import models

S3 access in worker:
- from core.quant_core.s3_keys import build_market_store_object_key
- put_bytes(object_key, data, content_type) / get_bytes(object_key)

Key patterns:
- Create a tracking row in API (e.g. MarketRefreshRun), pass its ID to worker
- Worker updates status: queued → running → succeeded/failed
- Worker logs per-item errors to a separate table
- Frontend polls the tracking row for progress

Data source adapters: import from core.quant_core.data (BMCEDataSource, YFinanceMoroccoAdapter, etc.)
Parquet merge: _merge_overwrite_if_different(old_df, new_df) → (merged_df, summary_dict)
Upsert market store: _upsert_market_data_store(db, symbol, timeframe, object_key, start_ts, end_ts, row_count, source_provider)
```

---

## Context Block 5: Add a New Database Migration

Use when: you need to add or modify database tables.

```
### Architecture Context — Database Migrations

Migration dir: services/api/alembic/versions/
Models file: services/api/app/models.py

Create migration:
  cd services/api
  alembic revision --autogenerate -m "description"

Apply: alembic upgrade head
Rollback: alembic downgrade -1

Existing data layer tables:
- market_data_store: PK=(symbol, timeframe). Canonical OHLCV metadata + S3 pointer.
- stock_master: PK=id(UUID), UNIQUE=symbol. Tracked stock registry.
- provider_symbol_map: FK=symbol→stock_master.symbol, UNIQUE=(symbol, provider). Ticker mappings.
- market_refresh_run: PK=id(UUID). Refresh job tracking.
- market_refresh_error: FK=refresh_run_id→market_refresh_run.id (CASCADE). Per-symbol errors.
- dataset: PK=id(UUID). Uploaded file metadata.

Column conventions:
- UUIDs: server_default=text("gen_random_uuid()")
- Timestamps: server_default=func.now(), TIMESTAMPTZ
- JSON: JSONB type, default={}
- Indexes: name pattern ix_{table}_{column}

If adding columns to stock_master or market_data_store:
- Update the corresponding Pydantic schema in services/api/app/schemas/market_data.py
- Update the /catalog endpoint query to include the new column
- Update the frontend MarketCatalogRowSchema in lib/api.ts
```

---

## Context Block 6: Modify the Ingestion Pipeline

Use when: you need to change how Excel files are parsed or how data is ingested.

```
### Architecture Context — Excel Ingestion Pipeline

File: services/worker/tasks/ingest_market_data.py
Entry point: ingest_excel_to_store(dataset_id: str)

Pipeline stages per symbol:
1. Ticker resolution: _resolve_canonical_symbol(db, symbol) → market_data_store priority, then stock_master
2. Sheet loading: case-insensitive sheet name match
3. Column detection: _detect_and_rename_columns(df) → old BMCE format or new format
4. French numerics: _clean_french_numeric_series(s) → "1 052,00" → 1052.0
5. Standardization: _standardize_ohlcv(df) from core/quant_core/data.py
6. Merge: _merge_overwrite_if_different(old_df, new_df) — only overwrite rows that differ
7. Save: parquet to S3 at market_data/{symbol}/1D.parquet
8. Upsert: market_data_store row (source_provider="bmce_excel")
9. Report: per-symbol entry saved to ingest_report.json

Old BMCE columns: Ouvt, '+Haut, '+Bas, Clôture, Volume
New BMCE columns: Séance, Ouverture, Dernier Cours, +haut du jour, +bas du jour, Nombre de titres échangés

Column matching is normalized: lowercase + collapse whitespace

French number patterns:
- "1 052,00" → 1052.0 (space thousands + comma decimal)
- Mojibake variants: \xa0 (non-breaking space)

Unknown tickers are rejected (not auto-created in stock_master).
Merge strategy: deduplicate by DatetimeIndex (keep='last'), only overwrite if OHLCV values differ.
```
