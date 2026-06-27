# Repository Audit & Cleanup Plan

_Date: 2026-06-23 · Scope decision: **keep everything, just organize** · Goal: turn this into a clean, defensible GitHub portfolio project that strengthens a data-engineering job search._

This is an **audit only** — no code has been changed. It inventories dead code, redundancy, and architecture/infra defects, then proposes a prioritized, incremental plan.

---

## 1. Executive summary

This is a real, full-stack quant platform (FastAPI + RQ workers + Next.js + Postgres + MinIO + dbt + Airflow). The architecture and documentation are strong. Three things hold it back as a portfolio piece:

1. **One confirmed infra bug** — the Alembic migration tree has **5 heads**, so `alembic upgrade head` fails on a fresh DB. This makes the repo non-runnable by a stranger, which is the worst possible failure for a portfolio.
2. **A few monster files** (one router is 9,118 lines) that hurt readability for anyone reviewing the code.
3. **Minor dead code and redundancy** — a handful of unreferenced components/scripts and committed data dumps.

The good news: the **git-tracked tree is already clean** of the personal clutter (CVs, PDFs, logs, zips) that fills the working directory — those are all untracked. The cleanup is therefore mostly *internal organization*, not mass deletion.

---

## 2. What's healthy (keep as-is)

- **Service separation** is textbook: `core/quant_core` (shared logic) → `services/api` (FastAPI) → `services/worker` (RQ jobs) → `frontend` (Next.js). This is a genuine selling point.
- **Data-engineering layer exists and is correctly structured**: `dataeng/dbt` has a proper `staging → marts` star schema with declared sources and lineage (`dim_date`, `dim_symbol`, `dim_category`, `dim_signal_source`, `fct_signal_scores`, `fct_fundamental_pillars`), plus an Airflow `warehouse_refresh` DAG (trigger → sensor → dbt run/test). **This is the strongest asset for a data role and is underdeveloped relative to its potential.**
- **Documentation** is unusually thorough (`docs/` layered by domain, accurate `README.md`, `DEPLOY_RUNBOOK.md`).
- **The repo root is clean in git**: only `.dockerignore`, `.gitignore`, `README.md`, `requirements-dev.txt` are tracked at root. No duplicate frontend tree, no `graphify-out/`, no `.next/`, no CVs are tracked. `.gitignore` is doing its job.

---

## 3. Confirmed defects (must fix)

### 3.1 Alembic multi-head migration tree — BLOCKER
The migration tree keeps re-splitting into multiple heads, so `alembic upgrade head` is ambiguous and fails on a fresh database — exactly the symptom reported during `compose up`.

**The head list is a moving target — always merge what `alembic heads` reports at fix time, never a hardcoded list:**
- At audit time (2026-06-23): **5 heads** (`571b9673d32f, c1d2e3f4a5b6, c788e94f3062, d1e2f3a4b5c6, ff2ed8e51892`). These were later resolved by subsequent migrations.
- Observed again shortly after: **2 fresh heads** (`d8e9f0a1b2c3`, `g8h9i0j1k2l3`) from two independent lines of development.

The fact that this recurred is itself the argument for the regression guard below.

**Fix:** generate one new merge revision whose `down_revision` is the tuple of all 5 current heads (`alembic merge heads`), verify `alembic upgrade head` runs clean on an empty DB, then add a CI/check step so this can't regress. Low risk, high payoff. Must be validated against the real DB state, not just blindly generated.

### 3.2 Repo is not verified to "run from clean clone"
README documents the run path, but with 3.1 unresolved a fresh `docker compose up` fails at the migration gate. After 3.1, do a full clean-clone smoke test (`docker compose config`, `up`, `alembic upgrade head`, `pytest core/tests`, frontend `tsc --noEmit`) and capture the result.

---

## 4. Dead code & redundancy inventory

> Scope is "keep everything," so this section targets **truly unreferenced** code and **duplicated artifacts**, not subsystem removal.

### 4.1 Frontend legacy components (`frontend/components/strategy/`)
Five `legacy-*.tsx` files exist. Reference analysis:
- `legacy-indicator-chart.tsx`, `legacy-indicator-explorer.tsx`, `legacy-indicator-sidebar.tsx` — still referenced (mutually, and from `app/signals/page.tsx`). **Keep, but rename off "legacy"** or fold into the active components.
- `legacy-signals-view.tsx`, `legacy-technical-analysis-panel.tsx` — **no inbound references found → dead-code candidates.** Confirm with a build, then delete.

### 4.2 Misleadingly-named "v2" code (NOT dead)
- `services/api/app/strategy_v2.py` is **actively used** by `routers/strategy.py` and `routers/strategy_backtest_runs.py`. It is not dead — but the `_v2` name is debt. Consider renaming to something descriptive once stable.

### 4.3 Redundant presentation/report scripts (`scripts/`)
Three overlapping generators: `generate_presentation.py`, `generate_presentation_v2.py`, `generate_pfe_presentation.py`. None are referenced by docs, CI, or infra. These are one-off academic-deck builders. **Action:** consolidate to one, or move all PFE/report tooling under a clearly-labeled `latex/`-adjacent location so they don't look like part of the app.

