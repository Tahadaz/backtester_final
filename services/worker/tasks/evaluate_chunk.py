# services/worker/tasks/evaluate_chunk.py
"""
Child RQ task: evaluate a chunk of optimisation candidates.

Contract
--------
* Marks OptTask as running → succeeded | failed.
* Loads dataset via MinIO once, caches the raw DataFrame in-process (LRU maxsize=4,
  keyed by dataset_hash, NOT run_id).
* Evaluates every candidate with the fast-path optimiser internals (no engine.run, no
  BacktestEngine, no plots, no ledgers).
* Keeps at most `top_k` results in a min-heap.
* UPSERTs OptResult.topk_json (array of ≤ K dicts) keyed by (run_id, fold_id, chunk_id).
* Does NOT write any MinIO artifact.
* Safe to retry: UPSERT is idempotent.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import logging
import math
import time
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.worker.db import SessionLocal
from services.worker.storage import s3_client

log = logging.getLogger("quant.evaluate_chunk")


# ── in-process LRU dataset cache (raw DataFrame) ──────────────────────────────
# Key: dataset_hash (stable, content-addressed)
# Value: Path to the local temp file that was already materialised
# We store the path so the child never re-downloads the same file.

_DATASET_PATH_CACHE: dict[str, str] = {}
_DATASET_CACHE_MAX = 4


def _evict_lru_if_needed() -> None:
    while len(_DATASET_PATH_CACHE) >= _DATASET_CACHE_MAX:
        oldest_key = next(iter(_DATASET_PATH_CACHE))
        _DATASET_PATH_CACHE.pop(oldest_key, None)
        log.debug("dataset_path_cache evicted key=%s", oldest_key)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_dumps_safe(payload: Any) -> str:
    def _default(v: Any) -> Any:
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        raise TypeError(f"Object of type {type(v)} is not JSON serialisable")

    return json.dumps(payload, default=_default, ensure_ascii=False)


def _score_for_ranking(entry: dict[str, Any], rank_metric: str) -> float:
    """Return the numeric score used to rank candidates (higher = better)."""
    metric_aliases: dict[str, list[str]] = {
        "pnl": ["pnl"],
        "cagr": ["cagr"],
        "sharpe": ["sharpe"],
        "total_return": ["total_return"],
        "efficiency": ["efficiency"],
        "n_fills": ["n_fills"],
        "max_drawdown": ["max_drawdown"],
    }
    key = str(rank_metric).strip().lower()
    candidates = metric_aliases.get(key, [key])
    for c in candidates:
        v = entry.get(c)
        if v is not None:
            try:
                fv = float(v)
                if math.isfinite(fv):
                    return fv
            except Exception:
                pass
    # Fall back to pnl if metric not found
    return float(entry.get("pnl", float("-inf")))


# ── heap helpers ──────────────────────────────────────────────────────────────
# We keep a min-heap of (score, entry) so we can efficiently maintain top-K.

def _topk_insert(heap: list, entry: dict[str, Any], score: float, k: int) -> None:
    """Insert entry into min-heap, ejecting the smallest if len > k."""
    heapq.heappush(heap, (score, id(entry), entry))
    if len(heap) > k:
        heapq.heappop(heap)


def _heap_to_topk(heap: list) -> list[dict[str, Any]]:
    """Return top-K list sorted best-first."""
    return [entry for _, _, entry in sorted(heap, key=lambda x: -x[0])]


# ── main task ─────────────────────────────────────────────────────────────────

def evaluate_chunk(
    *,
    run_id: str,
    fold_id: str,
    chunk_id: int,
    opt_task_id: str,
    spec_json: dict[str, Any],
    candidates: list[dict[str, Any]],
    top_k: int = 20,
    rank_metric: str = "pnl",
    dataset_hash: str | None = None,
    dataset_object_key: str | None = None,
) -> dict[str, Any]:
    """
    RQ entry-point.  All arguments are JSON-serialisable so they survive
    RQ's pickle/unpickle cycle.
    """
    db: Session = SessionLocal()
    rid = uuid.UUID(run_id)
    tid = uuid.UUID(opt_task_id)

    try:
        # ── 1. Mark running ───────────────────────────────────────────────────
        now = _utcnow()
        db.execute(
            text(
                """
                update opt_task
                set status     = 'running',
                    started_at = :ts
                where id = :id
                  and status not in ('succeeded', 'canceled')
                """
            ),
            {"ts": now, "id": tid},
        )
        db.commit()

        # ── 2. Load dataset (with LRU cache on dataset_hash) ──────────────────
        local_path: str | None = None
        if dataset_hash:
            cache_hit = dataset_hash in _DATASET_PATH_CACHE
            if cache_hit:
                local_path = _DATASET_PATH_CACHE[dataset_hash]
                log.debug(
                    "dataset_path_cache HIT  hash=%s path=%s chunk=%s/%s",
                    dataset_hash[:8],
                    local_path,
                    run_id,
                    chunk_id,
                )
            else:
                log.debug(
                    "dataset_path_cache MISS hash=%s chunk=%s/%s",
                    dataset_hash[:8] if dataset_hash else "None",
                    run_id,
                    chunk_id,
                )
                if dataset_object_key:
                    import tempfile, os
                    s3 = s3_client()
                    from services.worker.config import settings

                    suffix = os.path.splitext(dataset_object_key)[1] or ".bin"
                    tmp = tempfile.NamedTemporaryFile(
                        suffix=suffix, delete=False, prefix="chunk_ds_"
                    )
                    tmp.close()
                    s3.download_file(settings.S3_BUCKET, dataset_object_key, tmp.name)
                    local_path = tmp.name
                    _evict_lru_if_needed()
                    _DATASET_PATH_CACHE[dataset_hash] = local_path

        # ── 3. Evaluate candidates ────────────────────────────────────────────
        # We use quant_core's internal fast-path: build the EngineSpec from spec_json,
        # then run the fast stats-only path for each candidate.
        # This avoids duplicating optimisation logic and keeps quant_core "pure".

        from core.quant_core.optimize import (
            STRATEGY_ADAPTERS,
            _align_marketdata_inner,
            _eval_one_trial,
            _load_market_data_from_spec,
            _slice_index,
            _trial_params_key,
            build_bank,
        )
        from core.quant_core.engine import estimate_warmup_bars_from_params
        from core.quant_core.engine import (
            DataConfig,
            EngineSpec,
            IndicatorsConfig,
            StrategyConfig,
        )
        from core.quant_core.portfolio import CostModel, PortfolioConfig, PortfolioEngine
        from dataclasses import replace
        import numpy as np
        import pandas as pd

        # Build base_spec from spec_json (reuse pipeline's parsing logic)
        data_json = spec_json.get("data", {})
        portfolio_json = spec_json.get("portfolio", {})
        strategy_json = spec_json.get("strategy", {})
        optimization_json = spec_json.get("optimization", {})

        symbols = list(spec_json.get("symbols") or data_json.get("symbols") or [])

        # Patch in the local dataset path if we downloaded it
        if local_path:
            import os

            ext = os.path.splitext(local_path)[1].lower()
            if ext == ".parquet":
                # Expect parquet paths dict or single path
                data_json = dict(data_json)
                data_json["parquet_paths"] = local_path
            else:
                data_json = dict(data_json)
                data_json["source"] = "bmce"
                data_json["bmce_paths"] = local_path

        cost_model_cfg = CostModel(
            brokerage_bps=float(portfolio_json.get("cost_model", {}).get("brokerage_bps", 0.2)),
            comm_bourse_bps=float(portfolio_json.get("cost_model", {}).get("comm_bourse_bps", 0.1)),
            reg_liv_bps=float(portfolio_json.get("cost_model", {}).get("reg_liv_bps", 0.0)),
            slippage_bps=float(portfolio_json.get("cost_model", {}).get("slippage_bps", 0.0)),
            tva_rate=float(portfolio_json.get("cost_model", {}).get("tva_rate", 3e-4)),
        )

        portfolio_cfg = PortfolioConfig(
            allow_short=bool(portfolio_json.get("allow_short", True)),
            initial_cash=float(portfolio_json.get("initial_cash", 100_000.0)),
            rebalance_policy=str(portfolio_json.get("rebalance_policy", "on_change")),
            sizing_mode=str(portfolio_json.get("sizing_mode", "target_weight")),
            buy_pct_cash=float(portfolio_json.get("buy_pct_cash", 1.0)),
            sell_pct_shares=float(portfolio_json.get("sell_pct_shares", 1.0)),
            cooldown_bars=int(portfolio_json.get("cooldown_bars", 0)),
            min_return_before_sell=float(portfolio_json.get("min_return_before_sell", 0.0)),
            use_volume_gate=bool(portfolio_json.get("volume_gate", {}).get("enabled", False)),
            volume_gate_kind=str(portfolio_json.get("volume_gate", {}).get("kind", "min_ratio_adv")),
            min_volume_abs=float(portfolio_json.get("volume_gate", {}).get("min_volume_abs", 0.0)),
            min_volume_ratio_adv=float(portfolio_json.get("volume_gate", {}).get("min_volume_ratio_adv", 0.1)),
            volume_gate_adv_window=int(portfolio_json.get("volume_gate", {}).get("adv_window", 20)),
            use_participation_cap=bool(portfolio_json.get("participation_cap", {}).get("enabled", False)),
            participation_rate=float(portfolio_json.get("participation_cap", {}).get("rate", 0.05)),
            participation_basis=str(portfolio_json.get("participation_cap", {}).get("basis", "adv")),
            adv_window=int(portfolio_json.get("participation_cap", {}).get("adv_window", 20)),
            cost_model=cost_model_cfg,
        )

        data_cfg = DataConfig(
            source=str(spec_json.get("source_key") or data_json.get("source") or "bmce"),
            symbols=symbols,
            timezone=str(data_json.get("timezone", "GMT")),
            interval=str(data_json.get("interval", "1d")),
            start=data_json.get("start"),
            end=data_json.get("end"),
            periods=(int(data_json["periods"]) if data_json.get("periods") is not None else None),
            freq=str(data_json.get("freq", "B")),
            bmce_paths=data_json.get("bmce_paths"),
            parquet_paths=data_json.get("parquet_paths"),
            yf_period=str(data_json.get("yf_period", "max")),
            yf_interval=str(data_json.get("yf_interval", "1d")),
            yf_auto_adjust=bool(data_json.get("yf_auto_adjust", False)),
            synthetic=dict(data_json.get("synthetic") or {}),
        )

        strategy_cfg = StrategyConfig(
            kind=str(strategy_json.get("kind", "sma_price")),
            params=dict(strategy_json.get("params") or {}),
        )

        indicators_cfg = IndicatorsConfig(
            specs=None,
            cache_dir=".cache/features",
            enable_disk_cache=False,
            enable_memory_cache=True,
            engine_version="v1",
        )

        base_spec = EngineSpec(
            data=data_cfg,
            indicators=indicators_cfg,
            strategy=strategy_cfg,
            portfolio=portfolio_cfg,
            periods_per_year=int(spec_json.get("periods_per_year", 252)),
            rf_annual=float(spec_json.get("rf_annual", 0.0)),
        )

        strategy_kind = base_spec.strategy.kind.lower()
        if strategy_kind not in STRATEGY_ADAPTERS:
            raise ValueError(
                f"No StrategyAdapter for strategy kind '{strategy_kind}'"
            )
        adapter = STRATEGY_ADAPTERS[strategy_kind]

        # Build feature bank once (same as run_optimization)
        from core.quant_core.optimize import ParamDef  # reuse type

        # We receive raw candidate dicts; convert keys to ParamDef list for bank building
        # Use an empty active_params so bank is built for spec defaults only
        _active_params: list[ParamDef] = []
        warmup_pad = 0

        load_cfg = data_cfg
        if data_cfg.start and warmup_pad > 0:
            start_dt = pd.to_datetime(data_cfg.start)
            pad_start = start_dt - pd.tseries.offsets.BDay(int(warmup_pad))
            load_cfg = replace(load_cfg, start=pad_start.date().isoformat())

        md_full = _load_market_data_from_spec(load_cfg)
        md = _align_marketdata_inner(md_full, symbols)

        if not symbols:
            raise ValueError("No symbols in spec_json.symbols")

        common_index = md.bars[symbols[0]].index
        if len(common_index) < 2:
            raise ValueError("Not enough bars after alignment.")

        need_volume = bool(
            base_spec.portfolio.use_participation_cap
            or base_spec.portfolio.use_volume_gate
            or strategy_kind in ("obv", "stoch_vwap")
        )

        bars_open: dict[str, np.ndarray] = {}
        bars_close: dict[str, np.ndarray] = {}
        bars_high: dict[str, np.ndarray] = {}
        bars_low: dict[str, np.ndarray] = {}
        bars_vol: dict[str, np.ndarray] = {}

        for s in symbols:
            b = md.bars[s].reindex(common_index)
            bars_open[s] = b["Open"].to_numpy(dtype=np.float64, copy=False)
            bars_close[s] = b["Close"].to_numpy(dtype=np.float64, copy=False)
            bars_high[s] = b["High"].to_numpy(dtype=np.float64, copy=False)
            bars_low[s] = b["Low"].to_numpy(dtype=np.float64, copy=False)
            if need_volume:
                vcol = base_spec.portfolio.volume_col
                bars_vol[s] = b[vcol].to_numpy(dtype=np.float64, copy=False)

        req = adapter.required_bank(base_spec, _active_params)
        bank = build_bank(bars_close, bars_high, bars_low, bars_vol, req)

        # Slice to eval window
        eval_index = _slice_index(common_index, data_cfg.start, data_cfg.end)
        if eval_index is None or len(eval_index) < 2:
            raise ValueError("Not enough bars after slicing to eval window.")

        if len(eval_index) != len(common_index):
            idx_pos = common_index.get_indexer_for(eval_index)
            common_index = eval_index
            for s in symbols:
                bars_open[s] = bars_open[s][idx_pos]
                bars_close[s] = bars_close[s][idx_pos]
                bars_high[s] = bars_high[s][idx_pos]
                bars_low[s] = bars_low[s][idx_pos]
                if need_volume:
                    bars_vol[s] = bars_vol[s][idx_pos]
                bank[s] = {k: v[idx_pos] for k, v in bank[s].items()}

        # Build ADV arrays
        adv_by_window_np: dict[int, dict[str, np.ndarray]] = {}
        if need_volume:
            adv_windows = []
            if base_spec.portfolio.use_participation_cap and str(base_spec.portfolio.participation_basis) == "adv":
                adv_windows.append(int(base_spec.portfolio.adv_window))
            if base_spec.portfolio.use_volume_gate and str(base_spec.portfolio.volume_gate_kind) == "min_ratio_adv":
                adv_windows.append(int(base_spec.portfolio.volume_gate_adv_window))
            adv_windows = sorted(set(w for w in adv_windows if w >= 1))
            for w in adv_windows:
                adv_by_window_np[w] = {}
                for s in symbols:
                    v = bars_vol[s]
                    c = np.cumsum(np.insert(v, 0, 0.0))
                    adv = np.empty_like(v)
                    idx = np.arange(v.size)
                    lo = np.maximum(0, idx - (w - 1))
                    den = (idx - lo + 1).astype(np.float64)
                    adv[:] = (c[idx + 1] - c[lo]) / den
                    adv_by_window_np[w][s] = adv

        # Pre-hoist PortfolioEngine if no portfolio params vary
        _PORT_PARAM_KEYS = frozenset(
            ("portfolio.cooldown_bars", "portfolio.buy_pct_cash", "portfolio.sell_pct_shares")
        )
        all_candidate_keys = set()
        for cand in candidates:
            all_candidate_keys.update(cand.keys())
        precomputed_port: PortfolioEngine | None = None
        if not (all_candidate_keys & _PORT_PARAM_KEYS):
            precomputed_port = PortfolioEngine(base_spec.portfolio)

        # ── 4. Evaluate each candidate, maintain min-heap of top-K ───────────
        heap: list = []
        eval_cache: dict[str, dict] = {}

        initial_cash = float(base_spec.portfolio.initial_cash)
        n_bars = len(common_index)
        ppy = float(getattr(base_spec, "periods_per_year", 252))

        for params in candidates:
            params_key = _trial_params_key(params)
            if params_key in eval_cache:
                entry = eval_cache[params_key]
                score = _score_for_ranking(entry, rank_metric)
                _topk_insert(heap, entry, score, top_k)
                continue

            ok, err = adapter.validate_params(params, base_spec)
            if not ok:
                entry = {
                    "params": params,
                    "params_hash": params_key,
                    "pnl": float("-inf"),
                    "cagr": float("-inf"),
                    "efficiency": float("-inf"),
                    "n_fills": 0,
                    "score": float("-inf"),
                    "error": err or "invalid params",
                }
                eval_cache[params_key] = entry
                # Don't insert invalid into top-K heap
                continue

            trial = _eval_one_trial(
                base_spec=base_spec,
                md=md,
                common_index=common_index,
                bank=bank,
                bars_open=bars_open,
                bars_close=bars_close,
                bars_high=bars_high,
                bars_low=bars_low,
                bars_vol=bars_vol,
                adv_by_window_np=adv_by_window_np,
                adapter=adapter,
                params=params,
                precomputed_port=precomputed_port,
            )

            # Compute CAGR
            E0 = initial_cash
            ET = E0 + float(trial.pnl)
            if n_bars > 1 and E0 > 0 and ET > 0:
                cagr = float((ET / E0) ** (ppy / n_bars) - 1.0)
            else:
                cagr = float("-inf")

            entry = {
                "params": trial.params,
                "params_hash": params_key,
                "pnl": float(trial.pnl),
                "cagr": cagr,
                "efficiency": float(trial.efficiency),
                "n_fills": int(trial.n_fills),
                "traded_notional": float(trial.traded_notional),
                "score": 0.0,  # filled below
                "error": trial.error,
            }
            score = _score_for_ranking(entry, rank_metric)
            entry["score"] = score
            eval_cache[params_key] = entry

            if trial.error is None or trial.error == "":
                _topk_insert(heap, entry, score, top_k)

        topk = _heap_to_topk(heap)

        # ── 5. UPSERT OptResult ────────────────────────────────────────────────
        topk_payload = _json_dumps_safe(topk)
        result_id = str(uuid.uuid4())
        db.execute(
            text(
                """
                insert into opt_result(id, run_id, fold_id, chunk_id, topk_json)
                values (:id, :run_id, :fold_id, :chunk_id, cast(:topk_json as jsonb))
                on conflict (run_id, fold_id, chunk_id)
                do update set
                    topk_json  = excluded.topk_json,
                    created_at = now()
                """
            ),
            {
                "id": result_id,
                "run_id": str(rid),
                "fold_id": fold_id,
                "chunk_id": chunk_id,
                "topk_json": topk_payload,
            },
        )

        # ── 6. Mark OptTask succeeded ─────────────────────────────────────────
        db.execute(
            text(
                """
                update opt_task
                set status      = 'succeeded',
                    finished_at = now()
                where id = :id
                """
            ),
            {"id": tid},
        )
        db.commit()

        log.info(
            "evaluate_chunk OK  run=%s fold=%s chunk=%s  candidates=%d  topk=%d",
            run_id,
            fold_id,
            chunk_id,
            len(candidates),
            len(topk),
        )
        return {
            "status": "succeeded",
            "run_id": run_id,
            "fold_id": fold_id,
            "chunk_id": chunk_id,
            "n_candidates": len(candidates),
            "topk": len(topk),
        }

    except Exception as exc:
        import traceback

        err_msg = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[:8000]
        log.error(
            "evaluate_chunk FAILED run=%s fold=%s chunk=%s: %s",
            run_id,
            fold_id,
            chunk_id,
            err_msg[:300],
        )
        try:
            db.rollback()
        except Exception:
            pass
        try:
            db.execute(
                text(
                    """
                    update opt_task
                    set status        = 'failed',
                        finished_at   = now(),
                        error_message = :err
                    where id = :id
                    """
                ),
                {"id": tid, "err": err_msg},
            )
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        raise  # re-raise so RQ marks the job failed

    finally:
        db.close()
