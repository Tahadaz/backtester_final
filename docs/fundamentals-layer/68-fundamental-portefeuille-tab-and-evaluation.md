# 68 — Fundamental "Portefeuille" tab + honest signal evaluation

**Status**: implementation brief, 2026-07-06. Supersedes the placement of the SFC portfolio backtest
(currently in the dashboard). Builds on the corrected backtest from brief 65 (event rebalance +
benchmark-relative weights vs float-weighted MASI) and the study findings in 61/66/67.

## Motivation & the honest baseline (read first)

The realistic backtest (snapshot id 3, event rebalance, benchmark-relative ±3% active vs float-weighted
MASI) gives a **proof-half IR of −0.20 (p≈0.21)** — the fundamental signal has real rank IC (0.085 @6m,
t≈2.2) but ~zero *harvestable long-only active edge* over the true benchmark. The prior dashboard panel
showed IR +2.11, an artifact of equal-weighting measured against an equal-weight universe. **The new tab
must present the honest numbers, not the flattering ones.**

The evaluation must separate two questions that were previously conflated:
1. **Signal ability** — can the composite rank names? (rank IC; long-short top-minus-bottom tercile
   spread, gross and net). This is where the signal looks decent.
2. **Tradable portfolio** — can we harvest it long-only vs MASI, after costs and the transfer-coefficient
   penalty of a ~60-name universe? This is where it currently does not beat the benchmark.
The gap between (1) and (2) is the long-only/breadth tax, and seeing both is what tells us how to improve.

## Prerequisites (correctness — a "proper backtest" depends on these)

These block a trustworthy tab; do them first (tracked from the 2026-07-06 review):
- **P1 — price-loader credentials/env.** `ic_study._build_price_loader` defaults to `minioadmin` and
  reads `AWS_ACCESS_KEY_ID/SECRET`; this env uses `minio`/`minio12345` and `S3_ACCESS_KEY/SECRET`. Align
  the env-var names and remove the wrong default, and **raise on an empty panel** instead of writing a
  no-row study/snapshot (a study must never silently run on zero rows again).
- **P2 — tercile bug in `technical_conditioning._assign_sfc_terciles`.** Line 50 pre-fills every row
  `"uncovered"`, so the `setdefault(idx, "middle")` on 57–58 is a no-op and the middle tercile is dropped
  (`non_bottom_sfc` collapses to `top_sfc_only`). Initialize the map empty or assign `"middle"`
  unconditionally, then re-run 67.
- **P3 — verify the technical signal's PIT integrity.** 67's technical IC (0.13 @3m) is high; confirm the
  per-(symbol,date) technical score is not using a best-method chosen on full-sample data (selection
  look-ahead). If it is, the technical IC is optimistic — fix the join to a PIT-available method before
  any conditioning conclusion stands.

## Task A — Backend: derive a trades ledger + dual evaluation from the SFC backtest

The backtest already emits (`portfolio_backtest.run_sfc_portfolio_backtest`): `equity_curve`
(strategy/universe/masi, segmented), `rebalance_rows` (holdings_in/out, turnover, per-period returns,
costs, active_return), `summary` (proof/selection/live), `significance`, `latest_holdings`. Add:

1. **Round-trip trades list** derived from `rebalance_rows`: for each symbol, pair the rebalance where it
   enters the book (open_date, open_price, weight) with the one where it exits (close_date, close_price),
   compute `pnl_return` over the hold (price return net of the entry/exit cost share). Shape it to the
   frontend `Trade` interface (`open_date, close_date, side="long", open_price, close_price, pnl_return`)
   consumed by `TradeLedgerTable`. Include still-open positions with `close_date=null`.
2. **Signal-ability panel data**: the long-short top-minus-bottom tercile spread series (gross and net at
   33/75 bps) and the rank IC table — reuse `ic_study.tercile_backtest` / `compute_ic_table` so the tab
   shows the signal's ranking power independent of the long-only book.
3. Expose both through the existing SFC snapshot API (`analytics` router; extend the response schema),
   PIT-guarded, carrying the same benchmark caveats already in `warnings`.

## Task B — Frontend: new "Portefeuille" tab in the fundamental signal page

Mirror the technical evidence backtest UX. In `frontend/components/strategy/fundamental/`:
1. Add `portefeuille` to `DetailTab` (`./lib/types`), to `tabFromQuery` + `FUND_TAB_PURPOSE`
   (`./lib/view-models`), and a tab button + render branch in `index.tsx` (same pattern as
   synthese/valuation/estimates/quality).
2. New `tabs/portefeuille-tab.tsx` with three sections, styled like `signal-evidence-tab.tsx`'s
   "WFO Stitched OOS Backtest" card:
   - **Résultats** — proof-segment stat tiles (CAGR, Sharpe, **IR vs MASI**, tracking error, max drawdown,
     turnover, bootstrap p-value), with the "validé sur 2023–2026 (une seule période de marché)" label and
     the single-regime + stale-benchmark caveats shown inline, never hidden.
   - **Courbe d'équité** — strategy vs float-weighted MASI vs equal-weight universe, selection/proof/live
     segments visually distinguished (reuse the equity-curve chart pattern).
   - **Journal des trades** — `TradeLedgerTable` fed by the Task A round-trip list (entry/exit dates,
     prices, hold return), plus the per-rebalance holdings_in/out and turnover.
   - **Capacité du signal** (the honest separation) — long-short tercile spread + rank IC, labeled as the
     signal's ranking power *before* the long-only harvest, so the −0.20 IR sits next to the +spread and
     the gap is legible.
3. **Remove the SFC panel from the dashboard** (`dashboard-v1/sfc-portfolio-backtest-panel.tsx`): delete
   its mount from the dashboard and, if nothing else consumes it, the component. The dashboard "Fondamental"
   mode keeps only the per-name SFC rank; the portfolio evaluation lives on the signal page.

## Task C — Model-improvement backlog (separate track, gated by the honest harness)

Only pursue after A/B give a trustworthy read. Ordered by expected payoff, each validated on the
selection half then proven once (brief 59 §5 discipline):
1. **Diagnose why QUAL/FMOM are flat** (61 showed VAL carries the composite). Check FMOM history depth and
   the QUAL component construction before assuming the pillars are dead — a data-coverage problem is
   fixable; a signal problem is not.
2. **Concentration / active-bound sensitivity.** The long-only ±3% cap on ~60 names is the binding
   constraint. Sweep top-quintile (vs tercile), wider active bounds, and a fixed-N concentrated book to
   see how much active edge the transfer coefficient is eating — this is the highest-leverage tradability
   lever given the fundamental law.
3. **Separate "signal ability" reporting from "tradability"** permanently, so improvements are judged on
   the long-short spread (pure signal) as well as the long-only IR (harvest).
4. Only after 1–3: revisit pillar weighting (still equal-weight per 59 §3.5) once ≥3y live pillar ICs
   exist — not before.

## Out of scope / guardrails
- No new flattering defaults: the tab's headline is the benchmark-relative IR, not the equal-weight Sharpe.
- Keep everything PIT-guarded and reproducible from the existing CLI entrypoints.
- Do not delete the IC study or backtest engine; this brief only relocates/expands their presentation and
  adds the trades-ledger + signal-ability views.
