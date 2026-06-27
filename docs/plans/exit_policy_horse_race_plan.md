# Plan — Exit-policy horse-race harness (TP/SL methodology)

**Audience:** implementer (Sonnet/Codex). Plan only — implement and run; do not assume done.

**Purpose.** The portfolio backtest currently exits with a crude `effective_return = min(raw_return, 0.05)` clip and **no stop-loss** (`services/api/app/routers/strategy_signals.py:8912`). We want to replace it with a principled, per-signal take-profit / stop-loss, but **decided by evidence, not assertion**. This harness scores competing exit policies on the existing WFO OOS trades with statistical rigor (bootstrap CIs + a data-snooping–corrected test), and outputs a ranked verdict. Only after the verdict do we wire the winning policy into the portfolio path.

**Methodology basis (institutional):**
- **Triple-Barrier Method** — López de Prado, *Advances in Financial Machine Learning* (2018): two volatility-scaled horizontal barriers (profit-take, stop-loss) + one vertical (time) barrier; exit on first touch.
- **MAE/MFE calibration** — Sweeney: set the stop just beyond the Maximum Adverse Excursion that *winning* trades survive; set the target from the Maximum Favorable Excursion distribution.
- **Reality Check / SPA** — White (2000) / Hansen (2005): correct for the fact that the best of many tested policies looks good by luck.

---

## Background facts (already verified in the codebase)

- **A bracket engine already exists** in `core/quant_core/strategy_plan/backtest.py`: `stop_atr_multiplier` (ATR stop, default 1.5), `take_profit_rr` (R-multiple target, default 1.5), `trailing_stop_enabled`, exit loop with `exit_reason ∈ {stop_loss, take_profit, window_end}` (backtest.py:1106-1131), barriers built in `_build_barriers` (backtest.py:1474-1478). **Weakness:** the exit check is on the **close** (`close_t <= stop_loss`, backtest.py:1114), not the intrabar high/low — it cannot model an intrabar touch.
- **ATR + S/R level helper** exists: `core/quant_core/decision/levels.py :: compute_levels_support_resistance` (blends S/R with ATR floors, min ATR-multiple distances).
- **Stored WFO trades** live in `SignalBacktestRun.trades_json` (per symbol, source=`wfo`, scope=`global`, variant, horizon, status=`succeeded`). Each trade dict has: `direction`, `open_date`, `close_date`, `open_price`, `close_price`, `pnl_return` — **endpoints only, no intra-trade path**.
- **Daily OHLC loader:** `services.api.app.market_data_loader.load_ohlcv_for_symbol(db, symbol)` → DataFrame, Title-case columns (`Open/High/Low/Close/Volume`), DatetimeIndex. This is how we reconstruct intra-trade paths.
- **Bar resolution:** daily OHLC only. Use the conservative first-touch rule (below). Intraday via `tvdatafeed` is a **follow-up sensitivity check only** (poor BVC coverage, shallow history, fragile scrape) — not a dependency.

---

## Architecture: where it lives

Research module + runnable script (matches repo `core/quant_core/research/` convention):

```
core/quant_core/research/exit_policy/
  __init__.py
  paths.py        # reconstruct intra-trade OHLC paths + ATR(entry) from stored trades
  policies.py     # the exit-policy simulators (A–E) on a single trade path
  calibrate.py    # walk-forward MAE/MFE k-multiple + per-signal Kelly calibration
  portfolio.py    # re-run the capital-recycling portfolio sim for a given policy
  stats.py        # bootstrap CIs + Hansen SPA / White Reality Check
  harness.py      # orchestrates: load → reconstruct → run policies → stats → report
scripts/research/exit_policy_horse_race.py   # CLI entrypoint
core/tests/test_exit_policy_*.py             # unit + no-look-ahead + regression tests
```

The harness reads the DB read-only; it does **not** touch production endpoints yet.

---

## Step 1 — Intra-trade path reconstruction (`paths.py`)

