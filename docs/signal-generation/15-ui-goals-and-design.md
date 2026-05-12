# 15 - Signals Page UI Goals and Design

## Page Goal and Workflow

The Signals page is the evidence station for technical signals. A daily user should be able to select a stock, choose the signal horizon and source view, inspect the current signal, then drill into the evidence that produced it.

The page must keep one distinction visible: signals are evidence about market state, not executable trades. Trade construction belongs to the Strategy page, and strategy evaluation belongs to the Backtest page.

## Audience and Success Criteria

Audience:

- Portfolio or research user checking current signal evidence for one stock.
- Engineer modifying the Signals page without rediscovering the frontend ownership map.

Success criteria:

- A user can see the current signal, supporting indicator evidence, WFO evidence, and historical backtest evidence from one stock-centered page.
- A new engineer can find the route, layout components, API client functions, and reference HTML design from this repository map.
- Horizon naming is not ambiguous: UI values are `weekly`, `monthly`, `quarterly`; older docs and backend-facing contracts may still refer to `short`, `medium`, `long`, mapped in `frontend/lib/horizon.ts`.

## Reference Design

Primary reference:

- `C:\Users\taha\Downloads\Backtest Platform Design System (1)\ui_kits\app\03-signals.html`

Use this as the product/design reference for Signals redesign work. Treat the implementation files below as the source of truth for current behavior.

## Required Page Sections

The current page is assembled around a stock selector and nested technical-analysis tabs:

- Version selector: `expanded`, `legacy`, and `factor_x_ta`.
- Stock selector/sidebar with per-stock signal summary.
- Horizon control using `weekly`, `monthly`, `quarterly`.
- Current signal proof section showing Signal Engine and WFO evidence.
- Technical signal view with current consensus, categories, families, and drill-downs.
- Indicator explorer chart with price, active overlays/subpanels, parameters, and live scores.
- WFO methodology/evidence tab.
- Backtest and Monte Carlo tab with historical results, price/signal chart, Edge proof, fan chart, and trade ledger.

For the planned redesign around `03-signals.html`, preserve these concepts:

- Stock selector plus horizon/source controls.
- Current signal proof before detailed drill-downs.
- Indicator chart that shows the overlays used to construct the signal.
- Separate proof cards for Signal Engine and WFO where both are available.
- Historical mini-backtest and trade ledger with returns.
- Explicit signal-vs-strategy copy: evidence here does not mean an executable trade.

## Data and API Contracts

Canonical API/data contract:

- `docs/signal-generation/09-api-and-frontend.md`

Current frontend API client functions live in `frontend/lib/api.ts` and include:

- Signal Engine: `fetchFamilyEnsemble`, `fetchBatchScores`, `fetchVariantDetail`, `fetchVariantBacktest`.
- Indicator explorer: `fetchIndicatorSeries` posts to `/strategy/signal/indicator-series`.
- Support/resistance and WFO detail helpers are also routed through `frontend/lib/api.ts`.
- Edge proof uses `fetchEdge` with normalized `weekly`/`monthly`/`quarterly` horizons.

Horizon compatibility:

- UI inputs use `weekly`, `monthly`, `quarterly`.
- `resolveHorizonPreset()` maps legacy aliases: `short -> weekly`, `medium -> monthly`, `long -> quarterly`.
- API calls that use `canonicalSignalHorizon()` should accept either naming scheme and send the normalized value.

## UI States

Required states:

- Loading: Suspense fallback, skeletons, and per-panel loading states must keep the layout stable.
- No stock selected: show an empty state for signal, indicator, WFO, and backtest panels.
- Empty/no result: show the reason where known, such as no WFO consensus or no persisted backtest result.
- Stale/unavailable evidence: Edge cache and WFO evidence cards can be unavailable independently; the page should still render other evidence.
- Error: family, WFO, indicator, and backtest panels should fail locally and not blank the entire page.

## Implementation Ownership

Primary route:

- `frontend/app/signals/page.tsx`

Current component ownership:

- Page switching/layout: `frontend/components/strategy/signals-version-toggle.tsx`, `frontend/components/strategy/signals-view-layout.tsx`, `frontend/components/strategy/shared-signals-view.tsx`.
- Current signal and family drill-downs: `frontend/components/strategy/technical-analysis-panel.tsx` and related `frontend/components/strategy/*` signal components.
- Indicator explorer: `frontend/components/strategy/indicator-explorer.tsx`, `indicator-chart.tsx`, `indicator-sidebar.tsx`, `indicator-config.ts`.
- Signal proof: `frontend/components/strategy/signal-proof-overview.tsx`.
- Backtest/MC evidence: `frontend/components/signals/backtest-mc-panel.tsx`, `price-signals-chart.tsx`, `trade-ledger-table.tsx`, `fan-chart.tsx`, `shuffled-trades-panel.tsx`.

## Known Gaps and Next Improvements

- `12-indicator-explorer.md` was originally written as a deferred design; it now needs to be read as implemented/partial because the indicator chart and sidebar exist.
- Older Signals docs still contain `short`/`medium`/`long` examples. Do not remove those from API history, but document the UI mapping when editing page code.
- `09-api-and-frontend.md` remains the API/data contract. This file is the product/UI contract.
