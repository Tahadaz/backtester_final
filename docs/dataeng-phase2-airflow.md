# Data Engineering — Phase 2: Airflow orchestration

**Status:** Implemented (2026-06-23), refactored (2026-06-23) — trigger+sensor now use HTTP to the API (not in-process imports); see commit sequence in §7
**Owner:** Taha
**Date:** 2026-06-23
**Prereq:** Phase 1 (dbt warehouse) is done & committed — see `docs/dataeng-phase1-dbt.md` and `dataeng/README.md`.

**Goal of Phase 2:** Introduce **Apache Airflow** as an orchestrator that runs the chain
`refresh data → dbt run → dbt test` as a real **DAG**, so that (a) cross-step dependencies are
explicit instead of guessed by staggered cron times, and (b) the Phase-1 warehouse is rebuilt and
re-validated automatically whenever fresh data lands. A failing `dbt test` halts the pipeline.

This is **additive and non-destructive**: the existing APScheduler process
(`services/worker/scheduler.py`) stays running and untouched. Airflow is a second, opt-in
orchestrator that *triggers existing code* and *waits* on it — it does not reimplement compute.

---

## 0. Hard guardrails (do not violate)

1. **Do NOT modify or delete** `services/worker/scheduler.py`, `scheduler_dispatch.py`, or
   `scheduler_registry.py` beyond *importing* `dispatch_schedule`. The old scheduler must keep
   working exactly as-is. Phase 2 runs alongside it.
2. **Do NOT reimplement** ingestion, signal-engine, WFO, or dbt logic inside Airflow operators.
   Airflow only *triggers* (`dispatch_schedule(...)`) and *runs the dbt CLI*. Heavy compute stays
   in the RQ workers and in dbt.
3. **No secrets committed.** dbt connection comes from `env_var()` in a committed
   `profiles.yml` (env-var-only, no passwords) — credentials are injected as Airflow container env.
4. **Airflow gets its own metadata database** (`airflow` logical DB on the existing
   `quant_postgres`). Never point Airflow's metadata DB at the `quant` application database.
5. Default the Airflow stack **off** in `docker-compose.yml` via a compose `profiles:` flag, the
   same way `quant_frontend` uses `profiles: ["frontend-container"]`. It must not start with a
   plain `docker compose up` unless explicitly opted in. This keeps day-to-day app dev unaffected.
6. Keep everything inside **`dataeng/`** and **`infra/airflow/`** + the new compose service block.
   Do not scatter Airflow files across the app.

---

## 1. What exists today (grounding — read these first)

- **`services/worker/scheduler.py`** — a dedicated APScheduler `BlockingScheduler` process
  (compose service `quant_scheduler`, gated by `WORKER_SCHEDULER_ENABLED`, default `0` locally).
  It registers one job per `ScheduleSpec` and calls `dispatch_schedule(schedule_id)`.
- **`services/worker/tasks/scheduler_dispatch.py`** — `dispatch_schedule(schedule_id, *, trigger_source)`
  is the single entry point. For `daily_market_refresh` it creates a `MarketRefreshRun` row
  (status `"queued"`, `symbols_total`, `symbols_done`, `symbols_failed`) and enqueues
  `refresh_market_data.refresh_all_tracked_symbols` on the `market_refresh` RQ queue, returning a
  dict including `refresh_run_id` and `rq_job_id`. This is the function Airflow will call.
- **`services/api/app/services/scheduler_registry.py`** — `SCHEDULE_SPECS`: the 10 cron schedules.
  Note the **guessed-timing dependency chain** this plan replaces: fundamentals 20:00 Sat →
  WFO 21:00 Sun → signal engine 22:00 Sun → backtest 23:00 Sun → evidence 01:30 Mon. The cron
  offsets *are* the (fragile) dependency model.
- **`infra/docker-compose.yml`** — Postgres 16 (`quant_postgres`, host `5555`→`5432`, db `quant`,
  user/pass `app`/`app`), Redis, MinIO, API, worker pools, `quant_scheduler`. Compose `profiles:`
  is already used by `quant_frontend`. The code is bind-mounted (`../core`, `../services/*`) so
  containers pick up edits without rebuild.
- **`dataeng/dbt/`** — the Phase-1 dbt project. Profile name `quant_warehouse`. Today the profile
  lives at `~/.dbt/profiles.yml` with hardcoded local creds. Phase 2 needs an **env-var profile**
  so the Airflow container can supply the connection.
