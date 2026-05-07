# 01 — Export Script

## Overview

Create `frontend/scripts/export-scores.py` — a Python script that runs locally with the project's venv and database. It calls the signal engine for every MASI stock and writes static JSON files that the dashboard page reads.

Also create `frontend/public/data/.gitkeep` so the output directory exists.

---

## File: `frontend/scripts/export-scores.py` (CREATE)

### Complete implementation

```python
"""Export signal engine scores to static JSON for the dashboard.

Usage:
    cd <repo-root>
    .venv/Scripts/python frontend/scripts/export-scores.py

Produces:
    frontend/public/data/scores-short.json
    frontend/public/data/scores-medium.json
    frontend/public/data/scores-long.json
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Path setup — allow imports from repo root
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from services.api.app.db import _ensure_session_factory          # noqa: E402
from services.api.app.market_data_loader import load_ohlcv_for_symbol  # noqa: E402
from services.api.app.masi_tickers import get_masi_info, is_masi_ticker  # noqa: E402

from core.quant_core.signal_engine.ensemble import (              # noqa: E402
    run_family_ensemble_full,
    _score_to_label,
)
from core.quant_core.signal_engine.domain import (                # noqa: E402
    HORIZON_PARAMS,
    FAMILY_SIGNAL_TYPE,
    CATEGORY_FAMILIES,
    signal_type_label,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = REPO_ROOT / "frontend" / "public" / "data"
FAMILIES = ("sma", "macd", "rsi", "obv")
HORIZONS = {
    "short": "Court terme",
    "medium": "Moyen terme",
    "long": "Long terme",
}
COST_BPS = 10.0
COOLDOWN_BARS = 0
TIMEFRAME = "1D"


# ---------------------------------------------------------------------------
# Signal computation helpers (replicated from strategy_signals.py:73-114)
# ---------------------------------------------------------------------------

def _truncate_for_horizon(ohlcv, horizon: str):
    """Keep only the last N years of data for the given horizon."""
    max_bars = HORIZON_PARAMS[horizon]["max_years"] * 252
    if len(ohlcv) > max_bars:
        return ohlcv.iloc[-max_bars:]
    return ohlcv


def _clean_ohlcv(ohlcv):
    """Drop rows with NaN in any OHLCV column."""
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in ohlcv.columns]
    if cols:
        ohlcv = ohlcv.dropna(subset=cols)
    return ohlcv


def _has_valid_volume(ohlcv) -> bool:
    """Check if volume data is meaningful (>1% non-zero)."""
    if "Volume" not in ohlcv.columns:
        return False
    volume = ohlcv["Volume"].values.astype("float64")
    finite = volume[np.isfinite(volume)]
    if len(finite) == 0:
        return False
    return (finite != 0).mean() >= 0.01


# ---------------------------------------------------------------------------
# Core: compute scores for one symbol at one horizon
# ---------------------------------------------------------------------------

def compute_symbol_scores(db, symbol: str, horizon: str) -> dict | None:
    """Compute all family scores for one symbol at one horizon.

    Returns a dict with per_family, categories, aggregate, or None if all
    families fail.
    """
    try:
        ohlcv = load_ohlcv_for_symbol(db, symbol, TIMEFRAME)
    except (ValueError, Exception) as exc:
        logger.debug("  %s: no OHLCV data (%s)", symbol, exc)
        return None

    ohlcv = _truncate_for_horizon(ohlcv, horizon)
    ohlcv = _clean_ohlcv(ohlcv)

    if len(ohlcv) < 50:
        logger.debug("  %s: insufficient data (%d bars)", symbol, len(ohlcv))
        return None

    close = ohlcv["Close"].values.astype("float64")
    volume = ohlcv["Volume"].values.astype("float64") if "Volume" in ohlcv.columns else None

    family_scores: dict[str, float] = {}
    family_labels: dict[str, str] = {}

    for family in FAMILIES:
        try:
            # Skip OBV if volume data is bad
            if family == "obv" and not _has_valid_volume(ohlcv):
                continue

            detail = run_family_ensemble_full(
                family, close, volume=volume, symbol=symbol, horizon=horizon,
                timeframe=TIMEFRAME, cost_bps=COST_BPS, cooldown_bars=COOLDOWN_BARS,
            )
            family_scores[family] = detail.signal.family_score_pct
            family_labels[family] = detail.signal.family_signal_label
        except Exception as exc:
            logger.debug("  %s/%s: failed (%s)", symbol, family, exc)
            continue

    if not family_scores:
        return None

    # Build per_family output
    per_family = {}
    for f in FAMILIES:
        if f in family_scores:
            per_family[f] = {
                "score_pct": round(family_scores[f], 2),
                "label": family_labels[f],
            }

    # Category grouping (same logic as batch_scores at strategy_signals.py:746-756)
    categories = {}
    for cat_name, cat_fams in CATEGORY_FAMILIES.items():
        cat_scores = [family_scores[f] for f in cat_fams if f in family_scores]
        if cat_scores:
            cat_avg = sum(cat_scores) / len(cat_scores)
            st = FAMILY_SIGNAL_TYPE.get(cat_fams[0], "trend")
            categories[cat_name] = {
                "score_pct": round(cat_avg, 2),
                "label": signal_type_label(st, cat_avg),
                "families": cat_fams,
            }

    # Aggregate (equal-weight across all available families)
    all_scores = list(family_scores.values())
    agg = sum(all_scores) / len(all_scores)

    return {
        "per_family": per_family,
        "categories": categories,
        "aggregate_score_pct": round(agg, 2),
        "aggregate_signal_label": _score_to_label(agg),
    }


# ---------------------------------------------------------------------------
# Sector and index aggregation
# ---------------------------------------------------------------------------

def aggregate_sectors(stocks: list[dict]) -> list[dict]:
    """Group stocks by sector and compute average scores."""
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for s in stocks:
        sector = s.get("sector") or "Autre"
        by_sector[sector].append(s)

    sectors = []
    for sector_name, sector_stocks in sorted(by_sector.items()):
        # Average per_family scores
        family_sums: dict[str, list[float]] = defaultdict(list)
        agg_scores = []
        for st in sector_stocks:
            if st["aggregate_score_pct"] is not None:
                agg_scores.append(st["aggregate_score_pct"])
            for fam, fdata in st["per_family"].items():
                if fdata is not None:
                    family_sums[fam].append(fdata["score_pct"])

        per_family = {}
        for fam in FAMILIES:
            scores = family_sums.get(fam, [])
            if scores:
                avg = sum(scores) / len(scores)
                st = FAMILY_SIGNAL_TYPE.get(fam, "trend")
                per_family[fam] = {
                    "score_pct": round(avg, 2),
                    "label": signal_type_label(st, avg),
                }

        sector_agg = sum(agg_scores) / len(agg_scores) if agg_scores else 0.0

        sectors.append({
            "sector": sector_name,
            "stock_count": len(sector_stocks),
            "aggregate_score_pct": round(sector_agg, 2),
            "aggregate_signal_label": _score_to_label(sector_agg),
            "per_family": per_family,
        })

    return sectors


def aggregate_index(stocks: list[dict]) -> dict:
    """Compute MASI-wide aggregate scores and breadth."""
    family_sums: dict[str, list[float]] = defaultdict(list)
    agg_scores = []
    count_achat = 0
    count_neutre = 0
    count_vente = 0
    count_indisponible = 0

    for s in stocks:
        label = s.get("aggregate_signal_label")
        if label is None:
            count_indisponible += 1
        elif "Achat" in label:
            count_achat += 1
        elif "Vente" in label:
            count_vente += 1
        else:
            count_neutre += 1

        if s["aggregate_score_pct"] is not None:
            agg_scores.append(s["aggregate_score_pct"])
        for fam, fdata in s["per_family"].items():
            if fdata is not None:
                family_sums[fam].append(fdata["score_pct"])

    per_family = {}
    for fam in FAMILIES:
        scores = family_sums.get(fam, [])
        if scores:
            avg = sum(scores) / len(scores)
            st = FAMILY_SIGNAL_TYPE.get(fam, "trend")
            per_family[fam] = {
                "score_pct": round(avg, 2),
                "label": signal_type_label(st, avg),
            }

    overall_agg = sum(agg_scores) / len(agg_scores) if agg_scores else 0.0

    return {
        "name": "MASI",
        "stock_count": len(stocks),
        "aggregate_score_pct": round(overall_agg, 2),
        "aggregate_signal_label": _score_to_label(overall_agg),
        "per_family": per_family,
        "breadth": {
            "achat": count_achat,
            "neutre": count_neutre,
            "vente": count_vente,
            "indisponible": count_indisponible,
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    from sqlalchemy import text

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    SessionLocal = _ensure_session_factory()
    db = SessionLocal()

    try:
        # 1. Get all symbols with canonical 1D data
        rows = db.execute(text("""
            SELECT DISTINCT mds.symbol, sm.display_name, sm.sector
            FROM market_data_store mds
            LEFT JOIN stock_master sm ON sm.symbol = mds.symbol
            WHERE mds.timeframe = '1D'
            ORDER BY mds.symbol
        """)).fetchall()

        symbols_info = []
        for r in rows:
            symbol = r[0]
            display_name = r[1]
            sector = r[2]
            # Fallback to masi_tickers registry for display_name and sector
            masi = get_masi_info(symbol)
            if masi:
                display_name = display_name or masi.get("display_name")
                sector = sector or masi.get("sector")
            symbols_info.append({
                "symbol": symbol,
                "display_name": display_name,
                "sector": sector,
            })

        logger.info("Found %d symbols with 1D data", len(symbols_info))

        # 2. For each horizon, compute all scores
        for horizon, horizon_label in HORIZONS.items():
            logger.info("\n=== Horizon: %s (%s) ===", horizon, horizon_label)
            t0 = time.time()

            stocks = []
            for i, info in enumerate(symbols_info, 1):
                symbol = info["symbol"]
                result = compute_symbol_scores(db, symbol, horizon)

                if result is None:
                    logger.info("[%d/%d] %s: SKIPPED (no data or all families failed)",
                                i, len(symbols_info), symbol)
                    continue

                fam_summary = " ".join(
                    f"{f}={result['per_family'][f]['label']}"
                    for f in FAMILIES if f in result["per_family"]
                )
                logger.info("[%d/%d] %s: %s -> %s (%.1f)",
                            i, len(symbols_info), symbol, fam_summary,
                            result["aggregate_signal_label"],
                            result["aggregate_score_pct"])

                stocks.append({
                    "symbol": symbol,
                    "display_name": info["display_name"],
                    "sector": info["sector"],
                    **result,
                })

            # 3. Aggregate
            sectors = aggregate_sectors(stocks)
            index = aggregate_index(stocks)

            # 4. Write JSON
            output = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "horizon": horizon,
                "horizon_label": horizon_label,
                "stocks": stocks,
                "sectors": sectors,
                "index": index,
            }

            out_path = OUTPUT_DIR / f"scores-{horizon}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            elapsed = time.time() - t0
            logger.info("Wrote %s (%d stocks, %d sectors) in %.1fs",
                        out_path.name, len(stocks), len(sectors), elapsed)

    finally:
        db.close()

    logger.info("\nDone. Files in: %s", OUTPUT_DIR)


if __name__ == "__main__":
    main()
```

