# 07 — Frontend Architecture

---

## Page: `/data`

**File**: `quant-backtesting-frontend/app/data/page.tsx` (596 lines)
**Component**: `DataPage()` — client component

### Layout

```
┌─────────────────────────────────────────────────────┐
│  Header: "Données de marché"                        │
│  [Ajouter un titre] [Importer Excel] [MAJ Bourse]  │
├─────────────────────────────────────────────────────┤
│  RefreshStatusBar (conditional)                     │
├─────────────────────────────────────────────────────┤
│  Help text / legend (3 icons explaining actions)    │
├──────────────┬──────────────────────────────────────┤
│  MASI (N)    │  Autres (N)     ← market tabs        │
├──────────────┴──────────────────────────────────────┤
│  Data Table                                         │
│  ┌──────────────────────────────────────────────┐   │
│  │ Ticker│Nom│Début│Fin│Barres│Source│Fraîcheur │   │
│  │       │   │     │   │      │      │Bourse│Suivi│  │
│  │ [row actions: Graphique│Importer│MAJ│Supprimer] │
│  └──────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────┤
│  StockDetailPanel (modal, conditional)              │
│  ExcelUploadDialog (modal, conditional)             │
│  AddStockDialog (modal, conditional)                │
│  Delete AlertDialog (conditional)                   │
└─────────────────────────────────────────────────────┘
```

### State Management (11 useState hooks)

| State | Type | Purpose |
|-------|------|---------|
| `marketTab` | `"masi" \| "other"` | Filters catalog between MASI and non-MASI |
| `selectedSymbol` | `string \| null` | Triggers StockDetailPanel |
| `uploadOpen` | `boolean` | ExcelUploadDialog visibility |
| `addStockOpen` | `boolean` | AddStockDialog visibility |
| `activeRefreshId` | `string \| null` | Tracks current refresh run for status bar |
| `refreshingAll` | `boolean` | Loading state for "MAJ Bourse" button |
| `refreshingSymbol` | `string \| null` | Loading state for per-row refresh |
| `deletingSymbol` | `string \| null` | Loading state for delete |
| `deleteTarget` | `MarketCatalogRow \| null` | Confirmation dialog target |

### SWR Hooks

| Hook | Endpoint | Refresh |
|------|----------|---------|
| `useMarketCatalog()` | `GET /market-data/catalog` | 30s interval, revalidate on focus |
| `useTrackedStocks()` | `GET /market-data/stocks` | 60s interval, revalidate on focus |
| `useMasiTickers()` | `GET /market-data/masi-tickers` | Cached, no focus revalidation |

### Derived State (useMemo)

- `trackedSet`: Set of `is_tracked` symbols (for checkmark column)
- `masiRows`: filter by `market === "masi"`
- `otherRows`: filter by `market !== "masi"`
- `rows`: selected based on active tab

### Table Columns (9, responsive)

| Column | Visibility | Content |
|--------|------------|---------|
| Ticker | Always | Monospace bold |
| Nom | Hidden sm | display_name |
| Début | Always | start_ts (YYYY-MM-DD) |
| Fin | Always | end_ts (YYYY-MM-DD) |
| Barres | Hidden md | row_count (locale formatted) |
| Source | Hidden md | Badge: FileSpreadsheet (green) for Excel, RefreshCw (blue) for provider |
| Fraîcheur | Always | FreshnessBadge component |
| Bourse | Hidden lg | External link to bourse_url |
| Suivi | Hidden lg | CheckCircle2 (tracked) or Circle |
| Actions | Always | 4 icon buttons (w-[220px]) |

### Row Actions

| Button | Icon | Color | Handler |
|--------|------|-------|---------|
| Graphique | Eye | Green outline | Opens StockDetailPanel |
| Importer | FileSpreadsheet | Green ghost | Opens ExcelUploadDialog |
| Mettre à jour | RefreshCw | Blue ghost | `refreshSingleStock(symbol)` → auto-adds to tracked if needed |
| Supprimer | Trash2 | Red ghost | Opens delete confirmation AlertDialog |

