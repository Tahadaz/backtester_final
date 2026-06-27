# `dataeng/` — Analytics warehouse (dbt)

A **dbt** project that turns the backtester's operational Postgres tables into a tested,
documented **medallion → star-schema** warehouse. It reads the application's tables read-only and
writes its own models into dedicated `analytics_*` schemas, so it can never affect the running app.

This is **Phase 1 + 2** of a phased data-engineering build.
- Phase 1 (done) — dbt warehouse — see `../docs/dataeng-phase1-dbt.md`
- Phase 2 (done) — Airflow orchestration — see `../docs/dataeng-phase2-airflow.md` and §Phase 2 below
- Roadmap: Kubernetes + KEDA → Kafka / MLflow

---

## Architecture

```
RAW  (app Postgres `public`, read-only — declared as dbt sources)
  stock_master · signal_score_history (~6.6M) · fundamental_pillar_score_history · macro_factor_meta
        │   source()
        ▼
SILVER  schema `analytics_staging`  (views: rename / cast / clean only — no logic)
  stg_stock_master · stg_signal_score_history · stg_fundamental_pillar_scores · stg_macro_factor_meta
        │   ref()
        ▼
GOLD  schema `analytics_marts`  (physical star schema)

        dim_date ─────────┐          ┌───── dim_signal_source
                          │          │
        dim_symbol ──< fct_signal_scores >── dim_category      (incremental · ~6.6M rows)
            │
            └──────< fct_fundamental_pillars >── dim_date      (grain: symbol × import_id)
```

### Models

| Layer | Model | Materialization | Grain / notes |
|---|---|---|---|
| staging | `stg_stock_master` | view | per equity symbol |
| staging | `stg_signal_score_history` | view | splits compound `source` → base + method |
| staging | `stg_fundamental_pillar_scores` | view | per (symbol, import) pillar scores |
| staging | `stg_macro_factor_meta` | view | non-equity symbols (commodities, FX) |
| marts | `dim_symbol` | table | **conformed** — equities ∪ macro factors |
| marts | `dim_date` | table | `date_spine`, 2000 → +10y (covers projections) |
| marts | `dim_signal_source` | table | one row per raw signal source |
| marts | `dim_category` | table | junk dim: (category, horizon) |
| marts | `fct_signal_scores` | **incremental** | date × symbol × source × category × horizon |
| marts | `fct_fundamental_pillars` | table | symbol × import_id |

### Data quality
Every model is tested (`dbt test`). 51 checks total: `not_null` / `unique` on keys,
`accepted_values` on coded columns (values verified against real data), `accepted_range` on scores,
and `relationships` proving **zero orphan facts** (referential integrity enforced by tests).

---

## Stack
- **dbt-core 1.11.11** + **dbt-postgres** adapter, **dbt_utils** package.
- Installed in an **isolated virtualenv** (`dataeng/.venv`) — deliberately separate from the app's
  Python env to avoid dependency conflicts.
- Target warehouse: the Docker-compose Postgres (`localhost:5555/quant`). A BigQuery target is a
  planned additive profile (Phase 1.2).

## How to run

```bash
# 1. One-time: create the isolated env and install dbt
python -m venv dataeng/.venv
dataeng/.venv/Scripts/python -m pip install "dbt-core==1.11.11" dbt-postgres

# 2. One-time: connection profile at ~/.dbt/profiles.yml  (NOT committed — see block below)

# 3. Fetch packages, then build + test everything
DBT=dataeng/.venv/Scripts/dbt.exe
"$DBT" deps  --project-dir dataeng/dbt
"$DBT" build --project-dir dataeng/dbt        # run all models + run all tests

# 4. Explore the lineage graph in a browser
"$DBT" docs generate --project-dir dataeng/dbt
"$DBT" docs serve    --project-dir dataeng/dbt   # opens http://localhost:8080
```

`~/.dbt/profiles.yml` (local dev — in production these would come from `env_var()`):

```yaml
quant_warehouse:
  target: dev
  outputs:
    dev:
      type: postgres
      host: localhost
      port: 5555
      user: app
      password: app
      dbname: quant
      schema: analytics
      threads: 4
```

The Docker stack must be up (`infra/docker-compose.yml`) so the Postgres is reachable.

---

## Design decisions worth knowing
These came out of letting `dbt test` fail against real data, then fixing the model:

1. **`signal_score_history.source` is compound** (`wfo:expanded_factor_x_ta_combo`). Split into
   `source_base` + `source_method` in staging instead of treating it as one opaque code.
2. **`dim_symbol` is conformed across heterogeneous sources.** The signal fact scores both MASI
   equities *and* macro factors (BRENT, DXY, EURUSD, GOLD). The dimension unions `stock_master`
   with `macro_factor_meta` so the fact has zero orphans.
