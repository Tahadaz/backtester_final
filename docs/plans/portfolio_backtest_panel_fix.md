# Plan — Fix Portfolio Backtest panel (dup-key crash + results presentation)

**For:** Sonnet (implementer)
**Scope:** `Portefeuille` tab of the signals page.
**Status:** plan only — do NOT skip backend; do backend first, then frontend.

---

## Context / files

- Frontend panel: `frontend/components/signals/portfolio-backtest-panel.tsx`
- Frontend API client + types: `frontend/lib/api.ts`
  - `PortfolioBacktestResult`, `PortfolioBacktestSymbolStats` (~line 6780)
  - `runPortfolioBacktest` (~6809), `getPortfolioBacktestUniverse` (~6832)
  - `PortfolioBacktestUniverseSymbol` (~6825)
- Backend endpoints: `services/api/app/routers/strategy_signals.py`
  - `_PortfolioBacktestRequest` (8752)
  - `_portfolio_backtest_metrics` (8779)
  - `signal_portfolio_backtest` POST `/signal/portfolio-backtest` (8818)
  - `signal_portfolio_backtest_universe` GET `/signal/portfolio-backtest/universe` (8966)
- Model: `services/api/app/models.py` → `SignalBacktestRun` (1851). Trade rows live in
  `trades_json`: list of `{open_date, close_date, open_price, close_price, direction, pnl_return, bars_held}`.
  Row has `computed_at`, `updated_at` timestamps.

---

## Root cause of the `Encountered two children with the same key, "ADI"` crash

`SignalBacktestRun`'s natural key (`uq_sbr_natural_key`) includes `window_start`, `window_end`,
`cooldown_bars`. So for one `(symbol, horizon, source=wfo, scope=global, variant)` there can be
**multiple succeeded rows** (different WFO windows / re-runs / data_as_of).

Both backend endpoints iterate `query.all()` and emit **one entry per row**, not per symbol:
- `signal_portfolio_backtest_universe` → universe list has duplicate symbols (ADI ×N) →
  frontend `filteredUniverse.map(... key={row.symbol})` collides → the React crash.
- `signal_portfolio_backtest` → `per_symbol` gets duplicate symbol entries AND `all_trades`
  double-counts the same symbol's trades across windows (silent data bug, not just cosmetic).

**Fix = dedupe to one row per symbol on the backend** (canonical: latest by `computed_at`
desc, tie-break `updated_at` desc, then `id` desc). Add a defensive frontend dedupe too.

---

## Part A — Fix the crash + double-count (backend first)

### A1. `signal_portfolio_backtest_universe` (strategy_signals.py:8966)
After fetching `rows`, collapse to one row per symbol before building `universe`:

- Sort rows by `(computed_at or updated_at)` desc, `id` desc.
- Keep first occurrence per `row.symbol` (use a `seen: set[str]`).
- Build `universe` from the deduped rows (existing per-row logic unchanged).

### A2. `signal_portfolio_backtest` (strategy_signals.py:8818)
Same dedupe applied to `rows` before the `for row in rows:` aggregation loop, so
`per_symbol` has exactly one entry per symbol and `all_trades` is not double-counted.

> Implementation note: extract a small helper `_latest_rows_per_symbol(rows)` near the top of
> the portfolio section and call it from both endpoints to avoid drift.

### A3. Frontend defensive dedupe (portfolio-backtest-panel.tsx)
Even after the backend fix, make the UI robust:
- In the `getPortfolioBacktestUniverse(...).then((rows) => ...)` handler (line ~116), dedupe
  `rows` by `symbol` before `setUniverse` (keep first).
- This guarantees the `key={row.symbol}` map (line 290) can never collide again.

**Acceptance:** Open Portefeuille tab with the dataset that produced ADI twice → no console
error; universe picker shows each symbol once; trade counts are not doubled.

---

## Part B — Results presentation (trades ledger, period control, per-signal drill-down)

The user wants: (1) a detailed list of trades, (2) ability to set the backtest period, and
(3) per-signal (per-symbol) trades + results.

### B1. Backend: return the trades + effective period

`signal_portfolio_backtest` already builds `all_trades` internally but discards it. Change the
response (line 8957) to also return the trade ledger and the effective period.

1. **Request model** (`_PortfolioBacktestRequest`, 8752) — add optional period bounds:
   ```python
   start_date: str | None = None   # "YYYY-MM-DD" inclusive, on open_date
   end_date: str | None = None     # "YYYY-MM-DD" inclusive, on open_date
   ```
2. **Filter** trades by `open_date` within `[start_date, end_date]` when provided, right after
   `all_trades` is assembled and before the sort (8908). Keep it string-comparison safe since
   dates are ISO `YYYY-MM-DD`.
