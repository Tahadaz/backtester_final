from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import UUID

import pandas as pd
from plotly.utils import PlotlyJSONEncoder
from rq import get_current_job
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.quant_core.analysis.defaults_discovery import (
    TRADING_HORIZON_VALUES,
    discover_sma_defaults,
)
try:
    from core.quant_core.analysis.defaults_discovery import discover_sma_defaults_all_horizons
except ImportError:
    # Backward compatibility for older quant-core versions that don't expose
    # multi-horizon discovery yet.
    discover_sma_defaults_all_horizons = None
from core.quant_core.research.horizon import get_horizon_config
from services.worker.config import settings
from services.worker.db import SessionLocal
from services.worker.storage import ensure_bucket, s3_client


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _rq_job_id() -> str | None:
    try:
        job = get_current_job()
        return job.id if job else None
    except Exception:
        return None


def _set_progress(
    db: Session,
    run_id: UUID,
    job_id: str | None,
    *,
    pct: float | int | None = None,
    stage: str | None = None,
    message: str | None = None,
) -> None:
    pct_out = None
    if pct is not None:
        try:
            pct_out = int(max(0, min(100, float(pct))))
        except Exception:
            pct_out = None

    if job_id:
        try:
            job = get_current_job()
            if job is not None:
                meta = job.meta or {}
                if pct_out is not None:
                    meta["progress_pct"] = pct_out
                if stage is not None:
                    meta["progress_stage"] = stage
                if message is not None:
                    meta["progress_message"] = message
                meta["heartbeat"] = _utcnow().isoformat()
                job.meta = meta
                job.save_meta()
        except Exception:
            pass

    db.execute(
        text(
            """
            update defaults_discovery_run
            set progress_pct = :pct,
                progress_stage = :stage,
                progress_message = :message,
                last_heartbeat_at = :ts
            where id = :id
            """
        ),
        {
            "id": run_id,
            "pct": pct_out,
            "stage": stage,
            "message": message,
            "ts": _utcnow(),
        },
    )
    db.commit()


