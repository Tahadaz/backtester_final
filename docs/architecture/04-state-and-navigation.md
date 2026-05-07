# 04 — Frontend State and Navigation

How the four pages share state, navigate between each other, and reuse components.

---

## Navigation Model

The application uses a `DynamicHeader` component that renders different navigation bars depending on the current route:

- **`SignalsHeader`** — displayed on `/data`, `/signals`, `/strategy`, `/backtest` routes
  - 4 nav items: **Données** | **Signaux** | **Stratégie** | **Backtest**
  - Active page is highlighted
  - This is the "signal engine app" navigation

- **`AppHeader`** — displayed on other routes (dashboard, results, defaults discovery, etc.)
  - 7 nav items for the broader backtester application

The signal engine app is a cohesive 4-page flow within the larger platform.

---

## Shared State

### Symbol Selection

The `selectedSymbol` state is the primary shared context between pages.

| Page | How symbol is set | How symbol is used |
|------|------------------|-------------------|
| Data | Click stock in catalog table | Opens stock detail panel (OHLCV chart, availability calendar) |
| Signal | Click stock in sidebar | Loads ensemble scores, indicator explorer, variant detail |
| Strategy | Stock tabs in basket | Per-stock strategy configuration |
| Backtest | Inherited from strategy | Per-stock WFO results |

**Cross-page carry:** When navigating from Signal to Strategy, the selected symbol can be passed as a URL parameter (`/strategy?symbol=IAM`) to pre-select the stock tab.

### Horizon

Each page has its own horizon state, defaulting to `"medium"`:

| Page | Horizon role |
|------|-------------|
| Signal | Controls which OOS windows and parameter ranges the pipeline uses |
| Strategy | Part of the saved strategy config, selected inside Signal Construction |
| Backtest | Controls WFO window geometry (IS/OOS sizes) |

Horizons are not synchronized across pages — each page's horizon is independent. A user may explore signals at "short" horizon but configure a "medium" strategy.

### Timeframe

Fixed at `"1D"` (daily bars) in v1. Passed to all API calls but not user-configurable.

---

## Page Transitions

### Signal → Strategy

**Trigger:** User has explored indicators and wants to build a strategy.

**Flow:**
1. User clicks "Configurer une stratégie" (or similar CTA) on signal page
2. Navigate to `/strategy?symbol=IAM` (carry selected symbol)
3. Strategy page opens with the stock pre-selected in the basket
4. Signal findings (which families are strong, which parameter ranges) inform the user's choices — but are NOT automatically applied

**What transfers:** Only the selected symbol. The user manually configures strategy parameters based on what they learned on the signal page.

### Strategy → Backtest

**Trigger:** User has completed strategy configuration and wants to evaluate it.

**Flow:**
1. User clicks "Open in Backtest" on strategy review section
2. System requires strategy to be saved first (explicit save)
3. Navigate to `/backtest?strategy_id=abc123`
4. Backtest page loads the strategy and detects WFO-flagged parameters
5. User configures WFO start date, cost model, then launches

**What transfers:** `BacktestHandoff` payload with full strategy definition (see `02-data-contracts.md`).

### Backtest → Strategy (Revision)

**Trigger:** User reviews backtest results and wants to modify the strategy.

**Flow:**
1. User reviews WFE, OOS windows, sizing results
2. Clicks "Réviser la stratégie" to go back to strategy page
3. Navigate to `/strategy?id=abc123` (load the same strategy)
4. Optionally clicks "Appliquer le sizing" to copy Kelly values

**What transfers:**
- Navigation only (strategy loads from its saved state)
- Kelly sizing transfer is an explicit user action, not automatic

### Data → Signal (Implicit)

The data page does not link directly to the signal page. The connection is implicit: fresh data on the data page produces accurate signals on the signal page. If a stock's data is stale, signals may be inaccurate — the data page's freshness badges warn about this.

---

## Component Reuse

Several UI components appear across multiple pages:

| Component | File | Used on |
|-----------|------|---------|
| `SignalScoreBar` | `components/strategy/signal-score-bar.tsx` | Signal page (consensus overview), Strategy page (signal construction preview) |
| `Speedometer` | `components/strategy/speedometer.tsx` | Signal page (family overview) |
| `HorizonSelector` | `components/strategy/horizon-selector.tsx` | Signal page, Strategy page Signal Construction section |
| `StockSidebar` | `components/strategy/stock-sidebar.tsx` | Signal page (with batch scores) |
| `PipelineStepper` | `components/strategy/pipeline-stepper.tsx` | Signal page (family drilldown), Variant detail page |
| `FreshnessBadge` | `components/data/freshness-badge.tsx` | Data page catalog |
| `PlotlyChart` | `components/run/plotly-chart.tsx` | Variant detail, Backtest results |

### Design System Consistency

All pages use the same:
- Color palette for signal labels (emerald/green/gray/orange/red for Achat Fort → Vente Forte)
- Card-based layouts with consistent spacing
- French language labels throughout
- Tailwind CSS utilities

---

## URL Structure

```
/data                          — Data page (market data management)
/signals                       — Signals page (consensus + indicator explorer)
/signals/variant/[id]          — Variant detail page
/strategy                      — Strategy page
/strategy?symbol=IAM           — Strategy page with pre-selected stock
/strategy?id=abc123            — Strategy page loading saved strategy
/backtest                      — Backtest page
/backtest?strategy_id=abc123   — Backtest page with pre-loaded strategy
```

Query parameters are the primary mechanism for cross-page state transfer. They are bookmarkable and shareable.

---

## Cross-Links

- Navigation components: `quant-backtesting-frontend/components/layout/`
- Signal page components: `quant-backtesting-frontend/components/strategy/`
- Data page components: `quant-backtesting-frontend/components/data/`
- API hooks: `quant-backtesting-frontend/hooks/use-api.ts`
- Type definitions: `quant-backtesting-frontend/lib/api.ts`
