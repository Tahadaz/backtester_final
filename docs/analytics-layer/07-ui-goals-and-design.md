# 07 - Analytics Page UI Goals and Design

## Page Goal and Workflow

The Analytics page is the read-only evidence surface for signal and factor predictive ability. A user should be able to rank signals, select a stock, inspect expected returns and hit rates by bucket/horizon, and review macro-factor diagnostics.

## Audience and Success Criteria

Audience:

- Research user validating whether Signal Engine, WFO, or Factor x TA scores have historical predictive ability.
- Engineer modifying analytics panels, leaderboard behavior, or recompute controls.

Success criteria:

- Leaderboard and per-stock diagnostics are both reachable from `/analytics`.
- Signal analytics, macro data, and factor analytics remain separate tabs.
- Recompute controls and recompute status are visible without hiding read-only evidence.

## Reference Design

Primary reference:

- `C:\Users\taha\Downloads\Backtest Platform Design System (1)\ui_kits\app\06-analytics.html`

## Required Page Sections

- Header with title and global recompute control.
- Recompute status card.
- Top-level tabs: TA signals, macro data, macro factors.
- TA signals sub-tabs: top signals leaderboard and per-stock predictive matrix/details.
- Optional lookback and liquidity filters for TA signal views.
- Macro data table.
- Factor tabs: leaderboard and per-stock factor diagnostics.

## Data and API Contracts

Canonical analytics docs:

- `docs/analytics-layer/02-data-flow.md`
- `docs/analytics-layer/03-bucket-matrix-per-stock.md`
- `docs/analytics-layer/04-leaderboard-top-signaux.md`
- `docs/analytics-layer/05-category-combinations-and-monotonicity.md`

Current frontend/API touchpoints include:

- `useAnalyticsSignalsOverview()` and related analytics hooks from `frontend/hooks/use-api.ts`.
- `useDashboardData("short")` for ADV/liquidity context.
- Components in `frontend/components/analytics/*`.
- Recompute actions through `RecomputeControls` and status via `RecomputeStatusCard`.

## UI States

- Loading: symbol lists and panels use skeletons or empty placeholders.
- Empty: no selected symbol/factor, no symbols after filter, or no rows returned.
- No result: panel should explain missing predictive data without implying an app failure.
- Error: recompute and analytics panel errors should be local.
- Stale/recomputing: status card should indicate refresh state while existing evidence remains visible.

## Implementation Ownership

Primary route:

- `frontend/app/analytics/page.tsx`

Current component ownership:

- Analytics panels: `frontend/components/analytics/*`.
- API hooks: `frontend/hooks/use-api.ts`.
- Dashboard liquidity context: `frontend/hooks/use-dashboard.ts`.

## Known Gaps and Next Improvements

- Keep signal-level analytics separate from backtest-level validation. Backtest statistics belong in `docs/backtest-layer/`.
- Factor methodology belongs in `docs/factor-layer/`; this page-level file only describes the UI composition and navigation.