---

## Components

### FreshnessBadge (`components/data/freshness-badge.tsx`, 34 lines)

Color-coded data freshness indicator based on calendar days since `dataAsOf`:

| Days | Badge | Color |
|------|-------|-------|
| ≤1 | "À jour" | Green (text-green-700, bg-green-50) |
| 2–7 | "{n}j" | Yellow (text-yellow-700, bg-yellow-50) |
| >7 | "{n}j — obsolète" | Red (text-red-700, bg-red-50) |

### RefreshStatusBar (`components/data/refresh-status-bar.tsx`, 43 lines)

Real-time progress during market refresh.

- **Hook**: `useRefreshRun(refreshRunId)` — adaptive polling: 2s while running/queued, stops when done
- **Running**: spinning RefreshCw icon + "Mise à jour en cours… {done}/{total}" + progress bar
- **Done**: CheckCircle2 + "Mise à jour terminée"
- **Failed**: AlertCircle + error_message

### ExcelUploadDialog (`components/data/excel-upload-dialog.tsx`, 242 lines)

Step-by-step Excel import with format reference.

**Phases**: idle → uploading → processing → done

**Flow**:
1. Display format reference (from `useUploadFormatReference()`) showing accepted aliases, numeric examples, volume suffixes
2. User clicks "Choisir un fichier" → file input
3. `uploadExcelFile(file)` → returns dataset_id
4. Poll via `waitForIngestCompletion(dataset_id)` (1.5s interval, 30s timeout)
5. Display per-symbol results: SymbolResultRow with CheckCircle2 (success) or XCircle (error)

**Toast feedback**:
- All success: "{N} symbole(s) importés avec succès"
- Mixed: "{N} importés, {M} en erreur"
- All error: "Aucun symbole importé — voir les détails"

### StockDetailPanel (`components/data/stock-detail-panel.tsx`, 854 lines)

Full OHLCV detail modal with chart, calendar, and diagnostics.

**Hooks** (conditional on panel being open):
- `useStockOhlcvPreview(symbol, limit=10)` — last 10 bars
- `useStockOhlcvHistory(symbol)` — full history for chart
- `useStockAvailabilityCalendar(symbol)` — per-day coverage

**Sections** (top to bottom):

#### 1. Header (bg-slate-50/80)
- Symbol (text-2xl), badges (Tracked, source_provider)
- Metadata: "Dernière barre" date, "Historique" row count

#### 2. QuickFacts
Card with 4 columns: Début, Fin, Barres, Source

