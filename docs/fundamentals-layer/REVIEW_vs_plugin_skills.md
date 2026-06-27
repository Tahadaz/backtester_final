# Fundamental layer — review against the financial-analysis & equity-research plugin skills

> **What this is.** A read-only audit of the app's bespoke fundamental subsystem, judged against the rubrics in the Claude `financial-analysis`, `equity-research`, `market-researcher`, and `valuation-reviewer` plugin skills (loaded from `~/.claude/plugins/cache/claude-for-financial-services/`).
>
> **Why now.** The fundamental layer was implemented entirely by hand — none of the plugin skills were used during design or implementation (verified: zero references in code, docs, or commit history). This document is the post-hoc check: did we end up at parity with the standard rubric, and where did we under-build?
>
> **Author opinion is included at the end.** Component sections are graded ✅ aligned / ⚠️ partial / ❌ missing with file:line citations.

---

## 1. DCF / FCFF / FCFE / DDM / Reverse-DCF

**Rubric** (`financial-analysis:dcf-model`):
- WACC built from CAPM (Rf + β × ERP + size/country premia) — explicit, not hard-coded.
- 5–10y explicit forecast + terminal value (Gordon or exit multiple), mid-year convention.
- Sanity: TV typically 50–70 % of EV; flag if higher.
- Three scenarios (Bear / Base / Bull) with separate assumption blocks.
- Sensitivity tables (≥ 5×5) on WACC × terminal growth and WACC × exit multiple.

**App** (`core/quant_core/fundamentals/valuation.py`):
- **FCFF DCF** at `valuation.py:419-472` — linear growth fade 6 → 3 % over 5y, WACC from `assumptions.wacc` (default 8.51 %), Gordon terminal. ✅
- **FCFE DCF** at `valuation.py:469-528` — COE discount; uses real debt flows when `Interest_Expense / Debt_Issuance / Debt_Repayment` present, else FCF proxy with confidence haircut. ⚠️
- **DDM** at `valuation.py:508-590` — Gordon with sustainable growth `g = ROE × (1-payout)`. ✅ Methodologically clean (this is an improvement over the earnings-growth proxy used in earlier versions).
- **Reverse-DCF** at `valuation.py:669-697` — diagnostic only, returns `implied_perpetual_growth = WACC − FCF_Yield`, correctly excluded from ensemble. ✅
- **Moroccan defaults** at `valuation.py:16-32` — Rf 3.5 %, ERP 5.5 %, CoE 10.5 %, g 3 %, tax 30 %, payout 55 %. ✅ Documented in `08-assumptions-and-defaults.md`.

**Verdict.** ⚠️ **PARTIAL.** Models themselves are textbook. Three gaps vs. rubric:

| Gap | Where |
|---|---|
| No per-symbol Bear / Base / Bull assumption blocks — only **global** scenario overrides at `valuation.py:35-39` (`SCENARIO_DEFAULT_OVERRIDES`) | scenarios |
| No 5×5 sensitivity tables (WACC × g, WACC × exit multiple) surfaced in API or workbook output. Ensemble bands `fair_value_low/base/high` are quartiles of model fair values, not a sensitivity grid | sensitivity |
| FCFE proxy path does not surface a side-by-side "proper FCFE vs. FCF fallback" comparison; the consumer can't see which path was used without reading `warnings` | transparency |

**Notes for the app side.** Sensitivity grids are the cheapest gap to close (a 2-D loop over `assumptions.wacc` and `assumptions.terminal_growth`, output as a `dict[(wacc, g)] -> fair_value`). The scenario gap is more design-heavy — it needs per-symbol UI overrides plus persistence.

---

## 2. Comparables / justified multiples / relative tiles

**Rubric** (`financial-analysis:comps-analysis`, `market-researcher:comps-analysis`):
- Operating block (revenue, GM, EBITDA margin, FCF margin, growth) + valuation block (EV/Rev, EV/EBITDA, P/E, P/B).
- Statistical row per metric: Max / 75th / Median / 25th / Min.
- Peer cohort selection rules + fallback when cohort < N.
- Statistical benchmarking (z-score / quartile of subject vs. cohort).
- Cell-level provenance (source citation per number).

**App**:
- **Relative multiples** at `valuation.py:638-667` — implied price = `current × peer_median / own_multiple` for PER, P/B, P/S, EV/EBITDA. ✅
- **Justified multiples** at `valuation.py:583-630` — justified P/B = `(ROE − g) / (CoE − g)`, justified P/E = `payout × (1+g) / (CoE − g)` with linear growth fade. ✅
- **Peer cohort + fallback** at `valuation.py:229` (`_peer_stats`) — sector first; falls back to market when `peer_min_count < 3`, with `scope` tag for audit. ✅
- **Statistical benchmarking** at `scoring.py:70` (`_percentile_scores`) — per-metric percentile + z-score + pct deviation, sector-bucketed. ✅

