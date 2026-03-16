# Data Layer — Frontend Architecture

---

## Page: `/data`

**File:** `quant-backtesting-frontend/app/data/page.tsx`
**Client component** (`"use client"`)
**Nav link:** "Données" in `components/app-header.tsx`

### State

| State | Type | Purpose |
|-------|------|---------|
| `selectedSymbol` | `string \| null` | Which stock has the detail panel open |
| `uploadOpen` | `boolean` | Excel upload dialog visibility |
| `activeRefreshId` | `string \| null` | Refresh run being polled (drives RefreshStatusBar) |
| `refreshingAll` | `boolean` | "Refresh All" button spinner |
| `refreshingSymbol` | `string \| null` | Per-row refresh spinner (which symbol) |

### Data Sources

| Hook | Endpoint | Refresh | Returns |
|------|----------|---------|---------|
| `useMarketCatalog()` | `GET /market-data/catalog` | 30s | `MarketCatalogRow[]` |
| `useTrackedStocks()` | `GET /market-data/stocks` | 60s | `StockMaster[]` (used for `trackedSet`) |

### Key Handlers

- **`handleRefreshAll()`** — calls `refreshAllStocks()` → sets `activeRefreshId` → shows toast
- **`handleBourseRefresh(symbol)`**:
  1. If symbol not in `trackedSet` → auto-calls `addTrackedStock({symbol, track_source:"bourse_direct"})` → ignores 409
  2. Calls `refreshSingleStock(symbol)` → sets `activeRefreshId`
- **`mutateAll()`** — invalidates both SWR caches (catalog + tracked stocks)

### Table Columns

| Column | Responsive | Source |
|--------|-----------|--------|
| Ticker | always | `row.symbol` (monospace bold) |
| Nom | sm+ | `row.display_name` |
| Début | always | `row.start_ts?.slice(0, 10)` |
| Fin | always | `row.end_ts?.slice(0, 10)` |
| Barres | md+ | `row.row_count?.toLocaleString()` |
| Source | md+ | Badge: Excel (green) or source_provider (blue) |
| Fraîcheur | always | `FreshnessBadge` or "Non ingéré" badge |
| Bourse | lg+ | External link to `row.bourse_url` |
| Suivi | lg+ | CheckCircle2 (tracked) or Circle (not tracked) |
| Actions | always | Eye (detail), FileSpreadsheet (upload), RefreshCw (refresh) |

---

## Components (`components/data/`)

### StockDetailPanel (`stock-detail-panel.tsx`)
Sheet (slide-out from right, `sm:max-w-lg`).

**Props:** `{ row: MarketCatalogRow | null, open: boolean, onClose, onSaved }`

**Sections:**
1. Header: symbol + FreshnessBadge
2. Data summary: Début / Fin / Barres
3. OHLCV chart: `OhlcvMiniChart` with last 60 bars via `useStockOhlcvPreview`
4. Editable fields: display_name, ISIN, sector, bourse_url
5. "Auto-remplir depuis Bourse" button → calls `bourseLookupStock(symbol)` → auto-fills empty fields
6. Save button → `addTrackedStock()` (new) or `updateTrackedStock()` (existing)

**Data loading:** On open, calls `listTrackedStocks()` → finds matching symbol → populates form state.

### ExcelUploadDialog (`excel-upload-dialog.tsx`)
**Props:** `{ open: boolean, onClose, onUploaded }`

- Drag-drop zone accepting `.xlsx` / `.xls`
- Calls `uploadExcelFile(file)` → `POST /market-data/excel`
- On success: `onUploaded()` → parent mutates catalog after 4s delay

### FreshnessBadge (`freshness-badge.tsx`)
**Props:** `{ dataAsOf: string | null, isStale?: boolean, className?: string }`

| Days ago (calendar) | Label | Color |
|---------------------|-------|-------|
| null | "Jamais ingéré" | gray outline |
| 0–1 | "À jour · J-0/J-1" | green (bg-green-600) |
| 2–7 | "Périmé · J-N" | amber (bg-amber-500) |
| 8+ | "Très périmé · J-N" | red (bg-red-600) |

Note: uses **calendar days**, not business days. Backend `is_stale` uses business days — they can disagree on weekends.

### RefreshStatusBar (`refresh-status-bar.tsx`)
**Props:** `{ refreshRunId: string | null }`

Uses `useRefreshRun(refreshRunId)` internally. Shows progress bar: `pct = (done + failed) / total * 100`.

Status labels: queued → "En file", running → "En cours…", succeeded → "Terminé", partial → "Partiel", failed → "Échec".

### HealthCards (`health-cards.tsx`)
**Props:** `{ health: MarketHealth }`

