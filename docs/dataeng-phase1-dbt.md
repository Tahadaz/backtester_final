# Data Engineering — Phase 1: dbt + dimensional model

**Status:** Plan (not yet implemented)
**Owner:** Taha
**Date:** 2026-06-22
**Goal of Phase 1:** Stand up a dbt project on top of the existing Postgres that turns the
operational tables into a tested, documented **medallion → star schema** warehouse. This closes
four job-market gaps at once (dbt, SQL/dimensional modeling, data warehouse, data-quality tests)
with **zero risk to the running app** — dbt only *reads* the app's tables and writes new models
into a separate `analytics` schema.

This is the foundation for Phase 2 (Airflow orchestrates `dbt run`/`dbt test`) and Phase 3
(Oracle Autonomous Data Warehouse target swap, Kubernetes).

---

## 1. Current-state findings (from schema inspection, 2026-06-22)

- App is FastAPI + RQ workers + **Postgres 16** + Redis + MinIO, already deployed on Docker.
- Postgres schema comes from `services/api/app/models.py` (~2,100 lines, 77 Alembic migrations).
- **Data is in the Docker Postgres** (`localhost:5555 / quant`), confirmed by real counts:
  `signal_score_history` = **6,642,857 rows**, `fundamental_annual_metric` = 164,138,
  `signal_engine_global_result` = 3,491, `fundamental_latest_snapshot` = 777,
  `fundamental_pillar_score_history` = 704, `stock_master` = 73, `market_data_store` = 91.
  (An earlier read of `pg_stat_user_tables.n_live_tup` showed 0 — that was stale stats, not reality.)
  → dbt points straight at the running compose Postgres; **no dump/seed needed**.
- The operational tables are already fairly clean and typed (closer to *silver* than raw *bronze*).
  True bronze (raw scraped JSON, MinIO parquet) is out of scope for Phase 1 and is where the
  separate "immutable raw layer" work (data versioning/lineage) will land in a later phase.

### Tables that matter for Phase 1

| Table | Grain | Role in star schema |
|---|---|---|
| `signal_score_history` | date × symbol × source × category × horizon | **Primary fact** (`fct_signal_scores`) |
| `fundamental_pillar_score_history` | symbol × import × as_of | **Second fact** (`fct_fundamental_pillars`) |
| `stock_master` | symbol | **Conformed dim** (`dim_stock`) |
| `index_master` | symbol | dim (later — benchmark/index) |
| `strategy_decision` | run × symbol × strategy_kind × trial | fact (later — decisions) |
| `strategy_leaderboard` | run × symbol × strategy_kind × rank | fact (later — backtest perf) |
| `signal_engine_global_result` | symbol × horizon × variant | current-snapshot fact (later) |

`signal_score_history` is the cleanest starting fact: a single numeric measure (`score_pct` in
`[-100, +100]`), an `is_oos` flag, and four low-cardinality dimension keys. Textbook.

---

## 2. What we're building (medallion → star)

```
RAW (Postgres operational tables, owned by the app — read-only to dbt)
        │
        ▼
STAGING / "silver"   models/staging/stg_*.sql   (views: 1:1 clean + rename + cast)
        │
        ▼
MARTS / "gold"       models/marts/*.sql          (tables: dimensional star schema)
        │
        ▼
TESTS                schema.yml                  (not_null / unique / relationships / accepted_values)
```

Two fact tables that **share conformed dimensions** (`dim_stock`, `dim_date`) — this is the exact
concept interviewers probe ("how do you reuse dimensions across facts?").

### Star schema (Phase 1 target)

```
              dim_date ─────────────┐
                                    │
dim_stock ──< fct_signal_scores >── dim_signal_source
   │                                │
   │                                └── dim_category   (category + horizon)
   │
   └──────< fct_fundamental_pillars >── dim_date
```

