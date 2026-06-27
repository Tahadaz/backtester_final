#!/usr/bin/env python3
"""Breadth pressure test: does the universe support an active-management framework?

THE GATE
--------
Fundamental Law of Active Management (Grinold-Kahn):

    IR = TC * IC * sqrt(BR)

  IC = cross-sectional information coefficient (skill per bet)
  BR = breadth = number of INDEPENDENT bets per year
  TC = transfer coefficient (how much skill survives constraints; long-only ~0.5)

Small single-market universes (like the BVC) die on BR: the naive count
(N names * rebalances/year) is an illusion because (a) names co-move, so the
EFFECTIVE number of independent names is far below N, and (b) a slow signal
makes consecutive periods overlap. This script measures the REAL numbers and
reports the achievable IR, so we know whether the calibration/sizing framework
is worth building before we build it.

WHAT IT COMPUTES
----------------
1. Periodic cross-sectional IC: each rebalance date, Spearman(score_i, fwd_ret_i)
   across names. Report mean IC, std, t-stat (signal real?), IC-IR.
2. Effective breadth:
     N_eff = N / (1 + (N-1)*rho_bar)         (avg pairwise return correlation)
     periods/yr = 252 / h                    (NON-overlapping holding periods)
     BR_eff = N_eff * periods/yr   vs naive  BR = N * periods/yr
3. Achievable IR = TC * mean_IC * sqrt(BR_eff), TC in {1.0 unconstrained, 0.5 long-only}
   and the implied annual Sharpe.

CAVEATS: reconstructed score (current weights); BVC corr may be noisy; TC is a
rule-of-thumb (Clarke-de Silva-Thorley). Estimates POTENTIAL, not realized.
Read-only. Run INSIDE the worker container.
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict

import numpy as np
import pandas as pd
from sqlalchemy import text

from services.worker.db import SessionLocal
from services.api.app.market_data_loader import load_ohlcv_for_symbol
from core.quant_core.data import drop_incomplete_ohlcv_rows

CATEGORIES = ("tendance", "momentum", "oscillation", "volume")
TRADING_DAYS = 252


def load_scores(db, horizon, variant):
    src = f"wfo:{variant}"
    rows = db.execute(text("""
        SELECT symbol, date, category, score_pct
        FROM signal_score_history
        WHERE horizon=:h AND source=:s AND is_oos=true AND score_pct IS NOT NULL
    """), {"h": horizon, "s": src}).fetchall()
    out = defaultdict(lambda: defaultdict(dict))
    for symbol, d, cat, score in rows:
        out[symbol][d][cat] = float(score)
    return out


def load_weights(db, horizon, variant):
    rows = db.execute(text("""
        SELECT symbol, weight_tendance, weight_momentum, weight_oscillation, weight_volume
        FROM wfo_global_signal
        WHERE horizon=:h AND variant=:v AND status='succeeded'
    """), {"h": horizon, "v": variant}).fetchall()
    out = {}
    for symbol, wt, wm, wo, wv in rows:
        w = {"tendance": wt or 0.0, "momentum": wm or 0.0,
             "oscillation": wo or 0.0, "volume": wv or 0.0}
        tot = sum(w.values())
        if tot > 0:
            out[symbol] = {k: v / tot for k, v in w.items()}
    return out


def spearman(x, y):
    if len(x) < 4:
        return float("nan")
    def rank(a):
        o = a.argsort(); r = np.empty_like(o, float); r[o] = np.arange(len(a)); return r
    rx, ry = rank(x), rank(y); rx -= rx.mean(); ry -= ry.mean()
    d = math.sqrt((rx @ rx) * (ry @ ry))
    return float(rx @ ry / d) if d else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", default="weekly")
    ap.add_argument("--variant", default="expanded_ta_simple")
    ap.add_argument("--h", type=int, default=5, help="holding period in bars (=rebalance spacing)")
    ap.add_argument("--min-names", type=int, default=10)
    ap.add_argument("--corr-lookback", type=int, default=504, help="bars for corr matrix")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        scores = load_scores(db, args.horizon, args.variant)
        weights = load_weights(db, args.horizon, args.variant)

        # Build per-symbol aligned series of (date -> assembled score) and price frames.
        assembled = {}      # symbol -> dict(date -> score)
        ret_series = {}     # symbol -> pd.Series daily returns (for corr)
        fwd = {}            # symbol -> dict(date -> fwd h-bar return)
        for symbol, w in weights.items():
            sc = scores.get(symbol)
            if not sc:
                continue
            try:
                df = drop_incomplete_ohlcv_rows(load_ohlcv_for_symbol(db, symbol)).copy().sort_index()
            except Exception:
                continue
            col = next((c for c in ("Close", "close", "Adj Close") if c in df.columns), None)
            if col is None or len(df) < args.h + 30:
                continue
            close = df[col].astype(float)
            idx = [d.date() if hasattr(d, "date") else d for d in df.index]
            close.index = idx
            assembled[symbol] = {
                d: sum(w.get(c, 0.0) * cs.get(c, 0.0) for c in CATEGORIES)
                for d, cs in sc.items()
            }
            arr = close.to_numpy()
            fwd[symbol] = {idx[i]: arr[i + args.h] / arr[i] - 1.0
                           for i in range(len(arr) - args.h) if arr[i]}
            ret_series[symbol] = close.pct_change().dropna()

        symbols = sorted(assembled)
        N = len(symbols)
        if N < args.min_names:
            print(f"Only {N} symbols; cannot assess breadth."); return

        # ---- Cross-sectional IC on NON-overlapping rebalance dates ----
        master = sorted({d for s in symbols for d in assembled[s]})
        rebal = master[::args.h]
        ic_list = []
        names_per = []
        for d in rebal:
            xs, ys = [], []
            for s in symbols:
                sv = assembled[s].get(d); rv = fwd[s].get(d)
                if sv is not None and rv is not None:
                    xs.append(sv); ys.append(rv)
            if len(xs) >= args.min_names:
                ic = spearman(np.array(xs), np.array(ys))
                if not math.isnan(ic):
                    ic_list.append(ic); names_per.append(len(xs))
        ic = np.array(ic_list)
        n_per = len(ic)
        mean_ic = float(ic.mean()); std_ic = float(ic.std(ddof=1))
        t_ic = mean_ic / std_ic * math.sqrt(n_per) if std_ic else float("nan")
        ic_ir = mean_ic / std_ic if std_ic else float("nan")
        avg_names = float(np.mean(names_per))

        # ---- Effective breadth via avg pairwise return correlation ----
        rdf = pd.DataFrame(ret_series)
        if args.corr_lookback:
            rdf = rdf.tail(args.corr_lookback)
        corr = rdf.corr(min_periods=60)
        vals = corr.to_numpy()
        iu = np.triu_indices_from(vals, k=1)
        off = vals[iu]
        off = off[~np.isnan(off)]
        rho_bar = float(np.mean(off))
        n_eff = N / (1 + (N - 1) * rho_bar) if (1 + (N - 1) * rho_bar) > 0 else float("nan")
        # eigenvalue participation ratio cross-check (uses complete-case corr)
        try:
            c2 = corr.dropna(how="any", axis=0).dropna(how="any", axis=1).to_numpy()
            ev = np.linalg.eigvalsh(c2)
            ev = ev[ev > 0]
            part_ratio = float((ev.sum() ** 2) / (ev ** 2).sum())
        except Exception:
            part_ratio = float("nan")

        periods_yr = TRADING_DAYS / args.h
        br_naive = N * periods_yr
        br_eff = n_eff * periods_yr

        ir_uncon = mean_ic * math.sqrt(br_eff)
        ir_lo = 0.5 * ir_uncon  # long-only transfer coefficient ~0.5

        print("=" * 74)
        print(f"BREADTH PRESSURE TEST  ({args.horizon}/{args.variant}, h={args.h} bars)")
        print("=" * 74)
        print(f"\n[1] SIGNAL SKILL (cross-sectional IC, non-overlapping periods)")
        print(f"    rebalance periods           : {n_per}")
        print(f"    avg names / cross-section   : {avg_names:.1f}  (of {N})")
        print(f"    mean IC                     : {mean_ic:+.4f}")
        print(f"    std  IC                     : {std_ic:.4f}")
        print(f"    IC t-stat                   : {t_ic:+.2f}   "
              f"{'(significant)' if abs(t_ic) >= 2 else '(NOT significant)'}")
        print(f"    IC information ratio        : {ic_ir:+.3f}")

        print(f"\n[2] BREADTH HAIRCUT")
        print(f"    universe N                  : {N}")
        print(f"    avg pairwise return corr    : {rho_bar:+.3f}")
        print(f"    effective independent names : {n_eff:.1f}   "
              f"(participation-ratio check: {part_ratio:.1f})")
        print(f"    non-overlap periods / year  : {periods_yr:.1f}")
        print(f"    naive breadth  (N*f)        : {br_naive:,.0f}")
        print(f"    EFFECTIVE breadth (Neff*f)  : {br_eff:,.0f}   "
              f"(haircut x{br_naive/br_eff:.1f})")

        print(f"\n[3] ACHIEVABLE INFORMATION RATIO  (IR = TC * IC * sqrt(BR_eff))")
        print(f"    unconstrained (TC=1.0)      : {ir_uncon:+.2f}")
        print(f"    long-only     (TC~0.5)      : {ir_lo:+.2f}")
        print(f"    -> implied annual Sharpe of the active book ~ {ir_lo:+.2f}")

        print("\n" + "=" * 74)
        print("VERDICT")
        print("=" * 74)
        if abs(t_ic) < 2:
            print("STOP. The cross-sectional IC is not statistically significant.")
            print("The score does not reliably rank names; no breadth fixes that.")
        elif ir_lo < 0.3:
            print("THIN. Signal is real but breadth is too low for a meaningful IR.")
            print("Do NOT build the full calibration/optimizer stack. Use simple,")
            print("heavily-shrunk risk-controlled sizing and manage expectations.")
        elif ir_lo < 0.6:
            print("MARGINAL. Worth a LIGHTWEIGHT version (z-score -> shrunk forecast")
            print("-> fractional-Kelly w/ vol target). Heavy optimization not justified.")
        else:
            print("SUPPORTED. Breadth sustains a real IR; the full framework is")
            print("worth building. Proceed to the calibration layer.")
        print("\nNOTE: this is achievable POTENTIAL (pre-cost, pre-estimation-error).")
        print("Realized will be lower. Re-run with --h 10 / --h 20 to test sensitivity")
        print("to holding period (slower signal -> fewer periods -> lower breadth).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
