# Implementation brief — WFO fold-winner backtest panel (train/test), all categories incl. S/R

Audience: implementing agent (Codex). This brief is self-contained: all design decisions are
final and all referenced code has been verified to exist at the stated locations (line numbers
are approximate anchors — search by symbol name if drifted).

## 1. Feature summary

In the WFO tab of the technical-signal page (frontend `WfoEvidenceTab`), each fold row shows a
winning indicator and its train/test date ranges, but there is no way to inspect how that winner
behaved in those periods. The variant-details page (`frontend/app/signals/variant/[id]/page.tsx`,
"Comparaison" tab → `VariantDetailPanel`) already has the desired UX: a period selector where each
period shows Sharpe / PnL(100k) / n_trades, price+equity+drawdown Plotly charts, and a trade
ledger — but its periods are the pipeline's fixed OOS windows, and its backend endpoint
(`POST /signal/variant-backtest`) accepts no date range.

**Requirement (user-confirmed):**
- Every fold row in the WFO tab becomes **expandable inline** into a details panel for that
  fold's winner.
- The panel has exactly **two selectable periods: the fold's train range and its test range**,
  same UX as `VariantDetailPanel`'s period selector (buttons with dates + sharpe coloring;
  metric chips; chart tabs; trade ledger).
- Works for **all folds** and **all five categories**: `tendance`, `momentum`, `oscillation`,
  `volume`, and `support_resistance`. For S/R the fold winner is a support+resistance **line
  pair**, not a variant — its backtest uses the existing touch-pair simulator.
- Scope is the **in-tab panel only**. The full-page route `frontend/app/signals/wfo-detail/page.tsx`
  is explicitly a follow-up — do not touch it.

Phases 1 and 2 (backend) are independent of each other; Phase 3 (frontend standard) depends on 1;
Phase 4 (frontend S/R) depends on 2 and 3.

## 2. Verified architecture facts (do not re-derive; trust these anchors)

Backend:
- `core/quant_core/signal_engine/oos_eval.py::evaluate_variant_oos` (~line 355) computes the
  variant signal over the **full** close array, then per OOS window slices
  `[test_start:test_end]` and computes metrics (~lines 408–446): cooldown via `apply_cooldown`,
  long-only positions via `signal_to_long_only_positions`, net returns with cost applied on
  signal changes, `sharpe_ratio`, `pnl = 100_000 * total_return`. This block is the metric
  ground truth to reuse.
- `core/quant_core/signal_engine/variant_detail.py::compute_variant_detail` (~line 320) accepts
  **any** `list[OOSWindowResult]` and builds `per_window` entries (`window_index, start_date,
  end_date, sharpe, pnl, pnl_100k, n_trades, is_valid, plot, equity_plot, drawdown_plot, trades`)
  purely from each window's `test_start/test_end` indices. It has a `force_valid_windows: bool`
  parameter (verified, ~line 332). Synthetic windows work.
- Standard fold dicts are built by `services/worker/tasks/wfo_signal_batch.py::_build_folds_json`
  (~line 232) and normalized by
  `services/api/app/services/wfo_folds.py::normalize_wfo_folds_json`. Fields per fold:
  `index`, `train_start/train_end/oos_start/oos_end` (fold-local), `*_idx`, `*_abs_idx`
  (absolute), `train_start_date/train_end_date/oos_start_date/oos_end_date` (end dates are the
  date of the **last bar inside** the window), `is_return`, `oos_return`, `oos_sharpe`,
  `winner_variant_id`, `winner_description`, `winner_params`, `winner_prom`, `profile_passes`,
  `profile_reason`, `oos_profitable`.
- Persisted WFO rows live in DB table `WfoSignalSummary` keyed `(symbol, horizon, category,
  variant)` with `folds_json`, `config_json` (contains `families`, `cost_bps`,
  `train_bars/oos_bars/step_bars`), `representatives_json`, `fragility_json`. Read pattern:
  see `get_wfo_detail` in `services/api/app/routers/wfo_signals.py` (router prefix
  `/strategy/wfo`).