**Verdict.** ✅ **ALIGNED on methodology**, ⚠️ on packaging.

**Gaps:**
- The full comps table (10 metrics × N peers + Max/75th/Median/25th/Min row) is **not surfaced as a unified artifact**. Statistics live inside `snapshot.metrics` and the percentile dict, not as a "comps view" the user can read or export.
- No cell-level citation map — provenance is implicit (yfinance → workbook → snapshot) but not attached to each rendered number on the comparables tab.

---

## 3. 3-statement integrity & cash flow

**Rubric** (`financial-analysis:3-statement-model`, `financial-analysis:audit-xls`):
- Historical 3–5y + projected 5y for IS, BS, CFS, fully linked.
- Cross-checks: **A = L + E**, **CFS ending cash = BS cash**, **NI link IS → CFS**.
- Working-capital schedule, D&A roll-forward, debt schedule.
- All formulas, no hard-codes.
- Scenario toggle drives the linked output.

**App**:
- **Historical ingest** at `core/quant_core/fundamentals/normalize_yfinance.py` + `workbook.py` — IS / BS / CFS rows stored as `AnnualMetricRow` (statement_year × metric_name × metric_value). ✅
- **Projections** — implicit only. `_dcf_cash_flows` projects FCF arrays for valuation, but **no projected IS / projected BS / projected CFS** is built or stored.
- **Cross-checks** — ❌ none. No BS-balance assertion, no cash tie-out, no NI link verification anywhere in `fundamentals/` or the worker tasks.

**Verdict.** ❌ **MISSING.** The app is a *consumer* of historical financials but not a 3-statement *modeller*. The valuation models hold together because they integrate cash-flow arrays internally, but a user cannot answer: "show me the projected balance sheet in year 3" or "does your model's BS balance?" This is the single biggest gap vs. the rubric, and it would be the first blocker any institutional sign-off raises.

---

## 4. Pillar scoring, ensemble & confidence

**Rubric** (`equity-research:thesis-tracker`, `financial-analysis:audit-xls`):
- 6 pillars, 0–100 percentile, weighted composite.
- Quality cross-checked with diagnostics (Piotroski 9-point, DuPont 3- or 5-step, accruals).
- Ensemble with explicit model-coverage and confidence tracking.
- Thesis scorecard with **pillar trends** (On Track / Behind / Watch).

**App**:
- **Pillar weights** at `scoring.py:42-50` — Value 0.20, Quality 0.22, Growth 0.16, Risk 0.14, Cash Flow 0.14, Health 0.14. ✅
- **Quality adjustment** at `scoring.py:351-359` — `adjusted_quality = mean(raw_percentile, accounting_discipline, accrual_quality)` where `accounting_discipline = mean(Piotroski, DuPont)`. ✅
- **Piotroski-lite** at `scoring.py:270-299` — full 9-point list (ROA>0, FCF>0, ΔROA>0, FCF>NI, Δleverage<0, Δliquidity>0, Δmargin>0, Δasset-turn>0, Δrev>0). ✅
- **Ensemble & confidence** in `docs/fundamentals-layer/07-ensemble-and-confidence.md:40-98` + valuation.py — base weight × confidence × proxy cap, `CONFIDENCE_TO_SCORE = {high 0.85, medium 0.60, low 0.35, unavailable 0.0}`. ✅
- **Thesis trend tracking** — ❌ not implemented. No history table comparing pillar scores quarter over quarter; no On Track / Behind / Watch flag.

**Verdict.** ✅ aligned on the static scoring; ⚠️ partial because there is no temporal layer. The infrastructure is here to add trend tracking cheaply (snapshot pillar scores by `as_of_date`, diff against previous).

---

## 5. Universe / screen / idea sourcing

**Rubric** (`equity-research:idea-generation`, `market-researcher:idea-generation`):
- Quant screens (value, growth, quality, short, special situation).
- Thematic sweep (theme → value chain → pure-play vs. second-order).
- Output a ranked 5–10 idea list with thesis + metrics + risks.

