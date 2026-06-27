#!/usr/bin/env python3
"""Does the global score predict forward OOS return, and where are the real breaks?

QUESTION THIS ANSWERS
---------------------
The recommendation buckets are hard-coded thresholds on the global score:
    > 50  achat_fort      (strong buy)
    > 15  achat           (buy)
    >=-15 neutre
    >=-50 vente           (sell)
    <-50  vente_forte     (strong sell)

The 15/50 cutoffs are unjustified, and it's unclear whether "buy" and
"strong buy" are even distinguishable. A bucket boundary is only justified
if the buckets differ in the thing we care about: FORWARD OOS RETURN.

This builds a panel of (assembled score at bar t, forward h-bar return) over
all OOS bars and asks:
  1. Is the score monotonically related to forward return? (rank IC, bin table)
  2. Does the >50 region actually out-earn the 15..50 region? (buy vs strong-buy
     mean return + hit rate + Welch t-stat)
  3. Where does expected forward return actually cross zero? (the data-driven
     "buy line", vs the assumed 15)

METHOD / CAVEATS
----------------
- Per-bar assembled score is RECONSTRUCTED as sum(weight_cat * category_score),
  using the per-bar OOS category scores in signal_score_history and the (current)
  assembly weights in wfo_global_signal. Using current weights for historical
  bars is an approximation (weights are stable, computed on full-OOS composite).
  S/R modifier is NOT applied (not stored per bar); we test the core signal.
- Forward return = close[t+h]/close[t]-1, aligned on each symbol's price index.
- Read-only. Run INSIDE the worker container (needs DB + MinIO price loader).

USAGE (inside worker container)
-------------------------------
    python /tmp/score_threshold_information.py --horizon weekly --variant expanded_ta_simple
"""

from __future__ import annotations

import argparse
import math
import statistics
from collections import defaultdict

import numpy as np
from sqlalchemy import text

from services.worker.db import SessionLocal
from services.api.app.market_data_loader import load_ohlcv_for_symbol
from core.quant_core.data import drop_incomplete_ohlcv_rows

CATEGORIES = ("tendance", "momentum", "oscillation", "volume")


def load_scores(db, horizon: str, variant: str):
    """-> {symbol: {date: {category: score_pct}}} for OOS bars only."""
    src = f"wfo:{variant}"
    rows = db.execute(text("""
        SELECT symbol, date, category, score_pct
        FROM signal_score_history
        WHERE horizon = :h AND source = :s AND is_oos = true
              AND score_pct IS NOT NULL
    """), {"h": horizon, "s": src}).fetchall()
    out: dict[str, dict] = defaultdict(lambda: defaultdict(dict))
    for symbol, d, cat, score in rows:
        out[symbol][d][cat] = float(score)
    return out


def load_weights(db, horizon: str, variant: str):
    """-> {symbol: {category: weight}} from wfo_global_signal."""
    rows = db.execute(text("""
        SELECT symbol, weight_tendance, weight_momentum,
               weight_oscillation, weight_volume
        FROM wfo_global_signal
        WHERE horizon = :h AND variant = :v AND status = 'succeeded'
    """), {"h": horizon, "v": variant}).fetchall()
    out: dict[str, dict] = {}
    for symbol, wt, wm, wo, wv in rows:
        w = {"tendance": wt or 0.0, "momentum": wm or 0.0,
             "oscillation": wo or 0.0, "volume": wv or 0.0}
        total = sum(w.values())
        if total > 0:
            out[symbol] = {k: v / total for k, v in w.items()}
    return out


def forward_returns(close: np.ndarray, idx, h: int):
    """-> {date: fwd_return} where fwd = close[t+h]/close[t]-1."""
    out = {}
    n = len(close)
    for i in range(n - h):
        c0 = close[i]
        if c0 and not math.isnan(c0):
            out[idx[i]] = close[i + h] / c0 - 1.0
    return out