---

## File: `frontend/public/data/.gitkeep` (CREATE)

Empty file. Just ensures the `public/data/` directory exists in the repo.

---

## How to run

```bash
cd C:/Users/taha/Downloads/backtester_signal_engine_autoaccept
.venv/Scripts/python frontend/scripts/export-scores.py
```

**Prerequisites**: The PostgreSQL database must be running at `127.0.0.1:5555` (or wherever `DATABASE_URL` points), and it must have market data loaded via the "Mettre a jour via Bourse" button on the `/data` page.

**Output**: Three JSON files in `frontend/public/data/`:
- `scores-short.json` — Court terme signals
- `scores-medium.json` — Moyen terme signals
- `scores-long.json` — Long terme signals

---

## Output JSON shape reference

Each file has this structure:

```json
{
  "generated_at": "2026-04-08T14:30:00",
  "horizon": "medium",
  "horizon_label": "Moyen terme",
  "stocks": [
    {
      "symbol": "IAM",
      "display_name": "Maroc Telecom",
      "sector": "Telecommunications",
      "aggregate_score_pct": 34.5,
      "aggregate_signal_label": "Achat",
      "per_family": {
        "sma": { "score_pct": 45.2, "label": "Haussier" },
        "macd": { "score_pct": 23.1, "label": "Haussier" },
        "rsi": { "score_pct": -12.0, "label": "Normal" },
        "obv": { "score_pct": 51.3, "label": "Accumulation" }
      },
      "categories": {
        "tendance": { "score_pct": 34.15, "label": "Haussier", "families": ["sma", "macd"] },
        "oscillation": { "score_pct": -12.0, "label": "Normal", "families": ["rsi"] },
        "volume": { "score_pct": 51.3, "label": "Accumulation", "families": ["obv"] }
      }
    }
  ],
  "sectors": [
    {
      "sector": "Banques",
      "stock_count": 7,
      "aggregate_score_pct": 12.3,
      "aggregate_signal_label": "Neutre",
      "per_family": {
        "sma": { "score_pct": 18.5, "label": "Haussier" },
        "macd": { "score_pct": 6.1, "label": "Neutre" },
        "rsi": { "score_pct": -5.2, "label": "Normal" },
        "obv": { "score_pct": 29.8, "label": "Accumulation" }
      }
    }
  ],
  "index": {
    "name": "MASI",
    "stock_count": 75,
    "aggregate_score_pct": 8.7,
    "aggregate_signal_label": "Neutre",
    "per_family": {
      "sma": { "score_pct": 14.2, "label": "Neutre" },
      "macd": { "score_pct": 3.1, "label": "Neutre" },
      "rsi": { "score_pct": -8.5, "label": "Normal" },
      "obv": { "score_pct": 25.9, "label": "Accumulation" }
    },
    "breadth": {
      "achat": 28,
      "neutre": 32,
      "vente": 15,
      "indisponible": 0
    }
  }
}
```

