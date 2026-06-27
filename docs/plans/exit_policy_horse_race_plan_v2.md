# Plan v2 — Exit-policy horse race, corrected: fold-scoped OOS + in-sample calibration

**Supersedes** the data-source and calibration sections of `exit_policy_horse_race_plan.md` (v1).
The policy definitions (A–E), the conservative first-touch fill rules, and the stats layer
(stationary bootstrap CI + Hansen SPA / White Reality Check) from v1 are **unchanged** — reuse them.
This document replaces only **where the trades come from** and **how exit parameters are calibrated**.

**Why v2 exists.** The v1 run scored policies on `SignalBacktestRun.trades_json`
(`scope=global, source=wfo`). That ledger is built by `build_category_signal_series_wfo` →
`build_family_signal_series` over the **full price history** using the WFO-selected
representatives — i.e. a single full-sample backtest of the winning methods, applied across the
very periods used to select them. It is **not** the fold-scoped stitched OOS shown in the
signal-evidence tab. Two consequences invalidated the v1 verdict:
1. **Method-selection look-ahead** — winners applied to their own selection windows.
2. **Cost-basis mismatch** — Policy A used the stored net `pnl_return` (net of 33 bps/side =
   66 bps round-trip + slippage ≈ 74 bps), while policies B–E reconstructed **gross** returns.
   The measured "edge" (Δ ≈ +0.0074) was almost exactly that cost. Not skill — accounting.

v2 fixes both by sourcing trades from the **same fold-scoped OOS ledger the signal page uses**,
and by calibrating every exit parameter **in-sample per fold**, exactly as the WFO chose the signal.

---

## Core principle

> **No exit parameter may see its own evaluation window.**
> The exit-policy parameters (ATR multiples, MAE/MFE `k`, S/R levels/lookback) are calibrated on
> each fold's **train window** `[train_start, train_end)` — the same in-sample period that selected
> that fold's signal — then **frozen** and applied to that fold's **OOS window**
> `[oos_start, oos_end)`. OOS results are stitched across folds. This makes the TP/SL calibration
> as out-of-sample as the signal itself.

Confirmed available in `WfoSignalSummary.folds_json` (verified against live data):
each fold dict has `train_start`, `train_end`, `oos_start`, `oos_end` (bar indices, contiguous:
`train_end == oos_start`), plus `winner_variant_id`, `winner_description`, `winner_params`,
`oos_return`, `is_return`.

---

## Data sources (replace v1 `paths.py` source)

### OOS trades (evaluation set) — REUSE the evidence path, do not reinvent
- `core.quant_core.research.oos_index.oos_sample_for(...)` → `OosSample` with per-fold
  `windows: tuple[OosWindow, ...]` (`fold_id`, `start`, `end`, `winner_variant_id`).
- `services/api/app/routers/strategy_signals/_evidence.py :: _signal_evidence_oos_periods(...)`
  (line ~1136) returns `(periods, total_trades, stitched)`. Its `all_trades` (assembled ~line 1384)
  is the stitched-OOS ledger, each trade carrying:
  `signal_date`, `entry_date`, `exit_date`, `direction`, `action_return_gross`,
  `action_return_net`, `stock_return`, `is_hit`, bucketed into folds by `signal_date`.
- **Reuse this assembly** (call the same code path) so the harness ledger is byte-for-byte the
  one the signal page reports — parity is the whole point. Do **not** read `folds_json` and
  re-derive trade returns independently.

### IS trades (calibration set) — Approach A: replay the fold winner on the train window
The evidence path yields OOS trades only. Policy C calibrates `k` from the MAE/MFE distribution of
the fold winner's **in-sample** trades, so we regenerate them:
1. Per fold, resolve the winner: `winner_id = fold["winner_variant_id"]`; look it up in
   `WfoSignalSummary.representatives_json` (`reps_by_id[winner_id]`, see `_evidence.py:532-546`)
   to get the variant's family + `params` (fall back to `fold["winner_params"]`).
2. Slice the symbol OHLCV to the train window `[train_start, train_end)` (bar-index space; convert
   via the same `ohlcv_index` `oos_index` uses).
3. Regenerate that single variant's signal over the train slice:
   `build_family_signal_series(close, volume, high, low, [winner_rep], ...)`
   (`core/quant_core/signal_engine/backtest_mc.py`), then run the backtest kernel
   (`run_signal_backtest`, same module) to get **IS trades with MAE/MFE**.
4. These IS trades feed `calibrate.py` (below). They are used **only** to choose parameters,
   never scored.

> If a fold's winner cannot be resolved or the train window yields `< min_calib_trades` (default 20)
> IS trades, Policy C falls back to the static default `k` (`DEFAULT_K_SL=DEFAULT_K_TP=1.5`).
> Log the fallback count — expect many on 3-fold symbols. This is honest, not a failure.

---

## Per-fold evaluation loop (replaces v1 `harness.py` + `portfolio.py` orchestration)

For each symbol with a succeeded `WfoSignalSummary` (chosen horizon/variant), for each fold:

1. **Resolve windows** from `folds_json`: train `[train_start, train_end)`, OOS `[oos_start, oos_end)`.
2. **Calibrate (IS):**
   - Policy C: replay winner on train window → IS trades → `walk_forward_c_params`-style fit, but
     **fit once on the whole train window** (not an expanding sub-window): `k_sl` = 90th pct of
     winning-trade `|MAE|/ATR`, `k_tp` = median `MFE/ATR`, clipped `[0.5, 5.0]`. Freeze.
   - Policies D/E: compute S/R **method/lookback** on the train window; the per-trade S/R *levels*
     themselves are still computed point-in-time at each OOS entry (already look-ahead-safe).
   - Policies A, B: no IS calibration. A is the stored stitched-OOS net return; B is the fixed
     `k`-grid (intentionally non-adaptive — the control for "does calibration help?").
