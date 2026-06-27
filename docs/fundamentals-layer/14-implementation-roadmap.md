# Implementation roadmap

Prioritized work for Codex (or any implementer) to evolve the fundamentals layer from its current state to institutional quality. The v3 pass has implemented the 21 known issues in [12-known-issues-and-limitations.md](12-known-issues-and-limitations.md).

## Current status

All Phase A, B, and C items below are implemented in v3:

- Valuation correctness fixes V1-V6.
- Configuration/API polish V7-V9.
- Scoring correctness and auditability S1-S9.
- Institutional features V10-V12.

Remaining work is operational: migrate databases, re-import/rescore fundamentals, review sample fair-value shifts, and monitor API/UI consumers for the clean contract changes.

## Priority framework

Two axes:
- **Severity**: 🔴 logic concern, 🟡 configuration smell, 🔵 missing feature.
- **Impact**: does the fix change the headline numbers (fair value, scores)? Does it surface new data the analyst can use?

Suggested 3-phase rollout:

| Phase | Theme | Scope | Risk |
|---|---|---|---|
| **A** | Correctness fixes for valuation | 🔴 V1-V6 + S1-S3 | Medium-high (changes fair values) |
| **B** | Configuration polish | 🟡 V7-V9 + S4-S7 | Low-medium |
| **C** | Institutional features | 🔵 V10-V12 + S8-S9 | Low (additive) |

Each phase is 4-8 PRs. Each PR ships one issue (with tests and doc updates).

## Phase A — Correctness fixes

These change headline numbers, so test coverage and pre-deploy rescores are critical.

### A.1 — V4 (FCFF DCF growth input)

**Why first:** lowest-risk correctness fix. Adds preference order for growth inputs without changing math.

- Add `_fcf_growth_input()` helper in `valuation.py`.
- Modify `_fcff_dcf` to use it.
- Expose `fcf_growth_source` in `ValuationResult.inputs`.
- Test: symbol with `FCF_Growth` metric uses it; symbol without falls back as documented.

**Acceptance:** all existing tests pass with one new test verifying the fallback chain.

### A.2 — V5 (NetDebt fallback)

**Why second:** independent of growth fix. Adds explicit warning when NetDebt is missing.

- Add `_net_debt_bridge()` helper.
- Modify `_fcff_dcf` to consume it, append warning, cap confidence.
- Test: workbook with Debt-Cash but no NetDebt → bridge computed; workbook with neither → warning fires.

### A.3 — V6 (Justified multiples growth fade)

**Why third:** symmetric to A.1 (growth handling). Adds `_justified_growth()` helper for linear fade.

- Add helper.
- Modify `_justified_multiples` to use it.
- Test: high-growth firm (sustainable > terminal) → fades, not clipped.

### A.4 — V2 (DDM sustainable growth)

**Why fourth:** independent of V4/V6, similar pattern.

- Reuse `_sustainable_dividend_growth()` (logic already exists inside justified_multiples).
- Modify `_ddm`.
- Test: high-payout firm has growth ≈ 0; low-payout firm has growth ≈ ROE × retention.

### A.5 — V3 (Residual income fade)

**Why fifth:** higher risk (banks valuation will shift). Needs careful testing.

- Implement `_residual_income_with_fade`.
- Compare bank fair values before/after on a sample. Document the shift in `08-assumptions-and-defaults.md`.
- Test: ROE=COE → fair = book value; ROE > COE → fair > book by less than no-fade version.

### A.6 — V1 (FCFE proxy → real FCFE when data permits)

**Why sixth:** dependent on workbook spec changes (need `Interest_Expense`, `Debt_Issuance`, `Debt_Repayment` in canonical vocabulary).

- Add new metric names to `core/quant_core/fundamentals/normalize.py` (or equivalent).
- Implement `_fcfe_start` helper.
- Modify `_fcfe_dcf`.
- Test: symbol with full debt-flow data → `is_proxy=False`, full weight; symbol without → unchanged behaviour.