- **`fct_signal_scores`** — grain: one row per (date, symbol, source, category, horizon).
  Measures: `score_pct`, `is_oos`. FKs: `stock_key`, `date_key`, `source_key`, `category_key`.
- **`fct_fundamental_pillars`** — grain: one row per (symbol, as_of). Measures: `value_score`,
  `quality_score`, `growth_score`, `risk_score`, `cash_flow_score`, `health_score`,
  `overall_score`. FKs: `stock_key`, `date_key`.
- **`dim_stock`** — symbol, display_name, isin, sector, market_cap_class, asset_type,
  market_region, shares_outstanding. (Conformed — used by both facts.)
- **`dim_date`** — generated from a dbt date spine: date_key, year, quarter, month,
  day_of_week, is_month_end, etc.
- **`dim_signal_source`** — source ∈ {engine_legacy, engine_expanded, wfo} + human label.
- **`dim_category`** — category × horizon junk dimension (low cardinality).

---

## 3. Decision: where does dbt point? — RESOLVED

The data is already in the **Docker compose Postgres** (`localhost:5555 / quant`, user `app`).
dbt connects there directly, **reads** the app's operational tables, and **writes** all its output
to a dedicated `analytics` schema (and `analytics_staging` for views) so it can never collide with
the app. No dump, no seed, no prod access required.

Safety: use the existing `app` role for now (simplest); optionally create a read-only `dbt_ro`
role later. dbt never writes to app-owned schemas — only `analytics*`.

An Oracle Autonomous Data Warehouse target (Phase 1.2) is an additive profile, not a replacement.

---

## 4. Project layout

```
dataeng/
└── dbt/
    ├── dbt_project.yml
    ├── profiles.yml            # local Postgres target "dev"; OCI target "oci" added in Phase 1.2
    ├── packages.yml            # dbt_utils (date spine, surrogate keys, tests)
    ├── models/
    │   ├── staging/
    │   │   ├── _staging__sources.yml      # declares Postgres source tables + freshness
    │   │   ├── _staging__models.yml        # column docs + tests for stg_ models
    │   │   ├── stg_stock_master.sql
    │   │   ├── stg_signal_score_history.sql
    │   │   └── stg_fundamental_pillar_scores.sql
    │   └── marts/
    │       ├── _marts__models.yml          # tests + docs for dims/facts (the data-quality layer)
    │       ├── dim_stock.sql
    │       ├── dim_date.sql
    │       ├── dim_signal_source.sql
    │       ├── dim_category.sql
    │       ├── fct_signal_scores.sql
    │       └── fct_fundamental_pillars.sql
    ├── seeds/                  # optional synthetic fallback
    └── README.md              # how to run, the schema diagram, the resume blurb
```

Lives under a new top-level `dataeng/` dir — keeps it cleanly separated from `services/` and
`core/`, and is the obvious home for Airflow (`dataeng/airflow/`) in Phase 2.

---

## 5. Model-by-model spec

### Staging (views, `materialized: view`, schema `analytics_staging`)

- **`stg_stock_master`** — select from `stock_master`; keep symbol, display_name, isin, sector,
  market_cap_class, asset_type, market_region, shares_outstanding, is_active. Trim/upper symbol.
- **`stg_signal_score_history`** — select from `signal_score_history`; cast `date`, coerce
  `score_pct` to numeric, keep `is_oos`, normalize `source`/`category`/`horizon` casing.
- **`stg_fundamental_pillar_scores`** — select from `fundamental_pillar_score_history`; keep
  symbol, as_of, the seven `*_score` columns.

### Marts (tables, schema `analytics`)

- **`dim_stock`** — `surrogate_key(symbol)` → `stock_key`; one row per active symbol from
  `stg_stock_master`.
- **`dim_date`** — `dbt_utils.date_spine` across the min/max of both facts; `date_key` =
  YYYYMMDD int; calendar attributes.
