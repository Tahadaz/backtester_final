# Plan v3 — TP/SL as a WFO exit treatment (supersedes v1 + v2)

**Supersedes** `exit_policy_horse_race_plan.md` (v1) and `exit_policy_horse_race_plan_v2.md` (v2).
Those described a *post-hoc* harness that bolts exit rules onto already-selected WFO trades. That
architecture is abandoned. **Decision (user):** TP/SL must live **inside the WFO**, and we evaluate
exit rules as **treatments** — run the full WFO end-to-end once per exit rule, on identical folds,
then compare the stitched-OOS results statistically.

**Why this is correct.** The WFO already does fold-scoped train→select→OOS. The exit rule's
parameters should be calibrated on the **same in-sample window that selects the signal**, and the
winner should be chosen *under* that exit regime (a signal is only as good as how you exit it). A
parallel harness that re-implements fold scoping is redundant and, as v1 proved, leaks look-ahead
and a gross-vs-net cost artifact. Putting the exit in the WFO PnL path makes all of that fall out
for free: same costs (`DEFAULT_COST_BPS_PER_SIDE = 33.0`/side already applied there), same folds,
genuine OOS.

---

## Architecture

Run the WFO N times, once per exit treatment, over the same symbol universe / horizon / folds:

```
treatments = { none(baseline), atr_triple_barrier, support_resistance, mae_mfe_calibrated }
for policy in treatments:
    run full WFO with exit_policy=policy        # selection happens UNDER this exit regime
    collect stitched-OOS return stream per symbol
compare the N stitched-OOS streams  -> SPA / bootstrap (salvaged from v1 stats.py)
report: which exit definition beats `none` OOS, snooping-corrected
```