### A.7 — S2 (Sector-bucketed scoring)

**Why seventh:** non-trivial refactor of `_metric_percentiles`. Touches both scoring.py and the resulting `snapshot.scores` shape.

- Add `_metric_percentiles_by_sector`.
- Surface `scope` per pillar score.
- Coordinate with frontend to display scope chips.

### A.8 — S1 (Metric overlap)

**Why eighth:** product decision (deduplicate vs document). Should follow S2 because sector buckets surface the overlap more starkly.

- Pick Option A or B from [S1](12-known-issues-and-limitations.md#-s1).
- Update `_METRICS` tuples and/or `OVERALL_WEIGHTS`.
- Re-run scoring on test cohort, compare before/after.

### A.9 — S3 (Single-symbol scoring)

**Why last in Phase A:** depends on the yfinance ingestion path (Phase −1 in the integration plan above). The fix is small but only valuable once we have a use case.

- Update `_percentile_scores` to return None for cohort < min_count.
- Propagate None correctly downstream.

## Phase B — Configuration polish

### B.1 — V7 (WACC default)

- Change `DEFAULT_ASSUMPTIONS["wacc"]` to 0.0851.
- Add `cost_of_debt` and capital-structure weights as comments in docs.
- Verify FCFF DCF outputs shift consistently.
- Document the new default in `08-assumptions-and-defaults.md`.

### B.2 — V8 (Currency tagging)

- Add `currency` field to `FundamentalSnapshot.source`, `ValuationResult`, `EnsembleResult`.
- Default to `"MAD"` for all existing rows (migration).
- Add `currency` check in `compute_valuation_ensemble`.
- Required precursor for yfinance integration.

### B.3 — V9 (Reverse DCF rendering)

- `_reverse_dcf` returns `fair_value=None`, surfaces `implied_perpetual_growth` and a narrative.
- Frontend: render Diagnostic models distinctly.

### B.4 — S4 (Dividend pillar decision)

- Pick Option A or B from [S4](12-known-issues-and-limitations.md#-s4).
- Update `snapshot.scores` shape.

### B.5 — S5 (Health rename or recompute)

- Pick Option A (rename) or Option B (recompute) from [S5](12-known-issues-and-limitations.md#-s5).
- Update docs everywhere.

### B.6 — S6 (Quality audit trail)

- Add `quality_raw`, `quality_components` to `snapshot.scores`.
- UI tooltip showing breakdown.

### B.7 — S7 (Partial-coverage flag)

- Return `(overall, coverage_pct)` from `_weighted_score`.
- UI: "Partial" chip when coverage < 0.7.

## Phase C — Institutional features

### C.1 — V12 (Sensitivity tables)

**Why first in C:** highest analyst value, lowest implementation complexity.

- Add `compute_sensitivity()` helper.
- New endpoint `GET /fundamentals/stocks/{symbol}/sensitivity`.
- Frontend heatmap on valuation tab.

### C.2 — V11 (Scenarios)

- Default assumption sets for bear / base / bull at the global / sector level.
- `compute_symbol_valuations_all_scenarios` orchestrator.
- Persist all three scenarios in `FundamentalEnsembleResult`.
- Frontend: 3-column scenario comparison.

### C.3 — V10 (Monte Carlo overlay)

- `_monte_carlo_fair_value()` helper (per model).
- New fields `monte_carlo_low/base/high` on `EnsembleResult`.
- Rename existing `fair_value_low/base/high` → `model_dispersion_*` for clarity.
- Frontend: display both bands with labels.

### C.4 — S8 (Magnitude alongside percentile)

- `_metric_breakdown()` returning z-score + pct_deviation.
- Persist in `snapshot.diagnostics["metric_breakdown"]`.
- Frontend toggle on score display: percentile / z-score / pct-deviation.

### C.5 — S9 (Trailing averages)

- `_trailing_average()` helper.
- Compute and persist trailing values alongside latest.
- Frontend toggle on cyclical pillars: latest / 3y trailing / 5y trailing.

## Dependencies

```
A.1 (V4) ────┐
A.2 (V5) ────┤
A.3 (V6) ────┤
A.4 (V2) ────┴── all independent, can ship in parallel

A.5 (V3) ────── depends on A's testing infrastructure (regression suite for bank fair values)

A.6 (V1) ────── depends on workbook metric vocabulary additions

A.7 (S2) ────── prerequisite for A.8 (S1) understanding

A.9 (S3) ────── depends on yfinance ingestion path (Phase −1 in main plan)

B.2 (V8) ────── prerequisite for non-MASI yfinance ingestion

C.1 (V12) ───── independent
C.2 (V11) ───── independent
C.3 (V10) ───── independent
C.4 (S8) ───── ideally after S2 (sector context strengthens magnitude reads)
C.5 (S9) ───── independent
```

## Phase D — Institutional screens (Addendum #3)

Adds 5 new screening methods that complement the 6-pillar scoring and 7 valuation models. Full specification: [16-institutional-screens.md](16-institutional-screens.md).

### D.1 — Magic Formula + PEG/GARP

- New module `core/quant_core/fundamentals/screens.py`.
- Both use existing canonical metrics; no workbook spec changes.
- Wired into `score_fundamental_snapshots` → `snapshot.diagnostics["screens"]`.
- Tests + API extension.

### D.2 — Altman Z-score

- Workbook spec adds `Retained_Earnings` and `Total_Liabilities` (graceful degradation when missing).
- Two variants: 5-factor manufacturing (Z), 4-factor emerging-market for financials (Z'').
- Persisted as `screens.altman_z` with zone label.

### D.3 — EVA

- ROIC vs WACC spread × invested capital.
- Skipped for financial-sector firms (regulatory capital is different).
- Verify `Total_Debt` presence (fall back to `NetDebt + Cash`).

### D.4 — Regression-adjusted multiples

- OLS fit per multiple via `np.linalg.lstsq`.
- Cohort size gating (≥8 peers for stable regression).
- Sector vs market scope fallback.

### D.5 — `/fundamentals/screens/{screen_name}` endpoint + universe columns

- Ranked-by-screen endpoint.
- Universe table gains 5 new toggleable columns.
- Docs: 16-institutional-screens.md.

## Phase E — DEPRECATED (superseded by Phase F)

Phase E in this document originally described a standalone-page UI rebuild with 7 tabs. **It is superseded by the Claude Design handoff** (see [20-claude-design-handoff.md](20-claude-design-handoff.md)) which restructures the rebuild around:
- Unified `/signals` page with a 3-mode switcher (Technical / Fundamental / Quantitative) instead of the standalone `/fundamentals` page.
- 5-tab Fundamental view (Thèse / Valorisation / Qualité & ROE / Estimations / Comparables) instead of 7 tabs.
- DM Sans + DM Mono fonts and oklch color tokens instead of Inter + IBM Plex Mono + hex.

The actual UI work proceeds via **Phase F (D5.0 → D5.9)** below.

## Phase F — Claude Design rebuild (canonical UI plan)

Implementation phases derived directly from the Claude Design handoff bundle. Specs:
- [20-claude-design-handoff.md](20-claude-design-handoff.md) — canonical visual + topology spec.
- [15-ui-goals-and-design.md](15-ui-goals-and-design.md) — page layout + tab content per the handoff.
- [17-ui-design-language.md](17-ui-design-language.md) — DM Sans/Mono + oklch tokens.
- [18-ui-component-library.md](18-ui-component-library.md) — 31 components (#1–#18 original + #19–#31 new).
- [19-ui-tear-sheet-spec.md](19-ui-tear-sheet-spec.md) — print/PDF export.
- [16-institutional-screens.md](16-institutional-screens.md) — screens integrated into Qualité + Comparables tabs.

Feature-flagged behind `NEXT_PUBLIC_FUNDAMENTALS_V2_UI=true`. Each PR independently shippable.

### D5.0 — Foundation
- Add DM Sans + DM Mono via `next/font/google`.
- Update Tailwind tokens to oklch palette (light + dark) per [17-ui-design-language.md](17-ui-design-language.md) §14.
- Build foundation atoms: `<Chip>`, `<ScoreBar>`, `<Sparkline>`.
- Set up `tabular-nums` globally on `html, body`.

### D5.1 — App shell + mode switcher
- New `/signals` route hosts mode switcher.
- Build `<ModeSwitcher>` (#19) per [20-claude-design-handoff.md](20-claude-design-handoff.md) §"Mode switcher".
- Wire `?mode=` URL state.
- Existing TechnicalView stays in place (lift into the mode-shell pattern).
- 301 redirect: `/fundamentals?...` → `/signals?mode=fundamental&...` (already in place).

### D5.2 — Fundamental view shell + universe screen
- New `<UniverseScreen>` (#19a) — 380px wide, research overlay with BUY/HOLD/SELL filter chips + sort dropdown + bottom summary bar.
- New `<ResearchTicket>` (#20) header per spec.
- 5-tab nav (Thèse · Valorisation · Qualité & ROE · Estimations · Comparables).
- URL state for `?fund_tab=`.

### D5.3 — Thèse tab
- `<ThesisCard>` — sub-component for the eyebrow + 2-paragraph thesis.
- `<ScenarioCards>` (#22) — 3-card bear/base/bull grid + expected-price line.
- `<CatalystList>` (#23) — 5 catalyst items.
- `<RiskRegister>` (#24) — 5 risk rows with severity meter.

### D5.4 — Valorisation tab (user's chief pain point — click DCF/DDM to drill down)
- `<FootballField>` (#21) — SVG range chart.
- `<MethodologyCardRow>` × 7 — list of expandable rows. Each row uses `<MethodologyCard>` (#1) body when expanded. Methods: FCFF DCF, FCFE DCF, DDM, Residual income, Justified multiples, Relative multiples, Reverse DCF.
- `<ComputationStepsTable>` (#2) — per-model step traces (use `model-step-traces.ts` lib).
- `warning-dictionary.ts` — plain-language warning translations.
- DCF assumptions card (8 stat tiles).
- `<SensitivityHeatmap>` (#13) with oklch coloration.
- "Modifier" link in DCF assumptions card → opens `<AssumptionEditor>` (#11 retained from original list).

### D5.5 — Qualité & ROE tab
- 4-KPI grid (Score global / qualité / santé / croissance).
- `<DuPontDecomposition>` (#25) — 4 boxes Marge × Rotation × Levier = ROE.
- `<PeerComparisonBar>` (#26) list — ROIC, Marge opér., FCF conversion, etc.
- **Altman Z card** (from Addendum #3 backend) with `<ZoneGauge>` (#14).
- **EVA card** (from Addendum #3 backend) with dual horizontal bars.

### D5.6 — Estimations tab
- `<EstimationsTable>` (#27) — 6-year P&L (3A + 3E).
- `<ConsensusVsHouse>` (#28) — FY 2026E consensus vs house.

### D5.7 — Comparables tab
- `<ComparablesTable>` (#29) — MENA + global peers with relative-vs-median coloration.
- `<RelativeValuationTiles>` (#30) — 3-tile summary (décote vs médiane / vs historique / rendement total).
- **Magic Formula card** (from Addendum #3 backend).
- **PEG / GARP card** (from Addendum #3 backend).
- **Regression-adjusted multiples card** (from Addendum #3 backend).

### D5.8 — Quantitative view rebuild
- `<QuantitativeView>` per `sr-quantitative.jsx`: leaderboard sidebar + 4 tabs (Stat-arb / IC / Facteurs / Macro).
- **Outside fundamentals-layer scope** but part of the Claude Design handoff.

### D5.9 — Tweaks panel + polish
- `<TweaksPanel>` (#31) — dark/light, sidebar width S/M/L, default mode. Server-backed persistence via `frontend/app/api/account/preferences/dashboard/route.ts` (extend existing schema; NO localStorage).
- `<TearSheet>` (#18) + print stylesheet per [19-ui-tear-sheet-spec.md](19-ui-tear-sheet-spec.md).
- Accessibility audit (Lighthouse ≥ 95).
- Final visual regression test against the prototype HTML.

## Dependencies (Phases D & F)

```
D.1 (Magic + PEG) ─┬── independent
D.2 (Altman)      ─┤── workbook spec adds RE, TL
D.3 (EVA)         ─┤── independent
D.4 (Regression)  ─┤── independent
D.5 (endpoints)   ─┴── after D.1-D.4

F.0 (Foundation)  ─── must come first
F.1 (Mode shell)  ─── after F.0
F.2 (Fund. shell) ─── after F.1
F.3 (Thèse)       ─── after F.2
F.4 (Valorisation)─── after F.2  (user's chief pain point)
F.5 (Qualité)     ─── after F.2, integrates Altman + EVA from Phase D
F.6 (Estimations) ─── after F.2
F.7 (Comparables) ─── after F.2, integrates Magic Formula + PEG + Regression from Phase D
F.8 (Quantitative)─── after F.1 (independent of fundamentals layer)
F.9 (Tweaks/print)─── after F.3-F.7
```

## Total scope summary

| Phase | Theme | Duration |
|---|---|---|
| A | Correctness (V1-V6, S1-S3) | 4-6 weeks |
| B | Configuration (V7-V9, S4-S7) | 2-3 weeks |
| C | Institutional features (V10-V12, S8-S9) | 2-3 weeks |
| D | Five institutional screens (Magic Formula / PEG / Altman / EVA / Regression-adj) — backend | 3-4 weeks |
| F | Claude Design UI rebuild (D5.0–D5.9) — frontend | 5-7 weeks |
| D | Institutional screens (5 new) | 3-4 weeks |
| E | Professional UI rebuild | 5-7 weeks |

Total: roughly 16-23 weeks for one skilled engineer to ship everything, or 8-12 weeks with 2 engineers (one backend on A-D, one frontend on E).

## Out of scope for this layer (deferred)

- **Signal-engine integration** (Phase C of the parallel integration plan in `/Users/taha/.claude/plans/`). Fundamentals consume by signal engine, not the other way around.
- **Real-time data feed.** Workbook + yfinance batch are the only ingestion paths.
- **Cross-currency arithmetic.** Currency tagging (V8) is in scope; FX conversion is not.
- **Bloomberg/Refinitiv integration.** Own subsystem.
- **Analyst notes / commentary.** Hand-written context goes in a separate research notes table not yet specified.
- **Mobile-optimized layout.** Current target is desktop (≥ 1024px). Mobile is a follow-up phase.
- **Multi-language UI** (English / French / Arabic). Current rebuild ships in French (primary user base); i18n is a follow-up.

## Cadence

Suggested:
- 1 PR per issue.
- Each PR: code change + tests + docs update.
- After Phase A ships: deploy, re-import all workbooks (rescore), validate sample fair values manually.
- After Phase B: deploy, no rescore needed.
- After Phase C: deploy, opt-in features behind flags initially.

Total effort estimate (skilled engineer): 4-6 weeks for Phase A, 2-3 weeks each for B and C.

## See also

- [12-known-issues-and-limitations.md](12-known-issues-and-limitations.md) — full issue catalog with fix recipes.
- [11-prompts-for-claude.md](11-prompts-for-claude.md#16-plan-the-next-implementation-phase) — prompt for re-prioritizing.
