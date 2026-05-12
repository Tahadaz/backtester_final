# 13 - Strategy Page UI Goals and Design

## Page Goal and Workflow

The Strategy page turns signal evidence into saved, editable trading-system definitions. A user should be able to select or create a strategy, choose portfolio capital/universe/allocation, configure each stock, review readiness, and hand off a saved strategy to Backtest.

## Audience and Success Criteria

Audience:

- Strategy builder converting Signals-page evidence into rules.
- Engineer modifying saved-strategy state, preview panels, or backtest handoff.

Success criteria:

- Draft state remains separate from computed preview state.
- Per-stock tabs expose Strategy Type, Signal Construction, Entry Rules, Exit Rules, Risk, and Review.
- The Backtest link appears only when the saved strategy is ready enough for the current implementation.

## Reference Design

Primary reference:

- `C:\Users\taha\Downloads\Backtest Platform Design System (1)\ui_kits\app\04-strategy.html`

## Required Page Sections

- Saved strategy rail with create/select behavior.
- Strategy header with name, side policy, status, focused stock, save/duplicate/archive, and Backtest handoff.
- Portfolio-level capital and allocation card.
- Universe card with filters, sector chips, candidate table, and basket selection.
- Per-stock tabs for the selected basket.
- Per-stock sections: allocation, strategy type, signal construction, entry rules, exit rules, risk, and review.

## Data and API Contracts

Canonical contract:

- `docs/strategy-layer/10-api-data-flow-and-frontend-contracts.md`

Current frontend/API touchpoints include:

- Hooks from `frontend/hooks/use-api.ts`: `useStrategies`, `useStrategy`, `useUniverse`, `useStrategyAllocation`, `useSignalConstructionPreview`, `useEntryRulesPreview`, `useExitRulesPreview`, `useRiskPreview`, `useStrategyReview`.
- API functions from `frontend/lib/api.ts`: `createStrategy`, `updateStrategy`, `duplicateStrategy`, `archiveStrategy`.
- Strategy config helpers in `frontend/lib/strategy-v2.ts`.

## UI States

- Loading: saved rail, universe, allocation, and previews can load independently.
- Empty: no active strategy, no selected basket symbols, or no active stock.
- Modified/saved/draft: status must reflect local edits and persistence.
- Preview unavailable/error: a failed section preview must not overwrite draft state or block unrelated sections.
- Handoff unavailable: Backtest link remains disabled/null until saved and review-ready.

## Implementation Ownership

Primary route:

- `frontend/app/strategy/page.tsx`

Current component ownership:

- Saved strategy rail: `frontend/components/layout/retractable-saved-sidebar.tsx`, `frontend/components/strategy-plan/strategy-rail.tsx`.
- Strategy header and sections: `frontend/components/strategy/*`.
- Strategy config model/helpers: `frontend/lib/strategy-v2.ts`.

## Known Gaps and Next Improvements

- Keep editable user intent in Strategy docs and code; do not let preview outputs become saved configuration.
- If the design file changes section order or density, preserve the contract boundary documented in `10-api-data-flow-and-frontend-contracts.md`.
