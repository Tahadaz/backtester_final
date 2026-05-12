from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests


DEFAULT_SPOOL_DIR = Path(os.getenv("BT_BLOOMBERG_SPOOL_DIR", "spool"))


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


def _normalize_bdh_output(raw: pd.DataFrame, securities: list[str], fields: list[str]) -> pd.DataFrame:
    if raw.empty:
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
