# 65 — SFC amendments: own-history diagnostic, technical integration, construction fixes

**Status**: implementation brief for Codex, 2026-07-06. Amends [`59`](59-cross-sectional-composite-methodology.md)
(methodology) and the shipped SFC layer (`core/quant_core/fundamentals/cross_section/`,
`services/api/app/services/fundamental_cross_section.py`). The SFC layer is live and its IC gate
**passed** ([`61-sfc-ic-study-results.md`](61-sfc-ic-study-results.md), verdict PASS, proof-half
6m composite IC 0.085 / t 2.18, 3m net tercile spread +3.4%/qtr surviving 75 bps).

**Non-negotiable discipline for all three tasks** (same standard as the existing layer):
- Point-in-time joins only: fundamentals on `availability_date` (publication date or the conservative
  fallback lag), consensus on `as_of_date`, prices ≤ as-of. Reuse `panel.build_pit_panel` and its
  `_assert_no_lookahead` guard; do not hand-roll a parallel PIT path.
- Selection/proof split at 2023-07-31 (`SFC_PROOF_SPLIT_DATE`). Any new definitional choice is made
  on the selection half; the proof half is touched once with the frozen config. HAC/Newey-West
  t-stats and BH-FDR at 10% across every variant carried to proof, exactly as `ic_study.py` does.
- No threshold shopping. A failing study is published as a negative finding, not retuned.
- Do not change any live scoring behavior in Task 1 (it is a diagnostic only). Tasks 2 and 3 change
  behavior and must ship behind the same gate/label conventions already in the layer.

---

## Task 1 — Own-history (time-series) value percentile as a gated diagnostic

**Goal**: measure whether de-meaning each name against its *own* fundamental history adds
cross-sectional information beyond the universe-wide VAL z-score — without touching the live SFC.
Motivation: the two-bucket cross-sectional z conflates a name's structural ratio *level* (e.g. IAM
is a regulated monopoly with a permanently distinct E/P) with its *timing* (is IAM cheap vs its own
norm). For thin-comparability / singleton-sector names the level component is meaningless; the
own-history axis isolates the timing component. This is the intra/inter decomposition of
Asness–Porter–Stevens with "the name itself" replacing "the industry".

