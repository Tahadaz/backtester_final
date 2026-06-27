"""Smoke test: real-data cross-sectional momentum bake-off on the liquid MASI universe.

Run from repo root:
    python scripts/research/momentum_bakeoff_smoke.py

Data loading path: services.api.app  (same as the analytics router, no HTTP layer).
  DB  — postgresql+psycopg2://app:app@127.0.0.1:5555/quant  (or $DATABASE_URL)
  S3  — http://localhost:9000, minio/minio12345             (or $S3_* env vars)

Universe construction:
  1. Query market_data_store WHERE timeframe='1D' AND asset_class='equity' AND object_key IS NOT NULL
  2. Load Close series via load_close_series_from_store(object_key=...)
  3. Apply get_active_universe filters: min_bars=252, min_price=5 MAD
     (volume absent from Close parquet → ADV filter applied from DB adv_20d column)
  4. Exclude symbols where adv_20d IS NOT NULL AND adv_20d > 0 AND adv_20d < 1_000_000 MAD

No tuning of parameters to improve results. "No variant passes FDR" is a valid outcome.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

# Repo root on sys.path → imports `core` and `services.api.app`
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from services.api.app.db import _ensure_session_factory
from services.api.app import models
from services.api.app.market_data_loader import load_close_series_from_store
from core.quant_core.research.universe import get_active_universe
from core.quant_core.research.cross_sectional import (
    CrossSectionalConfig,
    VARIANTS,
    run_momentum_bakeoff,
)

MIN_BARS = 252
MIN_PRICE = 5.0
MIN_ADV_MAD = 1_000_000.0
GAP_WARN_DAYS = 20   # flag max gap > this many calendar days


def main() -> None:
    t0 = time.time()

    SessionLocal = _ensure_session_factory()
    db = SessionLocal()
    try:
        _run(db, t0)
    finally:
        db.close()


def _run(db, t0: float) -> None:
    # ── 1. Enumerate equity symbols ──────────────────────────────────────────
    print("Querying market_data_store for equity 1D symbols with S3 parquet…")
    store_rows = (
        db.query(models.MarketDataStore)
        .filter(
            models.MarketDataStore.timeframe == "1D",
            models.MarketDataStore.asset_class == "equity",
            models.MarketDataStore.object_key.isnot(None),
        )
        .order_by(models.MarketDataStore.symbol.asc())
        .all()
    )
    print(f"  DB rows found: {len(store_rows)}")

    # ── 2. Load Close series from S3 ─────────────────────────────────────────
    print("Loading Close series from S3 parquet…")
    close_raw: dict[str, pd.Series] = {}
    adv_from_db: dict[str, float] = {}
    load_errors: list[str] = []

    for row in store_rows:
        sym = str(row.symbol).strip().upper()
        raw_adv = row.adv_20d
        adv_from_db[sym] = float(raw_adv) if raw_adv is not None else float("nan")
        try:
            s = load_close_series_from_store(object_key=str(row.object_key))
            # Strip tz-info: portfolio_stats helpers compare against tz-naive Timestamps
            if getattr(s.index, "tz", None) is not None:
                s = s.tz_convert("UTC").tz_localize(None)
            if not s.empty:
                close_raw[sym] = s
        except Exception as exc:
            load_errors.append(f"  {sym}: {exc}")

    if load_errors:
        print(f"\n  WARN: {len(load_errors)} symbol(s) failed to load from S3:")
        for msg in load_errors[:15]:
            print(msg)
        if len(load_errors) > 15:
            print(f"  … and {len(load_errors) - 15} more")
    print(f"  Loaded Close series: {len(close_raw)} symbols")

    # ── 3. Universe filters ───────────────────────────────────────────────────
    # Wrap each Close series as a single-column DataFrame so get_active_universe
    # can apply the bar-count and price filters. Volume is absent → ADV filter
    # is bypassed inside the function (NaN → don't exclude). We apply adv_20d
    # from the DB separately below.
    price_frames = {
        sym: pd.DataFrame({"Close": series})
        for sym, series in close_raw.items()
    }

    universe = get_active_universe(
        price_frames,
        min_bars=MIN_BARS,
        min_adv_mad=0,       # volume absent; handle adv_20d below
        min_price=MIN_PRICE,
    )

    # Apply ADV filter from DB metadata: exclude only when adv_20d is a known
    # positive value below the threshold (null / 0 = volume data missing → keep)
    tradeable_final: list[str] = []
    excluded_adv: list[tuple[str, float]] = []
    for sym in universe.tradeable:
        adv = adv_from_db.get(sym, float("nan"))
        if math.isfinite(adv) and adv > 0 and adv < MIN_ADV_MAD:
            excluded_adv.append((sym, adv))
        else:
            tradeable_final.append(sym)

    # ── 4. Report universe composition ───────────────────────────────────────
    print(f"\n{'='*70}")
    print("LIQUID MASI UNIVERSE")
    print(f"{'='*70}")
    print(f"  Total equity Close series loaded:  {len(close_raw)}")
    print(f"  Passed min_bars={MIN_BARS}, min_price={MIN_PRICE} MAD:  {universe.n_tradeable}")

    if universe.excluded:
        reasons: dict[str, int] = {}
        for r in universe.excluded:
            key = (r.exclusion_reason or "unknown").split("(")[0].strip()
            reasons[key] = reasons.get(key, 0) + 1
        print(f"  Bar/price exclusion reasons: {dict(sorted(reasons.items(), key=lambda x: -x[1]))}")

    print(f"  Excluded by adv_20d < {MIN_ADV_MAD:,.0f} MAD:  {len(excluded_adv)}")
    if excluded_adv:
        for sym, adv in excluded_adv:
            print(f"    {sym}  adv_20d={adv:,.0f}")

    print(f"  Final tradeable universe:  {len(tradeable_final)} symbols")

    if not tradeable_final:
        print("\n  ERROR: empty tradeable universe — cannot run bake-off.")
        return

    close_by_symbol = {sym: close_raw[sym] for sym in tradeable_final if sym in close_raw}
    print(f"  Symbols: {', '.join(sorted(close_by_symbol.keys()))}")

    # Date range and bar counts
    all_series = list(close_by_symbol.values())
    union_start = min(s.index.min() for s in all_series)
    union_end = max(s.index.max() for s in all_series)
    common_start = max(s.index.min() for s in all_series)
    bar_counts = sorted(len(s) for s in all_series)
    print(f"\n  Date range (union):  {union_start.date()} -> {union_end.date()}")
    print(f"  Common start (intersection):  {common_start.date()}")
    print(f"  Bar counts: min={bar_counts[0]}  median={bar_counts[len(bar_counts)//2]}  max={bar_counts[-1]}")

    # Gap check: flag symbols with calendar gaps > GAP_WARN_DAYS
    gap_warnings: list[str] = []
    for sym, s in close_by_symbol.items():
        diffs = s.index.to_series().diff().dt.days.dropna()
        if diffs.empty:
            continue
        max_gap = int(diffs.max())
        if max_gap > GAP_WARN_DAYS:
            gap_warnings.append(f"{sym}: max_gap={max_gap} calendar days")
    if gap_warnings:
        print(f"\n  WARN: {len(gap_warnings)} symbol(s) have gaps > {GAP_WARN_DAYS} calendar days:")
        for w in gap_warnings:
            print(f"    {w}")
    else:
        print(f"\n  No gaps > {GAP_WARN_DAYS} calendar days detected.")

    # ── 5. Run bake-off ───────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("Running run_momentum_bakeoff(execution='next_open', cost_bps=33.0, min_names=8)…")
    print(f"{'='*70}")
    t_bakeoff = time.time()

    cfg = CrossSectionalConfig(
        execution="next_open",
        cost_bps=33.0,
        min_names=8,
        fdr_alpha=0.10,
    )
    result = run_momentum_bakeoff(close_by_symbol, cfg)
    bakeoff_s = time.time() - t_bakeoff
    print(f"  Bake-off done in {bakeoff_s:.1f}s")

    # ── 6. Print results table ────────────────────────────────────────────────
    W = 13

    def f(x: object, dec: int = 4) -> str:
        if x is None or (isinstance(x, float) and not math.isfinite(x)):
            return "—".ljust(W)
        return f"{float(x):.{dec}f}".ljust(W)

    def fi(x: object) -> str:
        return str(int(x) if x is not None else "—").ljust(W)

    print(f"\n{'='*70}")
    print("BAKE-OFF RESULTS — REAL DATA")
    print(f"{'='*70}")
    cols = [
        "variant", "n_dates", "IC_mean", "NW_tstat", "IC_pval",
        "BH_q", "FDR?", "Q5-Q1_sprd", "monoton",
        "LO_net_SR", "LS_net_SR", "LO_maxDD", "avg_turn",
    ]
    print("  " + "  ".join(c.ljust(W) for c in cols))
    print("  " + "-" * (W * len(cols) + 2 * (len(cols) - 1)))

    for v in result.ranked_variants:
        ev = result.evaluations[v]
        lo = result.long_only[v]
        ls = result.long_short[v]
        q = result.bh_qvalues[v]
        fp = result.fdr_pass[v]
        cells = [
            v.ljust(W),
            fi(ev.n_dates),
            f(ev.rank_ic_mean),
            f(ev.rank_ic_tstat),
            f(ev.ic_pvalue),
            f(q),
            ("YES" if fp else "NO ").ljust(W),
            f(ev.quintile_spread),
            f(ev.quintile_monotonicity),
            f(lo.after_cost_sharpe),
            f(ls.after_cost_sharpe),
            f(lo.max_drawdown),
            f(lo.avg_turnover),
        ]
        print("  " + "  ".join(cells))

    print()
    if result.winner_key:
        winner_ev = result.evaluations[result.winner_key]
        winner_lo = result.long_only[result.winner_key]
        print(f"  *** WINNER: {result.winner_key}  "
              f"IC={winner_ev.rank_ic_mean:.4f}  t={winner_ev.rank_ic_tstat:.2f}  "
              f"net_SR={winner_lo.after_cost_sharpe:.4f}  "
              f"total_ret={winner_lo.total_return:.2%} ***")
    else:
        print("  *** NO VARIANT PASSES FDR (q <= 0.10) — no alpha found. ***")

    if result.survivorship_warning:
        print(f"\n  SURVIVORSHIP WARNING: {result.survivorship_warning}")

    # ── 7. Per-variant quintile detail ────────────────────────────────────────
    print(f"\n{'='*70}")
    print("PER-VARIANT QUINTILE MEAN FORWARD RETURNS (primary horizon = 21 bars)")
    print(f"{'='*70}")
    for v in result.ranked_variants:
        ev = result.evaluations[v]
        if not ev.quintile_returns:
            print(f"  {v}: no quintile data")
            continue
        q_row = "  ".join(
            f"Q{q['quintile']}={q['mean_forward_return']*100:.2f}%"
            for q in ev.quintile_returns
        )
        print(f"  {v}: {q_row}")

    # ── 8. IC decay ───────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("IC DECAY (mean rank-IC at each horizon)")
    print(f"{'='*70}")
    for v in result.ranked_variants:
        ev = result.evaluations[v]
        decay_row = "  ".join(
            f"{d['horizon_days']}d={d['mean_ic']:.4f}" if d['mean_ic'] is not None and math.isfinite(d['mean_ic']) else f"{d['horizon_days']}d=—"
            for d in ev.ic_decay
        )
        print(f"  {v}: {decay_row}")

    total_s = time.time() - t0
    print(f"\n  Total elapsed: {total_s:.1f}s")
    print()


if __name__ == "__main__":
    main()
