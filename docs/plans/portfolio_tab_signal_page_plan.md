# Plan — Portfolio (Portefeuille) tab improvements on the Signals page

**Audience:** Sonnet (implementer). This is a plan only — do not treat it as done code; implement each task and run the build/tests.

**Scope:** The "Portefeuille" tab of the Signals page. Four problems reported by the user:

1. The result stats (Rendement, CAGR, Sharpe, MaxDD…) render stacked vertically instead of in a grid — looks bad.
2. Add a **plein écran** (fullscreen) mode that hides the analysis-mode banner and the left stock list so the panel uses the whole viewport.
3. Navigation is hard. Add a **per-stock view**: for each traded symbol show its own equity curve, a price chart with the executed trades marked (buy/sell/short/cover), a per-stock metrics row, and the detailed trades ledger filtered to that symbol.
4. The **Long only / Long & Short** toggle appears not to work.

## Key files

| File | Role |
|------|------|
| `frontend/components/signals/portfolio-backtest-panel.tsx` | The whole portfolio tab UI (config form, KPIs, equity curve, per-symbol table, trades ledger). All four fixes live mostly here. |
| `frontend/components/strategy/signals-view-layout.tsx` | Outer layout: left `StockSidebar`, topbar, tabs incl. `portfolio`. Relevant to fullscreen (issue 2). |
| `frontend/app/signals/page.tsx` | Renders `SignalsAnalysisModeSwitcher` banner + the view. Relevant to fullscreen banner. |
| `frontend/app/globals.css` | `.kpi4` grid rule is scoped to `.claude-backtest-shell` (root cause of issue 1). |
| `frontend/lib/api.ts` | `runPortfolioBacktest`, `getPortfolioBacktestUniverse`, `PortfolioBacktestResult/Trade/SymbolStats`, `getStockOhlcvHistory`, `OhlcvHistory`. |
| `frontend/hooks/use-api.ts` | `useStockOhlcvHistory(symbol, { timeframe })` SWR hook. |
| `frontend/components/signals/price-signals-chart.tsx` | Reusable candlestick chart with `tradeMarkers` support. |
| `frontend/lib/trade-marker-utils.js` | `normalizeTradeMarkers(rows)` — maps trade rows to buy/sell/short/cover markers. |
| `services/api/app/routers/strategy_signals.py` | Backend `/signal/portfolio-backtest` (line ~8844) and `/universe` (line ~9047). Long/short logic is already correct here — see issue 4. |

---

## Issue 1 — Stats stacked vertically (grid broken)

**Root cause.** `portfolio-backtest-panel.tsx` wraps the StatCards in `<div className="kpi4">` (lines ~480 and ~509). But the grid rule in `globals.css` is scoped:

```css
.claude-backtest-shell .kpi4 { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 10px; }
```

The portfolio panel is rendered inside the Signals tab content (`signals-view-layout.tsx` → `TabsContent value="portfolio"`), **not** inside any `.claude-backtest-shell`. So `.kpi4` matches nothing and the cards fall back to block layout (stacked). The `.claude-stat` card styling itself is global (defined at globals.css ~257) and works fine — only the grid wrapper is dead.

**Fix.** Stop relying on the scoped `kpi4` class. Replace both `<div className="kpi4">` wrappers with explicit Tailwind grid utilities:

```tsx
<div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
```

Apply to both KPI rows (the 4-metric row and the second 4-metric row). This is responsive (2 cols on narrow, 4 on ≥sm) and self-contained. Do **not** add a new `.claude-backtest-shell` wrapper — that class carries unrelated layout assumptions.

---

## Issue 4 — Long only / Long & Short toggle "not working"

Fix this before issue 3 because the per-stock view depends on a trustworthy `result`.

**The backend is correct.** In `strategy_signals.py`:
- `/universe` (line ~9092): counts `n_long`/`n_short`, qualifies on `n_long` when `long_only` else `n_long+n_short`.
- `/portfolio-backtest` (line ~8885): filters `direction > 0` when `long_only` else `direction != 0`.

So the toggle *does* change what the backend returns.

**The real bug is frontend stale state.** In `portfolio-backtest-panel.tsx`:
- The `<ToggleGroup>` (lines ~311-327) calls `setLongOnly(...)` correctly.
- The `useEffect` on `[horizon, longOnly]` (lines ~128-161) reloads the universe and resets `selected`.
- **But `result` is never cleared.** After the user has run a backtest, flipping the toggle reloads the universe silently while the KPIs / equity curve / ledger keep showing the *previous* direction's results. Nothing visibly changes → the button looks broken.

