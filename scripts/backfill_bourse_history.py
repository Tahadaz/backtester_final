"""Audit / repair gaps in stored Casablanca stock + index daily bars (boursenova API).

Dry-run is the default; nothing is written without --apply.

  python scripts/backfill_bourse_history.py                       # gap report, all
  python scripts/backfill_bourse_history.py --symbols IAM,ATW     # subset
  python scripts/backfill_bourse_history.py --indices-only
  python scripts/backfill_bourse_history.py --apply [--enqueue-downstream]

Same env/bootstrap as the other host-side scripts (local dev stack defaults below).
The report is also written to output/bourse-backfill/<timestamp>.json.
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://app:app@127.0.0.1:5555/quant")
os.environ.setdefault("S3_ENDPOINT_URL", "http://127.0.0.1:9000")
os.environ.setdefault("AWS_ACCESS_KEY_ID", os.environ.get("S3_ACCESS_KEY", "minio"))
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", os.environ.get("S3_SECRET_KEY", "minio12345"))
os.environ.setdefault("S3_BUCKET", "quant-artifacts")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

from services.worker.tasks.backfill_bourse_history import render_table, run_backfill  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report only (default)")
    mode.add_argument("--apply", action="store_true", help="write missing/changed bars")
    ap.add_argument("--symbols", help="comma-separated symbols (stocks and/or index symbols)")
    scope = ap.add_mutually_exclusive_group()
    scope.add_argument("--indices-only", action="store_true")
    scope.add_argument("--stocks-only", action="store_true")
    ap.add_argument("--enqueue-downstream", action="store_true", help="after --apply: enqueue signal + weekly chains")
    args = ap.parse_args()
    if args.enqueue_downstream and not args.apply:
        ap.error("--enqueue-downstream requires --apply")

    report = run_backfill(
        apply=args.apply,
        symbols=args.symbols.split(",") if args.symbols else None,
        stocks=not args.indices_only,
        indices=not args.stocks_only,
        downstream=args.enqueue_downstream,
    )
    print(render_table(report))
    out_dir = ROOT / "output" / "bourse-backfill"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{datetime.datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"report: {out}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