**App** (`core/quant_core/fundamentals/screens.py`):
- `magic_formula` (Greenblatt ROC + EY), `peg_garp`, `altman_z` (with financial / non-financial variant), `eva`, `regression_adjusted_multiples`. ✅ Quant side is strong.
- **Thematic sweep** — ❌ no workflow to map a theme to beneficiaries, no pure-play tagging, no second-order analysis.
- **Idea report** — ⚠️ screens return scored lists but there is no "top N with one-line thesis + risks" packaging.

**Verdict.** ⚠️ **PARTIAL.** Strong on quant, missing the thematic / synthesis half. The institutional-screens spec in `docs/fundamentals-layer/16-institutional-screens.md` plans this but the implementation is quant-only.

---

## 6. Thesis / scenarios

**Rubric** (`equity-research:thesis-tracker`, `equity-research:initiating-coverage`):
- Persisted thesis statement, supporting pillars, refutation risks.
- Catalysts with dates and expected impact.
- Bull / Base / Bear with probability + key drivers + price target per scenario.
- Stop-loss trigger and target.

**App**:
- ❌ **Nothing persisted at the thesis level.** No DB field for thesis text, risk register, conviction, stop-loss, or target.
- Scenarios exist only as **global assumption overrides** (`SCENARIO_DEFAULT_OVERRIDES` at `valuation.py:35-39`), not per-symbol custom revenue/margin paths.
- Risks are **implicit** in `warnings` and `quality_issue_count`, not a ranked register.

**Verdict.** ❌ **MISSING.** This is the second-biggest gap and the easiest to close on the data side (small schema change), though it does drag in real UX work.

---

## 7. Catalysts

**Rubric** (`equity-research:catalyst-calendar`): earnings dates, product launches, regulatory milestones, M&A; coverage-wide calendar with impact tiering and positioning notes.

**App.** ❌ **Not implemented anywhere.** No event table, no earnings-date ingest, no catalyst surface in the API or UI.

**Verdict.** ❌ **MISSING.** Needed for any "what's coming up this week / month" workflow. Low complexity to add a `fundamental_catalyst` table; the heavier lift is sourcing dates.

---

## 8. Estimates / model-update / per-name updates

**Rubric** (`equity-research:model-update`, `equity-research:earnings-analysis`, `equity-research:earnings-preview`): reconcile actuals to prior estimates, track revisions, re-value with new numbers, flag material changes.

**App**:
- Actuals ingest at `services/worker/tasks/fundamentals.py`, `targeted_bvc_fundamentals.py`, `refresh_yfinance_fundamentals.py` — refresh historical financials, recompute all models. ✅
- **Forward consensus** — ❌ not ingested. App has no concept of a forecast.
- **Estimate revision history** — ❌ not tracked.
- **Material-change synthesis** — ⚠️ only via `quality_issue_count` / severity; no rating-change logic.

**Verdict.** ⚠️ **PARTIAL.** Refresh works; the equity-research notion of "estimate management" is absent because the app does not consume forecasts.

---

## 9. Sector / market overview

**Rubric** (`equity-research:sector-overview`, `market-researcher:sector-overview`): TAM/CAGR, industry structure, competitive landscape, sector trading multiples, recent M&A.

**App**:
- ❌ No TAM, no industry structure narrative, no M&A log.
- ⚠️ Sector multiples are computed implicitly (`_peer_stats` returns peer median by sector) but not packaged as a sector page.

**Verdict.** ⚠️ **PARTIAL** at best — peer-level data is there, but there is no sector synthesis or market context view. The methodology docs envision this; the implementation does not.

---

## 10. Tear sheet / morning-note / IC memo

**Rubric** (`equity-research:morning-note`, `equity-research:initiating-coverage`, `valuation-reviewer:ic-memo`): a 1-page exec summary with rating, target, key metrics, thesis, risks, catalysts, football field, overnight developments.

**App**:
- API at `services/api/app/schemas/fundamentals.py` exposes a rich `EnsembleOut` / `FundamentalUniverseRow` (scores, fair value low/base/high, upside, confidence, model weights, warnings). ✅ Data is there.
- UI at `frontend/components/strategy/signal-fundamental-view.tsx` renders the 5 tabs (Thèse / Valorisation / Qualité & ROE / Estimations / Comparables) — but this is an **interactive screen, not a printable tear sheet**. ⚠️
- ❌ No PDF / DOCX / morning-note export.
- ❌ No football-field chart asset.

**Verdict.** ⚠️ **PARTIAL.** Everything needed is in the API; the export / formatting layer is missing.

---

## 11. Competitive landscape / peer deep-dives

**Rubric** (`financial-analysis:competitive-analysis`, `market-researcher:competitive-analysis`): positioning matrix, peer deep-dives, moat assessment, strategic context (M&A, partnerships, regulation).

