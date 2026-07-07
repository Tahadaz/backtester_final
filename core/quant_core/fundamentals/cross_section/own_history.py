from __future__ import annotations

import argparse
import datetime as dt
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

from .composite import compute_sfc
from .ic_study import (
    SFC_PROOF_SPLIT_DATE,
    _hac_mean_t_stat,
    _norm_pvalue,
    benjamini_hochberg,
    chronological_split,
    compute_ic_table,
)
from .panel import PanelConfig, build_pit_panel, load_universe
from .pillars import PillarConfig, compute_pillar_scores

SIGNALS = ("pillar_val", "own_hist_z", "value_own_hist_blend")
HORIZONS = ("3m", "6m", "12m")


@dataclass(frozen=True)
class OwnHistoryConfig:
    trailing_months: int = 60
    min_months: int = 36
    min_fiscal_years: int = 3
    split_date: dt.date = SFC_PROOF_SPLIT_DATE


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _latest_statement_year(history: Any) -> int | None:
    years = [int(getattr(row, "statement_year")) for row in list(history or []) if getattr(row, "statement_year", None) is not None]
    return max(years) if years else None


def _empirical_percentile(values: list[float], current: float) -> float:
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    lower = float(np.sum(arr < current))
    equal = float(np.sum(arr == current))
    pct = (lower + 0.5 * equal) / float(n)
    return min(max(pct, 1e-6), 1.0 - 1e-6)


def compute_own_history_signals(
    scored_panel: pd.DataFrame,
    *,
    config: OwnHistoryConfig | None = None,
) -> pd.DataFrame:
    cfg = config or OwnHistoryConfig()
    if scored_panel.empty:
        return scored_panel.copy()
    out = scored_panel.copy()
    out["as_of_date"] = pd.to_datetime(out["as_of_date"]).dt.date
    out["latest_statement_year"] = out["history"].apply(_latest_statement_year)
    out["own_hist_pct"] = np.nan
    out["own_hist_z"] = np.nan
    out["own_hist_obs"] = np.nan
    out["own_hist_fiscal_years"] = np.nan
    normal = NormalDist()
    for symbol, idx in out.groupby("symbol").groups.items():
        sub = out.loc[list(idx)].sort_values("as_of_date").copy()
        records = sub[["as_of_date", "pillar_val_raw", "latest_statement_year"]].to_dict("records")
        for row_idx, row in zip(sub.index, records):
            current_val = _finite(row.get("pillar_val_raw"))
            if current_val is None:
                continue
            end = pd.Timestamp(row["as_of_date"])
            start = end - pd.DateOffset(months=max(cfg.trailing_months - 1, 0))
            window = [
                item
                for item in records
                if start <= pd.Timestamp(item["as_of_date"]) <= end and _finite(item.get("pillar_val_raw")) is not None
            ]
            obs = len(window)
            years = {int(item["latest_statement_year"]) for item in window if item.get("latest_statement_year") is not None}
            out.at[row_idx, "own_hist_obs"] = float(obs)
            out.at[row_idx, "own_hist_fiscal_years"] = float(len(years))
            if obs < cfg.min_months or len(years) < cfg.min_fiscal_years:
                continue
            trailing_values = [float(item["pillar_val_raw"]) for item in window if _finite(item.get("pillar_val_raw")) is not None]
            pct = _empirical_percentile(trailing_values, current_val)
            out.at[row_idx, "own_hist_pct"] = pct
            out.at[row_idx, "own_hist_z"] = normal.inv_cdf(pct)
    out["value_own_hist_blend"] = np.where(
        out["pillar_val"].notna() & out["own_hist_z"].notna(),
        0.5 * pd.to_numeric(out["pillar_val"], errors="coerce") + 0.5 * pd.to_numeric(out["own_hist_z"], errors="coerce"),
        np.nan,
    )
    return out


