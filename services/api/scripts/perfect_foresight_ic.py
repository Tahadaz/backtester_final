"""Perfect-foresight IC study for forward-estimate seeding (Brief 54 follow-up, doc 55).

Question: would the forward-NI/forward-revenue seeding of the intrinsic models
(ddm, residual_income, fcff_dcf) have produced positive cross-sectional IC
against 12-month forward returns, IF the seed had been perfectly accurate?

Design
------
Reuses the exact machinery of core/quant_core/fundamentals/pit_ic_backtest.py
(PIT statement filter, PIT snapshot construction, PIT prices, survivorship-free
universe, Spearman IC + Newey-West aggregation).  For each (symbol, T):

  arm A (baseline): compute_symbol_valuations() with default assumptions —
      byte-for-byte the same call the existing PIT IC backtest makes.
  arm B (seeded):   same call, plus the three assumptions-dict keys the live
      consensus path injects (services/api/app/services/fundamentals.py →
      consensus.load_forward_view):
          forward_net_income  = REALIZED NetIncome  for fiscal year L+1
          forward_revenue     = REALIZED Revenue    for fiscal year L+1
          forward_fiscal_year = L + 1
      where L = latest PIT statement year (mirrors the live anchor
      _fwd_year = latest_statement_year + 1).  Realized values are read from
      the FULL statement history — deliberately unknowable at T.  This is the
      ONLY foresight injection; statements, prices, peers stay strictly PIT.

Pairing discipline: a (symbol, T, model) pair enters the IC computation only
if BOTH arms produced a finite, non-"unavailable" upside.  A symbol enters a
period only if a realized forward NI > 0 exists (the seed cannot fire
otherwise; see projection.py `_fwd_ni_seeded`).

Honesty: ~5 annual periods only. No parameter fitting, no optimization.

Usage:
  .venv/Scripts/python.exe services/api/scripts/perfect_foresight_ic.py \
      [--years 2020 2021 2022 2023 2024] [--json out.json]

DB access is READ-ONLY (SELECTs via pit_ic_backtest loaders).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DB_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"
os.environ.setdefault("DATABASE_URL", DEFAULT_DB_URL)
# Host-side MinIO defaults (infra/docker-compose.yml quant_minio service)
os.environ.setdefault("S3_ENDPOINT_URL", "http://127.0.0.1:9000")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "minio")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "minio12345")
os.environ.setdefault("S3_BUCKET", "quant-artifacts")

from core.quant_core.fundamentals import pit_ic_backtest as pit  # noqa: E402
from core.quant_core.fundamentals.projection import (  # noqa: E402
    NET_INCOME_ALIASES,
    REVENUE_ALIASES,
    _pick_best_row_per_year,
)
from core.quant_core.fundamentals.valuation import compute_symbol_valuations  # noqa: E402
from core.quant_core.research.stats.ic import _newey_west_var, _spearman_corr  # noqa: E402

MODELS = ("ddm", "residual_income", "fcff_dcf", "relative_multiples")
SEED_AFFECTED = {"ddm", "residual_income", "fcff_dcf"}


def _realized(history, aliases, year: int) -> float | None:
    """Realized (full-history, non-PIT) metric value for one fiscal year.

    Uses projection.py's _pick_best_row_per_year so alias resolution and
    mis-scaled-twin rejection match what the projection itself would consume.
    """
    row = _pick_best_row_per_year(history, aliases).get(year)
    if row is None or row.metric_value is None:
        return None
    v = float(row.metric_value)
    return v if math.isfinite(v) else None


def _upsides_for_arm(snap, pit_hist, peers, sector_map, assumptions) -> tuple[dict[str, float], bool]:
    """Run compute_symbol_valuations for one arm.

    Returns ({model: upside_pct}, seeded_flag_fired).
    """
    eligibility, results = compute_symbol_valuations(
        snapshot=snap,
        history=pit_hist,
        peer_snapshots=peers,
        sectors=sector_map,
        assumptions=assumptions,
        scenario="base",
    )
    proj_warnings = (eligibility.get("projection") or {}).get("warnings") or []
    seeded_fired = "net_income_forward_seeded" in [str(w) for w in proj_warnings]
    upsides: dict[str, float] = {}
    for r in results:
        if r.model not in MODELS:
            continue
        if r.upside_pct is None or not math.isfinite(r.upside_pct):
            continue
        if r.confidence == "unavailable":
            continue
        upsides[r.model] = float(r.upside_pct)
    return upsides, seeded_fired


def run_study(as_of_years: list[int], verbose: bool = True) -> dict:
    universe_df = pd.read_csv(pit.UNIVERSE_PATH)

    print("Loading fundamental data from DB...", flush=True)
    all_rows = pit._load_rows_from_db()
    print(f"Loaded {len(all_rows):,} annual metric rows.", flush=True)
    sectors = pit._load_sectors_from_db()
    price_loader = pit._build_price_loader()

    rows_by_symbol: dict[str, list] = defaultdict(list)
    for row in all_rows:
        rows_by_symbol[row.symbol].append(row)

    universe_by_symbol = {
        str(r["symbol"]).strip().upper(): r
        for _, r in universe_df.iterrows()
        if pd.notna(r.get("symbol"))
    }

    prices_cache: dict = {}

    def get_prices(sym):
        if sym not in prices_cache:
            prices_cache[sym] = price_loader(sym)
        return prices_cache[sym]

    # (model, arm) -> {year: [(upside, fwd_return)]}
    paired: dict[tuple[str, str], dict[int, list[tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    stats = {
        "skipped_no_realized_fwd_ni": 0,
        "skipped_nonpositive_fwd_ni": 0,
        "seed_flag_fired": 0,
        "seed_flag_missing": 0,
        "symbols_seeded_by_year": defaultdict(int),
    }

    for as_of_year in sorted(as_of_years):
        as_of_date = dt.date(as_of_year, 12, 31)
        fwd_date = dt.date(as_of_year + 1, 12, 31)
        if verbose:
            print(f"\n=== as_of_year={as_of_year} (as-of {as_of_date}, forward {fwd_date}) ===", flush=True)

        live_symbols = [
            sym for sym, uni_row in universe_by_symbol.items()
            if sym in rows_by_symbol and pit._is_live(uni_row, as_of_date)
        ]

        # PIT snapshots (identical to pit_ic_backtest.run_pilot step 2)
        pit_snapshots: dict = {}
        pit_histories: dict = {}
        for sym in live_symbols:
            sym_rows = rows_by_symbol[sym]
            pit_hist = pit._filter_pit_history(sym_rows, as_of_year, sym)
            if not pit_hist:
                continue
            prices = get_prices(sym)
            price = pit._pit_close(prices, as_of_date)
            if price is None:
                continue
            snap = pit._build_pit_snapshot(
                symbol=sym,
                company_name=sym_rows[0].company_name,
                pit_history=pit_hist,
                price=price,
                as_of_year=as_of_year,
            )
            pit_snapshots[sym] = snap
            pit_histories[sym] = pit_hist

        valid_symbols = list(pit_snapshots.keys())
        if verbose:
            print(f"  Live: {len(live_symbols)}  valid (price+fundamentals): {len(valid_symbols)}", flush=True)
        if not valid_symbols:
            continue

        peer_list = list(pit_snapshots.values())
        n_period_pairs = 0

        for sym in valid_symbols:
            snap = pit_snapshots[sym]
            pit_hist = pit_histories[sym]
            full_hist = rows_by_symbol[sym]
            peers = [s for s in peer_list if s.symbol != sym]

            # Forward return (identical to pit_ic_backtest)
            prices = get_prices(sym)
            pit_price = snap.metrics.get("Current_Price")
            fwd_price = pit._pit_close(prices, fwd_date)
            if fwd_price is None or not pit_price or pit_price <= 0:
                continue
            fwd_return = fwd_price / float(pit_price) - 1.0

            # Foresight seed: realized L+1 values, L = latest PIT statement year
            latest_year = snap.latest_statement_year
            if latest_year is None:
                continue
            fwd_fy = int(latest_year) + 1
            realized_ni = _realized(full_hist, NET_INCOME_ALIASES, fwd_fy)
            realized_rev = _realized(full_hist, REVENUE_ALIASES, fwd_fy)
            if realized_ni is None:
                stats["skipped_no_realized_fwd_ni"] += 1
                continue
            if realized_ni <= 0:
                # projection's _fwd_ni_seeded requires _fwd_ni > 0; seed cannot fire
                stats["skipped_nonpositive_fwd_ni"] += 1
                continue

            seed_assumptions: dict = {
                "forward_net_income": realized_ni,
                "forward_fiscal_year": fwd_fy,
            }
            if realized_rev is not None and realized_rev > 0:
                seed_assumptions["forward_revenue"] = realized_rev

            # Suppress metric_resolver stderr-noise duplication in output
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    base_upsides, _ = _upsides_for_arm(snap, pit_hist, peers, sectors, None)
                    seed_upsides, seed_fired = _upsides_for_arm(
                        snap, pit_hist, peers, sectors, seed_assumptions
                    )
            except Exception as exc:
                if verbose:
                    print(f"    SKIP {sym}: valuation error: {exc}", flush=True)
                continue

            if seed_fired:
                stats["seed_flag_fired"] += 1
                stats["symbols_seeded_by_year"][as_of_year] += 1
            else:
                stats["seed_flag_missing"] += 1

            # Paired discipline: keep model only if BOTH arms produced it
            for model in MODELS:
                if model in base_upsides and model in seed_upsides:
                    paired[(model, "baseline")][as_of_year].append(
                        (base_upsides[model], fwd_return)
                    )
                    paired[(model, "seeded")][as_of_year].append(
                        (seed_upsides[model], fwd_return)
                    )
                    n_period_pairs += 1

        if verbose:
            print(
                f"  Symbols seeded (flag fired): {stats['symbols_seeded_by_year'][as_of_year]}"
                f"  paired model-stock rows: {n_period_pairs}",
                flush=True,
            )

    # ── IC aggregation (mirrors pit_ic_backtest._compute_cross_sectional_ic) ──
    def aggregate(period_data: dict[int, list[tuple[float, float]]]) -> dict:
        per_period: dict[int, float] = {}
        pair_counts: dict[int, int] = {}
        for year in sorted(period_data):
            pairs = period_data[year]
            if len(pairs) < 5:  # same thinness cutoff as pit_ic_backtest
                continue
            ic = _spearman_corr(
                pd.Series([p[0] for p in pairs], dtype=float),
                pd.Series([p[1] for p in pairs], dtype=float),
            )
            if math.isfinite(ic):
                per_period[year] = float(ic)
                pair_counts[year] = len(pairs)
        n = len(per_period)
        out = {
            "periods": n,
            "pairs": sum(pair_counts.values()),
            "per_period_ic": {str(y): round(v, 4) for y, v in per_period.items()},
            "per_period_pairs": {str(y): c for y, c in pair_counts.items()},
            "mean_IC": float("nan"),
            "IC_std": float("nan"),
            "t_stat": float("nan"),
        }
        if n == 0:
            return out
        arr = np.array(list(per_period.values()), dtype=float)
        mean_ic = float(np.mean(arr))
        ic_std = float(np.std(arr, ddof=1)) if n > 1 else float("nan")
        nw_var = _newey_west_var(arr) if n >= 3 else None
        if nw_var is not None and math.isfinite(nw_var) and nw_var > 0:
            t = mean_ic / math.sqrt(nw_var)
        elif n > 1 and math.isfinite(ic_std) and ic_std > 0:
            t = mean_ic / (ic_std / math.sqrt(n))
        else:
            t = float("nan")
        out.update(
            mean_IC=round(mean_ic, 4),
            IC_std=round(ic_std, 4) if math.isfinite(ic_std) else float("nan"),
            t_stat=round(t, 3) if math.isfinite(t) else float("nan"),
        )
        return out

    results: dict = {"as_of_years": sorted(as_of_years), "models": {}, "diagnostics": {}}
    for model in MODELS:
        base = aggregate(paired[(model, "baseline")])
        seed = aggregate(paired[(model, "seeded")])
        # Paired per-period IC delta (seeded - baseline), same periods only
        deltas = {
            y: round(seed["per_period_ic"][y] - base["per_period_ic"][y], 4)
            for y in seed["per_period_ic"]
            if y in base["per_period_ic"]
        }
        pos = sum(1 for v in seed["per_period_ic"].values() if v > 0)
        results["models"][model] = {
            "baseline": base,
            "seeded": seed,
            "ic_delta_per_period": deltas,
            "mean_ic_delta": round(float(np.mean(list(deltas.values()))), 4) if deltas else None,
            "seeded_positive_periods": f"{pos}/{len(seed['per_period_ic'])}",
        }

    stats["symbols_seeded_by_year"] = dict(stats["symbols_seeded_by_year"])
    results["diagnostics"] = stats

    # ── console report ──
    hdr = (
        f"{'model':<20} {'arm':<9} {'periods':>7} {'pairs':>6} "
        f"{'mean_IC':>8} {'IC_std':>7} {'t_stat':>7}  per-period IC"
    )
    print("\n" + hdr)
    print("-" * len(hdr))
    for model in MODELS:
        m = results["models"][model]
        for arm in ("baseline", "seeded"):
            a = m[arm]
            pp = "  ".join(f"{y}:{v:+.3f}" for y, v in sorted(a["per_period_ic"].items()))
            mic = a["mean_IC"]
            std = a["IC_std"]
            ts = a["t_stat"]
            print(
                f"{model:<20} {arm:<9} {a['periods']:>7} {a['pairs']:>6} "
                f"{mic if math.isfinite(mic) else float('nan'):>8.4f} "
                f"{std if math.isfinite(std) else float('nan'):>7.4f} "
                f"{ts if math.isfinite(ts) else float('nan'):>7.3f}  {pp}"
            )
        print(
            f"{'':<20} {'delta':<9} {'':>7} {'':>6} "
            f"{(m['mean_ic_delta'] if m['mean_ic_delta'] is not None else float('nan')):>8.4f}"
            f"{'':>7} {'':>7}  seeded>0 in {m['seeded_positive_periods']} periods"
        )
        print()
    print(f"Diagnostics: {json.dumps(stats, indent=2)}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Perfect-foresight seeding IC study (doc 55)")
    parser.add_argument("--years", nargs="+", type=int, default=[2020, 2021, 2022, 2023, 2024])
    parser.add_argument("--json", type=str, default=None, help="write raw results JSON here")
    args = parser.parse_args()

    results = run_study(args.years)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)

        def _clean(o):
            if isinstance(o, float) and not math.isfinite(o):
                return None
            if isinstance(o, dict):
                return {k: _clean(v) for k, v in o.items()}
            if isinstance(o, list):
                return [_clean(v) for v in o]
            return o

        out.write_text(json.dumps(_clean(results), indent=2), encoding="utf-8")
        print(f"\nResults JSON written to {out}")


if __name__ == "__main__":
    main()