3. **Apply (OOS):** for each OOS trade in this fold (those whose `signal_date ∈ [oos_start, oos_end)`):
   - **Fill at `entry_date`** (signal fires at close → enter next bar). The entry bar is the
     `entry_date` bar; **barrier scanning starts strictly after `entry_date`** — never on the
     signal bar or the entry bar's own High/Low (this kills the v1 entry-bar look-ahead, where 71%
     of fills were the signal bar's close yet that bar's intrabar range was scanned, producing
     15.8% spurious same-bar take-profits).
   - **Barriers cannot exit past the fold OOS boundary** `oos_end`: if no barrier touches by
     `min(natural_exit, oos_end)`, exit there (`time_exit` / `signal_exit`).
   - Reconstruct the intra-trade OHLC path between `entry_date` and the exit for the first-touch
     simulator (v1 `policies.py` `_first_touch`, unchanged logic).
4. **Cost — apply identically to every policy:** net each policy's per-trade return by the WFO's
   actual round-trip cost. Prefer reading `cost_bps`/`slippage_bps` off the `WfoSignalSummary` /
   backtest config (`DEFAULT_COST_BPS_PER_SIDE = 33.0`, `horizons.py:8`) and applying
   `2 × (cost_bps + slippage_bps)` per trade. Since every policy is one entry + one exit per trade,
   cost is a per-trade constant and **cancels in policy-vs-A differences** — but apply it anyway so
   absolute equity curves show true net profitability, and Policy A reconciles to the signal page's
   `action_return_net` exactly (regression anchor).

Stitch all OOS trades across folds and symbols → per-policy OOS return series → v1 portfolio sim +
v1 stats layer unchanged.

---

## Baseline redefinition (critical)

**Policy A = the stitched-OOS `action_return_net` series** straight from `_signal_evidence_oos_periods`.
Not the v1 `min(return, 0.05)` clip, not a reconstructed gross series. This anchors the null to the
exact number the signal-evidence tab displays, so the horse race answers the real question:
*does any TP/SL policy beat the OOS performance the user already sees and trusts, net of the same costs?*

The v1 baseline-regression test must be rewritten accordingly: assert Policy A reproduces the
signal page's stitched-OOS net metrics for a fixed symbol/fold fixture (was: assert A == stored
`pnl_return`, which anchored to the wrong, full-sample ledger).

---

## What stays from v1 (reuse as-is)
- `policies.py` simulators A–E and `_first_touch` (gap-fill, both-barriers→stop-first) — **except**
  the caller now passes the post-`entry_date` bar slice, and the time barrier is `min(natural, oos_end)`.
- `stats.py` entirely (stationary block bootstrap CI, Hansen SPA, White RC).
- `calibrate.py` MAE/MFE → `k` math (`_calibrate_k_from_history`) — but called once per fold on IS
  trades, not as an expanding window over OOS trades.
- Already-applied session fixes (keep): variant alias resolution (`expanded`→`expanded_ta_simple`),
  `id(path)` keying for Policy C (was `open_date`, collided across symbols), tz-naive bars reindex,
  CLI stdout→utf-8.

## What gets deleted / rewritten
- `paths.py :: reconstruct_trade_paths` source: drop `SignalBacktestRun.trades_json`; build from the
  evidence OOS ledger + per-fold winner replay.
- `harness.py :: _load_wfo_trades` / `_enumerate_symbols`: re-target to `WfoSignalSummary` + `oos_sample_for`.
- `walk_forward_c_params`: from expanding-over-OOS to once-per-fold-on-IS.

---

## Tests (extend v1 suite)
- `test_exit_policy_foldscope.py`: a barrier touch after `oos_end` is **not** taken (clipped to fold);
  trades are bucketed to the correct fold by `signal_date`.
- `test_exit_policy_is_calibration.py`: Policy C `k` computed only from train-window replay trades;
  shuffling OOS trades leaves `k` unchanged (IS/OOS isolation); `< min_calib_trades` → default `k`.
- `test_exit_policy_entry_fill.py`: fill at `entry_date`; no barrier can fire on the signal bar or the
  entry bar's own intrabar range; first scannable bar is the one after `entry_date`.
- `test_exit_policy_baseline_parity.py`: Policy A reproduces `_signal_evidence_oos_periods` stitched-OOS
  `action_return_net` for a fixed fixture (replaces the old stored-`pnl_return` regression).
- `test_exit_policy_cost_parity.py`: identical round-trip cost applied to every policy; policy−A deltas
  invariant to the cost constant.

## Verification
- `python -m pytest core/tests/test_exit_policy_*.py -q`.
- Run CLI `--horizon weekly --variant expanded` (resolves to `expanded_ta_simple`); confirm Policy A's
  stitched-OOS net metrics match the signal page for a spot-checked symbol **before** trusting the ranking.
- Sanity: the gross-vs-net artifact from v1 must be gone — expect Δ-vs-A to shrink dramatically once A
  and B–E share the net basis and the look-ahead is removed. A credible verdict may well be
  "no policy beats the stitched-OOS baseline net of costs" — report that honestly if so.

## Out of scope (unchanged from v1)
- Wiring the winning policy into the production portfolio endpoint (`strategy_signals.py:8912`) + UI.
- Upgrading the production bracket engine (`strategy_plan/backtest.py:1114`) from close-based to
  intrabar first-touch.
- `tvdatafeed` intraday fill-accuracy robustness check.
