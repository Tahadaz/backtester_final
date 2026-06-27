from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests


DEFAULT_SPOOL_DIR = Path(os.getenv("BT_BLOOMBERG_SPOOL_DIR", "spool"))
DEFAULT_OHLCV_FIELDS = ["PX_OPEN", "PX_HIGH", "PX_LOW", "PX_LAST", "VOLUME"]


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _request_id(prefix: str) -> str:
    return f"{prefix}-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def _to_parquet_bytes(frame: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    frame.to_parquet(buffer, index=False)
    return buffer.getvalue()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(
    *,
    bridge_id: str,
    request_id: str,
    bloomberg_source: str,
    kind: str,
    frame: pd.DataFrame,
    securities: list[str],
    fields: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    periodicity: str | None = None,
    overrides: dict[str, Any] | None = None,
    data_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "bridge_id": bridge_id,
        "request_id": request_id,
        "bloomberg_source": bloomberg_source,
        "kind": kind,
        "securities": securities,
        "fields": fields,
        "start_date": start_date,
        "end_date": end_date,
        "periodicity": periodicity,
        "overrides": overrides or {},
        "columns": [str(column) for column in frame.columns],
        "row_count": int(len(frame)),
        "data_sha256": data_sha256,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def _upload(endpoint: str, bridge_key: str, manifest: dict[str, Any], payload: bytes, filename: str) -> dict[str, Any]:
    base = endpoint.rstrip("/")
    url = f"{base}/bridge/bloomberg/batches"
    response = requests.post(
        url,
        headers={"X-Bloomberg-Bridge-Key": bridge_key},
        data={"manifest_json": json.dumps(manifest, default=str)},
        files={"file": (filename, payload, "application/octet-stream")},
        timeout=120,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"{response.status_code} {response.text}")
    return response.json()


def _common_config(args: argparse.Namespace) -> tuple[str, str, str]:
    endpoint = args.endpoint or _env("BT_BLOOMBERG_ENDPOINT")
    bridge_key = args.bridge_key or _env("BT_BLOOMBERG_BRIDGE_KEY")
    bridge_id = args.bridge_id or _env("BT_BLOOMBERG_BRIDGE_ID", "bloomberg-terminal")
    if not endpoint or not bridge_key:
        raise SystemExit("BT_BLOOMBERG_ENDPOINT and BT_BLOOMBERG_BRIDGE_KEY are required")
    return endpoint.rstrip("/"), bridge_key, bridge_id or "bloomberg-terminal"


def _api_request(args: argparse.Namespace, method: str, path: str, **kwargs: Any) -> Any:
    endpoint, bridge_key, bridge_id = _common_config(args)
    url = f"{endpoint}{path}"
    headers = dict(kwargs.pop("headers", {}) or {})
    headers["X-Bloomberg-Bridge-Key"] = bridge_key
    headers["X-Bloomberg-Bridge-Id"] = bridge_id
    response = requests.request(method, url, headers=headers, timeout=kwargs.pop("timeout", 120), **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} failed: {response.status_code} {response.text}")
    if not response.content:
        return None
    return response.json()


def _spool(spool_dir: Path, manifest: dict[str, Any], payload: bytes, filename: str) -> Path:
    batch_dir = spool_dir / str(manifest["request_id"])
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    (batch_dir / filename).write_bytes(payload)
    return batch_dir


def _emit_or_upload(args: argparse.Namespace, frame: pd.DataFrame, *, source: str, kind: str, fields: list[str]) -> int:
    endpoint = args.endpoint or _env("BT_BLOOMBERG_ENDPOINT")
    bridge_key = args.bridge_key or _env("BT_BLOOMBERG_BRIDGE_KEY")
    bridge_id = args.bridge_id or _env("BT_BLOOMBERG_BRIDGE_ID", "bloomberg-terminal")
    request_id = args.request_id or _request_id(source)

    payload = _to_parquet_bytes(frame)
    filename = f"{request_id}.parquet"
    manifest = _manifest(
        bridge_id=bridge_id or "bloomberg-terminal",
        request_id=request_id,
        bloomberg_source=source,
        kind=kind,
        frame=frame,
        securities=getattr(args, "security", None) or [],
        fields=fields,
        start_date=getattr(args, "start", None),
        end_date=getattr(args, "end", None),
        periodicity=getattr(args, "periodicity", None),
        overrides={},
        data_sha256=_sha256(payload),
    )

    if args.upload:
        if not endpoint or not bridge_key:
            raise SystemExit("BT_BLOOMBERG_ENDPOINT and BT_BLOOMBERG_BRIDGE_KEY are required for --upload")
        try:
            result = _upload(endpoint, bridge_key, manifest, payload, filename)
            print(json.dumps(result, indent=2, default=str))
            return 0
        except Exception as exc:
            batch_dir = _spool(Path(args.spool_dir), manifest, payload, filename)
            print(f"upload failed; spooled to {batch_dir}: {exc}", file=sys.stderr)
            return 2

    batch_dir = _spool(Path(args.spool_dir), manifest, payload, filename)
    print(f"spooled to {batch_dir}")
    return 0


def _upload_frame_for_job(
    args: argparse.Namespace,
    frame: pd.DataFrame,
    *,
    source: str,
    kind: str,
    securities: list[str],
    fields: list[str],
    start_date: str | None,
    end_date: str | None,
    periodicity: str | None,
    request_prefix: str,
) -> dict[str, Any]:
    endpoint, bridge_key, bridge_id = _common_config(args)
    request_id = _request_id(request_prefix)
    payload = _to_parquet_bytes(frame)
    filename = f"{request_id}.parquet"
    manifest = _manifest(
        bridge_id=bridge_id,
        request_id=request_id,
        bloomberg_source=source,
        kind=kind,
        frame=frame,
        securities=securities,
        fields=fields,
        start_date=start_date,
        end_date=end_date,
        periodicity=periodicity,
        overrides={},
        data_sha256=_sha256(payload),
    )
    try:
        return _upload(endpoint, bridge_key, manifest, payload, filename)
    except Exception:
        _spool(Path(args.spool_dir), manifest, payload, filename)
        raise


def _mock_frame(securities: list[str], fields: list[str], start: str, end: str) -> pd.DataFrame:
    dates = pd.date_range(start=start, end=end, freq="B")
    rows: list[dict[str, Any]] = []
    for security in securities:
        base = (int(hashlib.sha1(security.encode("utf-8")).hexdigest()[:6], 16) % 500) + 50
        for field in fields:
            field_offset = int(hashlib.sha1(field.encode("utf-8")).hexdigest()[:4], 16) % 20
            for idx, day in enumerate(dates):
                rows.append(
                    {
                        "date": day.date().isoformat(),
                        "security": security,
                        "field": field,
                        "value": float(base + field_offset + idx),
                    }
                )
    return pd.DataFrame(rows)


def _normalize_bdh_output(raw: pd.DataFrame | None, securities: list[str], fields: list[str]) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "security", "field", "value"])

    frame = raw.copy()
    frame.index.name = "date"

    if isinstance(frame.columns, pd.MultiIndex):
        long = frame.stack(list(range(frame.columns.nlevels))).reset_index()
        long.columns = ["date", *[f"level_{i}" for i in range(frame.columns.nlevels)], "value"]
        rows: list[dict[str, Any]] = []
        for _, row in long.iterrows():
            labels = [str(row[f"level_{i}"]) for i in range(frame.columns.nlevels)]
            security = next((label for label in labels if label in securities), labels[0])
            field = next((label for label in labels if label in fields), labels[-1])
            rows.append({"date": row["date"], "security": security, "field": field, "value": row["value"]})
        return pd.DataFrame(rows)

    out = frame.reset_index()
    if len(securities) == 1:
        out["security"] = securities[0]
    return out.melt(id_vars=["date", "security"], var_name="field", value_name="value")


