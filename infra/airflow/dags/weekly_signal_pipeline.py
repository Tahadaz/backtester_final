"""
weekly_signal_pipeline DAG
==========================
Orchestrates the full weekly signal batch in dependency order:

    trigger_fundamental_refresh → wait_fundamental_refresh
            ▼
    trigger_wfo_dispatch → wait_wfo_dispatch
            ▼
    trigger_signal_backtest_dispatch → wait_signal_backtest_dispatch
            ▼
    trigger_best_evidence_snapshot → wait_best_evidence_snapshot
            ▼
    trigger_dashboard_snapshot → wait_dashboard_snapshot   (maintenance tail)

Note: Signal Engine recompute is no longer a standalone weekly step — it now
piggybacks on the Friday daily_market_refresh run (see
_enqueue_signal_layers_after_refresh in refresh_market_data.py) and is not
part of this DAG.

Design:
- Each trigger_* = PythonOperator POSTing to POST /ops/scheduler/run/{schedule_id},
  pushing the returned scheduler_run id to XCom.
- Each wait_* = PythonSensor (mode=reschedule) polling GET /ops/scheduler/run/{run_id}
  until terminal; raises on failure so downstream steps do not run.
- Mirrors warehouse_refresh.py exactly: HTTP-trigger + sensor-poll, no app library
  imports, no SQLAlchemy, no RQ — only the `requests` library (bundled with Airflow).
- schedule=None for Phase 1 (manual trigger only). Once a manual run is verified
  green end-to-end, set the weekly cron and remove the corresponding APScheduler
  entries from scheduler_registry.py (Phase 2 — do NOT do this yet).
- max_active_runs=1 prevents concurrent signal pipeline runs.
- retries=1 + on_failure_callback for alerting.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any

from airflow import DAG
from airflow.exceptions import AirflowSkipException
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

API_BASE = os.environ.get("API_BASE_URL", "http://quant_api:8000")

_ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "").strip()
_API_KEY = os.environ.get("API_KEY", "").strip()

TERMINAL_SUCCESS = {"succeeded", "partial"}
TERMINAL_FAILURE = {"failed"}

# Consecutive 404s on a run row before treating it as a hard error.
_NOT_FOUND_LIMIT = 5

# ---------------------------------------------------------------------------
# Generic trigger + sensor callables
# ---------------------------------------------------------------------------


def _trigger_schedule(schedule_id: str, **ctx: Any) -> None:
    """POST /ops/scheduler/run/{schedule_id} and push run_id to XCom."""
    import requests

    headers = {"X-Admin-Api-Key": _ADMIN_API_KEY} if _ADMIN_API_KEY else {}
    resp = requests.post(
        f"{API_BASE}/ops/scheduler/run/{schedule_id}",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    res = resp.json()

    if res.get("status") == "failed":
        raise RuntimeError(f"dispatch failed for {schedule_id!r}: {res.get('error')}")

    run_id = res.get("scheduler_run_id") or res.get("run_id") or res.get("id")
    if not run_id:
        reason = res.get("reason", "no run id returned")
        logger.info("Skipping sensor for %s: %s", schedule_id, reason)
        raise AirflowSkipException(reason)

    logger.info("Dispatched %s — run_id=%s", schedule_id, run_id)
    ctx["ti"].xcom_push(key="run_id", value=run_id)


def _wait_for_schedule(trigger_task_id: str, **ctx: Any) -> bool:
    """Poll GET /ops/scheduler/run/{run_id} until terminal.

    Returns True on success (succeeded / partial).
    Raises RuntimeError on failure — halts the DAG.
    Returns False to keep poking (queued / running / 404 below limit).
    """
    import requests

    ti = ctx["ti"]
    run_id = ti.xcom_pull(task_ids=trigger_task_id, key="run_id")
    if not run_id:
        raise ValueError(
            f"run_id not found in XCom from {trigger_task_id!r} — "
            "trigger task may have been skipped"
        )

    headers = {"X-API-Key": _API_KEY} if _API_KEY else {}
    url = f"{API_BASE}/ops/scheduler/run/{run_id}"
    resp = requests.get(url, headers=headers, timeout=10)

    if resp.status_code == 404:
        not_found_count = (
            ti.xcom_pull(task_ids=ti.task_id, key="not_found_count") or 0
        ) + 1
        ti.xcom_push(key="not_found_count", value=not_found_count)
        if not_found_count >= _NOT_FOUND_LIMIT:
            raise RuntimeError(
                f"GET {url} returned 404 for {not_found_count} consecutive pokes — "
                f"scheduler_run row missing for id={run_id}"
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

    logger.info("scheduler_run run_id=%s status=%s", run_id, status)

    if status in TERMINAL_SUCCESS:
        return True
    if status in TERMINAL_FAILURE:
        raise RuntimeError(
            f"Scheduler run failed — run_id={run_id} status={status} "
            f"details={data.get('error') or data.get('detail')}"
        )
    return False


def _on_failure_alert(context: Any) -> None:
    """Minimal failure callback — logs the failure; extend with Slack/email as needed."""
    dag_id = context.get("dag").dag_id if context.get("dag") else "unknown"
    task_id = context.get("task_instance").task_id if context.get("task_instance") else "unknown"
    exception = context.get("exception")
    logger.error(
        "weekly_signal_pipeline FAILED — dag=%s task=%s exception=%s",
        dag_id,
        task_id,
        exception,
    )


# ---------------------------------------------------------------------------
# Schedule IDs (must match scheduler_registry.py)
# ---------------------------------------------------------------------------

_STEPS = [
    ("fundamental_refresh", "weekly_fundamental_refresh"),
    ("wfo_dispatch", "weekly_wfo_dispatch"),
    ("signal_backtest_dispatch", "weekly_signal_backtest_dispatch"),
    ("signal_history_dispatch", "weekly_signal_history_dispatch"),
    ("best_evidence_snapshot", "weekly_signal_best_evidence_snapshot"),
    ("dashboard_snapshot", "daily_dashboard_snapshot"),
]

# Per-step sensor timeout override. WFO's individual RQ jobs now carry a
# 24h job_timeout (see wfo_signal_batch.py), so the sensor waiting on the
# whole dispatch batch needs a matching ceiling — the other steps stay at
# the default 4h.
_STEP_SENSOR_TIMEOUT_SECONDS = {
    "wfo_dispatch": 90000,  # 25h: 24h max per job + 1h slack
}
_DEFAULT_SENSOR_TIMEOUT_SECONDS = 14400

# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

default_args = {
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
    "email_on_retry": False,
    "on_failure_callback": _on_failure_alert,
}

with DAG(
    dag_id="weekly_signal_pipeline",
    description=(
        "Weekly signal batch: fundamental refresh → WFO → signal engine → "
        "backtest → best-evidence snapshot → dashboard snapshot"
    ),
    schedule=None,  # Phase 1: manual only. Set weekly cron after a green run (Phase 2).
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["signals", "weekly"],
) as dag:

    previous_sensor = None
    for step_name, schedule_id in _STEPS:
        trigger_task_id = f"trigger_{step_name}"
        wait_task_id = f"wait_{step_name}"

        trigger = PythonOperator(
            task_id=trigger_task_id,
            python_callable=_trigger_schedule,
            op_kwargs={"schedule_id": schedule_id},
            doc_md=(
                f"POSTs to `POST /ops/scheduler/run/{schedule_id}`. "
                f"Pushes `run_id` to XCom for the sensor."
            ),
        )

        sensor = PythonSensor(
            task_id=wait_task_id,
            python_callable=_wait_for_schedule,
            op_kwargs={"trigger_task_id": trigger_task_id},
            poke_interval=60,
            timeout=_STEP_SENSOR_TIMEOUT_SECONDS.get(step_name, _DEFAULT_SENSOR_TIMEOUT_SECONDS),
            mode="reschedule",
            doc_md=(
                f"Polls `GET /ops/scheduler/run/{{run_id}}` every 60 s until terminal. "
                f"Raises on `failed` so downstream steps do not run."
            ),
        )

        trigger >> sensor

        if previous_sensor is not None:
            previous_sensor >> trigger

        previous_sensor = sensor