- **`dim_signal_source`** — distinct `source` from the fact + a static label mapping.
- **`dim_category`** — distinct (category, horizon) pairs → `category_key`.
- **`fct_signal_scores`** — from `stg_signal_score_history`, join to dims to attach surrogate
  keys; measures `score_pct`, `is_oos`. **Materialize `incremental`** (this table is ~6.6M rows):
  on incremental runs, only process rows with `date > (select max(date_key)...)`. Use
  `unique_key` on the natural grain to stay idempotent. Good place to learn dbt incremental models.
- **`fct_fundamental_pillars`** — from `stg_fundamental_pillar_scores`, join to `dim_stock` +
  `dim_date`; the seven pillar measures.

---

## 6. Data-quality tests (the "data quality" résumé row, for free)

In `schema.yml` files — these run with `dbt test`:

- **Keys / integrity**
  - `dim_stock.stock_key`, `dim_date.date_key` → `unique`, `not_null`
  - `fct_signal_scores.stock_key` / `date_key` / `source_key` / `category_key` →
    `relationships` to their dims (no orphan facts)
- **Domain / accepted values**
  - `signal_score_history.source` → `accepted_values: [engine_legacy, engine_expanded, wfo]`
  - `dim_stock.asset_type` → `accepted_values: [equity, commodity, forex, bond, crypto]`
- **Range checks (mirrors `integrity.py` spirit)**
  - `fct_signal_scores.score_pct` → custom test `between -100 and 100`
  - pillar scores → `between 0 and 100` (or whatever the real bound is — confirm)
- **Source freshness** — `dbt source freshness` on `signal_score_history` (warn if newest
  `date` is older than N days) → this is the seed of the freshness-alerting idea from the
  app-improvement list.

---

## 7. Build order (do these in sequence)

1. **Confirm data location** (§3 action item); dump a slice → local `analytics`-adjacent schema.
2. `pip install dbt-postgres`; `dbt init` into `dataeng/dbt`; wire `profiles.yml` to
   `localhost:5555` (read app tables, write `analytics`).
3. Add `packages.yml` (`dbt_utils`); `dbt deps`.
4. Write the 3 `stg_` models; `dbt run --select staging`. Get them green.
5. Write `dim_*` + `dim_date`; `dbt run --select dim_*`.
6. Write `fct_signal_scores`; `dbt run`. Then `fct_fundamental_pillars`.
7. Add `schema.yml` tests (§6); `dbt test` until clean.
8. `dbt docs generate && dbt docs serve` — the lineage graph is a great portfolio screenshot.
9. Write `dataeng/dbt/README.md` with the schema diagram + a 2-line résumé blurb.

**Definition of done for Phase 1:** `dbt build` (run + test) passes end-to-end; `dbt docs`
shows the staging → star lineage; README documents it.

---

## 8. Phase 1.2 and beyond (not now)

- **1.2 — Oracle Autonomous Data Warehouse target:** add an Oracle profile, `dbt run --target oci`. Same models, new engine
  → ticks "cloud" + "warehouse" + "ported dbt across engines". Needs an OCI tenancy + a load step
  (Postgres → Oracle Autonomous Data Warehouse via a small Python job or `dlt`).
- **Phase 2 — Airflow:** one DAG `ingest → dbt run → dbt test`, replacing parts of
  `services/worker/scheduler.py`.
- **Phase 3 — Kubernetes + KEDA, Kafka, MLflow.**

---

## 9. Open questions to resolve before implementing

1. ~~Where does the data live?~~ **Resolved:** Docker compose Postgres, ~6.6M-row fact present.
2. Confirm the real numeric bounds for pillar scores (0–100? 0–1?) so range tests are correct —
   will read from the scoring code at build time.
3. OK to introduce a top-level `dataeng/` directory? (Keeps DE work isolated from app code.)
4. dbt runs on the host (`pip install dbt-postgres`, connect to `localhost:5555`) vs. as a compose
   service — recommend host for fast iteration now; containerize in Phase 2 with Airflow.
