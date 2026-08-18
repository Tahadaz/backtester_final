"""Download the free-data proxies for the W1 security master and cache them.

Free sources only -- yfinance for prices, FRED's no-key CSV endpoint for yields.
Bloomberg is deliberately not used (program decision G9 / the TSMOM
pre-registration §2).

    python tools/global_desk/ingest_free_panel.py [--start 2000-01-01] [--refresh]

Writes one parquet per instrument to data/global_desk/raw/ (gitignored) plus a
manifest recording what was fetched, when, and from where.
"""

from __future__ import annotations

import argparse
import io
import json
import pathlib
import sys
import time
from datetime import date, datetime, timezone

import pandas as pd


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "core"))

from quant_core.cross_asset.security_master import REGISTRY, SecurityMasterEntry  # noqa: E402

CACHE_DIR = REPO_ROOT / "data" / "global_desk" / "raw"
MANIFEST_PATH = REPO_ROOT / "data" / "global_desk" / "manifest.json"

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_yfinance(ticker: str, start: date) -> pd.Series:
    import yfinance as yf

    frame = yf.download(
        ticker,
        start=start.isoformat(),
        auto_adjust=False,
        progress=False,
        group_by="column",
    )
    if frame is None or frame.empty:
        raise RuntimeError("no rows returned")
    if isinstance(frame.columns, pd.MultiIndex):
        close = frame["Close"]
        series = close.iloc[:, 0] if close.shape[1] else pd.Series(dtype=float)
    else:
        series = frame["Close"]
    series = pd.to_numeric(series, errors="coerce").dropna()
    if series.empty:
        raise RuntimeError("all-NaN close column")
    series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
    return series[~series.index.duplicated(keep="last")].sort_index()


def _fetch_fred(series_id: str, start: date) -> pd.Series:
    import requests

    response = requests.get(FRED_CSV.format(series_id=series_id), timeout=60)
    response.raise_for_status()
    frame = pd.read_csv(io.StringIO(response.text))
    date_col, value_col = frame.columns[0], frame.columns[1]
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    # FRED writes "." for missing observations.
    frame[value_col] = pd.to_numeric(frame[value_col], errors="coerce")
    series = frame.dropna(subset=[date_col, value_col]).set_index(date_col)[value_col]
    series = series[series.index >= pd.Timestamp(start)]
    if series.empty:
        raise RuntimeError("no observations after start")
    series.index = series.index.tz_localize(None).normalize()
    # FRED yields are percent; store as decimal.
    return (series / 100.0).sort_index()


def fetch(entry: SecurityMasterEntry, start: date) -> pd.Series:
    if entry.free_proxy is None:
        raise RuntimeError(f"no free proxy: {entry.free_proxy_note}")
    effective = max(start, entry.history_start)
    if entry.free_proxy_source == "yfinance":
        return _fetch_yfinance(entry.free_proxy, effective)
    if entry.free_proxy_source == "fred":
        return _fetch_fred(entry.free_proxy, effective)
    raise RuntimeError(f"unsupported free_proxy_source {entry.free_proxy_source!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2000-01-01")
    parser.add_argument("--refresh", action="store_true", help="re-download even if cached")
    parser.add_argument("--sleep", type=float, default=0.4, help="pause between downloads")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, dict] = {}
    if MANIFEST_PATH.exists() and not args.refresh:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("instruments", {})

    fetched = skipped = failed = 0
    for entry in REGISTRY:
        target = CACHE_DIR / f"{entry.canonical_id}.parquet"
        if entry.free_proxy is None:
            manifest[entry.canonical_id] = {
                "status": "no_free_path",
                "reason": entry.free_proxy_note,
                "source": "none",
            }
            skipped += 1
            continue
        if target.exists() and not args.refresh:
            skipped += 1
            continue
        try:
            series = fetch(entry, start)
            series.rename("value").to_frame().to_parquet(target)
            manifest[entry.canonical_id] = {
                "status": "ok",
                "source": entry.free_proxy_source,
                "ticker": entry.free_proxy,
                "rows": int(series.size),
                "first": series.index.min().date().isoformat(),
                "last": series.index.max().date().isoformat(),
                "fetched_at": _utcnow(),
            }
            fetched += 1
            print(f"  ok   {entry.canonical_id:<14} {series.size:>6} rows  "
                  f"{series.index.min().date()} -> {series.index.max().date()}")
        except Exception as exc:  # noqa: BLE001 - report and continue
            manifest[entry.canonical_id] = {
                "status": "failed",
                "source": entry.free_proxy_source,
                "ticker": entry.free_proxy,
                "error": f"{type(exc).__name__}: {exc}"[:300],
                "attempted_at": _utcnow(),
            }
            failed += 1
            print(f"  FAIL {entry.canonical_id:<14} {type(exc).__name__}: {str(exc)[:120]}")
        time.sleep(args.sleep)

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps({"generated_at": _utcnow(), "start": args.start, "instruments": manifest}, indent=2),
        encoding="utf-8",
    )
    print(f"\nfetched={fetched} skipped={skipped} failed={failed}")
    print(f"manifest -> {MANIFEST_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
