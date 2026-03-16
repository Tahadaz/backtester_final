# Data Page — Complete Reference

**Route**: `/data`
**Purpose**: Manage Moroccan market OHLCV data — view all symbols, upload Excel files, trigger Bourse de Casablanca refresh, and edit per-stock metadata.

---

## Table of Contents

1. [File Map](#file-map)
2. [Data Flow](#data-flow)
3. [Database Tables](#database-tables)
4. [Backend API Endpoints](#backend-api-endpoints)
5. [Frontend Types & Schemas (Zod)](#frontend-types--schemas-zod)
6. [API Client Functions](#api-client-functions)
7. [SWR Hooks](#swr-hooks)
8. [Next.js Proxy](#nextjs-proxy)
9. [Page Component: `app/data/page.tsx`](#page-component)
10. [Component: `stock-table.tsx`](#component-stock-table)
11. [Component: `stock-detail-panel.tsx`](#component-stock-detail-panel)
12. [Component: `freshness-badge.tsx`](#component-freshness-badge)
13. [Component: `health-cards.tsx`](#component-health-cards)
14. [Component: `refresh-status-bar.tsx`](#component-refresh-status-bar)
15. [Component: `add-stock-dialog.tsx`](#component-add-stock-dialog)
16. [Component: `ohlcv-mini-chart.tsx`](#component-ohlcv-mini-chart)
17. [Component: `excel-upload-dialog.tsx`](#component-excel-upload-dialog)
18. [Worker Tasks](#worker-tasks)
19. [Key Logic & Gotchas](#key-logic--gotchas)
20. [Sector List](#sector-list)
21. [Environment Variables](#environment-variables)

---

## File Map

```
Frontend
├── app/data/page.tsx                          ← Main page (client component)
├── app/api/[...path]/route.ts                 ← Next.js reverse proxy to FastAPI
├── components/data/
│   ├── stock-table.tsx                        ← Table of all symbols (NOT used by page directly — logic is inlined)
│   ├── stock-detail-panel.tsx                 ← Slide-out sheet: view/edit stock metadata
│   ├── freshness-badge.tsx                    ← Green/amber/red staleness badge
│   ├── health-cards.tsx                       ← 4 summary stat cards (requires /health endpoint)
│   ├── refresh-status-bar.tsx                 ← Live progress bar for active refresh run
│   ├── add-stock-dialog.tsx                   ← Dialog to add a new stock to stock_master
│   ├── ohlcv-mini-chart.tsx                   ← Recharts line chart of Close prices
│   └── excel-upload-dialog.tsx                ← Drag-and-drop Excel upload dialog
├── hooks/use-api.ts                           ← All SWR hooks
└── lib/api.ts                                 ← All Zod schemas + API client functions

Backend
├── services/api/app/routers/market_data.py    ← All /market-data/* endpoints
├── services/api/app/models.py                 ← SQLAlchemy ORM models
├── services/api/app/schemas/market_data.py    ← Pydantic response schemas
├── services/api/app/queue.py                  ← get_market_refresh_queue()
├── services/worker/config.py                  ← WORKER_QUEUES (must include "market_refresh")
├── services/worker/tasks/refresh_market_data.py ← RQ worker tasks
└── services/api/alembic/versions/
    ├── a1b2c3d4e5f6_add_morocco_market_data_tables.py   ← Creates stock_master etc.
    └── b2c3d4e5f6a7_add_bourse_url_to_stock_master.py   ← Adds bourse_url column
```

> **Note**: `stock-table.tsx` exists as a standalone component but **the page does not import it**. The page has its own inline table implementation. `StockTable` is unused in the current `/data` page — it was the original design before the unified `MergedRow` approach was adopted.

---

## Data Flow

### How symbols get onto the page

The page merges **two data sources** into one `MergedRow[]` list:

```
Source 1: market_data_store table
  → GET /market-data/symbols
  → useMarketSymbols() SWR hook
  → storeSymbols: MarketSymbolRow[]
  Contains: symbols that have been fully ingested into S3 parquet

Source 2: dataset table
  → GET /datasets
  → useDatasets() SWR hook
  → datasets: Dataset[]
  Contains: uploaded Excel files + their detected symbol lists

Merge logic (in page.tsx useMemo):
  1. Seed map from storeSymbols (these have real OHLCV data)
  2. For each dataset (sorted newest-first), extract symbols via getDatasetSymbols()
     - If symbol not in map → add with storeRow: null, datasetFilename from this dataset
     - If symbol already in map → record datasetFilename only if not already set
  3. Sort alphabetically → MergedRow[]

A MergedRow has:
  - symbol: string
  - storeRow: MarketSymbolRow | null   (null = uploaded but not yet ingested)
  - datasetFilename: string | null      (filename of most recent dataset with this symbol)
  - datasetId: string | null
```

### How OHLCV gets into the system

**Path 1 — Manual Excel upload**:
```
User → ExcelUploadDialog → POST /market-data/excel (multipart)
→ FastAPI saves file to MinIO at datasets/{data_hash}/{filename}
→ Enqueues RQ job: ingest_excel_to_store(dataset_id)
→ Worker: parses BMCE/Casablanca Excel format → parquet → MinIO
→ Upserts market_data_store row (symbol, timeframe="1D", object_key, start_ts, end_ts, row_count)
```
After upload: `onUploaded()` mutates datasets immediately, then mutates storeSymbols after 4s delay (to let the worker finish).

**Path 2 — Bourse de Casablanca refresh**:
```
User → handleBourseRefresh(symbol) or handleRefreshAll()
→ If symbol not in stock_master: auto-calls addTrackedStock({symbol, track_source:"bourse_direct"})
→ POST /market-data/stocks/{symbol}/refresh  (or /market-data/refresh for all)
→ FastAPI creates MarketRefreshRun row (status="queued")
→ Enqueues RQ job to "market_refresh" queue:
    refresh_single_symbol(run_id, symbol, timeframe, source)
    or refresh_all_tracked_symbols(run_id, timeframe, ...)
→ Worker: fetches data from Bourse de Casablanca or Yahoo Finance
→ Merges with existing parquet, re-uploads to MinIO
→ Upserts market_data_store with new end_ts, row_count, source_provider, data_as_of
→ Updates market_refresh_run status: queued → running → succeeded/partial/failed
Frontend polls GET /market-data/refresh/{id} every 2s while status is queued/running
```

---

## Database Tables

### `market_data_store` (existing, extended)
Composite PK: `(symbol, timeframe)`

| Column | Type | Notes |
|--------|------|-------|
| symbol | VARCHAR | e.g. "ATW" |
| timeframe | VARCHAR | always "1D" for this page |
| object_key | VARCHAR | MinIO path: `market_data/symbols/{SYMBOL}/ohlcv.parquet` |
| start_ts | TIMESTAMPTZ | earliest bar date |
| end_ts | TIMESTAMPTZ | latest bar date — drives freshness display |
| row_count | INTEGER | total bars |
| source_provider | VARCHAR | "bourse_direct" \| "yahoo" \| "bmce_excel" (nullable, added by migration) |
| data_as_of | DATE | denormalized copy of end_ts.date() (nullable, added by migration) |
| updated_at | TIMESTAMPTZ | |

### `stock_master` (new)
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| symbol | VARCHAR | UNIQUE, e.g. "ATW" |
| display_name | VARCHAR | e.g. "Attijariwafa Bank" |
| isin | VARCHAR | e.g. "MA0000011926" |
| sector | VARCHAR | see Sector List below |
| market_cap_class | VARCHAR | "large"\|"mid"\|"small" (not used in UI yet) |
| is_active | BOOLEAN | default true; false = stop tracking |
| track_source | VARCHAR | default "bourse_direct"; used by worker to pick adapter |
| bourse_url | VARCHAR | link to Bourse de Casablanca stock page (added by migration b2c3d4e5f6a7) |
| notes | TEXT | free text |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | auto-updates on PATCH |

### `provider_symbol_map` (new)
Maps internal symbol to provider-specific ticker.
Auto-populated when a stock is added: creates `yahoo` row (`ATW.CS`, confidence=0.9) and `bourse_direct` row (`ATW`, confidence=1.0).

| Column | Type | Notes |
|--------|------|-------|
| symbol | VARCHAR | FK → stock_master.symbol |
| provider | VARCHAR | "yahoo" \| "bourse_direct" |
| provider_symbol | VARCHAR | e.g. "ATW.CS" |
| confidence | FLOAT | 0.0–1.0 |
| is_verified | BOOLEAN | default false |

UNIQUE(symbol, provider).

### `market_refresh_run` (new)
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| trigger_source | VARCHAR | "manual" \| "scheduled" |
| scope | VARCHAR | "all" \| "single" |
| symbol | VARCHAR | NULL if scope="all" |
| timeframe | VARCHAR | "1D" |
| status | VARCHAR | "queued" \| "running" \| "succeeded" \| "partial" \| "failed" |
| rq_job_id | VARCHAR | Redis queue job ID |
| symbols_total | INTEGER | |
| symbols_done | INTEGER | |
| symbols_failed | INTEGER | |
| started_at | TIMESTAMPTZ | |
| finished_at | TIMESTAMPTZ | |
| error_message | TEXT | top-level error (not per-symbol) |

### `market_refresh_error` (new)
Per-symbol errors within a refresh run. FK → market_refresh_run ON DELETE CASCADE.

---

## Backend API Endpoints

All endpoints are under prefix `/market-data`, require `x-api-key` header (set by proxy automatically).
**File**: `services/api/app/routers/market_data.py`

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| GET | `/market-data/symbols` | List all ingested symbols (from market_data_store) | 200 |
| POST | `/market-data/excel` | Upload Excel file, trigger ingestion | 200 |
| GET | `/market-data/stocks` | List tracked stocks (stock_master) with freshness | 200 |
| POST | `/market-data/stocks` | Add stock to stock_master | **201** |
| PATCH | `/market-data/stocks/{symbol}` | Update stock metadata | 200 |
| GET | `/market-data/stocks/{symbol}/bourse-lookup` | Scrape Bourse de Casablanca for URL + metadata | 200 |
| GET | `/market-data/stocks/{symbol}/ohlcv-preview` | Last N bars of OHLCV from MinIO | 200 / 404 |
| GET | `/market-data/stocks/{symbol}/mappings` | List provider symbol mappings | 200 |
| PATCH | `/market-data/stocks/{symbol}/mappings/{provider}` | Update provider mapping | 200 |
| POST | `/market-data/refresh` | Trigger refresh for ALL active tracked stocks | **202** |
| POST | `/market-data/stocks/{symbol}/refresh` | Trigger refresh for ONE stock | **202** |
| GET | `/market-data/refresh` | List recent refresh runs | 200 |
| GET | `/market-data/refresh/{id}` | Get single refresh run status | 200 / 404 |
| GET | `/market-data/health` | Health summary counts | 200 |

### Key behaviors

**`GET /market-data/symbols`** — reads `market_data_store` only (not stock_master). Returns symbols that have actual parquet data in MinIO. Fields: `symbol, timeframe, object_key, start_ts, end_ts, row_count, updated_at, source_provider`.

**`GET /market-data/stocks`** — reads `stock_master` LEFT JOINed with `market_data_store` (timeframe="1D"). Returns full `StockMasterOut` including freshness fields. Query param `is_active=true` (default).

**`POST /market-data/stocks`** — `db.flush()` is called after inserting the `stock_master` row before inserting the two `provider_symbol_map` rows. This is critical: without the flush, the FK constraint `provider_symbol_map.symbol → stock_master.symbol` would fail. Returns 409 if symbol already exists.

**`GET /market-data/stocks/{symbol}/bourse-lookup`** — constructs URL from template `BOURSE_STOCK_PAGE_URL` env var (default: `https://www.casablanca-bourse.com/bourseweb/Detail-Valeur.aspx?Cat=3&valeur={symbol}`). Fetches the page, extracts:
- `display_name`: from `<title>` tag, strips " - Bourse de Casablanca" suffix
- `isin`: regex `MA[A-Z0-9]{10}`
- `sector`: regex on "Secteur:" pattern
Always returns a `bourse_url` even if scraping fails (silently caught). `found` is always `true`.

**`POST /market-data/refresh`** — creates a `market_refresh_run` row, enqueues job to `market_refresh` RQ queue. Returns immediately with `refresh_run_id`.

**`POST /market-data/stocks/{symbol}/refresh`** — requires symbol to exist in `stock_master`. The frontend auto-adds it first via `addTrackedStock` if not present.

**Staleness logic** (`_is_stale`): a stock is stale if `data_as_of < 2 business days ago` (Mon–Fri counting only). Used in health endpoint and `StockMasterOut.is_stale`.

---

## Frontend Types & Schemas (Zod)

**File**: `quant-backtesting-frontend/lib/api.ts`

### `MarketSymbolRow` (line ~1052)
From `GET /market-data/symbols`. Read-only, no editing.
```typescript
{
  symbol: string
  timeframe?: string
  object_key?: string
  start_ts?: string | null        // ISO datetime string
  end_ts?: string | null          // ISO datetime string — used for freshness display
  row_count?: number | null
  updated_at?: string | null
  source_provider?: string | null // "bourse_direct" | "yahoo" | "bmce_excel"
}
```

### `StockMaster` (line ~1190)
From `GET /market-data/stocks` and write operations.
```typescript
{
  symbol: string
  display_name?: string | null
  isin?: string | null
  sector?: string | null
  market_cap_class?: string | null
  is_active: boolean
  track_source: string            // "bourse_direct" | "yahoo"
  bourse_url?: string | null      // direct link to Bourse de Casablanca
  notes?: string | null
  created_at?: string | null
  updated_at?: string | null
  // Freshness (from market_data_store join)
  start_ts?: string | null
  end_ts?: string | null
  row_count?: number | null
  store_updated_at?: string | null
  source_provider?: string | null
  data_as_of?: string | null      // YYYY-MM-DD
  is_stale: boolean               // computed by backend
}
```

### `BourseStockLookup` (line ~1213)
From `GET /market-data/stocks/{symbol}/bourse-lookup`
```typescript
{
  symbol: string
  bourse_url: string              // always present
  display_name?: string | null    // scraped from <title>
  sector?: string | null          // scraped from page content
  isin?: string | null            // scraped MA... pattern
  found: boolean                  // always true currently
}
```

### `MarketRefreshRun` (line ~1235)
```typescript
{
  id: string                      // UUID
  trigger_source: string          // "manual" | "scheduled"
  scope: string                   // "all" | "single"
  symbol?: string | null
  timeframe: string
  status: string                  // "queued"|"running"|"succeeded"|"partial"|"failed"
  rq_job_id?: string | null
  symbols_total?: number | null
  symbols_done?: number | null
  symbols_failed?: number | null
  started_at?: string | null
  finished_at?: string | null
  created_at: string
  error_message?: string | null
  meta_json: Record<string, unknown>
}
```

### `MarketHealth` (line ~1254)
```typescript
{
  total_tracked: number           // active stocks in stock_master
  up_to_date: number              // data_as_of >= 2 biz days ago
  stale: number                   // 2–7 days old
  very_stale: number              // > 7 days old
  never_ingested: number          // in stock_master but no market_data_store row
  last_refresh_run?: MarketRefreshRun | null
  last_successful_refresh?: string | null
}
```

### `OhlcvBar` / `OhlcvPreview`
```typescript
OhlcvBar = { date: string, open?, high?, low?, close?, volume? }
OhlcvPreview = { symbol, timeframe, bars: OhlcvBar[], source_provider?, data_as_of?, row_count? }
```

### `Dataset`
```typescript
{
  id: string
  dataset_id: string
  source?: string
  filename?: string              // e.g. "ATW_2024.xlsx"
  sha256?: string
  created_at?: string
  meta?: unknown                 // contains detected_symbols array
  detected_symbols?: string[]    // parsed at upload time
}
```

---

## API Client Functions

**File**: `quant-backtesting-frontend/lib/api.ts`

| Function | Method | Path | Used by |
|----------|--------|------|---------|
| `listMarketSymbols(params?)` | GET | `/market-data/symbols` | `useMarketSymbols` |
| `uploadExcelFile(file)` | POST | `/market-data/excel` | `ExcelUploadDialog` |
| `listDatasets()` | GET | `/datasets` | `useDatasets` |
| `listTrackedStocks(params?)` | GET | `/market-data/stocks` | `useTrackedStocks` |
| `addTrackedStock(body)` | POST | `/market-data/stocks` | page, `StockDetailPanel`, `AddStockDialog` |
| `updateTrackedStock(symbol, body)` | PATCH | `/market-data/stocks/{symbol}` | `StockDetailPanel` |
| `bourseLookupStock(symbol)` | GET | `/market-data/stocks/{symbol}/bourse-lookup` | `StockDetailPanel` |
| `listStockMappings(symbol)` | GET | `/market-data/stocks/{symbol}/mappings` | (available, not used in UI yet) |
| `updateStockMapping(symbol, provider, body)` | PATCH | `/market-data/stocks/{symbol}/mappings/{provider}` | (available, not used in UI yet) |
| `getStockOhlcvPreview(symbol, params?)` | GET | `/market-data/stocks/{symbol}/ohlcv-preview` | `useStockOhlcvPreview` |
| `refreshAllStocks(body?)` | POST | `/market-data/refresh` | page `handleRefreshAll` |
| `refreshSingleStock(symbol)` | POST | `/market-data/stocks/{symbol}/refresh` | page `handleBourseRefresh` |
| `getRefreshRun(id)` | GET | `/market-data/refresh/{id}` | `useRefreshRun` |
| `getMarketHealth()` | GET | `/market-data/health` | `useMarketHealth` |

All functions use a shared `request<T>(path, init?)` helper that:
1. Prepends `/api` path prefix (routes through Next.js proxy)
2. Sets `Content-Type: application/json` for non-GET
3. Throws `ApiError(message, status)` on non-OK response

---

## SWR Hooks

**File**: `quant-backtesting-frontend/hooks/use-api.ts`

| Hook | Endpoint | Refresh Interval | Notes |
|------|----------|-----------------|-------|
| `useMarketSymbols(params?)` | `/market-data/symbols` | 30s | revalidateOnFocus |
| `useDatasets()` | `/datasets` | 15s | revalidateOnFocus |
| `useTrackedStocks(params?)` | `/market-data/stocks` | 60s | revalidateOnFocus |
| `useRefreshRun(id)` | `/market-data/refresh/{id}` | 2s while active, 0 when done | Smart polling: stops when status is not queued/running |
| `useMarketHealth()` | `/market-data/health` | 30s | revalidateOnFocus |
| `useStockOhlcvPreview(symbol, params?)` | `/market-data/stocks/{symbol}/ohlcv-preview` | 0 (on-demand) | Null key when symbol is null |

All hooks accept `null` key to disable fetching. The `useRefreshRun` hook uses a function for `refreshInterval` that reads the current data to decide polling speed.

---

## Next.js Proxy

**File**: `quant-backtesting-frontend/app/api/[...path]/route.ts`

All frontend API calls go through this proxy at `/api/*` → backend at `http://127.0.0.1:8000`.

**Upstream URL**: `process.env.UPSTREAM_API_BASE ?? process.env.API_URL ?? "http://127.0.0.1:8000"`

**API Key**: `process.env.API_KEY ?? ""` — injected as `x-api-key` header on every request.

**Offline fallback** (`OFFLINE_EMPTY_GET_PATHS`): In development, if the backend is unreachable, these paths silently return `[]` instead of 503:
```
/runs
/defaults/runs
/datasets
/market-data/symbols
```
**The new stock/refresh endpoints are NOT in this list** — if the backend is down, they return 503. This is intentional: you need to notice if the backend is offline for these paths.

The proxy is a pure pass-through: it forwards all methods (GET, POST, PUT, PATCH, DELETE), request body, query params, and response body verbatim. It strips `host`, `connection`, `content-length`, `transfer-encoding` headers.

---

## Page Component

**File**: `quant-backtesting-frontend/app/data/page.tsx`
Client component (`"use client"`).

### State

| State var | Type | Purpose |
|-----------|------|---------|
| `selectedSymbol` | `string \| null` | Which stock has the detail panel open |
| `uploadOpen` | `boolean` | Excel upload dialog visibility |
| `activeRefreshId` | `string \| null` | Refresh run being polled (passed to RefreshStatusBar) |
| `refreshingAll` | `boolean` | "Refresh All" button spinner |
| `refreshingSymbol` | `string \| null` | Per-row refresh button spinner (which symbol) |

### Key computed values

**`trackedSymbols: Set<string>`** — derived from `useTrackedStocks()`. Used to check whether a symbol is already in `stock_master` before triggering a refresh. If not tracked, it auto-adds it first.

**`mergedRows: MergedRow[]`** — the unified symbol list. See Data Flow section.

**`isPlaceholder(sym)`** — filters out symbols like "UPLOAD", "SHEET1", "NONE", "NA", "N/A" that appear in dataset metadata but aren't real tickers.

**`getDatasetSymbols(ds)`** — extracts symbols from a Dataset: checks `ds.detected_symbols` first, then falls back to `ds.meta.detected_symbols`.

### Key handlers

**`handleRefreshAll()`**: calls `refreshAllStocks()`, sets `activeRefreshId` to start polling progress bar. Shows toast on success/failure.

**`handleBourseRefresh(symbol)`**:
1. If symbol not in `trackedSymbols` → calls `addTrackedStock({symbol, track_source:"bourse_direct"})` → ignores 409 (already exists)
2. Calls `refreshSingleStock(symbol)` → gets `refresh_run_id` → sets `activeRefreshId`

**`mutateAll()`**: invalidates all three SWR caches (`mutateStore()`, `mutateDatasets()`, `mutateTracked()`). Called after saves in the detail panel.

### Detail panel wiring

```tsx
<StockDetailPanel
  row={selectedRow?.storeRow ?? (selectedRow ? { symbol: selectedRow.symbol } as MarketSymbolRow : null)}
  open={selectedSymbol !== null}
  onClose={() => setSelectedSymbol(null)}
  onSaved={mutateAll}
/>
```

If the symbol has no `storeRow` (not ingested yet), a minimal `MarketSymbolRow` with just the symbol is passed. The detail panel handles this gracefully.

### Table columns (inline in page, not StockTable component)

| Column | Responsive | Source |
|--------|-----------|--------|
| Ticker | always | `row.symbol` |
| Début | md+ | `row.storeRow?.start_ts?.slice(0, 10)` |
| Fin | sm+ | `row.storeRow?.end_ts?.slice(0, 10)` |
| Barres | md+ | `row.storeRow?.row_count?.toLocaleString()` |
| Source | always | Excel badge (green) if `datasetFilename` set; blue badge with `source_provider` if has store row |
| Fraîcheur | sm+ | `FreshnessBadge` if has store row, else "Non ingéré" badge |
| Actions | always | Eye (detail), FileSpreadsheet (upload), RefreshCw (bourse refresh) |

---

## Component: `stock-table.tsx`

**File**: `quant-backtesting-frontend/components/data/stock-table.tsx`
**Status**: Not used by the current page (the page inlines its own table). Available for future use.

Props:
```typescript
{
  stocks: MarketSymbolRow[]
  trackedSymbols: Set<string>
  onSelectSymbol: (symbol: string) => void
  onUploadForSymbol: (symbol: string) => void
  onRefreshStarted: (runId: string) => void
  onMutate: () => void
}
```

Has its own `handleBourseRefresh` logic (identical pattern to the page's handler). If you refactor to use this component, remove the duplicate logic from the page.

---

## Component: `stock-detail-panel.tsx`

**File**: `quant-backtesting-frontend/components/data/stock-detail-panel.tsx`
Rendered as a shadcn `Sheet` (slide-out from right). `sm:max-w-lg`.

Props:
```typescript
{
  row: MarketSymbolRow | null
  open: boolean
  onClose: () => void
  onSaved: () => void
}
```

### Internal state

| State | Type | Purpose |
|-------|------|---------|
| `stockMaster` | `StockMaster \| null` | Loaded from stock_master (if exists) |
| `displayName` | `string` | Editable field |
| `sector` | `string` | Editable field |
| `isin` | `string` | Editable field |
| `bourseUrl` | `string` | Editable Bourse URL field |
| `saving` | `boolean` | Save button spinner |
| `lookingUp` | `boolean` | Auto-fill button spinner |

### Data loading

On `open + row` change → calls `listTrackedStocks()` (direct function call, not SWR) → finds matching symbol → populates all state fields.

### `handleSave()`

If `stockMaster` exists → calls `updateTrackedStock(symbol, payload)` (PATCH)
If not → calls `addTrackedStock({symbol, ...payload, track_source:"bourse_direct"})` (POST)
Payload: `{display_name, sector, isin, bourse_url}` (undefined if empty string, so it doesn't overwrite with blanks)
On success: toast + calls `onSaved()`

### `handleBourseLookup()`

Calls `bourseLookupStock(row.symbol)` → auto-fills:
- `bourse_url` — always set (overwrite)
- `display_name` — only if currently empty
- `sector` — only if currently empty
- `isin` — only if currently empty

Shows success toast. User must still click Save to persist.

### Layout

1. **Header**: symbol in monospace + `FreshnessBadge`
2. **Data summary grid**: Début / Fin / Barres (3 cells)
3. **OHLCV chart**: `OhlcvMiniChart` with last 60 bars via `useStockOhlcvPreview`
4. **Separator**
5. **Editable section**:
   - Header: "Informations du titre" + "(sera créé à la sauvegarde)" if not yet in stock_master
   - "Auto-remplir depuis Bourse" button (blue outline, Sparkles icon)
   - Display name input
   - ISIN input (monospace font)
   - Sector select
   - Bourse URL input + external link button (opens in new tab)
   - Save button

### OHLCV preview hook usage

```typescript
const { data: preview, isLoading: previewLoading } = useStockOhlcvPreview(
  open && row ? row.symbol : null,
  { limit: 60 }
)
```

Key is `null` when panel is closed → no fetch. Fetches 60 bars of close prices.

---

## Component: `freshness-badge.tsx`

**File**: `quant-backtesting-frontend/components/data/freshness-badge.tsx`

Props: `{ dataAsOf: string | null | undefined, isStale?: boolean, className?: string }`

**Logic** (based on calendar days, not business days):

| Days ago | Badge | Color |
|----------|-------|-------|
| null/undefined | "Jamais ingéré" | gray outline |
| 0–1 | "À jour · J-0" or "À jour · J-1" | green (`bg-green-600`) |
| 2–7 | "Périmé · J-N" | amber (`bg-amber-500`) |
| 8+ | "Très périmé · J-N" | red (`bg-red-600`) |

Note: The `isStale` prop exists in the interface but is **not used** in the logic — only `dataAsOf` drives the display. The backend's `is_stale` (based on business days) is separate from this visual indicator (based on calendar days).

---

## Component: `health-cards.tsx`

**File**: `quant-backtesting-frontend/components/data/health-cards.tsx`

Props: `{ health: MarketHealth }`

Not rendered in the current page — the page does not import or use `HealthCards`. It exists as a standalone component ready to be added to the page header.

Displays 4 cards:
- **Suivis**: `health.total_tracked` (green CheckCircle2)
- **À jour**: `health.up_to_date` (green text)
- **Périmés**: `health.stale + health.very_stale` (amber)
- **Jamais ingérés**: `health.never_ingested` (muted)

To add it to the page: import `useMarketHealth` hook, add `<HealthCards health={health} />` to the page JSX.

---

## Component: `refresh-status-bar.tsx`

**File**: `quant-backtesting-frontend/components/data/refresh-status-bar.tsx`

Props: `{ refreshRunId: string | null }`

Uses `useRefreshRun(refreshRunId)` internally. Renders nothing if `refreshRunId` is null or if the run data hasn't loaded yet.

**Visibility**: Only shown when status is one of: `queued | running | partial | succeeded | failed`. Hidden for any other status (or if `!run`).

**Progress calculation**: `pct = (done + failed) / total * 100`

**Status label mapping**:
```
queued  → "En file"
running → "En cours…"
succeeded → "Terminé"
partial → "Partiel"
failed  → "Échec"
```

**Badge variants**: succeeded=default, failed=destructive, partial=outline, queued/running=secondary

---

## Component: `add-stock-dialog.tsx`

**File**: `quant-backtesting-frontend/components/data/add-stock-dialog.tsx`
Not rendered in the current page — the page does not import or use `AddStockDialog`. It exists as a ready-to-use component.

Props: `{ open: boolean, onClose: () => void, onAdded: (stock: StockMaster) => void }`

Fields:
- **Ticker** (required): uppercased as you type, sent as `symbol.trim().toUpperCase()`
- **Nom d'affichage**: optional
- **Secteur**: dropdown (see Sector List)
- **Source**: "Bourse de Casablanca" (`bourse_direct`) or "Yahoo Finance" (`yahoo`)

On submit: calls `addTrackedStock(...)`. On 409 (duplicate): shows toast error. On success: calls `onAdded(stock)`, resets form, closes dialog.

---

## Component: `ohlcv-mini-chart.tsx`

**File**: `quant-backtesting-frontend/components/data/ohlcv-mini-chart.tsx`

Props: `{ bars: OhlcvBar[] }`

Recharts `LineChart`, height 120px, responsive. Plots `close` price only.

**Y-axis domain**: `[min_close * 0.998, max_close * 1.002]` — tight fit with 0.2% padding.

**X-axis**: dates, `interval="preserveStartEnd"` (only shows first and last label).

**Line**: `type="monotone"`, stroke `hsl(var(--primary))` (follows theme), no dots, animation disabled.

**Tooltip**: shows close price formatted to 2 decimals.

If no bars → shows "Aucune donnée" placeholder.

---

## Component: `excel-upload-dialog.tsx`

**File**: `quant-backtesting-frontend/components/data/excel-upload-dialog.tsx`

Props: `{ open: boolean, onClose: () => void, onUploaded: () => void }`

Accepts `.xlsx` and `.xls` only (enforced by both `accept` attribute and drag-drop handler).

**Upload**: calls `uploadExcelFile(file)` → `POST /market-data/excel` (multipart FormData). On success: calls `onUploaded()` which triggers `mutateDatasets()` + delayed `mutateStore()`.

**Format note** shown in UI: "Format BMCE / Bourse de Casablanca — chaque feuille correspond à un titre (colonnes : Date, Ouvt, +Haut, +Bas, Clôture, Volume)"

Each Excel sheet must correspond to one ticker. Sheet names are parsed as symbols.

---

## Worker Tasks

**File**: `services/worker/tasks/refresh_market_data.py`

### Queue

Queue name: `market_refresh` (defined in `services/worker/config.py` → `_default_worker_queues()`)

**Critical**: if `market_refresh` is not in the worker's queue list, jobs are enqueued by the API but never processed. Verify with:
```python
python -c "from services.worker.config import settings; print(settings.WORKER_QUEUES)"
# Must include 'market_refresh'
```

### `refresh_all_tracked_symbols(refresh_run_id, timeframe, source_override, include_unverified)`

1. Sets run status → "running"
2. Queries `stock_master WHERE is_active=TRUE`
3. Updates `symbols_total`
4. For each symbol: calls `_do_refresh_symbol()`, catches errors per-symbol
5. Logs per-symbol errors to `market_refresh_error`
6. Updates `symbols_done/failed` after each symbol
7. Final status: "succeeded" (0 failed), "partial" (some failed), "failed" (all failed)

### `refresh_single_symbol(refresh_run_id, symbol, timeframe, source)`

1. Sets run status → "running"
2. Calls `_do_refresh_symbol()`
3. Sets status → "succeeded" or logs error → "failed"

### `_do_refresh_symbol(db, run_id, symbol, timeframe, source)`

1. Resolves provider symbol via `provider_symbol_map` table (fallback: `symbol.CS` for Yahoo, `symbol` for bourse_direct)
2. Picks adapter: `BourseDirectAdapter` or `YFinanceMoroccoAdapter`
3. Incremental fetch: looks up existing `end_ts` → fetches from `end_ts + 1 day` onwards
4. Validates OHLCV (`_validate_ohlcv`)
5. Loads existing parquet from MinIO (`_try_load_existing_parquet`)
6. Merges (`_merge_overwrite_if_different`): deduplicates by index (keep='last'), overwrites if value differs by >0.1%
7. Saves merged parquet if changed (`_save_parquet`)
8. Upserts `market_data_store` with new `start_ts, end_ts, row_count, source_provider, data_as_of`

### Adapters (in `core/quant_core/data.py`)

- `BourseDirectAdapter`: fetches from Bourse de Casablanca (URL configured via `BOURSE_DIRECT_URL_TEMPLATE` env var). **Note**: the exact URL template for bulk OHLCV download must be verified — the per-stock detail page URL (used in `bourse-lookup`) is different from the OHLCV download endpoint.
- `YFinanceMoroccoAdapter`: wraps Yahoo Finance with `.CS` suffix normalization

---

## Key Logic & Gotchas

### FK constraint (FIXED)
When creating a `stock_master` row, SQLAlchemy must `db.flush()` before adding `provider_symbol_map` children. Without the flush, both are inserted in the same batch and PostgreSQL raises `ForeignKeyViolation`. The fix is at line ~604 of `market_data.py`.

### Symbol deduplication
The page uses a `Map<string, MergedRow>` seeded from `market_data_store`, then overlaid with dataset symbols. A symbol from a dataset that is already in the store gets its `datasetFilename` filled in but doesn't get a duplicate row.

### Stale data detection: two systems
1. **Backend** (`_is_stale`): business days only, ≥2 biz days = stale. Used in `/health` and `StockMasterOut.is_stale`.
2. **Frontend** (`FreshnessBadge`): calendar days. 0–1 = green, 2–7 = amber, 8+ = red.

These can disagree on weekends/holidays — a stock from Friday will show green in the badge on Monday (1 calendar day) but `is_stale=true` from the backend (1 biz day is 2 biz days threshold). Adjust `_business_days_ago` in the backend if you want to change this.

### OHLCV preview 404
`GET /market-data/stocks/{symbol}/ohlcv-preview` returns 404 if the symbol has no row in `market_data_store`. The detail panel handles this: if `preview?.bars?.length` is falsy, it shows "Aucune donnée disponible". The `useStockOhlcvPreview` hook will have an SWR error in this case, which is silently ignored.

### offline proxy fallback
`/market-data/stocks`, `/market-data/health`, `/market-data/refresh` are NOT in `OFFLINE_EMPTY_GET_PATHS`. If the backend is down in dev, these return 503 (not empty arrays). The page will show loading indefinitely or error state.

### 4-second delay after upload
After Excel upload succeeds, the page calls `mutateStore()` with a 4-second delay:
```typescript
onUploaded={() => {
  mutateDatasets()
  setTimeout(() => mutateStore(), 4000)
}}
```
This is because the RQ ingestion worker takes time. 4s is a best-guess. If the worker is slow, the table won't immediately show the new symbol's store row.

### `track_source` drives the refresh adapter
When triggering a refresh, the worker uses `stock.track_source` from `stock_master` to pick the data adapter. `"bourse_direct"` → `BourseDirectAdapter`, `"yahoo"` → `YFinanceMoroccoAdapter`. Changing `track_source` via PATCH changes which adapter is used in future refreshes.

---

## Sector List

Used in `stock-detail-panel.tsx` and `add-stock-dialog.tsx` (hardcoded in both):
```
Banques, Assurances, Télécommunications, Immobilier, Energie,
Distribution, BTP, Mines, Agroalimentaire, Transport, Autre
```
To add sectors, update the `SECTORS` array in both files.

---

## Environment Variables

| Variable | Where used | Default | Notes |
|----------|-----------|---------|-------|
| `BOURSE_STOCK_PAGE_URL` | `market_data.py:_bourse_lookup()` | `https://www.casablanca-bourse.com/bourseweb/Detail-Valeur.aspx?Cat=3&valeur={symbol}` | Template; `{symbol}` is replaced with the ticker |
| `BOURSE_DIRECT_URL_TEMPLATE` | `core/quant_core/data.py:BourseDirectAdapter` | (not set) | URL for bulk OHLCV download — must be configured for refresh to work |
| `MARKET_REFRESH_QUEUE_NAME` | `services/api/app/config.py` | `market_refresh` | RQ queue name for refresh jobs |
| `MARKET_REFRESH_JOB_TIMEOUT_SECONDS` | `services/api/app/config.py` | (see config) | Job timeout |
| `UPSTREAM_API_BASE` / `API_URL` | `app/api/[...path]/route.ts` | `http://127.0.0.1:8000` | Where Next.js proxy forwards requests |
| `API_KEY` | `app/api/[...path]/route.ts` | `""` | Injected as `x-api-key` on every proxied request |
| `WORKER_QUEUES` | `services/worker/config.py` | `runs,defaults_discovery,market_refresh` | Comma-separated list of queues the worker listens on |
