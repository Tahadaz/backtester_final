"""Fetch the FRED rate series the carry sleeve needs.

    python tools/global_desk/ingest_rates.py

3-month interbank rates per G10 currency (FX carry) and the US Treasury curve
(rates curve carry). Writes to data/global_desk/rates/ (gitignored).

Uses IR3TIB01* rather than the IRSTCI01* policy rates wired into
services/api/app/services/cross_asset/datasources.py:23 -- several of those are
dead or years stale, documented in docs/global-desk/03-carry-preregistration.md §2.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import requests


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "data" / "global_desk" / "rates"
MANIFEST = REPO_ROOT / "data" / "global_desk" / "rates_manifest.json"

# 3-month interbank offered rate, monthly, per currency.
INTERBANK_3M: dict[str, str] = {
    "USD": "IR3TIB01USM156N",
    "EUR": "IR3TIB01EZM156N",
    "JPY": "IR3TIB01JPM156N",
    "GBP": "IR3TIB01GBM156N",
    "CHF": "IR3TIB01CHM156N",
    "AUD": "IR3TIB01AUM156N",
    "CAD": "IR3TIB01CAM156N",
    "NZD": "IR3TIB01NZM156N",
    "NOK": "IR3TIB01NOM156N",
    "SEK": "IR3TIB01SEM156N",
}

# US Treasury constant-maturity curve, daily.
US_CURVE: list[str] = ["DGS3MO", "DGS1", "DGS2", "DGS5", "DGS10", "DGS30"]

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


def fetch(series_id: str) -> pd.Series:
    response = requests.get(FRED_CSV.format(series_id=series_id), timeout=60)
    response.raise_for_status()
    frame = pd.read_csv(io.StringIO(response.text))
    date_col, value_col = frame.columns[0], frame.columns[1]
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame[value_col] = pd.to_numeric(frame[value_col], errors="coerce")
    series = frame.dropna(subset=[date_col, value_col]).set_index(date_col)[value_col]
    if series.empty:
        raise RuntimeError("no observations")
    series.index = series.index.tz_localize(None).normalize()
    return (series / 100.0).sort_index()  # percent -> decimal


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}
    failures = 0

    targets = [(f"IB3M_{ccy}", sid) for ccy, sid in INTERBANK_3M.items()]
    targets += [(sid, sid) for sid in US_CURVE]

    for name, series_id in targets:
        try:
            series = fetch(series_id)
            series.rename("value").to_frame().to_parquet(OUT_DIR / f"{name}.parquet")
            manifest[name] = {
                "series_id": series_id,
                "rows": int(series.size),
                "first": series.index.min().date().isoformat(),
                "last": series.index.max().date().isoformat(),
                "status": "ok",
            }
            print(f"  ok   {name:<12} {series_id:<18} {series.size:>6} rows  "
                  f"{series.index.min().date()} -> {series.index.max().date()}")
        except Exception as exc:  # noqa: BLE001
            manifest[name] = {"series_id": series_id, "status": "failed", "error": str(exc)[:200]}
            failures += 1
            print(f"  FAIL {name:<12} {series_id:<18} {type(exc).__name__}")
        time.sleep(0.3)

    MANIFEST.write_text(
        json.dumps(
            {"generated_at": datetime.now(timezone.utc).isoformat(), "series": manifest}, indent=2
        ),
        encoding="utf-8",
    )
    print(f"\nfailures={failures}  manifest -> {MANIFEST.relative_to(REPO_ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
