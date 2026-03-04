# services/worker/tasks/parallel_opt.py
"""
Parent-side orchestrator for parallel optimisation.

Called from execute_run when spec_json["optimization"]["parallel"] == True.
Imports are lazy (inside the function) to avoid circular dependencies at module load time.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import logging
import math
import time
import uuid as _uuid_mod
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("quant.parallel_opt")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def run_parallel_optimization(
    *,
    db: Session,
    rid: UUID,
    job_id: str | None,
    spec_json: dict[str, Any],
    dataset_hash: str | None,
    dataset_id,
    dataset_meta: dict[str, Any],
    cancel_redis,
    set_progress_fn,
    check_cancel_fn,
    persist_pipeline_output_fn,
) -> None:
    """
    Fan-out parent:
      1. Generate all candidates (grid or random).
      2. Chunk them into lists of chunk_size.
      3. Create OptTask rows, enqueue child RQ jobs respecting max_in_flight.
      4. Poll until all children done (fail fast on any child failure).
      5. Aggregate chunk Top-K → global Top-K via heap merge.
      6. Persist merged leaderboard on run.leaderboard_json.
      7. Re-run global best candidate(s) in full mode (fast_mode=False) for artifacts.
    """
    from rq import Queue as _RQQueue
    from rq.job import Job as _RQJob
    from redis import Redis as _Redis

    from core.quant_core.optimize import (
        STRATEGY_ADAPTERS,
        _iter_grid,
        _iter_random,
        default_param_catalog,
        ParamDef,
    )
    from core.quant_core.pipeline import run_pipeline as _run_pipeline
    from services.worker.config import settings
    from services.worker.tasks.evaluate_chunk import evaluate_chunk

    optimization_json = spec_json.get("optimization", {})
    chunk_size = int(optimization_json.get("chunk_size", 100))
    max_in_flight = int(optimization_json.get("max_in_flight", 4))
    top_k = int(optimization_json.get("top_k", 20))
    top_n_artifacts = int(optimization_json.get("top_n_artifacts", 1))
    rank_metric = str(optimization_json.get("rank_metric", "pnl"))
    n_trials = int(optimization_json.get("n_trials", 300))
    opt_method = str(optimization_json.get("method", "random")).lower()
    seed = int(optimization_json.get("seed", 42))

    strategy_json = spec_json.get("strategy", {})
    data_json = spec_json.get("data", {})
    symbols = list(spec_json.get("symbols") or data_json.get("symbols") or [])
    strategy_kind = str(strategy_json.get("kind", "sma_price")).lower()

    if strategy_kind not in STRATEGY_ADAPTERS:
        raise ValueError(f"No StrategyAdapter for strategy kind '{strategy_kind}'")

    # ── 1. Generate candidates ─────────────────────────────────────────────────
    domains_by_kind = dict(optimization_json.get("domains_by_kind") or {})
    catalog = default_param_catalog(strategy_kind)
    custom = domains_by_kind.get(strategy_kind)
    if custom and isinstance(custom, dict):
        for key, dom in custom.items():
            if key in catalog:
                p = catalog[key]
                catalog[key] = ParamDef(
                    key=p.key, kind=p.kind, domain=dom, cast=p.cast, enabled=True
                )
    active_params = [p for p in catalog.values() if p.enabled]

    if opt_method == "grid":
        all_candidates = list(_iter_grid(active_params))
    else:
        all_candidates = list(
            _iter_random(active_params, n_trials=n_trials, seed=seed)
        )

    if not all_candidates:
        raise RuntimeError("Parallel optimisation: no candidates generated.")

    total_candidates = len(all_candidates)
    set_progress_fn(
        db, rid, job_id,
        stage="parallel_opt",
        pct=1,
        message=(
            f"Parallel opt: {total_candidates} candidates, "
            f"chunk_size={chunk_size}, max_in_flight={max_in_flight}"
        ),
    )

    # ── 2. Chunk candidates ────────────────────────────────────────────────────
    chunks = [
        all_candidates[i: i + chunk_size]
        for i in range(0, total_candidates, chunk_size)
    ]
    n_chunks = len(chunks)
    fold_id = "0"

    # ── 3. Create OptTask rows ─────────────────────────────────────────────────
    spec_hash_val = hashlib.sha256(
        json.dumps(spec_json, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    opt_task_ids: list[str] = []
    for chunk_idx in range(n_chunks):
        task_id = str(_uuid_mod.uuid4())
        opt_task_ids.append(task_id)
        db.execute(
            text(
                """
                insert into opt_task(id, run_id, fold_id, chunk_id, status,
                                     params_count, spec_hash, attempt)
                values (:id, :run_id, :fold_id, :chunk_id, 'queued',
                        :params_count, :spec_hash, 1)
                on conflict do nothing
                """
            ),
            {
                "id": task_id,
                "run_id": str(rid),
                "fold_id": fold_id,
                "chunk_id": chunk_idx,
                "params_count": len(chunks[chunk_idx]),
                "spec_hash": spec_hash_val,
            },
        )
    db.commit()

    # ── 4. Enqueue with max_in_flight throttle ─────────────────────────────────
    redis_conn = _Redis.from_url(settings.REDIS_URL, decode_responses=False)
    q = _RQQueue(settings.RUNS_QUEUE_NAME, connection=redis_conn)

    # Resolve dataset object_key for child workers (for MinIO download)
    ds_object_key: str | None = None
    if dataset_id:
        ds_row = db.execute(
            text("select object_key from dataset where id = :id"),
            {"id": dataset_id},
        ).mappings().first()
        if ds_row and ds_row.get("object_key"):
            ds_object_key = str(ds_row["object_key"])

    chunk_to_rq_job: dict[int, str] = {}
    in_flight: set[int] = set()
    pending_chunks: list[int] = list(range(n_chunks))
    failed_chunks: list[str] = []
    done_chunks = 0

    def _enqueue(chunk_idx: int) -> None:
        rq_job = q.enqueue(
            evaluate_chunk,
            kwargs=dict(
                run_id=str(rid),
                fold_id=fold_id,
                chunk_id=chunk_idx,
                opt_task_id=opt_task_ids[chunk_idx],
                spec_json=spec_json,
                candidates=chunks[chunk_idx],
                top_k=top_k,
                rank_metric=rank_metric,
                dataset_hash=dataset_hash,
                dataset_object_key=ds_object_key,
            ),
            job_timeout=3600,
            result_ttl=600,
        )
        chunk_to_rq_job[chunk_idx] = rq_job.id
        db.execute(
            text("update opt_task set worker_job_id=:jid where id=:tid"),
            {"jid": rq_job.id, "tid": opt_task_ids[chunk_idx]},
        )
        db.commit()
        in_flight.add(chunk_idx)
        logger.debug("Enqueued chunk %d as rq job %s", chunk_idx, rq_job.id)

    # Fill up to max_in_flight
    while pending_chunks and len(in_flight) < max_in_flight:
        _enqueue(pending_chunks.pop(0))

    # Poll loop
    while in_flight or pending_chunks:
        check_cancel_fn(cancel_redis, job_id)
        time.sleep(2.0)

        finished_now: set[int] = set()
        for chunk_idx in list(in_flight):
            rq_jid = chunk_to_rq_job.get(chunk_idx)
            if not rq_jid:
                continue
            try:
                rq_obj = _RQJob.fetch(rq_jid, connection=redis_conn)
                status = rq_obj.get_status()
            except Exception:
                status = "unknown"

            if status in ("finished", "stopped"):
                finished_now.add(chunk_idx)
                done_chunks += 1
                logger.debug("Chunk %d succeeded (rq job %s)", chunk_idx, rq_jid)
            elif status == "failed":
                finished_now.add(chunk_idx)
                done_chunks += 1
                task_row = db.execute(
                    text("select error_message from opt_task where id=:id"),
                    {"id": opt_task_ids[chunk_idx]},
                ).mappings().first()
                err_detail = (
                    task_row.get("error_message") or "unknown"
                ) if task_row else "unknown"
                failed_chunks.append(f"chunk {chunk_idx}: {err_detail[:300]}")
                logger.error("Chunk %d FAILED: %s", chunk_idx, err_detail[:200])

        in_flight -= finished_now

        # Enqueue pending up to max_in_flight
        while pending_chunks and len(in_flight) < max_in_flight:
            _enqueue(pending_chunks.pop(0))

        pct = int(5 + 80 * done_chunks / max(n_chunks, 1))
        set_progress_fn(
            db, rid, job_id,
            stage="parallel_opt",
            done=done_chunks,
            total=n_chunks,
            pct=min(pct, 85),
            message=f"Chunks done: {done_chunks}/{n_chunks}",
        )

        if failed_chunks:
            raise RuntimeError(
                "Parallel optimisation chunk(s) failed:\n" + "\n".join(failed_chunks)
            )

    # ── 5. Aggregate chunk Top-K → global Top-K ────────────────────────────────
    global_heap: list = []

    def _entry_score(entry: dict) -> float:
        for k in ("score", rank_metric, "pnl"):
            v = entry.get(k)
            if v is not None:
                try:
                    fv = float(v)
                    if math.isfinite(fv):
                        return fv
                except Exception:
                    pass
        return float("-inf")

    for chunk_idx in range(n_chunks):
        row = db.execute(
            text(
                "select topk_json from opt_result "
                "where run_id=:run_id and fold_id=:fold_id and chunk_id=:chunk_id"
            ),
            {"run_id": str(rid), "fold_id": fold_id, "chunk_id": chunk_idx},
        ).mappings().first()
        if not row:
            continue
        topk_list = row.get("topk_json") or []
        if isinstance(topk_list, str):
            topk_list = json.loads(topk_list)
        for entry in topk_list:
            s = _entry_score(entry)
            heapq.heappush(global_heap, (s, id(entry), entry))
            if len(global_heap) > top_k:
                heapq.heappop(global_heap)

    global_topk = [
        entry
        for _, _, entry in sorted(global_heap, key=lambda x: -x[0])
    ]

    # ── 6. Persist merged leaderboard on run ───────────────────────────────────
    leaderboard_payload = json.dumps(
        {"global": global_topk, "rank_metric": rank_metric, "top_k": top_k},
        default=str,
    )
    db.execute(
        text("update run set leaderboard_json=cast(:lb as jsonb) where id=:id"),
        {"lb": leaderboard_payload, "id": rid},
    )
    db.commit()

    set_progress_fn(
        db, rid, job_id,
        stage="parallel_opt_artifacts",
        pct=87,
        message=(
            f"Global top-{len(global_topk)} aggregated. "
            f"Re-running best {top_n_artifacts} candidate(s) for full artifacts."
        ),
    )

    # ── 7. Re-run best candidate(s) in full mode ──────────────────────────────
    default_symbol = str(symbols[0]) if symbols else "__ALL__"

    for rank_i in range(min(top_n_artifacts, len(global_topk))):
        best_entry = global_topk[rank_i]
        best_params = dict(best_entry.get("params") or {})

        # Patch spec_json with the winning params
        patched = json.loads(json.dumps(spec_json, default=str))
        patched.setdefault("strategy", {}).setdefault("params", {})
        patched.setdefault("portfolio", {})
        for k, v in best_params.items():
            if k.startswith("strategy."):
                patched["strategy"]["params"][k[len("strategy."):]] = v
            elif k.startswith("portfolio."):
                patched["portfolio"][k[len("portfolio."):]] = v
        # Disable parallel flag to avoid recursion
        patched.setdefault("optimization", {})["parallel"] = False

        try:
            out = _run_pipeline(patched)
            persist_pipeline_output_fn(
                db=db,
                rid=rid,
                out=out,
                default_symbol=default_symbol,
                spec_json=patched,
                dataset_meta=dataset_meta,
                dataset_hash=dataset_hash,
            )
            db.commit()
        except Exception as full_err:
            logger.warning(
                "Full-mode re-run rank=%d failed (non-fatal): %s", rank_i + 1, full_err
            )
