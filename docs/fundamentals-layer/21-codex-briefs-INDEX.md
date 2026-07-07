# 21 — Codex briefs: master index + dangers of the current app

> **Status.** Draft authoritative work-list for Codex, derived from `REVIEW_vs_plugin_skills.md`. Each numbered brief in this folder is **self-contained**: it tells Codex which files to read, which tables to add, which formulas to use, what NOT to touch, and how the work is verified.
>
> **Plan-only.** These briefs describe work for Codex to implement. Claude has not modified any code. Do not let any future agent skip the "files to read" gates at the top of each brief.
>
> **Rubric source of truth.** Skill folders the briefs reference live under `~/.claude/plugins/cache/claude-for-financial-services/`. Codex is expected to open the `SKILL.md` named in each brief and follow its methodology where this folder does not already constrain the answer.

---

## Read these BEFORE picking up any brief

1. `docs/fundamentals-layer/REVIEW_vs_plugin_skills.md` — the audit that motivated this work.
2. `docs/fundamentals-layer/00-INDEX.md` — current doc topology and public symbol surface.
3. `docs/fundamentals-layer/06-valuation-models.md` and `07-ensemble-and-confidence.md` — methodology these briefs must not contradict.
4. `core/quant_core/fundamentals/domain.py` — current dataclasses; no new dataclass duplicates an existing one.
5. `core/quant_core/fundamentals/valuation.py` lines 13–49 — the canonical `DEFAULT_ASSUMPTIONS` and `SCENARIO_DEFAULT_OVERRIDES` tables. Briefs reuse these names; do not fork them.
6. `services/api/alembic/versions/a0b1c2d3e4f6_add_fundamental_research_tables.py`, `b1c2d3e4f5a6_add_fundamental_data_source.py`, `c2d3e4f5a6b7_add_fundamental_currency_and_bands.py`, `b0c1d2e3f4a8_add_fundamental_bvc_documents.py` — current fundamental schema. Any new migration MUST set `down_revision` to the current head of this chain (Codex reads the latest file to confirm).

---

## Dangers of the current app (what could bite us in production)

These are the silent-failure modes the briefs are designed to close. Codex should read them once and keep them in mind for every change.

| # | Danger | Where it lives today | Mitigated by brief |
|---|---|---|---|
| D1 | **No balance-sheet integrity check.** A row can be ingested where Assets ≠ Liabilities + Equity by a large delta and nothing flags it. The downstream ROE, leverage and Piotroski signals all degrade silently. | `core/quant_core/fundamentals/workbook.py`, `normalize_yfinance.py`, `services/api/app/services/fundamentals.py` (ingest path) | **22** |
| D2 | **No cash tie-out.** Ending cash in CFS is not reconciled against BS cash. If yfinance returns inconsistent cash buckets, the FCF proxy used by FCFE/FCFF DCF can be off by 10–30 % and the user has no warning. | ingest path + `valuation.py` FCFE proxy block | **22** |
| D3 | **No NI link IS → CFS.** Net income at the top of the cash-flow statement is not verified equal to net income at the bottom of the income statement. Sign-flip or rounding bugs propagate into accruals (`scoring.py`). | ingest path | **22** |
| D4 | **Scenarios are global, not per-symbol.** `SCENARIO_DEFAULT_OVERRIDES` shifts WACC and terminal growth identically for *every* symbol. A defensive consumer-staples name and a high-growth small-cap get the same Bear case — meaningless. | `valuation.py:35-39` consumed wherever `scenario` is passed | **25** |
| D5 | **No persisted thesis.** There is no place to store "why we own this". When the score moves, we cannot tell whether the thesis is intact or broken. | DB schema (no `fundamental_thesis` table) | **23** |
| D6 | **No catalyst awareness.** Earnings, dividend, regulatory or ex-date events are not ingested. A score refresh the day before earnings is treated identically to one mid-cycle, and the user has no calendar of what is coming. | DB schema (no event table); ingest workers | **24** |
| D7 | **No sensitivity grid.** A fair-value point estimate plus an ensemble band hides the WACC × terminal-growth surface. A 50 bp WACC mistake can move fair value 20 %, and the consumer never sees that. | `valuation.py` ensemble outputs; API schemas | **26** |
| D8 | **Comps view is implicit.** `_peer_stats` builds the data but no Max/75th/Median/25th/Min table is materialised. Two analysts can disagree about "who the peers are" because the cohort is not surfaced. | `valuation.py:229` peer logic; API schemas | **27** |
| D9 | **No pillar-trend history.** Pillar scores are stateless. Quality moving from 78 → 52 over four quarters does not flag anywhere — every refresh overwrites the prior snapshot. | DB schema; refresh workers | **28** |
| D10 | **No printable artefact.** Everything is API data. There is no IC-memo, no tear sheet, no morning-note export. If the desk has to send something to a client, they screenshot the UI. | API schemas; no export route | **29** |

