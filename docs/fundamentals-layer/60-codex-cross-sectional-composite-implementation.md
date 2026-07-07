# 60 — Codex brief: implement the cross-sectional fundamental composite (SFC)

**Methodology + rationale**: read [`59-cross-sectional-composite-methodology.md`](59-cross-sectional-composite-methodology.md)
**first and in full** — every design decision below is justified there and must not be re-litigated
during implementation (in particular: equal pillar weights, publication-date PIT joins,
selection/proof split, long-only tercile construction).

Work in phases, **in order**. Each phase is a separate commit, leaves the repo green
(`pytest core services`, frontend build), and ends with `graphify update .`.
**Phase 1's gate decides whether Phases 3–4 run at all** — do not build UI ahead of evidence.

---

## Phase 1 — Research CLI: PIT panel + IC study (no app surface changes)

**Goal**: compute pillar and composite rank ICs on real MASI history and print a gate decision,
in the exact style of the existing `core/quant_core/fundamentals/pit_ic_backtest.py` (read it
first; reuse its PIT filters, universe file `bvc_pit_universe.csv`, price loading, and
`_assert_no_lookahead` pattern).

New module: `core/quant_core/fundamentals/cross_section/` with:

1. `panel.py` — build the PIT panel:
   - one row per (symbol, as_of_date) on a monthly grid;
   - fundamentals joined as-of `fundamental_annual_metric.publication_date`
     (fallback lags when null: annual +90d, semiannual +60d, quarterly indicators +45d);
   - consensus joined as-of `FundamentalConsensusEstimate.as_of_date`;
   - prices: close on or before as-of date; forward returns at 3/6/12 months (63/126/252 bars).
2. `pillars.py` — pure functions per pillar (VAL, QUAL, FMOM, PMOM) exactly as specified in
   brief 59 §4.2. Reuse `scoring.py` primitives (`_piotroski_lite`, `_dupont`,
   `_accrual_quality`) — import, don't reimplement. Cross-sectional MAD winsorization at ±3,
   z-scores demeaned separately for {financials+insurers} vs {non-financials} (reuse the
   archetype/tiering split); skip a bucket on any date with < 8 scored names.
3. `composite.py` — SFC = mean of available pillar z (≥ 2 pillars required), plus
   `coverage_ratio` and per-pillar attribution dict.
4. `ic_study.py` — CLI entry point
   (`python -m quant_core.fundamentals.cross_section.ic_study`):
   - Spearman rank IC per date per horizon, for each pillar and the composite;
   - Newey-West t-stats on the IC series (reuse the HAC approach from
     `core/quant_core/factor_selection/direct.py::_hac_t_stat`);
   - **selection/proof split**: chronological first half = selection (used to choose 6-1 vs
     12-1 PMOM and any component-set choices — log every variant tried), second half = proof,
     evaluated once with the frozen config;
   - Benjamini–Hochberg FDR at 10% across all proof-half tests (pillars × horizons + composite
     × horizons + every selection-half variant carried to proof);
   - tercile long-only backtest (top tercile equal-weight vs universe equal-weight), net of
     33 bps/side and stressed at 75 bps/side, block-bootstrap p-value via
     `core/quant_core/significance.py`;
   - prints an IC table + a **gate verdict** per brief 59 §5.5
     (composite proof-half NW t ≥ 2.0 at ≥ 1 horizon AND net tercile spread > 0 at 33 bps,
     ≥ 0 at 75 bps).

**Tests** (pytest, no DB — synthetic frames): look-ahead assertion fires on a violating row;
winsorization/z-score correctness; ≥2-pillar coverage rule; a name with a known top rank ends
in the top tercile; FDR arithmetic on a hand-computed example.

**Deliverable**: the printed study on real data, committed as
`docs/fundamentals-layer/61-sfc-ic-study-results.md` (raw table + verdict + config hash).
**STOP after Phase 1 and report the verdict.** If the gate fails, Phases 3–4 are cancelled and
the negative finding is written up in doc 61 (brief 59 §5.6) — Phase 2 persistence may still
land if trivially small.

## Phase 2 — Persistence + scheduled computation

- New table `fundamental_cross_section_score` (alembic migration):
  `(symbol, as_of_date)` PK-ish unique, columns: `sfc`, `rank`, `tercile`,
  `pillar_val`, `pillar_qual`, `pillar_fmom`, `pillar_pmom`, `coverage_ratio`,
  `attribution_json`, `config_hash`, `methodology_version`, `computed_at`.
- Worker job registered in the existing scheduler (`services/.../schedules`): recompute the
  cross-section after each publication-window (reuse the cadence machinery that drives the
  weekly signal-engine batch; a weekly run that no-ops when no new publication arrived is
  acceptable v1).
- Versioning: `SFC_METHODOLOGY_VERSION` constant; any pillar-definition change bumps it and
  is an append (new rows), never an overwrite of history.

## Phase 3 — API + dashboard integration (only if Phase 1 gate passes)

- Router: `GET /analytics/fundamental-cross-section?as_of=` → ranked list with pillar
  attribution; `GET .../fundamental-cross-section/{symbol}` → score history.
- Dashboard "Fondamental" mode (`frontend/app/v1/page.tsx` + `dashboard-v1/
  fundamental-directions-tab.tsx`): rank by **SFC** instead of ensemble upside; columns:
  rank, SFC, four pillar chips (with tooltip attribution), coverage badge, tercile tone.
  Ensemble upside moves to the drill-down only, labeled "Ancre de valorisation (non-signal)".
- Per brief 59 §7: in the Valorisation tab, disable the IC weighting toggle with an explanatory
  tooltip wherever the IC spread is degenerate; DCF/DDM/RI presented in the diagnostic family.
- French labels, correct accents.

## Phase 4 — Portfolio construction + blotter (only if Phase 1 gate passes)

- `core/quant_core/research/fundamental_portfolio.py`: tercile → bounded active weights vs
  MASI (default ±3% per name), delegating sector caps + ADV participation + cash buffer to the
  existing blotter machinery in `services/api/app/services/dashboard_portfolio.py`.
- Blotter source option `"sfc"` alongside the existing edge sources; bottom tercile emits
  AVOID (zero target), never SELL-short, for MASI equities.
- Rebalance proposals generated only on publication-window recomputes (Phase 2 job), surfaced
  as a dated ticket in the existing ticket UI.

---

## Hard constraints (all phases)

- **No look-ahead**: publication-date/as-of joins everywhere; assertion guards in every
  backtest path.
- **No fitted pillar weights, no optimizer, no ML** — equal weights are a design commitment
  (brief 59 §3.5).
- **No threshold shopping**: the Phase 1 gate is evaluated once; a failed gate is a published
  negative result, not a parameter search.
- Do not modify the technical-edge gates or `core/quant_core/research/edge.py`.
- Do not start the brief-57 UI redesign work here; Phase 3 touches only the listed surfaces.
- Fundamentals N/R verdicts are cached — before attributing any missing metric to a data bug,
  re-run the live tie-out (known trap).
