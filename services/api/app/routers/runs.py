# services/api/app/routers/runs.py
from __future__ import annotations

import copy
import csv
from datetime import date, datetime, timezone
import io
import hashlib
import logging
import math
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile
import uuid
from typing import Any
from uuid import UUID
import numpy as np
import pandas as pd
import sqlalchemy as sa
from redis import Redis
from rq import Queue, Retry
from rq.job import Job
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from ..config import settings

from ..db import get_db
from ..services.hash_utils import json_hash
from ..models import (
    Artifact,
    Fill,
    PositionLedger,
    Run,
    RunFold,
    RunIntegrityCheck,
    RunMetric,
    RunRisk,
    RunSignificance,
    StrategyDecision,
    StrategyLeaderboard,
)
from ..schemas.artifacts import ArtifactOut
from ..schemas.runs import (
    DecisionDashboardOut,
    FillOut,
    MaterializeStrategyDetailsRequest,
    MaterializeStrategyDetailsResponse,
    PositionLedgerOut,
    RunCreateRequest,
    RunCreateResponse,
    RunListItemOut,
    RunMetricOut,
    RunFoldOut,
    RunIntegrityCheckOut,
    RunRiskOut,
    RunSignificanceOut,
    StrategyDecisionOut,
    StrategyLeaderboardOut,
    WalkForwardResolveDatesRequest,
    WalkForwardResolveDatesResponse,
)
from ..storage import presign_get, s3_client
from core.quant_core.data import BMCEDataSource, ParquetDataSource, YahooFinanceDataSource
from core.quant_core.s3_keys import build_dataset_object_key as _build_dataset_object_key
from core.quant_core.wfo import resolve_wfo_start_end_dates





logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])

_NON_REUSABLE_RUN_STATUSES = {"failed", "canceled"}
_ACTIVE_RUN_STATUSES = {"queued", "running", "cancel_requested"}


def _parse_cursor(cursor: str | None) -> datetime | None:
    if cursor is None:
        return None

    raw = cursor.strip().replace(" ", "+")
    if not raw:
        return None

    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid cursor; expected ISO8601 timestamp") from exc

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    return ts


def _infer_run_type(spec_json: dict) -> str:
    decision_cfg = dict(spec_json.get("decision_backtest") or {})
    if bool(decision_cfg.get("enabled", False)):
        return "decision_backtest"
    optimization = dict(spec_json.get("optimization") or {})
    n_trials = int(optimization.get("n_trials") or 0)
    kinds = list(optimization.get("kinds") or [])
    return "optimization" if n_trials > 0 or len(kinds) > 0 else "backtest"


def _infer_mode(spec_json: dict[str, Any]) -> str:
    optimization = dict(spec_json.get("optimization") or {})
    walk_forward = dict(optimization.get("walk_forward") or {})
    return "walk_forward" if bool(walk_forward.get("enabled", False)) else "single"


def _assert_wfo_resolved_dates(spec_json: dict[str, Any], *, caller: str) -> None:
    optimization = dict(spec_json.get("optimization") or {})
    walk_forward = dict(optimization.get("walk_forward") or {})
    if not bool(walk_forward.get("enabled", False)):
        return

    missing_fields: list[str] = []
    for field in ("resolved_start_date", "resolved_end_date"):
        if str(walk_forward.get(field) or "").strip():
            continue
        missing_fields.append(f"optimization.walk_forward.{field}")

    if missing_fields:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{caller}: walk_forward.enabled=true requires resolved date bounds before run_pipeline. "
                f"Missing {', '.join(missing_fields)}. "
                "These fields must be produced by core/quant_core/wfo/date_resolution.py "
                "(resolve_wfo_start_end_dates)."
            ),
        )


def _extract_seed(spec_json: dict[str, Any]) -> int | None:
    candidates = [
        ((spec_json.get("optimization") or {}).get("seed") if isinstance(spec_json.get("optimization"), dict) else None),
        ((spec_json.get("analysis") or {}).get("significance", {}).get("seed") if isinstance((spec_json.get("analysis") or {}).get("significance"), dict) else None),
        ((spec_json.get("analysis") or {}).get("risk", {}).get("seed") if isinstance((spec_json.get("analysis") or {}).get("risk"), dict) else None),
    ]
    for raw in candidates:
        if raw is None:
            continue
        try:
            return int(raw)
        except Exception:
            continue
    return None


def _resolve_code_version() -> str | None:
    env_value = str(settings.GIT_COMMIT or "").strip() if hasattr(settings, "GIT_COMMIT") else ""
    if env_value:
        return env_value

    repo_root = Path(__file__).resolve().parents[4]
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


def _resolve_dataset_hash(
    db: Session,
    *,
    dataset_id: UUID | None,
    spec_json: dict[str, Any],
) -> str | None:
    if dataset_id is not None:
        row = db.execute(
            text("select data_hash from dataset where id=:id"),
            {"id": dataset_id},
        ).mappings().first()
        if row and row.get("data_hash"):
            return str(row["data_hash"])
        return None

    data_json = dict(spec_json.get("data") or {})
    dataset_symbol_map = data_json.get("dataset_symbol_map")
    if isinstance(dataset_symbol_map, dict) and dataset_symbol_map:
        canonical = {
            str(sym).strip().upper(): str(dsid).strip()
            for sym, dsid in dataset_symbol_map.items()
            if str(sym).strip() and str(dsid).strip()
        }
        if canonical:
            content = str(sorted(canonical.items())).encode("utf-8")
            return f"map:{hashlib.sha256(content).hexdigest()}"

    return None


def _compute_run_id(spec_hash: str, dataset_id: UUID | None) -> UUID:
    dataset_part = str(dataset_id) if dataset_id is not None else "none"
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{spec_hash}|{dataset_part}")


def _legacy_run_id_candidates(spec_hash: str) -> list[UUID]:
    out: list[UUID] = []
    try:
        out.append(UUID(spec_hash))
    except Exception:
        pass
    out.append(uuid.uuid5(uuid.NAMESPACE_URL, spec_hash))
    return out


def _artifact_strategy_kind(name: str) -> str:
    if not name:
        return ""
    return name.split(".", 1)[0].strip().lower()


def _artifact_base_name(name: str) -> str:
    if not name:
        return ""
    parts = str(name).split(".", 1)
    if len(parts) == 2:
        return parts[1].strip().lower()
    return str(name).strip().lower()


def _as_summary_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _split_best_params_and_summary(raw: Any) -> tuple[dict[str, Any] | None, dict[str, float | None]]:
    if not isinstance(raw, dict):
        return None, {"total_return": None, "win_pct": None, "max_drawdown": None, "sharpe": None}

    params = dict(raw)
    summary_raw = params.pop("_summary", None)
    summary_dict = summary_raw if isinstance(summary_raw, dict) else {}

    summary = {
        "total_return": _as_summary_float(summary_dict.get("total_return")),
        "win_pct": _as_summary_float(summary_dict.get("win_pct")),
        "max_drawdown": _as_summary_float(summary_dict.get("max_drawdown")),
        "sharpe": _as_summary_float(summary_dict.get("sharpe")),
    }
    return params, summary


def _normalize_symbol_key(value: Any) -> str:
    symbol = str(value or "").strip()
    return symbol.upper() if symbol else "__ALL__"