These are *not* engine bugs — the valuation math is solid. They are wrapper / institutional-workflow gaps. The briefs target them in priority order.

---

## Briefs in this folder

| Brief | Title | Priority | Plugin rubric anchor |
|---|---|---|---|
| 22 | [3-statement integrity & projected statements](22-codex-3statement-integrity.md) | **P1** | `financial-analysis:3-statement-model`, `financial-analysis:audit-xls` |
| 23 | [Thesis persistence per symbol](23-codex-thesis-persistence.md) | **P1** | `equity-research:thesis-tracker`, `equity-research:initiating-coverage` |
| 24 | [Catalyst calendar](24-codex-catalyst-calendar.md) | **P1** | `equity-research:catalyst-calendar` |
| 25 | [Per-symbol Bull / Base / Bear scenarios](25-codex-scenarios-per-symbol.md) | **P1 — executable** | `financial-analysis:dcf-model` (scenario block) |
| 26 | [Sensitivity tables (quick win)](26-codex-sensitivity-tables.md) | P2 quick | `financial-analysis:dcf-model` |
| 27 | [Comps view as a materialised artefact (quick win)](27-codex-comps-artifact.md) | P2 quick | `financial-analysis:comps-analysis`, `market-researcher:comps-analysis` |
| 28 | [Pillar-score history & trend](28-codex-pillar-history.md) | P2 | `equity-research:thesis-tracker` |
| 29 | [Tear-sheet / IC-memo / morning-note export](29-codex-tearsheet-export.md) | P2 | `equity-research:morning-note`, `equity-research:initiating-coverage`, `valuation-reviewer:ic-memo` |
| 30 | [DDM and Residual Income — post-V3 corrections](30-codex-ddm-ri-corrections.md) | **P1 — engine fix** | `equity-research:model-update`, `financial-analysis:dcf-model` |
| 31 | [Valuation over-statement remediation (desk-grade fair values)](31-codex-valuation-overvaluation-remediation.md) | **P0 — engine fix** | `financial-analysis:dcf-model`, `financial-analysis:comps-analysis` |
| 32 | [Scenario governance (base-anchored rating, no market-anchoring, documented probabilities)](32-codex-scenario-governance.md) | **P1 — governance fix** | `financial-analysis:dcf-model` (Bear/Base/Bull case selector) |
| 33 | [Screenshot-driven product deck + scenario fix (runbook)](33-codex-product-deck-and-scenario-fix.md) | **P1 — demo + governance** | `financial-analysis:pptx-author`, brief 32 |
| 34 | [Fundamental valuation sanity remediation (no fabricated numbers, defensible methodology)](34-codex-fundamental-sanity-remediation.md) | **P0 — engine correctness** | `financial-analysis:dcf-model`, `financial-analysis:comps-analysis`, `equity-research:model-update` |
| 35 | [Scenario coherence (co-compute bear/base/bull atomically; enforce ordering)](35-codex-scenario-coherence.md) | **P0 — display correctness** | `financial-analysis:dcf-model` (Bear/Base/Bull as one run), brief 32 |
| 36 | [Canonical snapshot per symbol + import hygiene](36-codex-canonical-snapshot.md) | **P1 — data integrity** | `equity-research:model-update`, `financial-analysis:audit-xls` |
| 37 | [Genuine bank / insurer valuation (equity-side, bank accounting)](37-codex-bank-insurer-model.md) | **P1 — methodology** | `financial-analysis:comps-analysis`, `financial-analysis:dcf-model` |
| 38 | [Data integrity remediation (tie-out gate + source re-verification)](38-codex-data-integrity-remediation.md) | **P0 — PREREQUISITE to 34–37** | `financial-analysis:audit-xls`, `equity-research:model-update` |
| 39 | [Risk-differentiated cost of capital + consistent ROE basis](39-codex-risk-differentiated-cost-of-capital.md) | **P0 — dominant under-valuation cause** | `financial-analysis:dcf-model`, `equity-research:model-update` |
| 40 | [Method-class combiner: stop comps being rejected by the intrinsic cluster](40-codex-ensemble-method-class-combiner.md) | **P1 — residual gap + intrinsic tail** | `financial-analysis:comps-analysis`, `financial-analysis:dcf-model` |
| 41 | [Expand verification coverage: minority-aware T4 + finish doc-fetch](41-codex-expand-verification-coverage.md) | **P1 — coverage (12→~49+ verified)** | `financial-analysis:audit-xls`, `equity-research:model-update` |
| 42 | [Complete FY2025 re-ingestion for the priority cohort (mandatory proof-of-read)](42-codex-fy2025-priority-reingestion.md) | **P0 — the actual data fix; everything else is blocked on it** | `equity-research:model-update`, `financial-analysis:audit-xls` |
| 43 | [Sector-aware valuation correctness: cyclical mid-cycle into intrinsic models + insurer model](43-codex-sector-aware-valuation-correctness.md) | **Superseded by 44** (its §3.1/§3.2 premise — "midcycle only feeds multiples" — is no longer true in the live tree) | `financial-analysis:dcf-model`, `equity-research:initiate` |
| 44 | [Systematic downward-bias remediation (reclassify cyclicals, fix normalization direction, terminal-value handling, reliability-weighted combiner, insurer path)](44-sonnet-valuation-bias-remediation.md) | **P0 — engine-side; the dominant correctness problem (−38.5pp one-directional bias, 37% directional vs BKGR)** | `financial-analysis:dcf-model`, `financial-analysis:comps-analysis`, `equity-research:initiate` |
| 45 | _(planned, parallel)_ FY2025 proof-of-read re-ingestion for the 24 zero-model NR names (BCI/MNG/ADI/JET/LBV/MSA/VCN/CMG…) — data-acquisition, brief-42 style | **P0 — data coverage; low-conflict with 44** | `equity-research:model-update`, `financial-analysis:audit-xls` |
| 50 | [Couple data-tie-out verification into recompute (fix silent-rating / absurd-cible hole — 52 canonical names rated without a verification row on their canonical import; MNG cible 4129 vs price 14800)](50-sonnet-verification-canonical-coupling.md) | **P0 — integrity plumbing; LAND BEFORE 44 so its scorecard runs on gated names** | `financial-analysis:audit-xls`, `financial-analysis:debug-model` |
| 52 | [Archetype-aware coverage gates + bank/insurer statement UI (kill false "missing" flags on banks/insurers; gap-fill the FY2025 coverage tail; dedicated PNB/NII + premiums/combined-ratio views)](52-sonnet-archetype-aware-coverage-and-ui.md) | **P1 — UX correctness; the "lots of missing data" report. Phase 2 is the high-leverage backend fix** | `equity-research:initiate`, `financial-analysis:comps-analysis` |
| 59 | [Cross-sectional fundamental composite — methodology & rationale (SFC)](59-cross-sectional-composite-methodology.md) | **P0 — strategy reframe; read before 60.** Absolute-valuation upside is demoted from signal to anchor; the trading signal becomes a cited, PIT-disciplined cross-sectional rank (value + quality + fundamental momentum + price momentum). | `equity-research:idea-generation`, `equity-research:screen` |
| 60 | [Codex brief: implement the SFC (research CLI → persistence → UI → blotter)](60-codex-cross-sectional-composite-implementation.md) | **P0 — gated implementation; Phase 1 IC study decides whether Phases 3–4 run.** N.B. "pillar" in briefs 59–60 means an SFC component (VAL/QUAL/FMOM/PMOM), not the six scoring buckets of `scoring.py`. | `equity-research:idea-generation`, `financial-analysis:audit-xls` |
| 62 | [Codex brief: SFC Portefeuille — fundamental strategy backtest tab](62-codex-sfc-portfolio-backtest.md) | **P1 — rebalance-replay backtest of the frozen SFC strategy** (engine → snapshot/API → UI with selection/proof/live segments). Depends on 59–61; doc-61 wording rules bind the UI. | `equity-research:idea-generation`, `financial-analysis:comps-analysis` |
| 63 | [Codex brief: SFC live-path fix + fundamental view honesty fixes](63-codex-fundamental-view-honesty-fixes.md) | **P0 Package 0 — SFC pipeline crashes on live tz-aware prices (pit_ic_backtest.py:117) and its migration was unapplied; this is why no factors display.** Then: one official target, honest flat-sensitivity/scenario states, proxy provenance badges, triangulation anchor-diversity gating, growth-chart polish. **Run 63 BEFORE 62.** *(Implemented 2026-07-05, verified live.)* | `financial-analysis:debug-model`, `financial-analysis:audit-xls` |
| 64 | [Codex brief: fundamental UX transparency & navigation polish](64-codex-fundamental-ux-transparency.md) | **P1 — French rec labels (raw "accumulate" enum leaking), N/R stale-verdict triage (24 shown vs 6 real on latest rows), Altman/Piotroski calculation breakdown + deep-links, fullscreen & chart lightbox.** | `equity-research:initiate`, `financial-analysis:audit-xls` |

