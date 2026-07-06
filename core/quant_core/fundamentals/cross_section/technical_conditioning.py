from __future__ import annotations

import argparse
import datetime as dt
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .composite import compute_sfc
from .ic_study import (
    SFC_PROOF_SPLIT_DATE,
    _hac_mean_t_stat,
    _norm_pvalue,
    benjamini_hochberg,
    chronological_split,
)
from .panel import PanelConfig, _assert_no_lookahead, build_pit_panel, load_universe
from .pillars import PillarConfig, compute_pillar_scores
from .portfolio_backtest import SfcPortfolioBacktestConfig, _target_rebalance_dates

HORIZONS = ("3m", "6m", "12m")
TERCILES = ("top", "middle", "bottom")


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _resolve_db_session() -> Session:
    db_url = os.environ.get("DATABASE_URL", "postgresql+psycopg2://app:app@127.0.0.1:5555/quant")
    engine = create_engine(db_url, pool_pre_ping=True)
    return sessionmaker(bind=engine)()


def _assign_sfc_terciles(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    terciles = []
    for _, sub in out.groupby("as_of_date"):
        ranked = sub.dropna(subset=["sfc"]).sort_values(["sfc", "symbol"], ascending=[False, True])
        mapping = {idx: "uncovered" for idx in sub.index}
        if not ranked.empty:
            ranked_index = ranked.index.to_numpy()
            for label, bucket in zip(("top", "middle", "bottom"), np.array_split(ranked_index, 3)):
                for idx in bucket.tolist():
                    mapping[idx] = label
        terciles.extend((idx, label) for idx, label in mapping.items())
    tercile_series = pd.Series({idx: label for idx, label in terciles})
    out["sfc_tercile"] = out.index.to_series().map(tercile_series).fillna("uncovered")
    return out


def _load_best_monthly_variants(db: Session) -> dict[str, str]:
    from services.api.app import models

    rows = (
        db.query(models.SignalBestEvidenceSnapshot)
        .filter(
            models.SignalBestEvidenceSnapshot.horizon == "monthly",
            models.SignalBestEvidenceSnapshot.source == "wfo",
            models.SignalBestEvidenceSnapshot.status == "succeeded",
            models.SignalBestEvidenceSnapshot.cooldown_bars == 0,
        )
        .all()
    )
    out: dict[str, str] = {}
    for row in rows:
        symbol = str(row.symbol or "").strip().upper()
        variant = str(row.variant or "").strip()
        if symbol and variant:
            out[symbol] = variant
    return out


def _monthly_score_series_by_symbol(db: Session, symbols: list[str]) -> dict[str, pd.Series]:
    from core.quant_core.research.score_history import aggregate_subset
    from services.api.app.routers.analytics import _load_score_history

    variants = _load_best_monthly_variants(db)
    out: dict[str, pd.Series] = {}
    for symbol in symbols:
        variant = variants.get(symbol)
        if not variant:
            continue
        series_by_cat = _load_score_history(db, symbol=symbol, source=f"wfo:{variant}", horizon="monthly")
        if not series_by_cat:
            continue
        score = aggregate_subset(series_by_cat, list(series_by_cat.keys()))
        if score is None or score.dropna().empty:
            continue
        out[symbol] = score.sort_index().dropna()
    return out


def _technical_monthly_join(scored_panel: pd.DataFrame, db: Session) -> pd.DataFrame:
    if scored_panel.empty or "as_of_date" not in scored_panel.columns:
        return scored_panel.copy()
    out = scored_panel.copy()
    out["as_of_date"] = pd.to_datetime(out["as_of_date"]).dt.date
    score_series = _monthly_score_series_by_symbol(db, sorted(out["symbol"].astype(str).str.upper().unique()))
    score_dates: list[dt.date | None] = []
    scores: list[float | None] = []
    for _, row in out.iterrows():
        symbol = str(row["symbol"]).strip().upper()
        series = score_series.get(symbol)
        if series is None or series.empty:
            score_dates.append(None)
            scores.append(None)
            continue
        idx = series.index.searchsorted(pd.Timestamp(row["as_of_date"]), side="right") - 1
        if idx < 0:
            score_dates.append(None)
            scores.append(None)
            continue
        score_dates.append(pd.Timestamp(series.index[idx]).date())
        scores.append(float(series.iloc[idx]))
    out["technical_score_date"] = score_dates
    out["technical_score"] = scores
    guard = out[["symbol", "as_of_date", "technical_score_date"]].rename(columns={"technical_score_date": "max_metric_availability_date"})
    _assert_no_lookahead(guard)
    return out


def _ic_stats(sub: pd.DataFrame, signal_col: str, return_col: str) -> tuple[float, float, int]:
    values = []
    pair_count = 0
    for _, date_sub in sub.groupby("as_of_date"):
        pairs = date_sub[[signal_col, return_col]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(pairs) < 5:
            continue
        ic = float(pairs[signal_col].corr(pairs[return_col], method="spearman"))
        if math.isfinite(ic):
            values.append(ic)
            pair_count += len(pairs)
    mean_ic = float(np.mean(values)) if values else float("nan")
    t_stat = _hac_mean_t_stat(values)
    return mean_ic, t_stat, pair_count


def _directional_stats(sub: pd.DataFrame, signal_col: str, return_col: str) -> tuple[float, float]:
    pairs = sub[[signal_col, return_col]].replace([np.inf, -np.inf], np.nan).dropna()
    if pairs.empty:
        return float("nan"), float("nan")
    signed = np.sign(pd.to_numeric(pairs[signal_col], errors="coerce")) * pd.to_numeric(pairs[return_col], errors="coerce")
    signed = signed.replace([np.inf, -np.inf], np.nan).dropna()
    if signed.empty:
        return float("nan"), float("nan")
    return float((signed > 0).mean()), float(signed.mean())


def conditioned_ic_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for tercile in TERCILES:
        tercile_frame = frame[frame["sfc_tercile"] == tercile].copy()
        for horizon in HORIZONS:
            mean_ic, t_stat, pairs = _ic_stats(tercile_frame, "technical_score", f"fwd_return_{horizon}")
            hit_rate, mean_return = _directional_stats(tercile_frame, "technical_score", f"fwd_return_{horizon}")
            rows.append(
                {
                    "tercile": tercile,
                    "horizon": horizon,
                    "pairs": pairs,
                    "mean_ic": mean_ic,
                    "nw_t_stat": t_stat,
                    "pvalue": _norm_pvalue(t_stat),
                    "hit_rate": hit_rate,
                    "mean_signed_forward_return": mean_return,
                }
            )
    out = pd.DataFrame(rows)
    if not out.empty:
        fdr = benjamini_hochberg(out["pvalue"].tolist(), alpha=0.10)
        out["fdr_qvalue"] = [item["qvalue"] for item in fdr]
        out["fdr_reject_10pct"] = [item["reject"] for item in fdr]
    return out


def decomposition_table(frame: pd.DataFrame) -> pd.DataFrame:
    subsets = {
        "full_universe": frame,
        "non_bottom_sfc": frame[frame["sfc_tercile"].isin(["top", "middle"])].copy(),
        "top_sfc_only": frame[frame["sfc_tercile"] == "top"].copy(),
    }
    rows: list[dict[str, Any]] = []
    for name, sub in subsets.items():
        for horizon in HORIZONS:
            mean_ic, t_stat, pairs = _ic_stats(sub, "technical_score", f"fwd_return_{horizon}")
            hit_rate, mean_return = _directional_stats(sub, "technical_score", f"fwd_return_{horizon}")
            rows.append(
                {
                    "subset": name,
                    "horizon": horizon,
                    "pairs": pairs,
                    "mean_ic": mean_ic,
                    "nw_t_stat": t_stat,
                    "hit_rate": hit_rate,
                    "mean_signed_forward_return": mean_return,
                }
            )
    return pd.DataFrame(rows)


def event_window_table(frame: pd.DataFrame) -> pd.DataFrame:
    cfg = SfcPortfolioBacktestConfig(rebalance="event")
    event_dates = set(_target_rebalance_dates(frame, cfg))
    top = frame[frame["sfc_tercile"] == "top"].copy()
    rows = []
    for label, sub in {
        "top_all_dates": top,
        "top_event_dates": top[top["as_of_date"].isin(event_dates)].copy(),
    }.items():
        for horizon in HORIZONS:
            mean_ic, t_stat, pairs = _ic_stats(sub, "technical_score", f"fwd_return_{horizon}")
            rows.append({"subset": label, "horizon": horizon, "pairs": pairs, "mean_ic": mean_ic, "nw_t_stat": t_stat})
    return pd.DataFrame(rows)


def run_study(scored_panel: pd.DataFrame, db: Session) -> dict[str, Any]:
    if scored_panel.empty or "as_of_date" not in scored_panel.columns:
        empty = pd.DataFrame()
        return {
            "joined": empty,
            "selection": empty,
            "proof": empty,
            "conditioned": empty,
            "decomposition": empty,
            "event_window": empty,
            "split_date": SFC_PROOF_SPLIT_DATE,
            "verdict": "avoid-list veto only",
        }
    joined = _assign_sfc_terciles(_technical_monthly_join(scored_panel, db))
    joined = joined[joined["technical_score"].notna()].copy()
    selection, proof, split_date = chronological_split(joined, split_date=SFC_PROOF_SPLIT_DATE)
    conditioned = conditioned_ic_table(proof)
    decomposition = decomposition_table(proof)
    event_window = event_window_table(proof)

    verdict = "avoid-list veto only"
    top_rows = conditioned[(conditioned["tercile"] == "top") & (conditioned["nw_t_stat"] >= 2.0) & (conditioned["mean_ic"] > 0)]
    bottom_bad = conditioned[(conditioned["tercile"] == "bottom") & (conditioned["mean_ic"] <= 0)]
    non_bottom = decomposition[(decomposition["subset"] == "non_bottom_sfc") & (decomposition["nw_t_stat"] >= 2.0) & (decomposition["mean_ic"] > 0)]
    event_rows = event_window[(event_window["subset"] == "top_event_dates") & (event_window["nw_t_stat"] >= 2.0) & (event_window["mean_ic"] > 0)]
    if not event_rows.empty:
        verdict = "event-window drift overlay"
    elif not top_rows.empty and not bottom_bad.empty:
        verdict = "SFC-tercile position sizing"
    elif not non_bottom.empty:
        verdict = "avoid-list veto only"
    return {
        "joined": joined,
        "selection": selection,
        "proof": proof,
        "conditioned": conditioned,
        "decomposition": decomposition,
        "event_window": event_window,
        "split_date": split_date,
        "verdict": verdict,
    }


def format_results_markdown(result: dict[str, Any]) -> str:
    conditioned = result["conditioned"].round(4)
    decomposition = result["decomposition"].round(4)
    event_window = result["event_window"].round(4)
    return "\n".join(
        [
            "# 67 - SFC technical conditioning",
            "",
            f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
            f"Selection/proof split date: `{result['split_date']}`",
            "",
            "## Proof-half technical IC within SFC terciles",
            "",
            conditioned.to_markdown(index=False) if not conditioned.empty else "_No conditioned IC rows._",
            "",
            "## Practical decomposition",
            "",
            decomposition.to_markdown(index=False) if not decomposition.empty else "_No decomposition rows._",
            "",
            "## Event-window overlay check",
            "",
            event_window.to_markdown(index=False) if not event_window.empty else "_No event-window rows._",
            "",
            "## Verdict",
            "",
            f"Verdict: **{result['verdict']}**",
            "No live sizing is changed by this study.",
            "",
        ]
    ) + "\n"


def main() -> None:
    from .ic_study import _build_price_loader, _load_rows_from_db

    parser = argparse.ArgumentParser(description="SFC-conditioned technical IC study")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out", default="docs/fundamentals-layer/67-sfc-technical-conditioning.md")
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
    db = _resolve_db_session()
    try:
        result = run_study(scored, db)
    finally:
        db.close()
    markdown = format_results_markdown(result)
    Path(args.out).write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