### Notes on `per_family`

- Keys are always from `["sma", "macd", "rsi", "obv"]`
- A family may be absent if it failed for that stock (e.g., OBV with no volume)
- In the frontend, absent families should show "—" not an error

### Notes on `aggregate_signal_label`

Possible values (from `_score_to_label` in `ensemble.py`):
- `"Achat fort"` (score > 50)
- `"Achat"` (score > 15)
- `"Neutre"` (score between -15 and 15)
- `"Vente"` (score < -15)
- `"Vente forte"` (score < -50)

### Notes on family labels

From `signal_type_label()` in `domain.py:38-84`:

| Family | Type | > 50 | 15 to 50 | -15 to 15 | -50 to -15 | < -50 |
|--------|------|------|----------|-----------|------------|-------|
| sma | trend | Tres haussier | Haussier | Neutre | Baissier | Tres baissier |
| macd | trend | Tres haussier | Haussier | Neutre | Baissier | Tres baissier |
| rsi | oscillator | Tres survendu | Survendu | Normal | Surachete | Tres surachete |
| obv | volume | Forte accumulation | Accumulation | Neutre | Distribution | Forte distribution |

**Important**: These labels do NOT have accents (no "e" with accent on "Tres", no accent on "Surachete"). This matches `domain.py` exactly. Do NOT add accents in the frontend code.
