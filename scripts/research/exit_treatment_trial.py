"""Exit-treatment trial: do TP/SL rules beat 'none' on the WFO-selected signal, OOS?

For each symbol, for each TA category, walk the same weekly WFO folds the signal
page uses. Per fold: pick the in-sample prominence winner (the signal the WFO
already selects), then apply each exit treatment to that winner's OOS trades.
Because the entries are identical across treatments, the OOS trade returns are
PAIRED by entry — so 'none' vs each treatment is a clean apples-to-apples test
(same signal, same costs, same folds; only the exit differs).

Scoped to a small symbol list for a fast trial. No DB writes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from core.quant_core.horizons import HORIZON_PARAMS, DEFAULT_COST_BPS_PER_SIDE
from core.quant_core.wfo.config import WalkForwardConfig
from core.quant_core.wfo.window import build_walk_forward_windows
from core.quant_core.wfo.prom import compute_prom
from core.quant_core.signal_engine.oos_eval import compute_signal_array
from core.quant_core.signal_engine.wfo_signal import build_category_candidate_grid, _variant_min_history
from core.quant_core.signal_engine.exit_barriers import (
    wilder_atr, segment_trades, simulate_exit, calibrate_k_mae_mfe,
)
# Established edge rules (verbatim) — same gate the dashboard/portfolio edge uses.
from core.quant_core.research.edge import N_MIN, WILSON_LB_THRESHOLD, bootstrap_mean_ci
from core.quant_core.research.stats.hit_rate import wilson_ci

CATEGORIES = ["tendance", "momentum", "oscillation", "volume"]
DEFAULT_SYMBOLS = ["ADH", "IAM", "MNG", "SMI", "CMT", "MSA", "AKT", "BCP", "BOA", "ATW"]

# (name, policy, k_sl, k_tp)
TREATMENTS = [
    ("none", "none", 0.0, 0.0),
    ("atr_1.5_1.5", "atr", 1.5, 1.5),
    ("atr_2.0_1.0", "atr", 2.0, 1.0),
    ("atr_3.0_1.0", "atr", 3.0, 1.0),
    ("mae_mfe", "mae_mfe", 1.5, 1.5),  # k overridden per-fold by IS calibration
]

ROUND_TRIP_COST = 2.0 * DEFAULT_COST_BPS_PER_SIDE / 10_000.0  # net each trade identically


def _all_symbols(db):
    """All symbols with stored daily price data (MarketDataStore), sorted."""
    from services.api.app import models
    rows = db.query(models.MarketDataStore.symbol).distinct().all()
    return sorted({str(r[0]).strip().upper() for r in rows if r[0]})


def _load_arrays(db, symbol):
    from services.api.app.market_data_loader import load_ohlcv_for_symbol
    df = load_ohlcv_for_symbol(db, symbol)
    if df is None or df.empty:
        return None
    cap = HORIZON_PARAMS["weekly"]["max_years"] * 252
    df = df.tail(cap)
    return (
        df["Open"].to_numpy(np.float64), df["High"].to_numpy(np.float64),
        df["Low"].to_numpy(np.float64), df["Close"].to_numpy(np.float64),
        (df["Volume"].to_numpy(np.float64) if "Volume" in df else None),
    )


def _is_winner_idx(pool, sigs, close, o, h, l, atr, win):
    """In-sample prominence winner under the 'none' signal exit (= production signal)."""
    best_idx, best_prom = -1, -np.inf
    for i, sig in enumerate(sigs):
        segs = segment_trades(sig[win.train_start:win.train_end])
        if len(segs) < 2:
            continue
        base = win.train_start
        rets = [
            simulate_exit(o, h, l, close, atr, entry_idx=base + e, direction=d,
                          natural_end_idx=base + ne, policy="none", k_sl=0, k_tp=0).gross_return
            - ROUND_TRIP_COST
            for (e, d, ne) in segs
        ]
        prom = compute_prom(rets, 1.0)
        if prom > best_prom:
            best_prom, best_idx = prom, i
    return best_idx


def run_trial(db, symbols):
    """Return {(symbol, category): {treatment: {'gross':[...], 'net':[...]}}}.

    Each (symbol, category) is one signal; its OOS trades are stitched across
    folds. The winner variant per fold is the WFO's in-sample-prominence pick
    (the production signal); only the EXIT differs per treatment.
    """
    hp = HORIZON_PARAMS["weekly"]
    config = WalkForwardConfig(train_bars=hp["train"], oos_bars=hp["test"], step_bars=hp["step"])
    signals: dict[tuple[str, str], dict[str, dict[str, list[float]]]] = {}
    n_folds = 0

    for symbol in symbols:
        arrays = _load_arrays(db, symbol)
        if arrays is None:
            print(f"  [skip] {symbol}: no OHLCV")
            continue
        o, h, l, close, vol = arrays
        atr = wilder_atr(h, l, close)
        atr_frac = np.where(close > 0, atr / close, 0.0)

        for category in CATEGORIES:
            pool = build_category_candidate_grid(category, "weekly")
            if not pool:
                continue
            max_lb = max(_variant_min_history(v) for v in pool)
            windows = build_walk_forward_windows(len(close), config, max_lookback=max_lb)
            if not windows:
                continue
            sigs = [compute_signal_array(close, v, volume=vol, high=h, low=l) for v in pool]
            acc = signals.setdefault(
                (symbol, category), {name: {"gross": [], "net": []} for name, *_ in TREATMENTS}
            )

            for win in windows:
                wi = _is_winner_idx(pool, sigs, close, o, h, l, atr, win)
                if wi < 0:
                    continue
                n_folds += 1
                sig = sigs[wi]

                # IS natural trades for MAE/MFE calibration (in-sample only)
                is_segs = segment_trades(sig[win.train_start:win.train_end])
                is_nat, is_atrfrac = [], []
                for (e, d, ne) in is_segs:
                    base = win.train_start
                    tr = simulate_exit(o, h, l, close, atr, entry_idx=base + e, direction=d,
                                       natural_end_idx=base + ne, policy="none", k_sl=0, k_tp=0)
                    is_nat.append(tr)
                    is_atrfrac.append(float(atr_frac[base + e]))
                k_cal = calibrate_k_mae_mfe(is_nat, is_atrfrac)

                # OOS entries (the winner signal), exits per treatment
                oos_segs = segment_trades(sig[win.oos_start:win.oos_end])
                base = win.oos_start
                for (e, d, ne) in oos_segs:
                    for name, policy, k_sl, k_tp in TREATMENTS:
                        if policy == "mae_mfe":
                            k_sl, k_tp = k_cal
                        tr = simulate_exit(o, h, l, close, atr, entry_idx=base + e, direction=d,
                                           natural_end_idx=base + ne, policy=policy,
                                           k_sl=k_sl, k_tp=k_tp)
                        acc[name]["gross"].append(tr.gross_return)
                        acc[name]["net"].append(tr.gross_return - ROUND_TRIP_COST)

    return signals, n_folds


def classify_edge(gross: list[float], net: list[float]) -> dict:
    """Apply the established edge rules (N_MIN, Wilson LB, bootstrap net LB)."""
    g = np.asarray(gross, dtype=np.float64)
    narr = np.asarray(net, dtype=np.float64)
    n = len(narr)
    if n == 0:
        return dict(triage="insufficient", n=0, hit=0.0, er_net=0.0, score=0.0)
    hits = int(np.sum(g > 0.0))
    hit_rate = hits / n
    wl, _ = wilson_ci(hits, n)
    nlo, _ = bootstrap_mean_ci(narr)
    gate_n = n >= N_MIN
    gate_wilson = wl > WILSON_LB_THRESHOLD
    gate_net = nlo is not None and float(nlo) > 0.0
    proven = gate_n and gate_wilson and gate_net
    triage = "proven" if proven else ("insufficient" if not gate_n else "watch")
    score = float(nlo) if nlo is not None else float(narr.mean())
    return dict(triage=triage, n=n, hit=hit_rate, er_net=float(narr.mean()), score=score)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--out", default="results/exit_treatment_trial")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    from services.api.app.db import _ensure_session_factory
    db = _ensure_session_factory()()
    try:
        if args.symbols.strip().lower() == "all":
            symbols = _all_symbols(db)
        else:
            symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        print(f"Exit-treatment trial — {len(symbols)} symbols, weekly, categories={CATEGORIES}")
        signals, n_folds = run_trial(db, symbols)
    finally:
        db.close()

    n_sig = len(signals)
    lines = ["# Exit-Treatment Trial — edge counts & quality per treatment", ""]
    lines.append(f"Symbols: {', '.join(symbols)}")
    lines.append(f"Signals (symbol×category): {n_sig}  |  Folds evaluated: {n_folds}")
    lines.append(f"Edge rule: n≥{N_MIN}, Wilson hit-LB>{WILSON_LB_THRESHOLD}, bootstrap net-LB>0 "
                 f"(proven); n≥{N_MIN} only → watch; else insufficient")
    lines.append(f"Cost: {DEFAULT_COST_BPS_PER_SIDE} bps/side = {ROUND_TRIP_COST*10000:.0f} bps round-trip, all treatments")
    lines.append("")
    lines.append("Only signals WITH an edge (proven+watch) are summarised for quality.")
    lines.append("")
    lines.append("| Treatment | #Proven | #Watch | #Edged | Edged mean net ER | Edged mean hit% | Edged mean score |")
    lines.append("|-----------|---------|--------|--------|-------------------|-----------------|------------------|")

    detail: dict[str, list] = {}
    for name, *_ in TREATMENTS:
        classes = [classify_edge(acc[name]["gross"], acc[name]["net"]) for acc in signals.values()]
        proven = [c for c in classes if c["triage"] == "proven"]
        watch = [c for c in classes if c["triage"] == "watch"]
        edged = proven + watch
        detail[name] = classes
        if edged:
            er = np.mean([c["er_net"] for c in edged])
            hr = np.mean([c["hit"] for c in edged])
            sc = np.mean([c["score"] for c in edged])
            lines.append(f"| {name} | {len(proven)} | {len(watch)} | {len(edged)} | "
                         f"{er:+.4f} | {hr:.1%} | {sc:+.4f} |")
        else:
            lines.append(f"| {name} | 0 | 0 | 0 | — | — | — |")
    lines.append("")
    lines.append("**#Proven** = signals that clear the full edge gate; **#Edged** = proven+watch.")
    lines.append("Question: does any exit treatment yield MORE / STRONGER edged signals than `none`?")

    report = "\n".join(lines)
    print("\n" + report)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(report, encoding="utf-8")
    print(f"\nReport: {out / 'report.md'}")


if __name__ == "__main__":
    main()