3. **Pillar fact grain is `(symbol, import_id)`, not `(symbol, as_of)`.** The `unique` test caught
   that the same `as_of` recurs across re-imports.
4. **`dim_date` extends 10 years into the future** because fundamental projections are forward-dated.
5. **`fct_signal_scores` is incremental** — full first load (~6.6M rows, ~38s), then only the latest
   day reprocessed (~3.5s), deduped by surrogate key.

---

## Phase 2 — Airflow orchestration

Phase 2 adds **Apache Airflow** as an opt-in orchestrator that chains market-refresh → dbt as a
real DAG, replacing fragile staggered-cron timing with explicit data-dependency edges.

### Starting the Airflow stack

Airflow is gated behind a Docker Compose profile so a plain `docker compose up` starts **zero**
Airflow containers and the app behaves exactly as before.

```bash
# First time only — initialise Airflow metadata DB and create admin user
docker compose --profile airflow up airflow_init

# Then start scheduler + webserver
docker compose --profile airflow up airflow_scheduler airflow_webserver

# Or bring up everything (app + Airflow) in one shot
docker compose --profile airflow up
```

Airflow UI: **http://localhost:8081** (user: `admin` / password: `admin`)

> **Port note:** Airflow webserver is on **8081**, not 8080, to avoid conflict with
> `dbt docs serve` which also defaults to 8080.

### `warehouse_refresh` DAG

```
trigger_market_refresh     PythonOperator — dispatch_schedule("daily_market_refresh")
        │  pushes refresh_run_id to XCom
        ▼
wait_for_market_refresh    PythonSensor   — polls market_refresh_run until terminal
        │  terminal-success: "succeeded" | "partial"
        │  terminal-failure: "failed" → raises, halts DAG
        ▼
dbt_deps                   BashOperator  — dbt deps (idempotent)
        ▼
dbt_run_staging            BashOperator  — dbt run  --select staging
        ▼
dbt_test_staging           BashOperator  — dbt test --select staging  (gate: failure stops marts)
        ▼
dbt_run_marts              BashOperator  — dbt run  --select marts
        ▼
dbt_test_marts             BashOperator  — dbt test --select marts
        ▼
dbt_source_freshness       BashOperator  — dbt source freshness  (soft-fail, informational)
```

**Why trigger + sensor?** The sensor blocks on the *real* completion signal by polling the API
(`GET /market-data/refresh/{run_id}`), not a guessed timer. This replaces the fragile
staggered-cron dependency model in `scheduler_registry.py`.

**Why split run/test per layer?** A staging test failure stops before marts are built — you never
publish gold tables on top of data that already failed silver checks.

### Infrastructure decisions

| Decision | Choice | Reason |
|---|---|---|
| Executor | LocalExecutor | Tasks run as scheduler subprocesses — no extra Celery/Redis infra. KubernetesExecutor is Phase 3. |
| Metadata DB | `airflow` logical DB on `quant_postgres` | Reuse existing Postgres; separate DB keeps Airflow tables isolated from `quant`. |
| App coupling | HTTP to the API (`POST /ops/scheduler/run/…`, `GET /market-data/refresh/…`) | Airflow image needs no app libraries (no rq, SQLAlchemy, app models). Loose coupling; auth handled by optional env vars. |
| dbt in Airflow image | Installed via pip in `infra/airflow/Dockerfile` | BashOperators call `dbt` directly; no bind-mount to host venv. |
| dbt connection | `env_var()` profile at `dataeng/dbt/profiles.yml` | No secrets committed; Airflow container injects creds as env vars. |
| Webserver port | 8081 (host) → 8080 (container) | Avoids collision with `dbt docs serve` on 8080. |

### Airflow metadata DB

`airflow_init` creates a separate `airflow` logical database on `quant_postgres` (idempotent:
`SELECT 1 FROM pg_database WHERE datname='airflow'` guard before `CREATE DATABASE`). Airflow's
`SQL_ALCHEMY_CONN` points at `airflow`, never at the `quant` app database.

---

## Résumé blurb
> Built a dbt (medallion → star-schema) analytics warehouse over a 6.6M-row Postgres dataset:
> conformed dimensions with surrogate keys, an incremental fact model, and 50+ data-quality tests
> (referential-integrity, range, accepted-value) enforcing correctness in the build.
> Then orchestrated the pipeline with Apache Airflow: a trigger+sensor DAG that blocks on the
> RQ worker's real completion signal, chains market-refresh → dbt staging → dbt marts with
> an explicit test gate between layers, and runs entirely on LocalExecutor behind a Docker
> Compose profile (zero infra added to the default `docker compose up`).
