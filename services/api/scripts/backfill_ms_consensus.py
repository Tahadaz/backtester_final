"""Backfill MarketScreener forward estimates into fundamental_consensus_estimate.

Reads HTML from a cache directory (ms_{id}.html files) and the IAM test fixture.
Upserts Revenue_Forward, NetIncome_Forward, EPS_Forward, PER_Forward,
Target_Price, and Rating estimates.

Units: Revenue and NI are written as absolute MAD (converted at ingest ×1_000_000
inside parse_finances_html).  EPS and ratios are written as MAD/share or dimensionless.

Coverage: currently IAM (id=1408717) from the test fixture; add more HTML files
to the cache directory (ms_{id}.html) to extend coverage.

Usage:
    python services/api/scripts/backfill_ms_consensus.py [--cache-dir PATH]

Ask before running on a shared DB.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

os.environ.setdefault("FUNDAMENTAL_DISABLE_LIVE_QUOTES", "1")

from core.quant_core.fundamentals.consensus.marketscreener import (  # noqa: E402
    KNOWN_IDS,
    MarketScreenerAdapter,
)
from app.db import _ensure_session_factory  # noqa: E402
from app.services.consensus import upsert_consensus_estimates  # noqa: E402

FIXTURE_DIR = REPO_ROOT / "core" / "tests" / "fixtures"

# Map ms_id → fixture filename for files that live outside the standard cache dir.
# These are linked into a temp cache dir at runtime so the adapter can find them.
_FIXTURE_OVERRIDES: dict[int, Path] = {
    1408717: FIXTURE_DIR / "ms_iam_finances.html",  # IAM
}


def _build_cache(cache_dir: Path, tmp_dir: Path) -> Path:
    """Return a directory containing ms_{id}.html files.

    Copies files from cache_dir (if they exist) then adds fixture overrides
    for any ID not already present.
    """
    merged = tmp_dir / "ms_cache"
    merged.mkdir(parents=True, exist_ok=True)

    # Copy existing cache files
    if cache_dir.exists():
        for f in cache_dir.glob("ms_*.html"):
            shutil.copy2(f, merged / f.name)

    # Add fixture overrides for IDs not already in merged cache
    for ms_id, src in _FIXTURE_OVERRIDES.items():
        dest = merged / f"ms_{ms_id}.html"
        if not dest.exists() and src.exists():
            shutil.copy2(src, dest)
            print(f"  Linked fixture: {src.name} -> ms_{ms_id}.html")

    return merged


def main(cache_dir: Path | None = None) -> None:
    cache_dir = cache_dir or REPO_ROOT / "scratch" / "ms_cache"

    print(f"MarketScreener backfill — cache_dir={cache_dir}", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        merged_cache = _build_cache(cache_dir, Path(tmp))
        available = sorted(merged_cache.glob("ms_*.html"))
        print(f"  HTML files available: {[f.name for f in available]}", flush=True)
        if not available:
            print("  No HTML files found; nothing to backfill.")
            return

        adapter = MarketScreenerAdapter(
            cache_dir=merged_cache,
            id_map=KNOWN_IDS,
            rate_limit_sec=0.0,  # cache-only; no live fetches
        )
        estimates = adapter.fetch()
        if not estimates:
            print("  No estimates parsed from available HTML.", flush=True)
            return

        print(f"  Parsed {len(estimates)} estimates:", flush=True)
        by_sym: dict[str, list] = {}
        for e in estimates:
            by_sym.setdefault(e.symbol, []).append(e)
        for sym, rows in sorted(by_sym.items()):
            metrics = sorted({r.metric for r in rows})
            print(f"    {sym}: {len(rows)} rows — {metrics}", flush=True)

        session_factory = _ensure_session_factory()
        with session_factory() as db:
            n = upsert_consensus_estimates(db, estimates)
            db.commit()
        print(f"  Upserted {n} rows into fundamental_consensus_estimate.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Directory with ms_{id}.html files (default: scratch/ms_cache/)",
    )
    args = parser.parse_args()
    main(cache_dir=args.cache_dir)
