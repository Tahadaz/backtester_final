# 08 — End-to-End Data Flows

---

## Flow 1: Excel Upload & Ingestion

```
USER clicks "Importer Excel" button
  │
  ▼
ExcelUploadDialog opens
  │ Shows format reference (canonical fields, aliases, numeric examples)
  │ from GET /market-data/upload-format-reference
  │
  ▼
USER selects .xlsx/.xls file
  │
  ▼
Frontend: uploadExcelFile(file) → POST /market-data/excel (multipart)
  │
  ▼
API validates:
  │ ✓ Extension (.xlsx or .xls)
  │ ✓ Size (≤ DATASET_MAX_UPLOAD_BYTES)
  │ ✓ SHA256 hash → datasets/{hash}/{filename}
  │ ✓ Detect symbols from sheet names (filter FEUIL1/SHEET1/etc.)
  │
  ▼
API creates Dataset row in DB
  │
  ▼
API enqueues RQ job: ingest_excel_to_store(dataset_id)
  │ Returns: {dataset_id, job_id}
  │
  ▼
Frontend polls: waitForIngestCompletion(dataset_id)
  │ GET /market-data/uploads/{dataset_id}/status every 1.5s (30s timeout)
  │ API checks S3 for ingest_report.json → "processing" or "done"
  │
  ▼ (meanwhile, in worker)
Worker: ingest_excel_to_store(dataset_id)
  │
  ├─ Download Excel from S3
  ├─ For each detected symbol:
  │   ├─ Resolve canonical symbol (UPPER, auto-create stock if new)
  │   ├─ Load sheet (case-insensitive match)
  │   ├─ Detect format (bmce_new / bmce_old / investing)
  │   ├─ Rename columns to canonical (Date, Open, High, Low, Close, Volume)
  │   ├─ Parse dates (day-first or month-first with disambiguation)
  │   ├─ Parse numbers (French "1 052,00" or English "1,052.00")
  │   ├─ Standardize OHLCV (validate, drop NaN, drop future dates)
  │   ├─ Load existing parquet (if any)
  │   ├─ Merge: overwrite-if-different
  │   ├─ Save merged parquet to S3
  │   └─ Upsert market_data_store row
  │
  └─ Write ingest_report.json to S3
       Per-symbol: status, row_count, detected_format, matched_aliases, errors
  │
  ▼
Frontend receives "done" status
  │ Displays SymbolResultRow per symbol: ✓ success or ✗ error
  │ Toast: "{N} symbole(s) importés avec succès"
  │
  ▼
SWR auto-revalidates catalog (30s) → table updates with new data
```

---

## Flow 2: Bourse de Casablanca Refresh (All Symbols)

```
USER clicks "Mettre à jour via Bourse" button
  │
  ▼
Frontend: refreshAllStocks() → POST /market-data/refresh
  │ Body: {timeframe: "1D"}
  │
  ▼
API creates MarketRefreshRun (status="queued")
  │ Counts is_active=true stocks → symbols_total
  │ Enqueues RQ: refresh_all_tracked_symbols(run_id)
  │ Returns: {refresh_run_id, status, symbols_total}
  │
  ▼
Frontend shows RefreshStatusBar
  │ useRefreshRun(refreshRunId) — polls every 2s
  │ Shows: "Mise à jour en cours… {done}/{total}" + progress bar
  │
  ▼ (in worker)
Worker: refresh_all_tracked_symbols(run_id)
  │ Sets status → "running"
  │
  ├─ For each active stock:
  │   ├─ Resolve provider_symbol from provider_symbol_map
  │   ├─ Select adapter:
  │   │   └─ Yahoo: YFinanceMoroccoAdapter({sym}.CS)
  │   │   └─ Bourse: BourseDirectAdapter or BDCSessionAdapter
  │   ├─ Determine start date:
  │   │   └─ Session adapter: re-fetch last day
  │   │   └─ Historical adapter: end_ts + 1 day
  │   ├─ Fetch OHLCV from provider
  │   ├─ Validate & merge with existing parquet
  │   ├─ Upsert market_data_store
  │   ├─ Update progress: symbols_done++
  │   └─ On error: log to market_refresh_error, symbols_failed++
  │
  └─ Final status: "succeeded" / "partial" / "failed"
  │
  ▼
RefreshStatusBar shows completion
  │ ✓ "Mise à jour terminée" or ✗ error message
  │
  ▼
SWR revalidates catalog → freshness badges update
```