def cmd_mock(args: argparse.Namespace) -> int:
    frame = _mock_frame(args.security, args.field, args.start, args.end)
    return _emit_or_upload(args, frame, source="bdh", kind="time_series", fields=args.field)


def cmd_bdh(args: argparse.Namespace) -> int:
    try:
        from xbbg import blp  # type: ignore
    except Exception as exc:
        raise SystemExit(f"xbbg is not available: {exc}") from exc

    raw = blp.bdh(
        tickers=args.security,
        flds=args.field,
        start_date=args.start.replace("-", ""),
        end_date=args.end.replace("-", ""),
    )
    frame = _normalize_bdh_output(raw, args.security, args.field)
    return _emit_or_upload(args, frame, source="bdh", kind="time_series", fields=args.field)


def cmd_bdp(args: argparse.Namespace) -> int:
    try:
        from xbbg import blp  # type: ignore
    except Exception as exc:
        raise SystemExit(f"xbbg is not available: {exc}") from exc
    frame = blp.bdp(tickers=args.security, flds=args.field).reset_index()
    return _emit_or_upload(args, frame, source="bdp", kind="reference", fields=args.field)


def cmd_bds(args: argparse.Namespace) -> int:
    try:
        from xbbg import blp  # type: ignore
    except Exception as exc:
        raise SystemExit(f"xbbg is not available: {exc}") from exc
    frames = []
    for security in args.security:
        for field in args.field:
            data = blp.bds(ticker=security, flds=field)
            data["security"] = security
            data["field"] = field
            frames.append(data)
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return _emit_or_upload(args, frame, source="bds", kind="bulk_table", fields=args.field)