- Candidate pool regeneration:
  `core/quant_core/signal_engine/wfo_signal.py::build_category_candidate_grid(category, horizon,
  families)` (~line 110) deterministically rebuilds the variant pool; look up
  `winner_variant_id` there to get the variant definition.
- Data loading helpers `load_ohlcv_for_symbol`, `_clean_ohlcv`, `_truncate_for_horizon`, and
  the in-process cache pattern `_BACKTEST_CACHE` live in/under
  `services/api/app/routers/strategy_signals/` (`_shared`, `_variants.py`).
- S/R WFO: `core/quant_core/signal_engine/sr_wfo.py` — `run_sr_wfo` (~line 354),
  `sr_window_plan` (~line 87), `simulate_touch_pair(close, high, low, open_, support_series,
  resistance_series, start, end, cost_bps, cooldown_bars)` (~line 113; long-only, 1-unit,
  same-bar-fill), plus module helpers `_sharpe/_total_return/_max_drawdown`. Endpoint
  `POST /signal/support-resistance/wfo` in
  `services/api/app/routers/strategy_signals/_support_resistance.py` (~line 4240) backed by
  `_sr_get_or_compute_wfo` (~line 4025) which builds `pair_series` / `pair_meta` and caches
  `{response, context}` in `_SR_WFO_CACHE`. **`pair_series` is not currently cached** — Phase 2a
  adds it. Window objects carry `window_index, train_start/_end, test_start/_end` (bar indices),
  `*_date` fields, `selected_pair_id`, `selected_pair_meta`, `train_objective`,
  `test_metrics{sharpe,total_return,max_drawdown,n_trades}`, `test_trades[]`.
- S/R plot builders already emit `VariantDetailPanel`-shaped per-window entries:
  `_sr_plot_price_levels(ohlcv, support_series, resistance_series, fills, title, start, end)`
  and `_sr_plot_equity_drawdown` (used ~lines 3499–3544 of `_support_resistance.py`); the fills
  shape they consume is the `_sr_simulate_window_touch` output used around line 3504.

Frontend:
- WFO tab: `frontend/components/strategy/wfo-evidence-tab.tsx` — `WfoDetailPanel` → `FoldTable`
  (~line 282) for the 4 standard categories; `SrWfoDetailPanel` → `SrWfoWindowsTable` (~line 491)
  for S/R (adapts persisted detail via `srWfoResultFromDetail`, ~line 590). `WfoEvidenceTab`
  holds `symbol/horizon` and receives `cooldownBars`; `WfoDetailPanel` already has
  `symbol/horizon/variant`; `SrWfoDetailPanel` currently does not.
- UX model: `VariantDetailPanel` in `frontend/app/signals/variant/[id]/page.tsx` (~line 651) —
  period buttons ~lines 738–751 (colored by sharpe sign), metric chips ~755–780, chart tabs via
  `PlotlyChart` (`@/components/run/plotly-chart`), ledger tables `TradesTable`/`TradeLedgerTable`
  ~lines 952–1082 (French columns: `date, side, open_t_plus_1, cmp, position, return_cumule,
  pnl_realise_cumule`).
- API layer: `frontend/lib/api.ts` has `VariantBacktestSchema` / `PerWindowDetailSchema`
  (~line 4106); note existing SR fetchers prefix routes with `/strategy`. Hooks live in
  `frontend/hooks/use-api.ts` (SWR).
- Fold range formatting: `frontend/lib/wfo-fold-display.js::formatWfoFoldRange(fold, phase)`
  with phase `"train"|"oos"`.

## 3. Phase 1 — Backend, standard categories

### 1a. `core/quant_core/signal_engine/oos_eval.py`

Add:

```python
def evaluate_variant_windows(
    close, variant, windows: list[tuple[int, int]], *,
    cost_bps, cooldown_bars=0, volume=None, high=None, low=None,
) -> list[OOSWindowResult]
```