- **`dataeng/.venv`** — isolated dbt venv (Windows host). Airflow runs in Linux containers, so it
  will install its own dbt (see §4); it does **not** reuse `dataeng/.venv`.

---

## 2. Target DAG

DAG id: **`warehouse_refresh`**. Schedule: `None` to start (manual trigger via UI/CLI) so the first
runs are deliberate; switch to a cron later once green. `catchup=False`. `max_active_runs=1`.
Default args: `retries=2`, `retry_delay=5m`, `email_on_failure=False` (no SMTP locally).

Task graph:

```
trigger_market_refresh        (PythonOperator → dispatch_schedule("daily_market_refresh"))
        │   pushes refresh_run_id to XCom
        ▼
wait_for_market_refresh        (PythonSensor → polls MarketRefreshRun row until terminal)
        │
        ▼
dbt_deps                       (BashOperator → dbt deps)        [first run only; safe to always run]
        │
        ▼
dbt_run_staging                (BashOperator → dbt run  --select staging)
        ▼
dbt_test_staging               (BashOperator → dbt test --select staging)
        ▼
dbt_run_marts                  (BashOperator → dbt run  --select marts)
        ▼
dbt_test_marts                 (BashOperator → dbt test --select marts)
        ▼
dbt_source_freshness           (BashOperator → dbt source freshness)   [optional; allow soft-fail]
```

**Why this shape teaches the right things:**
- `trigger_market_refresh` + `wait_for_market_refresh` together are the **sensor pattern** —
  Airflow orchestrating an *external* system (your RQ workers) and blocking on its real completion
  signal, not a timer. This is the core lesson and the part that replaces guessed-timing cron.
- Splitting `run`/`test` per layer means a **staging test failure stops before marts are built** —
  you never publish gold tables on top of data that already failed silver checks.

### Sensor contract (important — confirm before coding)

`wait_for_market_refresh` reads `refresh_run_id` from XCom and polls the `MarketRefreshRun` row.
**Sonnet must confirm the exact terminal-status semantics** in
`services/worker/tasks/refresh_market_data.py` and the `MarketRefreshRun` model in
`services/api/app/models.py` before implementing. Expected contract:
- terminal-success when `status` is a done value (confirm the literal string — likely `"done"`/
  `"succeeded"`/`"completed"`) **or** `symbols_done + symbols_failed >= symbols_total`;
- terminal-failure when `status == "failed"` → raise so the sensor fails the task;
- `poke_interval=30`, `timeout=2h`, `mode="reschedule"` (frees the worker slot between pokes).

Use a short-lived SQLAlchemy session built from `DATABASE_URL` (reuse
`services/worker/db.py:SessionLocal` if importable in the Airflow image, else a plain
`create_engine`). Do not hold a session open across pokes.

### v1 scope decision (build this, defer the rest)

- **v1 (this plan):** the single `warehouse_refresh` DAG above — market refresh → dbt run/test.
  This proves the trigger+sensor+dbt pattern end-to-end with the least surface area.
- **v1.1 (next):** extend the same DAG (or a `weekly_signals` DAG) to chain the real
  fundamentals → WFO → signal-engine → backtest dependency, each as `trigger_* → wait_for_*`,
  replacing the staggered-cron coordination for that chain. Old scheduler can then be flipped off
  for *those* specs only.
- **v2 (later):** astronomer-cosmos to render each dbt model as its own Airflow task (per-model
  lineage in the Airflow graph); Oracle Autonomous Data Warehouse target (Phase 1.2); Kubernetes executor (Phase 3).

Do not build v1.1/v2 now. Ship v1 green first.

---

## 3. dbt profile change (env-var driven)

Add a committed, secret-free profile so the Airflow container supplies the connection via env.

Create **`dataeng/dbt/profiles.yml`** (committed — uses `env_var`, no passwords inline):

```yaml
quant_warehouse:
  target: "{{ env_var('DBT_TARGET', 'dev') }}"
  outputs:
    dev:
      type: postgres
      host: "{{ env_var('DBT_PG_HOST', 'localhost') }}"
      port: "{{ env_var('DBT_PG_PORT', '5432') | as_number }}"
      user: "{{ env_var('DBT_PG_USER', 'app') }}"
      password: "{{ env_var('DBT_PG_PASSWORD', 'app') }}"
      dbname: "{{ env_var('DBT_PG_DBNAME', 'quant') }}"
      schema: "{{ env_var('DBT_PG_SCHEMA', 'analytics') }}"
      threads: 4
```