#### 3. Candlestick Chart (Plotly)
- **Type**: Candlestick + volume bar (secondary y-axis)
- **Colors**: Increasing = teal (#14b8a6), Decreasing = red (#ef4444)
- **Volume**: Slate bars (#94a3b8), opacity 0.6
- **Holiday breaks**: rangebreaks with weekend bounds + holiday values (removes gaps from chart)
- **Initial range**: 12 months from last date
- **Height**: 520px, dragmode: pan

#### 4. Year Strip Overview
- Year buttons for navigation
- Month grid (sm:3 cols, xl:6 cols) with color tones:
  - Amber: missing days > 0
  - Sky: holidays/tentative > 0
  - Emerald: present days > 0
- Click month → selects it in calendar below

#### 5. Availability Calendar Grid
- Month navigation with chevrons + fr-MA locale label
- Summary stats (6 boxes): OHLCV, Partiels, Manquants, Weekend, Fériés, Tentatifs
- **7-column grid** (Lun–Dim):
  - Each cell: day number, state color, GAP badge (amber) if missing, ! badge if partial
  - Colors: emerald (present), amber (missing), sky (holiday), fuchsia (tentative), slate (weekend), dashed (outside range)
  - Out-of-month days shown at 55% opacity
- Legend: 7-item with colored boxes

#### 6. Data Quality Report
- Green "Aucun problème détecté" if clean
- Amber expandable section if issues:
  - **Partial days table**: field, count, dates (truncated at 12 with "… et N autres")
  - **Missing days**: count + date list

#### 7. Last 10 OHLCV Bars
Table: Date, O, H, L, C, Vol (right-aligned, 2-decimal prices, locale-formatted volume)

### AddStockDialog (inline in page.tsx, lines 517–595)

- Search input filters MASI tickers by symbol/display_name/sector
- Scrollable list (max-h-80) with per-ticker buttons
- Already-existing symbols shown with green checkmark (disabled)
- On select: `addTrackedStock(ticker)` → mutates catalog + tracked

---

## API Client (`lib/api.ts`)

### Key Types

| Type | Fields |
|------|--------|
| `MarketCatalogRow` | symbol, display_name, sector, start_ts, end_ts, row_count, source_provider, data_as_of, is_stale, is_tracked, has_canonical_data, market |
| `OhlcvHistory` | symbol, timeframe, bars[], source_provider, data_as_of, row_count |
| `OhlcvBar` | date, open?, high?, low?, close?, volume? |
| `AvailabilityCalendar` | symbol, days[], counts per state, default_month |
| `AvailabilityCalendarDay` | date, state, has_data, holiday_name, holiday_certainty, missing_fields[] |
| `MasiTicker` | symbol, display_name, sector |
| `MarketRefreshRun` | id, status, symbols_total/done/failed, timestamps, error_message |
| `UploadFormatReference` | canonical_fields, formats[], validation |

### API Functions

| Function | Method | Endpoint |
|----------|--------|----------|
| `listMarketCatalog()` | POST | `/market-data/catalog` |
| `fetchMasiTickers()` | GET | `/market-data/masi-tickers` |
| `listTrackedStocks()` | GET | `/market-data/stocks` |
| `addTrackedStock(body)` | POST | `/market-data/stocks` |
| `updateTrackedStock(symbol, body)` | PATCH | `/market-data/stocks/{symbol}` |
| `deleteMarketSymbol(symbol)` | DELETE | `/market-data/symbols/{symbol}` |
| `uploadExcelFile(file)` | POST | `/market-data/excel` (multipart) |
| `pollIngestStatus(datasetId)` | GET | `/market-data/uploads/{id}/status` |
| `waitForIngestCompletion(id)` | — | Polls pollIngestStatus (1.5s, 30s timeout) |
| `refreshAllStocks()` | POST | `/market-data/refresh` |
| `refreshSingleStock(symbol)` | POST | `/market-data/stocks/{symbol}/refresh` |
| `getRefreshRun(id)` | GET | `/market-data/refresh/{id}` |
| `getStockOhlcvPreview(symbol)` | GET | `/market-data/stocks/{symbol}/ohlcv-preview` |
| `getStockOhlcvHistory(symbol)` | GET | `/market-data/stocks/{symbol}/ohlcv-history` |
| `getStockAvailabilityCalendar(symbol)` | GET | `/market-data/stocks/{symbol}/availability-calendar` |
| `getUploadFormatReference()` | GET | `/market-data/upload-format-reference` |

---

## User Interactions Summary

| Action | French Label | Toast |
|--------|-------------|-------|
| Add stock | "Ajouter un titre" | "{symbol} — {name} ajouté" |
| Import Excel | "Importer Excel" | "{N} symbole(s) importés avec succès" |
| Refresh all | "Mettre à jour via Bourse" | "Mise à jour Bourse lancée pour tous les titres suivis" |
| Refresh single | Per-row RefreshCw | "Mise à jour Bourse lancée pour {symbol}" |
| View chart | Per-row Eye | Opens StockDetailPanel |
| Delete | Per-row Trash2 | "{symbol} supprimé du catalogue" |
| Save name | "Enregistrer" in detail panel | "{symbol} mis à jour" |
