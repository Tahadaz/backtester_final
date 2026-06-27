# Cleanup & Data-Architecture Implementation Plan

_Date: 2026-06-23 · Companion to `docs/REPO_AUDIT.md` · Scope: **keep everything, just organize** · Executor: Sonnet (implementation)_

This is the **implementation plan** derived from the audit. It is incremental and backend-first. **Every phase ends with the full check gate green and is committed separately.** No phase depends on a later one. Do not start a phase until the previous phase's gate passes.

### Decisions locked with the owner
1. `data/corrections/fy2025/` → **delete** (owner authored them; not loaded by runtime app).
2. PFE / LaTeX / presentation tooling → **keep on disk, remove from git, gitignore** (must not reach GitHub).
3. Router splitting → **approved** as the professional choice, provided behavior is preserved and tests stay green.

### The check gate (run after every phase)
```bash
# backend
python -m pytest core/tests -q --tb=short
python -m pytest services/api/tests -q --tb=short
python -m pytest services/worker/tests -q --tb=short
# frontend
cd frontend && npm ci --legacy-peer-deps && npx tsc --noEmit && cd ..
# infra sanity
docker compose -f infra/docker-compose.yml config >/dev/null && echo "compose OK"
# keep the knowledge graph current (AST-only, no API cost)
graphify update .
```
A phase is "done" only when all of the above pass and the change is committed with a clear message.

---

## Phase 0 — Make the repo runnable from a clean clone (BLOCKER)

**Goal:** a stranger can `git clone` + `docker compose up` and the migration gate passes.

### 0.1 Merge the Alembic heads
**The head list drifts** — migrations land between inspection and action, so do NOT trust any hardcoded list (including this one). Always merge exactly what `alembic heads` prints at execution time.

History of this split:
- Audit (2026-06-23) saw **5 heads**: `571b9673d32f, c1d2e3f4a5b6, c788e94f3062, d1e2f3a4b5c6, ff2ed8e51892`. Those have since been resolved by subsequent migrations — **do not merge them.**
- As of execution, the tree shows **2 heads**: `d8e9f0a1b2c3` ("update cost of equity floor for brief 39") and `g8h9i0j1k2l3` ("add signal best evidence snapshot").

Steps:
1. From the API service context (so `alembic.ini` / env is found), run `alembic heads` and record the **current** head revisions. Merge those — not the list above.
2. Generate one merge revision joining the current heads, e.g. (with the 2 heads observed at execution):
   `alembic merge -m "merge heads into single tip" d8e9f0a1b2c3 g8h9i0j1k2l3`
3. Open the generated file; verify `down_revision` is the tuple of all current heads and `revision` is the new single head. Add a short docstring explaining why the merge exists.
4. **Validate against an empty DB** (do NOT test only against the already-migrated dev DB):
   - spin up a throwaway Postgres (compose service or a temp container),
   - run `alembic upgrade head` — must succeed with no "multiple heads" error,
   - run `alembic downgrade -1` then `upgrade head` to confirm reversibility of the merge node.
5. `alembic heads` must now print **exactly one** revision.

**Risk/rollback:** merge migrations are no-op schema-wise (they only join lineage). If anything is off, delete the new file and regenerate. Do not rewrite or delete existing migrations.

### 0.2 Guard against regression
Add a lightweight check so multi-head can't silently return:
- a small test (in `services/api/tests/`) or a CI step that asserts `len(alembic heads) == 1`. Prefer a pytest that shells `alembic heads` or uses the Alembic API on the migrations dir.

### 0.3 Clean-clone smoke test (document the result)
- `docker compose -f infra/docker-compose.yml config` passes.
- `docker compose -f infra/docker-compose.yml up --build` reaches healthy API; migration gate passes.
- Capture the outcome in the PR/commit description.

**Acceptance:** one head; `alembic upgrade head` clean on empty DB; regression guard added; check gate green.

---

