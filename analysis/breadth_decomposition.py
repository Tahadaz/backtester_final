#!/usr/bin/env python3
"""Decompose the universe into its independent 'bets' - with stock names.

Pipeline (each step prints real numbers):
  1. Daily return panel for the signal universe (equities only).
  2. RAW correlation: avg pairwise rho (full universe), effective bets N_eff,
     plus PCA eigenvalues on a liquid complete-case block.
  3. NAME the bets: each principal component is a portfolio (eigenvector);
     PC1 ~ the whole market, PC2.. ~ sector/style spreads. Show top loadings
     with company name + sector.
  4. REMOVE the market factor (regress each stock on the equal-weight market),
     recompute residual correlation + N_eff on what's left.
  5. Residual PCA: how many independent STOCK-PICKING dimensions remain, and
     which sector clusters they are.

Headline N_eff uses PAIRWISE correlation over the full universe (robust to the
illiquid BVC calendar). PCA/component structure uses a liquid complete-case
block (stocks trading >=90% of days) so the matrix is PSD with no holes.
Read-only. Run INSIDE the worker container.
"""
from __future__ import annotations
import argparse, math
import numpy as np, pandas as pd
from sqlalchemy import text
from services.worker.db import SessionLocal
from services.api.app.market_data_loader import load_ohlcv_for_symbol
from core.quant_core.data import drop_incomplete_ohlcv_rows


def universe(db, horizon, variant):
    rows = db.execute(text("""
        SELECT DISTINCT symbol FROM wfo_global_signal
        WHERE horizon=:h AND variant=:v AND status='succeeded'
    """), {"h": horizon, "v": variant}).fetchall()
    return sorted(r[0] for r in rows)


def meta(db):
    rows = db.execute(text("SELECT symbol, display_name, sector FROM stock_master")).fetchall()
    return {s: (n or s, sec or "?") for s, n, sec in rows}


def n_eff(rho_bar, n):
    d = 1 + (n - 1) * rho_bar
    return n / d if d > 0 else float("nan")


def avg_offdiag(C):
    v = C.to_numpy(); iu = np.triu_indices_from(v, 1); o = v[iu]; o = o[~np.isnan(o)]
    return float(o.mean()) if len(o) else float("nan")


def part_ratio(ev):
    ev = ev[ev > 0]
    return float((ev.sum() ** 2) / (ev ** 2).sum())