**App**:
- Peer grouping is sector-based via `stock_master.sector`. ✅ basic
- ❌ No positioning matrix (2×2 or radar), no moat scoring, no per-peer narrative, no M&A log.

**Verdict.** ❌ **MISSING** beyond the basic peer-cohort plumbing.

---

## Top 10 gaps — ranked by impact × ease

| # | Gap | Impact | Effort | Priority |
|---|---|---|---|---|
| 1 | Projected 3-statement (IS/BS/CFS) + integrity checks (BS balance, cash tie-out, NI link) | **High** — institutional blocker | Medium-high | **P1** |
| 2 | Persist thesis (statement, risks, catalysts, target, stop, conviction) per symbol | High | Low (schema) + medium (UX) | **P1** |
| 3 | Catalyst calendar table + universe-wide calendar view | High | Low schema + sourcing lift | **P1** |
| 4 | Per-symbol Bull / Base / Bear scenarios (custom growth & margin paths, prob-weighted) | Medium-high | Medium | **P2** |
| 5 | Sensitivity tables (5×5 WACC × g, WACC × exit multiple) in valuation output | Medium | Low | **P2 quick win** |
| 6 | Comps view packaged as a single artifact (Max/75th/Median/25th/Min row + cell provenance) | Medium | Low-medium | **P2 quick win** |
| 7 | Tear-sheet / morning-note / IC-memo export (PDF or DOCX) with football field | Medium | Medium | **P2** |
| 8 | Pillar-score history + trend tracking (On Track / Behind / Watch) | Medium | Low | **P2** |
| 9 | Forward consensus ingest + estimate-revision history | Medium | High (sourcing) | **P3** |
| 10 | Sector overview page (TAM / structure / sector multiples / M&A comps) and competitive matrix / moat scoring | Low–medium | High | **P3** |

---

## Strengths to preserve

1. **Seven-model ensemble with confidence cascade** — `valuation.py` + `07-ensemble-and-confidence.md`. The proxy caps + warning haircut + re-normalised weighting is more rigorous than what the plugin's DCF-only skill ships.
2. **Sector-bucketed peer logic with explicit fallback scope** (`_peer_stats` at `valuation.py:229`) — the `scope` tag is a nice audit feature absent from the plugin's templates.
3. **Moroccan-market defaults baked in** (`valuation.py:16-32`) — practical advantage over the plugin's US-centric assumptions.
4. **Piotroski-lite + DuPont + accrual quality fused into the Quality pillar** (`scoring.py:270-359`) — more transparent than a single quality score.
5. **Confidence taxonomy** (`CONFIDENCE_TO_SCORE` + warnings + proxy demotion) gives a defensible answer to "how much should I trust this output?" — the plugin skills assume clean inputs.
6. **FCF-DCF gate for financial-sector names** + RI / DDM emphasis — this is a real methodology improvement; the rubric's DCF skill is one-size-fits-all.

---

## Verdict — author opinion

The fundamental layer in this app is **methodologically strong and architecturally clean**. On the *valuation engine and scoring* axes — what the rubric calls the "model" — you are at or above plugin-skill parity (the ensemble + confidence cascade is genuinely better than what the standalone `dcf-model` and `comps-analysis` skills produce).

Where you are below the rubric is the **workflow scaffolding around the model**: there is no projected 3-statement, no persisted thesis, no catalyst calendar, no scenario per symbol, no exported tear sheet, no estimate-revision history. The plugin skills are heavily oriented around those workflow artifacts because that is what an equity-research desk actually consumes day to day. Right now the app outputs a *score and a fair value*; the rubric expects a *recommendation packaged as a research product*.

If this app is going to remain an internal screening / scoring tool, this gap is fine — you have built a better engine than the plugin ships, just without the wrapper. If the intent is to put it in front of an investment committee or external client, the three P1 gaps (3-statement integrity, thesis persistence, catalyst calendar) are non-negotiable, and the two P2 quick wins (sensitivity tables, comps view as an artifact) are nearly free and worth doing first.

**Did the plugin contribute? No.** **Should it have? Partially.** Specifically — the engine work was correct to keep in-house; the workflow/reporting wrapper (tear sheets, IC memo, catalyst calendar, idea-list format) is exactly what the plugin skills are good at, and re-using them via `equity-research:initiating-coverage`, `equity-research:morning-note`, `equity-research:catalyst-calendar`, and `valuation-reviewer:ic-memo` would close most of the gap above without rewriting any of the model code.