---

## Flow 3: Single-Symbol Refresh

```
USER clicks per-row RefreshCw button
  │
  ▼
Frontend: handleBourseRefresh(symbol)
  │ If not tracked: auto-add via addTrackedStock(symbol, "bourse_direct")
  │ Then: refreshSingleStock(symbol) → POST /market-data/stocks/{symbol}/refresh
  │
  ▼
Same as all-symbols flow but for one symbol only
  │ RefreshStatusBar tracks progress
```

---

## Flow 4: Add Stock from MASI Registry

```
USER clicks "Ajouter un titre"
  │
  ▼
AddStockDialog opens
  │ Shows searchable list of 93 MASI tickers (from useMasiTickers())
  │ Already-existing symbols shown disabled with green checkmark
  │
  ▼
USER selects a ticker
  │
  ▼
Frontend: addTrackedStock({symbol, track_source: "manual"})
  │ POST /market-data/stocks
  │
  ▼
API:
  ├─ Auto-fills display_name/sector from MASI registry
  ├─ Creates stock_master row
  ├─ Creates provider_symbol_map: yahoo ({sym}.CS) + bourse_direct ({sym})
  │
  ▼
Toast: "{symbol} — {display_name} ajouté"
  │ SWR mutates catalog → new row appears in table (no data yet)
```

---

## Flow 5: View Stock Detail

```
USER clicks row or Eye button → setSelectedSymbol(symbol)
  │
  ▼
StockDetailPanel opens (modal, 95vh height)
  │
  ├─ useStockOhlcvHistory(symbol) → Full OHLCV for candlestick chart
  ├─ useStockOhlcvPreview(symbol, limit=10) → Last 10 bars table
  ├─ useStockAvailabilityCalendar(symbol) → Per-day coverage
  │
  ▼
Renders (top to bottom):
  1. Header: symbol, badges, history metadata
  2. QuickFacts: Début, Fin, Barres, Source
  3. Candlestick chart (Plotly) with volume bars
  4. Year strip overview (month summaries by year)
  5. Availability calendar grid (7-col, per-day states)
  6. Data quality report (partial/missing diagnostics)
  7. Last 10 OHLCV bars table
```

---

## Flow 6: Delete Symbol

```
USER clicks Trash2 button → setDeleteTarget(row)
  │
  ▼
AlertDialog: "Supprimer ce symbole ?"
  │ Warning: deletes tracked stock AND canonical data
  │
  ▼
USER confirms
  │
  ▼
Frontend: deleteMarketSymbol(symbol) → DELETE /market-data/symbols/{symbol}
  │
  ▼
API cascade deletes:
  ├─ market_data_store row
  ├─ provider_symbol_map rows
  ├─ stock_master row
  └─ Best-effort S3 cleanup (delete parquet)
  │
  ▼
Toast: "{symbol} supprimé du catalogue"
  │ If selectedSymbol === symbol: close detail panel
  │ SWR mutates catalog → row disappears
```

---

## Flow 7: Scheduled Daily Refresh

```
APScheduler CronTrigger fires at 18:00 Africa/Casablanca (Mon–Fri)
  │ (scheduler.py → _enqueue_daily_refresh())
  │
  ▼
Creates MarketRefreshRun (trigger_source="scheduled")
  │
  ▼
Enqueues RQ: refresh_all_tracked_symbols(run_id)
  │
  ▼
Same as Flow 2 (worker processing)
  │ No frontend feedback (runs in background)
  │ Status visible via GET /market-data/refresh (list runs)
```

**Configuration**: Disabled by setting `MARKET_REFRESH_CRON_ENABLED=0`. Default: enabled.
