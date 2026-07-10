# Deployment hardening + weekly signal pipeline as an Airflow DAG

Status: PLAN (not yet implemented). Scope chosen 2026-06-25.

Companion to the signal-evidence 404 fix (already implemented — see
"Related code fix" at the bottom). This doc covers everything **outside** that
code change: making the deploy pipeline safe/versioned and turning the weekly
batch chain into a real orchestrated DAG.

---

## 0. Current state (what exists today)

**Runtime topology**
- Production = a single Oracle VM (`84.8.218.252`) running a Docker Compose
  stack at `/opt/bt`, fronted by Caddy.
- Services (from `infra/docker-compose.yml`): `quant_postgres`, `quant_redis`,
  `quant_minio`, `quant_api`, `quant_worker`, `quant_scheduler`,
  `quant_frontend`, plus `airflow_scheduler` / `airflow_webserver`.

**Deploy flow** (`.github/workflows/deploy-vm.yml`)
- Trigger: `build-images` workflow succeeds on `main` → SSH into the VM.
- Steps: `git reset --hard origin/main` → `docker compose -f
  infra/docker-compose.prod.yml pull` → `alembic upgrade head` → `up -d` →
  rebuild **dashboard** snapshots → smoke test.

**Weekly batch chain** (`services/api/app/services/scheduler_registry.py`)
- Five independent APScheduler cron specs, staggered by hours:
  `weekly_fundamental_refresh` (Sat) → `weekly_wfo_dispatch` (Sun 21:00) →
  `weekly_signal_engine_dispatch` (Sun 22:00) →
  `weekly_signal_backtest_dispatch` (Sun 23:00) →
  `weekly_signal_best_evidence_snapshot` (Mon 01:30).
- Each fires `dispatch_schedule(schedule_id)` → enqueues RQ jobs onto queues.

**Airflow** (`infra/airflow/`)
- Already wired, but runs only `warehouse_refresh.py` (the dbt warehouse DAG).
- That DAG is the gold-standard pattern we copy below: HTTP-trigger + sensor-poll,
  retries, `max_active_runs=1`, no app library imports.

---

## 1. The problems (evidence-backed)

| # | Problem | Evidence | Risk |
|---|---------|----------|------|
| P1 | **Prod compose is not in version control.** `deploy-vm.yml` + `docs/APP_MAP.md` + `docs/DEPLOY_RUNBOOK.md` all reference `infra/docker-compose.prod.yml`, which has **never existed in git** and is not gitignored. It lives only as an untracked file on the one VM. | `git log --all -- infra/docker-compose.prod.yml` is empty; `git check-ignore` says not ignored. | Prod topology is unreviewed and unrecoverable if the VM is lost. SPOF. |
| P2 | **CI does not run the API/worker test suites.** `ci.yml` runs only `core/tests/`. The `services/api/tests` + `services/worker/tests` suites — including the 3 best-evidence tests that were red — never run in CI. | `ci.yml` lines 22-23. | Half-built features with failing tests reach prod (exactly what happened here). |
| P4 | **Weekly chain has no dependency enforcement.** Five cron entries spaced by guessed hour-offsets. If WFO dispatch runs long, signal-engine dispatch starts anyway on stale inputs. No retries, no failure alerting, no completion signal. | `scheduler_registry.py` cron specs; `scheduler_dispatch.py`. | Silent partial pipelines; downstream artifacts built on incomplete upstream data. |
| P5 | **Deploy doesn't rebuild best-evidence snapshots.** It rebuilds `dashboard_snapshot` to avoid 503s after payload-shape changes, but the equivalent for `signal_best_evidence_snapshot` was never added. | `deploy-vm.yml` lines 46-61. | After a deploy, the signal-evidence tab serves 404/409 until the next Monday refresh. |
| P6 | **No off-VM backup.** DB + prod compose + `/etc/bt/env` live only on the VM. | — | Total loss on VM failure. |

---

## 2. Why NOT Kubernetes

