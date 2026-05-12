# 15 - Backtest Page UI Goals and Design

## Page Goal and Workflow

The Backtest page evaluates saved strategies. A user should be able to choose a saved strategy, configure direct or WFO execution, run or inspect saved results, and review portfolio, per-stock, chart, window, and trade-ledger evidence.

## Audience and Success Criteria

Audience:

- Research user validating whether a saved strategy survives direct or walk-forward testing.
- Engineer modifying result rendering, WFO status, or saved-run behavior.

Success criteria:

- The page clearly separates run configuration, active/saved run status, and immutable result evidence.
- Direct backtest and WFO result sections expose the different evidence they produce.
- Per-stock drill-downs keep charts, metrics, and trade ledgers together.

## Reference Design

Primary reference:

- `C:\Users\taha\Downloads\Backtest Platform Design System (1)\ui_kits\app\05-backtest.html`

## Required Page Sections

- Saved strategy/backtest sidebar or selector.
- Run configuration for direct/WFO mode, date range, family history mode, and execution options.
- Run lifecycle controls: create/run, cancel active run, rename saved run, delete saved run.
- WFO saved-run summary: portfolio held-out summary, per-stock tabs, windows, final parameters, all configs tested, and held-out metrics.
- Direct result summary: portfolio metrics, equity/drawdown/monthly/yearly charts, per-stock charts, trade ledger, and metric table.
- Error and not-viable messages surfaced close to the affected result.

## Data and API Contracts

Canonical contract:

- `docs/backtest-layer/10-api-data-flow-and-frontend-contracts.md`

Current frontend/API touchpoints include:

- Hooks from `frontend/hooks/use-api.ts`: `useStrategies`, `useStrategy`, `useStrategyBacktestRun`, `useStrategyBacktestRuns`, `useStrategyBacktestStockDetail`.
- API functions from `frontend/lib/api.ts`: `createStrategyBacktestRun`, `fetchStrategyBacktest`, `cancelStrategyBacktestRun`, `renameStrategyBacktestRun`, `deleteStrategyBacktestRun`.
- Plot rendering through `frontend/components/run/plotly-chart.tsx`.

## UI States

- Loading: strategy, run, and per-stock detail can load independently.
- Empty: no strategy selected, no saved run selected, no result yet, or no stock detail loaded.
- Running/queued/cancel-requested: active run card shows current lifecycle state.
- Not viable: WFO per-stock and run-level rejection reasons should be visible.
- Error: run error text, compatibility warnings, and API failures should be local to the affected section.

## Implementation Ownership

Primary route:

- `frontend/app/backtest/page.tsx`

Current component ownership:

- Backtest page assembly is currently concentrated in `frontend/app/backtest/page.tsx`.
- Shared chart/table helpers are under `frontend/components/run/*` and `frontend/lib/format.ts`.
- Strategy selection reuses saved-strategy hooks and models.

## Known Gaps and Next Improvements

- The page file is large; future changes should extract stable sections only when there is a clear ownership boundary.
- Keep methodology and API details in the backtest-layer contract docs; this file should stay focused on UI intent and navigation.