def _sanitize_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): _sanitize_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_json(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _normalize_ticker(raw: Any) -> str | None:
    symbol = str(raw or "").strip().upper()
    if not symbol:
        return None
    symbol = re.sub(r"\s*\([^)]+\)\s*$", "", symbol).strip()
    return symbol or None


def _is_placeholder_sheet_symbol(raw: Any) -> bool:
    sym = str(raw or "").strip().upper()
    if not sym:
        return True
    if sym in {"UPLOAD", "DATASET"}:
        return True
    if re.match(r"^FEUIL(?:LE)?\d*$", sym):
        return True
    if re.match(r"^SHEET\d*$", sym):
        return True
    return False


def _normalize_symbol_list(raw: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    if not isinstance(raw, list):
        return out
    for item in raw:
        sym = _normalize_ticker(item)
        if not sym or _is_placeholder_sheet_symbol(sym) or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def _dataset_has_symbol(*, row: dict[str, Any], symbol: str) -> bool:
    target = _normalize_ticker(symbol)
    if not target:
        return False
    direct = _normalize_ticker(row.get("symbol"))
    if direct == target:
        return True
    meta = row.get("meta_json")
    if isinstance(meta, dict):
        detected = set(_normalize_symbol_list(meta.get("detected_symbols")))
        return target in detected
    return False


def _find_latest_dataset_for_symbol(db: Session, *, symbol: str) -> UUID | None:
    rows = db.execute(
        text(
            """
            select id, symbol, meta_json
            from dataset
            order by created_at desc
            limit 500
            """
        )
    ).mappings().all()
    for row in rows:
        row_map = dict(row)
        if _dataset_has_symbol(row=row_map, symbol=symbol):
            rid = row_map.get("id")
            if rid is None:
                continue
            return UUID(str(rid))
    return None


def _normalize_horizon_token(raw: Any) -> str:
    token = str(raw or "").strip().lower()
    return token if token in TRADING_HORIZON_VALUES else ""


def _discover_sma_defaults_all_horizons_compat(
    bars: pd.DataFrame,
    *,
    buckets: list[dict[str, Any]],
    train_window: int | None,
    step_size: int | None,
    use_test_window: bool | None,
    test_window: int | None,
    enforce_feasible_train_half: bool,
    override_feasible_max_n: Any,
    allow_short: bool,
    signal_mode: str,
    score_drawdown_weight: float,
    score_turnover_weight: float,
    use_net_after_costs: bool,
    cost_model: dict[str, Any],
    mode_threshold: float,
    snap_to_nice: bool,
    buy_threshold_perc: float = 0.0,
    sell_threshold_perc: float = 0.0,
    cooldown_days: int = 0,
    min_volume: float = 0.0,
    primary_horizon: str = "medium",
    horizons: list[str] | None = None,
    horizon_overrides: dict[str, Any] | None = None,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    if discover_sma_defaults_all_horizons is not None:
        return discover_sma_defaults_all_horizons(
            bars,
            buckets=buckets,
            train_window=train_window,
            step_size=step_size,
            use_test_window=use_test_window,
            test_window=test_window,
            enforce_feasible_train_half=enforce_feasible_train_half,
            override_feasible_max_n=override_feasible_max_n,
            allow_short=allow_short,
            signal_mode=signal_mode,
            buy_threshold_perc=buy_threshold_perc,
            sell_threshold_perc=sell_threshold_perc,
            cooldown_days=cooldown_days,
            min_volume=min_volume,
            score_drawdown_weight=score_drawdown_weight,
            score_turnover_weight=score_turnover_weight,
            use_net_after_costs=use_net_after_costs,
            cost_model=cost_model,
            mode_threshold=mode_threshold,
            snap_to_nice=snap_to_nice,
            primary_horizon=primary_horizon,
            horizons=horizons or list(TRADING_HORIZON_VALUES),
            horizon_overrides=horizon_overrides or {},
            progress_callback=progress_callback,
        )

    normalized_horizons: list[str] = []
    for raw in list(horizons or TRADING_HORIZON_VALUES):
        token = _normalize_horizon_token(raw)
        if token and token not in normalized_horizons:
            normalized_horizons.append(token)
    if not normalized_horizons:
        normalized_horizons = list(TRADING_HORIZON_VALUES)

    active_horizon = _normalize_horizon_token(primary_horizon) or normalized_horizons[0]
    if active_horizon not in normalized_horizons:
        normalized_horizons.insert(0, active_horizon)

    total_horizons_scaled = max(len(normalized_horizons), 1) * 1000
    done_scaled = 0
    by_horizon: dict[str, dict[str, Any]] = {}
    for hz in normalized_horizons:
        local_done_scaled = 0

        def _on_progress(done: int, total: int) -> None:
            nonlocal local_done_scaled
            if progress_callback is None:
                return
            denom = max(int(total), 1)
            local_done_scaled = max(local_done_scaled, int((max(0, min(int(done), denom)) / denom) * 1000))
            progress_callback(min(done_scaled + local_done_scaled, total_horizons_scaled), total_horizons_scaled)

        use_explicit_windows = hz == active_horizon
        result = discover_sma_defaults(
            bars,
            buckets=buckets,
            train_window=(int(train_window) if use_explicit_windows and train_window is not None else None),
            step_size=(int(step_size) if use_explicit_windows and step_size is not None else None),
            use_test_window=use_test_window,
            test_window=(int(test_window) if use_explicit_windows and test_window is not None else None),
            enforce_feasible_train_half=bool(enforce_feasible_train_half),
            override_feasible_max_n=override_feasible_max_n,
            allow_short=bool(allow_short),
            signal_mode=str(signal_mode),
            buy_threshold_perc=float(buy_threshold_perc),
            sell_threshold_perc=float(sell_threshold_perc),
            cooldown_days=int(cooldown_days),
            min_volume=float(min_volume),
            score_drawdown_weight=float(score_drawdown_weight),
            score_turnover_weight=float(score_turnover_weight),
            use_net_after_costs=bool(use_net_after_costs),
            cost_model=cost_model,
            mode_threshold=float(mode_threshold),
            snap_to_nice=bool(snap_to_nice),
            horizon=hz,
            horizon_overrides=horizon_overrides,
            progress_callback=_on_progress if progress_callback is not None else None,
        )
        by_horizon[hz] = dict(result)
        done_scaled += 1000
        if progress_callback is not None:
            progress_callback(min(done_scaled, total_horizons_scaled), total_horizons_scaled)

    active_payload = dict(by_horizon.get(active_horizon) or by_horizon[normalized_horizons[0]])
    active_meta = dict(active_payload.get("meta") or {})
    active_meta["active_horizon"] = str(active_horizon)
    active_meta["computed_horizons"] = list(normalized_horizons)
    active_payload["meta"] = active_meta
    active_payload["active_horizon"] = str(active_horizon)
    active_payload["computed_horizons"] = list(normalized_horizons)
    active_payload["horizons"] = {key: value for key, value in by_horizon.items()}
    active_payload["defaults_by_horizon"] = {
        key: [int(x) for x in list((value or {}).get("defaults") or [])]
        for key, value in by_horizon.items()
    }
    active_payload["horizon_summaries"] = [
        {
            "horizon": key,
            "horizon_label": str(((value.get("meta") or {}).get("horizon_label")) if isinstance(value, dict) else ""),
            "window_count": int((value.get("window_count") or 0) if isinstance(value, dict) else 0),
            "defaults": [int(x) for x in list((value.get("defaults") or []) if isinstance(value, dict) else [])],
        }
        for key, value in by_horizon.items()
    ]
    return active_payload


def _upload_json(object_key: str, payload: Any) -> tuple[int, str]:
    ensure_bucket()
    s3 = s3_client()
    body = json.dumps(_sanitize_json(payload), ensure_ascii=False, allow_nan=False, cls=PlotlyJSONEncoder).encode("utf-8")
    s3.put_object(
        Bucket=settings.S3_BUCKET,
        Key=object_key,
        Body=body,
        ContentType="application/json",
    )
    import hashlib

    return len(body), hashlib.sha256(body).hexdigest()


def _upload_csv(object_key: str, frame: pd.DataFrame) -> tuple[int, str]:
    ensure_bucket()
    s3 = s3_client()
    body = frame.to_csv(index=False).encode("utf-8")
    s3.put_object(
        Bucket=settings.S3_BUCKET,
        Key=object_key,
        Body=body,
        ContentType="text/csv",
    )
    import hashlib

    return len(body), hashlib.sha256(body).hexdigest()


def _coerce_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        ts_col = None
        for cand in ("timestamp", "Timestamp", "date", "Date", "datetime", "Datetime"):
            if cand in out.columns:
                ts_col = cand
                break
        if ts_col is None:
            raise ValueError("data has no DatetimeIndex or timestamp column")
        out[ts_col] = pd.to_datetime(out[ts_col], errors="coerce")
        out = out.dropna(subset=[ts_col]).set_index(ts_col)
    out.index = pd.to_datetime(out.index, errors="coerce")
    out = out[~out.index.isna()]
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def _canonicalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = out.columns.astype(str).str.strip()
    col_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "price": "Close",
        "cloture": "Close",
        "clôture": "Close",
    }
    renamed = {}
    for col in list(out.columns):
        key = col.lower().strip()
        if key in col_map:
            renamed[col] = col_map[key]
    if renamed:
        out = out.rename(columns=renamed)

    if "Close" not in out.columns:
        raise ValueError("input data is missing Close column")

    for c in ("Open", "High", "Low", "Close", "Volume"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    if "Open" not in out.columns:
        out["Open"] = out["Close"]
    if "High" not in out.columns:
        out["High"] = out[["Open", "Close"]].max(axis=1)
    if "Low" not in out.columns:
        out["Low"] = out[["Open", "Close"]].min(axis=1)
    if "Volume" not in out.columns:
        out["Volume"] = 0.0

    out = out.dropna(subset=["Close"])
    return out[["Open", "High", "Low", "Close", "Volume"]]


def _materialize_dataset_file(*, filename: str, data_hash: str) -> Path:
    s3 = s3_client()
    object_key = f"datasets/{data_hash}/{filename}"
    payload = s3.get_object(Bucket=settings.S3_BUCKET, Key=object_key)["Body"].read()
    suffix = Path(filename).suffix or ".bin"
    tmp = NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(payload)
    finally:
        tmp.close()
    return Path(tmp.name)


def _materialize_store_parquet(*, object_key: str) -> Path:
    s3 = s3_client()
    payload = s3.get_object(Bucket=settings.S3_BUCKET, Key=object_key)["Body"].read()
    if not payload:
        raise RuntimeError(f"empty parquet object: {object_key}")
    tmp = NamedTemporaryFile(delete=False, suffix=".parquet")
    try:
        tmp.write(payload)
    finally:
        tmp.close()
    return Path(tmp.name)


def _load_bars_from_store(
    db: Session,
    *,
    ticker: str,
    timeframe: str,
) -> pd.DataFrame:
    row = db.execute(
        text("select object_key from market_data_store where symbol = :s and timeframe = :tf"),
        {"s": str(ticker).strip().upper(), "tf": str(timeframe).strip().upper()},
    ).mappings().first()
    if not row:
        raise RuntimeError(f"symbol not found in market_data_store: {ticker} ({timeframe})")
    temp_file = _materialize_store_parquet(object_key=str(row["object_key"]))
    try:
        frame = pd.read_parquet(temp_file)
        frame = _coerce_datetime_index(frame)
        return _canonicalize_ohlcv(frame)
    finally:
        try:
            temp_file.unlink(missing_ok=True)
        except Exception:
            pass


def _load_bars_from_dataset(
    db: Session,
    *,
    dataset_id: UUID,
    ticker: str | None,
) -> pd.DataFrame:
    row = db.execute(
        text("select filename, data_hash from dataset where id = :id"),
        {"id": dataset_id},
    ).mappings().first()
    if not row:
        raise RuntimeError(f"dataset not found: {dataset_id}")

    filename = str(row.get("filename") or "upload.xlsx")
    temp_file = _materialize_dataset_file(filename=filename, data_hash=str(row["data_hash"]))
    try:
        ext = Path(filename).suffix.lower()
        if ext in {".xlsx", ".xls"}:
            with pd.ExcelFile(temp_file) as xls:
                if ticker:
                    sheet_map = {str(name).strip().upper(): str(name) for name in xls.sheet_names}
                    sheet = sheet_map.get(str(ticker).strip().upper(), str(xls.sheet_names[0]))
                else:
                    sheet = str(xls.sheet_names[0])
                frame = pd.read_excel(xls, sheet_name=sheet, engine="openpyxl")
        elif ext == ".csv":
            frame = pd.read_csv(temp_file)
        else:
            raise RuntimeError(f"unsupported dataset extension: {ext}")

        frame = _coerce_datetime_index(frame)
        return _canonicalize_ohlcv(frame)
    finally:
        try:
            temp_file.unlink(missing_ok=True)
        except Exception:
            pass


def _filter_date_range(frame: pd.DataFrame, *, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    out = frame.copy()
    if start_date:
        start_ts = pd.to_datetime(start_date, errors="coerce")
        if pd.notna(start_ts):
            out = out[out.index >= start_ts]
    if end_date:
        end_ts = pd.to_datetime(end_date, errors="coerce")
        if pd.notna(end_ts):
            out = out[out.index <= end_ts]
    if out.empty:
        raise RuntimeError("No rows remain after applying date range.")
    return out


def _build_histogram_figure(winners_df: pd.DataFrame) -> dict[str, Any]:
    if winners_df.empty:
        return {"data": [], "layout": {"title": "Bucket Winner Histogram"}}

    traces = []
    for bucket_id, grp in winners_df.groupby("bucket_id"):
        traces.append(
            {
                "type": "histogram",
                "x": grp["best_n"].tolist(),
                "name": str(bucket_id),
                "opacity": 0.6,
            }
        )
    return {
        "data": traces,
        "layout": {
            "barmode": "overlay",
            "title": "Best n* Distribution by Bucket",
            "xaxis": {"title": "SMA window n"},
            "yaxis": {"title": "Count"},
        },
    }


def _build_selection_heatmap(matrix_df: pd.DataFrame) -> dict[str, Any]:
    if matrix_df.empty:
        return {"data": [], "layout": {"title": "Selection Heatmap"}}

    bucket_cols = [c for c in matrix_df.columns if c.startswith("B")]
    z = matrix_df[bucket_cols].T.to_numpy(dtype="float64")
    x = matrix_df["window_index"].tolist()
    y = bucket_cols
    return {
        "data": [
            {
                "type": "heatmap",
                "x": x,
                "y": y,
                "z": z.tolist(),
                "colorscale": "Blues",
            }
        ],
        "layout": {
            "title": "Selected Best n*(window, bucket)",
            "xaxis": {"title": "Walk-forward window"},
            "yaxis": {"title": "Bucket"},
        },
    }


def _build_bucket_metrics_figure(bucket_df: pd.DataFrame) -> dict[str, Any]:
    if bucket_df.empty:
        return {"data": [], "layout": {"title": "Bucket Metrics"}}

    labels = bucket_df["bucket_id"].astype(str).tolist()
    return {
        "data": [
            {
                "type": "bar",
                "x": labels,
                "y": bucket_df["win_rate"].astype(float).tolist(),
                "name": "Win rate",
                "yaxis": "y",
            },
            {
                "type": "scatter",
                "mode": "lines+markers",
                "x": labels,
                "y": bucket_df["stability_std"].astype(float).tolist(),
                "name": "Stability (std n*)",
                "yaxis": "y2",
            },
        ],
        "layout": {
            "title": "Win Rate vs Stability",
            "xaxis": {"title": "Bucket"},
            "yaxis": {"title": "Win rate"},
            "yaxis2": {"title": "Std dev", "overlaying": "y", "side": "right"},
        },
    }


def execute_defaults_discovery(run_id: str) -> dict[str, Any]:
    db: Session = SessionLocal()
    rid = UUID(run_id)
    job_id = _rq_job_id()

    try:
        row = db.execute(
            text(
                """
                select id, ticker, dataset_id, params_json
                from defaults_discovery_run
                where id = :id
                """
            ),
            {"id": rid},
        ).mappings().first()
        if not row:
            raise RuntimeError(f"defaults discovery run not found: {rid}")

        params_json = dict(row.get("params_json") or {})
        ticker = _normalize_ticker(row.get("ticker") or params_json.get("ticker"))
        dataset_id_raw = row.get("dataset_id") or params_json.get("dataset_id")
        dataset_id = UUID(str(dataset_id_raw)) if dataset_id_raw else None
        timeframe = str(params_json.get("timeframe") or "1D").strip().upper()

        db.execute(
            text(
                """
                update defaults_discovery_run
                set status='running',
                    error_message=null,
                    finished_at=null,
                    progress_pct=0,
                    progress_stage='running',
                    progress_message='Loading data',
                    last_heartbeat_at=:ts
                where id=:id
                """
            ),
            {"id": rid, "ts": _utcnow()},
        )
        db.commit()

        _set_progress(db, rid, job_id, pct=5, stage="loading_data", message="Loading bars")
        if dataset_id is not None:
            bars = _load_bars_from_dataset(db, dataset_id=dataset_id, ticker=ticker)
        else:
            if not ticker:
                raise RuntimeError("ticker is required when dataset_id is not provided")
            try:
                bars = _load_bars_from_store(db, ticker=ticker, timeframe=timeframe)
            except RuntimeError as store_exc:
                if "symbol not found in market_data_store" not in str(store_exc):
                    raise
                fallback_dataset_id = _find_latest_dataset_for_symbol(db, symbol=ticker)
                if fallback_dataset_id is None:
                    raise store_exc
                bars = _load_bars_from_dataset(db, dataset_id=fallback_dataset_id, ticker=ticker)

        bars = _filter_date_range(
            bars,
            start_date=params_json.get("start_date"),
            end_date=params_json.get("end_date"),
        )

        wf = dict(params_json.get("walk_forward") or {})
        score_settings = dict(params_json.get("score_settings") or {})
        signal_params = dict(params_json.get("signal_params") or {})
        horizon_overrides = (
            dict(params_json.get("horizon_overrides") or {})
            if isinstance(params_json.get("horizon_overrides"), dict)
            else None
        )
        requested_horizon = str(params_json.get("horizon") or "medium").strip().lower() or "medium"
        horizon_cfg = get_horizon_config(requested_horizon, overrides=horizon_overrides)
        compute_all_horizons = bool(params_json.get("compute_all_horizons", True))

        train_window_raw = wf.get("train_window")
        step_size_raw = wf.get("step_size")
        test_window_raw = wf.get("test_window")
        use_test_window_raw = wf.get("use_test_window")

        train_window_eff = int(train_window_raw) if train_window_raw not in (None, "") else int(horizon_cfg.train_window)
        step_size_eff = int(step_size_raw) if step_size_raw not in (None, "") else int(horizon_cfg.step_size)

        progress_scope = "short/medium/long" if compute_all_horizons else str(horizon_cfg.name.value)
        _set_progress(
            db,
            rid,
            job_id,
            pct=20,
            stage="walk_forward",
            message=f"Running walk-forward discovery ({progress_scope})",
        )
        if compute_all_horizons:
            total_windows_hint = 0
            for horizon_name in TRADING_HORIZON_VALUES:
                cfg = get_horizon_config(horizon_name, overrides=horizon_overrides)
                use_explicit_windows = horizon_name == requested_horizon
                h_train = int(train_window_raw) if use_explicit_windows and train_window_raw not in (None, "") else int(cfg.train_window)
                h_step = int(step_size_raw) if use_explicit_windows and step_size_raw not in (None, "") else int(cfg.step_size)
                total_windows_hint += max(
                    1,
                    int((max(0, len(bars) - int(h_train)) // max(1, int(h_step))) + 1),
                )
            total_windows_hint = max(int(total_windows_hint), 1)
        else:
            total_windows_hint = max(
                1,
                int(
                    (
                        max(0, len(bars) - int(train_window_eff))
                        // max(1, int(step_size_eff))
                    )
                    + 1
                ),
            )

        def _on_window_progress(done: int, total: int) -> None:
            denom = max(int(total), total_windows_hint, 1)
            pct = 20 + int((max(0, min(done, denom)) / denom) * 50)
            _set_progress(db, rid, job_id, pct=pct, stage="walk_forward", message=f"walk-forward window {done}/{denom}")

        if compute_all_horizons:
            results = _discover_sma_defaults_all_horizons_compat(
                bars,
                buckets=list(params_json.get("buckets") or []),
                train_window=(int(train_window_raw) if train_window_raw not in (None, "") else None),
                step_size=(int(step_size_raw) if step_size_raw not in (None, "") else None),
                use_test_window=(bool(use_test_window_raw) if use_test_window_raw is not None else None),
                test_window=(int(test_window_raw) if test_window_raw not in (None, "") else None),
                enforce_feasible_train_half=bool(wf.get("enforce_feasible_train_half", True)),
                override_feasible_max_n=wf.get("override_feasible_max_n"),
                allow_short=bool(params_json.get("allow_short", False)),
                signal_mode=str(params_json.get("signal_mode") or "level"),
                score_drawdown_weight=float(score_settings.get("drawdown_weight", 0.5)),
                score_turnover_weight=float(score_settings.get("turnover_weight", 0.1)),
                use_net_after_costs=bool(params_json.get("use_net_after_costs", False)),
                cost_model=dict(params_json.get("cost_model") or {}),
                mode_threshold=float(score_settings.get("mode_threshold", 0.20)),
                snap_to_nice=bool(params_json.get("snap_to_nice", True)),
                buy_threshold_perc=float(signal_params.get("buy_threshold_perc", 0.0)),
                sell_threshold_perc=float(signal_params.get("sell_threshold_perc", 0.0)),
                cooldown_days=int(signal_params.get("cooldown_days", 0)),
                min_volume=float(signal_params.get("min_volume", 0.0)),
                primary_horizon=requested_horizon,
                horizons=list(TRADING_HORIZON_VALUES),
                horizon_overrides=horizon_overrides,
                progress_callback=_on_window_progress,
            )
        else:
            results = discover_sma_defaults(
                bars,
                buckets=list(params_json.get("buckets") or []),
                train_window=(int(train_window_raw) if train_window_raw not in (None, "") else None),
                step_size=(int(step_size_raw) if step_size_raw not in (None, "") else None),
                use_test_window=(bool(use_test_window_raw) if use_test_window_raw is not None else None),
                test_window=(int(test_window_raw) if test_window_raw not in (None, "") else None),
                enforce_feasible_train_half=bool(wf.get("enforce_feasible_train_half", True)),
                override_feasible_max_n=wf.get("override_feasible_max_n"),
                allow_short=bool(params_json.get("allow_short", False)),
                signal_mode=str(params_json.get("signal_mode") or "level"),
                score_drawdown_weight=float(score_settings.get("drawdown_weight", 0.5)),
                score_turnover_weight=float(score_settings.get("turnover_weight", 0.1)),
                use_net_after_costs=bool(params_json.get("use_net_after_costs", False)),
                cost_model=dict(params_json.get("cost_model") or {}),
                mode_threshold=float(score_settings.get("mode_threshold", 0.20)),
                snap_to_nice=bool(params_json.get("snap_to_nice", True)),
                buy_threshold_perc=float(signal_params.get("buy_threshold_perc", 0.0)),
                sell_threshold_perc=float(signal_params.get("sell_threshold_perc", 0.0)),
                cooldown_days=int(signal_params.get("cooldown_days", 0)),
                min_volume=float(signal_params.get("min_volume", 0.0)),
                horizon=str(params_json.get("horizon") or "") or None,
                horizon_overrides=horizon_overrides,
                progress_callback=_on_window_progress,
            )

        _set_progress(db, rid, job_id, pct=75, stage="aggregating", message="Aggregating and uploading artifacts")
        results_meta = dict(results.get("meta") or {})
        horizon_name = str(results_meta.get("horizon") or horizon_cfg.name.value).strip().lower() or "medium"
        symbol_slug = str(ticker or "dataset").strip().upper() or "DATASET"
        prefix = f"defaults/wfo/sma_price/{symbol_slug}/{horizon_name}/{rid}"
        winners_df = pd.DataFrame(list(results.get("walk_forward_winners") or []))
        bucket_df = pd.DataFrame(list(results.get("bucket_reports") or []))
        defaults_df = pd.DataFrame(
            [{"index": i + 1, "bucket_id": f"B{i + 1}", "default_n": int(n)} for i, n in enumerate(results.get("defaults") or [])]
        )

        artifacts: dict[str, Any] = {
            "object_keys": {},
            "horizon": horizon_name,
            "compute_all_horizons": bool(compute_all_horizons),
            "available_horizons": list(results.get("computed_horizons") or [horizon_name]),
        }
        winners_key = f"{prefix}/tables/walk_forward_winners.csv"
        bucket_key = f"{prefix}/tables/bucket_summary.csv"
        defaults_key = f"{prefix}/tables/defaults.csv"

        _upload_csv(winners_key, winners_df if not winners_df.empty else pd.DataFrame(columns=["window_index", "bucket_id", "best_n"]))
        _upload_csv(bucket_key, bucket_df if not bucket_df.empty else pd.DataFrame(columns=["bucket_id", "chosen_default_n"]))
        _upload_csv(defaults_key, defaults_df)

        artifacts["object_keys"]["winners_csv"] = winners_key
        artifacts["object_keys"]["bucket_summary_csv"] = bucket_key
        artifacts["object_keys"]["defaults_csv"] = defaults_key

        hist_fig = _build_histogram_figure(winners_df)
        matrix_rows = []
        for row_item in list(results.get("selection_matrix") or []):
            item = dict(row_item or {})
            row_out = {"window_index": int(item.get("window_index", 0))}
            row_out.update(dict(item.get("selections") or {}))
            matrix_rows.append(row_out)
        matrix_df = pd.DataFrame(matrix_rows).sort_values("window_index") if matrix_rows else pd.DataFrame()
        heatmap_fig = _build_selection_heatmap(matrix_df)
        metric_fig = _build_bucket_metrics_figure(bucket_df)

        hist_key = f"{prefix}/plots/histogram.json"
        heatmap_key = f"{prefix}/plots/selection_heatmap.json"
        metric_key = f"{prefix}/plots/bucket_metrics.json"

        _upload_json(hist_key, hist_fig)
        _upload_json(heatmap_key, heatmap_fig)
        _upload_json(metric_key, metric_fig)

        artifacts["object_keys"]["histogram_plot_json"] = hist_key
        artifacts["object_keys"]["selection_heatmap_plot_json"] = heatmap_key
        artifacts["object_keys"]["bucket_metrics_plot_json"] = metric_key

        results_payload = dict(results)
        results_payload["exports"] = {
            "defaults": defaults_df.to_dict(orient="records"),
        }
        results_payload["artifact_keys"] = dict(artifacts.get("object_keys") or {})

        db.execute(
            text(
                """
                update defaults_discovery_run
                set status='succeeded',
                    progress_pct=100,
                    progress_stage='done',
                    progress_message='Succeeded',
                    results_json=cast(:results_json as jsonb),
                    artifacts_json=cast(:artifacts_json as jsonb),
                    finished_at=:ts,
                    last_heartbeat_at=:ts
                where id=:id
                """
            ),
            {
                "id": rid,
                "ts": _utcnow(),
                "results_json": json.dumps(_sanitize_json(results_payload), ensure_ascii=False, allow_nan=False, cls=PlotlyJSONEncoder),
                "artifacts_json": json.dumps(_sanitize_json(artifacts), ensure_ascii=False, allow_nan=False, cls=PlotlyJSONEncoder),
            },
        )
        db.commit()
        _set_progress(db, rid, job_id, pct=100, stage="done", message="Succeeded")
        return {"run_id": run_id, "status": "succeeded", "defaults": results.get("defaults")}
    except Exception as exc:
        err = str(exc)[:8000]
        try:
            db.rollback()
        except Exception:
            pass
        db.execute(
            text(
                """
                update defaults_discovery_run
                set status='failed',
                    progress_pct=100,
                    progress_stage='failed',
                    progress_message='failed',
                    error_message=:err,
                    finished_at=:ts,
                    last_heartbeat_at=:ts
                where id=:id
                """
            ),
            {"id": rid, "err": err, "ts": _utcnow()},
        )
        db.commit()
        return {"run_id": run_id, "status": "failed", "error": err}
    finally:
        db.close()
