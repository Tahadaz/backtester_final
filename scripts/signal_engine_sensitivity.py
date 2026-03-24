"""Sensitivity analysis for signal engine funnel thresholds.

Runs the pipeline on a given stock/horizon with baseline thresholds,
then re-runs with each threshold perturbed +/-20% (one at a time).
Reports whether the final family scores are stable or fragile.

Usage:
    python scripts/signal_engine_sensitivity.py
    python scripts/signal_engine_sensitivity.py --csv path/to/IAM.csv --horizon short --cost-bps 33
    python scripts/signal_engine_sensitivity.py --lookback-years 5
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Ensure repo root is importable
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent
IMPORT_ROOTS = (REPO_ROOT, REPO_ROOT / "core")
for import_root in reversed(IMPORT_ROOTS):
    import_root_str = str(import_root)
    if import_root_str not in sys.path:
        sys.path.insert(0, import_root_str)

DEFAULT_DATA_PATH = SCRIPT_DIR / "IAM.xlsx"

from core.quant_core.signal_engine.candidates import generate_candidates
from core.quant_core.signal_engine.domain import HORIZON_PARAMS
from core.quant_core.signal_engine.oos_eval import evaluate_variant_oos
from core.quant_core.signal_engine.robustness import score_variant_robustness
from core.quant_core.signal_engine.survivor import filter_survivors
from core.quant_core.signal_engine.redundancy import reduce_redundancy
from core.quant_core.signal_engine.current_signal import compute_current_signals
from core.quant_core.signal_engine.ensemble import combine_family_signals


# ---------------------------------------------------------------------------
# Core: run pipeline with configurable thresholds
# ---------------------------------------------------------------------------

@dataclass
class ThresholdSet:
    """All tuneable thresholds in one place."""
    min_fraction_positive: float = 0.40
    min_competitive_score: float = 0.25
    competitive_percentile: float = 0.40
    max_corr: float = 0.85
    cost_bps: float = 33.0


@dataclass
class PipelineResult:
    """Compact summary of one pipeline run."""
    family: str
    score: float
    label: str
    n_viable: int
    n_competitive: int
    n_representatives: int
    representative_ids: list[str]


def run_pipeline_with_thresholds(
    family: str,
    close: np.ndarray,
    horizon: str,
    ts: ThresholdSet,
    *,
    volume: np.ndarray | None = None,
) -> PipelineResult:
    """Run the A->G pipeline with custom thresholds, return compact result."""

    # Truncate to horizon window
    hp = HORIZON_PARAMS[horizon]
    max_bars = hp["max_years"] * 252
    if len(close) > max_bars:
        close = close[-max_bars:]
        if volume is not None:
            volume = volume[-max_bars:]

    min_bars = hp["train"] + hp["test"] + 1
    if len(close) < min_bars:
        return PipelineResult(family, 0.0, "NEUTRAL", 0, 0, 0, [])

    # Layer A
    candidates = generate_candidates(family, horizon)

    # Layer B + C (with custom min_fraction_positive via viability override)
    summaries = []
    for c in candidates:
        windows = evaluate_variant_oos(close, c, horizon, ts.cost_bps, volume=volume)
        summary = score_variant_robustness(c, windows)

        # Re-apply viability gate with custom threshold
        valid = [w for w in windows if w.is_valid]
        n_valid = len(valid)
        frac_pos = sum(1 for w in valid if w.sharpe > 0) / n_valid if n_valid else 0.0
        if n_valid < 3 or frac_pos < ts.min_fraction_positive:
            # Override viability
            summary.is_viable = False
            summary.reliability_score = 0.0

        summaries.append(summary)

    n_viable = sum(1 for s in summaries if s.is_viable)

    # Layer D (with custom thresholds)
    survivors = filter_survivors(
        summaries,
        competitive_percentile=ts.competitive_percentile,
        min_competitive_score=ts.min_competitive_score,
    )
    n_competitive = len(survivors)

    if not survivors:
        return PipelineResult(family, 0.0, "NEUTRAL", n_viable, 0, 0, [])

    # Layer E (with custom max_corr)
    representatives, _, _ = reduce_redundancy(
        survivors, close, volume=volume, max_corr=ts.max_corr,
    )

    # Layer F + G
    current_signals = compute_current_signals(representatives, close, volume=volume)
    score_pct, label, _ = combine_family_signals(current_signals)

    rep_ids = [r.variant.variant_id for r in representatives]
    return PipelineResult(family, round(score_pct, 2), label, n_viable, n_competitive,
                          len(representatives), rep_ids)


# ---------------------------------------------------------------------------
# Sensitivity analysis
# ---------------------------------------------------------------------------

FAMILIES = ["sma", "rsi", "macd", "obv"]

PERTURBATIONS = {
    "min_fraction_positive": (-0.20, +0.20),
    "min_competitive_score": (-0.20, +0.20),
    "competitive_percentile": (-0.20, +0.20),
    "max_corr": (-0.20, +0.20),
    "cost_bps": (-0.20, +0.20),
}


def classify_delta(delta: float) -> str:
    """Classify score delta as STABLE, MODERATE, or SENSITIVE."""
    d = abs(delta)
    if d < 5:
        return "STABLE"
    if d < 15:
        return "MODERATE"
    return "SENSITIVE"


def run_sensitivity(
    close: np.ndarray,
    horizon: str,
    cost_bps: float,
    *,
    volume: np.ndarray | None = None,
) -> None:
    """Run full sensitivity analysis and print results."""

    baseline_ts = ThresholdSet(cost_bps=cost_bps)

    # --- Baseline ---
    print("=" * 78)
    print("BASELINE RESULTS")
    print(f"  Horizon: {horizon} | Cost: {cost_bps} bps | Bars: {len(close)}")
    print(f"  Thresholds: frac_pos={baseline_ts.min_fraction_positive}, "
          f"min_score={baseline_ts.min_competitive_score}, "
          f"percentile={baseline_ts.competitive_percentile}, "
          f"max_corr={baseline_ts.max_corr}")
    print("=" * 78)

    baselines: dict[str, PipelineResult] = {}
    for fam in FAMILIES:
        result = run_pipeline_with_thresholds(fam, close, horizon, baseline_ts,
                                               volume=volume)
        baselines[fam] = result
        print(f"  {fam:>5s}: score={result.score:+7.2f}  label={result.label:<12s}  "
              f"viable={result.n_viable:2d}  competitive={result.n_competitive:2d}  "
              f"reps={result.n_representatives:2d}")

    # Aggregate
    agg_baseline = sum(r.score for r in baselines.values()) / len(baselines)
    print(f"\n  AGGREGATE: {agg_baseline:+.2f}")

    # --- Perturbations ---
    print("\n" + "=" * 78)
    print("SENSITIVITY ANALYSIS (each threshold perturbed +/-20%)")
    print("=" * 78)

    for param_name, (lo_pct, hi_pct) in PERTURBATIONS.items():
        base_val = getattr(baseline_ts, param_name)

        for direction, pct in [("-20%", lo_pct), ("+20%", hi_pct)]:
            perturbed_val = base_val * (1.0 + pct)

            # Clamp to valid ranges
            if param_name == "max_corr":
                perturbed_val = min(perturbed_val, 1.0)
            if param_name in ("min_fraction_positive", "competitive_percentile"):
                perturbed_val = max(0.0, min(1.0, perturbed_val))
            if param_name == "min_competitive_score":
                perturbed_val = max(0.0, perturbed_val)

            ts = ThresholdSet(cost_bps=cost_bps)
            setattr(ts, param_name, perturbed_val)

            print(f"\n  {param_name} = {perturbed_val:.4f} ({direction} from {base_val:.4f})")
            print(f"  {'Family':>7s}  {'Baseline':>10s}  {'Perturbed':>10s}  "
                  f"{'Delta':>8s}  {'Verdict':>10s}  {'Reps':>5s}")
            print(f"  {'-'*7:>7s}  {'-'*10:>10s}  {'-'*10:>10s}  "
                  f"{'-'*8:>8s}  {'-'*10:>10s}  {'-'*5:>5s}")

            deltas = []
            for fam in FAMILIES:
                result = run_pipeline_with_thresholds(fam, close, horizon, ts,
                                                       volume=volume)
                delta = result.score - baselines[fam].score
                verdict = classify_delta(delta)
                rep_change = result.n_representatives - baselines[fam].n_representatives
                rep_str = f"{result.n_representatives:d}" + (
                    f"({rep_change:+d})" if rep_change != 0 else ""
                )
                print(f"  {fam:>7s}  {baselines[fam].score:+10.2f}  {result.score:+10.2f}  "
                      f"{delta:+8.2f}  {verdict:>10s}  {rep_str:>5s}")
                deltas.append(abs(delta))

            max_delta = max(deltas)
            avg_delta = sum(deltas) / len(deltas)
            overall = classify_delta(max_delta)
            print(f"  >> Max delta: {max_delta:.2f}  Avg delta: {avg_delta:.2f}  "
                  f"Overall: {overall}")

    # --- Summary ---
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print("  STABLE    = score change < 5 pts   -> threshold is robust")
    print("  MODERATE  = score change 5-15 pts   -> threshold matters somewhat")
    print("  SENSITIVE = score change >= 15 pts   -> threshold is fragile, investigate")
    print("=" * 78)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _normalize_column_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(name))
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in ascii_only.lower()).strip("_")
    aliases = {
        "cloture": "close",
        "close": "close",
        "volume": "volume",
        "date": "date",
        "ouvt": "open",
        "open": "open",
        "haut": "high",
        "high": "high",
        "bas": "low",
        "low": "low",
    }
    return aliases.get(cleaned, cleaned)


def _read_market_data(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    print(f"ERROR: Unsupported file type '{path.suffix}'. Use CSV or Excel.")
    sys.exit(1)


def _clip_to_lookback(df: pd.DataFrame, lookback_years: int) -> pd.DataFrame:
    if lookback_years <= 0:
        return df

    if "date" in df.columns:
        valid_dates = df["date"].dropna()
        if not valid_dates.empty:
            cutoff = valid_dates.max() - pd.DateOffset(years=lookback_years)
            return df.loc[df["date"] >= cutoff].copy()

    approx_bars = max(1, lookback_years * 252)
    return df.tail(approx_bars).copy()


def load_ohlcv(path: str, *, lookback_years: int = 5) -> tuple[np.ndarray, np.ndarray | None]:
    """Load close prices and optional volume from CSV or Excel market data."""
    input_path = Path(path).expanduser().resolve()
    if not input_path.exists():
        print(f"ERROR: Data file not found: {input_path}")
        sys.exit(1)

    df = _read_market_data(input_path)
    df.columns = [_normalize_column_name(c) for c in df.columns]

    if "close" not in df.columns:
        print(
            "ERROR: Input must have a Close/Cloture column. "
            f"Found: {list(df.columns)}"
        )
        sys.exit(1)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values("date")

    df = _clip_to_lookback(df, lookback_years)

    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)

    volume = None
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
        if df["volume"].notna().any():
            # Keep OBV-capable runs alive even if the source has a few blank volume cells.
            df["volume"] = df["volume"].fillna(0.0)
            volume = df["volume"].to_numpy(dtype=float)

    close = df["close"].to_numpy(dtype=float)
    return close, volume


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Signal engine threshold sensitivity analysis"
    )
    parser.add_argument(
        "--csv",
        default=str(DEFAULT_DATA_PATH),
        help="Path to OHLCV CSV/Excel file (default: scripts/IAM.xlsx)",
    )
    parser.add_argument("--horizon", default="short", choices=["short", "medium", "long"])
    parser.add_argument("--cost-bps", type=float, default=33.0,
                        help="Transaction cost in basis points (default: 33)")
    parser.add_argument(
        "--lookback-years",
        type=int,
        default=5,
        help="Use only the most recent N years of data (default: 5)",
    )
    args = parser.parse_args()

    close, volume = load_ohlcv(args.csv, lookback_years=args.lookback_years)
    print(f"Loaded {len(close)} bars from {args.csv} (last {args.lookback_years} years)")

    run_sensitivity(close, args.horizon, args.cost_bps, volume=volume)


if __name__ == "__main__":
    main()
