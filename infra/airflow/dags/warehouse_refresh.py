"""
warehouse_refresh DAG
=====================
Orchestrates the full data-engineering pipeline:

    trigger_market_refresh
        │  (PythonOperator — POST /ops/scheduler/run/daily_market_refresh;
        │   pushes refresh_run_id to XCom)
        ▼
    wait_for_market_refresh
        │  (PythonSensor — GET /market-data/refresh/{run_id} until terminal;
        │   reschedule mode)
        ▼
    dbt_deps → dbt_run_staging → dbt_test_staging → dbt_run_marts → dbt_test_marts
        ▼
    dbt_source_freshness  (soft-fail — informational only)

Design:
- trigger + sensor replace staggered-cron coordination: Airflow blocks on the *real*
  completion signal polled from the API, not a guessed timer offset.
- Splitting run/test per layer means a staging test failure stops before marts are built.
- Schedule is None (manual) for v1; switch to a cron once green.
- max_active_runs=1 prevents concurrent refreshes.
- All app communication is via HTTP to the running API — no app library imports,
  no SQLAlchemy, no RQ. The Airflow image only needs `requests` (bundled with Airflow).
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.exceptions import AirflowSkipException
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# dbt lives in its own isolated venv inside the image (it cannot share Airflow's
# Python env — conflicting deps). Call its binary by absolute path.
DBT_BASE = "cd /opt/dataeng/dbt && /opt/dbt-venv/bin/dbt"
DBT_FLAGS = "--profiles-dir /opt/dataeng/dbt --project-dir /opt/dataeng/dbt"

TERMINAL_SUCCESS = {"succeeded", "partial"}
TERMINAL_FAILURE = {"failed"}

# API base URL — injected via compose env; defaults to the compose service name.
API_BASE = os.environ.get("API_BASE_URL", "http://quant_api:8000")

# Optional auth headers — read from env vars, omitted when unset (dev mode).
_ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "").strip()
_API_KEY = os.environ.get("API_KEY", "").strip()

# Number of consecutive 404 pokes before treating the missing row as a hard error.
_NOT_FOUND_LIMIT = 5

# ---------------------------------------------------------------------------
# Task callables
# ---------------------------------------------------------------------------


def _trigger_market_refresh(**ctx):
    """
    POST /ops/scheduler/run/daily_market_refresh → dispatch via the API.
    Pushes refresh_run_id to XCom so the sensor can poll it.
    Raises AirflowSkipException if there are no active stocks to refresh.
    """
    import requests

    headers = {"X-Admin-Api-Key": _ADMIN_API_KEY} if _ADMIN_API_KEY else {}
    resp = requests.post(
        f"{API_BASE}/ops/scheduler/run/daily_market_refresh",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    res = resp.json()

    if res.get("status") == "failed":
        raise RuntimeError(f"dispatch failed: {res.get('error')}")

    run_id = res.get("refresh_run_id")
    if not run_id:
        reason = res.get("reason", "no refresh_run_id returned")
        logger.info("Skipping sensor: %s", reason)
        raise AirflowSkipException(reason)

    logger.info(
        "Enqueued market refresh — refresh_run_id=%s rq_job_id=%s",
        run_id,
        res.get("rq_job_id"),
    )
    ctx["ti"].xcom_push(key="refresh_run_id", value=run_id)


def _wait_for_market_refresh(**ctx):
    """
    GET /market-data/refresh/{refresh_run_id} until terminal.
    Returns True on success (succeeded / partial).
    Raises RuntimeError on failure (failed) — halts the DAG.
    Returns False to continue poking (queued / running / 404 below limit).

    Uses mode=reschedule so the worker slot is freed between pokes.
    Tracks consecutive 404s via XCom; raises after _NOT_FOUND_LIMIT pokes.
    """
    import requests

    ti = ctx["ti"]
    run_id = ti.xcom_pull(task_ids="trigger_market_refresh", key="refresh_run_id")
    if not run_id:
        raise ValueError(
            "refresh_run_id not found in XCom — trigger task may have been skipped"
        )

    headers = {"X-API-Key": _API_KEY} if _API_KEY else {}
    url = f"{API_BASE}/market-data/refresh/{run_id}"
    resp = requests.get(url, headers=headers, timeout=10)

    if resp.status_code == 404:
        # Row not yet visible (should be rare — it's committed before the RQ job is
        # enqueued, but guard anyway).
        not_found_count = (
            ti.xcom_pull(task_ids=ti.task_id, key="not_found_count") or 0
        ) + 1
        ti.xcom_push(key="not_found_count", value=not_found_count)
        if not_found_count >= _NOT_FOUND_LIMIT:
            raise RuntimeError(
                f"GET {url} returned 404 for {not_found_count} consecutive pokes — "
                f"market_refresh_run row missing for id={run_id}"
            )
        logger.warning(
            "GET %s → 404 (poke %d/%d), will retry",
            url,
            not_found_count,
            _NOT_FOUND_LIMIT,
        )
        return False

    resp.raise_for_status()
    data = resp.json()
    status = data.get("status")

    logger.info("market refresh run_id=%s status=%s", run_id, status)

    if status in TERMINAL_SUCCESS:
        return True
    if status in TERMINAL_FAILURE:
        raise RuntimeError(
            f"Market refresh failed — run_id={run_id} status={status} "
            f"done={data.get('symbols_done')} failed={data.get('symbols_failed')} "
            f"total={data.get('symbols_total')}"
        )
    # Still queued / running — keep poking
    return False


# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

default_args = {
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
    "email_on_retry": False,
}

with DAG(
    dag_id="warehouse_refresh",
    description="market refresh → dbt staging → dbt marts (trigger+sensor pattern)",
    schedule=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["dataeng", "warehouse"],
) as dag:

    trigger_market_refresh = PythonOperator(
        task_id="trigger_market_refresh",
        python_callable=_trigger_market_refresh,
        doc_md=(
            "POSTs to `POST /ops/scheduler/run/daily_market_refresh` on the running API. "
            "Creates a `market_refresh_run` row and enqueues the RQ job. "
            "Pushes `refresh_run_id` to XCom for the sensor. "
            "Raises AirflowSkipException when there are no active stocks."
        ),
    )

    wait_for_market_refresh = PythonSensor(
        task_id="wait_for_market_refresh",
        python_callable=_wait_for_market_refresh,
        poke_interval=30,
        timeout=7200,
        mode="reschedule",
        doc_md=(
            "GETs `GET /market-data/refresh/{refresh_run_id}` every 30 s until terminal. "
            "Terminal success: `succeeded` or `partial`. "
            "Terminal failure: `failed` → raises, halting the DAG. "
            "Uses `mode=reschedule` to free the worker slot between pokes."
        ),
    )

    dbt_deps = BashOperator(
        task_id="dbt_deps",
        bash_command=f"{DBT_BASE} deps {DBT_FLAGS}",
        doc_md="Installs dbt package dependencies (dbt_utils). Idempotent — safe to always run.",
    )

    dbt_run_staging = BashOperator(
        task_id="dbt_run_staging",
        bash_command=f"{DBT_BASE} run --select staging {DBT_FLAGS}",
        doc_md="Builds all staging views (`analytics_staging` schema) from the raw app tables.",
    )

    dbt_test_staging = BashOperator(
        task_id="dbt_test_staging",
        bash_command=f"{DBT_BASE} test --select staging {DBT_FLAGS}",
        doc_md=(
            "Runs all dbt tests on the staging layer. "
            "If any test fails here, marts are NOT built (gate)."
        ),
    )

    dbt_run_marts = BashOperator(
        task_id="dbt_run_marts",
        bash_command=f"{DBT_BASE} run --select marts {DBT_FLAGS}",
        doc_md="Builds the gold star schema (`analytics_marts`): dims + incremental fact tables.",
    )

    dbt_test_marts = BashOperator(
        task_id="dbt_test_marts",
        bash_command=f"{DBT_BASE} test --select marts {DBT_FLAGS}",
        doc_md=(
            "Validates the marts layer (not-null, unique, relationships, accepted-range). "
            "A failure here halts the DAG — downstream does NOT run."
        ),
    )

    dbt_source_freshness = BashOperator(
        task_id="dbt_source_freshness",
        # `|| true` makes this a soft-fail: freshness warnings/errors are logged but
        # do not fail the DAG or prevent it from being marked green.
        bash_command=f"{DBT_BASE} source freshness {DBT_FLAGS} || true",
        doc_md=(
            "Checks source freshness (informational, soft-fail). "
            "Exits 0 regardless of freshness outcome so the DAG always goes green here."
        ),
    )

    # Wire the task graph
    (
        trigger_market_refresh
        >> wait_for_market_refresh
        >> dbt_deps
        >> dbt_run_staging
        >> dbt_test_staging
        >> dbt_run_marts
        >> dbt_test_marts
        >> dbt_source_freshness
    )