def cmd_bql(args: argparse.Namespace) -> int:
    try:
        import bql  # type: ignore
    except Exception as exc:
        raise SystemExit(f"Bloomberg bql package is not available: {exc}") from exc

    service = bql.Service()
    response = service.execute(args.query)
    frames = [item.df().reset_index() for item in response]
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return _emit_or_upload(args, frame, source="bql", kind="bql_table", fields=[])


def _capabilities() -> dict[str, Any]:
    caps: dict[str, Any] = {
        "python": sys.version.split()[0],
        "pandas": pd.__version__,
        "requests": requests.__version__,
        "parquet": True,
        "xbbg": False,
        "bdh": False,
        "bdp": False,
        "bds": False,
        "bdib": False,
        "bql": False,
    }
    try:
        _to_parquet_bytes(pd.DataFrame([{"ok": 1}]))
    except Exception as exc:
        caps["parquet"] = False
        caps["parquet_error"] = str(exc)
    try:
        from xbbg import blp  # type: ignore

        caps["xbbg"] = True
        caps["bdh"] = hasattr(blp, "bdh")
        caps["bdp"] = hasattr(blp, "bdp")
        caps["bds"] = hasattr(blp, "bds")
        caps["bdib"] = hasattr(blp, "bdib")
    except Exception as exc:
        caps["xbbg_error"] = str(exc)
    try:
        import bql  # type: ignore  # noqa: F401

        caps["bql"] = True
    except Exception as exc:
        caps["bql_error"] = str(exc)
    return caps


