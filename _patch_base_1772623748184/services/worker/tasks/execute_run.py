# services/worker/tasks/execute_run.py
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import gettempdir
from uuid import UUID, uuid4
from typing import Any
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
import copy
import logging
import traceback
import json
import hashlib
import math
import os
import subprocess
import time
import pandas as pd

logger = logging.getLogger(__name__)
from threading import Lock
from redis import Redis
from rq import get_current_job
from plotly.utils import PlotlyJSONEncoder

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from services.worker.db import SessionLocal
from services.worker.config import settings
from services.worker.storage import s3_client, ensure_bucket

from core.quant_core.pipeline import run_pipeline
from core.quant_core.s3_keys import build_dataset_object_key
from core.quant_core.integrity import build_integrity_report
from core.quant_core.mean_reversion import adf_test, cadf_cointegration, estimate_half_life
from core.quant_core.research.horizon import get_horizon_config
from core.quant_core.risk import build_risk_summary
from core.quant_core.significance import evaluate_significance
from core.quant_core.decision import (
    build_decision_page,
    compute_confidence_score,
    compute_levels_support_resistance,
    compute_opportunity_score,
    compute_rr_and_invalidation,
    deterministic_seed_from_key,
)


def _utcnow():
    return datetime.now(timezone.utc)


def _has_table(db: Session, table_name: str) -> bool:
    try:
        return inspect(db.get_bind()).has_table(table_name)
    except Exception:
        return False


def _table_columns(db: Session, table_name: str) -> set[str]:
    try:
        cols = inspect(db.get_bind()).get_columns(table_name)
        return {str(c.get("name") or "").strip() for c in cols if c.get("name")}
    except Exception:
        return set()


def _has_column(db: Session, table_name: str, column_name: str) -> bool:
    return str(column_name).strip() in _table_columns(db, table_name)


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


_ARTIFACT_SHA_CACHE_LOCK = Lock()
_ARTIFACT_SHA_CACHE: dict[tuple[str, str], str] = {}


def _preferred_dataset_cache_root() -> Path:
    configured = str(os.getenv("WORKER_DATASET_CACHE_DIR", "/tmp/datasets")).strip()
    if configured:
        return Path(configured)
    return Path("/tmp/datasets")


def _dataset_cache_root() -> Path:
    preferred = _preferred_dataset_cache_root()
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except Exception:
        fallback = Path(gettempdir()) / "datasets"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _safe_path_token(value: str, *, fallback: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or ""))
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = f".{path.name}.{uuid4().hex}.tmp"
    tmp_path = path.parent / tmp_name
    try:
        tmp_path.write_bytes(payload)
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _materialize_object_to_cache(
    *,
    bucket: str,
    object_key: str,
    cache_key: str,
    filename: str,
    require_non_empty: bool = False,
) -> Path:
    cache_dir = _dataset_cache_root() / _safe_path_token(cache_key, fallback="cache")
    cache_path = cache_dir / _safe_path_token(filename, fallback="dataset.bin")
    try:
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path
    except Exception:
        pass

    payload = s3_client().get_object(Bucket=bucket, Key=object_key)["Body"].read()
    if require_non_empty and not payload:
        raise RuntimeError(f"Empty parquet object: {object_key}")
    _atomic_write_bytes(cache_path, payload)
    return cache_path