3. **Per-trade position PnL in MAD**: in the equity simulation loop (8914+), the actual capital
   committed to each trade is `position_size`. Capture realized MAD pnl per trade so the ledger
   can show money, not just %. Attach back onto each `all_trades` entry:
   - `position_size` (MAD committed)
   - `pnl_mad = position_size * effective_return`
   - mark trades skipped for insufficient capital (the `position_size < 1.0` continue at 8931)
     with `executed: false` so the UI can distinguish "signal fired but no capital".
4. **Response additions** (8957):
   - `"trades": [...]` — each: `symbol, direction (1/-1), open_date, close_date, open_price,
     close_price, pnl_return, effective_return, tp_applied, position_size, pnl_mad, executed`.
     Sort by `open_date` then `symbol` (already sorted). Cap length defensively (e.g. 2000) and
     add a `trades_truncated: bool` if capped.
   - `"period": {"start": <first open_date>, "end": <last close_date>, "requested_start":
     start_date, "requested_end": end_date}` so the UI can show the realized window.
5. **Universe → date bounds**: extend the universe endpoint response (or add the bounds to the
   backtest response only) so the period picker can default/clamp to the available data. Minimal
   approach: in `signal_portfolio_backtest_universe`, also compute and return
   `"date_range": {"min": <earliest open_date over universe>, "max": <latest close_date>}` so
   the frontend can bound the date inputs. (Acceptable to skip if costly; then the picker is
   unbounded and the realized `period` from the backtest response is the source of truth.)

### B2. Frontend types (`frontend/lib/api.ts`)
- Add `PortfolioBacktestTrade` interface mirroring the new `trades` item.
- Extend `PortfolioBacktestResult` with `trades: PortfolioBacktestTrade[]`,
  `trades_truncated?: boolean`, and `period?: { start, end, requested_start, requested_end }`.
- Extend `runPortfolioBacktest` body type with `start_date?`, `end_date?`.
- If implementing B1.5, extend `getPortfolioBacktestUniverse` return / a companion type with
  `date_range`.

### B3. Frontend UI (`portfolio-backtest-panel.tsx`)

**Period control** (in the config Card, alongside Capital/Sens/Univers, ~line 206):
- Two date inputs `Début` / `Fin` (`<Input type="date">`), stored in state, passed to
  `runPortfolioBacktest` as `start_date`/`end_date`. Clamp to `date_range` if available.
- Show the realized period from `result.period` near the KPIs (e.g. a small caption
  "Période : 2021-03-01 → 2025-12-31").

**Trades ledger** (new Card after the "Par titre" card, ~line 465):
- Table columns: Ticker, Sens (Long/Short badge), Ouverture (date), Clôture (date), Prix ouv.,
  Prix clôt., Rendement %, TP badge when `tp_applied`, Capital (MAD), PnL (MAD, green/red).
- Sortable by date / return / pnl (reuse the dropdown-sort pattern already used on the results
  page if present, else a simple `useState` sort key + comparator).
- **Filter by symbol**: a select/segmented control populated from `result.per_symbol` symbols
  + an "Tous" option → filters the ledger to a single signal's trades (this is the "per signal
  trades" request). Default "Tous".
- Distinguish non-executed signals (`executed === false`) with a muted row + "Capital épuisé"
  tag so users see why a fired signal produced no PnL.
- Paginate or cap the visible rows (e.g. 200 with "voir plus") if `trades` is large; surface
  `trades_truncated`.

**Per-symbol card** (existing, line 421): make each row clickable to set the ledger's symbol
filter, so "Par titre" → click ADI → ledger shows only ADI trades. Keeps per-signal results
and per-signal trades in one flow.

### B4. Labels
All UI strings in French to match the existing panel ("Période", "Liste des trades",
"Sens", "Ouverture", "Clôture", "Capital engagé", "Gain/Perte", "TP", "Capital épuisé").

---

## Test / verify
- Backend: add/extend a router test for `signal_portfolio_backtest` asserting (a) one
  `per_symbol` entry per symbol given duplicate `SignalBacktestRun` window rows, (b) `trades`
  present and date-filtered when `start_date`/`end_date` set, (c) `pnl_mad` sums roughly to
  `final_equity - initial_capital` for executed trades.
- Backend: universe test asserting no duplicate symbols given duplicate window rows.
- Frontend: `npm run typecheck` clean; manually verify no React key warning, period inputs
  drive the run, ledger filters by symbol.

## Ordering
1. A1 + A2 + A3 (stop the crash + the double-count).
2. B1 backend (trades + period + pnl_mad).
3. B2 types.
4. B3/B4 UI.
5. Tests.