def _normalize_win_pct(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 1.0 and value <= 100.0:
        return value / 100.0
    return value


def _metric_lookup(
    metrics_by_symbol: dict[str, dict[str, float]],
    symbol: str,
    keys: list[str],
) -> float | None:
    candidates = [metrics_by_symbol.get(_normalize_symbol_key(symbol)), metrics_by_symbol.get("__ALL__")]
    for metric_map in candidates:
        if not metric_map:
            continue
        folded = {str(k).strip().lower(): v for k, v in metric_map.items()}
        for key in keys:
            if key in metric_map:
                return metric_map[key]
            low = str(key).strip().lower()
            if low in folded:
                return folded[low]
    return None


def _read_win_rate_from_perf_csv(object_key: str) -> float | None:
    try:
        s3 = s3_client()
        payload = s3.get_object(Bucket=settings.S3_BUCKET, Key=object_key)["Body"].read()
        text = payload.decode("utf-8", errors="ignore")
    except Exception:
        return None

    try:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            metric = str(row.get("metric") or row.get("Metric") or "").strip().lower()
            if metric not in {"win rate", "trade winning %"}:
                continue
            raw = row.get("value", row.get("Value"))
            value = _as_summary_float(raw)
            return _normalize_win_pct(value)
    except Exception:
        return None
    return None


def _list_artifact_keys(db: Session, run_id: UUID) -> list[str]:
    rows = db.query(Artifact.object_key).filter(Artifact.run_id == run_id).all()
    return [str(r[0]) for r in rows if r and r[0]]


def _delete_artifact_objects(object_keys: list[str]) -> tuple[int, int]:
    if not object_keys:
        return 0, 0

    deleted = 0
    failed = 0
    try:
        client = s3_client()
    except Exception:
        return 0, len(object_keys)

    for key in object_keys:
        try:
            client.delete_object(Bucket=settings.S3_BUCKET, Key=key)
            deleted += 1
        except Exception:
            failed += 1
    return deleted, failed


def _purge_run_outputs(db: Session, run_id: UUID, *, delete_objects: bool) -> dict[str, int]:
    object_keys: list[str] = []
    if delete_objects:
        object_keys = _list_artifact_keys(db, run_id)

    metrics_deleted = db.query(RunMetric).filter(RunMetric.run_id == run_id).delete(synchronize_session=False)
    fills_deleted = db.query(Fill).filter(Fill.run_id == run_id).delete(synchronize_session=False)
    positions_deleted = db.query(PositionLedger).filter(PositionLedger.run_id == run_id).delete(synchronize_session=False)
    leaderboard_deleted = (
        db.query(StrategyLeaderboard).filter(StrategyLeaderboard.run_id == run_id).delete(synchronize_session=False)
    )
    decisions_deleted = db.query(StrategyDecision).filter(StrategyDecision.run_id == run_id).delete(synchronize_session=False)
    integrity_deleted = db.query(RunIntegrityCheck).filter(RunIntegrityCheck.run_id == run_id).delete(synchronize_session=False)
    folds_deleted = db.query(RunFold).filter(RunFold.run_id == run_id).delete(synchronize_session=False)
    significance_deleted = db.query(RunSignificance).filter(RunSignificance.run_id == run_id).delete(synchronize_session=False)
    risk_deleted = db.query(RunRisk).filter(RunRisk.run_id == run_id).delete(synchronize_session=False)
    artifacts_deleted = db.query(Artifact).filter(Artifact.run_id == run_id).delete(synchronize_session=False)

    objects_deleted = 0
    object_delete_failed = 0
    if delete_objects:
        objects_deleted, object_delete_failed = _delete_artifact_objects(object_keys)

    return {
        "metrics_deleted": int(metrics_deleted or 0),
        "fills_deleted": int(fills_deleted or 0),
        "positions_deleted": int(positions_deleted or 0),
        "leaderboard_deleted": int(leaderboard_deleted or 0),
        "decisions_deleted": int(decisions_deleted or 0),
        "integrity_deleted": int(integrity_deleted or 0),
        "folds_deleted": int(folds_deleted or 0),
        "significance_deleted": int(significance_deleted or 0),
        "risk_deleted": int(risk_deleted or 0),
        "artifacts_deleted": int(artifacts_deleted or 0),
        "artifact_objects_deleted": int(objects_deleted),
        "artifact_object_delete_failed": int(object_delete_failed),
    }


def _normalize_symbols(raw_symbols: Any) -> list[str]:
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


def _parse_optional_iso_date(raw: Any, *, field_name: str) -> date | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a valid ISO date (YYYY-MM-DD).") from exc


def _extract_symbol_path(paths: Any, symbol: str) -> Any:
    if isinstance(paths, dict):
        exact = paths.get(symbol)
        if exact is not None:
            return exact
        upper_key_map = {str(k).strip().upper(): v for k, v in paths.items()}
        return upper_key_map.get(str(symbol).strip().upper())
    return paths


def _bars_for_symbol_from_market_data(md: Any, symbol: str) -> pd.DataFrame:
    sym = str(symbol).strip()
    if hasattr(md, "get"):
        try:
            bars = md.get(sym)
            if isinstance(bars, pd.DataFrame):
                return bars
        except Exception:
            pass

    bars_map = dict(getattr(md, "bars", {}) or {})
    if sym in bars_map and isinstance(bars_map[sym], pd.DataFrame):
        return bars_map[sym]
    if not bars_map:
        raise HTTPException(status_code=400, detail=f"No bars found for symbol {sym}.")
    first = next(iter(bars_map.values()))
    if not isinstance(first, pd.DataFrame):
        raise HTTPException(status_code=400, detail=f"Bars payload for symbol {sym} is not a dataframe.")
    return first


def _load_symbol_bars_for_wfo(
    *,
    source: str,
    symbol: str,
    interval: str,
    data_json: dict[str, Any],
) -> pd.DataFrame:
    source_norm = str(source or "").strip().lower()
    symbol_norm = str(symbol).strip()
    interval_norm = str(interval or "1d").strip() or "1d"

    if source_norm == "parquet":
        parquet_paths = _extract_symbol_path(data_json.get("parquet_paths"), symbol_norm)
        if parquet_paths in (None, ""):
            raise HTTPException(
                status_code=400,
                detail=f"Missing data.parquet_paths for symbol '{symbol_norm}' during walk-forward date resolution.",
            )
        ds = ParquetDataSource(timezone="GMT")
        md = ds.load(
            symbols=[symbol_norm],
            start=None,
            end=None,
            interval=interval_norm,
            paths=parquet_paths,
        )
        return _bars_for_symbol_from_market_data(md, symbol_norm)

    if source_norm == "yfinance":
        ds = YahooFinanceDataSource(timezone="GMT")
        md = ds.load(
            symbols=[symbol_norm],
            start=None,
            end=None,
            interval=interval_norm,
            auto_adjust=bool(data_json.get("yf_auto_adjust", False)),
            progress=False,
        )
        return _bars_for_symbol_from_market_data(md, symbol_norm)

    bmce_paths = _extract_symbol_path(data_json.get("bmce_paths"), symbol_norm)
    if bmce_paths in (None, ""):
        raise HTTPException(
            status_code=400,
            detail=(
                "Walk-forward date resolution needs accessible bars. "
                "Provide dataset_id, data.dataset_symbol_map, data.source='store', or data.bmce_paths/parquet_paths."
            ),
        )
    ds = BMCEDataSource(timezone="GMT")
    md = ds.load(
        symbols=[symbol_norm],
        start=None,
        end=None,
        interval=interval_norm,
        paths=bmce_paths,
    )
    return _bars_for_symbol_from_market_data(md, symbol_norm)


def _resolve_walk_forward_dates_in_spec(
    *,
    db: Session,
    dataset_id: UUID | None,
    spec_json: dict[str, Any],
) -> dict[str, Any]:
    spec = copy.deepcopy(spec_json or {})
    optimization = dict(spec.get("optimization") or {})
    walk_forward = dict(optimization.get("walk_forward") or {})
    if not bool(walk_forward.get("enabled", False)):
        return spec

    data_json = dict(spec.get("data") or {})
    symbols = _normalize_symbols(spec.get("symbols") or data_json.get("symbols") or [])
    if not symbols:
        raise HTTPException(status_code=400, detail="Walk-forward date resolution requires at least one symbol.")
    symbol = str(symbols[0]).strip()
    interval = str(data_json.get("interval") or "1d").strip() or "1d"

    policy = str(walk_forward.get("end_date_policy") or "latest").strip().lower() or "latest"
    start_raw = walk_forward.get("start_date")
    end_raw = walk_forward.get("end_date")

    # Backward-compatible fallback for older clients that only sent data.start/end.
    if start_raw in (None, "") and data_json.get("start") not in (None, ""):
        start_raw = data_json.get("start")
    if end_raw in (None, "") and data_json.get("end") not in (None, ""):
        end_raw = data_json.get("end")

    requested_start = _parse_optional_iso_date(start_raw, field_name="walk_forward.start_date")
    requested_end = _parse_optional_iso_date(end_raw, field_name="walk_forward.end_date")

    source_norm = str(data_json.get("source") or spec.get("source_key") or "bmce").strip().lower() or "bmce"
    temp_files: list[Path] = []

    try:
        bars_df: pd.DataFrame
        if dataset_id is not None:
            dataset_row = db.execute(
                text("select id, data_hash, filename, object_key from dataset where id = :id"),
                {"id": dataset_id},
            ).mappings().first()
            if not dataset_row:
                raise HTTPException(status_code=404, detail=f"dataset not found: {dataset_id}")
            p = _materialize_dataset_file(
                filename=str(dataset_row.get("filename") or "upload.xlsx"),
                data_hash=str(dataset_row["data_hash"]),
                object_key=str(dataset_row["object_key"]) if dataset_row.get("object_key") else None,
            )
            temp_files.append(p)
            source_data_json = dict(data_json)
            source_data_json["bmce_paths"] = str(p)
            bars_df = _load_symbol_bars_for_wfo(
                source="bmce",
                symbol=symbol,
                interval=interval,
                data_json=source_data_json,
            )
        else:
            dataset_symbol_map_raw = data_json.get("dataset_symbol_map")
            dataset_symbol_map: dict[str, str] = {}
            if isinstance(dataset_symbol_map_raw, dict):
                for key, value in dataset_symbol_map_raw.items():
                    sym = str(key).strip().upper()
                    dsid = str(value).strip()
                    if sym and dsid:
                        dataset_symbol_map[sym] = dsid

            if dataset_symbol_map:
                dsid_raw = dataset_symbol_map.get(symbol.strip().upper())
                if not dsid_raw:
                    raise HTTPException(
                        status_code=400,
                        detail=f"missing dataset id mapping for symbol in walk-forward date resolution: {symbol}",
                    )
                try:
                    dsid = UUID(dsid_raw)
                except Exception as exc:
                    raise HTTPException(status_code=400, detail=f"invalid dataset id in dataset_symbol_map: {dsid_raw}") from exc

                dataset_row = db.execute(
                    text("select id, data_hash, filename, object_key from dataset where id = :id"),
                    {"id": dsid},
                ).mappings().first()
                if not dataset_row:
                    raise HTTPException(status_code=404, detail=f"dataset not found in dataset_symbol_map: {dsid}")
                p = _materialize_dataset_file(
                    filename=str(dataset_row.get("filename") or "upload.xlsx"),
                    data_hash=str(dataset_row["data_hash"]),
                    object_key=str(dataset_row["object_key"]) if dataset_row.get("object_key") else None,
                )
                temp_files.append(p)
                source_data_json = dict(data_json)
                source_data_json["bmce_paths"] = str(p)
                bars_df = _load_symbol_bars_for_wfo(
                    source="bmce",
                    symbol=symbol,
                    interval=interval,
                    data_json=source_data_json,
                )
            elif source_norm == "store":
                key = _store_key_for_symbol(db=db, symbol=symbol, timeframe="1D")
                p = _materialize_store_parquet(object_key=key)
                temp_files.append(p)
                source_data_json = dict(data_json)
                source_data_json["parquet_paths"] = str(p)
                bars_df = _load_symbol_bars_for_wfo(
                    source="parquet",
                    symbol=symbol,
                    interval=interval,
                    data_json=source_data_json,
                )
            else:
                bars_df = _load_symbol_bars_for_wfo(
                    source=source_norm,
                    symbol=symbol,
                    interval=interval,
                    data_json=data_json,
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "walk-forward date resolution failed",
            extra={
                "dataset_id": str(dataset_id) if dataset_id is not None else None,
                "symbol": symbol,
                "wfo_end_date_policy": policy,
                "requested_start": str(requested_start) if requested_start is not None else None,
                "requested_end": str(requested_end) if requested_end is not None else None,
                "source": source_norm,
                "s3_bucket": settings.S3_BUCKET,
            },
        )
        # Surface a compact, non-secret hint to the client.  FileNotFoundError
        # is raised by _safe_get_object_bytes when NoSuchKey is received.
        if isinstance(exc, FileNotFoundError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=f"walk-forward date resolution failed: {exc}") from exc
    finally:
        for p in temp_files:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    horizon = str(walk_forward.get("horizon") or "medium").strip().lower() or "medium"
    try:
        resolved = resolve_wfo_start_end_dates(
            bars_df,
            horizon=horizon,
            start_date=requested_start,
            end_date=requested_end,
            end_date_policy=policy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    resolved_start = resolved["resolved_start_date"].isoformat()
    resolved_end = resolved["resolved_end_date"].isoformat()
    bars_slice = bars_df.loc[resolved_start:resolved_end]
    if bars_slice.empty:
        raise HTTPException(
            status_code=400,
            detail=(
                "Resolved walk-forward date range produced zero bars: "
                f"{resolved_start} to {resolved_end}."
            ),
        )

    walk_forward["horizon"] = horizon
    walk_forward["start_date"] = requested_start.isoformat() if requested_start is not None else None
    walk_forward["end_date"] = requested_end.isoformat() if requested_end is not None else None
    walk_forward["end_date_policy"] = policy
    walk_forward["resolved_start_date"] = resolved_start
    walk_forward["resolved_end_date"] = resolved_end
    walk_forward["date_resolution"] = {
        "warnings": list(resolved.get("warnings") or []),
        "alignment_notes": dict(resolved.get("alignment_notes") or {}),
    }

    data_json["start"] = resolved_start
    data_json["end"] = resolved_end
    spec["data"] = data_json
    optimization["walk_forward"] = walk_forward
    spec["optimization"] = optimization
    return spec


def _as_json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def _safe_get_object_bytes(key: str, *, context: dict | None = None) -> bytes:
    """Fetch *key* from the configured S3 bucket and return raw bytes.

    Wraps ``NoSuchKey`` (botocore ClientError) with a :class:`FileNotFoundError`
    that carries a compact, non-secret message suitable for returning to clients.
    All other errors propagate unchanged.

    Args:
        key:     S3 object key to fetch.
        context: Optional caller-supplied dict merged into the structured log
                 ``extra`` on NoSuchKey (e.g. filename, data_hash, key_source).
                 Must not contain secrets; bucket and key are already included.

    # Sanity-check (no test runner needed):
    #   python -m compileall services/api/app/routers/runs.py
    # Reproduce + read logs:
    #   docker compose logs -f api | grep "S3 object not found"
    """
    bucket = settings.S3_BUCKET
    try:
        return s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as exc:
        # Detect NoSuchKey without importing botocore at module level.
        # Works for both real boto3 ClientError and moto/minio stubs.
        response = getattr(exc, "response", None) or {}
        code = response.get("Error", {}).get("Code", "") if isinstance(response, dict) else ""
        if not code and "NoSuchKey" in str(exc):
            code = "NoSuchKey"

        if code == "NoSuchKey":
            log_extra: dict = {"s3_key": key, "s3_bucket": bucket}
            if context:
                log_extra.update(context)
            logger.error(
                "S3 object not found: key=%r bucket=%r",
                key,
                bucket,
                extra=log_extra,
            )
            raise FileNotFoundError(
                f"Dataset object missing in storage: key={key!r} bucket={bucket!r}"
            ) from exc
        raise


def _materialize_dataset_file(*, filename: str, data_hash: str, object_key: str | None = None) -> Path:
    # Prefer the stored object_key (guaranteed to match what was uploaded).
    # Fall back to reconstructing the key if it's missing (legacy records).
    key_source = "db" if object_key else "derived"
    key = object_key or _build_dataset_object_key(data_hash=data_hash, filename=filename)
    logger.debug(
        "materializing dataset file: key=%r key_source=%s filename=%r data_hash=%r db_object_key=%r",
        key,
        key_source,
        filename,
        data_hash,
        object_key,
    )
    payload = _safe_get_object_bytes(
        key,
        context={
            "filename": filename,
            "data_hash": data_hash,
            "key_source": key_source,
            "db_object_key": object_key,
        },
    )

    suffix = Path(filename).suffix or ".bin"
    tmp = NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(payload)
    finally:
        tmp.close()
    return Path(tmp.name)


def _store_key_for_symbol(*, db: Session, symbol: str, timeframe: str = "1D") -> str:
    sym = str(symbol).strip().upper()
    row = db.execute(
        text("select object_key from market_data_store where symbol=:s and timeframe=:tf"),
        {"s": sym, "tf": timeframe},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"symbol not found in canonical store: {sym} ({timeframe})")
    return str(row["object_key"])


def _materialize_store_parquet(*, object_key: str) -> Path:
    logger.debug("materializing store parquet: key=%r", object_key)
    payload = _safe_get_object_bytes(object_key)
    if not payload:
        raise HTTPException(status_code=500, detail=f"empty parquet object: {object_key}")

    tmp = NamedTemporaryFile(delete=False, suffix=".parquet")
    try:
        tmp.write(payload)
    finally:
        tmp.close()
    return Path(tmp.name)


def _apply_store_as_parquet(spec_json: dict[str, Any], local_paths: dict[str, Path]) -> dict[str, Any]:
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


def _apply_uploaded_dataset(spec_json: dict[str, Any], local_file: Path) -> dict[str, Any]:
    spec = dict(spec_json or {})
    data_json = dict(spec.get("data") or {})

    data_json["source"] = "bmce"
    data_json["bmce_paths"] = str(local_file)
    data_json.setdefault("interval", "1d")

    symbols = spec.get("symbols") or data_json.get("symbols") or []
    symbols = _normalize_symbols(symbols)
    if not symbols:
        raise HTTPException(status_code=400, detail="symbols are required to materialize uploaded dataset details")

    spec["symbols"] = list(symbols)
    data_json["symbols"] = list(symbols)
    spec["data"] = data_json
    spec["source_key"] = "bmce"
    return spec


def _apply_uploaded_dataset_map(spec_json: dict[str, Any], local_paths: dict[str, Path]) -> dict[str, Any]:
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


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge_dict(dict(out.get(key) or {}), value)
        else:
            out[key] = value
    return out


def _prepare_detail_spec(
    *,
    db: Session,
    run: Run,
    symbol: str,
    strategy_kind: str,
    strategy_params: dict[str, Any],
    portfolio_overrides: dict[str, Any],
) -> tuple[dict[str, Any], list[Path]]:
    spec_json = copy.deepcopy(dict(run.spec_json or {}))
    temp_files: list[Path] = []

    # Force a single-symbol, single-strategy deterministic backtest.
    target_symbol = str(symbol).strip()
    if not target_symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    data_json = dict(spec_json.get("data") or {})
    spec_json["symbols"] = [target_symbol]
    data_json["symbols"] = [target_symbol]
    spec_json["data"] = data_json

    strategy_json = dict(spec_json.get("strategy") or {})
    base_params = dict(strategy_json.get("params") or {})
    strategy_json["kind"] = str(strategy_kind).strip().lower()

    # The frontend may send strategy_params in leaderboard format, where keys are
    # prefixed with "strategy." or "portfolio." (e.g., {"strategy.window": 40,
    # "portfolio.buy_pct_cash": 0.8}).  Normalise before merging:
    #   "strategy.X"   → plain strategy param X
    #   "portfolio.X"  → portfolio override (collected separately)
    #   bare "X"       → plain strategy param (pass through as-is)
    #   "data.*" / "walk_forward.*" / etc. → skip
    _SKIP_PREFIXES = ("data.", "walk_forward.", "simple_wfo.", "meta.")
    clean_strategy_params: dict[str, Any] = {}
    implicit_portfolio: dict[str, Any] = {}

    for k, v in dict(strategy_params or {}).items():
        if k.startswith("strategy."):
            clean_strategy_params[k[len("strategy."):]] = v
        elif k.startswith("portfolio."):
            # Support nested keys like "portfolio.volume_gate.enabled"
            sub = k[len("portfolio."):]
            parts = sub.split(".", 1)
            if len(parts) == 1:
                implicit_portfolio[parts[0]] = v
            else:
                outer = implicit_portfolio.setdefault(parts[0], {})
                if isinstance(outer, dict):
                    outer[parts[1]] = v
        elif not any(k.startswith(p) for p in _SKIP_PREFIXES):
            clean_strategy_params[k] = v

    strategy_json["params"] = _deep_merge_dict(base_params, clean_strategy_params)
    spec_json["strategy"] = strategy_json

    portfolio_json = dict(spec_json.get("portfolio") or {})
    # Apply variant-specific portfolio params (from leaderboard best_params format) first,
    # then the explicit portfolio_overrides on top.
    if implicit_portfolio:
        portfolio_json = _deep_merge_dict(portfolio_json, implicit_portfolio)
    spec_json["portfolio"] = _deep_merge_dict(portfolio_json, dict(portfolio_overrides or {}))

    spec_json["optimization"] = {"n_trials": 0, "kinds": []}
    spec_json["plots"] = {
        "enabled": True,
        "return_plot_artifacts": True,
        "kinds": [
            "price_indicators_trades",
            "drawdown",
            "cumreturn_vs_benchmark",
            "monthly_heatmap",
            "yearly_return_barplot",
        ],
        "symbols": [target_symbol],
    }

    if run.dataset_id is not None:
        dataset_row = db.execute(
            text("select id, data_hash, filename, object_key from dataset where id = :id"),
            {"id": run.dataset_id},
        ).mappings().first()
        if not dataset_row:
            raise HTTPException(status_code=404, detail=f"dataset not found: {run.dataset_id}")
        temp_file = _materialize_dataset_file(
            filename=str(dataset_row.get("filename") or "upload.xlsx"),
            data_hash=str(dataset_row["data_hash"]),
            object_key=str(dataset_row["object_key"]) if dataset_row.get("object_key") else None,
        )
        temp_files.append(temp_file)
        spec_json = _apply_uploaded_dataset(spec_json, temp_file)
        return spec_json, temp_files

    dataset_symbol_map_raw = data_json.get("dataset_symbol_map")
    dataset_symbol_map: dict[str, str] = {}
    if isinstance(dataset_symbol_map_raw, dict):
        for k, v in dataset_symbol_map_raw.items():
            sym = str(k).strip().upper()
            dsid = str(v).strip()
            if sym and dsid:
                dataset_symbol_map[sym] = dsid

    if dataset_symbol_map:
        dsid_raw = dataset_symbol_map.get(target_symbol.strip().upper())
        if not dsid_raw:
            raise HTTPException(status_code=400, detail=f"missing dataset id mapping for symbol: {target_symbol}")
        try:
            dsid = UUID(dsid_raw)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid dataset id in dataset_symbol_map: {dsid_raw}") from exc

        dataset_row = db.execute(
            text("select id, data_hash, filename, object_key from dataset where id = :id"),
            {"id": dsid},
        ).mappings().first()
        if not dataset_row:
            raise HTTPException(status_code=404, detail=f"dataset not found in dataset_symbol_map: {dsid}")
        temp_file = _materialize_dataset_file(
            filename=str(dataset_row.get("filename") or "upload.xlsx"),
            data_hash=str(dataset_row["data_hash"]),
            object_key=str(dataset_row["object_key"]) if dataset_row.get("object_key") else None,
        )
        temp_files.append(temp_file)
        spec_json = _apply_uploaded_dataset_map(spec_json, {target_symbol: temp_file})
        return spec_json, temp_files

    source = str(data_json.get("source") or "").strip().lower()
    if source == "store":
        key = _store_key_for_symbol(db=db, symbol=target_symbol, timeframe="1D")
        temp_file = _materialize_store_parquet(object_key=key)
        temp_files.append(temp_file)
        spec_json = _apply_store_as_parquet(spec_json, {target_symbol: temp_file})
        return spec_json, temp_files

    return spec_json, temp_files


@router.post("", response_model=RunCreateResponse)
def create_run(payload: RunCreateRequest, db: Session = Depends(get_db)):
    spec_json = copy.deepcopy(dict(payload.spec_json or {}))
    initial_mode = _infer_mode(spec_json)
    if initial_mode == "walk_forward":
        spec_json = _resolve_walk_forward_dates_in_spec(
            db=db,
            dataset_id=payload.dataset_id,
            spec_json=spec_json,
        )
        _assert_wfo_resolved_dates(spec_json, caller="create_run")

    provided_spec_hash = str(payload.spec_hash or "").strip()
    computed_spec_hash = json_hash(spec_json)
    spec_hash = computed_spec_hash or provided_spec_hash

    # Deterministic run_id is bound to (spec_hash, dataset_id), so changing
    # dataset does not accidentally collide with a previous run.
    run_id = _compute_run_id(spec_hash, payload.dataset_id)

    run_type = _infer_run_type(spec_json)
    run_mode = _infer_mode(spec_json)
    run_seed = _extract_seed(spec_json)
    dataset_hash = _resolve_dataset_hash(db, dataset_id=payload.dataset_id, spec_json=spec_json)
    code_version = _resolve_code_version()

    # First check new identity. Then check legacy identities to preserve
    # backward-compatible idempotency for old runs created before this fix.
    hash_candidates: list[str] = []
    for h in (spec_hash, provided_spec_hash):
        if h and h not in hash_candidates:
            hash_candidates.append(h)

    candidate_ids = [run_id]
    for h in hash_candidates:
        candidate_ids.append(_compute_run_id(h, payload.dataset_id))
        candidate_ids.extend(_legacy_run_id_candidates(h))
    # preserve order, remove duplicates
    candidate_ids = list(dict.fromkeys(candidate_ids))

    for candidate_id in candidate_ids:
        existing = db.get(Run, candidate_id)
        if existing is None:
            continue
        existing_spec = dict(existing.spec_json or {})
        if existing.dataset_id == payload.dataset_id and existing_spec == spec_json:
            status = str(existing.status or "").strip().lower()
            if status in _NON_REUSABLE_RUN_STATUSES:
                _purge_run_outputs(db, existing.id, delete_objects=True)
                existing.status = "created"
                existing.spec_hash = spec_hash
                existing.mode = run_mode
                existing.seed = run_seed
                existing.dataset_hash = dataset_hash
                existing.code_version = code_version
                existing.integrity_status = "pending"
                existing.created_at = datetime.now(timezone.utc)
                existing.started_at = None
                existing.finished_at = None
                existing.error_message = None
                existing.rq_job_id = None
                existing.progress_pct = 0.0
                existing.progress_stage = "created"
                existing.progress_message = "Recreated from failed/canceled run"
                existing.last_heartbeat_at = None
                db.commit()
                return RunCreateResponse(
                    run_id=existing.id,
                    status=existing.status,
                    run_type=str(existing.run_type or run_type),
                )
            return RunCreateResponse(
                run_id=existing.id,
                status=existing.status,
                run_type=str(existing.run_type or run_type),
            )

    run = Run(
        id=run_id,
        status="created",
        run_type=run_type,
        mode=run_mode,
        seed=run_seed,
        dataset_hash=dataset_hash,
        code_version=code_version,
        integrity_status="pending",
        dataset_id=payload.dataset_id,
        spec_json=spec_json,
        spec_hash=spec_hash,
        engine_version="0.1.0",
        git_commit=code_version,
        error_message=None,
    )
    db.add(run)
    db.commit()

    return RunCreateResponse(run_id=run.id, status=run.status, run_type=run.run_type)


@router.post("/walk-forward/resolve-dates", response_model=WalkForwardResolveDatesResponse)
def resolve_walk_forward_dates(payload: WalkForwardResolveDatesRequest, db: Session = Depends(get_db)):
    spec_json = copy.deepcopy(dict(payload.spec_json or {}))
    if _infer_mode(spec_json) != "walk_forward":
        raise HTTPException(status_code=400, detail="walk_forward.enabled must be true for date resolution preview.")

    resolved_spec = _resolve_walk_forward_dates_in_spec(
        db=db,
        dataset_id=payload.dataset_id,
        spec_json=spec_json,
    )
    walk_forward = dict((dict(resolved_spec.get("optimization") or {})).get("walk_forward") or {})
    resolution = dict(walk_forward.get("date_resolution") or {})
    return {
        "requested_start_date": walk_forward.get("start_date"),
        "requested_end_date": walk_forward.get("end_date"),
        "resolved_start_date": str(walk_forward.get("resolved_start_date") or ""),
        "resolved_end_date": str(walk_forward.get("resolved_end_date") or ""),
        "end_date_policy": str(walk_forward.get("end_date_policy") or "latest"),
        "alignment_notes": dict(resolution.get("alignment_notes") or {}),
        "warnings": [str(w) for w in list(resolution.get("warnings") or [])],
    }


@router.get("", response_model=list[RunListItemOut])
def list_runs(
    status: str | None = Query(default=None),
    run_type: str | None = Query(default=None),
    dataset_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Run)
    if status:
        q = q.filter(Run.status == status)
    if run_type:
        q = q.filter(Run.run_type == run_type)
    if dataset_id:
        q = q.filter(Run.dataset_id == dataset_id)

    rows = (
        q.order_by(Run.created_at.desc(), Run.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        {
            "run_id": row.id,
            "status": row.status,
            "run_type": row.run_type,
            "mode": row.mode,
            "seed": row.seed,
            "dataset_hash": row.dataset_hash,
            "code_version": row.code_version,
            "integrity_status": row.integrity_status,
            "dataset_id": row.dataset_id,
            "created_at": row.created_at,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
        }
        for row in rows
    ]


@router.post("/{run_id}/start")
def start_run(run_id: UUID, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    # idempotency: if already queued/running/done, just return current status
    if run.status in {"queued", "running", "succeeded"}:
        return {"run_id": run.id, "status": run.status, "job_id": run.rq_job_id}

    retry_policy = None
    if settings.RUN_JOB_RETRY_MAX > 0:
        retry_policy = Retry(
            max=settings.RUN_JOB_RETRY_MAX,
            interval=settings.RUN_JOB_RETRY_INTERVAL_SECONDS,
        )

    q = Queue(
        settings.RUNS_QUEUE_NAME,
        connection=Redis.from_url(settings.REDIS_URL, decode_responses=False),
        default_timeout=int(settings.RUN_JOB_TIMEOUT_SECONDS),
    )

    try:
        # enqueue by dotted path to avoid importing worker/quant_core in API process
        job = q.enqueue(
            "services.worker.tasks.execute_run.execute_run",
            str(run.id),
            job_timeout=int(settings.RUN_JOB_TIMEOUT_SECONDS),
            result_ttl=int(settings.RUN_JOB_RESULT_TTL_SECONDS),
            failure_ttl=int(settings.RUN_JOB_FAILURE_TTL_SECONDS),
            retry=retry_policy,
        )
    except Exception as exc:
        run.status = "failed"
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = f"enqueue failed: {exc}"[:8000]
        db.commit()
        raise HTTPException(status_code=503, detail="failed to enqueue run") from exc

    # Allow restart (failed/canceled/cancel_requested -> queued)
    run.status = "queued"
    run.started_at = None
    run.finished_at = None
    run.error_message = None
    run.rq_job_id = str(job.id)
    run.progress_pct = 0.0
    run.progress_stage = "queued"
    run.progress_message = "Queued in RQ"
    run.last_heartbeat_at = None
    run.integrity_status = "pending"
    db.commit()

    return {"run_id": run.id, "status": run.status, "job_id": job.id}


@router.get("/{run_id}")
def get_run(run_id: UUID, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "run_id": str(run.id),
        "status": run.status,
        "run_type": run.run_type,
        "mode": run.mode,
        "seed": run.seed,
        "dataset_hash": run.dataset_hash,
        "code_version": run.code_version,
        "integrity_status": run.integrity_status,
        "spec_json": run.spec_json,
        "spec_hash": run.spec_hash,
        "dataset_id": run.dataset_id,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "rq_job_id": run.rq_job_id,
        "progress_pct": run.progress_pct,
        "progress_stage": run.progress_stage,
        "progress_message": run.progress_message,
        "last_heartbeat_at": run.last_heartbeat_at,
        "error_message": run.error_message,
    }



@router.get("/{run_id}/integrity")
def get_run_integrity(run_id: UUID, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    checks = (
        db.query(RunIntegrityCheck)
        .filter(RunIntegrityCheck.run_id == run_id)
        .order_by(RunIntegrityCheck.created_at.asc(), RunIntegrityCheck.id.asc())
        .all()
    )
    report = (
        db.query(Artifact)
        .filter(
            Artifact.run_id == run_id,
            Artifact.artifact_type == "run_integrity_json",
            Artifact.name == "integrity.report",
        )
        .order_by(Artifact.created_at.desc())
        .first()
    )
    return {
        "run_id": str(run_id),
        "integrity_status": run.integrity_status,
        "checks": [
            {
                "check_name": row.check_name,
                "status": row.status,
                "details_json": dict(row.details_json or {}),
                "created_at": row.created_at,
            }
            for row in checks
        ],
        "report_url": presign_get(report.object_key, expires_seconds=300) if report else None,
    }


@router.get("/{run_id}/walk-forward")
def get_run_walk_forward(run_id: UUID, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    spec_json = dict(run.spec_json or {})
    optimization_json = dict(spec_json.get("optimization") or {})
    walk_forward_spec = dict(optimization_json.get("walk_forward") or {})

    rows = (
        db.query(RunFold)
        .filter(RunFold.run_id == run_id)
        .order_by(RunFold.fold_index.asc(), RunFold.id.asc())
        .all()
    )

    objective_values: list[float] = []
    for row in rows:
        payload = dict(row.fold_metrics_json or {})
        for key in ("objective_value", "oos_objective_value", "stat.pnl", "stat.cagr"):
            value = _as_summary_float(payload.get(key))
            if value is not None:
                objective_values.append(value)
                break

    aggregate = {
        "fold_count": len(rows),
        "objective_mean": (sum(objective_values) / len(objective_values)) if objective_values else None,
    }

    first_fold_artifacts = dict(rows[0].fold_artifacts or {}) if rows else {}
    horizon = (
        str(first_fold_artifacts.get("horizon") or walk_forward_spec.get("horizon") or "medium").strip().lower() or "medium"
    )
    horizon_label = str(first_fold_artifacts.get("horizon_label") or "").strip() or None
    horizon_cfg = dict(first_fold_artifacts.get("horizon_cfg") or walk_forward_spec.get("horizon_cfg") or {})
    train_cfg = dict(first_fold_artifacts.get("train") or walk_forward_spec.get("train") or {})
    test_cfg = dict(first_fold_artifacts.get("test") or walk_forward_spec.get("test") or {})
    step_cfg = dict(first_fold_artifacts.get("step") or walk_forward_spec.get("step") or {})
    resolved_start_date = (
        first_fold_artifacts.get("resolved_start_date")
        or walk_forward_spec.get("resolved_start_date")
        or dict(spec_json.get("data") or {}).get("start")
    )
    resolved_end_date = (
        first_fold_artifacts.get("resolved_end_date")
        or walk_forward_spec.get("resolved_end_date")
        or dict(spec_json.get("data") or {}).get("end")
    )
    date_resolution = dict(first_fold_artifacts.get("date_resolution") or walk_forward_spec.get("date_resolution") or {})
    end_date_policy = str(
        first_fold_artifacts.get("end_date_policy") or walk_forward_spec.get("end_date_policy") or "latest"
    ).strip().lower() or "latest"
    requested_start_date = walk_forward_spec.get("start_date")
    requested_end_date = walk_forward_spec.get("end_date")

    return {
        "run_id": str(run_id),
        "mode": run.mode,
        "horizon": horizon,
        "horizon_label": horizon_label,
        "horizon_cfg": horizon_cfg,
        "windows": {
            "train": train_cfg,
            "test": test_cfg,
            "step": step_cfg,
        },
        "requested_start_date": requested_start_date,
        "requested_end_date": requested_end_date,
        "resolved_start_date": resolved_start_date,
        "resolved_end_date": resolved_end_date,
        "end_date_policy": end_date_policy,
        "date_resolution": date_resolution,
        "aggregate": aggregate,
        "folds": [
            {
                "fold_index": int(row.fold_index),
                "train_start": row.train_start,
                "train_end": row.train_end,
                "test_start": row.test_start,
                "test_end": row.test_end,
                "fold_metrics_json": dict(row.fold_metrics_json or {}),
                "fold_artifacts": dict(row.fold_artifacts or {}),
                "created_at": row.created_at,
            }
            for row in rows
        ],
    }


@router.get("/{run_id}/significance", response_model=list[RunSignificanceOut])
def get_run_significance(run_id: UUID, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    rows = (
        db.query(RunSignificance)
        .filter(RunSignificance.run_id == run_id)
        .order_by(RunSignificance.created_at.asc(), RunSignificance.id.asc())
        .all()
    )
    return [
        {
            "method": row.method,
            "pvalue": row.pvalue,
            "statistic": row.statistic,
            "mc_null_dist_ref": row.mc_null_dist_ref,
            "details_json": dict(row.details_json or {}),
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/{run_id}/risk")
def get_run_risk(run_id: UUID, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    row = (
        db.query(RunRisk)
        .filter(RunRisk.run_id == run_id)
        .order_by(RunRisk.created_at.desc(), RunRisk.id.desc())
        .first()
    )
    if row is None:
        return {"run_id": str(run_id), "risk": None}
    return {
        "run_id": str(run_id),
        "risk": {
            "kelly_fraction": row.kelly_fraction,
            "half_kelly": row.half_kelly,
            "chosen_leverage": row.chosen_leverage,
            "mc_drawdown_pctl": row.mc_drawdown_pctl,
            "mc_var": row.mc_var,
            "mc_cvar": row.mc_cvar,
            "details_json": dict(row.details_json or {}),
            "created_at": row.created_at,
        },
    }


@router.get("/{run_id}/mean-reversion")
def get_run_mean_reversion(run_id: UUID, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    artifact = (
        db.query(Artifact)
        .filter(
            Artifact.run_id == run_id,
            Artifact.artifact_type == "mean_reversion_json",
            Artifact.name == "mean_reversion.report",
        )
        .order_by(Artifact.created_at.desc())
        .first()
    )
    return {
        "run_id": str(run_id),
        "report_url": presign_get(artifact.object_key, expires_seconds=300) if artifact else None,
    }


@router.post("/{run_id}/cancel")
def cancel_run(run_id: UUID, db: Session = Depends(get_db)):
    row = db.execute(
        text("select id, rq_job_id, status from run where id=:id"),
        {"id": str(run_id)},
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="run not found")

    rq_job_id = row.get("rq_job_id")
    current_status = str(row.get("status") or "")
    if current_status in {"succeeded", "failed", "canceled"}:
        return {"run_id": str(run_id), "status": current_status, "job_id": rq_job_id}

    r = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    canceled_from_queue = False

    if rq_job_id:
        # cooperative cancel flag (worker checks rq:cancel:{job_id})
        r.set(f"rq:cancel:{rq_job_id}", "1", ex=24 * 3600)

        # if still queued, try cancel/remove
        try:
            job = Job.fetch(rq_job_id, connection=r)
            if job:
                status = job.get_status(refresh=True)
                if status in ("queued", "deferred", "scheduled"):
                    job.cancel()
                    canceled_from_queue = True
        except Exception:
            pass

    next_status = "cancel_requested"
    finished_at = None
    if current_status == "created" or (current_status == "queued" and canceled_from_queue):
        next_status = "canceled"
        finished_at = datetime.now(timezone.utc)

    db.execute(
        text("""
          update run
          set status=:status,
              finished_at=:finished_at,
              progress_stage=:progress_stage,
              progress_message=:progress_message
          where id=:id and status in ('created','queued','running','cancel_requested')
        """),
        {
            "id": str(run_id),
            "status": next_status,
            "finished_at": finished_at,
            "progress_stage": next_status,
            "progress_message": "Cancel requested by user" if next_status == "cancel_requested" else "Canceled by user",
        },
    )
    db.commit()

    return {"run_id": str(run_id), "status": next_status, "job_id": rq_job_id}


@router.delete("/{run_id}")
def delete_run(run_id: UUID, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    current_status = str(run.status or "").strip().lower()
    if current_status in _ACTIVE_RUN_STATUSES:
        raise HTTPException(status_code=409, detail="cannot delete an active run; cancel it first")

    cleanup = _purge_run_outputs(db, run_id, delete_objects=True)
    db.delete(run)
    db.commit()

    return {
        "run_id": str(run_id),
        "status": "deleted",
        **cleanup,
    }

@router.get("/{run_id}/metrics", response_model=list[RunMetricOut])
def list_run_metrics(run_id: UUID, db: Session = Depends(get_db)):
    rows = (
        db.query(RunMetric)
        .filter(RunMetric.run_id == run_id)
        .order_by(RunMetric.symbol.asc(), RunMetric.metric_name.asc())
        .all()
    )
    return [
        {
            "run_id": row.run_id,
            "symbol": row.symbol,
            "metric_name": row.metric_name,
            "metric_value": row.metric_value,
        }
        for row in rows
    ]


@router.get("/{run_id}/fills", response_model=list[FillOut])
def list_fills(
    run_id: UUID,
    symbol: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    cursor: str | None = None,
    db: Session = Depends(get_db),
):
    cursor_ts = _parse_cursor(cursor)

    q = db.query(Fill).filter(Fill.run_id == run_id)
    if symbol is not None:
        q = q.filter(Fill.symbol == symbol)
    if cursor_ts is not None:
        q = q.filter(Fill.timestamp < cursor_ts)

    rows = q.order_by(Fill.timestamp.desc(), Fill.id.desc()).limit(limit).all()
    return [
        {
            "id": row.id,
            "run_id": row.run_id,
            "timestamp": row.timestamp,
            "symbol": row.symbol,
            "side": row.side,
            "qty": row.qty,
            "price": row.price,
            "fees": row.fees,
            "notional": row.notional,
            "meta": row.meta,
        }
        for row in rows
    ]


@router.get("/{run_id}/position-ledger", response_model=list[PositionLedgerOut])
def list_position_ledger(
    run_id: UUID,
    symbol: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    cursor: str | None = None,
    db: Session = Depends(get_db),
):
    cursor_ts = _parse_cursor(cursor)

    q = db.query(PositionLedger).filter(PositionLedger.run_id == run_id)
    if symbol is not None:
        q = q.filter(PositionLedger.symbol == symbol)
    if cursor_ts is not None:
        q = q.filter(PositionLedger.timestamp < cursor_ts)

    rows = q.order_by(PositionLedger.timestamp.desc(), PositionLedger.id.desc()).limit(limit).all()
    return [
        {
            "id": row.id,
            "run_id": row.run_id,
            "timestamp": row.timestamp,
            "symbol": row.symbol,
            "available_qty": row.available_qty,
            "cmp": row.cmp,
            "position_value_cost": row.position_value_cost,
            "pnl_realise": row.pnl_realise,
            "pnl_latent": row.pnl_latent,
            "mark_price": row.mark_price,
        }
        for row in rows
    ]


@router.get("/{run_id}/leaderboard", response_model=list[StrategyLeaderboardOut])
def list_strategy_leaderboard(
    run_id: UUID,
    symbol: str | None = None,
    best_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    q = db.query(StrategyLeaderboard).filter(StrategyLeaderboard.run_id == run_id)
    if symbol:
        q = q.filter(StrategyLeaderboard.symbol == symbol)
    if best_only:
        q = q.filter(StrategyLeaderboard.rank == 1)

    rows = q.order_by(
        StrategyLeaderboard.symbol.asc(),
        StrategyLeaderboard.rank.asc(),
        StrategyLeaderboard.cagr.desc().nullslast(),
        StrategyLeaderboard.strategy_kind.asc(),
    ).all()

    if not rows:
        return []

    run = db.get(Run, run_id)
    spec_json = dict(run.spec_json or {}) if run is not None else {}
    portfolio_json = dict(spec_json.get("portfolio") or {})
    initial_cash = _as_summary_float(portfolio_json.get("initial_cash")) or 100000.0

    symbols = sorted({r.symbol for r in rows})
    metric_rows_q = db.query(RunMetric).filter(RunMetric.run_id == run_id)
    if symbol:
        metric_rows_q = metric_rows_q.filter(RunMetric.symbol.in_([symbol, "__ALL__"]))
    else:
        metric_rows_q = metric_rows_q.filter(RunMetric.symbol.in_(symbols + ["__ALL__"]))
    metric_rows = metric_rows_q.all()
    metrics_by_symbol: dict[str, dict[str, float]] = {}
    for m in metric_rows:
        sym_key = _normalize_symbol_key(m.symbol)
        metrics_by_symbol.setdefault(sym_key, {})[str(m.metric_name)] = float(m.metric_value)

    artifacts_q = db.query(Artifact).filter(
        Artifact.run_id == run_id,
        Artifact.artifact_type.in_(("strategy_plotly_json", "strategy_trade_ledger_csv", "strategy_trade_performance_csv")),
    )
    if symbol:
        artifacts_q = artifacts_q.filter(Artifact.symbol == symbol)
    else:
        artifacts_q = artifacts_q.filter(Artifact.symbol.in_(symbols))
    artifacts = artifacts_q.all()

    artifact_url_map: dict[tuple[str, str, str, str], str] = {}
    perf_key_map: dict[tuple[str, str], str] = {}
    for a in artifacts:
        kind = _artifact_strategy_kind(a.name)
        base = _artifact_base_name(a.name)
        if not kind:
            continue
        if str(a.artifact_type) == "strategy_trade_performance_csv":
            perf_key_map[(_normalize_symbol_key(a.symbol), kind)] = str(a.object_key)
            continue
        artifact_url_map[(str(a.symbol or ""), kind, base, str(a.artifact_type))] = presign_get(a.object_key, expires_seconds=300)

    win_pct_cache: dict[tuple[str, str], float | None] = {}

    out = []
    for row in rows:
        row_symbol = str(row.symbol)
        row_symbol_key = _normalize_symbol_key(row_symbol)
        strategy_kind_key = str(row.strategy_kind).lower()
        key_base = (row_symbol, strategy_kind_key)
        best_params_json, summary = _split_best_params_and_summary(row.best_params_json)

        total_return = summary.get("total_return")
        if total_return is None and row.pnl is not None and initial_cash > 0:
            total_return = float(row.pnl) / float(initial_cash)

        sharpe = summary.get("sharpe")
        if sharpe is None:
            sharpe = _metric_lookup(metrics_by_symbol, row_symbol_key, ["Sharpe", "Sharpe Ratio"])

        max_drawdown = summary.get("max_drawdown")
        if max_drawdown is None:
            max_drawdown = _metric_lookup(metrics_by_symbol, row_symbol_key, ["Max drawdown", "Max Drawdown", "Max Daily Drawdown"])

        win_pct = summary.get("win_pct")
        win_cache_key = (row_symbol_key, strategy_kind_key)
        if win_pct is None:
            if win_cache_key not in win_pct_cache:
                object_key = perf_key_map.get(win_cache_key)
                win_pct_cache[win_cache_key] = _read_win_rate_from_perf_csv(object_key) if object_key else None
            win_pct = win_pct_cache.get(win_cache_key)
        if win_pct is None:
            win_pct = _metric_lookup(metrics_by_symbol, row_symbol_key, ["Win Rate", "Trade Winning %"])
        win_pct = _normalize_win_pct(_as_summary_float(win_pct))

        out.append(
            {
                "run_id": row.run_id,
                "symbol": row.symbol,
                "strategy_kind": row.strategy_kind,
                "rank": int(row.rank),
                "pnl": row.pnl,
                "cagr": row.cagr,
                "total_return": total_return,
                "sharpe": sharpe,
                "max_drawdown": max_drawdown,
                "win_pct": win_pct,
                "efficiency": row.efficiency,
                "n_fills": row.n_fills,
                "signal_label": row.signal_label,
                "signal_today": row.signal_today,
                "signal_date": row.signal_date,
                "best_params_json": best_params_json,
                "plot_url": artifact_url_map.get((key_base[0], key_base[1], "price_indicators_trades", "strategy_plotly_json")),
                "ledger_url": artifact_url_map.get((key_base[0], key_base[1], "trade_ledger", "strategy_trade_ledger_csv")),
            }
        )
    return out


def _strategy_decision_to_out(row: StrategyDecision) -> dict[str, Any]:
    return {
        "run_id": row.run_id,
        "symbol": row.symbol,
        "strategy_kind": row.strategy_kind,
        "trial_id": row.trial_id,
        "rank": row.rank,
        "params_hash": row.params_hash,
        "params_json": _as_json_dict(row.params_json),
        "opportunity_score": float(row.opportunity_score),
        "confidence_score": float(row.confidence_score),
        "status": str(row.status or "watch"),
        "opportunity_subscores": _as_json_dict(row.opportunity_subscores),
        "confidence_subscores": _as_json_dict(row.confidence_subscores),
        "decision_page": _as_json_dict(row.decision_page_json),
        "explain": _as_json_dict(row.explain_json),
        "computed_at": row.computed_at,
    }


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on", "enabled"}:
            return True
        if lowered in {"0", "false", "no", "n", "off", "disabled"}:
            return False
    return bool(default)


def _normalize_direction_label(direction: int) -> str:
    if direction > 0:
        return "long"
    if direction < 0:
        return "short"
    return "neutral"


def _direction_to_int(value: Any) -> int:
    raw = str(value or "").strip().lower()
    if raw in {"long", "buy", "bullish", "1", "+1"}:
        return 1
    if raw in {"short", "sell", "bearish", "-1"}:
        return -1
    numeric = _safe_float(value)
    if numeric is None:
        return 0
    if numeric > 0:
        return 1
    if numeric < 0:
        return -1
    return 0


def _set_path(target: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = [p for p in str(dotted_path).split(".") if p]
    if not parts:
        return
    node = target
    for idx, part in enumerate(parts):
        if idx == len(parts) - 1:
            node[part] = value
            return
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt


def _flatten_dict(data: dict[str, Any], *, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in dict(data or {}).items():
        next_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten_dict(value, prefix=next_key))
            continue
        out[next_key] = value
    return out


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base or {})
    for key, value in dict(override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(dict(out.get(key) or {}), value)
            continue
        out[key] = value
    return out


def _effective_strategy_and_portfolio_params(
    *,
    run_spec: dict[str, Any],
    decision_params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    strategy_base = dict((run_spec.get("strategy") or {}).get("params") or {})
    portfolio_base = dict(run_spec.get("portfolio") or {})

    strategy_overrides: dict[str, Any] = {}
    portfolio_overrides: dict[str, Any] = {}
    for key, value in dict(decision_params or {}).items():
        if not isinstance(key, str):
            continue
        if key.startswith("strategy."):
            _set_path(strategy_overrides, key[len("strategy."):], value)
            continue
        if key.startswith("portfolio."):
            _set_path(portfolio_overrides, key[len("portfolio."):], value)

    nested_strategy = decision_params.get("strategy")
    if isinstance(nested_strategy, dict):
        strategy_overrides = _deep_merge(strategy_overrides, nested_strategy)
    nested_portfolio = decision_params.get("portfolio")
    if isinstance(nested_portfolio, dict):
        portfolio_overrides = _deep_merge(portfolio_overrides, nested_portfolio)

    strategy_effective = _deep_merge(strategy_base, strategy_overrides)
    portfolio_effective = _deep_merge(portfolio_base, portfolio_overrides)
    merged_flat = {
        **_flatten_dict(strategy_effective, prefix="strategy"),
        **_flatten_dict(portfolio_effective, prefix="portfolio"),
    }
    return strategy_effective, portfolio_effective, merged_flat


def _records_to_frame(records: Any) -> pd.DataFrame:
    rows = [r for r in list(records or []) if isinstance(r, dict)]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    ts_col = None
    for candidate in ("timestamp", "date", "datetime", "ts"):
        if candidate in df.columns:
            ts_col = candidate
            break
    if ts_col is not None:
        df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
        df = df.dropna(subset=[ts_col]).sort_values(ts_col)
        df = df.rename(columns={ts_col: "timestamp"})
        df = df.set_index("timestamp")
    return df


def _match_symbol_payload(by_symbol: Any, symbol: str) -> dict[str, Any]:
    if not isinstance(by_symbol, dict):
        return {}
    symbol_key = str(symbol or "").strip().upper()
    for key, payload in by_symbol.items():
        if str(key).strip().upper() == symbol_key and isinstance(payload, dict):
            return payload
    if symbol_key in by_symbol and isinstance(by_symbol.get(symbol_key), dict):
        return dict(by_symbol.get(symbol_key) or {})
    for payload in by_symbol.values():
        if isinstance(payload, dict):
            return payload
    return {}


def _pick_series(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    if df.empty:
        return pd.Series(dtype="float64")

    lowered = {str(col).strip().lower(): str(col) for col in df.columns}
    for name in candidates:
        if name in df.columns:
            return pd.to_numeric(df[name], errors="coerce")
        low = str(name).strip().lower()
        if low in lowered:
            return pd.to_numeric(df[lowered[low]], errors="coerce")
    return pd.Series(index=df.index, dtype="float64")


def _to_float_list(series: pd.Series) -> list[float | None]:
    if series is None or len(series) == 0:
        return []
    out: list[float | None] = []
    for value in pd.to_numeric(series, errors="coerce").tolist():
        f = _safe_float(value)
        out.append(f)
    return out


def _to_iso_timestamps(index: pd.Index) -> list[str]:
    if not isinstance(index, pd.DatetimeIndex):
        return []
    out: list[str] = []
    for ts in index:
        if pd.isna(ts):
            out.append("")
            continue
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        out.append(ts.strftime("%Y-%m-%dT%H:%M:%SZ"))
    return out


def _compute_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)
    avg_gain = gains.rolling(window, min_periods=window).mean()
    avg_loss = losses.rolling(window, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_atr_14(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(14, min_periods=14).mean()


def _build_regime_payload(bars: pd.DataFrame) -> dict[str, Any]:
    try:
        from core.quant_core.decision import classify_regime

        regime = dict(classify_regime(bars))
    except Exception:
        regime = {"label": "unknown", "bias": 0, "inputs": {}, "thresholds": {}}

    close = _pick_series(bars, ["Close", "close"])
    sma200 = close.rolling(200, min_periods=200).mean()
    slope_20 = None
    if len(sma200) >= 21:
        now = _safe_float(sma200.iloc[-1])
        prev = _safe_float(sma200.iloc[-21])
        if now is not None and prev not in (None, 0.0):
            slope_20 = (now - prev) / abs(prev)

    close_t = _safe_float(close.iloc[-1]) if len(close) else None
    sma200_t = _safe_float(sma200.iloc[-1]) if len(sma200) else None
    checks = [
        {
            "name": "price_vs_sma200",
            "expr": "close_t > sma200_t",
            "value": close_t,
            "threshold": sma200_t,
            "pass": bool(close_t is not None and sma200_t is not None and close_t > sma200_t),
        },
        {
            "name": "sma200_slope_20",
            "expr": "sma200_slope_20 > 0",
            "value": slope_20,
            "threshold": 0.0,
            "pass": bool(slope_20 is not None and slope_20 > 0),
        },
        {
            "name": "bearish_combo",
            "expr": "close_t < sma200_t and slope_20 < 0",
            "value": {"close_t": close_t, "sma200_t": sma200_t, "slope_20": slope_20},
            "threshold": {"close_vs_sma200": "<", "slope_20": "<0"},
            "pass": bool(
                close_t is not None and sma200_t is not None and slope_20 is not None and close_t < sma200_t and slope_20 < 0
            ),
        },
    ]

    return {
        "label": str(regime.get("label") or "unknown"),
        "bias": _safe_int(regime.get("bias"), 0),
        "inputs": dict(regime.get("inputs") or {}),
        "thresholds": dict(regime.get("thresholds") or {}),
        "rule_checks": checks,
        "verdict": str(regime.get("label") or "unknown"),
    }


def _build_signal_debug_snapshot(
    *,
    strategy_kind: str,
    strategy_direction: int,
    close: pd.Series,
    sma_ref: pd.Series,
    volume: pd.Series,
    signals: pd.Series,
    strategy_params: dict[str, Any],
    portfolio_params: dict[str, Any],
) -> dict[str, Any]:
    close_t = _safe_float(close.iloc[-1]) if len(close) else None
    close_prev = _safe_float(close.iloc[-2]) if len(close) >= 2 else None
    sma_t = _safe_float(sma_ref.iloc[-1]) if len(sma_ref) else None
    sma_prev = _safe_float(sma_ref.iloc[-2]) if len(sma_ref) >= 2 else None
    delta = (close_t - sma_t) if (close_t is not None and sma_t is not None) else None

    cross_up = bool(
        close_t is not None
        and sma_t is not None
        and close_prev is not None
        and sma_prev is not None
        and close_t > sma_t
        and close_prev <= sma_prev
    )
    cross_down = bool(
        close_t is not None
        and sma_t is not None
        and close_prev is not None
        and sma_prev is not None
        and close_t < sma_t
        and close_prev >= sma_prev
    )

    allow_short = _safe_bool(strategy_params.get("allow_short"), default=False)
    signal_mode = str(
        strategy_params.get("signal_mode")
        or strategy_params.get("sma_signal_mode")
        or "level"
    ).strip().lower()
    if signal_mode not in {"cross", "level"}:
        signal_mode = "level"

    data_ok = bool(close_t is not None and sma_t is not None)
    mode_condition = False
    raw_direction = 0
    if data_ok:
        if signal_mode == "cross":
            mode_condition = bool(cross_up or cross_down)
            if cross_up:
                raw_direction = 1
            elif cross_down:
                raw_direction = -1
        else:
            mode_condition = bool(abs(float(delta or 0.0)) > 1e-12)
            if close_t > sma_t:
                raw_direction = 1
            elif close_t < sma_t:
                raw_direction = -1

    short_signal_detected = raw_direction < 0 or bool(close_t is not None and sma_t is not None and close_t < sma_t)
    allow_short_ok = bool(not short_signal_detected or allow_short)
    if raw_direction < 0 and not allow_short:
        raw_direction = 0

    cooldown_bars = _safe_int(portfolio_params.get("cooldown_bars"), 0)
    cooldown_ok = True
    bars_since_last_signal_change = None
    sig = pd.to_numeric(signals, errors="coerce").fillna(0.0) if len(signals) else pd.Series(dtype="float64")
    if cooldown_bars > 0 and len(sig) > 1 and raw_direction != 0:
        change_idx = sig[sig.diff().fillna(0.0) != 0.0].index
        if len(change_idx):
            last_change = change_idx[-1]
            if isinstance(sig.index, pd.DatetimeIndex) and isinstance(last_change, pd.Timestamp):
                bars_since_last_signal_change = len(sig) - 1 - int(sig.index.get_loc(last_change))
            else:
                bars_since_last_signal_change = len(sig) - 1
            cooldown_ok = bool((bars_since_last_signal_change or 0) >= cooldown_bars)

    volume_gate = dict(portfolio_params.get("volume_gate") or {})
    use_volume_gate = _safe_bool(volume_gate.get("enabled"), default=_safe_bool(portfolio_params.get("use_volume_gate"), False))
    volume_gate_kind = str(
        volume_gate.get("kind")
        or portfolio_params.get("volume_gate_kind")
        or "min_ratio_adv"
    ).strip().lower()
    min_volume_abs = _safe_float(volume_gate.get("min_volume_abs"))
    if min_volume_abs is None:
        min_volume_abs = _safe_float(portfolio_params.get("min_volume_abs"))
        if min_volume_abs is None:
            min_volume_abs = 0.0
    min_volume_ratio_adv = _safe_float(volume_gate.get("min_volume_ratio_adv"))
    if min_volume_ratio_adv is None:
        min_volume_ratio_adv = _safe_float(portfolio_params.get("min_volume_ratio_adv"))
        if min_volume_ratio_adv is None:
            min_volume_ratio_adv = 0.1
    adv_window = _safe_int(volume_gate.get("adv_window") or portfolio_params.get("volume_gate_adv_window"), 20)
    vol_now = _safe_float(volume.iloc[-1]) if len(volume) else None
    adv = volume.rolling(adv_window, min_periods=max(5, min(adv_window, 20))).mean() if len(volume) else pd.Series(dtype="float64")
    adv_now = _safe_float(adv.iloc[-1]) if len(adv) else None
    vol_ratio = (vol_now / adv_now) if (vol_now is not None and adv_now not in (None, 0.0)) else None
    if not use_volume_gate:
        volume_ok = True
    elif volume_gate_kind == "min_abs":
        volume_ok = bool(vol_now is not None and vol_now >= float(min_volume_abs))
    else:
        volume_ok = bool(vol_ratio is not None and vol_ratio >= float(min_volume_ratio_adv))

    all_checks_ok = bool(data_ok and mode_condition and allow_short_ok and cooldown_ok and volume_ok)
    final_direction = raw_direction if all_checks_ok else 0

    return {
        "rule_name": f"{strategy_kind}.signal",
        "inputs": {
            "signal_mode": signal_mode,
            "allow_short": allow_short,
            "close_t": close_t,
            "sma_ref_t": sma_t,
            "close_t_minus_sma_ref_t": delta,
            "cross_up": cross_up,
            "cross_down": cross_down,
            "cooldown_bars": cooldown_bars,
            "bars_since_last_signal_change": bars_since_last_signal_change,
            "use_volume_gate": use_volume_gate,
            "volume_gate_kind": volume_gate_kind,
            "volume_t": vol_now,
            "adv_t": adv_now,
            "volume_ratio_adv": vol_ratio,
        },
        "checks": [
            {
                "name": "data_ok",
                "expr": "close_t and sma_ref_t are finite",
                "value": {"close_t": close_t, "sma_ref_t": sma_t},
                "threshold": "finite",
                "pass": bool(data_ok),
            },
            {
                "name": "signal_condition",
                "expr": "cross_up/cross_down when mode=cross, else close_t != sma_ref_t",
                "value": {"signal_mode": signal_mode, "cross_up": cross_up, "cross_down": cross_down, "delta": delta},
                "threshold": {"mode": signal_mode},
                "pass": bool(mode_condition),
            },
            {
                "name": "allow_short_gate",
                "expr": "if bearish signal then allow_short must be true",
                "value": {"allow_short": allow_short, "short_signal_detected": short_signal_detected},
                "threshold": True,
                "pass": bool(allow_short_ok),
            },
            {
                "name": "cooldown_ok",
                "expr": "bars_since_last_signal_change >= cooldown_bars",
                "value": bars_since_last_signal_change,
                "threshold": cooldown_bars,
                "pass": bool(cooldown_ok),
            },
            {
                "name": "volume_ok",
                "expr": "volume >= min_abs or volume/ADV >= min_ratio_adv",
                "value": {"volume_t": vol_now, "adv_t": adv_now, "volume_ratio_adv": vol_ratio},
                "threshold": {
                    "enabled": use_volume_gate,
                    "kind": volume_gate_kind,
                    "min_volume_abs": min_volume_abs,
                    "min_volume_ratio_adv": min_volume_ratio_adv,
                },
                "pass": bool(volume_ok),
            },
        ],
        "final_direction": int(final_direction),
        "strategy_direction": int(strategy_direction),
        "final_direction_label": _normalize_direction_label(int(final_direction)),
    }


def _param_description(key: str) -> tuple[str, str]:
    meta: dict[str, tuple[str, str]] = {
        "strategy.sma_window": ("SMA reference lookback window.", "Higher values smooth and delay turns."),
        "strategy.signal_mode": ("Signal generation mode (level vs cross).", "Cross is sparse; level is continuous."),
        "strategy.allow_short": ("Allow short directional signals.", "If false, bearish setup can be forced neutral."),
        "portfolio.cooldown_bars": ("Minimum bars between signal changes.", "Reduces churn, may suppress fresh signals."),
        "portfolio.volume_gate.enabled": ("Volume filter switch.", "Can block low-liquidity entries."),
        "portfolio.volume_gate.kind": ("Volume gate metric.", "Controls how liquidity threshold is evaluated."),
        "portfolio.volume_gate.min_volume_ratio_adv": ("Min Volume/ADV ratio.", "Higher threshold is stricter."),
        "portfolio.volume_gate.min_volume_abs": ("Absolute minimum volume.", "Rejects thin bars."),
    }
    return meta.get(key, ("Active run parameter.", "Contributes to run behavior and signal path."))

@router.get("/{run_id}/decisions", response_model=list[StrategyDecisionOut])
def list_strategy_decisions(
    run_id: UUID,
    symbol: str | None = None,
    best_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    q = db.query(StrategyDecision).filter(StrategyDecision.run_id == run_id)
    if symbol:
        q = q.filter(sa.func.upper(StrategyDecision.symbol) == str(symbol).strip().upper())
    if best_only:
        q = q.filter(StrategyDecision.rank == 1)

    rows = q.order_by(
        StrategyDecision.symbol.asc(),
        StrategyDecision.rank.asc().nullslast(),
        StrategyDecision.confidence_score.desc(),
        StrategyDecision.opportunity_score.desc(),
    ).all()
    return [_strategy_decision_to_out(row) for row in rows]


@router.get("/{run_id}/decisions/{symbol}/{strategy}/{trial_id}", response_model=StrategyDecisionOut)
def get_strategy_decision(
    run_id: UUID,
    symbol: str,
    strategy: str,
    trial_id: str,
    db: Session = Depends(get_db),
):
    row = (
        db.query(StrategyDecision)
        .filter(StrategyDecision.run_id == run_id)
        .filter(sa.func.upper(StrategyDecision.symbol) == str(symbol).strip().upper())
        .filter(sa.func.lower(StrategyDecision.strategy_kind) == str(strategy).strip().lower())
        .filter(StrategyDecision.trial_id == str(trial_id).strip())
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="decision_not_found")
    return _strategy_decision_to_out(row)


@router.get(
    "/{run_id}/decisions/{symbol}/{strategy}/{trial_id}/dashboard",
    response_model=DecisionDashboardOut,
)
def get_strategy_decision_dashboard(
    run_id: UUID,
    symbol: str,
    strategy: str,
    trial_id: str,
    bars: int = Query(default=320, ge=120, le=1200),
    db: Session = Depends(get_db),
):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    row = (
        db.query(StrategyDecision)
        .filter(StrategyDecision.run_id == run_id)
        .filter(sa.func.upper(StrategyDecision.symbol) == str(symbol).strip().upper())
        .filter(sa.func.lower(StrategyDecision.strategy_kind) == str(strategy).strip().lower())
        .filter(StrategyDecision.trial_id == str(trial_id).strip())
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="decision_not_found")

    run_spec = dict(run.spec_json or {})
    decision_page = _as_json_dict(row.decision_page_json)
    decision_params = _as_json_dict(row.params_json)
    strategy_kind = str(row.strategy_kind or strategy or "").strip().lower()
    symbol_norm = str(row.symbol or symbol or "").strip()

    strategy_effective, portfolio_effective, merged_flat = _effective_strategy_and_portfolio_params(
        run_spec=run_spec,
        decision_params=decision_params,
    )

    from core.quant_core.decision import compute_levels_support_resistance, compute_rr_and_invalidation

    temp_files: list[Path] = []
    out: dict[str, Any] = {}
    materialization_warning: str | None = None
    try:
        try:
            spec_json, temp_files = _prepare_detail_spec(
                db=db,
                run=run,
                symbol=symbol_norm,
                strategy_kind=strategy_kind,
                strategy_params=strategy_effective,
                portfolio_overrides=portfolio_effective,
            )
            from core.quant_core.pipeline import run_pipeline

            _assert_wfo_resolved_dates(spec_json, caller="strategy_decision_detail")
            out_raw = run_pipeline(spec_json)
            if isinstance(out_raw, dict):
                out = out_raw
        except HTTPException as exc:
            materialization_warning = f"http_{exc.status_code}:{exc.detail}"
        except Exception as exc:
            materialization_warning = f"pipeline_error:{exc.__class__.__name__}"
    finally:
        for p in temp_files:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    strategy_results = dict(out.get("strategy_results") or {})
    strategy_payload = strategy_results.get(strategy_kind)
    if not isinstance(strategy_payload, dict) and strategy_results:
        strategy_payload = next(iter(strategy_results.values()))
    if not isinstance(strategy_payload, dict):
        strategy_payload = {}

    decision_inputs = dict(strategy_payload.get("decision_inputs") or {})
    by_symbol_inputs = decision_inputs.get("symbols")
    symbol_payload = _match_symbol_payload(by_symbol_inputs, symbol_norm)

    bars_df = _records_to_frame(symbol_payload.get("bars")).tail(int(bars))
    features_df = _records_to_frame(symbol_payload.get("features")).reindex(bars_df.index)
    signals_df = _records_to_frame(symbol_payload.get("signals")).reindex(bars_df.index)

    open_s = _pick_series(bars_df, ["Open", "open"]).reindex(bars_df.index)
    high_s = _pick_series(bars_df, ["High", "high"]).reindex(bars_df.index)
    low_s = _pick_series(bars_df, ["Low", "low"]).reindex(bars_df.index)
    close_s = _pick_series(bars_df, ["Close", "close"]).reindex(bars_df.index)
    volume_s = _pick_series(bars_df, ["Volume", "volume"]).reindex(bars_df.index)

    sma_window = _safe_int(strategy_effective.get("sma_window") or strategy_effective.get("window"), 50)
    sma_ref = _pick_series(features_df, [f"sma_{sma_window}", "sma_ref"]).reindex(bars_df.index)
    if sma_ref.empty or sma_ref.notna().sum() == 0:
        sma_ref = close_s.rolling(sma_window, min_periods=sma_window).mean()
    sma100 = _pick_series(features_df, ["sma_100", "sma100"]).reindex(bars_df.index)
    if sma100.empty or sma100.notna().sum() == 0:
        sma100 = close_s.rolling(100, min_periods=100).mean()
    sma200 = _pick_series(features_df, ["sma_200", "sma200"]).reindex(bars_df.index)
    if sma200.empty or sma200.notna().sum() == 0:
        sma200 = close_s.rolling(200, min_periods=200).mean()

    rsi14 = _pick_series(features_df, ["rsi_14", "rsi14"]).reindex(bars_df.index)
    if rsi14.empty or rsi14.notna().sum() == 0:
        rsi14 = _compute_rsi(close_s, window=14)
    adx = _pick_series(features_df, ["adx_14", "adx14", "adx"]).reindex(bars_df.index)
    atr = _pick_series(features_df, ["atr_14", "atr14", "atr"]).reindex(bars_df.index)
    if atr.empty or atr.notna().sum() == 0:
        atr = _compute_atr_14(high_s, low_s, close_s)
    signal_series = _pick_series(signals_df, ["signal"]).reindex(bars_df.index).fillna(0.0)

    strategy_direction = _direction_to_int(decision_page.get("direction"))
    signal_debug = _build_signal_debug_snapshot(
        strategy_kind=strategy_kind,
        strategy_direction=strategy_direction,
        close=close_s,
        sma_ref=sma_ref,
        volume=volume_s,
        signals=signal_series,
        strategy_params=strategy_effective,
        portfolio_params=portfolio_effective,
    )
    final_direction = _safe_int(signal_debug.get("final_direction"), 0)

    levels_calc = {}
    risk_calc = {}
    try:
        levels_calc = dict(
            compute_levels_support_resistance(
                pd.DataFrame(
                    {
                        "Open": open_s,
                        "High": high_s,
                        "Low": low_s,
                        "Close": close_s,
                        "Volume": volume_s,
                    }
                ),
                direction=final_direction,
            )
            or {}
        )
        risk_calc = dict(
            compute_rr_and_invalidation(
                direction=final_direction,
                entry=_safe_float(levels_calc.get("entry")),
                stop=_safe_float(levels_calc.get("stop")),
                target=_safe_float(levels_calc.get("target")),
            )
            or {}
        )
    except Exception:
        levels_calc = {}
        risk_calc = {}

    levels_payload = {
        "entry": _safe_float(levels_calc.get("entry")) if levels_calc else _safe_float((decision_page.get("levels") or {}).get("entry")),
        "stop": _safe_float(levels_calc.get("stop")) if levels_calc else _safe_float((decision_page.get("levels") or {}).get("stop")),
        "target": _safe_float(levels_calc.get("target")) if levels_calc else _safe_float((decision_page.get("levels") or {}).get("target")),
        "support": _safe_float(levels_calc.get("support")) if levels_calc else _safe_float((decision_page.get("levels") or {}).get("support")),
        "resistance": _safe_float(levels_calc.get("resistance")) if levels_calc else _safe_float((decision_page.get("levels") or {}).get("resistance")),
    }

    risk_payload = {
        "rr": _safe_float(risk_calc.get("rr"))
        if risk_calc
        else _safe_float((decision_page.get("risk") or {}).get("rr")),
        "risk_per_share": _safe_float(risk_calc.get("risk_per_share"))
        if risk_calc
        else _safe_float((decision_page.get("risk") or {}).get("risk_per_share")),
        "reward_per_share": _safe_float(risk_calc.get("reward_per_share"))
        if risk_calc
        else _safe_float((decision_page.get("risk") or {}).get("reward_per_share")),
        "invalidation": str(risk_calc.get("invalidation") or (decision_page.get("risk") or {}).get("invalidation") or ""),
    }
    levels_payload["rr"] = risk_payload.get("rr")
    levels_payload["risk_per_share"] = risk_payload.get("risk_per_share")
    levels_payload["reward_per_share"] = risk_payload.get("reward_per_share")

    regime_payload = _build_regime_payload(
        pd.DataFrame(
            {
                "Open": open_s,
                "High": high_s,
                "Low": low_s,
                "Close": close_s,
                "Volume": volume_s,
            }
        )
    )

    signal_markers: list[dict[str, Any]] = []
    cross_markers: list[dict[str, Any]] = []
    t_values = _to_iso_timestamps(bars_df.index)
    close_values = _to_float_list(close_s)
    sma_values = _to_float_list(sma_ref)
    signal_values = _to_float_list(signal_series)
    for i in range(len(t_values)):
        sig_val = _safe_float(signal_values[i])
        close_val = _safe_float(close_values[i])
        sma_val = _safe_float(sma_values[i])
        if sig_val is not None and sig_val != 0 and close_val is not None:
            signal_markers.append(
                {
                    "t": t_values[i],
                    "value": close_val,
                    "direction": 1 if sig_val > 0 else -1,
                    "kind": "signal",
                }
            )
        if i <= 0:
            continue
        prev_close = _safe_float(close_values[i - 1])
        prev_sma = _safe_float(sma_values[i - 1])
        if prev_close is None or prev_sma is None or close_val is None or sma_val is None:
            continue
        is_cross_up = bool(close_val > sma_val and prev_close <= prev_sma)
        is_cross_down = bool(close_val < sma_val and prev_close >= prev_sma)
        if is_cross_up or is_cross_down:
            cross_markers.append(
                {
                    "t": t_values[i],
                    "value": close_val,
                    "direction": 1 if is_cross_up else -1,
                    "kind": "cross_up" if is_cross_up else "cross_down",
                }
            )

    dist_sma100 = None
    close_t = _safe_float(close_s.iloc[-1]) if len(close_s) else None
    sma100_t = _safe_float(sma100.iloc[-1]) if len(sma100) else None
    if close_t is not None and sma100_t not in (None, 0.0):
        dist_sma100 = (close_t - sma100_t) / abs(sma100_t)

    sma200_slope_20 = None
    if len(sma200) >= 21:
        sma200_now = _safe_float(sma200.iloc[-1])
        sma200_prev = _safe_float(sma200.iloc[-21])
        if sma200_now is not None and sma200_prev not in (None, 0.0):
            sma200_slope_20 = (sma200_now - sma200_prev) / abs(sma200_prev)

    atr_t = _safe_float(atr.iloc[-1]) if len(atr) else None
    rsi_t = _safe_float(rsi14.iloc[-1]) if len(rsi14) else None
    adx_t = _safe_float(adx.iloc[-1]) if len(adx) else None
    vol_ratio_20 = None
    vol_mean_20 = volume_s.rolling(20, min_periods=5).mean() if len(volume_s) else pd.Series(dtype="float64")
    vol_t = _safe_float(volume_s.iloc[-1]) if len(volume_s) else None
    vol_mean_t = _safe_float(vol_mean_20.iloc[-1]) if len(vol_mean_20) else None
    if vol_t is not None and vol_mean_t not in (None, 0.0):
        vol_ratio_20 = vol_t / vol_mean_t

    derived_metrics = {
        "close_t": close_t,
        "sma_ref_t": _safe_float(sma_ref.iloc[-1]) if len(sma_ref) else None,
        "distance_to_sma100": dist_sma100,
        "sma200_slope_20": sma200_slope_20,
        "atr_14": atr_t,
        "rsi_14": rsi_t,
        "adx_14": adx_t,
        "volume_ratio_20": vol_ratio_20,
        "signal_mode": signal_debug.get("inputs", {}).get("signal_mode"),
    }
    if materialization_warning:
        derived_metrics["materialization_warning"] = materialization_warning
    if bars_df.empty:
        derived_metrics["materialization_warning"] = derived_metrics.get("materialization_warning") or "dashboard_bars_unavailable"

    opportunity_layers = dict((decision_page.get("opportunity") or {}).get("layers") or {})
    reason_rows: list[dict[str, Any]] = []
    sorted_layers = sorted(
        (
            (name, payload if isinstance(payload, dict) else {})
            for name, payload in opportunity_layers.items()
        ),
        key=lambda item: (_safe_float((item[1] or {}).get("score")) or 0.0),
        reverse=True,
    )
    for name, payload in sorted_layers[:3]:
        score = _safe_float(payload.get("score"))
        reason_rows.append(
            {
                "name": str(name),
                "score": score,
                "detail": str(payload.get("explain") or ""),
            }
        )
    if not reason_rows:
        reason_rows = [
            {"name": "regime_bias", "score": None, "detail": str(regime_payload.get("label") or "unknown")},
            {"name": "signal_delta", "score": None, "detail": f"close-sma={_safe_float(signal_debug.get('inputs', {}).get('close_t_minus_sma_ref_t'))}"},
            {"name": "risk_rr", "score": _safe_float(risk_payload.get("rr")), "detail": "Reward/risk ratio"},
        ]

    confidence_layers = []
    for layer_name, payload in dict((decision_page.get("confidence") or {}).get("layers") or {}).items():
        if not isinstance(payload, dict):
            continue
        confidence_layers.append(
            {
                "name": str(layer_name),
                "score": _safe_float(payload.get("score")),
                "weight": _safe_float(payload.get("weight")),
                "metrics": dict(payload.get("inputs") or {}),
                "impact": str(payload.get("explain") or ""),
            }
        )

    comparison_rows = (
        db.query(StrategyDecision)
        .filter(StrategyDecision.run_id == run_id)
        .filter(sa.func.upper(StrategyDecision.symbol) == symbol_norm.upper())
        .order_by(StrategyDecision.rank.asc().nullslast(), StrategyDecision.confidence_score.desc(), StrategyDecision.opportunity_score.desc())
        .all()
    )
    frameworks = []
    directions_seen: set[str] = set()
    statuses_seen: set[str] = set()
    for item in comparison_rows:
        page = _as_json_dict(item.decision_page_json)
        direction = str(page.get("direction") or "neutral")
        status = str(item.status or page.get("status") or "watch")
        directions_seen.add(direction)
        statuses_seen.add(status)
        frameworks.append(
            {
                "strategy_kind": item.strategy_kind,
                "trial_id": item.trial_id,
                "rank": item.rank,
                "direction": direction,
                "status": status,
                "opportunity": _safe_float(item.opportunity_score),
                "confidence": _safe_float(item.confidence_score),
                "rr": _safe_float((_as_json_dict(page.get("risk") if isinstance(page, dict) else {}).get("rr"))),
            }
        )
    all_identical = bool(len(frameworks) > 1 and len(directions_seen) == 1 and len(statuses_seen) == 1)
    framework_comparison = {
        "all_identical": all_identical,
        "note": "All frameworks currently imply the same direction/status." if all_identical else "Frameworks diverge on direction and/or quality.",
        "frameworks": frameworks,
    }

    strategy_params_rows = []
    for key in sorted(merged_flat.keys()):
        description, impact = _param_description(key)
        strategy_params_rows.append(
            {
                "key": key,
                "value": merged_flat.get(key),
                "description": description,
                "impact": impact,
            }
        )

    decision_summary = {
        "symbol": symbol_norm,
        "strategy_kind": strategy_kind,
        "trial_id": row.trial_id,
        "direction": str(decision_page.get("direction") or _normalize_direction_label(strategy_direction)),
        "status": str(row.status or decision_page.get("status") or "watch"),
        "opportunity": _safe_float(row.opportunity_score),
        "confidence": _safe_float(row.confidence_score),
        "rr": _safe_float(risk_payload.get("rr")),
        "as_of_date": decision_page.get("as_of_date"),
        "reasons": reason_rows,
    }

    return {
        "decision_summary": decision_summary,
        "strategy_params": strategy_params_rows,
        "derived_metrics": derived_metrics,
        "regime": regime_payload,
        "signal_debug": signal_debug,
        "levels": levels_payload,
        "confidence_layers": confidence_layers,
        "framework_comparison": framework_comparison,
        "timeseries": {
            "t": t_values,
            "open": _to_float_list(open_s),
            "high": _to_float_list(high_s),
            "low": _to_float_list(low_s),
            "close": close_values,
            "volume": _to_float_list(volume_s),
            "sma_ref": sma_values,
            "sma100": _to_float_list(sma100),
            "sma200": _to_float_list(sma200),
            "rsi14": _to_float_list(rsi14),
            "adx": _to_float_list(adx),
            "atr": _to_float_list(atr),
            "signal_markers": signal_markers,
            "cross_markers": cross_markers,
        },
    }


@router.post("/{run_id}/materialize-strategy-details", response_model=MaterializeStrategyDetailsResponse)
def materialize_strategy_details(
    run_id: UUID,
    payload: MaterializeStrategyDetailsRequest,
    db: Session = Depends(get_db),
):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    strategy_kind = str(payload.strategy_kind or "").strip().lower()
    symbol = str(payload.symbol or "").strip()
    if not strategy_kind:
        raise HTTPException(status_code=400, detail="strategy_kind is required")
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    temp_files: list[Path] = []
    try:
        spec_json, temp_files = _prepare_detail_spec(
            db=db,
            run=run,
            symbol=symbol,
            strategy_kind=strategy_kind,
            strategy_params=dict(payload.strategy_params or {}),
            portfolio_overrides=dict(payload.portfolio_overrides or {}),
        )

        from core.quant_core.pipeline import run_pipeline  # local import keeps API startup light

        _assert_wfo_resolved_dates(spec_json, caller="materialize_strategy_details")
        out = run_pipeline(spec_json)
        strategy_results = dict(out.get("strategy_results") or {})
        strategy_payload = strategy_results.get(strategy_kind)
        if not isinstance(strategy_payload, dict) and strategy_results:
            strategy_payload = next(iter(strategy_results.values()))
        if not isinstance(strategy_payload, dict):
            raise HTTPException(status_code=500, detail="strategy details could not be materialized")

        plots: dict[str, Any] = {}
        plot_artifacts = strategy_payload.get("plot_artifacts")
        if isinstance(plot_artifacts, dict):
            symbol_key = symbol.strip().upper()
            figure = None
            for sym_key, candidate in plot_artifacts.items():
                if str(sym_key).strip().upper() == symbol_key:
                    figure = candidate
                    break
            if figure is None and plot_artifacts:
                figure = next(iter(plot_artifacts.values()))
            if isinstance(figure, dict):
                plots["price_indicators_trades"] = figure

        summary_plots = strategy_payload.get("summary_plot_artifacts")
        if isinstance(summary_plots, dict):
            for name, figure in summary_plots.items():
                if isinstance(name, str) and isinstance(figure, dict):
                    plots[name] = figure

        signal_label = None
        signal_today = None
        signal_date = None
        for row in list(out.get("leaderboard") or []):
            if not isinstance(row, dict):
                continue
            row_symbol = str(row.get("symbol") or "").strip().upper()
            row_kind = str(row.get("strategy_kind") or row.get("Strategy") or "").strip().lower()
            if row_kind != strategy_kind:
                continue
            if row_symbol and row_symbol != symbol.strip().upper():
                continue
            signal_label = row.get("signal_label")
            signal_today = _as_summary_float(row.get("signal_today"))
            signal_date = row.get("signal_date")
            break

        trade_performance_raw = strategy_payload.get("trade_performance")
        trade_performance = (
            [row for row in list(trade_performance_raw) if isinstance(row, dict)]
            if isinstance(trade_performance_raw, list)
            else []
        )
        trade_ledger_raw = strategy_payload.get("trade_ledger")
        trade_ledger = (
            [row for row in list(trade_ledger_raw) if isinstance(row, dict)]
            if isinstance(trade_ledger_raw, list)
            else []
        )
        metrics = dict(strategy_payload.get("metrics") or {})

        return {
            "run_id": run.id,
            "symbol": symbol,
            "strategy_kind": strategy_kind,
            "metrics": metrics,
            "trade_performance": trade_performance,
            "trade_ledger": trade_ledger,
            "plots": plots,
            "signal_label": signal_label,
            "signal_today": signal_today,
            "signal_date": signal_date,
        }
    finally:
        for p in temp_files:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass


@router.get("/{run_id}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(run_id: UUID, symbol: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Artifact).filter(Artifact.run_id == run_id)
    if symbol is not None:
        q = q.filter(Artifact.symbol == symbol)
    rows = q.order_by(Artifact.created_at.desc()).all()

    out = []
    for a in rows:
        out.append(
            {
                "id": a.id,
                "run_id": a.run_id,
                "symbol": a.symbol,
                "artifact_type": a.artifact_type,
                "name": a.name,
                "object_key": a.object_key,
                "bucket": a.bucket,
                "content_type": a.content_type,
                "size_bytes": int(a.size_bytes),
                "sha256": a.sha256,
                "created_at": a.created_at,
                "url": presign_get(a.object_key, expires_seconds=300),
            }
        )
    return out