This is a single-region app: ~7 services, one Postgres, one Redis, one MinIO, a
weekly batch. k8s would add a control plane, ingress controllers, secret
management, RBAC, and a permanent ops burden for **zero** benefit at this scale —
no multi-node scaling need, no per-service autoscaling need, no multi-tenant
isolation need. Docker Compose on a VM is the correct tool. The actual problems
(P1, P2, P4, P5, and P6) are about **versioning, testing, orchestration, and backups** — none of
which k8s fixes and all of which it complicates. Revisit k8s only if you reach
multi-node horizontal scaling or strict multi-tenant isolation requirements.

---

## Part A — Quick safety fixes

Ordered by ROI. Each is independent and shippable on its own.

### A1. Version the production compose file (fixes P1)
1. On the VM: `cp /opt/bt/infra/docker-compose.prod.yml /tmp/prod.yml`, copy it
   back into the repo at `infra/docker-compose.prod.yml`.
2. Diff it against `infra/docker-compose.yml` to confirm only prod-appropriate
   deltas (GHCR image refs with `${IMAGE_TAG}`, no build contexts, prod env via
   `/etc/bt/env`, restart policies, Caddy).
3. Commit. From now on the VM's copy is replaced by `git reset --hard` on each
   deploy (so the repo becomes the single source of truth — verify the committed
   file is byte-correct before the first deploy after this change).
4. Keep secrets in `/etc/bt/env` (already gitignored) — do **not** commit env.

### A2. CI test gate (fixes P2)
Add API + worker suites to `ci.yml` so the build/deploy chain is gated.

Caveat — there are **3 pre-existing failures** unrelated to the evidence fix
that must be resolved or quarantined first, or CI goes red on day one:
- `test_signal_backtest_results_score_series_uses_row_scope` — per-scope score
  aggregation returns a blended value instead of the scope's own series.
- `test_signal_backtest_results_enqueues_and_returns_404_on_cache_miss` and
  `..._expanded_alias_enqueues_canonical_variant` — expect `/backtest-mc` to
  **enqueue a worker job on cache-miss**; the endpoint currently just raises 404.

Plan: (a) decide whether the enqueue-on-miss behavior is still desired (if not,
update the tests; if yes, implement it), (b) fix or `xfail` the score-scope test
with a tracking issue, then (c) add the job:
```yaml
  api-worker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: |
          pip install --upgrade pip
          pip install -e core/
          pip install fastapi pytest pytest-asyncio sqlalchemy
          pip install -e services/api/ --no-deps
      - run: python -m pytest services/api/tests services/worker/tests -q --tb=short
```
Make `build-images` depend on this job (or gate `deploy-vm` on `ci` success).

### A4. Rebuild best-evidence snapshots on deploy (fixes P5)
Mirror the existing dashboard-snapshot rebuild in `deploy-vm.yml`, after the
`up -d` step:
```bash
IMAGE_TAG=${{ github.event.workflow_run.head_sha }} \
  docker compose --env-file /etc/bt/env \
  -f infra/docker-compose.prod.yml \
  run --rm --no-deps quant_worker \
  python - <<'PY'
import sys
from services.worker.tasks.signal_best_evidence_snapshot import refresh_signal_best_evidence_snapshot
result = refresh_signal_best_evidence_snapshot()
print(result)
sys.exit(0 if result.get("status") in {"succeeded", "partial"} else 1)
PY
```
Note: this is full-universe and can be slow; consider running it non-blocking or
limiting to the signal universe. Until A4 ships, run it **once manually** on the
VM so the evidence tab has data immediately after the code fix.

### A5. Off-VM backups (fixes P6)
- Nightly `pg_dump` of `quant_postgres` to MinIO **and** an off-VM location
  (Oracle Object Storage bucket / external).
- Back up `/etc/bt/env` (encrypted) and confirm `infra/docker-compose.prod.yml`
  is in git (A1). Document restore in `docs/ops/restore.md` (file exists — extend it).

---

## Part B — Weekly signal pipeline as an Airflow DAG (fixes P4)