For each stored trade `(symbol, direction, open_date, close_date, open_price, close_price)`:
1. Load the symbol's daily OHLC once (cache per symbol).
2. Slice bars in `[open_date, close_date]` inclusive → ordered list of `(date, open, high, low, close)`.
3. Compute `atr_entry` = ATR(20) using bars strictly **up to and including** the entry bar (reuse `compute_atr` from the same module the WFO pipeline uses; see `wfo_signal_batch.py:1011`). No look-ahead.
4. Capture the signal's **natural exit** = `(close_date, close_price)` — this is the always-available fallback exit (`exit_reason="signal_exit"`) and the implicit vertical barrier ceiling.
5. Carry the entry-time S/R levels for policies D/E. Prefer levels **stored at signal time**; if not stored, recompute with `compute_levels_support_resistance` using bars **up to entry only** (never full history).

Build a `TradePath` dataclass holding all of the above. Drop trades whose OHLC can't be reconstructed (log count).

---

## Step 2 — Exit-policy simulators (`policies.py`)

Common signature: `simulate(path: TradePath, params) -> ExitResult(exit_price, exit_date, exit_reason, effective_return, mae, mfe)`.

**Conservative daily first-touch rule** (long; mirror for short):
- Let `S` = stop level, `T` = take-profit level, `S < entry < T`.
- Walk bars in date order:
  - **Gap-through:** if `bar.open <= S` → fill at `bar.open`, `stop_loss`. If `bar.open >= T` → fill at `bar.open`, `take_profit`. (Gaps fill at open, not at the level.)
  - **Intrabar both touched** (`bar.low <= S` and `bar.high >= T`): assume **stop first** → fill at `S`, `stop_loss`. (Pessimistic; the institutional default.)
  - Else single touch: `bar.low <= S` → `S`/`stop_loss`; `bar.high >= T` → `T`/`take_profit`.
  - **Vertical barrier:** if `bar.date >= time_barrier_date` → fill at `bar.close`, `time_exit`.
- No barrier hit through the path → fill at natural `(close_date, close_price)`, `signal_exit`.
- Always also record `mae`/`mfe` over the path (needed for calibration + reporting), independent of which barrier fired.

**Policies:**
- **A — Baseline (status quo):** natural signal exit with `min(return, 0.05)` clip, no stop. The null to beat. Must reproduce today's portfolio numbers exactly (regression anchor).
- **B — ATR triple-barrier (static):** `S = entry − 1.5·ATR`, `T = entry + 1.5·ATR`, vertical = natural exit (or fixed N bars — make N a param). Uses existing engine defaults.
- **C — MAE/MFE-calibrated triple-barrier:** `k_sl`, `k_tp` (in ATR units) fit per-signal on the expanding past window (Step 3). Falls back to B's defaults below min sample.
- **D — S/R-based:** `T = resistance`, `S = support` from entry-time levels, vertical = natural exit.
- **E — Hybrid (ATR base + S/R overlay):** start from B; snap `T` **down** to resistance if resistance ∈ `(entry, T_atr]`; snap `S` **up** to support if support ∈ `[S_atr, entry)`; enforce a min ATR-distance floor so snapping can't create degenerate R:R.

Make the k-grid configurable so the SPA correction has a real search space to account for (e.g. `k_sl, k_tp ∈ {1.0, 1.5, 2.0, 2.5, 3.0}` for B/C variants).

---

## Step 3 — Walk-forward calibration (`calibrate.py`)

**No-look-ahead is the core invariant.** Sort each signal's trades by `open_date`. For trade *i*, calibrate using only trades `1..i-1`:
- **MAE/MFE → k multiples (policy C):** from past *winning* trades' MAE distribution, set `k_sl` at a percentile winners rarely breach (e.g. 90th pct of |MAE|/ATR); from past trades' MFE distribution set `k_tp` (e.g. median or a grid-searched value maximizing past expectancy). Require **≥ 20** past trades (a 2-D bracket overfits on thin samples — much stricter than the current Kelly `n≥3`); else fall back to static defaults.
- **Kelly per policy:** **Kelly must be recomputed from each policy's bracketed returns**, not the raw returns (current `_portfolio_kelly` uses raw `pnl_return`). After a policy rewrites each trade's `effective_return`, recompute the half-Kelly per signal on the expanding window of bracketed returns. TP/SL, Kelly and the portfolio sim are one coupled system — keep them coupled.

Provide a unit test that shuffles *future* trades and asserts the past-window calibration output is unchanged (peek detector).

---

