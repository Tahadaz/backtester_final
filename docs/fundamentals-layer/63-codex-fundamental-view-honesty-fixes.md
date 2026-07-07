# 63 — Codex brief: SFC pipeline live-path fix + fundamental view honesty fixes

Findings from a live review (2026-07-05) of the fundamental single-name view and the SFC
pipeline against the running local stack. Ordered by priority; Package 0 is why the user
currently sees **no SFC factors anywhere** — do it first and verify against the live DB.

Read first: briefs 59/60, doc 61 Reviewer caveats (wording rules bind), and the binding
rules in `21-codex-briefs-INDEX.md`.

---

## Package 0 — P0: the SFC pipeline does not run against the live stack

**Diagnosis (verified live):** the Phase-2 migration `sfc20260705` was not applied to the
running DB (now applied manually — `alembic current` = `sfc20260705`), and the recompute
job crashes before writing anything:

```
core/quant_core/fundamentals/pit_ic_backtest.py:117 in _pit_close
TypeError: Invalid comparison between dtype=datetime64[ns, UTC] and Timestamp
```

Root cause: the live price loader (`services/api/app/market_data_loader.py::
load_close_series_from_store`, consumed by `fundamental_cross_section.py::_price_loader`)
returns a **tz-aware UTC index**; the ic_study CLI's loader returns naive indexes, so the
study never hit this. The synthetic tests use naive indexes too.

- 0.1 Normalize price-series indexes to tz-naive at the SFC boundary (`_price_loader` or a
  shared helper used by both `_pit_close` callers): `idx.tz_convert("UTC").tz_localize(None)`
  when tz-aware. Do NOT change `_pit_close` semantics for naive inputs.
- 0.2 Add a test that feeds a tz-aware close series through `compute_cross_section_frame`
  (or `_pit_close` directly) and asserts no exception and correct PIT selection.
- 0.3 Run the recompute against the live stack and confirm rows exist:
  `select count(*), max(as_of_date) from fundamental_cross_section_score` > 0. Report the
  count and top-5 rows in your final message. Local env: DATABASE_URL
  `postgresql+psycopg2://app:app@127.0.0.1:5555/quant`, S3/minio per infra/docker-compose.yml.
- 0.4 Ops hardening so this class of failure is visible: the scheduler job must emit a
  loud, persisted failure status (reuse the existing batch-status pattern) instead of a
  swallowed `{"status": "failed"}` dict nobody reads; add `alembic upgrade head` to the
  deploy steps in `docs/DEPLOY_RUNBOOK.md` if not already there; add an admin/ops manual
  trigger for the SFC recompute (follow the existing ops-trigger conventions).

## Package 1 — P1: one official target

"Objectif 12 mois" (Synthèse, backend `ensemble.fair_value_base`) and the football-field
header target (frontend `originalTarget ?? selectionSummary.fairValue`) can differ, with
equal visual authority. Fix in `frontend/components/strategy/fundamental/tabs/valuation-tab.tsx`
(+ synthese-tab/research-ticket where they echo targets):
- The backend ensemble target is the ONLY number labeled "Cible officielle" anywhere.
- The frontend-recomputed figure appears only when the user has excluded ≥1 model or
  switched weighting, labeled "Cible de travail (sélection locale)" with a distinct muted
  style, and resets visibly.

## Package 2 — P1: honest scenarios & sensitivity for multiples-led names

Verified mechanism: `valuation.py::compute_sensitivity` perturbs WACC × terminal growth and
reads the **ensemble** per cell; scenarios shift the same assumptions. For names whose
ensemble weight in discount-rate-sensitive models (fcff/fcfe/ddm/ri families) is ~0, every
cell and every scenario is identical — arithmetically correct, visually absurd.

- Backend: compute `rate_sensitive_weight` (sum of effective ensemble weights of the
  DCF/DDM/RI families) and include it in the detail payload.
- Frontend, when `rate_sensitive_weight < 0.10`:
  - Sensitivity card shows an explicit state — "Insensible aux hypothèses d'actualisation :
    ancres ~100 % multiples" — with an optional expander showing the DCF-family diagnostic
    grid (model_grids already exist in the payload) clearly labeled diagnostic.
  - Scenario strip shows the same explanation instead of three identical numbers.
- Do NOT invent multiples-based scenario shifts in this brief (changing what bear/base/bull
  *mean* is a methodology decision → separate proposal, not silent implementation).

## Package 3 — P1: proxy provenance on model cards

`_fcff_dcf`/`_fcfe_dcf` proxy chains (e.g. `maintenance_capex_pct` = 4% of revenue when
capex is missing; growth-driver proxies) are correct and weight-capped, but invisible.
On each model card in the Valorisation tab, render the existing `warnings[]`/proxy flags as
explicit badges: "Capex : proxy 4 % CA (défaut)", "Croissance : proxy secteur", etc.
Mapping table from warning codes to French labels; unknown codes fall back to the raw code
(never hidden). Data check for context (live DB, 2026-07-05): 73 symbols covered, 70 with
real capex lines, 72 with FY2025+ — proxies are the exception, not the rule, and financials
suppress capex/FCF by design (brief 37).

## Package 4 — P1: triangulation anchor-diversity gating (reframe completion)

`triangulation.py` / `triangulation-band.tsx` still present an "agreement" verdict even when
all anchors are one method family. Add `effective_method_mix` (family → weight) and
`anchor_diversity: "single_family" | "multi_family"` to the triangulation payload; the band
prints the mix ("Ancres : 100 % multiples") and, when single_family, replaces the agreement
verdict with "Corroboration limitée — ancres non indépendantes".

## Package 5 — P2: Trajectoire de croissance chart polish

`frontend/components/strategy/fundamental/tabs/estimates-tab.tsx`: the growth-trajectory
charts lack axis titles, units, and readable tooltips. Add: titled axes (year / % or MAD),
value units on ticks, hover tooltips with year + value + source (observed vs projected vs
consensus, visually distinguished — solid vs dashed), a legend, and the app's standard
empty/insufficient-data state. Follow the existing dashboard chart conventions; no new
charting library.

---

## Constraints
- One commit per package, ordered; repo green each commit (pytest core + services,
  frontend build); `graphify update .` at the end.
- Package 0 acceptance requires the live-DB row-count proof, not just green tests.
- No changes to SFC pillar definitions, the frozen config, gates, or `edge.py`.
- Doc-61 wording rules apply to every displayed claim; French labels, correct accents.
- Ambiguities → `## Open questions` here and stop.