- Compute the signal **once** over the full array (preserves indicator warmup), then for each
  `(start, end)` run the exact metric block currently inside `evaluate_variant_oos`
  (~lines 408–446).
- **Refactor**: extract that block into a shared private helper (e.g. `_window_result(...)`)
  called by both `evaluate_variant_oos` and `evaluate_variant_windows`, so the two paths cannot
  drift. Behavior of `evaluate_variant_oos` must be byte-identical after the refactor.
- Emit `OOSWindowResult(window_index=i, test_start=start, test_end=end, is_valid=True, ...)`
  (set `train_start/train_end` to `start` — unused downstream for synthetic windows).

### 1b. `services/api/app/routers/wfo_signals.py` — `POST /strategy/wfo/fold-backtest`

Request model:

```python
class WfoFoldBacktestRequest(BaseModel):
    symbol: str
    horizon: CanonicalHorizon
    category: str
    variant: str = "expanded"
    fold_index: int
    timeframe: str = "1D"
```

Logic:
1. Load the `WfoSignalSummary` row using the same lookup as `get_wfo_detail`; find the fold by
   `index == fold_index` in `folds_json`; 404 if row or fold missing.
2. If `winner_variant_id` is empty/null → return `{"status": "no_winner", "periods": []}` (HTTP 200).
3. Rebuild the pool via `build_category_candidate_grid(category, horizon,
   families=config_json.get("families"))`; find the winner by id. If absent (symbol-conditioned
   `factor_x_ta` grids) → `{"status": "winner_unavailable", "periods": [], "note": ...}` —
   **never 500**.
4. Load OHLCV via `load_ohlcv_for_symbol(db, symbol, timeframe)` + `_clean_ohlcv` (import from
   `strategy_signals._shared`). **Do NOT apply `_truncate_for_horizon`** — fold indices/dates are
   anchored to the full index.
5. Resolve slice bounds **by dates first** (robust to data growth since the WFO run):
   `start = int(index.searchsorted(pd.Timestamp(fold["train_start_date"])))`;
   `end = int(index.searchsorted(pd.Timestamp(fold["train_end_date"]), side="right"))`
   (restores the exclusive end; same for `oos_*_date`). Fall back to `*_abs_idx` clamped to
   `len(index)` when a date is missing; 422 if neither resolves or `end - start < 2`.
6. `windows = evaluate_variant_windows(close, variant_def, [(train_s, train_e), (oos_s, oos_e)],
   cost_bps=config_json.get("cost_bps", <module default>))`, then
   `result = compute_variant_detail(ohlcv, close, variant_def, windows, volume=..., high=...,
   low=..., cost_bps=<same>, force_valid_windows=True)`.
7. Response:

```json
{"status": "ok", "fold_index": 3, "winner_variant_id": "...", "description": "...",
 "periods": [ {"...per_window item...", "phase": "train"},
              {"...per_window item...", "phase": "test"} ]}
```

   where `periods` entries are `result["per_window"]` items **verbatim** plus `phase`.
8. Module-level TTL cache (~1h), keyed
   `(symbol, horizon, category, variant, fold_index, timeframe)`, mirroring `_BACKTEST_CACHE`
   in `_variants.py`. One call returns **both** phases (single signal compute; the panel needs
   both button labels anyway).

**Phase 1 verification:** with the API running, curl the endpoint for a symbol/horizon/category
that has a succeeded WFO row. Assert: exactly two periods; test-phase `start_date/end_date`
match the fold's `oos_*_date`; test-phase sharpe ≈ `fold.oos_sharpe` with tolerance (the WFO
engine's internal evaluator — `_compute_variant_prom_for_window` in `wfo_signal.py` — may differ
slightly in cooldown/long-only handling; require sign + magnitude agreement, not equality, and
document this in the endpoint docstring). Second identical call must be cache-fast.

## 4. Phase 2 — Backend, support_resistance

### 2a. Cache pair series

In `_sr_get_or_compute_wfo` (`_support_resistance.py`, ~line 4025), add
`"pair_series": pair_series, "pair_meta": pair_meta` to the cached payload dict — in **both**
the success branch and the insufficient-history branch (empty dicts there).