def analyze(R, liq_frac=0.90, min_pair=40):
    """-> (rho_pairwise, N, ev, evec, cols, (n_liq_stocks, n_liq_days))."""
    Cpw = R.corr(min_periods=min_pair)
    rho = avg_offdiag(Cpw)
    N = R.shape[1]
    liq = R.dropna(axis=1, thresh=int(liq_frac * len(R))).dropna(axis=0)
    ev = evec = None; cols = []
    if liq.shape[1] >= 5 and liq.shape[0] > liq.shape[1]:
        Cl = liq.corr()
        e, V = np.linalg.eigh(Cl.to_numpy())
        order = e.argsort()[::-1]
        ev, evec, cols = e[order], V[:, order], list(Cl.columns)
    return rho, N, ev, evec, cols, liq.shape


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", default="weekly")
    ap.add_argument("--variant", default="expanded_ta_simple")
    ap.add_argument("--lookback", type=int, default=504)
    ap.add_argument("--n-pcs", type=int, default=6)
    ap.add_argument("--top", type=int, default=6)
    args = ap.parse_args()

    db = SessionLocal()
    try:
        info = meta(db)
        syms = [s for s in universe(db, args.horizon, args.variant) if s in info]
        rets = {}
        for s in syms:
            try:
                df = drop_incomplete_ohlcv_rows(load_ohlcv_for_symbol(db, s)).copy().sort_index()
            except Exception:
                continue
            col = next((c for c in ("Close", "close", "Adj Close") if c in df.columns), None)
            if col is None or len(df) < 120:
                continue
            ser = df[col].astype(float).pct_change()
            ser.index = [d.date() if hasattr(d, "date") else d for d in ser.index]
            rets[s] = ser
        R = pd.DataFrame(rets).tail(args.lookback)
        R = R.dropna(axis=1, thresh=int(0.4 * len(R)))   # drop barely-traded names
        nm = lambda s: f"{s:<5} {info.get(s,(s,'?'))[0][:24]:<24} [{info.get(s,(s,'?'))[1]}]"

        print("=" * 78)
        print(f"BREADTH DECOMPOSITION  ({args.horizon}/{args.variant}, lookback={args.lookback}d)")
        print("=" * 78)
        print(f"equities in universe: {R.shape[1]}   union trading days: {R.shape[0]}")

        # ---- STEP 2: raw correlation ----
        rho, N, ev, evec, cols, liqshape = analyze(R)
        var_exp = ev / ev.sum()
        print(f"\n[STEP 2] RAW return correlation")
        print(f"  avg pairwise corr rho_bar     : {rho:+.3f}")
        print(f"  effective bets  N_eff         : {n_eff(rho, N):.1f}  of {N}")
        print(f"  PCA on liquid block           : {liqshape[1]} stocks x {liqshape[0]} days")
        print(f"  participation ratio (PCA)     : {part_ratio(ev):.1f}")
        print(f"  variance explained PC1..6     : "
              + ", ".join(f"{v*100:.0f}%" for v in var_exp[:6]))
        print(f"  cumulative PC1..6             : {var_exp[:6].sum()*100:.0f}%")

        # ---- STEP 3: name the bets ----
        print(f"\n[STEP 3] THE BETS  (each PC = an independent direction of co-movement)")
        for k in range(min(args.n_pcs, len(cols))):
            load = pd.Series(evec[:, k], index=cols)
            if load.sum() < 0:          # sign is arbitrary; orient positive
                load = -load
            allpos = (load > 0).mean()
            tag = "MARKET (all move together)" if allpos > 0.85 else "SPREAD (relative)"
            print(f"\n  PC{k+1}  ({var_exp[k]*100:.0f}% of variance) - {tag}")
            if tag.startswith("MARKET"):
                top = load.reindex(load.abs().sort_values(ascending=False).index)[:args.top]
                for s, w in top.items():
                    print(f"     {nm(s)}  load={w:+.2f}")
            else:
                for s, w in load.sort_values(ascending=False)[:3].items():
                    print(f"     + {nm(s)}  {w:+.2f}")
                print(f"       ---- vs ----")
                for s, w in load.sort_values()[:3].items():
                    print(f"     - {nm(s)}  {w:+.2f}")

        # ---- STEP 4: remove market factor ----
        mkt = R.mean(axis=1)  # equal-weight market return
        resid, betas = {}, {}
        for s in R.columns:
            df2 = pd.concat([R[s], mkt], axis=1).dropna()
            if len(df2) < 60:
                continue
            x = df2.iloc[:, 1].to_numpy(); yy = df2.iloc[:, 0].to_numpy()
            b = np.cov(x, yy)[0, 1] / np.var(x)
            a = yy.mean() - b * x.mean()
            betas[s] = b
            resid[s] = pd.Series(yy - (a + b * x), index=df2.index)
        Rr = pd.DataFrame(resid)
        rho_r, Nr, evr, evecr, colsr, liqshape_r = analyze(Rr)
        print(f"\n[STEP 4] AFTER removing the common market factor (residuals)")
        print(f"  avg pairwise corr rho_bar     : {rho_r:+.3f}   (was {rho:+.3f})")
        print(f"  effective STOCK-PICKING bets  : {n_eff(rho_r, Nr):.1f}  of {Nr}")
        print(f"  participation ratio (resid)   : {part_ratio(evr):.1f}")
        print(f"  avg market beta               : {np.mean(list(betas.values())):.2f}")

        # ---- STEP 5: residual clusters ----
        print(f"\n[STEP 5] residual independent dimensions (stock-picking structure)")
        var_r = evr / evr.sum()
        for k in range(min(3, len(colsr))):
            load = pd.Series(evecr[:, k], index=colsr)
            pos = load.sort_values(ascending=False)[:3]
            neg = load.sort_values()[:3]
            print(f"\n  resid-PC{k+1} ({var_r[k]*100:.0f}% of residual var)")
            print(f"     one side  : " + " | ".join(
                f"{s}({info.get(s,(s,'?'))[1]})" for s in pos.index))
            print(f"     other side: " + " | ".join(
                f"{s}({info.get(s,(s,'?'))[1]})" for s in neg.index))

        # sector within/across correlation
        sec = {s: info.get(s, (s, "?"))[1] for s in R.columns}
        Cpw = R.corr(min_periods=40); v = Cpw.to_numpy(); cc = list(Cpw.columns)
        within, across = [], []
        for i in range(len(cc)):
            for j in range(i + 1, len(cc)):
                if np.isnan(v[i, j]):
                    continue
                (within if sec[cc[i]] == sec[cc[j]] else across).append(v[i, j])
        print(f"\n  avg corr WITHIN same sector : {np.mean(within):+.3f}  (n={len(within)})")
        print(f"  avg corr ACROSS sectors     : {np.mean(across):+.3f}  (n={len(across)})")
        print("\n(PC1 is the single market bet you can't diversify away long-only.")
        print(" Residual dims are your real stock-picking breadth.)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