def build_panel(db, horizon: str, variant: str, h: int):
    scores = load_scores(db, horizon, variant)
    weights = load_weights(db, horizon, variant)
    panel_score: list[float] = []
    panel_ret: list[float] = []
    symbols_used = 0
    for symbol, w in weights.items():
        sym_scores = scores.get(symbol)
        if not sym_scores:
            continue
        try:
            df = drop_incomplete_ohlcv_rows(load_ohlcv_for_symbol(db, symbol)).copy().sort_index()
        except Exception:
            continue
        close_col = next((c for c in ("Close", "close", "Adj Close") if c in df.columns), None)
        if close_col is None or len(df) < h + 5:
            continue
        close = df[close_col].to_numpy(dtype=float)
        idx = [d.date() if hasattr(d, "date") else d for d in df.index]
        fwd = forward_returns(close, idx, h)
        used = False
        for d, cat_scores in sym_scores.items():
            r = fwd.get(d)
            if r is None:
                continue
            assembled = sum(w.get(c, 0.0) * cat_scores.get(c, 0.0) for c in CATEGORIES)
            panel_score.append(assembled)
            panel_ret.append(r)
            used = True
        symbols_used += int(used)
    return np.array(panel_score), np.array(panel_ret), symbols_used


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    def rank(a):
        order = a.argsort()
        r = np.empty_like(order, dtype=float)
        r[order] = np.arange(len(a))
        return r
    rx, ry = rank(x), rank(y)
    rx -= rx.mean(); ry -= ry.mean()
    denom = math.sqrt((rx @ rx) * (ry @ ry))
    return float(rx @ ry / denom) if denom else 0.0


def welch_t(a: np.ndarray, b: np.ndarray):
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    va, vb = a.var(ddof=1), b.var(ddof=1)
    se = math.sqrt(va / len(a) + vb / len(b))
    return float((a.mean() - b.mean()) / se) if se else float("nan")


def pct(x: float) -> str:
    return f"{x*100:+.2f}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", default="weekly")
    ap.add_argument("--variant", default="expanded_ta_simple")
    ap.add_argument("--horizons-bars", default="5,10,20",
                    help="forward holding periods in bars to test")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        for h in [int(x) for x in args.horizons_bars.split(",")]:
            score, ret, n_sym = build_panel(db, args.horizon, args.variant, h)
            print("=" * 76)
            print(f"FORWARD HOLDING = {h} bars   ({args.horizon}/{args.variant})")
            print("=" * 76)
            if len(score) < 50:
                print(f"  too few observations ({len(score)}); skipping")
                continue
            print(f"  observations: {len(score)}   symbols: {n_sym}   "
                  f"rank IC (Spearman): {spearman(score, ret):+.3f}")

            # Bin table by score buckets (the production cut points + zero)
            edges = [-101, -50, -15, 0, 15, 50, 101]
            labels = ["<=-50 (strong sell)", "-50..-15 (sell)", "-15..0",
                      "0..15", "15..50 (buy)", ">50 (strong buy)"]
            print(f"  {'bucket':<22} {'n':>6} {'mean fwd':>10} "
                  f"{'median':>9} {'hit>0':>7}")
            for lab, lo, hi in zip(labels, edges[:-1], edges[1:]):
                mask = (score > lo) & (score <= hi)
                rr = ret[mask]
                if len(rr) == 0:
                    print(f"  {lab:<22} {0:>6}        --        --      --")
                    continue
                hit = float((rr > 0).mean())
                print(f"  {lab:<22} {len(rr):>6} {pct(rr.mean()):>10} "
                      f"{pct(float(np.median(rr))):>9} {hit*100:6.1f}%")

            # Buy vs strong-buy: the user's direct question
            buy = ret[(score > 15) & (score <= 50)]
            strong = ret[score > 50]
            print()
            if len(buy) and len(strong):
                t = welch_t(strong, buy)
                print(f"  buy(15..50): n={len(buy):>5} mean={pct(buy.mean())} "
                      f"hit={float((buy>0).mean())*100:.1f}%")
                print(f"  strong(>50): n={len(strong):>5} mean={pct(strong.mean())} "
                      f"hit={float((strong>0).mean())*100:.1f}%")
                print(f"  strong - buy: Δmean={pct(strong.mean()-buy.mean())}  "
                      f"Welch t={t:+.2f}  "
                      f"{'(distinguishable)' if abs(t) >= 2 else '(NOT distinguishable)'}")
            else:
                print(f"  buy/strong-buy: insufficient samples "
                      f"(buy={len(buy)}, strong={len(strong)})")

            # Decile monotonicity: mean fwd return by score decile
            qs = np.quantile(score, np.linspace(0, 1, 11))
            print("\n  score deciles -> mean forward return (monotone?):")
            prev = None
            mono = True
            for di in range(10):
                lo, hi = qs[di], qs[di + 1]
                m = (score >= lo) & (score <= hi) if di == 9 else (score >= lo) & (score < hi)
                rr = ret[m]
                if len(rr) == 0:
                    continue
                mean_r = rr.mean()
                if prev is not None and mean_r < prev - 1e-9:
                    mono = False
                prev = mean_r
                bar = "#" * max(0, int(mean_r * 500))
                print(f"    D{di+1} [{lo:7.1f},{hi:7.1f}]  n={len(rr):>5}  "
                      f"{pct(mean_r):>9}  {bar}")
            print(f"  monotone across deciles: {mono}")
            print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