### 2b. `POST /signal/support-resistance/wfo/fold-backtest`

New endpoint in `_support_resistance.py`. Request schema = the existing SR WFO request fields
plus `window_index: int`; define it next to the other SR request models in
`services/api/app/schemas/strategy_signals.py`.

Logic:
1. `payload = _sr_get_or_compute_wfo(...)`; find the window by `window_index` in
   `payload["response"]["wfo"]["windows"]`; 404 if absent (live recompute can drift from the
   persisted table row — the frontend tolerates this; see §7).
2. `selected_pair_id` null → `{"status": "no_winner", "periods": []}`.
3. `support_s, resistance_s = payload["pair_series"][selected_pair_id]`; get
   `ohlcv/close/high/low/open_` from `payload["context"]`.
4. For each phase `("train", train_start, train_end)` and `("test", test_start, test_end)`:
   `sim = simulate_touch_pair(...)` over that slice with `cost_bps`/`cooldown_bars` — **prefer
   the cached result's `params_echo` values when present**, else the request's. Metrics via the
   `sr_wfo` module's `_sharpe/_total_return/_max_drawdown` with `periods_per_year` from the
   context (this is what makes non-1D timeframes correct). `pnl_100k = round(100_000 *
   total_return, 2)`.
5. Map `sim["trades"]` to ledger-style fills with a small helper
   `_sr_wfo_trades_to_fills(trades, dates)`: per round trip, two rows
   (`side: "ACHAT"` entry / `"VENTE"` exit, price fields, `position` 1/0, exit rows carry
   `pnl_realise = pnl_return * entry_price`, running `pnl_realise_cumule`). Match the fills
   shape consumed by `_sr_plot_price_levels` (same shape as `_sr_simulate_window_touch` output
   used ~line 3504) so both the ledger table and the price-chart markers work.
6. Plots per phase: `_sr_plot_price_levels(ohlcv, support_s, resistance_s, fills,
   title=f"Fold #{window_index+1} — {phase}", start=s, end=e)` and `_sr_plot_equity_drawdown`
   over the slice returns/dates.
7. Response shape **identical to Phase 1** (`periods` items shaped like per_window entries with
   `phase`), plus `pair_id` and a human `description` built from `selected_pair_meta` labels.
8. Cache like `_SR_VARIANT_BACKTEST_CACHE`, key extended with `window_index` (and cost/cooldown).

**Phase 2 verification:** the test-phase output must **exactly equal** the window's persisted
`test_metrics` and `test_trades` (same simulator, same slice, same params) — assert via curl
against `/signal/support-resistance/wfo` for the same `(symbol, horizon, timeframe)`.

## 5. Phase 3 — Frontend, standard categories

- **3a.** Extract `TradesTable` + `TradeLedgerTable` + their local format helpers from
  `frontend/app/signals/variant/[id]/page.tsx` (~952–1082) into
  `frontend/components/strategy/trade-ledger-table.tsx`; re-import in page.tsx. Zero behavior
  change.
- **3b.** `frontend/lib/api.ts`: add
  `WfoFoldBacktestSchema = z.object({ status, fold_index, winner_variant_id/pair_id optional,
  description optional, periods: z.array(PerWindowDetailSchema.extend({ phase:
  z.enum(["train","test"]) })) })`; add `fetchWfoFoldBacktest(body)` →
  `POST /strategy/wfo/fold-backtest` and `fetchSrWfoFoldBacktest(body)` →
  the SR endpoint (respect the existing `/strategy` prefix convention used by SR fetchers).
- **3c.** `frontend/hooks/use-api.ts`: `useWfoFoldBacktest(params | null)` — SWR with a null key
  while the row is collapsed (lazy fetch on expand), `revalidateOnFocus: false`, an `sr`
  discriminator in params selecting the fetcher.