dbt CLI calls in Airflow pass `--profiles-dir /opt/dataeng/dbt --project-dir /opt/dataeng/dbt`.
The existing `~/.dbt/profiles.yml` on the Windows host is unaffected (still works for manual runs).
From inside the Airflow container the host is `quant_postgres` and port `5432` (container-internal),
**not** `localhost:5555`. Set these as Airflow service env (see §4).

---

## 4. Infra: Airflow image + compose service

### 4a. `infra/airflow/Dockerfile`

```dockerfile
FROM apache/airflow:2.10.4-python3.11
# dbt lives in the Airflow image so BashOperator can call it directly.
# Pin to match Phase 1 (dbt-core 1.11.x + dbt-postgres) and dbt_utils.
RUN pip install --no-cache-dir \
      "dbt-core==1.11.11" "dbt-postgres==1.11.*" \
      "apache-airflow-providers-postgres"
```

(If `dbt-postgres==1.11.*` does not resolve against dbt-core 1.11.11, Sonnet should pin the exact
compatible adapter version that `dataeng/.venv` resolved in Phase 1 — check
`dataeng/.venv/Lib/site-packages` or `pip freeze` from that venv.)

### 4b. `docker-compose.yml` additions (gated behind a profile)

Add **all** Airflow services under `profiles: ["airflow"]` so they only start with
`docker compose --profile airflow up`. Reuse the existing `quant_postgres` for Airflow's metadata
DB via a **separate logical database** `airflow` (create it in an init step).

Services to add:

