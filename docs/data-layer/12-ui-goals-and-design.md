# 12 - Data Page UI Goals and Design

## Page Goal and Workflow

The Data page is the market-data control center. A user should be able to inspect the catalog, add instruments or factors, import Excel files, trigger Bourse/Yahoo refreshes, and open a symbol detail view to audit OHLCV history and freshness.

## Audience and Success Criteria

Audience:

- Operator maintaining the data required by signals, analytics, strategies, and backtests.
- Engineer modifying ingestion, catalog, or detail-panel workflows.

Success criteria:

- The user can tell which instruments have data, how fresh it is, and which source produced it.
- Refresh and import actions are visible at both page and row level.
- A new engineer can find the current route, data components, API functions, and reference design without reading unrelated plans.

## Reference Design

Primary reference:

- `C:\Users\taha\Downloads\Backtest Platform Design System (1)\ui_kits\app\02-data.html`

## Required Page Sections

- Header with add stock, add factor, Excel import, download, and refresh actions.
- Refresh status bar when a refresh run is active.
- Asset category tabs and equity region/subcategory tabs.
- Catalog table showing ticker, name, sector, date range, row count, source, freshness, and row actions.
- Stock detail panel with OHLCV chart/history and save/edit actions.
- Excel upload dialog.
- Add stock dialog for MASI tickers.
- Add factor and category-edit dialogs.

## Data and API Contracts

Canonical data docs:

- `docs/data-layer/03-backend-endpoints.md`
- `docs/data-layer/07-frontend-architecture.md`
- `docs/data-layer/11-daily-update-and-data-page.md`

Current frontend/API touchpoints include:

- Catalog and tracked stock hooks from `frontend/hooks/use-api.ts`: `useMarketCatalog`, `useTrackedStocks`, `useMasiTickers`, `useMacroCatalog`.
- API functions in `frontend/lib/api.ts`: `refreshAllStocks`, `refreshSingleStock`, `addTrackedStock`, `enqueueAllMacroIngest`, `enqueueMacroIngest`, upload/download helpers, OHLCV history helpers.

## UI States

- Loading: skeleton rows while catalog data loads.
- Empty: category or subcategory has no assets; equity/all can prompt adding a MASI stock.
- Stale data: freshness badges show data recency from the catalog row.
- Error: catalog load failures show a local error panel with API/proxy message.
- Refresh in progress: row and page refresh buttons show active state, and the status bar tracks the refresh run.

## Implementation Ownership

Primary route:

- `frontend/app/data/page.tsx`

Current component ownership:

- Page-specific components: `frontend/components/data/*`.
- Shared UI primitives: `frontend/components/ui/*`.
- API client and types: `frontend/lib/api.ts`.

## Known Gaps and Next Improvements

- Some older data docs describe an earlier MASI/Other tab model. The current page uses asset category and equity subcategory tabs.
- Keep product/UI changes here and endpoint/schema changes in `03-backend-endpoints.md` or the relevant data-layer architecture document.