Execute in numerical order, **except brief 38 runs FIRST** — it is the data foundation. Each brief is a separate Codex run; do not bundle.

> **Brief 38 is the binding constraint.** An audit of all 73 names (2026-06-05) found ≥21 with hard data inconsistencies (equity off by 47×–2,300×, group-vs-consolidated ROE confusion, ratio components from different fiscal years, a snapshot copy that disagrees with the annual history) — and the true rate is higher because the check only catches internal contradictions. This is why the engine produced BCP −46% (with high value+quality scores), STROC +6,000%, and LHM ROE 1,386%: **garbage in, garbage out.** 38 builds a tie-out gate (recompute every ratio from raw lines; A=L+E, equity=BVPS×shares, NI=Résultat_net, group-basis ROE, single fiscal year) and a correction pipeline in which **Codex itself opens the official source documents (URLs already in `fundamental_source_document.source_url`) and extracts the figures by hand** — with page/line provenance — rather than trusting the auto-extractor that produced the errors; stockanalysis.com is the independent second source. Anything that still does not tie out is marked NR, never fabricated. **Do not trust briefs 34–37 output until 38 has run.**

> **Briefs 34–37 close the issues found after the brief-31 over-correction.** 34 (math: floors/bounds/weights/normalization), 35 (scenarios computed atomically as one run — fixes the `base < bear == bull` display), 36 (one canonical import per symbol + purge of 127-import clutter and failed-import orphans), 37 (banks/insurers valued equity-side on bank accounting — PNB/RBE/cost-of-risk, P/B-ROE/P/E/DDM/RI — with the fabricated EBITDA/EV/Capex/FCF suppressed for financials). 35 and 37 touch the engine/persistence and are sanctioned exceptions to rule #5, scoped as their headers state.