## Step 4 — Portfolio re-simulation per policy (`portfolio.py`)

Reuse the capital-recycling loop from `strategy_signals.py:8951-8996` (extract it into a shared function so the harness and the endpoint share one implementation — avoid a third divergent path). For each policy:
1. Apply the policy simulator to every trade → `effective_return`, new `exit_date` (= barrier hit date, which can be **earlier** than `close_date`; this changes when capital is freed and therefore which later trades get funded).
2. Recompute per-signal Kelly from bracketed returns (Step 3).
3. Run the sim → equity curve + `_portfolio_backtest_metrics`.

Output per policy: trade-level series (expectancy, win rate, payoff ratio, trade-Sharpe) + portfolio metrics (total return, CAGR, Sharpe, MaxDD, Calmar).

---

## Step 5 — Statistics (`stats.py`)

- **Paired bootstrap on trade returns:** the same signal events feed every policy, so pair per event. Resample B=10,000 (use **stationary/block bootstrap** to respect serial/overlap structure) → CIs for each policy's mean effective return and for each pairwise difference `(policy − baseline)`.
- **Portfolio significance via Hansen's SPA** (preferred over White's Reality Check — less conservative): loss-differential = policy performance − baseline performance (use mean return or Sharpe as the criterion). Bootstrap the null "no policy beats baseline" across **all policies AND all k-grid configs simultaneously** → a snooping-corrected p-value for "the best policy genuinely beats baseline." Report both SPA and Reality Check p-values.
- Implementation note: a vetted SPA/Reality Check exists in `arch` (`arch.bootstrap.SPA`). Prefer reusing it over hand-rolling; if adding `arch` is undesirable, implement the stationary-bootstrap SPA directly (documented algorithm).

**Report** (`harness.py` → markdown + CSV + optional plots): ranked table with point estimate, bootstrap CI, SPA-adjusted p-value per policy; per-policy exit-reason histogram (how often stop vs TP vs time vs signal exit fired); MAE/MFE scatter plots. The verdict sentence should read like: *"Policy C beats the 5% baseline on OOS Sharpe (Δ=+0.31, 95% CI [0.08,0.55], SPA p=0.03); S/R-only (D) is indistinguishable from baseline (SPA p=0.41)."*

---

## CLI (`scripts/research/exit_policy_horse_race.py`)

Args: `--horizon`, `--variant`, `--symbols` (default all qualifying), `--policies A,B,C,D,E`, `--k-grid`, `--min-calib-trades 20`, `--bootstrap 10000`, `--out <dir>`. Loads DB session like other scripts, runs the harness, writes the report.

---

## No-look-ahead invariants (call out in code + tests)

1. Per-signal calibration (MAE/MFE k, Kelly) uses only trades with `open_date` strictly before the current trade's `open_date`.
2. `atr_entry` and any recomputed S/R use only bars up to the entry bar.
3. Conservative first-touch fills; gaps fill at open; both-barriers-in-range → stop first.
4. Baseline (A) reproduces the current portfolio endpoint numbers exactly.

## Tests (`core/tests/`)

- `test_exit_policy_firsttouch.py`: gap-down→stop@open; gap-up→tp@open; both-in-range→stop-first; single touches; no-touch→signal_exit; short mirror.
- `test_exit_policy_calibration.py`: peek detector (future-shuffle invariance); min-sample fallback.
- `test_exit_policy_baseline_regression.py`: policy A == current `signal_portfolio_backtest` output for a fixed fixture.
- `test_exit_policy_stats.py`: bootstrap CI sanity (degenerate identical series → zero diff CI); SPA returns valid p in [0,1].

---

## Out of scope (follow-ups, do not build now)
- Wiring the winning policy into the production portfolio endpoint + UI controls (separate plan, after the verdict).
- Upgrading `backtest.py:1114` from close-based to intrabar first-touch via the shared simulator (do once, reuse everywhere).
- `tvdatafeed` intraday import as a fill-accuracy robustness check (gated on BVC coverage).

## Verification
- `python -m pytest core/tests/test_exit_policy_*.py -q` (all pass).
- Run the CLI on `--horizon weekly --variant expanded` over the full qualifying universe; eyeball the report; confirm baseline matches the live endpoint.
