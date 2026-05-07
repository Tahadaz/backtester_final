"""Diagnose signal backtest zero-trade issue for one (symbol, horizon).

Connects to the DB, rebuilds per-family and per-category signal series from
persisted engine family rows, and reports where signals collapse to zero.

Usage:
    python scripts/diagnose_signal_backtest.py --symbol ATW --horizon short
    python scripts/diagnose_signal_backtest.py --symbol ATW --horizon medium \
        --window-start 2026-01-01 --side-policy long_short

Writes a Markdown report to diagnostics/signal_backtest_<symbol>_<horizon>.md.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (REPO_ROOT, REPO_ROOT / "core"):
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)


def _dist(arr: np.ndarray) -> dict:
    arr = np.asarray(arr, dtype=np.float64)
    total = len(arr)
    if total == 0:
        return {"n": 0}
    pos = int(np.sum(arr > 0))
    zero = int(np.sum(arr == 0))
    neg = int(np.sum(arr < 0))
    return {
        "n": total,
        "pct_pos": round(100.0 * pos / total, 1),
        "pct_zero": round(100.0 * zero / total, 1),
        "pct_neg": round(100.0 * neg / total, 1),
        "min": round(float(np.min(arr)), 4),
        "max": round(float(np.max(arr)), 4),
        "mean": round(float(np.mean(arr)), 4),
    }


def _fmt(d: dict) -> str:
    if d.get("n", 0) == 0:
        return "no data"
    return (
        f"n={d['n']} | +{d['pct_pos']}% / 0:{d['pct_zero']}% / -{d['pct_neg']}% | "
        f"min={d['min']}, mean={d['mean']}, max={d['max']}"
    )


def diagnose(
    symbol: str,
    horizon: str,
    window_start: str,
    window_end: str | None,
    variant: str,
    side_policy: str,
) -> list[str]:
    from core.quant_core.data import drop_incomplete_ohlcv_rows
    from core.quant_core.signal_engine.backtest_mc import (
        _make_variant_def,
        build_category_signal_series_engine,
        build_global_signal_series,
    )
    from core.quant_core.signal_engine.domain import CATEGORY_FAMILIES
    from core.quant_core.signal_engine.oos_eval import compute_signal_array
    from services.api.app.market_data_loader import load_ohlcv_for_symbol
    from services.worker.db import SessionLocal
    from services.worker.tasks.signal_backtest_batch import (
        _compute_engine_category_weights,
        _load_engine_family_rows,
    )

    db = SessionLocal()
    lines: list[str] = []

    def add(line: str = "") -> None:
        lines.append(line)

    try:
        win_end_date = date.fromisoformat(window_end) if window_end else date.today()

        ohlcv_raw = load_ohlcv_for_symbol(db, symbol, "1D")
        ohlcv = drop_incomplete_ohlcv_rows(ohlcv_raw)
        ohlcv_window = ohlcv.loc[str(window_start):str(win_end_date)]

        add(f"# Signal backtest diagnostic — {symbol} / {horizon}")
        add()
        add(f"- Window: **{window_start} → {win_end_date.isoformat()}**")
        add(f"- Bars: **{len(ohlcv_window)}**")
        add(f"- Side policy: `{side_policy}`  |  Variant: `{variant}`")
        add()

        if len(ohlcv_window) < 10:
            add("> ⚠️ Insufficient bars. Aborting.")
            return lines

        close = ohlcv_window["Close"].values.astype(np.float64)
        high = ohlcv_window["High"].values.astype(np.float64) if "High" in ohlcv_window.columns else None
        low = ohlcv_window["Low"].values.astype(np.float64) if "Low" in ohlcv_window.columns else None
        volume = ohlcv_window["Volume"].values.astype(np.float64) if "Volume" in ohlcv_window.columns else None

        engine_rows = _load_engine_family_rows(db, symbol, horizon, variant)

        add("## 1. Engine family rows")
        add()
        if not engine_rows:
            add(f"> ⚠️ No `signal_engine_family_result` rows for {symbol}/{horizon}/{variant}.")
            add("> Trigger `/signal/engine/trigger` first.")
            return lines

        add(f"Found **{len(engine_rows)}** family rows.")
        add()
        add("| Family | Cat | Provisional | Tested | Viable | Reps | Mean norm_w |")
        add("|---|---|---|---|---|---|---|")
        for row in engine_rows:
            reps = row.get("representatives_json") or []
            mean_w = (
                round(float(np.mean([r.get("normalized_weight", 0.0) for r in reps])), 3)
                if reps else "—"
            )
            add(
                f"| {row.get('family','?')} | {row.get('category','?')} | "
                f"{row.get('is_provisional','?')} | {row.get('tested_count','?')} | "
                f"{row.get('viable_count','?')} | {len(reps)} | {mean_w} |"
            )
        add()

        add("## 2. Per-family signal arrays")
        add()
        for row in engine_rows:
            family = row.get("family", "?")
            reps = row.get("representatives_json") or []
            add(f"### {family} ({row.get('category','?')})")
            if not reps:
                add("> No representatives — skipped.")
                add()
                continue

            rep_arrays: list[np.ndarray] = []
            rep_weights: list[float] = []
            for idx, rep in enumerate(reps):
                try:
                    vdef = _make_variant_def(rep, fallback_family=rep.get("family") or family)
                    arr = np.asarray(compute_signal_array(vdef, close, volume, high, low), dtype=np.float64)
                    w = float(rep.get("normalized_weight") or rep.get("reliability_weight") or 0.0)
                    rep_arrays.append(arr)
                    rep_weights.append(w if w > 0 else 1.0)
                    add(f"- rep[{idx}] `{rep.get('archetype','?')}` w={w:.3f}: {_fmt(_dist(arr))}")
                except Exception as exc:
                    add(f"- rep[{idx}] **FAILED**: {exc}")

            if rep_arrays:
                wa = np.asarray(rep_weights, dtype=np.float64)
                wa = wa / max(wa.sum(), 1e-12)
                weighted = np.clip((wa[:, None] * np.vstack(rep_arrays)).sum(axis=0), -1.0, 1.0)
                add(f"- **weighted-avg**: {_fmt(_dist(weighted))}")
            add()

        add("## 3. Per-category signal series")
        add()
        add("| Category | series | after long_only clip | pos>0 bars |")
        add("|---|---|---|---|")

        cat_series: dict[str, np.ndarray] = {}
        for cat in CATEGORY_FAMILIES.keys():
            try:
                series = build_category_signal_series_engine(close, volume, high, low, engine_rows, cat)
                cat_series[cat] = series
                clipped = np.clip(series, 0.0, 1.0)
                pos_bars = int(np.sum(clipped > 0.0))
                add(
                    f"| {cat} | {_fmt(_dist(series))} | "
                    f"mean={round(float(np.mean(clipped)),4)}, max={round(float(np.max(clipped)),4)} | "
                    f"**{pos_bars} / {len(series)}** |"
                )
            except Exception as exc:
                add(f"| {cat} | **FAILED**: {exc} | — | — |")
        add()

        add("## 4. Global signal series")
        add()
        if len(cat_series) >= 2:
            weights = _compute_engine_category_weights(engine_rows)
            add(f"Category weights: `{weights}`")
            try:
                glob = build_global_signal_series(cat_series, weights)
                clipped = np.clip(glob, 0.0, 1.0)
                add(f"- Global series: {_fmt(_dist(glob))}")
                add(f"- After long_only clip: mean={round(float(np.mean(clipped)),4)}, max={round(float(np.max(clipped)),4)}")
                add(f"- Bars pos>0 (long_only): **{int(np.sum(clipped > 0.0))} / {len(glob)}**")
                add(f"- Bars pos<0 (only with long_short): **{int(np.sum(glob < 0.0))}**")
            except Exception as exc:
                add(f"> **Global build FAILED**: {exc}")
        else:
            add(f"> Only {len(cat_series)} categories computed — global not available.")
        add()

        add("## 5. Conclusion")
        add()
        any_active = any(int(np.sum(np.clip(s, 0.0, 1.0) > 0.0)) > 0 for s in cat_series.values())
        if not any_active:
            add(
                "⚠️ **All categories flat under long_only.** Signals are bearish/neutral and "
                "long_only clips every bar to 0. Options: (a) switch to long_short, "
                "(b) investigate if reps emit all-zero signals (upstream engine issue — check "
                "viable_count and is_provisional above)."
            )
        else:
            total_pos = sum(int(np.sum(np.clip(s, 0.0, 1.0) > 0.0)) for s in cat_series.values())
            add(
                f"✅ **{total_pos}** category-bar pairs have positive signal under long_only. "
                "Zero-trade outcomes in specific scopes may be from averaging/clipping in the "
                "global or combination builders. See section 3 for per-category detail."
            )
        add()

        return lines

    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--horizon", required=True, choices=["short", "medium", "long"])
    parser.add_argument("--window-start", default="2026-01-01")
    parser.add_argument("--window-end", default=None)
    parser.add_argument("--variant", default="expanded")
    parser.add_argument("--side-policy", default="long_only")
    parser.add_argument("--out-dir", default="diagnostics")
    args = parser.parse_args()

    lines = diagnose(
        args.symbol,
        args.horizon,
        args.window_start,
        args.window_end,
        args.variant,
        args.side_policy,
    )
    report = "\n".join(lines)

    out_dir = REPO_ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"signal_backtest_{args.symbol}_{args.horizon}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"Wrote {out_path}")
    print()
    print(report)


if __name__ == "__main__":
    main()