> **Briefs 30, 31 and 34 are sanctioned exceptions** to rule #5 below ("never modify the seven-model valuation engine"). Brief 30 scopes the override to `_ddm`, `_residual_income`, and their helpers. Brief 31 scopes it to `_relative_multiples`, `_justified_multiples`, `compute_valuation_ensemble`, and the ensemble-level confidence overlay. Brief 34 scopes it to the model floors (`_fcff_dcf`/`_fcfe_dcf`/`_ddm`/`_residual_income`), `compute_valuation_ensemble` (combiner), the `projection.py` driver-default block, and the confidence/rating layer in `services/api/app/services/fundamentals.py`. **Brief 34 is P0 and supersedes the residual symptoms of brief 31**: 31 over-corrected the +200–500 % over-valuation into systematic *under*-valuation (live universe now reads −42.6 % mean upside vs BKGR +24.9 %, 0 BUYs, a fabricated −100 % floor on 9 names and a +4,949 % tail). Pick up 34 before remaining P1/P2 work.

---

## Rules that bind every brief (anti-hallucination contract)

Codex MUST:
1. Open every file named in the brief's "Files Codex MUST read first" gate and confirm the actual line numbers and symbols. If a brief cites `valuation.py:742` and the file has shifted, **report the new line and proceed** — never assume.
2. Reuse existing dataclasses (`FundamentalSnapshot`, `EnsembleResult`, `ValuationResult`, `AnnualMetricRow`) and existing constants (`DEFAULT_ASSUMPTIONS`, `MODEL_VERSION`, `VALUATION_MODEL_ORDER`) — never fork.
3. Place new Alembic migrations with `down_revision` set to the head of the current chain (`b0c1d2e3f4a8_add_fundamental_bvc_documents.py` at the time of writing — Codex re-verifies).
4. Never call yfinance, BVC, or any external source from a request handler — only from worker tasks under `services/worker/tasks/`.
5. Never modify the seven-model valuation engine itself (`valuation.py` functions `compute_symbol_valuations`, `compute_valuation_ensemble`, `_relative_multiples`, `_fcff_dcf`, `_fcfe_dcf`, `_ddm`, `_residual_income`, `_justified_multiples`, `_reverse_dcf`) **except** through documented extension points (e.g. add an optional `sensitivity` kwarg to `compute_valuation_ensemble`; do not rewrite the body).
6. Never weaken `confidence` propagation. If a new code path produces a value, it must also produce a `confidence` and at least one `warnings[]` entry per existing convention.
7. Add tests under `core/tests/test_fundamental_*` and `services/api/tests/test_fundamentals_*` matching the test names listed in each brief's "Acceptance criteria" section.
8. Run `python -m pytest core/tests/ -q` and the API tests from the worktree root before declaring done. Briefs list which tests they introduce.
9. If a brief is ambiguous, write a question into the brief file under a `## Open questions` heading and stop — do not improvise.