- **3d.** New `frontend/components/strategy/wfo-fold-backtest-panel.tsx` — props
  `{ symbol, horizon, variant, category, foldIndex, sr?: boolean, timeframe?, costBps?,
  cooldownBars? }`. Modeled on `VariantDetailPanel` (simplified — **no "Toutes" aggregate**):
  - Two period buttons `Train (start → end)` / `Test (start → end)`, colored by sharpe sign like
    the existing OOS selector (page.tsx ~738–751). Default selection: **Test**.
  - Metric chips: Sharpe, PnL (100k), Trades (pattern at page.tsx ~755–780).
  - Tabs: Graphiques (`plot`, `equity_plot`, `drawdown_plot` via `PlotlyChart`) / Registre
    (`TradesTable` from 3a).
  - States: loading spinner; error row; "Aucun backtest disponible pour ce fold" when
    `status !== "ok"`.
- **3e.** `FoldTable` in `wfo-evidence-tab.tsx` (~282): add props `symbol/horizon/variant/category`
  (passed from `WfoDetailPanel`, which already has them); `expandedFold` state; clickable rows
  with a chevron cell (pattern: variant page rows ~558–644); when expanded, render
  `<tr><td colSpan={...}><WfoFoldBacktestPanel foldIndex={fold.index} .../></td></tr>`.

**Phase 3 verification:** frontend typecheck/build passes; in the browser, WFO tab → expand
folds in each of the 4 standard categories, toggle Train/Test, confirm charts + ledger render
and the panel's dates match the row's Train/OOS columns.

## 6. Phase 4 — Frontend, S/R

- Pass `symbol/horizon/variant` (+ `timeframe` default `"1D"`, `costBps`, `cooldownBars` —
  `WfoEvidenceTab` already receives `cooldownBars`) from `WfoEvidenceTab` into
  `SrWfoDetailPanel` → `SrWfoWindowsTable` (~491).
- Make `SrWfoWindowsTable` rows expandable exactly like `FoldTable` (colSpan 8), rendering
  `WfoFoldBacktestPanel` with `sr` and `foldIndex = win.window_index`.
- Panel header shows the pair label (reuse `srWfoPairMetaLabel`-style formatting).

**Phase 4 verification:** an expanded S/R fold's test-phase Sharpe / return / N trades must
equal the row's own "Sharpe test / Rendement test / N trades" columns (hard invariant — same
simulator, same slice); the train phase shows fresh numbers.

## 7. Edge cases (all must be handled)

- **Fold without winner** (`winner_variant_id == ""` / `selected_pair_id == null`): backend
  returns `status: "no_winner"`; panel shows an info row. All folds remain expandable.
- **Data grew since the WFO run**: standard endpoint slices by fold **dates**
  (`searchsorted`), abs-idx only as fallback. S/R recomputes the WFO live from current context,
  so its indices are self-consistent — but live windows may differ from the persisted DB row
  shown in the table (row-count/pair drift). Frontend must tolerate 404/mismatch gracefully;
  note this limitation in the PR description.
- **`factor_x_ta` winners absent from the regenerated grid** → `winner_unavailable`, never 500.
  During Phase 1 verification, confirm `build_category_candidate_grid` reproduces
  `winner_variant_id` for at least one persisted row per standard category.
- **Costs/cooldown consistency**: standard uses `config_json["cost_bps"]` and cooldown 0
  (matching how the WFO ran); S/R prefers `params_echo` values from the cached WFO result.
- **Non-1D S/R timeframes**: correct by construction because everything derives from the same
  `_sr_get_or_compute_wfo` context; pass its `periods_per_year` to the metric helpers.

## 8. End-to-end verification

Run the stack (API + frontend). Pick symbols with completed WFO rows (e.g., ATW monthly; IAM
weekly for S/R). Exercise fold expansion in all 5 categories in the browser. Run the two backend
assertions: standard test-phase sharpe ≈ `fold.oos_sharpe` (tolerance), S/R test-phase metrics
=== persisted `test_metrics`/`test_trades` (equality). Afterwards run `graphify update .` (repo
convention: keep the knowledge graph current after code changes).
