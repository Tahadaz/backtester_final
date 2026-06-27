# Plan — Portfolio tab: fix empty universe + instrument-kind selector

**Status:** plan only. Implementer: Sonnet.
**Owner:** taha
**Date:** 2026-06-27

## Context

The "Portefeuille" tab on the Signals page (`frontend/components/signals/portfolio-backtest-panel.tsx`)
always shows **"Aucun titre éligible"** in the Univers selector.

### Root cause (confirmed)

The two backend endpoints the panel calls **do not exist** in this repo:

- `GET  /strategy/signal/portfolio-backtest/universe`
- `POST /strategy/signal/portfolio-backtest`

`services/api/app/routers/strategy_signals/_backtest.py` has a module docstring claiming it owns
these "portfolio-backtest" endpoints, but no handler is registered. They were never committed
(`git log -S "n_symbols_qualified"` matches no commit in history, and the deleted twin folder
`backtester_final` didn't have them either). So there is **nothing to port — rebuild from the tests.**

Proof: all 12 tests in `services/api/tests/test_portfolio_backtest_panel.py` currently fail with
`assert 404 == 200`. **These 12 tests are the contract** for the backend work.

The frontend then masks the 404: the `.catch()` in the load effect
(`portfolio-backtest-panel.tsx:195`) sets `universe = []`, and `universeLabel`
(`portfolio-backtest-panel.tsx:298`) renders `"Aucun titre éligible"` for the empty case.
So the message hides a network failure rather than reporting "no qualifying data".

## Decisions (already approved by user)

1. **Kind grouping = region-aware.** Equities split by `market_region`
   (MASI stocks / US stocks / European stocks / Asian stocks), plus Commodity / Forex / Bond / Crypto.
2. **Distinguish empty vs error.** Show "Aucun titre éligible" only on a successful empty response;
   show an explicit error message when the request throws.
3. **Endpoint source = rebuild from the 12 tests** (no existing implementation anywhere).

## Sequencing

Do **Task 1 first** (endpoint), then **Task 2** (error UX), then **Task 3** (kind selector).
The kind filter operates on the universe list, which stays empty until the endpoint returns data.

---

## Task 1 — Implement the two backend endpoints

**File:** `services/api/app/routers/strategy_signals/_backtest.py`
**Router:** `from ._shared import router` (already imported). Router prefix is `/strategy`
(`_shared.py:104`), so the decorators must include the `/signal/` segment:

```python
@router.get("/signal/portfolio-backtest/universe", summary="Eligible WFO-trade universe for the portfolio backtest")
@router.post("/signal/portfolio-backtest", summary="Run the portfolio WFO backtest across selected symbols")
```

Submodule decorators auto-register via `strategy_signals/__init__.py` (it imports `_backtest`),
so no `__init__.py` change is needed.

### Data source

`SignalBacktestRun` (`services/api/app/models.py:1851`). Relevant columns:
`symbol`, `horizon`, `variant`, `source` (`"engine"|"wfo"`), `scope`, `scope_key`,
`computed_at`, and `trades_json` — a list of
`{open_date, close_date, open_price, close_price, direction, pnl_return, bars_held}`.

Query filter for real use: `horizon` (canonicalize via `_require_canonical_signal_horizon` from
`._shared`), `variant`, and `source == "wfo"`. NOTE: the test `_FakeQuery.filter()` ignores all
filter args and returns every fake row, so filtering does not break tests — but the dedupe and
trade math below must be exact.

### Dedupe (both endpoints)

Group rows by `symbol`; keep the row with the **latest `computed_at`** (treat `None` as oldest).
Covered by `test_universe_no_duplicate_symbols` and `test_latest_row_is_kept_on_dedupe`.

### `GET /universe` response

```jsonc
{
  "symbols": [ { "symbol": "ADI", "n_trades": 4, "n_long": 4, "n_short": 0 } ],
  "date_range": { "min": "2024-01-10", "max": "2024-04-10" }   // min open_date / max close_date across all kept rows
}
```

- `long_only` query param: when true, only long trades count toward `n_trades`/eligibility.
- A symbol appears in `symbols` only if it qualifies (see Kelly rule). `date_range` spans the kept rows.
- Tests: `test_universe_no_duplicate_symbols`, `test_universe_returns_date_range`.

### `POST /portfolio-backtest` request

```jsonc
{
  "symbols": [],              // [] or omitted = all eligible; otherwise restrict to these
  "horizon": "weekly",
  "variant": "expanded",
  "initial_capital": 100000,
  "take_profit_pct": 0.05,
  "kelly_multiplier": 0.5,
  "long_only": true,
  "start_date": "2024-01-01", // optional, inclusive — filters by trade open_date
  "end_date": "2024-12-31"    // optional, inclusive
}
```

### `POST /portfolio-backtest` response

Must match the frontend types in `frontend/lib/api.ts:6780-6830`
(`PortfolioBacktestResult`, `PortfolioBacktestTrade`, `PortfolioBacktestSymbolStats`):

```jsonc
{
  "equity_curve": [ { "date": "YYYY-MM-DD", "equity": 100000.0 } ],
  "metrics": { "total_return": .., "cagr": .., "sharpe": .., "max_drawdown": ..,
               "final_equity": .., "n_symbols": .., "n_trades": .., "tp_applied_pct": .. },
  "per_symbol": [ { "symbol": "ADI", "kelly_fraction": .., "kelly_pct": .., "n_trades": ..,
                    "n_long": .., "n_short": .., "win_rate": .., "avg_win_pct": .., "avg_loss_pct": .. } ],
  "n_symbols_qualified": 1,
  "warnings": [],
  "trades": [ /* PortfolioBacktestTrade, see required fields below */ ],
  "trades_truncated": false,                 // true when capped at 2000
  "period": { "start": .., "end": .., "requested_start": .., "requested_end": .. }
}
```

Each trade (test `test_trades_have_required_fields`) MUST include exactly these keys:
`symbol, direction, open_date, close_date, open_price, close_price, pnl_return,
effective_return, tp_applied, position_size, pnl_mad, executed`.

### Backtest math (the contract)

1. **Per-symbol Kelly** from that symbol's deduped trades:
   `win_rate`, `avg_win`, `avg_loss` → Kelly fraction `f = W - (1-W)/R` (R = avg_win/|avg_loss|),
   clamped to `[0, 1]`; applied size = `kelly_multiplier * f`.
   Requires **≥ 3 trades** to qualify; fewer → `kelly = 0`, symbol does not qualify
   (`test_no_executed_trades_when_kelly_zero`: `n_symbols_qualified == 0` and a non-empty `warnings`).
2. **Take-profit:** if `pnl_return >= take_profit_pct`, set `effective_return = take_profit_pct`,
   `tp_applied = true`; else `effective_return = pnl_return`, `tp_applied = false`.
3. **Date filter:** drop trades whose `open_date < start_date` or `open_date > end_date`
   (`test_date_filter_start_date`, `test_date_filter_end_date`).
4. **Sequential capital simulation** ordered by `open_date` across all selected symbols:
   `position_size = round(kelly_size * current_capital)`; if capital insufficient set
   `executed = false`, `position_size = 0`, `pnl_mad = 0`; else
   `pnl_mad = position_size * effective_return` and roll capital forward.
5. **Equity / metrics:** build `equity_curve` from running capital; `final_equity = initial + Σ pnl_mad`.
   **Invariant:** `Σ pnl_mad (executed) == final_equity - initial_capital` within 1.0 MAD
   (`test_pnl_mad_sums_to_equity_delta`).
6. **period:** `requested_start/end` echo the request; `start/end` are the realized first/last executed
   trade dates (`test_period_returned_in_response`).
7. Cap `trades` at 2000, set `trades_truncated` accordingly.

### Verify

```
python -m pytest services/api/tests/test_portfolio_backtest_panel.py -q   # 12 pass
```

---

## Task 2 — Empty vs. error UX

**File:** `frontend/components/signals/portfolio-backtest-panel.tsx`

- Add `const [universeError, setUniverseError] = useState<string | null>(null)`.
- In the load effect (~line 178): on success `setUniverseError(null)`; in `.catch()` set
  `setUniverseError("Erreur de chargement de l'univers")` **instead of** silently emptying.
- `universeLabel` (~line 298): when `universeError` is set, show the error string; keep
  "Aucun titre éligible" only for a genuine successful empty (`universe.length === 0 && !universeError`).
- Surface `universeError` near the selector (reuse the existing `error` paragraph styling at ~line 583).

No new test required; this is a UX guard. Optional: a small RTL test if convenient.

---

## Task 3 — Two-level instrument-kind selector

**File:** `frontend/components/signals/portfolio-backtest-panel.tsx`
(the Univers `Popover`, ~lines 484-560).

No backend change. The panel already loads `useMarketCatalog()` (line 157); `MarketCatalogRow`
carries `asset_type`, `market_region`, `asset_class` (`frontend/lib/api.ts:2495-2497`).

### Kind derivation (mirror the backend)

Add a helper that maps a catalog row → kind label, mirroring `dashboard_group_label()` in
`services/api/app/services/market_universe.py:365` so labels stay consistent app-wide:

- `asset_class === "index"` → `"Index"`
- equity + `market_region`: `masi`→"MASI stocks", `us`→"US stocks", `european`→"European stocks",
  `asian`→"Asian stocks", else "Other stocks"
- else by `asset_type`: `commodity`→"Commodity", `forex`→"Forex", `bond`→"Bond", `crypto`→"Crypto"

Build a `kindOf: Map<symbol, kindLabel>` from `catalog`, analogous to the existing
`displayNameOf` map (line 158).

### UI

- **Level 1 — Kind:** above the search input (~line 500), add a multi-select of the kinds present
  in the current universe (chips or `ToggleGroup`/`Select`). Default: all kinds selected.
  State: `const [selectedKinds, setSelectedKinds] = useState<Set<string>>(...)`.
- **Level 2 — Instrument:** the existing checkbox list, but `filteredUniverse` (line 224) also
  filters to symbols whose `kindOf` is in `selectedKinds` (in addition to the text query).
- Keep "Tout / Aucun" working within the visible (kind-filtered) set.
- "Select all eligible" semantics for the run (line 273, `allSelected`) should still compare against
  the full universe, not the kind-filtered subset — re-check this after adding the filter.

### Reuse reference

`frontend/components/strategy/stock-universe-selector.tsx` already implements sector-based
multi-select filtering — same shape, key on "kind" instead of "sector".

### Verify

`cd frontend && npm run lint && npx tsc --noEmit` (0 TS errors), then click through the panel.

---

## Out of scope / notes

- Salvaged from the deleted `backtester_final` folder:
  `C:\Users\taha\Downloads\backtester_final_uncommitted_backup.patch` contains a worth-porting
  `services/worker/worker.py` Redis-resilience hunk (retry/keepalive/health-check). Separate task.