- The exit rule is **fixed within a run** (it's the treatment) but its **levels are calibrated
  in-sample per fold** (for calibrated treatments).
- Because the winner variant is selected under the exit regime, each treatment is a coherent system;
  the comparison is system-vs-system at the OOS-return-stream level (paired by fold/date, since all
  treatments share identical fold boundaries from the same `WalkForwardConfig`).
- **Production is untouched:** `exit_policy` defaults to `"none"`, which is exactly today's
  signal-flip exit. Only the research driver passes alternatives.

---

## Integration points (all in `core/quant_core/signal_engine/wfo_signal.py`)

Thread one new optional `exit_policy: ExitPolicy = NONE` param down the call chain:

1. `run_wfo_category_signal(...)` (line ~725) — public entry; accept `exit_policy`, pass through.
2. `_execute_wfo_category_signal(...)` (line ~493) — pass `exit_policy` into the per-variant eval at
   line ~546.
3. `_compute_prom_for_variant(...)` (line ~225) — **already receives `high`/`low`** (lines 234-235),
   so no signature surgery for OHLC. Replace the two exit evaluators with policy-aware versions:
   - `_evaluate_variant_returns_and_pnl(signal_arr, close, cost_bps)` (line 168) — currently marks a
     daily position series that flips with the signal. New: when `exit_policy != none`, a barrier
     touch **flattens the position** (and blocks re-entry until the next signal entry), so daily
     returns and cost reflect the bracketed exit. Needs `high`/`low` passed in.
   - `_extract_trades(signal_arr, close)` (line 198) — currently exits a trade on signal flip. New:
     exit on the **first** of {stop touch, take-profit touch, signal flip, window end}, using the
     conservative daily first-touch rule.

> **Reuse the first-touch simulator from v1** (`core/quant_core/research/exit_policy/policies.py::
> _first_touch`): gap-through → fill at open; both barriers in one bar → stop first; vertical
> barrier → close. It is already unit-tested (37 passing). Lift it into a small shared module
> `signal_engine/exit_barriers.py` so both the WFO path and any later production use share one
> implementation. **Do not** re-derive the fill rules a third time.

`prom` (the winner-selection score) is computed from `_extract_trades(sig_is, close_is)` at line 265
→ under a treatment, IS trades carry bracketed exits, so the fold winner is selected under that exit
regime. This is the intended behavior, not a side effect.

---

## Exit treatments

All barriers are volatility-scaled (ATR), simulated with the conservative daily first-touch rule.
Direction-aware (mirror for shorts).

- **`none` (baseline / null):** unchanged signal-flip exit. Must reproduce today's WFO numbers
  exactly — this is the regression anchor and the null the other treatments must beat.
- **`atr_triple_barrier`:** `stop = entry − k_sl·ATR`, `tp = entry + k_tp·ATR`, vertical barrier =
  signal flip or fold OOS end. `k_sl, k_tp` are **run-level constants** for this treatment (sweep a
  small grid across separate runs if desired; the SPA accounts for the multiplicity).
- **`support_resistance`:** `tp = resistance`, `stop = support` from entry-time levels
  (`decision/levels.py::compute_levels_support_resistance`), computed point-in-time at entry (no
  look-ahead), with ATR-distance floors.
- **`mae_mfe_calibrated`:** `k_sl, k_tp` **calibrated in-sample per fold** from the MAE/MFE
  distribution of the IS trades of the variant being evaluated (the IS slice already exists inside
  `_compute_prom_for_variant`): `k_sl` = high percentile of winning IS trades' `|MAE|/ATR`, `k_tp` =
  median IS `MFE/ATR`. Calibrate on IS, apply on OOS → no look-ahead by construction. Fall back to a
  static default when the IS slice yields `< min_calib_trades` trades. (Reuse v1
  `calibrate.py::_calibrate_k_from_history`.)

---

## In-sample calibration discipline (the core invariant)

For `mae_mfe_calibrated`, calibration happens **entirely within the fold's IS window**, which is the
same window that selects the signal. No exit parameter ever sees its own OOS window. ATR and S/R for
OOS trades are computed point-in-time at each OOS entry. This is the discipline the user required and
it is now structurally guaranteed by living inside `_compute_prom_for_variant`'s IS/OOS split, rather
than re-implemented in a separate harness.

---

## Comparison driver + stats

New `scripts/research/exit_treatment_compare.py`:
1. For each treatment, run the WFO over the symbol universe (reuse the batch compute path with
   `exit_policy` injected; in-memory, **no DB writes** — production tables untouched).
2. Collect each treatment's stitched-OOS return stream (concat of fold OOS returns), paired by
   fold/date across treatments.
3. Feed the streams to the **salvaged** `core/quant_core/research/exit_policy/stats.py`
   (stationary block bootstrap CI + Hansen SPA + White Reality Check). Null = "no treatment beats
   `none` OOS"; SPA corrects for testing several treatments (and any k-grid sweep) at once.
4. Emit `report.md` + `results.csv`: per-treatment OOS Sharpe / return / MaxDD / exit-reason mix,
   Δ-vs-`none`, bootstrap CI, SPA p. Verdict sentence.

---

## Salvage vs delete (from v1/v2 implementation)
- **Salvage:** `_first_touch` (→ `signal_engine/exit_barriers.py`), `_calibrate_k_from_history`,
  all of `stats.py`. Keep their unit tests.
- **Delete / obsolete:** `paths.py` (post-hoc reconstruction from `trades_json`), `portfolio.py`
  (parallel sequential sim), `harness.py`, the v1 CLI, and the `results/exit_policy/` v1 output.
  The whole "reconstruct trades from `SignalBacktestRun.trades_json`" premise is gone.
- Plans v1 + v2 are historical context only.

---

## No-look-ahead invariants
1. Exit calibration (MAE/MFE `k`) uses only the fold IS slice; OOS never feeds calibration.
2. ATR / S/R at an OOS entry use only bars up to that entry.
3. First-touch fills are conservative (gap→open, both-in-bar→stop-first); barriers cannot exit past
   the fold OOS window.
4. `none` reproduces today's WFO output bit-for-bit (regression anchor).
5. `exit_policy` defaults to `none` everywhere; no production call site changes behavior.

## Tests (`core/tests/`)
- `test_wfo_exit_none_regression.py`: `exit_policy=none` ⇒ identical folds/winners/OOS returns to
  current `run_wfo_category_signal` for a fixed fixture.
- `test_wfo_exit_barriers.py`: barrier flattens the daily position + blocks re-entry; first-touch
  edge cases (reuse v1 cases via the shared module); short mirror.
- `test_wfo_exit_is_calibration.py`: `mae_mfe_calibrated` `k` depends only on IS trades; shuffling
  OOS leaves `k` unchanged; `< min_calib_trades` ⇒ static fallback.
- `test_exit_treatment_stats.py`: SPA/RC p in [0,1]; degenerate identical streams ⇒ zero diff.

## Verification
- `python -m pytest core/tests/test_wfo_exit_*.py core/tests/test_exit_treatment_stats.py -q`.
- Run the driver on `--horizon weekly --variant expanded_ta_simple` over the qualifying universe;
  confirm the `none` treatment's stitched-OOS metrics match the live signal-evidence tab before
  trusting any ranking.
- Honest expectation: with one shared net-of-cost basis and genuine OOS selection, a credible verdict
  is "no exit treatment beats `none` out-of-sample." Report that plainly if so.

## Out of scope (follow-ups)
- Making the WFO *select* the exit per fold (the "WFO selects the exit" option) — only after a
  treatment wins here.
- Wiring the winning exit into the production portfolio endpoint + UI.
- Persisting per-fold chosen exit to `folds_json` / DB.