**Fix (minimal, correct):** in the `[horizon, longOnly]` effect, clear the displayed result and error so the stale output disappears and the user is prompted to re-run:

```tsx
useEffect(() => {
  // ...existing universe reload...
  setResult(null)
  setError(null)
}, [horizon, longOnly])
```

Place the `setResult(null)` / `setError(null)` at the top of the effect body (before the async fetch) so the UI immediately drops back to the pre-run empty state when direction changes.

**Optional UX upgrade (do this too if cheap):** after the universe finishes reloading on a direction flip, if a backtest had previously been run, auto-rerun via `handleRun()` so the user sees fresh numbers without a second click. Guard with a ref so it only auto-reruns when the change was user-initiated (not the initial mount). If this adds meaningful complexity, ship the minimal fix above and skip auto-rerun.

**Data note (decided).** The user confirmed WFO signals **do** generate short trades, so Long & Short must produce materially different results from Long only. Treat this purely as the stale-state bug above — clearing `result`/`error` on direction change is the fix. No "zero shorts" note is needed. (If, during testing, a given horizon/variant happens to show `0S` everywhere in the universe popover, that's a data-coverage artifact for that slice, not a toggle bug — leave it.)

---

## Issue 2 — Plein écran (fullscreen) mode

**Goal.** A toggle that expands the portfolio panel to fill the viewport, hiding: the analysis-mode switcher banner (`page.tsx` `SignalsAnalysisModeSwitcher`), the left `StockSidebar`, the layout topbar, and the symbol strip.

**Decided approach — self-contained overlay inside the panel.** (User chose the overlay over a true layout collapse.) Do **not** thread fullscreen state up through `shared-signals-view` → `signals-view-layout` → `page`. Keep it local to `portfolio-backtest-panel.tsx` using a fixed-position overlay. This avoids touching the layout plumbing and works regardless of how the panel is mounted.

Implementation:

1. Add state: `const [fullscreen, setFullscreen] = useState(false)`.
2. Add a toggle button in the config card header (next to the `CardTitle` "Backtest Portefeuille — Signaux WFO"), using `lucide-react` `Maximize2` / `Minimize2` icons:
   ```tsx
   <Button type="button" variant="ghost" size="sm" className="h-7 gap-1.5 px-2 text-xs"
           onClick={() => setFullscreen(v => !v)}>
     {fullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
     {fullscreen ? "Quitter le plein écran" : "Plein écran"}
   </Button>
   ```
3. Wrap the panel's root in a conditional container. When `fullscreen`, render the existing tree inside a fixed overlay:
   ```tsx
   <div className={cn(
     "space-y-4",
     fullscreen && "fixed inset-0 z-50 overflow-y-auto bg-background p-4",
   )}>
     {/* existing content */}
   </div>
   ```
   Import `cn` from `@/lib/utils`.
4. Add an `Escape` key handler to exit fullscreen:
   ```tsx
   useEffect(() => {
     if (!fullscreen) return
     const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setFullscreen(false) }
     window.addEventListener("keydown", onKey)
     return () => window.removeEventListener("keydown", onKey)
   }, [fullscreen])
   ```
5. Optional polish: when `fullscreen`, set `document.body.style.overflow = "hidden"` in the same effect and restore on cleanup to prevent background scroll.

`z-50` over a `fixed inset-0 bg-background` overlay covers the banner, sidebar, topbar and strip without needing to know about them. The plotly/lightweight charts inside resize to the wider container automatically.

> Follow-up only (not in scope now): a true *layout* collapse would lift state into `signals-view-layout.tsx`, hide the `ResizablePanel` sidebar, and hide `SignalsAnalysisModeSwitcher` in `page.tsx`. The user chose the overlay for this delivery.

---

## Issue 3 — Per-stock detail view

**Goal.** Make the results navigable per traded symbol. Today there's a global equity curve, a "Par titre" summary table (clicking a row only filters the ledger), and one big ledger. Add a dedicated per-stock view.

### Data available (no backend change needed)
- `result.per_symbol[]`: `{ symbol, kelly_pct, n_trades, n_long, n_short, win_rate, avg_win_pct, avg_loss_pct }`.
- `result.trades[]`: `{ symbol, direction, open_date, close_date, open_price, close_price, pnl_return, effective_return, tp_applied, position_size, pnl_mad, executed }`.
- OHLCV per symbol via `useStockOhlcvHistory(symbol, { timeframe })` → `OhlcvHistory { bars: OhlcvBar[] }`. Check `OhlcvBarSchema` for field names (date/open/high/low/close/volume) and map accordingly.

### UX structure
Introduce a `selectedStock: string | null` state in the panel. Render mode:
- **List mode** (`selectedStock === null`): keep the global KPIs + global equity curve + the existing "Par titre" table, but change the row click to **open the per-stock view** (`setSelectedStock(s.symbol)`) instead of only filtering the ledger.
- **Detail mode** (`selectedStock !== null`): show a "← Retour" button and the per-stock sections below.

### Per-stock detail sections
1. **Header / metrics row** — reuse `StatCard` in the same Tailwind grid from issue 1. Pull the row from `per_symbol.find(s => s.symbol === selectedStock)`: Trades, Win Rate, Moy. gain, Moy. perte, ½-Kelly, and a computed **PnL total** = sum of `pnl_mad` over that symbol's executed trades.

2. **Per-stock equity curve** — compute client-side from the symbol's executed trades. Sort the symbol's trades by `close_date`, accumulate `pnl_mad`, and plot cumulative realized PnL (MAD) vs `close_date`. Reuse the existing `buildEquityPlot` pattern (Plotly via `PlotlyChart`) but plotting cumulative PnL rather than % of initial capital. Label it clearly (e.g. "PnL réalisé cumulé — {symbol}"). Skip if fewer than 2 closed trades.

3. **Price chart with trade markers** — reuse `PriceSignalsChart`:
   - Fetch bars with `useStockOhlcvHistory(selectedStock)`.
   - Map bars → `dates`, `open`, `high`, `low`, `close` arrays (the component takes parallel arrays; see its `PriceSignalsChartProps`).
   - Build `tradeMarkers` from the symbol's trades. `normalizeTradeMarkers` (in `lib/trade-marker-utils.js`) accepts rows and reads `marker_label` or `side`/`direction`+`position`. Emit **two rows per trade** with an explicit `marker_label` so kind detection is unambiguous:
     - open: `{ date: open_date, marker_label: direction > 0 ? "Achat" : "Short" }`
     - close: `{ date: close_date, marker_label: direction > 0 ? "Vente" : "Cover" }`
     (`markerKindFromLabel` maps buy/achat→buy, sell/vente→sell, short→short, cover→cover.) Pass the raw rows array as `tradeMarkers`; the component normalizes internally.
   - Pass `position` (the prop) as all-null or omit if not needed; the markers carry the trade events. Set a reasonable `height` (e.g. 360).

4. **Per-stock trades ledger** — reuse the existing ledger table markup but filtered to `selectedStock`. The panel already has `ledgerSymbolFilter` + sorting machinery (`filteredTrades`, `SortHeader`, paging). Simplest integration: when entering detail mode, set `ledgerSymbolFilter = selectedStock` and render the existing ledger card below the detail sections; when returning to list mode, reset to `"__all__"`. Keep the sort headers and "Voir plus" paging working.

### Notes
- Keep all copy in **French** to match the existing panel.
- OHLCV fetch is per selected symbol — only fetch in detail mode (hook key is null when `selectedStock` is null, which `useStockOhlcvHistory` already guards via `symbol ? ... : null`).
- If the OHLCV history is empty/unavailable for a symbol, show a muted fallback ("Données de prix indisponibles pour {symbol}.") instead of a broken chart.
- Date alignment: trade `open_date`/`close_date` are `YYYY-MM-DD`; OHLCV bar dates should be sliced to the same 10-char key for marker matching (the marker util already slices to 10).

---

## Suggested implementation order
1. **Issue 1** (grid) — trivial, immediate visual win.
2. **Issue 4** (toggle stale-state) — clear `result`/`error` on direction change; verify short-trade data; optional auto-rerun + zero-shorts note.
3. **Issue 2** (fullscreen overlay) — local state + fixed overlay + Esc handler.
4. **Issue 3** (per-stock view) — the largest piece; `selectedStock` state, detail sections, reuse `PriceSignalsChart` + `normalizeTradeMarkers` + `useStockOhlcvHistory`.

## Verification
- `cd frontend && npm run build` (or the project's typecheck/lint script) — expect 0 TS errors.
- Manual: open Signals → Portefeuille. Confirm (1) KPIs render in a 4-up grid; (2) toggling Long only / Long & Short clears stale results and reloads the universe; (3) Plein écran covers banner + sidebar, Esc exits; (4) clicking a symbol in "Par titre" opens its equity curve, price chart with buy/sell markers, metrics, and filtered ledger; "← Retour" returns to the list.
- No backend changes are required; do not modify `strategy_signals.py` unless the short-data verification reveals a genuine backend gap (it should not).
