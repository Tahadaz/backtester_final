# 08 - Dashboard Page UI Goals and Design

## Page Goal and Workflow

The Dashboard page is the daily triage surface. A user should be able to choose a horizon and score source, scan the MASI universe, filter to actionable names, inspect Edge evidence, and build a daily blotter or basket ticket.

## Audience and Success Criteria

Audience:

- Desk user scanning current market opportunities.
- Engineer modifying dashboard navigation, filters, Edge proof, or daily blotter behavior.

Success criteria:

- The user can move from universe scan to row evidence to daily action without leaving the page.
- Edge and WFO/Signal Engine source selection are visible in the same workflow as stock filtering.
- A new engineer can find the active route and components without relying on the historical deployment plan.

## Reference Design

Reference HTML design files available in the local design kit:

- `C:\Users\taha\Downloads\Backtest Platform Design System (1)\ui_kits\app\01-dashboard.html`
- `C:\Users\taha\Downloads\Backtest Platform Design System (1)\ui_kits\app\01-dashboard v2.html`
- `C:\Users\taha\Downloads\Backtest Platform Design System (1)\ui_kits\app\01-dashboard v3.html`
- `C:\Users\taha\Downloads\Backtest Platform Design System (1)\ui_kits\app\01-dashboard v4.html`

Use the latest agreed dashboard design when changing visual structure. This page and the implementation files below are the active UI source of truth.

## Required Page Sections

- Header with horizon, source, filters/export/recalculate controls.
- KPI strip for active universe, bullish/bearish signal counts, and Edge/expected-return summary where available.
- Setup/filter controls for horizon, universe/scope, score source, liquidity/category, support/resistance visibility, sector, and search.
- Stock table with per-family scores, aggregate signal, Edge evidence, and row actions.
- Edge detail panel for a selected row.
- Basket/daily blotter section using selected symbols and manual positions.
- Loading, empty, error, and disabled states for dashboard data, Edge cache, and blotter/ticket APIs.

## Data and API Contracts

Existing contracts are spread across:

- `docs/dashboard-layer/04-dashboard-page.md`
- `docs/EDGE_METHOD.md` for Edge methodology
- `frontend/lib/dashboard-types.ts`
- `frontend/lib/api.ts`

Current frontend/API touchpoints include:

- `useDashboardData(horizon)` from `frontend/hooks/use-dashboard.ts`.
- `useMarketCatalog()` from `frontend/hooks/use-api.ts`.
- `fetchEdge()` for row-level Edge proof.
- `fetchDashboardDailyBlotter()`, `fetchDashboardPortfolioTicket()`, `fetchDashboardPortfolioPositions()`, and `saveDashboardPortfolioPositions()` for ticket/blotter workflows.

## UI States

- Loading: use table and KPI skeletons; keep filter controls visible where possible.
- Empty: no rows after filters, no basket symbols, or no manual positions.
- Stale/unavailable: Edge may be `null` on cold cache; row should still render.
- Error: dashboard data, Edge fetches, and blotter/ticket calls should show local error states.
- Feature flag: `NEXT_PUBLIC_EDGE_ENABLED=false` hides or disables Edge-specific affordances.

## Implementation Ownership

Primary routes:

- `frontend/app/dashboard/page.tsx` re-exports `frontend/app/v1/page.tsx`.
- `frontend/app/v1/page.tsx` owns the active Dashboard v1 implementation.

Current component ownership:

- Table components: `frontend/components/dashboard-v1/*`.
- Dashboard atoms/panels: `frontend/components/dashboard/*`.
- Shared types/constants: `frontend/lib/dashboard-types.ts`, `frontend/lib/horizon.ts`.
- API client: `frontend/lib/api.ts`.

## Known Gaps and Next Improvements

- The `dashboard-layer` folder still contains older static-export documentation. Keep it for history, but use this file for active Dashboard UI intent.
- The design kit has multiple dashboard iterations. Record the chosen design file in this doc when a redesign pass locks one as canonical.
