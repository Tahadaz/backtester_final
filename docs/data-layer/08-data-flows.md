# Data Layer — End-to-End Data Flows

---

## Flow 1: Excel Upload & Ingestion

```
User drags .xlsx into ExcelUploadDialog
    │
    ▼
Frontend: uploadExcelFile(file)
    → POST /api/market-data/excel (multipart FormData)
    │
    ▼
Next.js Proxy → POST /market-data/excel
    │
    ▼
FastAPI: upload_excel_and_ingest()
    ├─ Validate: non-empty, ≤100 MiB, .xlsx/.xls extension
    ├─ SHA-256 hash the file bytes → data_hash
    ├─ Store raw bytes → S3: datasets/{data_hash}/{filename}
    ├─ Create Dataset row (source="uploaded_file", symbol=filename)
    ├─ Enqueue RQ job: ingest_excel_to_store(dataset_id) on "runs" queue
    └─ Return: { dataset_id, job_id, raw_object_key }
    │
    ▼
Frontend: toast("importé — ingestion en cours")
    └─ After 4s delay: mutateCatalog() to refresh table
    │
    ▼
RQ Worker picks up job: ingest_excel_to_store(dataset_id)
    ├─ Download file from S3
    ├─ Parse Excel workbook
    ├─ For each sheet/symbol:
    │   ├─ Resolve canonical symbol (market_data_store priority, then stock_master)
    │   │   └─ Unknown tickers → skip with error (NOT auto-created)
    │   ├─ Detect format: old BMCE (Ouvt/'+Haut/'+Bas/Clôture) or new (Ouverture/+haut du jour/+bas du jour)
    │   ├─ Rename columns → Open/High/Low/Close/Volume
    │   ├─ Clean French numerics: "1 052,00" → 1052.0
    │   ├─ Standardize: DatetimeIndex, coerce numerics, drop NaN Close, dedup
    │   ├─ Load existing parquet from S3 (if exists)
    │   ├─ Merge: deduplicate by date (keep='last'), only overwrite rows that differ
    │   ├─ Save merged parquet → S3: market_data/{symbol}/1D.parquet
    │   └─ Upsert market_data_store row (source_provider="bmce_excel")
    └─ Save ingest_report.json → S3: market_data/uploads/{dataset_id}/ingest_report.json
    │
    ▼
Frontend: SWR auto-revalidates /market-data/catalog (30s interval)
    └─ Table updates with new data ranges + freshness badges
```

---

## Flow 2: Bourse de Casablanca Refresh (Single Symbol)

```
User clicks refresh button on a row in the data table
    │
    ▼
Frontend: handleBourseRefresh(symbol)
    │
    ├─ Step 1: If symbol not in trackedSet
    │   └─ addTrackedStock({ symbol, track_source: "bourse_direct" })
    │      → POST /market-data/stocks (auto-creates provider_symbol_map entries)
    │      → Silently ignores 409 (already exists)
    │
    └─ Step 2: refreshSingleStock(symbol)
       → POST /market-data/stocks/{symbol}/refresh
       │
       ▼
    FastAPI: trigger_refresh_single()
       ├─ Verify symbol exists in stock_master (404 if not)
       ├─ Create MarketRefreshRun (scope="single", status="queued")
       ├─ Enqueue RQ job: refresh_single_symbol(run_id, symbol) on "market_refresh" queue
       └─ Return: { refresh_run_id, status: "queued" }
       │
       ▼
    Frontend: setActiveRefreshId(refresh_run_id)
       └─ RefreshStatusBar starts polling GET /market-data/refresh/{id} every 2s
       │
       ▼
    RQ Worker picks up job: refresh_single_symbol(run_id, symbol)
       ├─ Set MarketRefreshRun status → "running"
       ├─ Resolve provider_symbol via provider_symbol_map
       │   (fallback: {symbol}.CS for yahoo, {symbol} for bourse_direct)
       ├─ Pick adapter based on stock.track_source:
       │   ├─ "bourse_direct" → BourseDirectAdapter or BDCSessionAdapter
       │   └─ "yahoo" → YFinanceMoroccoAdapter
       ├─ Incremental fetch: from market_data_store.end_ts + 1 day → today
       ├─ Validate OHLCV integrity (High ≥ max(O,C), Low ≤ min(O,C), Low ≥ 0)
       ├─ Load existing parquet + merge (overwrite_if_different)
       ├─ Save merged parquet → S3: market_data/{symbol}/1D.parquet
       ├─ Upsert market_data_store row
       └─ Set status → "succeeded" (or log error → "failed")
       │
       ▼
    Frontend: useRefreshRun poll detects status != "queued"/"running"
       └─ RefreshStatusBar shows "Terminé" or "Échec"
       └─ SWR revalidates catalog → table updates
```

---

## Flow 3: Bulk Refresh (All Tracked Stocks)