1. **`airflow_init`** (`restart: "no"`): depends on `quant_postgres healthy`. Creates the `airflow`
   database if absent, then runs `airflow db migrate` and `airflow users create` (admin/admin for
   local). Create the DB with a small psql/`CREATE DATABASE` guard (idempotent: ignore "already
   exists"). Use `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://app:app@quant_postgres:5432/airflow`.
2. **`airflow_scheduler`** (`command: airflow scheduler`).
3. **`airflow_webserver`** (`command: airflow webserver`, port `8080:8080`).
   ⚠️ MinIO already publishes `9001`; the dbt docs server uses `8080` on the host — when Airflow
   webserver is up, don't also run `dbt docs serve` on 8080. If conflict matters, map Airflow to
   `8081:8080`. Pick one and note it in `dataeng/README.md`.

Shared Airflow env (define once via a YAML anchor `&airflow_env`, mirroring the existing
`x-worker-base` pattern):

```yaml
AIRFLOW__CORE__EXECUTOR: LocalExecutor
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://app:app@quant_postgres:5432/airflow
AIRFLOW__CORE__LOAD_EXAMPLES: "false"
AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: "true"
# Connection the DAG uses to enqueue + the dbt CLI uses to write the warehouse:
REDIS_URL: redis://quant_redis:6379/0
DATABASE_URL: postgresql+psycopg2://app:app@quant_postgres:5432/quant
MARKET_REFRESH_QUEUE_NAME: market_refresh
PYTHONPATH: /repo
# dbt env-var profile (container-internal host/port):
DBT_PG_HOST: quant_postgres
DBT_PG_PORT: "5432"
DBT_PG_USER: app
DBT_PG_PASSWORD: app
DBT_PG_DBNAME: quant
DBT_PG_SCHEMA: analytics
```

Volumes for the scheduler + webserver services:
```yaml
- ../dataeng:/opt/dataeng          # dbt project + committed profiles.yml
- ../core:/repo/core               # so `import services...`/core works for the trigger task
- ../services:/repo/services       # dispatch_schedule + SessionLocal
- ./airflow/dags:/opt/airflow/dags # the DAG file
- airflow_logs:/opt/airflow/logs
```
Add `airflow_logs:` to the top-level `volumes:` block. **Use `LocalExecutor`** (single
scheduler+webserver, no Celery/extra Redis for Airflow) — correct and minimal for this scale.

**Executor rationale to put in the PR description:** LocalExecutor runs tasks as subprocesses of the
scheduler — enough parallelism for this DAG, far less moving infrastructure than CeleryExecutor,
and no second Redis. KubernetesExecutor is the Phase-3 story.

---

## 5. The DAG file: `infra/airflow/dags/warehouse_refresh.py`

Key implementation notes:

- **Trigger task** (`PythonOperator`):
  ```python
  from services.worker.tasks.scheduler_dispatch import dispatch_schedule
  def _trigger(**ctx):
      res = dispatch_schedule("daily_market_refresh", trigger_source="airflow")
      if res.get("status") == "failed":
          raise RuntimeError(f"dispatch failed: {res.get('error')}")
      run_id = res.get("refresh_run_id")
      if not run_id:
          # e.g. no_active_stocks → nothing to wait for; skip downstream gracefully
          raise AirflowSkipException(res.get("reason", "no refresh_run_id"))
      ctx["ti"].xcom_push(key="refresh_run_id", value=run_id)
  ```
- **Sensor task** (`PythonSensor`, `mode="reschedule"`, `poke_interval=30`, `timeout=7200`): pull
  `refresh_run_id` from XCom, open a short SQLAlchemy session, read the `MarketRefreshRun` row,
  return `True` on terminal-success, raise on terminal-failure, return `False` otherwise.
  **Confirm the terminal-status literal first (see §2 sensor contract).**
- **dbt tasks** (`BashOperator`), one per step:
  ```
  cd /opt/dataeng/dbt && dbt run  --select staging --profiles-dir /opt/dataeng/dbt --project-dir /opt/dataeng/dbt
  cd /opt/dataeng/dbt && dbt test --select staging --profiles-dir /opt/dataeng/dbt --project-dir /opt/dataeng/dbt
  cd /opt/dataeng/dbt && dbt run  --select marts   ...
  cd /opt/dataeng/dbt && dbt test --select marts   ...
  ```
  Run `dbt deps` once as the first dbt task (idempotent). Set `bash_command` with explicit
  `--profiles-dir`/`--project-dir`; do not rely on `~/.dbt`.
- Wire dependencies with `>>` in the documented order. Give every task a `doc_md` one-liner so the
  Airflow UI explains the pipeline (this also screenshots well for the résumé).

---

## 6. Acceptance criteria (definition of done)

1. `docker compose --profile airflow up airflow_init` completes: `airflow` DB created, migrations
   applied, admin user exists. Plain `docker compose up` (no profile) starts **zero** Airflow
   containers and the app behaves exactly as before.
2. Airflow UI reachable (`http://localhost:8080`, or `8081` if remapped); `warehouse_refresh` DAG
   present, no import errors, examples not loaded.
3. Manually trigger the DAG with the app stack up and data present:
   - `trigger_market_refresh` enqueues a real `market_refresh` RQ job and a `MarketRefreshRun` row
     appears.
   - `wait_for_market_refresh` blocks, then succeeds when the refresh row reaches terminal-success.
   - `dbt_run_staging → dbt_test_staging → dbt_run_marts → dbt_test_marts` all green; the
     `analytics_staging` / `analytics_marts` schemas are rebuilt.
4. **Negative test (prove the gate works):** temporarily break one dbt model so a marts test fails;
   confirm the DAG **stops at `dbt_test_marts`** and downstream does not run. Revert the break.
5. The existing `quant_scheduler` / APScheduler path is unchanged and still functions.
6. Docs updated: add a "Phase 2 — Airflow" section to `dataeng/README.md` (how to start the
   profile, screenshot of the DAG graph, the trigger+sensor explanation) and flip this plan's
   status to "Implemented". Add a short résumé blurb.
7. No secrets committed (grep the diff for passwords outside env-var defaults). `profiles.yml` uses
   `env_var()` only.

---

## 7. Suggested commit sequence (small, reviewable)

1. `feat(dataeng): env-var dbt profile for containerized runs` — `dataeng/dbt/profiles.yml`.
2. `feat(infra): Airflow image + compose profile (LocalExecutor, own metadata DB)` —
   `infra/airflow/Dockerfile`, compose additions, `airflow_init`.
3. `feat(dataeng): warehouse_refresh DAG (trigger→sensor→dbt run/test)` — the DAG file.
4. `docs(dataeng): document Phase 2 Airflow orchestration` — README + flip this plan status.

Keep each commit independently buildable. Do not squash the DAG and infra together — the reviewer
should be able to read the infra change separately from the orchestration logic.

---

## 8. Open questions for Sonnet to resolve during implementation (don't guess — verify)

1. **Exact `MarketRefreshRun` terminal-status string** — read the model + `refresh_market_data.py`.
2. **dbt-postgres adapter version** compatible with dbt-core 1.11.11 — match Phase 1's resolved
   version from `dataeng/.venv`.
3. **Port 8080 conflict** between Airflow webserver and `dbt docs serve` — decide 8080 vs 8081 and
   document it.
4. Whether `services/worker/db.py:SessionLocal` imports cleanly inside the Airflow image (it should,
   given `PYTHONPATH=/repo` and the `../services` mount); if not, build a local engine from
   `DATABASE_URL` in the sensor.