Codex MUST NOT:
- Add new MCP integrations (factset / morningstar / pitchbook / etc.) under cover of these briefs.
- Change the public response shape of any existing endpoint without an explicit instruction in the brief.
- Touch the technical signal engine, backtest engine, WFO, or optimisation code.
- Introduce a new currency or FX layer.
- Rewrite UI tokens or design system files (`docs/fundamentals-layer/17`, `18`, `20` are read-only for these briefs).

---

## Glossary used across briefs

- **Snapshot** = `FundamentalSnapshot` instance (domain.py:62) for one symbol at one `latest_statement_year`.
- **Pillar** = one of the six scoring buckets (value, quality, growth, risk, cash_flow, health). Weights at `scoring.py:42-50`.
- **Ensemble** = `EnsembleResult` (domain.py:107) — confidence-weighted blend of `ValuationResult`s.
- **Scenario** = one of `bear` / `base` / `bull`. Today they shift `DEFAULT_ASSUMPTIONS` globally; brief 25 makes them per symbol.
- **Confidence** = ordinal `{high, medium, low, unavailable}` mapped to `{0.85, 0.60, 0.35, 0.0}` (see `07-ensemble-and-confidence.md`).
- **Proxy** = a `ValuationResult` whose computation substituted a missing input. Capped at `proxy_weight_cap = 0.25` of total weight.