### 4.4 Committed data dumps (`data/corrections/fy2025/`)
25 per-symbol JSON correction files are tracked. For "keep everything" this is acceptable *if* they are genuine fixtures the code depends on — but they read like operational data. **Action:** confirm whether code loads these at runtime. If yes, keep + document. If they're manual backfill inputs, move to a documented `fixtures/` or external storage and gitignore the operational variants.

### 4.5 Root-level `tests/` (2 files)
`tests/manual_specs/` holds a PowerShell script + JSON spec — manual API smoke specs, separate from the real suites in `core/tests`, `services/api/tests`, `services/worker/tests`. **Action:** relocate under `docs/` or a `manual/` folder so the top-level `tests/` doesn't imply a fourth test suite.

### 4.6 Stale build/scratch dirs in working tree (untracked — verify only)
`out/`, `output/`, `analysis/`, `frontend/out-pages`, `frontend/.next-pages`, `_pptx_build/`, `logs/` are untracked (good). Just confirm `.gitignore` covers all of them permanently so they can never leak into a portfolio clone.

---

## 5. Maintainability: the monster files

Largest tracked Python files (lines):

| File | Lines | Note |
| --- | --- | --- |
| `services/api/app/routers/strategy_signals.py` | 9,118 | One router file. Top refactor target. |
| `services/api/app/services/fundamentals.py` | 5,130 | Fundamentals service god-module. |
| `core/quant_core/fundamentals/valuation.py` | 3,760 | DDM/RI/valuation engine. |
| `services/worker/tasks/execute_run.py` | 3,724 | Run executor. |
| `services/api/app/routers/fundamentals.py` | 3,573 | Fundamentals router. |
| `services/api/app/routers/runs.py` | 3,000 | |
| `services/api/app/routers/analytics.py` | 2,990 | |

The knowledge graph confirms the fundamentals subsystem is the complexity center: the top god-nodes (`AnnualMetricRow` 571 edges, `FundamentalSnapshot` 538, `IntegrityReport` 442) are all fundamentals.

**Action (incremental, low-risk):** split the two worst routers (`strategy_signals.py`, `fundamentals.py`) into sub-routers by resource/endpoint group behind the same URL prefixes. No behavior change, large readability win. Do this *after* infra fixes and only one file at a time, with tests green between each.

---

## 6. Data-architecture improvements (the portfolio differentiator)

The dbt + Airflow layer is the part most aligned with a data job. It is correct but thin. Prioritized enhancements (incremental):

1. **dbt tests & freshness** — add `not_null`/`unique`/`relationships` tests on the dims/facts and `freshness` checks on sources. Cheap, and exactly what data teams screen for.
2. **dbt docs** — `dbt docs generate` lineage graph; link it from the README. Visual proof of the warehouse.
3. **Document the pipeline end-to-end** — one diagram: ingestion → Postgres (`public`) → dbt staging → marts → (serving/Airflow). Even under "keep everything," framing the app as the *source system* feeding the warehouse is the story that sells.
4. **Idempotency / incremental models** — `fct_signal_scores` is ~6.6M rows; make it an incremental model and document the strategy.
5. **Airflow polish** — ensure the DAG is documented, has retries/SLAs, and is mentioned in `README`/`docs`.

These are additive and don't conflict with "keep everything."

---

## 7. Recommended sequencing (incremental, backend-first)

**Phase 0 — Make it runnable (do first, smallest, highest value)**
- 3.1 merge the 5 Alembic heads; verify `alembic upgrade head` on empty DB.
- 3.2 clean-clone smoke test; capture results.
- 4.6 confirm `.gitignore` fully covers scratch dirs.

**Phase 1 — De-clutter (safe deletions/moves only)**
- 4.1 delete the two unreferenced `legacy-*` components (after a green build).
- 4.3 consolidate/relocate presentation scripts.
- 4.4 decide on `data/corrections/fy2025` (keep+document vs. move).
- 4.5 relocate root `tests/manual_specs`.

**Phase 2 — Readability**
- 5 split `strategy_signals.py` then `fundamentals.py` into sub-routers, one at a time, tests green between.
- 4.2 rename `strategy_v2` and the kept `legacy-*` components.

**Phase 3 — Data-engineering depth (the differentiator)**
- 6.1–6.5 dbt tests/freshness/docs, incremental fact model, Airflow polish, end-to-end pipeline diagram.

Each phase ends with `pytest core/tests` + frontend `tsc --noEmit` green. No phase depends on a later one.

---

## 8. Open questions for you

1. **`data/corrections/fy2025`** — are these loaded by code at runtime, or manual backfill inputs? (Decides 4.4.)
2. **PFE/latex/presentation tooling** — keep visible in the portfolio repo, or tuck under a clearly-academic subtree so reviewers don't mistake it for app code?
3. **Refactor appetite** — are you comfortable with me splitting the two 5k–9k-line routers (Phase 2), or do you want to leave large files untouched and focus on Phase 0/1/3 only?