**Why it must be gated, not assumed** (the user's data-history objection, made precise): the value
ratios carry price in the denominator, so E/P etc. move at monthly frequency from a single annual
numerator — the effective own-history sample is large where fundamentals exist. But our fundamental
panel is only reliable from ~2016 and pre-2023 covered ~14 names, so today most names fail a real
history gate. The study must report coverage, not paper over it.

**Implement** (new module `core/quant_core/fundamentals/cross_section/own_history.py` + a study path;
reuse existing panel/pillar code, add nothing to the live composite):
1. For each (symbol, as_of_date) in the PIT panel, build the trailing monthly series of
   `pillar_val_raw` (the raw value composite already computed in `pillars._value_raw`), holding the
   last-published numerator constant between publications and letting the PIT close move the ratio.
   Use only data with `availability_date <= as_of_date`.
2. `own_hist_pct` = rank of today's `pillar_val_raw` within its trailing window (default 60 months),
   gated: require ≥ `min_months` observations (default 36) **and** ≥ `min_fiscal_years` distinct
   published numerators (default 3); else `own_hist_pct = NaN` (name is diagnostic-uncovered on this
   axis — never a fabricated percentile). Map to a z-equivalent via inverse-normal for comparability.
3. Emit a coverage report: names passing the gate per as-of date, and the share of the universe.
4. Extend the IC study (reuse `ic_study.compute_ic_table` / `chronological_split` / the BH-FDR
   family) to score three signals on the proof half: cross-sectional `pillar_val`, `own_hist_z`
   standalone, and a 50/50 blend. Report standalone IC **and marginal IC** (blend minus
   cross-sectional-only) at 3/6/12m.

**Acceptance**: a results doc `docs/fundamentals-layer/66-own-history-diagnostic.md` with the coverage
table and the three-signal proof-half IC/FDR table, and an explicit verdict line. **Do not** wire
`own_hist_z` into `composite.compute_sfc` or any live/persisted score in this task. Promotion to the
live composite is a separate decision that requires the blend's marginal IC to clear NW t ≥ 2 on the
proof half with positive coverage — state that in the doc; do not do it now.

---

## Task 2 — SFC-conditioned technical IC study (the fundamentals → technical bridge)

**Goal**: quantify whether the technical model's edge is conditional on the fundamental rank — i.e.
whether a fundamental *filter/tilt* improves the technical signal. This is the actual deliverable that
translates the fundamental layer into the desk's technical process. It is a **study**, not a wired
change — the wiring decision follows the result.

**Design**:
1. Build a per-(symbol, as_of_date) technical signal series from the existing proven-edge machinery
   (`core/quant_core/research/score_history.py` — `build_engine_category_series` /
   `build_wfo_category_series` / `_calculate_forward_returns`; the best-method artifact lives in
   `signal_best_evidence_snapshot`). Locate the per-bar technical entry score/decision already used
   by the signal page; do not invent a new technical signal. Confirm its PIT correctness with the
   same `_assert_no_lookahead` standard before use.
2. Join to the SFC panel on matched monthly as-of dates. Assign each name its SFC tercile at that
   date (top / middle / bottom), using only PIT-available SFC scores.
3. Compute the technical signal's forward-return IC (and hit-rate / mean forward return) **within each
   SFC tercile**, 3/6/12m, HAC t-stats, selection/proof split, BH-FDR across the tercile × horizon
   family. Headline hypothesis (from the value-trap logic): technical IC concentrates in top-SFC names
   and is degraded/negative in bottom-SFC names.
4. Report the practical decomposition the desk needs: technical edge on the full universe vs. technical
   edge restricted to non-bottom-SFC names (the avoid-list filter) vs. technical edge on top-SFC names
   only (the tilt).

**Acceptance**: results doc `docs/fundamentals-layer/67-sfc-technical-conditioning.md` with the
tercile-conditioned IC table and an explicit verdict on which of three integrations the data supports:
(a) avoid-list veto only, (b) SFC-tercile position sizing, (c) event-window drift overlay (technical
breakout coincident with a positive FMOM publication window). Wire nothing into live sizing in this
task; the doc's verdict gates that as a follow-up.

---

## Task 3 — Portfolio-construction fixes to match brief 59 §4.4

The shipped `portfolio_backtest.run_sfc_portfolio_backtest` deviates from the approved methodology on
two points. Fix both, keep the existing proof/selection/live segmentation, cost model, significance
test, and labels.

**3a — Event-anchored rebalancing.** `_target_rebalance_dates` currently supports only `"monthly"` /
`"quarterly"` clock rebalances. Add `rebalance="event"`: rebalance only on as-of dates that follow a
fundamental publication window (annual / semiannual / quarterly-indicator availability), derived from
the panel's `availability_counts` / `max_metric_availability_date` — ~4/year, not 12. Make `"event"`
the default in `SfcPortfolioBacktestConfig` per §4.4; keep `"monthly"`/`"quarterly"` selectable for
sensitivity. Between events, hold (liquidity/risk exits only). Re-run the snapshot and report turnover
vs. the monthly baseline (expect a large turnover reduction — the design's core cost lever).

**3b — Benchmark-relative bounded active weights instead of naive equal-weight tercile.**
`_top_tercile_holdings` assigns 1/n_top to every top-tercile name. Replace with the brief's
benchmark-relative construction using the **real free-float MASI weights** exposed to Python in Task 4
(sourced from `frontend/lib/builtin-dashboard-indices.ts` → `BUILTIN_WEIGHTED_MASI_INDEX`, the same
float shares the indices tab renders). Build a `benchmark_weights.py` helper:
- benchmark weight = `float_shares × pit_close`, normalized over MASI all-share membership at each
  rebalance date, where `float_shares` comes from the Task 4 source. `free_float_factor` is an optional
  override, not the primary path.
- **Caveats to bake into the snapshot `warnings` and the results doc**: the float shares are a **single
  snapshot dated 2026-05-25** — exact for live construction, but applying them across the 2017–2026
  backtest is a documented staleness approximation in the benchmark weights only (float factors drift;
  capping resets at each quarterly review). Use the MASI all-share figures (not MASI 20 / ESG, which
  apply different capping / weighting schemes).
- **Two mandatory labeled caveats** (do not hide): (i) this is a **full-cap approximation of MASI**,
  not the published free-float index — it overweights the mega-caps (IAM, banks) that the ±3% bounds
  are most sensitive to; (ii) `shares_outstanding` is a latest snapshot, not PIT (there is a
  `shares_as_of` but no full history), so applying it to past dates is a mild look-ahead **in the
  benchmark weights only** — record both in the snapshot `warnings` and the results doc.

Then implement the active-weight book: overweight top tercile bounded to ±3% active vs the
reconstructed benchmark, middle tercile = benchmark weight, bottom tercile = zero (a long-only
underweight is capped at the name's benchmark weight — the transfer-coefficient limit from §46–49).
Apply a per-name active cap (default ±3%) and the existing per-sector and ADV caps; renormalize to
fully invested. Report financials-vs-non-financials active exposure at each rebalance (§6 mitigation).
Keep an equal-weight top-tercile mode selectable for comparison against the current snapshot.

**Acceptance**: updated `run_sfc_portfolio_backtest` + tests (extend
`core/tests/test_sfc_portfolio_backtest.py`), a refreshed `fundamental_sfc_backtest_snapshot`, and the
proof-segment headline recomputed under event rebalancing + capped weights. Preserve the
"validé sur 2023–2026 (une seule période de marché)" labeling and the single-regime / p≈0.08 active-
return caveat — do not present the new Sharpe/IR without it.

---

## Task 4 — Expose the existing free-float shares to the Python backtest

**Reality (verified 2026-07-06)**: the free-float capped shares are ALREADY in the repo, symbol-mapped
and ingested from the Excel — `frontend/lib/builtin-dashboard-indices.ts`
(`BUILTIN_WEIGHTED_MASI_INDEX` = MASI all-share float shares; plus MASI 20, ESG, Mid&Small, and 24
sector indices). The indices tab renders these as its "Actions" column. There is **no re-ingestion, no
ISIN mapping, and no name matching to do** — that work is done and the tickers already match the app's
symbols (ATW, IAM, BCP…). The only gap is that this is a **frontend TS constant** and the SFC backtest
is **Python** (`core/quant_core`), which cannot import it.

**Implement (small)**:
1. Make the same MASI all-share float table available to Python as a single source of truth. Preferred:
   a generated `core/quant_core/fundamentals/cross_section/masi_float_shares.py` (or a small JSON under
   `data/`) carrying `{symbol: float_shares}` for `BUILTIN_WEIGHTED_MASI_INDEX`, with a header noting it
   is generated from `Compo_All_Indices.xlsx` (snapshot 2026-05-25) and must stay in sync with the TS
   file. Do not fork the numbers by hand-copying selectively — port the full list so the two cannot drift
   silently; if feasible, generate both the TS and the Python/JSON from the Excel via one script so the
   single upstream source is the workbook.
2. Task 3b's benchmark reader consumes this table directly (weight = float_shares × PIT close,
   normalized over membership). `free_float_factor` becomes an optional override, not the primary path.

**Acceptance**: the Python backtest reads MASI all-share float shares for the covered symbols from the
new source; a test asserts a handful of values match the TS file (e.g. ATW 64,542,252; IAM 175,819,068;
BCP 30,496,871); the single-snapshot (2026-05-25) caveat is recorded so downstream users know the
benchmark weights are as-of that date until a composition history is collected.

---

## Out of scope / guardrails
- No new fundamental ingestion, no vintage changes, no regional-peer augmentation of the ranking
  (regional comps stay in the single-name anchor only).
- No live UI change until the relevant study doc carries a PASS verdict; these three tasks produce
  studies (1, 2) and a corrected backtest (3), not new user-facing signals.
- Keep every new column/artifact PIT-guarded and reproducible from a single CLI entrypoint, matching
  `ic_study.main()`.