def _post_job_status(
    args: argparse.Namespace,
    job_id: str,
    *,
    status: str | None = None,
    progress: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    message: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    body = {
        "status": status,
        "progress": progress or {},
        "result": result or {},
        "message": message,
        "error_message": error_message,
    }
    return _api_request(args, "POST", f"/bridge/bloomberg/jobs/{job_id}/status", json=body)


def _send_heartbeat(
    args: argparse.Namespace,
    *,
    status: str = "online",
    active_job_id: str | None = None,
    preflight: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    _endpoint, _bridge_key, bridge_id = _common_config(args)
    body = {
        "bridge_id": bridge_id,
        "status": status,
        "capabilities": _capabilities(),
        "preflight": preflight or {},
        "active_job_id": active_job_id,
        "error_message": error_message,
    }
    return _api_request(args, "POST", "/bridge/bloomberg/heartbeat", json=body)


def _spec_items(spec: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = spec.get("security_candidates")
    if isinstance(candidates, list) and candidates:
        items = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").strip().upper()
            raw_candidates = item.get("candidates") if isinstance(item.get("candidates"), list) else []
            cleaned = [str(value).strip() for value in raw_candidates if str(value).strip()]
            if symbol and cleaned:
                items.append({"symbol": symbol, "candidates": cleaned})
        if items:
            return items

    securities = [str(value).strip() for value in spec.get("securities", []) if str(value).strip()]
    symbols = [str(value).strip().upper() for value in spec.get("symbols", []) if str(value).strip()]
    items = []
    for idx, security in enumerate(securities):
        symbol = symbols[idx] if idx < len(symbols) else security
        items.append({"symbol": symbol, "candidates": [security]})
    return items


def _fields_from_spec(spec: dict[str, Any]) -> list[str]:
    fields = [str(value).strip().upper() for value in spec.get("fields", []) if str(value).strip()]
    return fields or DEFAULT_OHLCV_FIELDS.copy()


def _parse_date(value: str | None, default: dt.date) -> dt.date:
    if not value:
        return default
    return dt.date.fromisoformat(str(value)[:10])


def _date_chunks(start: dt.date, end: dt.date, chunk_days: int) -> list[tuple[dt.date, dt.date]]:
    chunks: list[tuple[dt.date, dt.date]] = []
    current = start
    step = max(1, int(chunk_days))
    while current <= end:
        chunk_end = min(end, current + dt.timedelta(days=step - 1))
        chunks.append((current, chunk_end))
        current = chunk_end + dt.timedelta(days=1)
    return chunks


def _fetch_bdh_frame(security: str, fields: list[str], start: dt.date, end: dt.date) -> pd.DataFrame:
    from xbbg import blp  # type: ignore

    raw = blp.bdh(
        tickers=[security],
        flds=fields,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    frame = _normalize_bdh_output(raw, [security], fields)
    if not frame.empty or len(fields) <= 1:
        return frame

    frames: list[pd.DataFrame] = []
    for field in fields:
        raw_field = blp.bdh(
            tickers=[security],
            flds=[field],
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        field_frame = _normalize_bdh_output(raw_field, [security], [field])
        if not field_frame.empty:
            frames.append(field_frame)
    return pd.concat(frames, ignore_index=True) if frames else frame


_BDIB_FIELD_MAP = {
    "open": "PX_OPEN",
    "high": "PX_HIGH",
    "low": "PX_LOW",
    "close": "PX_LAST",
    "last": "PX_LAST",
    "volume": "VOLUME",
    "num_trds": "NUM_TRADES",
}


def _normalize_bdib_output(raw: pd.DataFrame, security: str, requested_fields: list[str]) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["datetime", "security", "field", "value"])
    frame = raw.copy().reset_index()
    lower_cols = {str(column).strip().lower(): str(column) for column in frame.columns}
    time_col = None
    for candidate in ("datetime", "time", "timestamp", "index"):
        if candidate in lower_cols:
            time_col = lower_cols[candidate]
            break
    if time_col is None:
        time_col = str(frame.columns[0])

    requested = {field.upper() for field in requested_fields}
    rows: list[dict[str, Any]] = []
    for lower_name, bloomberg_field in _BDIB_FIELD_MAP.items():
        if requested and bloomberg_field not in requested:
            continue
        column = lower_cols.get(lower_name)
        if column is None:
            continue
        for _, row in frame[[time_col, column]].dropna(subset=[time_col]).iterrows():
            value = row[column]
            if pd.isna(value):
                continue
            rows.append(
                {
                    "datetime": row[time_col],
                    "security": security,
                    "field": bloomberg_field,
                    "value": value,
                }
            )
    return pd.DataFrame(rows)


def _fetch_bdib_frame(security: str, fields: list[str], day: dt.date, interval_minutes: int) -> pd.DataFrame:
    from xbbg import blp  # type: ignore

    try:
        raw = blp.bdib(ticker=security, dt=day.isoformat(), interval=interval_minutes)
    except TypeError:
        raw = blp.bdib(security, day.isoformat(), interval=interval_minutes)
    return _normalize_bdib_output(raw, security, fields)


def _probe_security(spec: dict[str, Any], security: str) -> dict[str, Any]:
    fields = _fields_from_spec(spec)
    frequency = str(spec.get("frequency") or "daily").lower()
    today = dt.datetime.now().date()
    probe_days = int((spec.get("options") or {}).get("probe_days") or 5)
    start = today - dt.timedelta(days=max(2, probe_days * 2))
    end = today
    try:
        if frequency == "daily":
            frame = _fetch_bdh_frame(security, fields[: min(len(fields), 4)], start, end)
        else:
            interval = 60 if frequency == "hourly" else 1
            frame = pd.DataFrame()
            for day in pd.date_range(start=start, end=end, freq="B")[-probe_days:]:
                frame = _fetch_bdib_frame(security, fields, day.date(), interval)
                if not frame.empty:
                    break
        return {
            "security": security,
            "available": not frame.empty,
            "rows": int(len(frame)),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "error": None,
        }
    except Exception as exc:
        return {
            "security": security,
            "available": False,
            "rows": 0,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "error": str(exc),
        }


def _run_preflight(args: argparse.Namespace, spec: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"endpoint": {}, "capabilities": _capabilities(), "probe": None}
    try:
        result["endpoint"] = _api_request(args, "GET", "/bridge/bloomberg/health")
    except Exception as exc:
        result["endpoint"] = {"ok": False, "error": str(exc)}

    items = _spec_items(spec)
    probe_security = None
    if items:
        probe_security = items[0]["candidates"][0]
    elif spec.get("securities"):
        probe_security = str(spec["securities"][0])
    else:
        probe_security = "ATW MA Equity"
    if result["capabilities"].get("xbbg"):
        result["probe"] = _probe_security({**spec, "frequency": "daily", "fields": ["PX_LAST"]}, probe_security)
    else:
        result["probe"] = {"security": probe_security, "available": False, "error": "xbbg is not available"}

    result["ok"] = bool(result["endpoint"].get("ok")) and bool(result["capabilities"].get("parquet"))
    return result


def _run_discovery(args: argparse.Namespace, job_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    items = _spec_items(spec)
    results: list[dict[str, Any]] = []
    available = 0
    for index, item in enumerate(items, start=1):
        symbol = item["symbol"]
        chosen: dict[str, Any] | None = None
        probes = []
        for candidate in item["candidates"]:
            probe = _probe_security(spec, candidate)
            probes.append(probe)
            if probe["available"]:
                chosen = probe
                break
        if chosen:
            available += 1
        row = {
            "symbol": symbol,
            "available": chosen is not None,
            "selected_security": chosen["security"] if chosen else None,
            "probes": probes,
        }
        results.append(row)
        _post_job_status(
            args,
            job_id,
            status="running",
            progress={
                "stage": "discovery",
                "symbols_done": index,
                "symbols_total": len(items),
                "latest_symbol": symbol,
            },
            message=f"Discovery checked {symbol}",
        )
    return {
        "frequency": spec.get("frequency"),
        "fields": _fields_from_spec(spec),
        "symbols_total": len(items),
        "available_count": available,
        "unavailable_count": max(0, len(items) - available),
        "items": results,
    }


def _run_backfill(args: argparse.Namespace, job_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    items = _spec_items(spec)
    fields = _fields_from_spec(spec)
    frequency = str(spec.get("frequency") or "daily").lower()
    options = spec.get("options") or {}
    today = dt.datetime.now().date()
    start = _parse_date(spec.get("start_date"), dt.date(2010, 1, 1))
    end = _parse_date(spec.get("end_date"), today)
    uploaded_batches = 0
    uploaded_rows = 0
    failures: list[dict[str, Any]] = []
    uploaded: list[dict[str, Any]] = []

    for item_index, item in enumerate(items, start=1):
        symbol = item["symbol"]
        selected_security = None
        for candidate in item["candidates"]:
            probe = _probe_security({**spec, "frequency": frequency}, candidate)
            if probe["available"]:
                selected_security = candidate
                break

        if not selected_security:
            failures.append({"symbol": symbol, "error": "No available Bloomberg security candidate"})
            continue

        try:
            if frequency == "daily":
                chunk_days = int(options.get("daily_chunk_days") or 365)
                chunks = _date_chunks(start, end, chunk_days)
                for chunk_index, (chunk_start, chunk_end) in enumerate(chunks, start=1):
                    frame = _fetch_bdh_frame(selected_security, fields, chunk_start, chunk_end)
                    if frame.empty:
                        continue
                    upload = _upload_frame_for_job(
                        args,
                        frame,
                        source="bdh",
                        kind="time_series",
                        securities=[selected_security],
                        fields=fields,
                        start_date=chunk_start.isoformat(),
                        end_date=chunk_end.isoformat(),
                        periodicity="DAILY",
                        request_prefix="bdh-job",
                    )
                    uploaded_batches += 1
                    uploaded_rows += int(len(frame))
                    uploaded.append({"symbol": symbol, "security": selected_security, "batch": upload.get("batch", {})})
                    _post_job_status(
                        args,
                        job_id,
                        status="running",
                        progress={
                            "stage": "backfill",
                            "symbols_done": item_index - 1,
                            "symbols_total": len(items),
                            "latest_symbol": symbol,
                            "chunk": chunk_index,
                            "chunks": len(chunks),
                            "uploaded_batches": uploaded_batches,
                        },
                        message=f"Uploaded {symbol} {chunk_start} to {chunk_end}",
                    )
            else:
                interval = 60 if frequency == "hourly" else 1
                chunk_days = int(options.get("hourly_chunk_days" if frequency == "hourly" else "minute_chunk_days") or 1)
                days = [day.date() for day in pd.date_range(start=start, end=end, freq="B")]
                for day_index, day in enumerate(days, start=1):
                    frame = _fetch_bdib_frame(selected_security, fields, day, interval)
                    if frame.empty:
                        continue
                    upload = _upload_frame_for_job(
                        args,
                        frame,
                        source="bdib",
                        kind="time_series",
                        securities=[selected_security],
                        fields=fields,
                        start_date=day.isoformat(),
                        end_date=day.isoformat(),
                        periodicity=f"INTRADAY_{interval}",
                        request_prefix="bdib-job",
                    )
                    uploaded_batches += 1
                    uploaded_rows += int(len(frame))
                    uploaded.append({"symbol": symbol, "security": selected_security, "batch": upload.get("batch", {})})
                    if day_index % max(1, chunk_days) == 0:
                        _post_job_status(
                            args,
                            job_id,
                            status="running",
                            progress={
                                "stage": "backfill",
                                "symbols_done": item_index - 1,
                                "symbols_total": len(items),
                                "latest_symbol": symbol,
                                "day": day.isoformat(),
                                "days": len(days),
                                "uploaded_batches": uploaded_batches,
                            },
                            message=f"Uploaded {symbol} intraday through {day}",
                        )
        except Exception as exc:
            failures.append({"symbol": symbol, "security": selected_security, "error": str(exc)})

    return {
        "frequency": frequency,
        "fields": fields,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "uploaded_batches": uploaded_batches,
        "uploaded_rows": uploaded_rows,
        "uploaded": uploaded[-25:],
        "failures": failures,
    }


def _execute_job(args: argparse.Namespace, job: dict[str, Any]) -> None:
    job_id = str(job["id"])
    spec = job.get("spec_json") or {}
    job_type = str(job.get("job_type") or spec.get("job_type") or "")
    _post_job_status(args, job_id, status="running", progress={"stage": "starting"}, message="Bridge started job")
    _send_heartbeat(args, status="busy", active_job_id=job_id)
    try:
        if job_type == "preflight":
            result = _run_preflight(args, spec)
        elif job_type == "discovery":
            result = _run_discovery(args, job_id, spec)
            if str(spec.get("mode") or "") == "discover_then_backfill":
                result = {**result, "backfill": _run_backfill(args, job_id, spec)}
        elif job_type in {"backfill", "refresh"}:
            result = _run_backfill(args, job_id, spec)
        else:
            raise RuntimeError(f"Unsupported Bloomberg job_type: {job_type}")
        _post_job_status(
            args,
            job_id,
            status="succeeded",
            progress={"stage": "completed"},
            result=result,
            message="Bridge completed job",
        )
        _send_heartbeat(args, status="online", active_job_id=None, preflight=result if job_type == "preflight" else None)
    except Exception as exc:
        _post_job_status(
            args,
            job_id,
            status="failed",
            progress={"stage": "failed"},
            error_message=str(exc),
            message="Bridge job failed",
        )
        _send_heartbeat(args, status="online", active_job_id=None, error_message=str(exc))


def cmd_listen(args: argparse.Namespace) -> int:
    _common_config(args)
    _send_heartbeat(args, status="online")
    while True:
        _endpoint, _bridge_key, bridge_id = _common_config(args)
        claim = _api_request(
            args,
            "GET",
            "/bridge/bloomberg/jobs/next",
            params={"bridge_id": bridge_id, "lease_seconds": args.lease_seconds},
        )
        job = (claim or {}).get("job")
        if job:
            _execute_job(args, job)
        else:
            _send_heartbeat(args, status="online")
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


def cmd_flush_spool(args: argparse.Namespace) -> int:
    endpoint = args.endpoint or _env("BT_BLOOMBERG_ENDPOINT")
    bridge_key = args.bridge_key or _env("BT_BLOOMBERG_BRIDGE_KEY")
    if not endpoint or not bridge_key:
        raise SystemExit("BT_BLOOMBERG_ENDPOINT and BT_BLOOMBERG_BRIDGE_KEY are required")

    spool_dir = Path(args.spool_dir)
    if not spool_dir.exists():
        print("spool is empty")
        return 0

    failures = 0
    for batch_dir in sorted(path for path in spool_dir.iterdir() if path.is_dir()):
        manifest_path = batch_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload_files = [path for path in batch_dir.iterdir() if path.name != "manifest.json"]
        if not payload_files:
            continue
        payload_file = payload_files[0]
        try:
            result = _upload(endpoint, bridge_key, manifest, payload_file.read_bytes(), payload_file.name)
            print(json.dumps(result, indent=2, default=str))
            for path in batch_dir.iterdir():
                path.unlink()
            batch_dir.rmdir()
        except Exception as exc:
            failures += 1
            print(f"failed to flush {batch_dir}: {exc}", file=sys.stderr)
    return 1 if failures else 0


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--endpoint", default=_env("BT_BLOOMBERG_ENDPOINT"))
    parser.add_argument("--bridge-key", default=_env("BT_BLOOMBERG_BRIDGE_KEY"))
    parser.add_argument("--bridge-id", default=_env("BT_BLOOMBERG_BRIDGE_ID", "bloomberg-terminal"))
    parser.add_argument("--request-id")
    parser.add_argument("--spool-dir", default=str(DEFAULT_SPOOL_DIR))
    parser.add_argument("--upload", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bloomberg Terminal to deployed app bridge")
    sub = parser.add_subparsers(dest="command", required=True)

    mock = sub.add_parser("mock")
    _add_common(mock)
    mock.add_argument("--security", action="append", required=True)
    mock.add_argument("--field", action="append", required=True)
    mock.add_argument("--start", required=True)
    mock.add_argument("--end", required=True)
    mock.set_defaults(func=cmd_mock)

    bdh = sub.add_parser("bdh")
    _add_common(bdh)
    bdh.add_argument("--security", action="append", required=True)
    bdh.add_argument("--field", action="append", required=True)
    bdh.add_argument("--start", required=True)
    bdh.add_argument("--end", required=True)
    bdh.add_argument("--periodicity", default="DAILY")
    bdh.set_defaults(func=cmd_bdh)

    bdp = sub.add_parser("bdp")
    _add_common(bdp)
    bdp.add_argument("--security", action="append", required=True)
    bdp.add_argument("--field", action="append", required=True)
    bdp.set_defaults(func=cmd_bdp)

    bds = sub.add_parser("bds")
    _add_common(bds)
    bds.add_argument("--security", action="append", required=True)
    bds.add_argument("--field", action="append", required=True)
    bds.set_defaults(func=cmd_bds)

    bql = sub.add_parser("bql")
    _add_common(bql)
    bql.add_argument("--query", required=True)
    bql.set_defaults(func=cmd_bql)

    listen = sub.add_parser("listen")
    _add_common(listen)
    listen.add_argument("--poll-seconds", type=float, default=10.0)
    listen.add_argument("--lease-seconds", type=int, default=300)
    listen.add_argument("--once", action="store_true")
    listen.set_defaults(func=cmd_listen)

    flush = sub.add_parser("flush-spool")
    flush.add_argument("--endpoint", default=_env("BT_BLOOMBERG_ENDPOINT"))
    flush.add_argument("--bridge-key", default=_env("BT_BLOOMBERG_BRIDGE_KEY"))
    flush.add_argument("--spool-dir", default=str(DEFAULT_SPOOL_DIR))
    flush.set_defaults(func=cmd_flush_spool)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