### Goal
Replace the five staggered APScheduler cron entries with **one** Airflow DAG that
enforces real dependencies, waits on actual completion signals, retries, and
alerts on failure. Reuse the **exact** pattern already proven in
`infra/airflow/dags/warehouse_refresh.py` (HTTP-trigger + PythonSensor poll; no
app imports in the Airflow image).

### Reused infrastructure (no new app logic)
- Trigger endpoint: `POST /ops/scheduler/run/{schedule_id}` (already used by
  `warehouse_refresh`) — fires `dispatch_schedule(schedule_id)` and returns a
  `scheduler_run` id.
- Completion signal: poll the `scheduler_run` / RQ batch status until terminal
  (same sensor approach as the market-refresh sensor in `warehouse_refresh`).
- The five `schedule_id`s already exist in `scheduler_registry.py`.

### DAG shape — `weekly_signal_pipeline`
```
trigger_fundamental_refresh ─▶ wait_fundamental_refresh
        ▼
trigger_wfo_dispatch ─▶ wait_wfo_dispatch
        ▼
trigger_signal_engine_dispatch ─▶ wait_signal_engine_dispatch
        ▼
trigger_signal_backtest_dispatch ─▶ wait_signal_backtest_dispatch
        ▼
trigger_best_evidence_snapshot ─▶ wait_best_evidence_snapshot
        ▼
trigger_dashboard_snapshot ─▶ wait_dashboard_snapshot   (maintenance tail)
```
- Each `trigger_*` = PythonOperator POSTing to `/ops/scheduler/run/{id}`,
  pushing the run id to XCom.
- Each `wait_*` = PythonSensor (`mode="reschedule"`) polling the run/batch until
  terminal; fails the task on a failed/partial run so downstream stops.
- DAG-level: `max_active_runs=1`, `retries=1` + `retry_delay`, `on_failure_callback`
  → alert (email/Slack/webhook). `schedule=None` for v1 (manual), then set the
  weekly cron once green and **disable the corresponding APScheduler crons** to
  avoid double-firing.

### Migration approach (incremental — per `feedback_incremental_phases`)
1. **Phase 1:** add `weekly_signal_pipeline.py` with `schedule=None`. Trigger
   manually; verify each trigger→sensor pair against a real weekend run. APScheduler
   stays the source of truth — zero risk.
2. **Phase 2:** once a manual run is green end-to-end, set the DAG's weekly cron
   and **remove the 5 weekly `ScheduleSpec` crons** from `scheduler_registry.py`
   (keep the `dispatch_schedule` kinds — the endpoint still uses them). Keep
   daily market refresh / factor monitor in APScheduler (or fold them in later).
3. **Phase 3 (optional):** add per-step data-quality gates (e.g., assert N
   symbols refreshed before WFO dispatch), and SLA/alerting.

### Why this is the right "data engineering" upgrade
It turns five hope-it-finished-in-time timers into a dependency graph with real
completion gates, retries, and visibility — the single highest-ROI maturity step,
and it reuses an orchestrator and a pattern you already run in prod.

---

## Related code fix (already implemented, for context)
The signal-evidence tab 404 was a missing serving layer for the
`signal_best_evidence_snapshot` feature. Implemented in this branch:
- `services/api/app/routers/strategy_signals/_evidence.py`:
  `_build_signal_evidence_payload` (extracted), `_read_best_evidence_snapshot`
  (freshness gate), `GET /signal/best-evidence`.
- `services/api/app/routers/strategy_signals/_backtest.py`:
  `build_stored_best_backtest_chart_payload`, `GET /backtest-mc/best-chart`,
  plus a `score_series` alias on `/backtest-mc` results.
- `__init__.py`: re-export the two helpers the worker imports.
All 14 best/evidence tests pass; the worker can now populate the table.
Remaining: run the snapshot worker once (or ship A4) so the table has data.

---

## Suggested order
A2 (CI gate — stops the bleeding) → A1 (version prod compose) → manual
best-evidence backfill → A4 → A5 → A3 → Part B Phase 1 → Phase 2.