def coverage_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["as_of_date", "covered_names", "universe_names", "coverage_share"])
    rows = []
    for as_of, sub in frame.groupby("as_of_date"):
        universe = int(sub["symbol"].nunique())
        covered = int(sub.loc[sub["own_hist_z"].notna(), "symbol"].nunique())
        rows.append(
            {
                "as_of_date": pd.Timestamp(as_of).date().isoformat(),
                "covered_names": covered,
                "universe_names": universe,
                "coverage_share": covered / universe if universe else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _marginal_ic_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        diffs: list[float] = []
        dates = []
        for as_of, sub in frame.groupby("as_of_date"):
            pairs = sub[["pillar_val", "value_own_hist_blend", f"fwd_return_{horizon}"]].replace([np.inf, -np.inf], np.nan).dropna()
            if len(pairs) < 5:
                continue
            base_ic = float(pairs["pillar_val"].corr(pairs[f"fwd_return_{horizon}"], method="spearman"))
            blend_ic = float(pairs["value_own_hist_blend"].corr(pairs[f"fwd_return_{horizon}"], method="spearman"))
            if math.isfinite(base_ic) and math.isfinite(blend_ic):
                diffs.append(blend_ic - base_ic)
                dates.append(as_of)
        rows.append(
            {
                "horizon": horizon,
                "periods": len(diffs),
                "mean_marginal_ic": float(np.mean(diffs)) if diffs else float("nan"),
                "nw_t_stat": _hac_mean_t_stat(diffs),
                "pvalue": _norm_pvalue(_hac_mean_t_stat(diffs)),
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        fdr = benjamini_hochberg(out["pvalue"].tolist(), alpha=0.10)
        out["fdr_qvalue"] = [item["qvalue"] for item in fdr]
        out["fdr_reject_10pct"] = [item["reject"] for item in fdr]
    return out


def run_own_history_diagnostic(
    scored_panel: pd.DataFrame,
    *,
    config: OwnHistoryConfig | None = None,
) -> dict[str, Any]:
    cfg = config or OwnHistoryConfig()
    if scored_panel.empty or "as_of_date" not in scored_panel.columns:
        empty = pd.DataFrame()
        return {
            "frame": empty,
            "selection": empty,
            "proof": empty,
            "proof_ic": empty,
            "marginal_ic": empty,
            "coverage": coverage_table(empty),
            "proof_coverage": coverage_table(empty),
            "split_date": cfg.split_date,
            "verdict": "FAIL for promotion; remain diagnostic-only",
            "promotion_pass": False,
        }
    enriched = compute_own_history_signals(scored_panel, config=cfg)
    selection, proof, split_date = chronological_split(enriched, split_date=cfg.split_date)
    proof_ic = compute_ic_table(proof, split="proof", variant_id="own_history_diag", signals=SIGNALS)
    if not proof_ic.empty:
        fdr = benjamini_hochberg(proof_ic["pvalue"].tolist(), alpha=0.10)
        proof_ic["fdr_qvalue"] = [item["qvalue"] for item in fdr]
        proof_ic["fdr_reject_10pct"] = [item["reject"] for item in fdr]
    marginal = _marginal_ic_table(proof)
    proof_coverage = coverage_table(proof)
    promotion_pass = False
    if not marginal.empty:
        promotion_pass = bool(((marginal["mean_marginal_ic"] > 0) & (marginal["nw_t_stat"] >= 2.0)).any())
    verdict = (
        "PASS for future promotion review"
        if promotion_pass and (proof_coverage["coverage_share"].mean() if not proof_coverage.empty else 0.0) > 0
        else "FAIL for promotion; remain diagnostic-only"
    )
    return {
        "frame": enriched,
        "selection": selection,
        "proof": proof,
        "proof_ic": proof_ic,
        "marginal_ic": marginal,
        "coverage": coverage_table(enriched),
        "proof_coverage": proof_coverage,
        "split_date": split_date,
        "verdict": verdict,
        "promotion_pass": promotion_pass,
    }


def format_results_markdown(result: dict[str, Any]) -> str:
    proof_ic = result["proof_ic"].round(4)
    marginal = result["marginal_ic"].round(4)
    coverage = result["coverage"].round(4)
    return "\n".join(
        [
            "# 66 - Own-history diagnostic",
            "",
            f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
            f"Selection/proof split date: `{result['split_date']}`",
            "",
            "## Coverage",
            "",
            coverage.to_markdown(index=False) if not coverage.empty else "_No coverage rows._",
            "",
            "## Proof-half IC",
            "",
            proof_ic.to_markdown(index=False) if not proof_ic.empty else "_No proof IC rows._",
            "",
            "## Marginal IC of 50/50 blend vs cross-sectional value",
            "",
            marginal.to_markdown(index=False) if not marginal.empty else "_No marginal IC rows._",
            "",
            "## Verdict",
            "",
            f"Verdict: **{result['verdict']}**",
            "Promotion rule: own-history stays out of `compute_sfc` unless the proof-half blend marginal IC clears NW t >= 2 with positive coverage.",
            "",
        ]
    ) + "\n"


def main() -> None:
    from .ic_study import _build_price_loader, _load_rows_from_db

    parser = argparse.ArgumentParser(description="Own-history diagnostic for the SFC value pillar")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out", default="docs/fundamentals-layer/66-own-history-diagnostic.md")
    args = parser.parse_args()

    annual, period, consensus, sectors = _load_rows_from_db()
    universe = load_universe()
    price_loader, price_cache = _build_price_loader()
    panel = build_pit_panel(
        annual_rows=annual,
        period_rows=period,
        consensus_rows=consensus,
        price_loader=price_loader,
        universe_df=universe,
        config=PanelConfig(
            start=pd.Timestamp(args.start).date() if args.start else None,
            end=pd.Timestamp(args.end).date() if args.end else None,
        ),
        sectors=sectors,
    )
    scored = compute_sfc(
        compute_pillar_scores(
            panel,
            price_by_symbol=price_cache,
            config=PillarConfig(pmom_months=6, min_bucket=8, mad_clip=3.0),
        )
    )
    result = run_own_history_diagnostic(scored)
    markdown = format_results_markdown(result)
    Path(args.out).write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
