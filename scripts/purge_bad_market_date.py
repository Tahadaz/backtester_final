from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.api.app.config import settings
from services.api.app.market_data_loader import load_ohlcv_from_store
from services.api.app.storage import put_bytes, s3_client
from services.worker.db import SessionLocal


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_iso_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid --date value {value!r}; expected YYYY-MM-DD") from exc


def _query_targets(
    db: Any,
    *,
    target_date: dt.date,
    timeframe: str,
    source_provider: str,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT symbol, timeframe, object_key, source_provider, data_as_of
            FROM market_data_store
            WHERE timeframe = :timeframe
              AND source_provider = :source_provider
              AND data_as_of = :target_date
            ORDER BY symbol
            """
        ),
        {
            "timeframe": timeframe,
            "source_provider": source_provider,
            "target_date": target_date,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _filter_out_date(frame: pd.DataFrame, target_date: dt.date) -> tuple[pd.DataFrame, int]:
    if frame.empty:
        return frame, 0
    mask = frame.index.map(lambda ts: ts.date() != target_date)
    cleaned = frame.loc[mask].sort_index()
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")]
    removed = int(len(frame) - len(cleaned))
    return cleaned, removed


def _build_backup_key(
    *,
    symbol: str,
    timeframe: str,
    target_date: dt.date,
    timestamp_utc: dt.datetime,
    object_key: str,
) -> str:
    suffix = Path(object_key).name or f"{symbol}_{timeframe}.parquet"
    ts = timestamp_utc.strftime("%Y%m%dT%H%M%SZ")
    return (
        f"market_data/backups/purge_bad_date/{target_date.isoformat()}/"
        f"{symbol}_{timeframe}_{ts}_{suffix}"
    )


def _save_frame_to_store(object_key: str, frame: pd.DataFrame) -> None:
    buf = BytesIO()
    frame.to_parquet(buf, index=True)
    buf.seek(0)
    put_bytes(object_key=object_key, data=buf.getvalue(), content_type="application/octet-stream")


def _update_store_row(
    db: Any,
    *,
    symbol: str,
    timeframe: str,
    frame: pd.DataFrame,
) -> None:
    if frame.empty:
        start_ts = None
        end_ts = None
        data_as_of = None
        row_count = 0
    else:
        start_ts = frame.index.min().to_pydatetime()
        end_ts = frame.index.max().to_pydatetime()
        data_as_of = end_ts.date()
        row_count = int(len(frame))

    db.execute(
        text(
            """
            UPDATE market_data_store
            SET row_count = :row_count,
                start_ts = :start_ts,
                end_ts = :end_ts,
                data_as_of = :data_as_of,
                updated_at = :updated_at
            WHERE symbol = :symbol
              AND timeframe = :timeframe
            """
        ),
        {
            "row_count": row_count,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "data_as_of": data_as_of,
            "updated_at": _utcnow(),
            "symbol": symbol,
            "timeframe": timeframe,
        },
    )


def purge_bad_market_date(
    *,
    target_date: dt.date,
    apply_changes: bool,
    source_provider: str = "bourse_direct",
    timeframe: str = "1D",
) -> dict[str, Any]:
    db = SessionLocal()
    client = s3_client()
    now_utc = _utcnow()
    report: dict[str, Any] = {
        "target_date": target_date.isoformat(),
        "timeframe": timeframe,
        "source_provider": source_provider,
        "apply_changes": bool(apply_changes),
        "generated_at": now_utc.isoformat(),
        "symbols": [],
        "summary": {
            "targets": 0,
            "affected": 0,
            "removed_rows": 0,
            "backups_created": 0,
            "writes": 0,
        },
    }

    try:
        targets = _query_targets(
            db,
            target_date=target_date,
            timeframe=timeframe,
            source_provider=source_provider,
        )
        report["summary"]["targets"] = len(targets)

        for row in targets:
            symbol = str(row["symbol"])
            object_key = str(row["object_key"])

            frame = load_ohlcv_from_store(object_key=object_key)
            cleaned, removed = _filter_out_date(frame, target_date)
            symbol_result: dict[str, Any] = {
                "symbol": symbol,
                "timeframe": timeframe,
                "object_key": object_key,
                "row_count_before": int(len(frame)),
                "row_count_after": int(len(cleaned)),
                "removed_rows": int(removed),
                "status": "unchanged",
            }

            if removed > 0:
                report["summary"]["affected"] += 1
                report["summary"]["removed_rows"] += int(removed)
                symbol_result["status"] = "would_update" if not apply_changes else "updated"

                backup_key = _build_backup_key(
                    symbol=symbol,
                    timeframe=timeframe,
                    target_date=target_date,
                    timestamp_utc=now_utc,
                    object_key=object_key,
                )
                symbol_result["backup_key"] = backup_key

                if apply_changes:
                    client.copy_object(
                        Bucket=settings.S3_BUCKET,
                        CopySource={"Bucket": settings.S3_BUCKET, "Key": object_key},
                        Key=backup_key,
                    )
                    report["summary"]["backups_created"] += 1
                    _save_frame_to_store(object_key=object_key, frame=cleaned)
                    _update_store_row(db, symbol=symbol, timeframe=timeframe, frame=cleaned)
                    report["summary"]["writes"] += 1

            report["symbols"].append(symbol_result)

        if apply_changes:
            db.commit()
        return report
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Purge a known bad market date from market_data_store parquet objects.",
    )
    parser.add_argument(
        "--date",
        default="2026-04-10",
        help="Target ISO date to remove from canonical OHLCV (default: 2026-04-10).",
    )
    parser.add_argument(
        "--source-provider",
        default="bourse_direct",
        help="Filter by source_provider (default: bourse_direct).",
    )
    parser.add_argument(
        "--timeframe",
        default="1D",
        help="Filter by timeframe (default: 1D).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. If omitted, runs as dry-run.",
    )
    args = parser.parse_args(argv)

    target_date = _parse_iso_date(str(args.date))
    report = purge_bad_market_date(
        target_date=target_date,
        apply_changes=bool(args.apply),
        source_provider=str(args.source_provider),
        timeframe=str(args.timeframe),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