## Phase 1 — De-clutter (safe deletions / moves only)

**Goal:** remove dead code and pull non-app artifacts out of the GitHub-visible tree. No app behavior changes.

### 1.1 Delete unreferenced frontend components
Confirmed **zero inbound references**:
- `frontend/components/strategy/legacy-signals-view.tsx`
- `frontend/components/strategy/legacy-technical-analysis-panel.tsx`

Steps: delete both → run `npx tsc --noEmit` and `npm run build` to prove nothing breaks. (The other three `legacy-*` components ARE still referenced — **do not touch them in this phase**; they're renamed in Phase 2.)

### 1.2 Delete the FY2025 corrections data
- `git rm -r data/corrections/fy2025/` (25 JSON files).
- **Caveat to honor:** `services/api/scripts/remediate_fundamentals.py` references this dir via `FY2025_PROOF_DIR` (`load_fy2025_proof_artifacts`, `apply_fy2025_reingestion`). This is a historical one-off already applied to the DB. After deletion the `--fy2025-reingestion` flag becomes inert. Acceptable. Add a one-line comment near `FY2025_PROOF_DIR` noting the proof artifacts were removed post-application, so a future reader isn't confused. Do **not** delete the script.
- Runtime app is unaffected (it loads `core/quant_core/fundamentals/data/fundamental_corrections.json`, a different path).

### 1.3 Move academic / presentation tooling out of git (keep on disk)
Target: a single top-level `academic/` directory, **gitignored**.
1. Create `academic/` on disk.
2. Move tracked academic content there (working tree): `latex/` (95 tracked files) and the three presentation scripts `scripts/generate_presentation.py`, `scripts/generate_presentation_v2.py`, `scripts/generate_pfe_presentation.py`.
3. Untrack without deleting from disk: `git rm -r --cached latex scripts/generate_presentation.py scripts/generate_presentation_v2.py scripts/generate_pfe_presentation.py` (then the physical move), or move first then `git add`/`git rm` to reflect the relocation. Net git result: these paths are **removed from the repo**, files **remain on disk** under `academic/`.
4. Add to `.gitignore`:
   ```
   # Academic deliverables — kept locally, never published
   /academic/
   ```
5. Update `README.md` repository map: drop the `latex/`, `report-pfe-mis3/`, `docs/presentations/` row (or replace with a one-liner that academic deliverables live locally under `academic/` and are intentionally untracked).
6. Verify `git status` shows the academic paths removed from tracking and `academic/` ignored; verify `git ls-files | grep -iE 'latex/|generate_present'` returns nothing.

### 1.4 Relocate root-level manual test specs
- Move `tests/manual_specs/` → `docs/manual_specs/` (or `services/api/tests/manual/`) so a top-level `tests/` dir doesn't imply a fourth suite. Update any references (none expected). Remove the now-empty `tests/` dir.

### 1.5 .gitignore hardening
Confirm these untracked scratch/working dirs are permanently ignored so they can never leak: `out/`, `output/`, `analysis/`, `frontend/out-pages/`, `frontend/.next-pages/`, `_pptx_build/`, `logs/`, plus root data dumps (`*.xlsx`, `*.pdf`, `top40_*`, `*.zip`). Add any missing patterns. Do not un-ignore anything already ignored.

**Acceptance:** dead components gone; FY2025 data removed with script comment added; academic content off git but on disk and ignored; README updated; check gate green.

---

## Phase 2 — Readability: split the monster files

**Goal:** improve reviewability with **zero behavior change**. URL paths, response shapes, auth, and OpenAPI operation IDs must be identical before/after. One file per commit. If a split risks changing behavior, stop and leave the file intact.

**General method (per router):**
- Create a package directory next to the file (e.g. `routers/strategy_signals/`) with an `__init__.py` that exposes the same `router` object.
- Move cohesive endpoint groups into submodules (`_<group>.py`), each defining an `APIRouter` with the **same prefix/tags**, then `include_router` them into the top-level router.
- Keep all shared helpers in one `_shared.py` within the package to avoid circular imports.
- Preserve `operation_id`s and path operations exactly. Diff the OpenAPI schema before/after (`GET /openapi.json`) — it must be unchanged.

### 2.1 Split `services/api/app/routers/strategy_signals.py` (9,118 lines)
Highest-value target. Split by resource group (e.g. signals overview, variant detail, WFO, leaderboard, backtest). Confirm the API import site (`app/main.py` or wherever routers are registered) still imports the same symbol.

### 2.2 Split `services/api/app/services/fundamentals.py` (5,130 lines)
Service module, not a router — split by responsibility (loading, ratios, valuation orchestration, serialization) into a `services/fundamentals/` package with a stable public surface (`__init__.py` re-exports the previously-imported names). Grep all importers first; their import paths must keep working.

### 2.3 Rename misleading names (only after splits are stable)
- `services/api/app/strategy_v2.py` → a descriptive name; update the two importers (`routers/strategy.py`, `routers/strategy_backtest_runs.py`).
- The **four** still-used `legacy-*` frontend components → descriptive names; update importers (incl. `app/signals/page.tsx`). NOTE: `legacy-signals-view.tsx` was originally slated for deletion in Phase 1.1 but proved to be actively imported by `app/signals/page.tsx` (line 7, used line 259), so it was correctly left in place and is renamed here instead. The set to rename: `legacy-indicator-chart.tsx`, `legacy-indicator-explorer.tsx`, `legacy-indicator-sidebar.tsx`, `legacy-signals-view.tsx`.

**Acceptance per sub-step:** OpenAPI schema diff empty (for routers); all importers resolve; check gate green; committed individually.

> If at any point a split would change behavior or balloon in risk, skip it, note why in the commit, and move on. Readability is not worth breaking the app.

---

## Phase 3 — Data-engineering depth (the portfolio differentiator)

**Goal:** make the `dataeng/dbt` + Airflow layer the headline. Additive only.

### 3.1 dbt tests & source freshness
- Add `not_null` + `unique` tests on every dim PK and fact grain key; `relationships` tests from facts → dims, in `_marts__models.yml` / `_staging__models.yml`.
- Add `freshness` blocks to the four sources in `_staging__sources.yml` (warn/error thresholds).
- `dbt build` (or `dbt test`) must pass.

### 3.2 Incremental fact model
- Convert `fct_signal_scores` (~6.6M rows) to an `incremental` materialization with an explicit unique key and `is_incremental()` filter. Document the incremental strategy in the model's YAML description.

### 3.3 dbt docs + lineage
- `dbt docs generate`; commit nothing heavy, but link how to view it from `README.md` / a new `dataeng/README.md`.

### 3.4 Airflow polish
- Ensure `warehouse_refresh` DAG has retries, an SLA, and a docstring; reference it in docs.

### 3.5 End-to-end pipeline doc
- One diagram + short narrative: ingestion → Postgres `public` (source system) → dbt staging → marts → serving/Airflow. Put it at the top of `dataeng/README.md` and link from the main `README.md`. This is the story that sells the repo for a data role.

**Acceptance:** `dbt build` green with tests + freshness; incremental model documented; lineage/docs reachable; pipeline diagram committed; check gate green.

---

## Working agreement for the executor
- **Branch:** create `chore/repo-cleanup` off the current branch tip (do not work on `main`). One commit per numbered sub-step where practical; never bundle phases.
- **Never** delete or rewrite existing Alembic migrations; only add the merge revision.
- **Never** push or open a PR unless explicitly asked.
- After any code change, run `graphify update .` (AST-only).
- If a step's assumption turns out false (e.g. a "dead" file is actually referenced), **stop and report** rather than forcing it.
- Keep `docs/REPO_AUDIT.md` and this plan as the source of truth; check items off as you go.
