#!/usr/bin/env python3
"""Sensitivity sweep for the composite-score metric weights (0.40/0.30/0.20/0.10).

QUESTION THIS ANSWERS
---------------------
The per-category composite score is:

    composite = 0.40*WFE_n + 0.30*robustness_n + 0.20*Sharpe_n + 0.10*DD_n

Those four coefficients are unjustified magic numbers. This script measures
whether they actually *matter*: if we wobble them, do the dashboard's
consequential outputs (signal DIRECTION, recommendation bucket, best category,
global score) move? If they barely move, the constants are harmless and we
leave them. If they move a lot, we have a real fragility to fix.

WHAT IT MEASURES (and does NOT)
-------------------------------
It re-derives, per symbol, the full chain that depends on the metric weights:
    metric weights -> per-category composite -> category assembly weights
    -> raw global score -> global score (x stored S/R modifier) -> recommendation
using the per-category metrics already persisted in wfo_signal_summary.

It does NOT re-run backtests, so it does not measure realized OOS portfolio
return. That is deliberate: this is the cheap "do they even matter" screen.
If outputs here are sensitive, escalate to a return-based (Level 3) test.

It changes NOTHING in the app or DB. Read-only. Stdlib only. Pulls data through
the running postgres container via `docker exec ... psql --csv`.

USAGE
-----
    python analysis/composite_weight_sensitivity.py
    python analysis/composite_weight_sensitivity.py --horizon weekly --variant expanded_ta_simple --n 2000
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import random
import statistics
import subprocess
import sys
from dataclasses import dataclass

PG_CONTAINER = "infra-quant_postgres-1"
PG_USER = "app"
PG_DB = "quant"

CATEGORIES = ("tendance", "momentum", "oscillation", "volume")
BASELINE = (0.40, 0.30, 0.20, 0.10)  # (wfe, robustness, sharpe, dd)
METRIC_NAMES = ("wfe", "robustness", "sharpe", "dd")


# --------------------------------------------------------------------------
# Data access (read-only, via the running postgres container)
# --------------------------------------------------------------------------
def _psql_csv(query: str) -> list[dict[str, str]]:
    proc = subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", PG_USER, "-d", PG_DB,
         "--csv", "-t", "-A", "-F", ",", "-c", query],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"psql failed (exit {proc.returncode})")
    reader = csv.reader(io.StringIO(proc.stdout))
    return list(reader)


@dataclass
class CatMetrics:
    category: str
    score_pct: float
    wfe: float            # already /100, raw (pre-clamp)
    robustness: float
    sharpe: float         # raw mean_oos_sharpe (pre /2, pre-clamp)
    dd: float             # raw worst_fold_drawdown (negative), pre-transform


def load_symbols(horizon: str, variant: str) -> dict[str, list[CatMetrics]]:
    rows = _psql_csv(
        f"""
        SELECT symbol, category, score_pct, wfe_pct, robustness_ratio,
               mean_oos_sharpe, worst_fold_drawdown
        FROM wfo_signal_summary
        WHERE horizon = '{horizon}' AND variant = '{variant}'
              AND status = 'succeeded'
        ORDER BY symbol, category
        """
    )
    out: dict[str, list[CatMetrics]] = {}
    for r in rows:
        if len(r) < 7 or not r[0]:
            continue
        symbol = r[0]
        try:
            cm = CatMetrics(
                category=r[1],
                score_pct=float(r[2] or 0.0),
                wfe=float(r[3] or 0.0) / 100.0,
                robustness=float(r[4] or 0.0),
                sharpe=float(r[5] or 0.0),
                dd=float(r[6] or 0.0),
            )
        except ValueError:
            continue
        out.setdefault(symbol, []).append(cm)
    return out


def load_sr_modifiers(horizon: str, variant: str) -> dict[str, float]:
    rows = _psql_csv(
        f"""
        SELECT symbol, sr_modifier
        FROM wfo_global_signal
        WHERE horizon = '{horizon}' AND variant = '{variant}' AND status = 'succeeded'
        """
    )
    mods: dict[str, float] = {}
    for r in rows:
        if len(r) < 2 or not r[0]:
            continue
        try:
            mods[r[0]] = float(r[1]) if r[1] not in ("", None) else 1.0
        except ValueError:
            mods[r[0]] = 1.0
    return mods


# --------------------------------------------------------------------------
# The chain under test (parametrized copy of the production formula)
# --------------------------------------------------------------------------
def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def composite(cm: CatMetrics, w: tuple[float, float, float, float]) -> float:
    wfe_n = _clamp01(cm.wfe)
    rob_n = _clamp01(cm.robustness)
    shp_n = _clamp01(cm.sharpe / 2.0)
    dd_n = _clamp01(1.0 - abs(cm.dd))
    return (w[0] * wfe_n + w[1] * rob_n + w[2] * shp_n + w[3] * dd_n) * 100.0


def recommendation(score: float) -> str:
    if score > 50:
        return "achat_fort"
    if score > 15:
        return "achat"
    if score >= -15:
        return "neutre"
    if score >= -50:
        return "vente"
    return "vente_forte"


@dataclass
class Outcome:
    weights: dict[str, float]   # category assembly weights
    best_category: str
    raw_score: float
    global_score: float
    direction: int              # sign of global score
    recommendation: str


def evaluate(cats: list[CatMetrics], sr_mod: float,
             w: tuple[float, float, float, float]) -> Outcome:
    comps = {c.category: composite(c, w) for c in cats}
    total = sum(comps.values())
    if total <= 0:
        cat_w = {c.category: 1.0 / len(cats) for c in cats}
    else:
        cat_w = {cat: v / total for cat, v in comps.items()}
    raw = sum(cat_w[c.category] * c.score_pct for c in cats)
    gscore = max(-100.0, min(100.0, raw * sr_mod))
    best = max(comps, key=lambda k: comps[k])
    return Outcome(
        weights=cat_w,
        best_category=best,
        raw_score=raw,
        global_score=gscore,
        direction=(1 if gscore > 0 else (-1 if gscore < 0 else 0)),
        recommendation=recommendation(gscore),
    )


def weight_l1(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    return sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys)


# --------------------------------------------------------------------------
# Perturbation generators
# --------------------------------------------------------------------------
def dirichlet(alpha: tuple[float, ...], rng: random.Random) -> tuple[float, ...]:
    gammas = [rng.gammavariate(a, 1.0) if a > 0 else 0.0 for a in alpha]
    s = sum(gammas) or 1.0
    return tuple(g / s for g in gammas)


def named_schemes() -> dict[str, tuple[float, float, float, float]]:
    return {
        "baseline (.40/.30/.20/.10)": BASELINE,
        "equal (.25 x4)": (0.25, 0.25, 0.25, 0.25),
        "reversed (.10/.20/.30/.40)": (0.10, 0.20, 0.30, 0.40),
        "WFE-only": (1.0, 0.0, 0.0, 0.0),
        "robustness-only": (0.0, 1.0, 0.0, 0.0),
        "sharpe-only": (0.0, 0.0, 1.0, 0.0),
        "dd-only": (0.0, 0.0, 0.0, 1.0),
        "WFE+rob (.5/.5)": (0.5, 0.5, 0.0, 0.0),
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def summarize(values: list[float]) -> str:
    if not values:
        return "n/a"
    vs = sorted(values)
    mean = statistics.fmean(vs)
    p95 = vs[min(len(vs) - 1, int(0.95 * len(vs)))]
    return f"mean={mean:6.2f}  p95={p95:6.2f}  max={vs[-1]:6.2f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", default="weekly")
    ap.add_argument("--variant", default="expanded_ta_simple")
    ap.add_argument("--n", type=int, default=2000, help="Dirichlet samples")
    ap.add_argument("--conc", type=float, default=40.0,
                    help="Dirichlet concentration (higher = tighter wobble around baseline)")
    ap.add_argument("--seed", type=int, default=12345)
    args = ap.parse_args()

    rng = random.Random(args.seed)

    data = load_symbols(args.horizon, args.variant)
    mods = load_sr_modifiers(args.horizon, args.variant)
    # Production builds the global scope only when >=2 succeeded categories exist.
    symbols = {s: c for s, c in data.items() if len(c) >= 2}

    print("=" * 78)
    print(f"COMPOSITE METRIC-WEIGHT SENSITIVITY  ({args.horizon} / {args.variant})")
    print("=" * 78)
    print(f"symbols with >=2 succeeded categories: {len(symbols)}  "
          f"(of {len(data)} with any)")
    print(f"baseline metric weights (wfe/rob/sharpe/dd): {BASELINE}")
    print()

    if not symbols:
        print("No symbols to evaluate. Has WFO finished for this horizon/variant?")
        return

    baselines = {s: evaluate(cats, mods.get(s, 1.0), BASELINE)
                 for s, cats in symbols.items()}

    # ---- Part 1: named alternative schemes (worst-case bounds) ----
    print("-" * 78)
    print("PART 1 - named alternative weightings  (flip rates vs baseline)")
    print("-" * 78)
    print(f"{'scheme':<30} {'dir-flip':>9} {'rec-flip':>9} {'bestcat':>9} "
          f"{'|dscore|':>16}")
    for name, w in named_schemes().items():
        dir_flips = rec_flips = cat_flips = 0
        dscores: list[float] = []
        for s, cats in symbols.items():
            o = evaluate(cats, mods.get(s, 1.0), w)
            b = baselines[s]
            dir_flips += (o.direction != b.direction)
            rec_flips += (o.recommendation != b.recommendation)
            cat_flips += (o.best_category != b.best_category)
            dscores.append(abs(o.global_score - b.global_score))
        n = len(symbols)
        print(f"{name:<30} {pct(dir_flips/n):>9} {pct(rec_flips/n):>9} "
              f"{pct(cat_flips/n):>9}   {summarize(dscores)}")

    # ---- Part 2: Dirichlet wobble around baseline (realistic uncertainty) ----
    print()
    print("-" * 78)
    print(f"PART 2 - Dirichlet wobble around baseline  "
          f"(n={args.n}, conc={args.conc})")
    print("-" * 78)
    alpha = tuple(c * args.conc for c in BASELINE)

    per_symbol_dir_flip: list[float] = []
    per_symbol_rec_flip: list[float] = []
    per_symbol_cat_flip: list[float] = []
    per_symbol_score_std: list[float] = []
    per_symbol_wdrift: list[float] = []

    for s, cats in symbols.items():
        b = baselines[s]
        dirf = recf = catf = 0
        scores: list[float] = []
        wdrifts: list[float] = []
        for _ in range(args.n):
            w = dirichlet(alpha, rng)
            o = evaluate(cats, mods.get(s, 1.0), w)
            dirf += (o.direction != b.direction)
            recf += (o.recommendation != b.recommendation)
            catf += (o.best_category != b.best_category)
            scores.append(o.global_score)
            wdrifts.append(weight_l1(o.weights, b.weights))
        per_symbol_dir_flip.append(dirf / args.n)
        per_symbol_rec_flip.append(recf / args.n)
        per_symbol_cat_flip.append(catf / args.n)
        per_symbol_score_std.append(statistics.pstdev(scores) if len(scores) > 1 else 0.0)
        per_symbol_wdrift.append(statistics.fmean(wdrifts))

    def agg(label: str, vals: list[float], as_pct: bool) -> None:
        mean = statistics.fmean(vals)
        worst = max(vals)
        share = sum(1 for v in vals if v > 0.05) / len(vals)  # > 5% of draws
        if as_pct:
            print(f"  {label:<34} avg/symbol={pct(mean)}   worst symbol={pct(worst)}"
                  f"   symbols>5%: {pct(share)}")
        else:
            print(f"  {label:<34} avg/symbol={mean:6.3f}   worst symbol={worst:6.3f}")

    print("Per-draw probability that a wobble changes the output, averaged over symbols:")
    agg("direction flip (buy<->sell)", per_symbol_dir_flip, True)
    agg("recommendation bucket flip", per_symbol_rec_flip, True)
    agg("best-category flip", per_symbol_cat_flip, True)
    print()
    print("Dispersion of the global score under wobble:")
    print(f"  global-score std (points)          {summarize(per_symbol_score_std)}")
    print(f"  category-weight L1 drift           {summarize(per_symbol_wdrift)}")

    # ---- Verdict heuristic ----
    print()
    print("=" * 78)
    print("VERDICT (heuristic)")
    print("=" * 78)
    mean_dir = statistics.fmean(per_symbol_dir_flip)
    mean_rec = statistics.fmean(per_symbol_rec_flip)
    worst_dir = max(per_symbol_dir_flip)
    if mean_dir < 0.02 and mean_rec < 0.10:
        print("LOW sensitivity. Direction is stable under realistic wobble; the")
        print("0.40/0.30/0.20/0.10 constants are low-stakes. Document them as a")
        print("deliberate prior and move on - the edge is elsewhere (TP/SL, sizing).")
    elif mean_dir < 0.05:
        print("MODERATE sensitivity. Direction mostly stable but recommendation")
        print("buckets shift. Worth a learned/shrunk weighting later, not urgent.")
    else:
        print("HIGH sensitivity. Direction flips materially under wobble")
        print(f"(avg {pct(mean_dir)}/draw, worst symbol {pct(worst_dir)}).")
        print("Escalate to a return-based (Level 3) test and fix the weighting.")
    print()
    print("NOTE: this screen measures signal/recommendation stability, not realized")
    print("OOS return. A 'LOW' verdict means the constants don't change what the")
    print("dashboard tells you to do - which is the decision that matters.")


if __name__ == "__main__":
    main()