4 summary cards: Suivis, À jour, Périmés, Jamais ingérés. **Not currently imported by the page** — ready to add.

### OhlcvMiniChart (`ohlcv-mini-chart.tsx`)
**Props:** `{ bars: OhlcvBar[] }`

Recharts LineChart, height 120px. Plots Close prices only. Y-axis: tight fit with 0.2% padding.

### AddStockDialog (`add-stock-dialog.tsx`)
**Props:** `{ open: boolean, onClose, onAdded }`

Fields: Ticker (required, uppercased), Nom, Secteur (dropdown), Source (bourse_direct/yahoo). **Not currently imported by the page** — ready to add.

### StockTable (`stock-table.tsx`)
Reusable table component. **Not imported by the page** — the page inlines its own table. Available for future refactoring.

---

## SWR Hooks (`hooks/use-api.ts`)

| Hook | Endpoint | Refresh | Notes |
|------|----------|---------|-------|
| `useMarketCatalog()` | `/market-data/catalog` | 30s | revalidateOnFocus |
| `useMarketSymbols(params?)` | `/market-data/symbols` | 30s | revalidateOnFocus |
| `useDatasets()` | `/datasets` | 15s | revalidateOnFocus |
| `useTrackedStocks(params?)` | `/market-data/stocks` | 60s | revalidateOnFocus |
| `useRefreshRun(id)` | `/market-data/refresh/{id}` | 2s while active | Smart poll: stops when terminal status |
| `useMarketHealth()` | `/market-data/health` | 30s | revalidateOnFocus |
| `useStockOhlcvPreview(symbol, params?)` | `/market-data/stocks/{symbol}/ohlcv-preview` | 0 | On-demand; null key when symbol is null |

---

## API Client Functions (`lib/api.ts`)

### Zod Schemas (types)
- `MarketSymbolRowSchema` / `MarketSymbolRow`
- `StockMasterSchema` / `StockMaster`
- `BourseStockLookupSchema` / `BourseStockLookup`
- `ProviderSymbolMapSchema` / `ProviderSymbolMap`
- `MarketRefreshRunSchema` / `MarketRefreshRun`
- `MarketHealthSchema` / `MarketHealth`
- `OhlcvBarSchema` / `OhlcvPreviewSchema` / `OhlcvBar` / `OhlcvPreview`
- `MarketCatalogRowSchema` / `MarketCatalogRow`

### Functions
| Function | Method | Endpoint |
|----------|--------|----------|
| `listMarketCatalog()` | GET | `/market-data/catalog` |
| `listMarketSymbols(params?)` | GET | `/market-data/symbols` |
| `listTrackedStocks(params?)` | GET | `/market-data/stocks` |
| `addTrackedStock(body)` | POST | `/market-data/stocks` |
| `updateTrackedStock(symbol, body)` | PATCH | `/market-data/stocks/{symbol}` |
| `bourseLookupStock(symbol)` | GET | `/market-data/stocks/{symbol}/bourse-lookup` |
| `getStockOhlcvPreview(symbol, params?)` | GET | `/market-data/stocks/{symbol}/ohlcv-preview` |
| `listStockMappings(symbol)` | GET | `/market-data/stocks/{symbol}/mappings` |
| `updateStockMapping(symbol, provider, body)` | PATCH | `/market-data/stocks/{symbol}/mappings/{provider}` |
| `uploadExcelFile(file)` | POST | `/market-data/excel` |
| `refreshAllStocks(body?)` | POST | `/market-data/refresh` |
| `refreshSingleStock(symbol, body?)` | POST | `/market-data/stocks/{symbol}/refresh` |
| `getRefreshRun(id)` | GET | `/market-data/refresh/{id}` |
| `listRefreshRuns(params?)` | GET | `/market-data/refresh` |
| `getMarketHealth()` | GET | `/market-data/health` |

---

## Next.js Proxy (`app/api/[...path]/route.ts`)

All `/api/*` requests → upstream at `http://127.0.0.1:8000`.

- Injects `x-api-key` header from env `API_KEY`
- Pure pass-through: all methods, body, query params, response verbatim
- Offline fallback (dev only): returns `[]` for GET `/runs`, `/datasets`, `/market-data/symbols`
- Market data endpoints (`/stocks`, `/refresh`, `/health`) are NOT in the fallback list — they 503 if backend is down

---

## Sector List (hardcoded in two components)

Used in `stock-detail-panel.tsx` and `add-stock-dialog.tsx`:

```
Banques, Assurances, Télécommunications, Immobilier, Energie,
Distribution, BTP, Mines, Agroalimentaire, Transport, Autre
```
