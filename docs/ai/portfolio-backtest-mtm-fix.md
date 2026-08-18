# Brief: Portefeuille backtest — daily mark-to-market equity curve + strict Kelly timing

**Status**: approved for implementation. Scope decided by Taha on 2026-07-17: MTM curve + strict Kelly timing only. **No per-symbol concentration cap** (that would change strategy economics — explicitly out of scope).

## Background — audit findings (verified live, do not re-litigate)

The "Portefeuille" tab cumulative performance chart shows near-vertical jumps (Feb 2025 ≈ −10%→+25%, June 2025 ≈ +5%→+23%). Root cause was diagnosed against the running stack:

- The chart is served by `run_portfolio_backtest` in `services/api/app/routers/strategy_signals/_backtest.py` (POST `/strategy/signal/portfolio-backtest`) and plotted by `buildEquityPlot` in `frontend/components/signals/portfolio-backtest-panel.tsx`.
- **The jumps are genuine market returns with artificial timing.** Feb 2025: MOX rallied 250→583 MAD (+88%) through ~10 consecutive +9.99% limit-up sessions (CSE ±10% daily limit); raw OHLCV verified clean (no gaps/dupes/splits). June 2025: STR 56→166 (+196%) limit-up streak, plus CMT/FBR. The replay held up to 3 overlapping MOX lots (~100% of equity at peak).
- **Mechanism**: `open_positions` stores entry cost only, and equity-curve points are stamped **only at close events** (currently `equity_curve.append(...)` inside the close branch). A position that rallies for weeks contributes nothing to the curve until its close date, where the whole trade P&L lands as one vertical step.
- **Accounting conservation is exact** (verified: final equity 131,909.10 = 100,000 + Σ realized P&L with weekly/min_edge_score=0/no-conditions config; curve dates unique+sorted; cash never negative). Do NOT change the cash accounting.
- **Secondary bug (fix it)**: on the same date D, close events (rank 0) are processed before open events (rank 1), and `closed_history[symbol].append(...)` happens at the close event — so a trade closed on D feeds the Kelly sizing of a trade opened on D. This violates the documented contract "trades already CLOSED strictly before that date" (see `_kelly_fraction_from_returns` docstring and the endpoint docstring).

## Change 1 — daily mark-to-market equity curve

In `run_portfolio_backtest` (`services/api/app/routers/strategy_signals/_backtest.py`):

1. Keep the event-driven cash accounting **exactly as-is**: open deducts `actual_size` from cash; close credits `pos_size * (1 + effective_return)`. The ledger, trade records, `pnl_mad`, skip reasons, TP/SL clamping all stay unchanged.
2. Track for each open lot (already mostly available): symbol, entry cost (`actual_size`), `open_price`, direction (±1), and qty (`actual_size / open_price` — already computed as `trade_quantity`).
3. Replace the close-event-only `equity_curve` with a **daily** curve:
   - Daily grid = union of trading dates (from each executed symbol's OHLCV) within `[first event date, last event date]`.
   - Reconstruct cash chronologically from the same events (or emit curve points inside the loop — implementer's choice), and value every open lot on each grid date at `cost * (1 + direction * (close_t / open_price − 1))` using the symbol's daily close.
   - Load closes once per executed symbol via `load_ohlcv_for_symbol(db, symbol, "1D")` with the same normalization `_portfolio_benchmark` uses (tz-naive, normalized index, dedupe keep-last, sorted). Forward-fill within a lot's holding window when the symbol doesn't print on a grid date.
   - On a lot's close date, the realized value (`pos_size * (1 + effective_return)`) wins over MTM, so TP/SL-clamped returns remain exact.
   - Open-at-end lots: value at last available close instead of cost; keep the existing "position(s) never closed" warning.
4. **Graceful degradation** (required — the sqlite test harness has no market data): if a symbol's OHLCV load fails or is empty, carry its lots at entry cost (current behavior) and append a warning like `"{symbol}: prix indisponibles — position évaluée au coût dans la courbe"`. With no OHLCV at all, the endpoint must still return the same curve shape as today and all existing tests must pass unmodified (except where they assert curve length/points — adjust only if strictly necessary and preserve their intent).
5. Downstream metrics recompute from the new daily curve using the existing code paths: the max-drawdown loop, weekly-resampled Sharpe, `_equity_at`/alpha window, and the duplicate-date collapse (dates must stay unique and sorted). Max drawdown will increase — that is the honest number; do not clip or smooth anything.
6. Payload shape (`equity_curve: [{date, equity}]`) is unchanged, so no frontend changes are needed. Keep payload size sane: if the daily curve exceeds ~600 points you MAY downsample exactly like `_portfolio_benchmark` does (keep the final point); metrics must be computed on the full curve before downsampling.

## Change 2 — strict Kelly timing

- Store `(close_date, pnl_return)` tuples in `closed_history` (append at close events as today).
- At an open event on date D, compute the Kelly fraction from entries with `close_date < D` **only** (strict). The starter-fraction threshold (`_PORTFOLIO_STARTER_TRADE_COUNT`) also counts only strictly-prior closes.
- Do NOT change event ordering: same-date closes must still release cash before opens.

## Regression tests

Extend `services/api/tests/test_portfolio_backtest_panel.py` (reuse `_stitched_trade` / `_snapshot_row` / `_make_app`; monkeypatch `load_ohlcv_for_symbol` in the router module to feed synthetic daily OHLCV frames):

1. **MTM continuity (bug reproduction)**: one symbol, close price rising steadily across a 10-day holding window → equity rises on the price-move days; the close-date step reflects only that day's move, not the whole trade P&L. (Before this fix, all P&L landed on the close date — assert that no longer happens.)
2. **No look-ahead sizing**: construct a symbol whose 3rd qualifying close lands on the same date D as the next open, such that including it would move sizing past the starter fraction → assert the open on D is sized from strictly-prior closes only.
3. **Wealth continuity / contributions**: for every consecutive pair of curve dates, `equity[t] − equity[t−1] == Σ_lots qty × Δclose` (with the realized-value substitution on close dates); no resets, no additive stitching anywhere.
4. **Conservation**: with all trades closed, final equity == initial + Σ `pnl_mad` (keep `test_pnl_mad_sums_to_equity_delta` green).
5. **Exposure invariants**: cash never negative at any event; Σ open-lot cost ≤ equity; `exposition_pct ≤ 100`.
6. **No duplicated dates**: curve dates strictly increasing.
7. **Degradation**: symbol with no OHLCV → endpoint still succeeds, lot carried at cost, warning present.

## Verification

1. `python -m pytest services/api/tests/test_portfolio_backtest_panel.py -q` — all green (run inside the API container if host env lacks deps: `docker exec infra-quant_api-1 python -m pytest ...`).
2. Live check against the running stack: `POST /strategy/signal/portfolio-backtest` with `{"horizon":"weekly","required_edge_conditions":[],"min_edge_score":0}` →
   - total_return unchanged (≈ +31.9%, final equity ≈ 131,909 — all trades closed in this config),
   - the Jan-28→Feb-07 2025 and Jun-10→12 2025 segments now accrue daily (max one-day curve move ≈ constituent limit move × exposure, i.e. ≤ ~10%), no flat-then-vertical steps,
   - max_drawdown larger than the old 25.99 (MTM reveals intra-trade drawdowns).
3. Do not touch `core/quant_core/historical_portfolio.py` (the PIT engine already marks to market daily) or the frontend.