```
User clicks "Mettre à jour via Bourse" header button
    │
    ▼
Frontend: handleRefreshAll()
    → refreshAllStocks() → POST /market-data/refresh
    │
    ▼
FastAPI: trigger_refresh_all()
    ├─ Count active stocks in stock_master → symbols_total
    ├─ Create MarketRefreshRun (scope="all", status="queued")
    ├─ Enqueue: refresh_all_tracked_symbols(run_id) on "market_refresh" queue
    └─ Return: { refresh_run_id, symbols_total }
    │
    ▼
Frontend: RefreshStatusBar polls progress (symbols_done / symbols_total)
    │
    ▼
Worker: refresh_all_tracked_symbols(run_id)
    ├─ Set status → "running"
    ├─ Query stock_master WHERE is_active=TRUE
    ├─ For each symbol (sequential):
    │   ├─ Call _do_refresh_symbol()
    │   ├─ On success: increment symbols_done, commit
    │   └─ On error: log to market_refresh_error, increment symbols_failed, commit
    └─ Final status:
        ├─ "succeeded" — 0 failures
        ├─ "partial" — some failures
        └─ "failed" — all failed
    │
    ▼
Frontend: progress bar hits 100%, shows final status badge
```

---

## Flow 4: Data Catalog View

```
User navigates to /data
    │
    ▼
Frontend: useMarketCatalog() → SWR fetcher
    → GET /api/market-data/catalog
    │
    ▼
Next.js Proxy → GET /market-data/catalog
    │
    ▼
FastAPI: get_market_catalog()
    ├─ Query 1: SELECT market_data_store.*, stock_master.*
    │           FROM market_data_store
    │           LEFT JOIN stock_master ON market_data_store.symbol = stock_master.symbol
    │           (all symbols that have canonical OHLCV data)
    │
    ├─ Query 2: SELECT stock_master.*
    │           FROM stock_master
    │           WHERE NOT EXISTS (market_data_store row for this symbol)
    │           (tracked symbols with no data yet)
    │
    ├─ Union both, compute derived flags:
    │   is_tracked = (stock_master row exists)
    │   has_canonical_data = (market_data_store row exists)
    │   is_stale = (data_as_of < 2 business days ago)
    │
    └─ Return: list[MarketCatalogRowOut]
    │
    ▼
Frontend: renders table with rows, freshness badges, action buttons
    └─ SWR auto-revalidates every 30s + on window focus
```

---

## Flow 5: Bourse Metadata Lookup (Auto-Fill)

```
User opens StockDetailPanel → clicks "Auto-remplir depuis Bourse"
    │
    ▼
Frontend: bourseLookupStock(symbol)
    → GET /market-data/stocks/{symbol}/bourse-lookup
    │
    ▼
FastAPI:
    ├─ Build URL from template: casablanca-bourse.com/...?valeur={symbol}
    ├─ HTTP GET the Bourse stock page
    ├─ Regex parse HTML:
    │   ├─ <title> → display_name (strip " - Bourse de Casablanca")
    │   ├─ /MA[A-Z0-9]{10}/ → ISIN
    │   └─ /Secteur:/ → sector
    └─ Return: { symbol, bourse_url, display_name, sector, isin, found: true }
    │
    ▼
Frontend: auto-fills empty form fields (display_name, sector, isin, bourse_url)
    └─ User must click "Save" to persist
    └─ handleSave() → addTrackedStock() or updateTrackedStock()
```

---

## Flow 6: SMA Technical Study

```
POST /market-data/technical-study/sma
    Body: { symbols: ["ATW","BCP"], windows: [5,10,20,50,200] }
    │
    ▼
FastAPI: sma_technical_study()
    │
    For each symbol:
    │
    ├─ Step 1: Load close price series
    │   ├─ Priority: market_data_store → load parquet from S3
    │   └─ Fallback: latest dataset for symbol → load Excel sheet from S3
    │
    ├─ Step 2: For each SMA window
    │   ├─ Compute: SMA(close, window)
    │   ├─ Signal: close > SMA → BUY (+1), close < SMA → SELL (-1), else HOLD (0)
    │   └─ Skip if insufficient data (< window bars)
    │
    └─ Step 3: Consensus
        ├─ Majority vote across all windows → consensus_signal (BUY/SELL/HOLD)
        ├─ score_pct = agreement_count / directional_windows * 100
        └─ Return: consensus + per-window variations
```

---

## Flow 7: OHLCV Preview (Detail Panel)

```
User clicks Eye icon on a row → StockDetailPanel opens
    │
    ▼
Frontend: useStockOhlcvPreview(symbol, { limit: 60 })
    → GET /market-data/stocks/{symbol}/ohlcv-preview?limit=60
    │
    ▼
FastAPI: get_ohlcv_preview()
    ├─ Look up market_data_store row by (symbol, "1D")
    │   └─ 404 if not found (panel shows "Aucune donnée disponible")
    ├─ Load parquet from S3 via object_key
    ├─ Normalize DatetimeIndex
    ├─ Take last N bars (sorted ascending)
    └─ Return: { symbol, timeframe, bars: [...], source_provider, data_as_of, row_count }
    │
    ▼
Frontend: OhlcvMiniChart renders Close prices as line chart
```