def _is_dataset_cache_path(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        resolved_path = Path(path).resolve()
        cache_root = _dataset_cache_root().resolve()
        return resolved_path == cache_root or cache_root in resolved_path.parents
    except Exception:
        return False
def _rq_job_id() -> str | None:
    try:
        job = get_current_job()
        return job.id if job else None
    except Exception:
        return None
    
def _set_progress(
    db: Session,
    rid: UUID,
    job_id: str | None,
    *,
    pct: float | int | None = None,
    done: float | int | None = None,
    total: float | int | None = None,
    stage: str | None = None,
    message: str | None = None,
) -> None:
    """
    Writes progress to RQ job.meta.
    DB progress will be handled separately (Step 2) to avoid hidden globals.
    """
    if not job_id:
        return

    # If caller provided done/total, compute pct unless pct is explicitly given
    pct_calc: float | None = None
    if pct is None and done is not None and total not in (None, 0):
        try:
            pct_calc = (float(done) / float(total)) * 100.0
        except Exception:
            pct_calc = None

    pct_final = pct if pct is not None else pct_calc

    pct_int = None
    if pct_final is not None:
        try:
            pct_int = int(max(0, min(100, float(pct_final))))
        except Exception:
            pct_int = None

    job = get_current_job()
    if job is not None:
        meta = job.meta or {}
        if pct_int is not None:
            meta["progress_pct"] = pct_int
        if stage is not None:
            meta["progress_stage"] = stage
        if message is not None:
            meta["progress_message"] = message
        meta["heartbeat"] = _utcnow().isoformat()
        job.meta = meta
        job.save_meta()
    try:
        db.execute(text("UPDATE run SET progress_pct = :pct, progress_stage = :stage, progress_message = :message WHERE id = :rid"), {
            "rid": rid,
            "pct": pct_int if pct_int is not None else 0,
            "stage": stage or "",
            "message": message or "",
        })
        db.commit()
    except Exception:
        try: db.rollback()
        except Exception: pass

def _redis_for_cancel() -> Redis:
    # Keep decode_responses=False consistent with your worker Redis usage
    return Redis.from_url(settings.REDIS_URL, decode_responses=False)


def _cancel_key(job_id: str) -> bytes:
    return f"rq:cancel:{job_id}".encode("utf-8")


def _cancel_requested(r: Redis, job_id: str) -> bool:
    try:
        return bool(r.get(_cancel_key(job_id)))
    except Exception:
        return False


class RunCanceled(Exception):
    pass


def _check_cancel(r: Redis, job_id: str | None) -> None:
    if not job_id:
        return
    if _cancel_requested(r, job_id):
        raise RunCanceled("Canceled by user")


def _json_default(value: Any) -> Any:
    # Plotly payloads can contain numpy/pandas scalar or ndarray values.
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _sanitize_for_json(value: Any) -> Any:
    """
    Normalize values before JSON serialization.
    Postgres json/jsonb rejects NaN and +/-Inf, so these are converted to null.
    """
    if value is None:
        return None

    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {str(k): _sanitize_for_json(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_json(v) for v in value]

    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, bool):
        return bool(value)

    if isinstance(value, int):
        return int(value)

    if isinstance(value, str):
        return value

    if hasattr(value, "tolist"):
        try:
            return _sanitize_for_json(value.tolist())
        except Exception:
            pass

    return value


def _json_dumps_pg(payload: Any) -> str:
    return json.dumps(
        _sanitize_for_json(payload),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    )


def _artifact_candidate_key(db: Session, *, sha256: str, content_type: str) -> str | None:
    row = db.execute(
        text(
            """
            select object_key
            from artifact
            where sha256=:sha and content_type=:ctype and bucket=:bucket
            order by created_at desc
            limit 1
            """
        ),
        {"sha": sha256, "ctype": content_type, "bucket": settings.S3_BUCKET},
    ).mappings().first()
    if not row:
        return None
    key = str(row.get("object_key") or "").strip()
    return key or None


def _s3_object_matches_sha(s3: Any, *, object_key: str, expected_sha256: str) -> bool:
    try:
        head = s3.head_object(Bucket=settings.S3_BUCKET, Key=object_key)
    except Exception:
        return False
    metadata = dict(head.get("Metadata") or {})
    stored_sha = str(metadata.get("sha256") or metadata.get("sha") or "").strip().lower()
    return bool(stored_sha and stored_sha == expected_sha256.lower())


def _upload_content(
    *,
    object_key: str,
    content_type: str,
    content: bytes,
    db: Session | None = None,
) -> tuple[int, str, str]:
    ensure_bucket()
    s3 = s3_client()
    sha256 = _sha256_bytes(content)
    size_bytes = len(content)
    cache_key = (sha256, content_type)

    with _ARTIFACT_SHA_CACHE_LOCK:
        cached_key = _ARTIFACT_SHA_CACHE.get(cache_key)
    if cached_key and _s3_object_matches_sha(s3, object_key=cached_key, expected_sha256=sha256):
        return size_bytes, sha256, cached_key

    # Fast-path for reruns where the same run-scoped key already exists.
    if _s3_object_matches_sha(s3, object_key=object_key, expected_sha256=sha256):
        with _ARTIFACT_SHA_CACHE_LOCK:
            _ARTIFACT_SHA_CACHE[cache_key] = object_key
        return size_bytes, sha256, object_key

    if db is not None:
        try:
            prior_key = _artifact_candidate_key(db, sha256=sha256, content_type=content_type)
        except Exception:
            prior_key = None
        if prior_key and _s3_object_matches_sha(s3, object_key=prior_key, expected_sha256=sha256):
            with _ARTIFACT_SHA_CACHE_LOCK:
                _ARTIFACT_SHA_CACHE[cache_key] = prior_key
            return size_bytes, sha256, prior_key

    s3.put_object(
        Bucket=settings.S3_BUCKET,
        Key=object_key,
        Body=content,
        ContentType=content_type,
        Metadata={"sha256": sha256},
    )
    with _ARTIFACT_SHA_CACHE_LOCK:
        _ARTIFACT_SHA_CACHE[cache_key] = object_key
    return size_bytes, sha256, object_key


def _upload_json(object_key: str, payload: Any, *, db: Session | None = None) -> tuple[int, str, str]:
    content = json.dumps(
        _sanitize_for_json(payload),
        ensure_ascii=False,
        allow_nan=False,
        cls=PlotlyJSONEncoder,
        default=_json_default,
    ).encode("utf-8")
    return _upload_content(
        object_key=object_key,
        content_type="application/json",
        content=content,
        db=db,
    )


def _upload_text(object_key: str, text_content: str, *, db: Session | None = None) -> tuple[int, str, str]:
    content = text_content.encode("utf-8")
    return _upload_content(
        object_key=object_key,
        content_type="text/plain",
        content=content,
        db=db,
    )


def _upload_csv(object_key: str, frame: pd.DataFrame, *, db: Session | None = None) -> tuple[int, str, str]:
    content = frame.to_csv(index=False).encode("utf-8")
    return _upload_content(
        object_key=object_key,
        content_type="text/csv",
        content=content,
        db=db,
    )


def _as_float(v, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        out = float(v)
        if not math.isfinite(out):
            return default
        return out
    except Exception:
        return default


def _as_int(v, default: int | None = None) -> int | None:
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _as_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        low = v.strip().lower()
        if low in {"1", "true", "yes", "y", "on", "enabled"}:
            return True
        if low in {"0", "false", "no", "n", "off", "disabled"}:
            return False
    return default


def _as_dict(v) -> dict:
    if isinstance(v, dict):
        out = _sanitize_for_json(dict(v))
        return out if isinstance(out, dict) else {}
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, dict):
                out = _sanitize_for_json(parsed)
                return out if isinstance(out, dict) else {}
        except Exception:
            return {}
    return {}


def _metric_rows_to_map(rows: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in list(rows or []):
        if not isinstance(row, dict):
            continue
        metric = str(row.get("metric") or row.get("metric_name") or "").strip()
        if not metric:
            continue
        value = _as_float(row.get("value"))
        if value is None:
            value = _as_float(row.get("Value"))
        if value is None:
            continue
        out[metric] = value
    return out


def _metric_pick(metrics: dict[str, Any], keys: list[str]) -> float | None:
    if not metrics:
        return None
    exact = {str(k): v for k, v in metrics.items()}
    folded = {str(k).strip().lower(): v for k, v in metrics.items()}
    for key in keys:
        if key in exact:
            value = _as_float(exact[key])
            if value is not None:
                return value
        value = _as_float(folded.get(str(key).strip().lower()))
        if value is not None:
            return value
    return None


def _normalize_win_pct(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 1.0 and value <= 100.0:
        return value / 100.0
    return value


def _extract_strategy_summary_metrics(payload: dict[str, Any]) -> dict[str, float]:
    metrics = _as_dict(payload.get("metrics"))
    perf_metrics = _metric_rows_to_map(payload.get("trade_performance"))

    total_return = _metric_pick(metrics, ["Total return", "Total Return"])
    sharpe = _metric_pick(metrics, ["Sharpe", "Sharpe Ratio"])
    max_drawdown = _metric_pick(metrics, ["Max drawdown", "Max Drawdown", "Max Daily Drawdown"])
    win_pct = _metric_pick(perf_metrics, ["Win Rate", "Trade Winning %"])
    win_pct = _normalize_win_pct(win_pct)

    out: dict[str, float] = {}
    if total_return is not None:
        out["total_return"] = float(total_return)
    if sharpe is not None:
        out["sharpe"] = float(sharpe)
    if max_drawdown is not None:
        out["max_drawdown"] = float(max_drawdown)
    if win_pct is not None:
        out["win_pct"] = float(win_pct)
    return out


def _collect_strategy_summary_by_symbol(
    strategy_results: dict[str, Any],
    default_symbol: str,
) -> dict[tuple[str, str], dict[str, float]]:
    def _sym_key(value: Any) -> str:
        s = str(value or "").strip()
        return s.upper() if s else "__ALL__"

    out: dict[tuple[str, str], dict[str, float]] = {}
    for strategy_kind_raw, payload_any in dict(strategy_results or {}).items():
        payload = payload_any if isinstance(payload_any, dict) else {}
        strategy_kind = str(strategy_kind_raw).strip().lower()
        if not strategy_kind:
            continue

        summary = _extract_strategy_summary_metrics(payload)
        if not summary:
            continue

        target_symbols = [str(s) for s in list(payload.get("symbols") or []) if str(s).strip()]
        if not target_symbols:
            target_symbols = [default_symbol or "__ALL__"]

        for sym in target_symbols:
            out[(_sym_key(sym), strategy_kind)] = dict(summary)
    return out


def _to_pg_ts(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    parsed = _coerce_datetime_value(v, utc=True)
    if parsed is None or pd.isna(parsed):
        return None
    try:
        return parsed.to_pydatetime() if isinstance(parsed, pd.Timestamp) else parsed
    except Exception:
        return None


def _infer_epoch_unit(values: pd.Series) -> str:
    numeric = pd.to_numeric(values, errors="coerce")
    numeric = numeric[np.isfinite(numeric.to_numpy(dtype="float64", copy=False))]
    if numeric.empty:
        return "s"
    scale = float(np.nanmedian(np.abs(numeric.to_numpy(dtype="float64"))))
    if scale >= 1e17:
        return "ns"
    if scale >= 1e14:
        return "us"
    if scale >= 1e11:
        return "ms"
    return "s"


def _coerce_datetime_series(values: pd.Series, *, utc: bool) -> pd.Series:
    s = values.copy()
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns, UTC]" if utc else "datetime64[ns]")
    numeric = pd.to_numeric(s, errors="coerce")
    mask_numeric = numeric.notna()

    if (~mask_numeric).any():
        out.loc[~mask_numeric] = pd.to_datetime(s.loc[~mask_numeric], utc=utc, errors="coerce")

    if mask_numeric.any():
        num = numeric.loc[mask_numeric]
        abs_num = num.abs()
        mask_ns = abs_num >= 1e17
        mask_us = (abs_num >= 1e14) & (abs_num < 1e17)
        mask_ms = (abs_num >= 1e11) & (abs_num < 1e14)
        mask_s = abs_num < 1e11
        if mask_ns.any():
            out.loc[num.index[mask_ns]] = pd.to_datetime(num.loc[mask_ns], unit="ns", utc=utc, errors="coerce")
        if mask_us.any():
            out.loc[num.index[mask_us]] = pd.to_datetime(num.loc[mask_us], unit="us", utc=utc, errors="coerce")
        if mask_ms.any():
            out.loc[num.index[mask_ms]] = pd.to_datetime(num.loc[mask_ms], unit="ms", utc=utc, errors="coerce")
        if mask_s.any():
            out.loc[num.index[mask_s]] = pd.to_datetime(num.loc[mask_s], unit="s", utc=utc, errors="coerce")

    return out


def _coerce_datetime_value(value: Any, *, utc: bool) -> pd.Timestamp | None:
    parsed = _coerce_datetime_series(pd.Series([value]), utc=utc).iloc[0]
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed)


def _materialize_dataset_file(*, filename: str, data_hash: str, object_key: str | None = None) -> Path:
    # Prefer the stored object_key (guaranteed to match what was uploaded).
    # Fall back to canonical reconstruction for legacy rows where it is NULL.
    key = object_key or build_dataset_object_key(data_hash=data_hash, filename=filename)
    effective_filename = str(filename or Path(key).name or "dataset.bin")
    return _materialize_object_to_cache(
        bucket=settings.S3_BUCKET,
        object_key=key,
        cache_key=f"uploaded/{data_hash}",
        filename=effective_filename,
    )


def _store_key_for_symbol(*, db: Session, symbol: str, timeframe: str = "1D") -> str:
    sym = str(symbol).strip().upper()
    row = db.execute(
        text("select object_key from market_data_store where symbol=:s and timeframe=:tf"),
        {"s": sym, "tf": timeframe},
    ).mappings().first()
    if not row:
        raise RuntimeError(f"Symbol not found in canonical store: {sym} ({timeframe})")
    return str(row["object_key"])


def _materialize_store_parquet(*, object_key: str) -> Path:
    store_hash = _sha256_bytes(object_key.encode("utf-8"))
    filename = Path(object_key).name or "ohlcv.parquet"
    if not str(filename).lower().endswith(".parquet"):
        filename = f"{filename}.parquet"
    return _materialize_object_to_cache(
        bucket=settings.S3_BUCKET,
        object_key=object_key,
        cache_key=f"store/{store_hash}",
        filename=filename,
        require_non_empty=True,
    )


def _normalize_symbols(raw_symbols) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in list(raw_symbols or []):
        sym = str(item).strip()
        if not sym:
            continue
        key = sym.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(sym)
    return out


def _apply_store_as_parquet(spec_json: dict, local_paths: dict[str, Path]) -> dict:
    """
    Rewrite spec to use core ParquetDataSource reading local temp parquet files.
    """
    spec = dict(spec_json or {})
    data_json = dict(spec.get("data") or {})

    data_json["source"] = "parquet"
    data_json.setdefault("interval", "1d")

    syms = list(local_paths.keys())
    spec["symbols"] = syms
    data_json["symbols"] = syms

    if len(syms) == 1:
        data_json["parquet_paths"] = str(local_paths[syms[0]])
    else:
        data_json["parquet_paths"] = {s: str(p) for s, p in local_paths.items()}

    spec["data"] = data_json
    spec["source_key"] = "parquet"
    return spec


def _apply_uploaded_dataset(spec_json: dict, dataset_row: dict, local_file: Path) -> dict:
    spec = dict(spec_json or {})
    data_json = dict(spec.get("data") or {})

    data_json["source"] = "bmce"
    data_json["bmce_paths"] = str(local_file)
    data_json.setdefault("interval", "1d")

    symbols = spec.get("symbols") or data_json.get("symbols")
    if not symbols:
        default_symbol = Path(str(dataset_row.get("symbol") or "UPLOAD")).stem.upper() or "UPLOAD"
        symbols = [default_symbol]

    spec["symbols"] = list(symbols)
    data_json["symbols"] = list(symbols)
    spec["data"] = data_json
    spec["source_key"] = "bmce"
    return spec


def _apply_uploaded_dataset_map(spec_json: dict, local_paths: dict[str, Path]) -> dict:
    """
    Rewrite spec to BMCE mode with per-symbol local files materialized from uploaded datasets.
    """
    spec = dict(spec_json or {})
    data_json = dict(spec.get("data") or {})

    syms = list(local_paths.keys())
    data_json["source"] = "bmce"
    data_json.setdefault("interval", "1d")
    data_json["symbols"] = syms
    data_json["bmce_paths"] = {s: str(p) for s, p in local_paths.items()}
    data_json.pop("dataset_symbol_map", None)

    spec["symbols"] = syms
    spec["data"] = data_json
    spec["source_key"] = "bmce"
    return spec


def _build_symbol_spec(spec_json: dict, symbol: str) -> dict:
    spec = copy.deepcopy(spec_json or {})
    spec["symbols"] = [symbol]
    data_json = dict(spec.get("data") or {})
    data_json["symbols"] = [symbol]
    spec["data"] = data_json

    plots_json = dict(spec.get("plots") or {})
    if plots_json:
        plots_json["symbols"] = [symbol]
        spec["plots"] = plots_json
    return spec


def _apply_wfo_defaults(spec_json: dict) -> dict:
    def _setdefault_if_missing(payload: dict[str, Any], key: str, default_value: Any) -> None:
        current = payload.get(key)
        if current in (None, ""):
            payload[key] = default_value

    spec = copy.deepcopy(spec_json or {})
    optimization = dict(spec.get("optimization") or {})
    walk_forward = dict(optimization.get("walk_forward") or {})
    if not bool(walk_forward.get("enabled", False)):
        return spec

    horizon_cfg = get_horizon_config(
        walk_forward.get("horizon"),
        overrides=(walk_forward.get("horizon_overrides") if isinstance(walk_forward.get("horizon_overrides"), dict) else None),
    )

    wf_train = dict(walk_forward.get("train") or {})
    wf_test = dict(walk_forward.get("test") or {})
    wf_step = dict(walk_forward.get("step") or {})

    _setdefault_if_missing(wf_train, "value", int(horizon_cfg.train_window))
    _setdefault_if_missing(wf_train, "unit", "days")
    _setdefault_if_missing(wf_test, "value", int(horizon_cfg.test_window))
    _setdefault_if_missing(wf_test, "unit", "days")
    _setdefault_if_missing(wf_step, "value", int(horizon_cfg.step_size))
    _setdefault_if_missing(wf_step, "unit", "days")

    walk_forward["train"] = wf_train
    walk_forward["test"] = wf_test
    walk_forward["step"] = wf_step
    walk_forward["horizon"] = str(horizon_cfg.name.value)
    walk_forward["horizon_cfg"] = {
        "train_window": int(horizon_cfg.train_window),
        "test_window": int(horizon_cfg.test_window),
        "step_size": int(horizon_cfg.step_size),
        "use_test_window": bool(horizon_cfg.use_test_window),
    }
    optimization["walk_forward"] = walk_forward
    spec["optimization"] = optimization
    return spec


def _infer_run_mode(spec_json: dict[str, Any]) -> str:
    optimization = dict(spec_json.get("optimization") or {})
    walk_forward = dict(optimization.get("walk_forward") or {})
    return "walk_forward" if bool(walk_forward.get("enabled", False)) else "single"


def _extract_seed(spec_json: dict[str, Any]) -> int | None:
    optimization = dict(spec_json.get("optimization") or {})
    raw = optimization.get("seed")
    if raw is None:
        analysis = dict(spec_json.get("analysis") or {})
        sig = analysis.get("significance")
        if isinstance(sig, dict):
            raw = sig.get("seed")
    if raw is None:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _resolve_code_version() -> str | None:
    env_version = str(os.getenv("GIT_COMMIT", "")).strip()
    if env_version:
        return env_version
    repo_root = Path(__file__).resolve().parents[3]
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            timeout=2,
            text=True,
        ).strip()
        return out or None
    except Exception:
        return None


def _dataset_meta_for_run(
    db: Session,
    *,
    dataset_id: UUID | None,
    spec_json: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    if dataset_id is not None:
        row = db.execute(
            text("select data_hash, meta_json from dataset where id=:id"),
            {"id": dataset_id},
        ).mappings().first()
        if not row:
            return {}, None
        return dict(row.get("meta_json") or {}), str(row.get("data_hash") or "") or None

    data_cfg = dict(spec_json.get("data") or {})
    mapping = data_cfg.get("dataset_symbol_map")
    if isinstance(mapping, dict) and mapping:
        out_meta: dict[str, Any] = {}
        canonical: list[tuple[str, str]] = []
        for sym_raw, dsid_raw in mapping.items():
            sym = str(sym_raw).strip().upper()
            dsid = str(dsid_raw).strip()
            if not sym or not dsid:
                continue
            try:
                ds_uuid = UUID(dsid)
            except Exception:
                continue
            row = db.execute(
                text("select data_hash, meta_json from dataset where id=:id"),
                {"id": ds_uuid},
            ).mappings().first()
            if not row:
                continue
            out_meta[sym] = {
                "data_hash": str(row.get("data_hash") or ""),
                "meta_json": dict(row.get("meta_json") or {}),
            }
            canonical.append((sym, str(row.get("data_hash") or "")))
        if canonical:
            digest = hashlib.sha256(str(sorted(canonical)).encode("utf-8")).hexdigest()
            return {"dataset_symbol_map": out_meta}, f"map:{digest}"
        return {"dataset_symbol_map": out_meta}, None

    return {}, None


def _persist_run_repro_metadata(
    db: Session,
    *,
    rid: UUID,
    spec_json: dict[str, Any],
    dataset_hash: str | None,
    code_version: str | None,
) -> None:
    run_cols = _table_columns(db, "run")
    if not run_cols:
        return

    assignments: list[str] = []
    params: dict[str, Any] = {"id": rid}

    if "mode" in run_cols:
        assignments.append("mode=:mode")
        params["mode"] = _infer_run_mode(spec_json)
    if "seed" in run_cols:
        assignments.append("seed=:seed")
        params["seed"] = _extract_seed(spec_json)
    if "dataset_hash" in run_cols:
        assignments.append("dataset_hash=coalesce(:dataset_hash, dataset_hash)")
        params["dataset_hash"] = dataset_hash
    if "code_version" in run_cols:
        assignments.append("code_version=coalesce(:code_version, code_version)")
        params["code_version"] = code_version
    if "git_commit" in run_cols:
        assignments.append("git_commit=coalesce(:code_version, git_commit)")
        params["code_version"] = code_version
    if "integrity_status" in run_cols:
        assignments.append("integrity_status=coalesce(integrity_status, 'pending')")
    if "spec_json" in run_cols:
        assignments.append("spec_json=cast(:spec_json as jsonb)")
        params["spec_json"] = _json_dumps_pg(spec_json)

    if not assignments:
        return

    db.execute(
        text(f"update run set {', '.join(assignments)} where id=:id"),
        params,
    )
    db.commit()


def _resolve_batch_symbol_workers(spec_json: dict, total_symbols: int) -> int:
    optimization = dict(spec_json.get("optimization") or {})
    raw = optimization.get("batch_symbol_workers")
    if raw is None:
        raw = optimization.get("parallel_workers")
    if raw is None:
        raw = os.getenv("OPT_BATCH_SYMBOL_WORKERS")

    cpu = max(1, int(os.cpu_count() or 1))
    auto = max(1, min(int(total_symbols), max(1, cpu - 1)))

    if raw is None:
        return auto
    if isinstance(raw, str) and raw.strip().lower() in {"auto", "default"}:
        return auto
    try:
        n = int(raw)
    except Exception:
        return auto
    if n <= 0:
        return auto
    return max(1, min(int(total_symbols), n))


def _resolve_batch_symbol_executor_kind(spec_json: dict) -> str:
    optimization = dict(spec_json.get("optimization") or {})
    raw = optimization.get("batch_symbol_executor")
    if raw is None:
        raw = os.getenv("OPT_BATCH_SYMBOL_EXECUTOR", "process")
    kind = str(raw).strip().lower()
    if kind in {"thread", "threads"}:
        return "thread"
    return "process"


def _run_symbol_pipeline(spec_json: dict, symbol: str, dataset_path: str | None) -> tuple[str, dict]:
    sym_spec = _build_symbol_spec(spec_json, symbol)
    if dataset_path is not None:
        sym_spec.setdefault("data", {})
        sym_spec["data"]["source"] = "bmce"
        sym_spec["data"]["bmce_paths"] = dataset_path
    return symbol, run_pipeline(sym_spec)


def _is_batch_per_symbol_optimization(spec_json: dict) -> bool:
    optimization = dict(spec_json.get("optimization") or {})
    n_trials = int(optimization.get("n_trials") or 0)
    kinds = list(optimization.get("kinds") or [])
    run_opt = bool(n_trials > 0 or len(kinds) > 0)
    if not run_opt:
        return False
    return bool(optimization.get("batch_per_symbol", False))

def _update_best_snapshots(db: Session, run_id: UUID):
    # Pull rank=1 rows from this run and upsert into snapshot if pnl improves.
    db.execute(
        text("""
        INSERT INTO best_strategy_snapshot
          (spec_hash, timeframe, symbol, strategy_kind, best_run_id,
           pnl, cagr, efficiency, n_fills,
           signal_label, signal_today, signal_date,
           best_params_json, updated_at)
        SELECT
          r.spec_hash,
          md.timeframe,
          sl.symbol,
          sl.strategy_kind,
          sl.run_id,
          sl.pnl,
          sl.cagr,
          sl.efficiency,
          sl.n_fills,
          sl.signal_label,
          sl.signal_today,
          sl.signal_date,
          sl.best_params_json,
          now()
        FROM strategy_leaderboard sl
        JOIN run r ON r.id = sl.run_id
        JOIN market_data_store md ON md.symbol = sl.symbol
        WHERE sl.run_id = :run_id AND sl.rank = 1
        ON CONFLICT (spec_hash, timeframe, symbol, strategy_kind)
        DO UPDATE SET
          best_run_id = EXCLUDED.best_run_id,
          pnl = EXCLUDED.pnl,
          cagr = EXCLUDED.cagr,
          efficiency = EXCLUDED.efficiency,
          n_fills = EXCLUDED.n_fills,
          signal_label = EXCLUDED.signal_label,
          signal_today = EXCLUDED.signal_today,
          signal_date = EXCLUDED.signal_date,
          best_params_json = EXCLUDED.best_params_json,
          updated_at = now()
        WHERE EXCLUDED.pnl > best_strategy_snapshot.pnl
        """),
        {"run_id": str(run_id)},
    )


def _normalize_strategy_kind(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip()
    return symbol if symbol else "__ALL__"


def _records_to_frame(records: Any) -> pd.DataFrame:
    rows = [r for r in list(records or []) if isinstance(r, dict)]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    ts_col = "timestamp" if "timestamp" in df.columns else None
    if ts_col:
        df[ts_col] = _coerce_datetime_series(df[ts_col], utc=True)
        df = df.dropna(subset=[ts_col]).set_index(ts_col).sort_index()
    for col in df.columns:
        if col in {"symbol", "side"}:
            continue
        df[col] = pd.to_numeric(df[col], errors="ignore")
    return df


def _decision_source_by_kind(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_kind: dict[str, dict[str, Any]] = {}

    decision_support = out.get("decision_support")
    if isinstance(decision_support, dict):
        support_inputs = decision_support.get("inputs_by_kind")
        if isinstance(support_inputs, dict):
            for kind_raw, payload_any in support_inputs.items():
                kind = _normalize_strategy_kind(kind_raw)
                if not kind:
                    continue
                payload = payload_any if isinstance(payload_any, dict) else {}
                decision_inputs = payload.get("decision_inputs")
                by_kind[kind] = {
                    "decision_inputs": decision_inputs if isinstance(decision_inputs, dict) else {},
                    "trade_ledger": [r for r in list(payload.get("trade_ledger") or []) if isinstance(r, dict)],
                    "symbols": [str(s) for s in list(payload.get("symbols") or []) if str(s).strip()],
                }

    if by_kind:
        return by_kind

    strategy_results = out.get("strategy_results") or {}
    for kind_raw, payload_any in dict(strategy_results).items():
        kind = _normalize_strategy_kind(kind_raw)
        if not kind:
            continue
        payload = payload_any if isinstance(payload_any, dict) else {}
        decision_inputs = payload.get("decision_inputs")
        by_kind[kind] = {
            "decision_inputs": decision_inputs if isinstance(decision_inputs, dict) else {},
            "trade_ledger": [r for r in list(payload.get("trade_ledger") or []) if isinstance(r, dict)],
            "symbols": [str(s) for s in list(payload.get("symbols") or []) if str(s).strip()],
        }

    return by_kind


def _decision_bars_by_symbol(decision_source_by_kind: dict[str, dict[str, Any]]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for payload in decision_source_by_kind.values():
        inputs = payload.get("decision_inputs")
        if not isinstance(inputs, dict):
            continue
        by_symbol = inputs.get("symbols")
        if not isinstance(by_symbol, dict):
            continue
        for sym, sym_payload_any in by_symbol.items():
            sym_payload = sym_payload_any if isinstance(sym_payload_any, dict) else {}
            frame = _records_to_frame(sym_payload.get("bars"))
            if frame.empty:
                continue
            out.setdefault(_normalize_symbol(sym), frame)
    return out


def _decision_signals_by_kind_symbol(
    decision_source_by_kind: dict[str, dict[str, Any]]
) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for kind, payload in decision_source_by_kind.items():
        inputs = payload.get("decision_inputs")
        if not isinstance(inputs, dict):
            continue
        by_symbol = inputs.get("symbols")
        if not isinstance(by_symbol, dict):
            continue
        for sym, sym_payload_any in by_symbol.items():
            sym_payload = sym_payload_any if isinstance(sym_payload_any, dict) else {}
            sig = _records_to_frame(sym_payload.get("signals"))
            if sig.empty or "signal" not in sig.columns:
                continue
            latest = _as_float(sig["signal"].iloc[-1], 0.0) or 0.0
            out[(_normalize_symbol(sym), kind)] = float(latest)
    return out


def _decision_returns_by_kind(decision_source_by_kind: dict[str, dict[str, Any]]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for kind, payload in decision_source_by_kind.items():
        inputs = payload.get("decision_inputs")
        if not isinstance(inputs, dict):
            continue
        ret_df = _records_to_frame(inputs.get("returns"))
        if ret_df.empty or "return" not in ret_df.columns:
            continue
        values = [
            float(v)
            for v in pd.to_numeric(ret_df["return"], errors="coerce").dropna().tolist()
        ]
        out[kind] = values
    return out


def _decision_trade_ledger_by_kind(
    decision_source_by_kind: dict[str, dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for kind, payload in decision_source_by_kind.items():
        rows = [r for r in list(payload.get("trade_ledger") or []) if isinstance(r, dict)]
        if rows:
            out[kind] = rows
    return out


def _stable_json_hash(payload: Any) -> str:
    content = json.dumps(_sanitize_for_json(payload), ensure_ascii=False, sort_keys=True, allow_nan=False, default=_json_default)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _params_from_leaderboard_row(row: dict[str, Any]) -> dict[str, Any]:
    base = _as_dict(row.get("best_params_json"))
    for k, v in row.items():
        key = str(k)
        if key.startswith("strategy.") or key.startswith("portfolio."):
            sv = _sanitize_for_json(v)
            if sv is not None:
                base[key] = sv
    return base


def _signal_value_from_row_or_map(
    *,
    symbol: str,
    strategy_kind: str,
    row: dict[str, Any],
    signal_map: dict[tuple[str, str], float],
) -> float:
    signal = _as_float(row.get("signal_today"))
    if signal is not None:
        return float(signal)
    label = str(row.get("signal_label") or "").strip().upper()
    if label in {"BUY", "LONG"}:
        return 1.0
    if label in {"SELL", "SHORT"}:
        return -1.0
    return float(signal_map.get((_normalize_symbol(symbol), _normalize_strategy_kind(strategy_kind)), 0.0))


def _walk_forward_rows(out: dict[str, Any]) -> list[dict[str, Any]]:
    decision_support = out.get("decision_support")
    if isinstance(decision_support, dict):
        rows = decision_support.get("walk_forward_rows")
        if isinstance(rows, list):
            filtered = [r for r in rows if isinstance(r, dict)]
            if filtered:
                return filtered

    batch = out.get("batch_period")
    if not isinstance(batch, dict):
        return []
    if str(batch.get("mode") or "").strip().lower() != "walk_forward":
        return []
    return [r for r in list(batch.get("results") or []) if isinstance(r, dict)]


def _walk_forward_oos_summary_by_kind(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    decision_support = out.get("decision_support")
    if isinstance(decision_support, dict):
        summary = decision_support.get("walk_forward_oos_summary_by_kind")
        if isinstance(summary, dict):
            out_summary: dict[str, dict[str, Any]] = {}
            for kind_raw, payload_any in summary.items():
                kind = _normalize_strategy_kind(kind_raw)
                payload = payload_any if isinstance(payload_any, dict) else {}
                if kind:
                    out_summary[kind] = payload
            if out_summary:
                return out_summary

    batch = out.get("batch_period")
    if not isinstance(batch, dict):
        return {}
    summary = batch.get("oos_summary_by_kind")
    if not isinstance(summary, dict):
        return {}
    out_summary: dict[str, dict[str, Any]] = {}
    for kind_raw, payload_any in summary.items():
        kind = _normalize_strategy_kind(kind_raw)
        payload = payload_any if isinstance(payload_any, dict) else {}
        if kind:
            out_summary[kind] = payload
    return out_summary


def _insert_artifact_row(
    *,
    db: Session,
    rid: UUID,
    symbol: str,
    artifact_type: str,
    name: str,
    object_key: str,
    content_type: str,
    size_bytes: int,
    sha256: str,
) -> None:
    db.execute(
        text(
            """
            insert into artifact(
                id, run_id, symbol, artifact_type, name, object_key, bucket, content_type, size_bytes, sha256
            ) values (
                :id, :run_id, :symbol, :atype, :name, :key, :bucket, :ctype, :size, :sha
            )
            """
        ),
        {
            "id": uuid4(),
            "run_id": rid,
            "symbol": symbol,
            "atype": artifact_type,
            "name": name,
            "key": object_key,
            "bucket": settings.S3_BUCKET,
            "ctype": content_type,
            "size": int(size_bytes),
            "sha": sha256,
        },
    )


def _warmup_artifact_options(spec_json: dict[str, Any] | None) -> tuple[bool, int]:
    env_enabled = _as_bool(os.getenv("WORKER_WARMUP_ARTIFACT_ENABLED"), False)
    env_max_rows = _as_int(os.getenv("WORKER_WARMUP_ARTIFACT_MAX_ROWS"), 320) or 320

    cfg = dict((spec_json or {}).get("cache") or {})
    warm_cfg_raw = cfg.get("warmup_artifact")
    if isinstance(warm_cfg_raw, dict):
        enabled = _as_bool(warm_cfg_raw.get("enabled"), env_enabled)
        max_rows = _as_int(warm_cfg_raw.get("max_rows"), env_max_rows) or env_max_rows
        return enabled, max(1, max_rows)
    if warm_cfg_raw is not None:
        enabled = _as_bool(warm_cfg_raw, env_enabled)
        return enabled, max(1, env_max_rows)
    return env_enabled, max(1, env_max_rows)


def _resolve_dataset_cache_identity(
    *,
    dataset_hash: str | None,
    spec_json: dict[str, Any] | None,
) -> str:
    if dataset_hash:
        return str(dataset_hash)

    spec = dict(spec_json or {})
    data_cfg = dict(spec.get("data") or {})
    payload = {
        "source": str(spec.get("source_key") or data_cfg.get("source") or ""),
        "symbols": [str(s) for s in list(spec.get("symbols") or data_cfg.get("symbols") or []) if str(s).strip()],
        "interval": str(data_cfg.get("interval") or data_cfg.get("timeframe") or ""),
        "start": data_cfg.get("start"),
        "end": data_cfg.get("end"),
        "dataset_symbol_map": data_cfg.get("dataset_symbol_map"),
        "parquet_paths": data_cfg.get("parquet_paths"),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return f"spec:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _build_warmup_snapshot_payload(
    *,
    strategy_kind: str,
    strategy_payload: dict[str, Any],
    max_rows: int,
) -> dict[str, Any] | None:
    decision_inputs = strategy_payload.get("decision_inputs")
    if not isinstance(decision_inputs, dict):
        return None

    symbols_in = decision_inputs.get("symbols")
    symbols_snapshot: dict[str, Any] = {}
    if isinstance(symbols_in, dict):
        for sym_raw, sym_payload_any in symbols_in.items():
            sym_payload = sym_payload_any if isinstance(sym_payload_any, dict) else {}
            features = [r for r in list(sym_payload.get("features") or []) if isinstance(r, dict)][-max_rows:]
            signals = [r for r in list(sym_payload.get("signals") or []) if isinstance(r, dict)][-max_rows:]
            if not features and not signals:
                continue
            symbols_snapshot[str(sym_raw)] = {
                "features": features,
                "signals": signals,
            }

    returns_rows = [r for r in list(decision_inputs.get("returns") or []) if isinstance(r, dict)][-max_rows:]
    if not symbols_snapshot and not returns_rows:
        return None

    best_params = _as_dict(strategy_payload.get("best_params"))
    return {
        "schema_version": 1,
        "generated_at": _utcnow().isoformat(),
        "strategy_kind": strategy_kind,
        "symbols": symbols_snapshot,
        "returns": returns_rows,
        "best_params": best_params,
    }


def _persist_warmup_artifacts(
    *,
    db: Session,
    rid: UUID,
    out: dict[str, Any],
    spec_json: dict[str, Any] | None,
    dataset_hash: str | None,
) -> None:
    enabled, max_rows = _warmup_artifact_options(spec_json)
    if not enabled:
        return

    strategy_results = out.get("strategy_results") or {}
    if not isinstance(strategy_results, dict) or not strategy_results:
        return

    spec = dict(spec_json or {})
    data_cfg = dict(spec.get("data") or {})
    dataset_identity = _resolve_dataset_cache_identity(dataset_hash=dataset_hash, spec_json=spec_json)
    dataset_token = _safe_path_token(dataset_identity, fallback="dataset")
    timeframe = str(data_cfg.get("interval") or data_cfg.get("timeframe") or "1d")
    timeframe_token = _safe_path_token(timeframe, fallback="1d")

    for strategy_kind_raw, payload_any in strategy_results.items():
        strategy_kind = str(strategy_kind_raw).strip().lower()
        if not strategy_kind:
            continue
        payload = payload_any if isinstance(payload_any, dict) else {}
        snapshot_payload = _build_warmup_snapshot_payload(
            strategy_kind=strategy_kind,
            strategy_payload=payload,
            max_rows=max_rows,
        )
        if not snapshot_payload:
            continue

        strategy_token = _safe_path_token(strategy_kind, fallback="strategy")
        object_key = (
            f"cache/warmup/{dataset_token}/{timeframe_token}/{strategy_token}/snapshot.json"
        )
        size_bytes, sha256, effective_key = _upload_json(object_key, snapshot_payload, db=db)
        _insert_artifact_row(
            db=db,
            rid=rid,
            symbol="__ALL__",
            artifact_type="cache_warmup_json",
            name=f"warmup.{strategy_kind}",
            object_key=effective_key,
            content_type="application/json",
            size_bytes=size_bytes,
            sha256=sha256,
        )


def _persist_integrity(
    *,
    db: Session,
    rid: UUID,
    out: dict[str, Any],
    spec_json: dict[str, Any],
    dataset_meta: dict[str, Any],
) -> None:
    analysis_cfg = dict(spec_json.get("analysis") or {})
    integrity_cfg = dict(analysis_cfg.get("integrity") or {})
    if not _as_bool(integrity_cfg.get("enabled"), True):
        return

    report = build_integrity_report(
        spec_json=spec_json,
        pipeline_output=out,
        dataset_meta=dataset_meta,
    )
    checks = [r for r in list(report.get("checks") or []) if isinstance(r, dict)]

    for check in checks:
        check_name = str(check.get("check_name") or "").strip()
        if not check_name:
            continue
        status = str(check.get("status") or "warn").strip().lower()
        details = _as_dict(check.get("details"))
        db.execute(
            text(
                """
                insert into run_integrity_check(run_id, check_name, status, details_json, created_at)
                values (:run_id, :check_name, :status, cast(:details_json as jsonb), :created_at)
                on conflict (run_id, check_name)
                do update set
                    status = excluded.status,
                    details_json = excluded.details_json,
                    created_at = excluded.created_at
                """
            ),
            {
                "run_id": rid,
                "check_name": check_name,
                "status": status,
                "details_json": _json_dumps_pg(details),
                "created_at": _utcnow(),
            },
        )

    overall = str(report.get("status") or "warn").lower()
    db.execute(
        text("update run set integrity_status=:status where id=:id"),
        {"id": rid, "status": overall},
    )

    object_key = f"runs/{rid}/integrity/report.json"
    size_bytes, sha256, effective_key = _upload_json(object_key, report, db=db)
    _insert_artifact_row(
        db=db,
        rid=rid,
        symbol="__ALL__",
        artifact_type="run_integrity_json",
        name="integrity.report",
        object_key=effective_key,
        content_type="application/json",
        size_bytes=size_bytes,
        sha256=sha256,
    )


def _persist_walk_forward_folds(
    *,
    db: Session,
    rid: UUID,
    out: dict[str, Any],
    default_symbol: str,
) -> None:
    simple_wfo = out.get("simple_wfo_multi_horizon")
    if isinstance(simple_wfo, dict) and _as_bool(simple_wfo.get("enabled"), False):
        # Simplified WFO mode intentionally hides fold-by-fold persistence/details.
        return

    rows = _walk_forward_rows(out)
    if not rows:
        return

    wfo_meta = dict(((out.get("artifacts") or {}).get("walk_forward") or {}))
    wfo_train = dict(wfo_meta.get("train") or {})
    wfo_test = dict(wfo_meta.get("test") or {})
    wfo_step = dict(wfo_meta.get("step") or {})
    horizon = str(wfo_meta.get("horizon") or "medium").strip().lower() or "medium"
    horizon_label = str(wfo_meta.get("horizon_label") or "").strip()
    horizon_cfg = dict(wfo_meta.get("horizon_cfg") or {})
    resolved_start_date = str(wfo_meta.get("resolved_start_date") or "").strip() or None
    resolved_end_date = str(wfo_meta.get("resolved_end_date") or "").strip() or None
    end_date_policy = str(wfo_meta.get("end_date_policy") or "latest").strip().lower() or "latest"
    date_resolution = dict(wfo_meta.get("date_resolution") or {})

    for i, row in enumerate(rows):
        fold_index = _as_int(row.get("fold_index"))
        if fold_index is None:
            period_label = str(row.get("period") or row.get("label") or "")
            if period_label.lower().startswith("fold"):
                try:
                    fold_index = int(period_label.split()[-1]) - 1
                except Exception:
                    fold_index = i
            else:
                fold_index = i

        db.execute(
            text(
                """
                insert into run_fold(
                    run_id, fold_index, train_start, train_end, test_start, test_end, fold_metrics_json, fold_artifacts, created_at
                ) values (
                    :run_id, :fold_index, :train_start, :train_end, :test_start, :test_end,
                    cast(:fold_metrics_json as jsonb), cast(:fold_artifacts as jsonb), :created_at
                )
                on conflict (run_id, fold_index)
                do update set
                    train_start = excluded.train_start,
                    train_end = excluded.train_end,
                    test_start = excluded.test_start,
                    test_end = excluded.test_end,
                    fold_metrics_json = excluded.fold_metrics_json,
                    fold_artifacts = excluded.fold_artifacts,
                    created_at = excluded.created_at
                """
            ),
            {
                "run_id": rid,
                "fold_index": int(fold_index),
                "train_start": _to_pg_ts(row.get("train_start")),
                "train_end": _to_pg_ts(row.get("train_end")),
                "test_start": _to_pg_ts(row.get("test_start") or row.get("start")),
                "test_end": _to_pg_ts(row.get("test_end") or row.get("end")),
                "fold_metrics_json": _json_dumps_pg(row),
                "fold_artifacts": _json_dumps_pg(
                    {
                        "symbol": default_symbol,
                        "horizon": horizon,
                        "horizon_label": horizon_label,
                        "horizon_cfg": horizon_cfg,
                        "train": wfo_train,
                        "test": wfo_test,
                        "step": wfo_step,
                        "resolved_start_date": resolved_start_date,
                        "resolved_end_date": resolved_end_date,
                        "end_date_policy": end_date_policy,
                        "date_resolution": date_resolution,
                    }
                ),
                "created_at": _utcnow(),
            },
        )

    object_key = f"runs/{rid}/wfo/{default_symbol}/{horizon}/folds.json"
    size_bytes, sha256, effective_key = _upload_json(object_key, rows, db=db)
    _insert_artifact_row(
        db=db,
        rid=rid,
        symbol=str(default_symbol or "__ALL__"),
        artifact_type="walk_forward_json",
        name="walk_forward.folds",
        object_key=effective_key,
        content_type="application/json",
        size_bytes=size_bytes,
        sha256=sha256,
    )


def _persist_significance(
    *,
    db: Session,
    rid: UUID,
    out: dict[str, Any],
    spec_json: dict[str, Any],
) -> None:
    analysis_cfg = dict(spec_json.get("analysis") or {})
    sig_cfg = dict(analysis_cfg.get("significance") or {})
    if not _as_bool(sig_cfg.get("enabled"), False):
        return

    returns_by_kind = _decision_returns_by_kind(_decision_source_by_kind(out))
    if not returns_by_kind:
        return

    seed = _as_int(sig_cfg.get("seed"), _extract_seed(spec_json) or 42) or 42
    iterations = _as_int(sig_cfg.get("iterations"), 2000) or 2000
    reports = evaluate_significance(
        returns_by_kind,
        n_iter=iterations,
        seed=seed,
        periods_per_year=252,
    )
    if not reports:
        return

    persisted: dict[str, Any] = {}
    for kind, payload in reports.items():
        t_res = _as_dict(payload.get("t_test"))
        mc_res = _as_dict(payload.get("mc_sharpe"))
        entries = [
            (f"{kind}.t_stat_mean_return", t_res.get("pvalue"), t_res.get("t_stat"), t_res),
            (f"{kind}.mc_sharpe_bootstrap", mc_res.get("pvalue"), mc_res.get("observed"), mc_res),
        ]
        for method, pvalue, statistic, details in entries:
            db.execute(
                text(
                    """
                    insert into run_significance(run_id, method, pvalue, statistic, mc_null_dist_ref, details_json, created_at)
                    values (:run_id, :method, :pvalue, :statistic, :mc_null_dist_ref, cast(:details_json as jsonb), :created_at)
                    on conflict (run_id, method)
                    do update set
                        pvalue = excluded.pvalue,
                        statistic = excluded.statistic,
                        mc_null_dist_ref = excluded.mc_null_dist_ref,
                        details_json = excluded.details_json,
                        created_at = excluded.created_at
                    """
                ),
                {
                    "run_id": rid,
                    "method": method,
                    "pvalue": _as_float(pvalue),
                    "statistic": _as_float(statistic),
                    "mc_null_dist_ref": None,
                    "details_json": _json_dumps_pg({**_as_dict(details), "strategy_kind": kind}),
                    "created_at": _utcnow(),
                },
            )
        persisted[kind] = payload

    object_key = f"runs/{rid}/significance/report.json"
    size_bytes, sha256, effective_key = _upload_json(object_key, persisted, db=db)
    _insert_artifact_row(
        db=db,
        rid=rid,
        symbol="__ALL__",
        artifact_type="run_significance_json",
        name="significance.report",
        object_key=effective_key,
        content_type="application/json",
        size_bytes=size_bytes,
        sha256=sha256,
    )


def _persist_risk(
    *,
    db: Session,
    rid: UUID,
    out: dict[str, Any],
    spec_json: dict[str, Any],
) -> None:
    analysis_cfg = dict(spec_json.get("analysis") or {})
    risk_cfg = dict(analysis_cfg.get("risk") or {})
    if not _as_bool(risk_cfg.get("enabled"), False):
        return

    returns_by_kind = _decision_returns_by_kind(_decision_source_by_kind(out))
    if not returns_by_kind:
        return

    primary_kind = str((out.get("artifacts") or {}).get("primary_kind") or "").strip().lower()
    if not primary_kind or primary_kind not in returns_by_kind:
        primary_kind = next(iter(returns_by_kind.keys()))

    returns = returns_by_kind.get(primary_kind) or []
    if len(returns) < 3:
        return

    portfolio_cfg = dict(spec_json.get("portfolio") or {})
    cost_cfg = dict(portfolio_cfg.get("cost_model") or {})
    seed = _as_int(risk_cfg.get("seed"), _extract_seed(spec_json) or 42) or 42
    n_paths = _as_int(risk_cfg.get("mc_paths"), 2000) or 2000
    leverage_cap = _as_float(risk_cfg.get("leverage_cap"), 2.0) or 2.0
    initial_cash = _as_float(portfolio_cfg.get("initial_cash"), 100000.0) or 100000.0
    fills = [r for r in list(out.get("fills") or []) if isinstance(r, dict)]
    total_notional = float(
        sum(
            _as_float(r.get("notional"), abs((_as_float(r.get("qty"), 0.0) or 0.0) * (_as_float(r.get("price"), 0.0) or 0.0)))
            or 0.0
            for r in fills
        )
    )
    avg_turnover = (total_notional / max(initial_cash, 1.0)) / max(len(returns), 1)

    risk_report = build_risk_summary(
        returns,
        seed=seed,
        n_paths=n_paths,
        leverage_cap=leverage_cap,
        cost_bps=(
            (_as_float(cost_cfg.get("brokerage_bps"), 0.0) or 0.0)
            + (_as_float(cost_cfg.get("comm_bourse_bps"), 0.0) or 0.0)
            + (_as_float(cost_cfg.get("reg_liv_bps"), 0.0) or 0.0)
        ),
        slippage_bps=_as_float(cost_cfg.get("slippage_bps"), 0.0) or 0.0,
        avg_turnover=avg_turnover,
    )

    db.execute(
        text(
            """
            insert into run_risk(
                run_id, kelly_fraction, half_kelly, chosen_leverage, mc_drawdown_pctl, mc_var, mc_cvar, details_json, created_at
            ) values (
                :run_id, :kelly_fraction, :half_kelly, :chosen_leverage, :mc_drawdown_pctl, :mc_var, :mc_cvar, cast(:details_json as jsonb), :created_at
            )
            on conflict (run_id)
            do update set
                kelly_fraction = excluded.kelly_fraction,
                half_kelly = excluded.half_kelly,
                chosen_leverage = excluded.chosen_leverage,
                mc_drawdown_pctl = excluded.mc_drawdown_pctl,
                mc_var = excluded.mc_var,
                mc_cvar = excluded.mc_cvar,
                details_json = excluded.details_json,
                created_at = excluded.created_at
            """
        ),
        {
            "run_id": rid,
            "kelly_fraction": _as_float(risk_report.get("kelly_fraction")),
            "half_kelly": _as_float(risk_report.get("half_kelly")),
            "chosen_leverage": _as_float(risk_report.get("chosen_leverage")),
            "mc_drawdown_pctl": _as_float(risk_report.get("mc_drawdown_pctl")),
            "mc_var": _as_float(risk_report.get("mc_var")),
            "mc_cvar": _as_float(risk_report.get("mc_cvar")),
            "details_json": _json_dumps_pg({**risk_report, "strategy_kind": primary_kind}),
            "created_at": _utcnow(),
        },
    )

    object_key = f"runs/{rid}/risk/report.json"
    size_bytes, sha256, effective_key = _upload_json(
        object_key,
        {**risk_report, "strategy_kind": primary_kind},
        db=db,
    )
    _insert_artifact_row(
        db=db,
        rid=rid,
        symbol="__ALL__",
        artifact_type="run_risk_json",
        name="risk.report",
        object_key=effective_key,
        content_type="application/json",
        size_bytes=size_bytes,
        sha256=sha256,
    )


def _persist_mean_reversion(
    *,
    db: Session,
    rid: UUID,
    out: dict[str, Any],
    spec_json: dict[str, Any],
) -> None:
    analysis_cfg = dict(spec_json.get("analysis") or {})
    mr_cfg = dict(analysis_cfg.get("mean_reversion") or {})
    if not _as_bool(mr_cfg.get("enabled"), False):
        return

    bars_by_symbol = _decision_bars_by_symbol(_decision_source_by_kind(out))
    if not bars_by_symbol:
        return

    report: dict[str, Any] = {"symbols": {}, "pairs": []}
    closes_by_symbol: dict[str, pd.Series] = {}
    for symbol, frame in bars_by_symbol.items():
        if "Close" not in frame.columns:
            continue
        close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
        if len(close) < 30:
            continue
        closes_by_symbol[symbol] = close
        try:
            adf = adf_test(close)
            hl = estimate_half_life(close)
            report["symbols"][symbol] = {"adf": adf, "half_life": hl}
        except Exception as exc:
            report["symbols"][symbol] = {"error": str(exc)}

    sorted_symbols = sorted(closes_by_symbol.keys())
    if len(sorted_symbols) >= 2:
        sym_a, sym_b = sorted_symbols[0], sorted_symbols[1]
        a, b = closes_by_symbol[sym_a], closes_by_symbol[sym_b]
        aligned = pd.concat([a.rename(sym_a), b.rename(sym_b)], axis=1).dropna()
        if len(aligned) >= 50:
            try:
                cadf = cadf_cointegration(aligned[sym_a].to_numpy(), aligned[sym_b].to_numpy())
                report["pairs"].append({"y": sym_a, "x": sym_b, "cadf": cadf})
            except Exception as exc:
                report["pairs"].append({"y": sym_a, "x": sym_b, "error": str(exc)})

    object_key = f"runs/{rid}/mean_reversion/report.json"
    size_bytes, sha256, effective_key = _upload_json(object_key, report, db=db)
    _insert_artifact_row(
        db=db,
        rid=rid,
        symbol="__ALL__",
        artifact_type="mean_reversion_json",
        name="mean_reversion.report",
        object_key=effective_key,
        content_type="application/json",
        size_bytes=size_bytes,
        sha256=sha256,
    )


def _persist_decisions(
    *,
    db: Session,
    rid: UUID,
    out: dict[str, Any],
    default_symbol: str,
) -> None:
    strategy_results = out.get("strategy_results") or {}
    decision_source_by_kind = _decision_source_by_kind(out)
    leaderboard_rows = [r for r in list(out.get("leaderboard") or []) if isinstance(r, dict)]
    top_k = max(1, int(settings.TOP_K_DECISIONS or 1))
    bars_by_symbol = _decision_bars_by_symbol(decision_source_by_kind)
    signals_by_kind_symbol = _decision_signals_by_kind_symbol(decision_source_by_kind)
    returns_by_kind = _decision_returns_by_kind(decision_source_by_kind)
    ledger_by_kind = _decision_trade_ledger_by_kind(decision_source_by_kind)
    wf_rows = _walk_forward_rows(out)
    wf_oos_summary_by_kind = _walk_forward_oos_summary_by_kind(out)

    normalized_rows: list[dict[str, Any]] = []
    if leaderboard_rows:
        rank_counter: dict[tuple[str, str], int] = {}
        for raw in leaderboard_rows:
            strategy_kind = _normalize_strategy_kind(raw.get("strategy_kind") or raw.get("Strategy"))
            if not strategy_kind:
                continue
            symbol = _normalize_symbol(raw.get("symbol") or default_symbol)
            rank_key = (symbol, strategy_kind)
            rank_counter[rank_key] = rank_counter.get(rank_key, 0) + 1
            rank = _as_int(raw.get("rank"), rank_counter[rank_key]) or rank_counter[rank_key]
            params_json = _params_from_leaderboard_row(raw)
            normalized_rows.append(
                {
                    "symbol": symbol,
                    "strategy_kind": strategy_kind,
                    "rank": int(rank),
                    "params_json": params_json,
                    "cagr": _as_float(raw.get("cagr")),
                    "pnl": _as_float(raw.get("pnl")),
                    "efficiency": _as_float(raw.get("efficiency")),
                    "n_fills": _as_int(raw.get("n_fills")),
                    "signal_today": _as_float(raw.get("signal_today")),
                    "signal_label": raw.get("signal_label"),
                    "sharpe": _as_float(raw.get("sharpe")),
                    "max_drawdown": _as_float(raw.get("max_drawdown")),
                }
            )
    else:
        for kind_raw, payload_any in dict(strategy_results or {}).items():
            payload = payload_any if isinstance(payload_any, dict) else {}
            kind = _normalize_strategy_kind(kind_raw)
            if not kind:
                continue
            params_json = _as_dict(payload.get("best_strategy_params"))
            target_symbols = [str(s) for s in list(payload.get("symbols") or []) if str(s).strip()]
            if not target_symbols:
                target_symbols = [default_symbol or "__ALL__"]
            for sym in target_symbols:
                signal = signals_by_kind_symbol.get((_normalize_symbol(sym), kind), 0.0)
                normalized_rows.append(
                    {
                        "symbol": _normalize_symbol(sym),
                        "strategy_kind": kind,
                        "rank": 1,
                        "params_json": params_json,
                        "cagr": _as_float(_as_dict(payload.get("metrics")).get("CAGR")),
                        "pnl": _as_float(_as_dict(payload.get("metrics")).get("Net PnL")),
                        "efficiency": None,
                        "n_fills": None,
                        "signal_today": signal,
                        "signal_label": None,
                        "sharpe": _as_float(_as_dict(payload.get("metrics")).get("Sharpe")),
                        "max_drawdown": _as_float(_as_dict(payload.get("metrics")).get("Max drawdown")),
                    }
                )

    if not normalized_rows:
        return

    by_symbol_rows: dict[str, list[dict[str, Any]]] = {}
    for row in normalized_rows:
        by_symbol_rows.setdefault(_normalize_symbol(row.get("symbol")), []).append(row)

    candidates: list[dict[str, Any]] = []
    for symbol, rows in by_symbol_rows.items():
        ranked = sorted(
            rows,
            key=lambda r: (
                int(r.get("rank") or 999999),
                -float(r.get("cagr") if r.get("cagr") is not None else -999999.0),
            ),
        )
        candidates.extend(ranked[:top_k])

    by_symbol_kind_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in normalized_rows:
        key = (_normalize_symbol(row.get("symbol")), _normalize_strategy_kind(row.get("strategy_kind")))
        by_symbol_kind_rows.setdefault(key, []).append(row)

    for row in candidates:
        symbol = _normalize_symbol(row.get("symbol"))
        strategy_kind = _normalize_strategy_kind(row.get("strategy_kind"))
        params_json = _as_dict(row.get("params_json"))
        params_hash = _stable_json_hash(params_json)
        trial_id = f"p_{params_hash[:16]}"

        bars = bars_by_symbol.get(symbol)
        if bars is None or bars.empty:
            bars = next(iter(bars_by_symbol.values()), pd.DataFrame())
        if bars is None or bars.empty:
            continue

        signal_today = _signal_value_from_row_or_map(
            symbol=symbol,
            strategy_kind=strategy_kind,
            row=row,
            signal_map=signals_by_kind_symbol,
        )
        direction = 1 if signal_today > 0 else -1 if signal_today < 0 else 0

        levels = compute_levels_support_resistance(bars, direction=direction)
        risk_payload = compute_rr_and_invalidation(
            direction=direction,
            entry=_as_float(levels.get("entry")),
            stop=_as_float(levels.get("stop")),
            target=_as_float(levels.get("target")),
        )
        opportunity = compute_opportunity_score(
            bars=bars,
            strategy_direction=direction,
            strategy_kind=strategy_kind,
            levels_payload=levels,
        )

        summary = _as_dict(params_json.get("_summary"))
        row_for_confidence = {
            "strategy_kind": strategy_kind,
            "best_params_json": params_json,
            "cagr": _as_float(row.get("cagr")),
            "pnl": _as_float(row.get("pnl")),
            "efficiency": _as_float(row.get("efficiency")),
            "n_fills": _as_int(row.get("n_fills")),
            "sharpe": _as_float(row.get("sharpe"), _as_float(summary.get("sharpe"))),
            "max_drawdown": _as_float(row.get("max_drawdown"), _as_float(summary.get("max_drawdown"))),
        }
        same_rows = by_symbol_kind_rows.get((symbol, strategy_kind), [])
        returns = returns_by_kind.get(strategy_kind, [])
        trade_ledger = ledger_by_kind.get(strategy_kind, [])
        seed_key = f"{rid}:{symbol}:{strategy_kind}:{trial_id}"
        confidence = compute_confidence_score(
            row=row_for_confidence,
            same_strategy_rows=same_rows,
            walk_forward_rows=wf_rows,
            walk_forward_summary=wf_oos_summary_by_kind.get(strategy_kind),
            trade_ledger=trade_ledger,
            returns=returns,
            mc_paths=int(settings.MC_NUM_PATHS),
            random_seed=deterministic_seed_from_key(seed_key),
        )
        as_of_date = None
        try:
            if len(bars.index) > 0:
                as_of_ts = pd.to_datetime(bars.index[-1], errors="coerce")
                if pd.notna(as_of_ts):
                    as_of_date = as_of_ts.date().isoformat()
        except Exception:
            as_of_date = None

        page_model = build_decision_page(
            symbol=symbol,
            strategy_kind=strategy_kind,
            trial_id=trial_id,
            strategy_direction=direction,
            levels=levels,
            risk_payload=risk_payload,
            opportunity=opportunity,
            confidence=confidence,
            extra_explain={
                "params_hash": params_hash,
                "signal_today": signal_today,
                "source": "post_run_worker",
            },
            as_of_date=as_of_date,
        )
        page_payload = page_model.model_dump(mode="json")
        status = str(page_payload.get("status") or "watch")

        db.execute(
            text(
                """
                insert into strategy_decision(
                    run_id, symbol, strategy_kind, trial_id, rank,
                    params_hash, params_json,
                    opportunity_score, confidence_score,
                    opportunity_subscores, confidence_subscores,
                    decision_page_json, explain_json, status, computed_at
                ) values (
                    :run_id, :symbol, :strategy_kind, :trial_id, :rank,
                    :params_hash, cast(:params_json as jsonb),
                    :opportunity_score, :confidence_score,
                    cast(:opportunity_subscores as jsonb), cast(:confidence_subscores as jsonb),
                    cast(:decision_page_json as jsonb), cast(:explain_json as jsonb), :status, :computed_at
                )
                on conflict (run_id, symbol, strategy_kind, trial_id)
                do update set
                    rank = excluded.rank,
                    params_hash = excluded.params_hash,
                    params_json = excluded.params_json,
                    opportunity_score = excluded.opportunity_score,
                    confidence_score = excluded.confidence_score,
                    opportunity_subscores = excluded.opportunity_subscores,
                    confidence_subscores = excluded.confidence_subscores,
                    decision_page_json = excluded.decision_page_json,
                    explain_json = excluded.explain_json,
                    status = excluded.status,
                    computed_at = excluded.computed_at
                """
            ),
            {
                "run_id": rid,
                "symbol": symbol,
                "strategy_kind": strategy_kind,
                "trial_id": trial_id,
                "rank": _as_int(row.get("rank")),
                "params_hash": params_hash,
                "params_json": _json_dumps_pg(params_json),
                "opportunity_score": _as_float(opportunity.get("total"), 0.0),
                "confidence_score": _as_float(confidence.get("total"), 0.0),
                "opportunity_subscores": _json_dumps_pg(opportunity.get("layers") or {}),
                "confidence_subscores": _json_dumps_pg(confidence.get("layers") or {}),
                "decision_page_json": _json_dumps_pg(page_payload),
                "explain_json": _json_dumps_pg(page_payload.get("explain") or {}),
                "status": status,
                "computed_at": _utcnow(),
            },
        )

def _persist_optimization_timing(
    *,
    db: Session,
    rid: UUID,
    out: dict[str, Any],
) -> None:
    """Persist optimization timing metrics as RunMetric rows and optional profile artifact."""
    timing = dict(out.get("optimization_timing") or {})
    if not timing:
        return

    _OPT_METRICS = ("load_ms", "bank_ms", "trial_total_ms", "n_trials_run", "avg_trial_ms", "cache_hits", "cache_misses")
    for metric_name in _OPT_METRICS:
        value = _as_float(timing.get(metric_name))
        if value is None:
            continue
        db.execute(
            text(
                """
                insert into run_metric(run_id, symbol, metric_name, metric_value)
                values (:run_id, :symbol, :name, :value)
                on conflict (run_id, symbol, metric_name)
                do update set metric_value = excluded.metric_value
                """
            ),
            {
                "run_id": rid,
                "symbol": "__opt__",
                "name": f"opt.{metric_name}",
                "value": value,
            },
        )

    profile_text = timing.get("profile_text")
    if profile_text and isinstance(profile_text, str):
        try:
            object_key = f"runs/{rid}/_debug/profile.txt"
            size_bytes, sha256, effective_key = _upload_text(object_key, profile_text, db=db)
            _insert_artifact_row(
                db=db,
                rid=rid,
                symbol="__opt__",
                artifact_type="profile_txt",
                name="optimize_profile",
                object_key=effective_key,
                content_type="text/plain",
                size_bytes=size_bytes,
                sha256=sha256,
            )
        except Exception:
            pass


def _upload_perf_profile(
    *,
    db: Session,
    rid: UUID,
    out: dict[str, Any],
    perf_phases: dict[str, Any],
    total_ms: float,
) -> None:
    """Build and upload runs/{run_id}/_perf/profile.json with nested timing data."""
    pipeline_perf = dict(out.get("_perf") or {})
    opt_timing = dict(out.get("optimization_timing") or {})

    params_tested = int(opt_timing.get("n_trials_run", 0) or 0)

    # Fold counts from nested _perf
    folds_by_kind: dict[str, list] = dict(pipeline_perf.get("folds_by_kind") or {})
    horizons_raw = dict(pipeline_perf.get("horizons") or {})

    # For multi-horizon runs, aggregate fold counts from nested horizon perfs
    if horizons_raw and not folds_by_kind:
        for h_perf in horizons_raw.values():
            if isinstance(h_perf, dict):
                for k, v in dict(h_perf.get("folds_by_kind") or {}).items():
                    folds_by_kind.setdefault(k, []).extend(v if isinstance(v, list) else [])
        params_tested = params_tested or sum(
            int(h.get("folds_count", 0)) * int(opt_timing.get("n_trials_run", 0) or 0)
            for h in horizons_raw.values()
            if isinstance(h, dict)
        )

    folds_total = sum(len(v) for v in folds_by_kind.values())
    if not folds_total and horizons_raw:
        folds_total = sum(
            int(h.get("folds_count", 0))
            for h in horizons_raw.values()
            if isinstance(h, dict)
        )

    profile: dict[str, Any] = {
        "generated_at": _utcnow().isoformat(),
        "total_ms": round(total_ms, 2),
        "cpu_threads": int(os.cpu_count() or 1),
        "phases_ms": perf_phases,
        "horizons": horizons_raw,
        "folds_by_kind": folds_by_kind,
        "folds_total": folds_total,
        "params_tested": params_tested,
        "opt_timing": {k: v for k, v in opt_timing.items() if k != "profile_text"},
    }

    object_key = f"runs/{rid}/_perf/profile.json"
    size_bytes, sha256, effective_key = _upload_json(object_key, profile, db=db)
    _insert_artifact_row(
        db=db,
        rid=rid,
        symbol="__perf__",
        artifact_type="perf_profile",
        name="perf_profile",
        object_key=effective_key,
        content_type="application/json",
        size_bytes=size_bytes,
        sha256=sha256,
    )
    logger.info(
        "[perf] run=%s total=%.0f ms pipeline=%.0f ms folds=%d params=%d",
        rid,
        total_ms,
        float(perf_phases.get("pipeline_ms", 0)),
        folds_total,
        params_tested,
    )


def _persist_pipeline_output(
    *,
    db: Session,
    rid: UUID,
    out: dict,
    default_symbol: str,
    spec_json: dict[str, Any] | None = None,
    dataset_meta: dict[str, Any] | None = None,
    dataset_hash: str | None = None,
) -> None:
    # --- 0) run-level metrics + fills + position ledger ---
    strategy_results_for_metrics = out.get("strategy_results") or {}
    symbols_seen: set[str] = set()
    for payload_any in dict(strategy_results_for_metrics).values():
        payload = payload_any if isinstance(payload_any, dict) else {}
        for sym in list(payload.get("symbols") or []):
            s = str(sym).strip()
            if s:
                symbols_seen.add(s)
    metrics_symbol = "__ALL__"
    if default_symbol and default_symbol != "__ALL__" and len(symbols_seen) <= 1:
        metrics_symbol = str(default_symbol)

    metrics = dict(out.get("metrics") or {})
    for metric_name, metric_value in metrics.items():
        value = _as_float(metric_value)
        if value is None:
            continue
        db.execute(
            text(
                """
                insert into run_metric(run_id, symbol, metric_name, metric_value)
                values (:run_id, :symbol, :name, :value)
                on conflict (run_id, symbol, metric_name)
                do update set metric_value = excluded.metric_value
                """
            ),
            {
                "run_id": rid,
                "symbol": metrics_symbol,
                "name": str(metric_name),
                "value": value,
            },
        )

    fill_rows = out.get("fills") or []
    for row in fill_rows:
        ts = _to_pg_ts(row.get("timestamp"))
        if ts is None:
            continue
        qty = _as_float(row.get("qty"), 0.0) or 0.0
        price = _as_float(row.get("price"), 0.0) or 0.0
        fees = _as_float(row.get("fees"), None)
        if fees is None:
            fees = _as_float(row.get("cost"), 0.0) or 0.0
        notional = _as_float(row.get("notional"), abs(qty * price)) or abs(qty * price)
        side_raw = str(row.get("side") or "").strip().upper()
        side = side_raw if side_raw else ("BUY" if qty >= 0 else "SELL")
        symbol = str(row.get("symbol") or default_symbol or "__ALL__")

        db.execute(
            text(
                """
                insert into fill(
                  id, run_id, timestamp, symbol, side, qty, price, fees, notional, meta
                ) values (
                  :id, :run_id, :ts, :symbol, :side, :qty, :price, :fees, :notional, cast(:meta as jsonb)
                )
                """
            ),
            {
                "id": uuid4(),
                "run_id": rid,
                "ts": ts,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": price,
                "fees": fees,
                "notional": notional,
                "meta": _json_dumps_pg(row.get("meta") or {}),
            },
        )

    def _row_num(row: dict, keys: list[str], default: float = 0.0) -> float:
        for key in keys:
            if key in row:
                value = _as_float(row.get(key))
                if value is not None:
                    return value
        return default

    pos_rows = out.get("position_ledger") or []
    for row in pos_rows:
        ts = _to_pg_ts(row.get("timestamp"))
        if ts is None:
            continue
        symbol = str(row.get("symbol") or default_symbol or "__ALL__")
        db.execute(
            text(
                """
                insert into position_ledger(
                  id, run_id, timestamp, symbol,
                  available_qty, cmp, position_value_cost,
                  pnl_realise, pnl_latent, mark_price
                ) values (
                  :id, :run_id, :ts, :symbol,
                  :available_qty, :cmp, :pvc,
                  :pnl_r, :pnl_l, :mark
                )
                """
            ),
            {
                "id": uuid4(),
                "run_id": rid,
                "ts": ts,
                "symbol": symbol,
                "available_qty": _row_num(row, ["available_qty", "available_quantity"]),
                "cmp": _row_num(row, ["cmp"]),
                "pvc": _row_num(row, ["position_value_cost"]),
                "pnl_r": _row_num(row, ["pnl_realise", "pnl_realized"]),
                "pnl_l": _row_num(row, ["pnl_latent"]),
                "mark": _row_num(row, ["mark_price", "close_du_jour", "close du jour", "_mark"]),
            },
        )

    # --- 1) plot artifacts ---
    plot_artifacts = (out.get("plot_artifacts") or {}).get("symbols") or {}
    for sym, fig_json in plot_artifacts.items():
        if not fig_json:
            continue
        object_key = f"runs/{rid}/symbols/{sym}/plots/price_indicators_trades.json"
        size_bytes, sha256, effective_key = _upload_json(object_key, fig_json, db=db)
        _insert_artifact_row(
            db=db,
            rid=rid,
            symbol=str(sym),
            artifact_type="plotly_json",
            name="price_indicators_trades",
            object_key=effective_key,
            content_type="application/json",
            size_bytes=size_bytes,
            sha256=sha256,
        )

    # --- 1.5) batch period artifacts ---
    batch_period = out.get("batch_period")
    if isinstance(batch_period, dict):
        bp_symbol = str(default_symbol or "__ALL__")
        bp_mode = str(batch_period.get("mode") or "").strip().lower()
        bp_walk_forward = dict(batch_period.get("walk_forward") or {}) if isinstance(batch_period.get("walk_forward"), dict) else {}
        bp_horizon = str(bp_walk_forward.get("horizon") or "medium").strip().lower() or "medium"
        bp_prefix = (
            f"runs/{rid}/wfo/{bp_symbol}/{bp_horizon}"
            if bp_mode == "walk_forward"
            else f"runs/{rid}/symbols/{bp_symbol}/batch_period"
        )
        results_rows = batch_period.get("results") or []
        if isinstance(results_rows, list) and results_rows:
            results_df = pd.DataFrame(results_rows)
            if not results_df.empty:
                object_key = f"{bp_prefix}/results.csv"
                size_bytes, sha256, effective_key = _upload_csv(object_key, results_df, db=db)
                _insert_artifact_row(
                    db=db,
                    rid=rid,
                    symbol=bp_symbol,
                    artifact_type="batch_period_csv",
                    name="batch_period.results",
                    object_key=effective_key,
                    content_type="text/csv",
                    size_bytes=size_bytes,
                    sha256=sha256,
                )

        heatmap_json = batch_period.get("heatmap")
        if isinstance(heatmap_json, dict) and heatmap_json:
            object_key = f"{bp_prefix}/heatmap.json"
            size_bytes, sha256, effective_key = _upload_json(object_key, heatmap_json, db=db)
            _insert_artifact_row(
                db=db,
                rid=rid,
                symbol=bp_symbol,
                artifact_type="batch_period_plotly_json",
                name="batch_period.heatmap",
                object_key=effective_key,
                content_type="application/json",
                size_bytes=size_bytes,
                sha256=sha256,
            )

    strategy_results = out.get("strategy_results") or {}
    _persist_warmup_artifacts(
        db=db,
        rid=rid,
        out=out,
        spec_json=spec_json,
        dataset_hash=dataset_hash,
    )
    strategy_summary_map = _collect_strategy_summary_by_symbol(strategy_results, default_symbol)

    # --- 2) leaderboard ---
    leaderboard_rows = out.get("leaderboard") or []
    rank_counter: dict[tuple[str, str], int] = {}

    for row in leaderboard_rows:
        strategy_kind = str(row.get("Strategy") or row.get("strategy_kind") or "").strip().lower()
        if not strategy_kind:
            continue
        symbol = str(row.get("symbol") or default_symbol or "__ALL__")
        symbol_key = symbol.strip().upper() if symbol and symbol != "__ALL__" else "__ALL__"
        rank_key = (symbol, strategy_kind)
        rank_counter[rank_key] = rank_counter.get(rank_key, 0) + 1
        rank = _as_int(row.get("rank"), rank_counter[rank_key]) or rank_counter[rank_key]

        best_params_json = _as_dict(row.get("best_params_json"))
        row_param_values: dict[str, Any] = {}
        for k in row.keys():
            key = str(k)
            if not (key.startswith("strategy.") or key.startswith("portfolio.")):
                continue
            val = _sanitize_for_json(row.get(k))
            if val is None:
                continue
            row_param_values[key] = val
        # Preserve explicit row parameter values for each variation.
        best_params_json = {**best_params_json, **row_param_values}

        row_summary = {
            "total_return": _as_float(row.get("total_return")),
            "win_pct": _normalize_win_pct(_as_float(row.get("win_pct"))),
            "max_drawdown": _as_float(row.get("max_drawdown")),
            "sharpe": _as_float(row.get("sharpe")),
        }
        if rank == 1:
            strategy_summary = strategy_summary_map.get((symbol_key, strategy_kind), {})
            merged_summary: dict[str, float] = {}
            for metric_key in ("total_return", "win_pct", "max_drawdown", "sharpe"):
                value = row_summary.get(metric_key)
                if value is None:
                    value = _as_float(strategy_summary.get(metric_key))
                if value is None:
                    continue
                merged_summary[metric_key] = float(value)
            if merged_summary:
                best_params_json["_summary"] = merged_summary

        best_params_clean: dict[str, Any] = {}
        for k, v in best_params_json.items():
            sv = _sanitize_for_json(v)
            if sv is None:
                continue
            best_params_clean[str(k)] = sv
        best_params_json = best_params_clean

        db.execute(
            text(
                """
                insert into strategy_leaderboard(
                  run_id, symbol, strategy_kind, rank,
                  pnl, cagr, efficiency, n_fills,
                  signal_label, signal_today, signal_date, best_params_json
                ) values (
                  :run_id, :symbol, :strategy_kind, :rank,
                  :pnl, :cagr, :efficiency, :n_fills,
                  :signal_label, :signal_today, :signal_date, cast(:best_params_json as jsonb)
                )
                on conflict (run_id, symbol, strategy_kind, rank)
                do update set
                  pnl = excluded.pnl,
                  cagr = excluded.cagr,
                  efficiency = excluded.efficiency,
                  n_fills = excluded.n_fills,
                  signal_label = excluded.signal_label,
                  signal_today = excluded.signal_today,
                  signal_date = excluded.signal_date,
                  best_params_json = excluded.best_params_json
                """
            ),
            {
                "run_id": rid,
                "symbol": symbol,
                "strategy_kind": strategy_kind,
                "rank": rank,
                "pnl": _as_float(row.get("pnl")),
                "cagr": _as_float(row.get("cagr")),
                "efficiency": _as_float(row.get("efficiency")),
                "n_fills": _as_int(row.get("n_fills")),
                "signal_label": row.get("signal_label"),
                "signal_today": _as_float(row.get("signal_today"), 0.0),
                "signal_date": _to_pg_ts(row.get("signal_date") or row.get("timestamp")),
                "best_params_json": _json_dumps_pg(best_params_json),
            },
        )

    # Snapshot table may be absent in some deployments; don't fail the run.
    try:
        with db.begin_nested():
            _update_best_snapshots(db, run_id=rid)
    except Exception:
        pass

    is_single_backtest_like = len(leaderboard_rows) == 0

    # --- 3) per-strategy artifacts (plots + ledgers) ---
    for strategy_kind_raw, payload in strategy_results.items():
        strategy_kind = str(strategy_kind_raw).strip().lower()
        if not strategy_kind:
            continue

        target_symbols = [str(s) for s in list(payload.get("symbols") or []) if str(s).strip()]
        if not target_symbols:
            target_symbols = [default_symbol or "__ALL__"]

        strategy_plot_map = dict(payload.get("plot_artifacts") or {})
        for sym, fig_json in strategy_plot_map.items():
            if not fig_json:
                continue
            object_key = f"runs/{rid}/symbols/{sym}/strategies/{strategy_kind}/plots/price_indicators_trades.json"
            size_bytes, sha256, effective_key = _upload_json(object_key, fig_json, db=db)
            _insert_artifact_row(
                db=db,
                rid=rid,
                symbol=str(sym),
                artifact_type="strategy_plotly_json",
                name=f"{strategy_kind}.price_indicators_trades",
                object_key=effective_key,
                content_type="application/json",
                size_bytes=size_bytes,
                sha256=sha256,
            )

        summary_plots = dict(payload.get("summary_plot_artifacts") or {})
        for plot_name, fig_json in summary_plots.items():
            if not fig_json:
                continue
            safe_name = str(plot_name).strip().lower().replace(" ", "_")
            if not safe_name:
                continue
            for sym in target_symbols:
                object_key = f"runs/{rid}/symbols/{sym}/strategies/{strategy_kind}/plots/{safe_name}.json"
                size_bytes, sha256, effective_key = _upload_json(object_key, fig_json, db=db)
                _insert_artifact_row(
                    db=db,
                    rid=rid,
                    symbol=str(sym),
                    artifact_type="strategy_plotly_json",
                    name=f"{strategy_kind}.{safe_name}",
                    object_key=effective_key,
                    content_type="application/json",
                    size_bytes=size_bytes,
                    sha256=sha256,
                )

        perf_rows = payload.get("trade_performance") or []
        if perf_rows:
            perf_df = pd.DataFrame(perf_rows)
            if not perf_df.empty:
                perf_df = perf_df.rename(columns={"Value": "value", "metric_name": "metric"})
                if "metric" not in perf_df.columns and len(perf_df.columns) > 0:
                    perf_df = perf_df.rename(columns={perf_df.columns[0]: "metric"})
                if "value" not in perf_df.columns and len(perf_df.columns) > 1:
                    perf_df = perf_df.rename(columns={perf_df.columns[1]: "value"})
                cols = [c for c in ("metric", "value") if c in perf_df.columns]
                perf_df = perf_df[cols] if cols else perf_df

                for sym in target_symbols:
                    object_key = f"runs/{rid}/symbols/{sym}/strategies/{strategy_kind}/tables/trade_performance.csv"
                    size_bytes, sha256, effective_key = _upload_csv(object_key, perf_df, db=db)
                    _insert_artifact_row(
                        db=db,
                        rid=rid,
                        symbol=str(sym),
                        artifact_type="strategy_trade_performance_csv",
                        name=f"{strategy_kind}.trade_performance",
                        object_key=effective_key,
                        content_type="text/csv",
                        size_bytes=size_bytes,
                        sha256=sha256,
                    )

                # Single backtests rely on run_metric for the metrics tab.
                if is_single_backtest_like:
                    for perf_row in perf_df.to_dict("records"):
                        metric_name = str(perf_row.get("metric") or "").strip()
                        metric_value = _as_float(perf_row.get("value"))
                        if not metric_name or metric_value is None:
                            continue
                        db.execute(
                            text(
                                """
                                insert into run_metric(run_id, symbol, metric_name, metric_value)
                                values (:run_id, :symbol, :name, :value)
                                on conflict (run_id, symbol, metric_name)
                                do update set metric_value = excluded.metric_value
                                """
                            ),
                            {
                                "run_id": rid,
                                "symbol": "__ALL__",
                                "name": metric_name,
                                "value": metric_value,
                            },
                        )

        ledger_rows = payload.get("trade_ledger") or []
        if ledger_rows:
            ledger_df = pd.DataFrame(ledger_rows)
            if not ledger_df.empty:
                if "symbol" in ledger_df.columns:
                    grouped = [(str(sym), sub.copy()) for sym, sub in ledger_df.groupby("symbol", sort=False)]
                else:
                    grouped = [(default_symbol or "__ALL__", ledger_df)]

                for sym, sub in grouped:
                    object_key = f"runs/{rid}/symbols/{sym}/strategies/{strategy_kind}/ledgers/trade_ledger.csv"
                    size_bytes, sha256, effective_key = _upload_csv(object_key, sub, db=db)
                    _insert_artifact_row(
                        db=db,
                        rid=rid,
                        symbol=str(sym),
                        artifact_type="strategy_trade_ledger_csv",
                        name=f"{strategy_kind}.trade_ledger",
                        object_key=effective_key,
                        content_type="text/csv",
                        size_bytes=size_bytes,
                        sha256=sha256,
                    )

        for cal_key in ("opportunity_calibration", "confidence_calibration"):
            cal_rows = payload.get(cal_key) or []
            if not cal_rows:
                continue
            cal_df = pd.DataFrame(cal_rows)
            if cal_df.empty:
                continue

            for sym in target_symbols:
                object_key = f"runs/{rid}/symbols/{sym}/strategies/{strategy_kind}/tables/{cal_key}.csv"
                size_bytes, sha256, effective_key = _upload_csv(object_key, cal_df, db=db)
                _insert_artifact_row(
                    db=db,
                    rid=rid,
                    symbol=str(sym),
                    artifact_type="strategy_decision_calibration_csv",
                    name=f"{strategy_kind}.{cal_key}",
                    object_key=effective_key,
                    content_type="text/csv",
                    size_bytes=size_bytes,
                    sha256=sha256,
                )

    safe_spec = dict(spec_json or {})
    safe_dataset_meta = dict(dataset_meta or {})

    # Extended run modules are best-effort and additive.
    if _has_table(db, "run_integrity_check"):
        try:
            with db.begin_nested():
                _persist_integrity(
                    db=db,
                    rid=rid,
                    out=out,
                    spec_json=safe_spec,
                    dataset_meta=safe_dataset_meta,
                )
        except Exception:
            pass

    if _has_table(db, "run_fold"):
        try:
            with db.begin_nested():
                _persist_walk_forward_folds(
                    db=db,
                    rid=rid,
                    out=out,
                    default_symbol=default_symbol,
                )
        except Exception:
            pass

    if _has_table(db, "run_significance"):
        try:
            with db.begin_nested():
                _persist_significance(
                    db=db,
                    rid=rid,
                    out=out,
                    spec_json=safe_spec,
                )
        except Exception:
            pass

    if _has_table(db, "run_risk"):
        try:
            with db.begin_nested():
                _persist_risk(
                    db=db,
                    rid=rid,
                    out=out,
                    spec_json=safe_spec,
                )
        except Exception:
            pass

    try:
        with db.begin_nested():
            _persist_mean_reversion(
                db=db,
                rid=rid,
                out=out,
                spec_json=safe_spec,
            )
    except Exception:
        pass

    try:
        with db.begin_nested():
            _persist_optimization_timing(db=db, rid=rid, out=out)
    except Exception:
        pass

    # Decisions are best-effort and should never invalidate persisted run outputs.
    # Use a savepoint so missing/partial decision schema doesn't abort the main tx.
    simple_wfo = out.get("simple_wfo_multi_horizon")
    simple_wfo_enabled = isinstance(simple_wfo, dict) and _as_bool(simple_wfo.get("enabled"), False)
    if _has_table(db, "strategy_decision") and not simple_wfo_enabled:
        try:
            with db.begin_nested():
                _persist_decisions(
                    db=db,
                    rid=rid,
                    out=out,
                    default_symbol=default_symbol,
                )
        except Exception:
            pass


def execute_run(run_id: str) -> dict:
    db: Session = SessionLocal()
    cancel_redis = _redis_for_cancel()
    job_id = _rq_job_id()
    temp_dataset_file: Path | None = None
    temp_uploaded_files: list[Path] = []
    temp_store_files: list[Path] = []
    dataset_meta: dict[str, Any] = {}
    dataset_hash: str | None = None
    code_version: str | None = None
    run_has_integrity_status = False

    _t_exe_start = time.perf_counter()
    _perf_phases: dict[str, Any] = {}

    try:
        rid = UUID(run_id)
        run_has_integrity_status = _has_column(db, "run", "integrity_status")

        # 1) fetch run spec + dataset_id
        row = db.execute(
            text("select spec_json, dataset_id from run where id = :id"),
            {"id": rid},
        ).mappings().first()
        _check_cancel(cancel_redis, job_id)
        if not row:
            raise RuntimeError(f"Run not found: {rid}")

        spec_json = dict(row["spec_json"] or {})
        dataset_id = row.get("dataset_id")
        dataset_meta, dataset_hash = _dataset_meta_for_run(
            db,
            dataset_id=dataset_id,
            spec_json=spec_json,
        )
        code_version = _resolve_code_version()

        # 1.1) Choose data source in this priority:
        #      (A) uploaded dataset attached to the run
        #      (B) canonical store mode (data.source == "store")
        if dataset_id is not None:
            dataset_row = db.execute(
                text(
                    """
                    select id, source, symbol, timeframe, data_hash, filename, object_key
                    from dataset
                    where id = :id
                    """
                ),
                {"id": dataset_id},
            ).mappings().first()
            if not dataset_row:
                raise RuntimeError(f"Dataset not found: {dataset_id}")

            temp_dataset_file = _materialize_dataset_file(
                filename=str(dataset_row.get("filename") or dataset_row.get("symbol") or "upload.xlsx"),
                data_hash=str(dataset_row["data_hash"]),
                object_key=str(dataset_row["object_key"]) if dataset_row.get("object_key") else None,
            )
            temp_uploaded_files.append(temp_dataset_file)
            spec_json = _apply_uploaded_dataset(spec_json, dataset_row, temp_dataset_file)

        else:
            data_cfg = dict(spec_json.get("data") or {})
            dataset_symbol_map_raw = data_cfg.get("dataset_symbol_map")
            dataset_symbol_map: dict[str, str] = {}
            if isinstance(dataset_symbol_map_raw, dict):
                for k, v in dataset_symbol_map_raw.items():
                    sym = str(k).strip().upper()
                    dsid = str(v).strip()
                    if sym and dsid:
                        dataset_symbol_map[sym] = dsid

            if dataset_symbol_map:
                raw_symbols = spec_json.get("symbols") or data_cfg.get("symbols") or []
                symbols = _normalize_symbols(raw_symbols)
                if not symbols:
                    symbols = [s for s in dataset_symbol_map.keys()]
                if not symbols:
                    raise RuntimeError("data.dataset_symbol_map requires symbols=[...] in spec")

                local_paths: dict[str, Path] = {}
                dataset_file_cache: dict[str, Path] = {}

                for sym in symbols:
                    _check_cancel(cancel_redis, job_id)
                    dsid_raw = dataset_symbol_map.get(str(sym).strip().upper())
                    if not dsid_raw:
                        raise RuntimeError(f"Missing dataset id mapping for symbol: {sym}")

                    dsid = UUID(dsid_raw)
                    dsid_key = str(dsid)

                    if dsid_key in dataset_file_cache:
                        local_paths[str(sym)] = dataset_file_cache[dsid_key]
                        continue

                    dataset_row = db.execute(
                        text(
                            """
                            select id, source, symbol, timeframe, data_hash, filename, object_key
                            from dataset
                            where id = :id
                            """
                        ),
                        {"id": dsid},
                    ).mappings().first()
                    if not dataset_row:
                        raise RuntimeError(f"Dataset not found in dataset_symbol_map: {dsid}")

                    p = _materialize_dataset_file(
                        filename=str(dataset_row.get("filename") or dataset_row.get("symbol") or "upload.xlsx"),
                        data_hash=str(dataset_row["data_hash"]),
                        object_key=str(dataset_row["object_key"]) if dataset_row.get("object_key") else None,
                    )
                    temp_uploaded_files.append(p)
                    dataset_file_cache[dsid_key] = p
                    local_paths[str(sym)] = p

                spec_json = _apply_uploaded_dataset_map(spec_json, local_paths)

            elif str(data_cfg.get("source") or "").strip().lower() == "store":
                raw_symbols = spec_json.get("symbols") or data_cfg.get("symbols") or []
                symbols = _normalize_symbols(raw_symbols)
                if not symbols:
                    raise RuntimeError("data.source='store' requires symbols=[...] in spec")

                local_paths: dict[str, Path] = {}
                for sym in symbols:
                    _check_cancel(cancel_redis, job_id)
                    key = _store_key_for_symbol(db=db, symbol=sym, timeframe="1D")
                    _check_cancel(cancel_redis, job_id)
                    p = _materialize_store_parquet(object_key=key)
                    temp_store_files.append(p)
                    local_paths[str(sym)] = p

                spec_json = _apply_store_as_parquet(spec_json, local_paths)

        spec_json = _apply_wfo_defaults(spec_json)
        portfolio_cfg = dict(spec_json.get("portfolio") or {})
        portfolio_cfg.setdefault("fill_price_model", "next_open")
        portfolio_cfg.setdefault("mtm_model", "close_t1")
        spec_json["portfolio"] = portfolio_cfg

        _persist_run_repro_metadata(
            db,
            rid=rid,
            spec_json=spec_json,
            dataset_hash=dataset_hash,
            code_version=code_version,
        )

        # 2) mark running
        db.execute(
            text(
                """
                update run
                set status='running',
                    started_at=:ts,
                    error_message=null
                """
                + (", integrity_status='pending'" if run_has_integrity_status else "")
                + """
                where id=:id
                """
            ),
            {"ts": _utcnow(), "id": rid},
        )
        db.commit()
        _set_progress(db, rid, job_id, stage="running", pct=0, message="Run started")

        # 2.5) idempotency on retries: wipe prior outputs
        db.execute(text("delete from run_metric where run_id = :id"), {"id": rid})
        db.execute(text("delete from fill where run_id = :id"), {"id": rid})
        db.execute(text("delete from position_ledger where run_id = :id"), {"id": rid})
        db.execute(text("delete from strategy_leaderboard where run_id = :id"), {"id": rid})
        if _has_table(db, "strategy_decision"):
            db.execute(text("delete from strategy_decision where run_id = :id"), {"id": rid})
        if _has_table(db, "run_integrity_check"):
            db.execute(text("delete from run_integrity_check where run_id = :id"), {"id": rid})
        if _has_table(db, "run_fold"):
            db.execute(text("delete from run_fold where run_id = :id"), {"id": rid})
        if _has_table(db, "run_significance"):
            db.execute(text("delete from run_significance where run_id = :id"), {"id": rid})
        if _has_table(db, "run_risk"):
            db.execute(text("delete from run_risk where run_id = :id"), {"id": rid})
        db.execute(text("delete from artifact where run_id = :id"), {"id": rid})
        db.commit()

        # 3) run pipeline and persist
        symbols = _normalize_symbols(spec_json.get("symbols") or (spec_json.get("data") or {}).get("symbols") or [])
        total_syms = max(len(symbols), 1)
        if _is_batch_per_symbol_optimization(spec_json) and len(symbols) > 1:
            n_workers = _resolve_batch_symbol_workers(spec_json, total_syms)
            executor_kind = _resolve_batch_symbol_executor_kind(spec_json)
            dataset_path = str(temp_dataset_file) if temp_dataset_file is not None else None

            if n_workers <= 1:
                for i, symbol in enumerate(symbols):
                    _check_cancel(cancel_redis, job_id)
                    _set_progress(db, rid, job_id, stage="running", done=i, total=total_syms, message=f"Running {symbol} ({i+1}/{total_syms})")
                    _, sym_out = _run_symbol_pipeline(spec_json, symbol, dataset_path)
                    _check_cancel(cancel_redis, job_id)
                    _persist_pipeline_output(
                        db=db,
                        rid=rid,
                        out=sym_out,
                        default_symbol=symbol,
                        spec_json=spec_json,
                        dataset_meta=dataset_meta,
                        dataset_hash=dataset_hash,
                    )
                    db.commit()
                    _set_progress(db, rid, job_id, stage="persisted", done=i + 1, total=total_syms, message=f"Saved results for {symbol}")
            else:
                executor_cls = ThreadPoolExecutor if executor_kind == "thread" else ProcessPoolExecutor
                _set_progress(
                    db,
                    rid,
                    job_id,
                    stage="running",
                    pct=0,
                    message=f"Running {total_syms} symbols with {n_workers} {executor_kind} workers",
                )
                with executor_cls(max_workers=n_workers) as ex:
                    futures = {
                        ex.submit(_run_symbol_pipeline, spec_json, symbol, dataset_path): symbol
                        for symbol in symbols
                    }
                    pending = set(futures.keys())
                    done_count = 0
                    while pending:
                        if job_id and _cancel_requested(cancel_redis, job_id):
                            for pf in pending:
                                pf.cancel()
                            ex.shutdown(wait=False, cancel_futures=True)
                            raise RunCanceled("Canceled by user")
                        done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                        if not done:
                            continue

                        for fut in done:
                            symbol = futures[fut]
                            try:
                                out_symbol, sym_out = fut.result()
                            except Exception as e:
                                for pf in pending:
                                    pf.cancel()
                                ex.shutdown(wait=False, cancel_futures=True)
                                raise RuntimeError(f"Symbol run failed for {symbol}: {e}") from e

                            _persist_pipeline_output(
                                db=db,
                                rid=rid,
                                out=sym_out,
                                default_symbol=out_symbol,
                                spec_json=spec_json,
                                dataset_meta=dataset_meta,
                                dataset_hash=dataset_hash,
                            )
                            db.commit()
                            done_count += 1
                            _set_progress(
                                db,
                                rid,
                                job_id,
                                stage="persisted",
                                done=done_count,
                                total=total_syms,
                                message=f"Saved results for {out_symbol} ({done_count}/{total_syms})",
                            )
        else:
            if temp_dataset_file is not None:
                spec_json.setdefault("data", {})
                spec_json["data"]["source"] = "bmce"
                spec_json["data"]["bmce_paths"] = str(temp_dataset_file)
            _check_cancel(cancel_redis, job_id)
            out = run_pipeline(spec_json)
            _check_cancel(cancel_redis, job_id)
            default_symbol = str(symbols[0]) if symbols else "__ALL__"
            _persist_pipeline_output(
                db=db,
                rid=rid,
                out=out,
                default_symbol=default_symbol,
                spec_json=spec_json,
                dataset_meta=dataset_meta,
                dataset_hash=dataset_hash,
            )
            db.commit()

        # 5) mark succeeded
        db.execute(
            text(
                """
                update run
                set status='succeeded',
                    finished_at=:ts
                """
                + (", integrity_status=coalesce(integrity_status, 'pass')" if run_has_integrity_status else "")
                + """
                where id=:id
                """
            ),
            {"ts": _utcnow(), "id": rid},
        )
        db.commit()
        _set_progress(db, rid, job_id, stage="done", pct=100, message="Succeeded")

        return {"run_id": run_id, "status": "succeeded"}

    except RunCanceled as e:
        err_msg = str(e)[:8000]

        # session might be in failed state -> rollback first
        try:
            db.rollback()
        except Exception:
            pass

        # best-effort: progress meta + DB
        try:
            _set_progress(db, rid, job_id, pct=100, stage="canceled", message=err_msg)
        except Exception:
            pass

        try:
            db.execute(
                text("""
                    update run
                    set status='canceled',
                        finished_at=:ts,
                        """ + ("integrity_status=coalesce(integrity_status, 'warn')," if run_has_integrity_status else "") + """
                        error_message=:err,
                        progress_stage='canceled',
                        progress_message=:err,
                        last_heartbeat_at=:ts
                    where id=:id
                """),
                {"ts": _utcnow(), "err": err_msg, "id": rid},
            )
            db.commit()
        except Exception:
            try: db.rollback()
            except Exception: pass

        return {"run_id": run_id, "status": "canceled"}

    except Exception as e:
        err = "".join(traceback.format_exception(type(e), e, e.__traceback__))[:8000]

        # session might be in failed state -> rollback first
        try:
            db.rollback()
        except Exception:
            pass

        # store error in rq meta too (VERY useful for frontend)
        try:
            _set_progress(db, rid, job_id, pct=100, stage="failed", message=err)
        except Exception:
            pass

        try:
            db.execute(
                text("""
                    update run
                    set status='failed',
                        finished_at=:ts,
                        """ + ("integrity_status='fail'," if run_has_integrity_status else "") + """
                        error_message=:err,
                        progress_stage='failed',
                        progress_message='failed',
                        last_heartbeat_at=:ts
                    where id=:id
                """),
                {"ts": _utcnow(), "err": err, "id": rid},
            )
            db.commit()
        except Exception:
            try: db.rollback()
            except Exception: pass

        # IMPORTANT: return error so you can see it in job.result too
        return {"run_id": run_id, "status": "failed", "error": err}


    finally:
        # cleanup uploaded dataset temp file
        if temp_dataset_file is not None and not _is_dataset_cache_path(temp_dataset_file):
            try:
                temp_dataset_file.unlink(missing_ok=True)
            except Exception:
                pass

        for p in temp_uploaded_files:
            if _is_dataset_cache_path(p):
                continue
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

        # cleanup canonical-store parquet temp files
        for p in temp_store_files:
            if _is_dataset_cache_path(p):
                continue
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

        db.close()
