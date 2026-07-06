from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .composite import compute_sfc
from .ic_study import (
    HORIZONS,
    SFC_METHODOLOGY_VERSION,
    SFC_PROOF_SPLIT_DATE,
    _build_price_loader,
    _hac_mean_t_stat,
    _load_rows_from_db,
    _norm_pvalue,
    benjamini_hochberg,
    chronological_split,
    compute_ic_table,
)
from .panel import PanelConfig, build_pit_panel, load_universe
from .pillars import PillarConfig, compute_pillar_scores
from .portfolio_backtest import SfcPortfolioBacktestConfig, run_sfc_portfolio_backtest
from .technical_conditioning import _resolve_db_session, _technical_monthly_join

EVAL_SIGNALS = ("pillar_val", "pillar_qual", "pillar_fmom", "sfc", "sfc_legacy")
ROBUST_SIGNALS = ("pillar_val", "sfc")
ROBUST_HORIZONS = ("6m", "12m")
FM_FACTORS = ("pillar_val", "sfc", "sfc_legacy")


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _evaluation_frame(scored_panel: pd.DataFrame) -> pd.DataFrame:
    if scored_panel.empty:
        return scored_panel.copy()
    frame = scored_panel.copy()
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"]).dt.date
    return frame[frame["as_of_date"] >= SFC_PROOF_SPLIT_DATE].copy()


def _pair_counts(frame: pd.DataFrame, signal_col: str, return_col: str) -> list[int]:
    counts: list[int] = []
    for _, sub in frame.groupby("as_of_date"):
        pairs = sub[[signal_col, return_col]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(pairs) >= 5:
            counts.append(int(len(pairs)))
    return counts


def _add_table_context(frame: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    if table.empty:
        return table
    out = table.copy()
    n_dates: list[int] = []
    medians: list[float] = []
    for _, row in out.iterrows():
        counts = _pair_counts(frame, str(row["signal"]), f"fwd_return_{row['horizon']}")
        n_dates.append(len(counts))
        medians.append(float(np.median(counts)) if counts else float("nan"))
    out["n_dates"] = n_dates
    out["median_cross_section_n"] = medians
    return out


def _bh_table(table: pd.DataFrame) -> pd.DataFrame:
    if table.empty:
        return table
    out = table.copy()
    bh = benjamini_hochberg(out["pvalue"].tolist(), alpha=0.10)
    out["bh_qvalue"] = [item["qvalue"] for item in bh]
    return out


def _core_exclusion_composite(frame: pd.DataFrame, exclude: str) -> pd.Series:
    remaining = [col for col in ("pillar_val", "pillar_qual", "pillar_fmom") if col != exclude]
    values = frame[remaining].apply(pd.to_numeric, errors="coerce")
    valid = values.notna().sum(axis=1) >= len(remaining)
    out = values.mean(axis=1)
    out.loc[~valid] = np.nan
    return out


def _spearman_corr_matrix(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for left in columns:
        for right in columns:
            values: list[float] = []
            counts: list[int] = []
            for _, sub in frame.groupby("as_of_date"):
                if left == right:
                    pairs = sub[[left]].replace([np.inf, -np.inf], np.nan).dropna()
                    corr = 1.0 if len(pairs) >= 5 else float("nan")
                    if math.isfinite(corr):
                        values.append(corr)
                        counts.append(len(pairs))
                    continue
                pairs = sub[[left, right]].replace([np.inf, -np.inf], np.nan).dropna()
                if len(pairs) < 5:
                    continue
                corr = float(pairs[left].corr(pairs[right], method="spearman"))
                if math.isfinite(corr):
                    values.append(corr)
                    counts.append(len(pairs))
            rows.append(
                {
                    "pillar_left": left,
                    "pillar_right": right,
                    "mean_rank_corr": float(np.mean(values)) if values else float("nan"),
                    "n_dates": len(counts),
                    "median_cross_section_n": float(np.median(counts)) if counts else float("nan"),
                }
            )
    return pd.DataFrame(rows)


def diagnostic_d1_attribution(scored_panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    eval_frame = _evaluation_frame(scored_panel)
    ic_table = compute_ic_table(eval_frame, split="evaluation", variant_id=SFC_METHODOLOGY_VERSION, signals=EVAL_SIGNALS)
    ic_table = _bh_table(_add_table_context(eval_frame, ic_table))

    with_exclusions = eval_frame.copy()
    exclusions = {
        "VAL": "pillar_val",
        "QUAL": "pillar_qual",
        "FMOM": "pillar_fmom",
    }
    for label, column in exclusions.items():
        with_exclusions[f"sfc_ex_{label.lower()}"] = _core_exclusion_composite(with_exclusions, column)
    excl_table = compute_ic_table(
        with_exclusions,
        split="evaluation",
        variant_id=SFC_METHODOLOGY_VERSION,
        signals=tuple(f"sfc_ex_{label.lower()}" for label in exclusions),
    )
    excl_table = _add_table_context(with_exclusions, excl_table)
    base = ic_table[["horizon", "mean_ic"]].loc[ic_table["signal"] == "sfc"].rename(columns={"mean_ic": "base_sfc_ic"})
    excl_table["excluded_pillar"] = excl_table["signal"].str.replace("sfc_ex_", "", regex=False).str.upper()
    excl_table = excl_table.merge(base, on="horizon", how="left")
    excl_table["IC with pillar excluded"] = excl_table["mean_ic"]
    excl_table["Δ associated with exclusion"] = excl_table["IC with pillar excluded"] - excl_table["base_sfc_ic"]

    corr_matrix = _spearman_corr_matrix(eval_frame, ["pillar_val", "pillar_qual", "pillar_fmom", "pillar_pmom"])
    coverage_rows = []
    for signal in ("pillar_val", "pillar_qual", "pillar_fmom", "pillar_pmom"):
        counts = eval_frame.groupby("as_of_date")[signal].apply(lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum()))
        coverage_rows.append(
            {
                "pillar": signal,
                "covered_rows": int(counts.sum()),
                "covered_dates": int((counts > 0).sum()),
                "n_dates": int(len(counts)),
                "median_cross_section_n": float(counts.median()) if not counts.empty else float("nan"),
            }
        )
    coverage = pd.DataFrame(coverage_rows)
    return {
        "ic_table": ic_table,
        "leave_one_out": excl_table,
        "rank_correlation_matrix": corr_matrix,
        "coverage": coverage,
    }


def _rank_residualize_by_date(frame: pd.DataFrame, source_col: str, control_col: str) -> pd.Series:
    residual = pd.Series(np.nan, index=frame.index, dtype=float)
    for _, sub in frame.groupby("as_of_date"):
        pairs = sub[[source_col, control_col]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(pairs) < 5:
            continue
        y = pairs[source_col].rank(method="average")
        x = pairs[control_col].rank(method="average")
        fit = sm.OLS(y.astype(float), sm.add_constant(x.astype(float))).fit()
        residual.loc[pairs.index] = fit.resid
    return residual


def diagnostic_d2_pmom_overlap(scored_panel: pd.DataFrame, technical_frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    eval_tech = _evaluation_frame(technical_frame)
    overlap_values: list[float] = []
    overlap_counts: list[int] = []
    for _, sub in eval_tech.groupby("as_of_date"):
        pairs = sub[["pillar_pmom", "technical_score"]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(pairs) < 5:
            continue
        corr = float(pairs["pillar_pmom"].corr(pairs["technical_score"], method="spearman"))
        if math.isfinite(corr):
            overlap_values.append(corr)
            overlap_counts.append(len(pairs))
    corr_summary = pd.DataFrame(
        [
            {
                "metric": "corr(pillar_pmom, technical_score)",
                "mean_corr": float(np.mean(overlap_values)) if overlap_values else float("nan"),
                "iqr_corr": float(np.subtract(*np.percentile(overlap_values, [75, 25]))) if overlap_values else float("nan"),
                "n_dates": len(overlap_counts),
                "median_cross_section_n": float(np.median(overlap_counts)) if overlap_counts else float("nan"),
            }
        ]
    )

    residual_frame = eval_tech.copy()
    residual_frame["pmom_residual_vs_technical"] = _rank_residualize_by_date(residual_frame, "pillar_pmom", "technical_score")
    residual_ic = _add_table_context(
        residual_frame,
        compute_ic_table(
            residual_frame,
            split="evaluation",
            variant_id=SFC_METHODOLOGY_VERSION,
            signals=("pmom_residual_vs_technical",),
        ),
    )
    return {"correlation": corr_summary, "incremental_ic": residual_ic}


def _mean_ic_stats(frame: pd.DataFrame, signal: str, horizon: str) -> dict[str, Any]:
    table = _add_table_context(
        frame,
        compute_ic_table(frame, split="evaluation", variant_id=SFC_METHODOLOGY_VERSION, signals=(signal,)),
    )
    if table.empty:
        return {
            "mean_ic": float("nan"),
            "nw_t_stat": 0.0,
            "pvalue": 1.0,
            "n_dates": 0,
            "median_cross_section_n": float("nan"),
        }
    row = table.loc[table["horizon"] == horizon].iloc[0]
    return {
        "mean_ic": float(row["mean_ic"]),
        "nw_t_stat": float(row["nw_t_stat"]),
        "pvalue": float(row["pvalue"]),
        "n_dates": int(row["n_dates"]),
        "median_cross_section_n": float(row["median_cross_section_n"]),
    }


def _drop_dates(frame: pd.DataFrame, dates: set[dt.date]) -> pd.DataFrame:
    return frame[~frame["as_of_date"].isin(dates)].copy()


def _symbol_influence(frame: pd.DataFrame, signal: str, horizon: str) -> list[str]:
    baseline = _mean_ic_stats(frame, signal, horizon)["mean_ic"]
    influences: list[tuple[str, float]] = []
    for symbol in sorted(frame["symbol"].astype(str).unique()):
        reduced = frame[frame["symbol"] != symbol].copy()
        if reduced.empty:
            continue
        influence = _mean_ic_stats(reduced, signal, horizon)["mean_ic"]
        influences.append((symbol, abs(influence - baseline)))
    influences.sort(key=lambda item: (-item[1], item[0]))
    return [symbol for symbol, _ in influences]


def _market_cap(frame: pd.DataFrame) -> pd.Series:
    return frame["metrics"].apply(
        lambda metrics: _safe_float((metrics or {}).get("MarketCap_Calc"))
        if _safe_float((metrics or {}).get("MarketCap_Calc")) is not None
        else _safe_float((metrics or {}).get("Market_Cap"))
    )


def diagnostic_d3_robustness(scored_panel: pd.DataFrame) -> pd.DataFrame:
    eval_frame = _evaluation_frame(scored_panel).copy()
    eval_frame["market_cap"] = _market_cap(eval_frame)
    rows: list[dict[str, Any]] = []
    all_dates = sorted(eval_frame["as_of_date"].unique())
    for signal in ROBUST_SIGNALS:
        for horizon in ROBUST_HORIZONS:
            base = _mean_ic_stats(eval_frame, signal, horizon)
            rows.append({"signal": signal, "horizon": horizon, "scenario": "baseline", **base})

            date_values = []
            for date in all_dates:
                stats = _mean_ic_stats(_drop_dates(eval_frame, {date}), signal, horizon)
                if math.isfinite(stats["mean_ic"]):
                    date_values.append(stats)
            if date_values:
                rows.append({"signal": signal, "horizon": horizon, "scenario": "date_jackknife_min", **min(date_values, key=lambda item: item["mean_ic"])})
                rows.append({"signal": signal, "horizon": horizon, "scenario": "date_jackknife_max", **max(date_values, key=lambda item: item["mean_ic"])})

            block_values = []
            for start in range(max(len(all_dates) - 2, 0)):
                stats = _mean_ic_stats(_drop_dates(eval_frame, set(all_dates[start : start + 3])), signal, horizon)
                if math.isfinite(stats["mean_ic"]):
                    block_values.append(stats)
            if block_values:
                rows.append({"signal": signal, "horizon": horizon, "scenario": "block3_jackknife_min", **min(block_values, key=lambda item: item["mean_ic"])})
                rows.append({"signal": signal, "horizon": horizon, "scenario": "block3_jackknife_max", **max(block_values, key=lambda item: item["mean_ic"])})

            influential = _symbol_influence(eval_frame, signal, horizon)
            for top_k in (1, 3, 5):
                reduced = eval_frame[~eval_frame["symbol"].isin(influential[:top_k])].copy()
                rows.append({"signal": signal, "horizon": horizon, "scenario": f"drop_top_{top_k}_influential_names", **_mean_ic_stats(reduced, signal, horizon)})

            non_financials = eval_frame[~eval_frame["is_financial"].fillna(False)].copy()
            rows.append({"signal": signal, "horizon": horizon, "scenario": "financials_removed", **_mean_ic_stats(non_financials, signal, horizon)})

            for bucket in ("small", "large"):
                pieces = []
                for _, sub in eval_frame.groupby("as_of_date"):
                    work = sub.copy()
                    work["market_cap"] = pd.to_numeric(work["market_cap"], errors="coerce")
                    work = work.dropna(subset=["market_cap"])
                    if len(work) < 6:
                        continue
                    median_cap = float(work["market_cap"].median())
                    if bucket == "small":
                        pieces.append(work[work["market_cap"] <= median_cap])
                    else:
                        pieces.append(work[work["market_cap"] > median_cap])
                bucket_frame = pd.concat(pieces, ignore_index=False) if pieces else eval_frame.iloc[0:0].copy()
                rows.append({"signal": signal, "horizon": horizon, "scenario": f"size_bucket_{bucket}", **_mean_ic_stats(bucket_frame, signal, horizon)})
    return pd.DataFrame(rows)


def _rank_standardize(series: pd.Series) -> pd.Series:
    ranks = series.rank(method="average", pct=True)
    return ranks - float(ranks.mean())


def _fama_macbeth_for_factor(frame: pd.DataFrame, factor_col: str, horizon: str, with_interaction: bool) -> list[dict[str, Any]]:
    coeffs: dict[str, list[float]] = {"Intercept": [], "T": [], "F": []}
    if with_interaction:
        coeffs["T*F"] = []
    sample_sizes: list[int] = []
    for _, sub in frame.groupby("as_of_date"):
        cols = ["technical_score", factor_col, f"fwd_return_{horizon}"]
        work = sub[cols].replace([np.inf, -np.inf], np.nan).dropna()
        if len(work) < (7 if with_interaction else 6):
            continue
        t_vals = _rank_standardize(work["technical_score"].astype(float))
        f_vals = _rank_standardize(work[factor_col].astype(float))
        x = pd.DataFrame({"Intercept": 1.0, "T": t_vals, "F": f_vals}, index=work.index)
        if with_interaction:
            x["T*F"] = t_vals * f_vals
        fit = sm.OLS(work[f"fwd_return_{horizon}"].astype(float), x).fit()
        for name in coeffs:
            coeff = _safe_float(fit.params.get(name))
            if coeff is not None:
                coeffs[name].append(coeff)
        sample_sizes.append(len(work))
    rows = []
    n_dates = len(sample_sizes)
    median_n = float(np.median(sample_sizes)) if sample_sizes else float("nan")
    for name, series in coeffs.items():
        mean_coef = float(np.mean(series)) if series else float("nan")
        hac_t = _hac_mean_t_stat(series)
        rows.append(
            {
                "factor": factor_col,
                "horizon": horizon,
                "model": "r ~ 1 + T + F + T*F" if with_interaction else "r ~ 1 + T + F",
                "term": name,
                "mean_coef": mean_coef,
                "hac_t_stat": hac_t,
                "pvalue": _norm_pvalue(hac_t),
                "n_dates": n_dates,
                "median_cross_section_n": median_n,
                "label": "EXPLORATORY_LOW_POWER" if name == "T*F" else "",
            }
        )
    return rows


def diagnostic_d4_integration(scored_panel: pd.DataFrame, technical_frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    eval_tech = _evaluation_frame(technical_frame)
    fm_rows: list[dict[str, Any]] = []
    for factor in FM_FACTORS:
        for horizon in HORIZONS:
            fm_rows.extend(_fama_macbeth_for_factor(eval_tech, factor, horizon, with_interaction=False))
            fm_rows.extend(_fama_macbeth_for_factor(eval_tech, factor, horizon, with_interaction=True))
    fama_macbeth = pd.DataFrame(fm_rows)

    eval_scored = _evaluation_frame(scored_panel)
    covered_counts = eval_scored.groupby("as_of_date")["sfc"].apply(lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum()))
    ladder_rows = []
    ladder_configs = [
        ("equal_top_tercile", SfcPortfolioBacktestConfig(rebalance="event", weighting_mode="equal_top_tercile")),
        ("benchmark_active_uncapped", SfcPortfolioBacktestConfig(rebalance="event", weighting_mode="benchmark_active", active_weight_cap=1.0)),
        ("benchmark_active_pm3pct", SfcPortfolioBacktestConfig(rebalance="event", weighting_mode="benchmark_active", active_weight_cap=0.03)),
    ]
    price_by_symbol = {}
    for symbol, sub in scored_panel.groupby("symbol"):
        if "close" not in sub.columns:
            continue
        series = pd.Series(sub["close"].astype(float).to_list(), index=pd.to_datetime(sub["as_of_date"]))
        price_by_symbol[str(symbol)] = series
    for label, cfg in ladder_configs:
        result = run_sfc_portfolio_backtest(eval_scored, price_by_symbol=price_by_symbol, config=cfg)
        proof = next((row for row in result.get("summary", []) if row.get("segment") == "proof"), {})
        ladder_rows.append(
            {
                "construction": label,
                "active_return": proof.get("mean_active_return"),
                "tracking_error": proof.get("tracking_error"),
                "information_ratio": proof.get("information_ratio"),
                "n_dates": int(proof.get("periods") or 0),
                "median_cross_section_n": float(covered_counts.median()) if not covered_counts.empty else float("nan"),
            }
        )
    ladder = pd.DataFrame(ladder_rows)
    return {"fama_macbeth": fama_macbeth, "harvestability": ladder}


def run_diagnostics(scored_panel: pd.DataFrame, technical_frame: pd.DataFrame) -> dict[str, Any]:
    d1 = diagnostic_d1_attribution(scored_panel)
    d2 = diagnostic_d2_pmom_overlap(scored_panel, technical_frame)
    d3 = diagnostic_d3_robustness(scored_panel)
    d4 = diagnostic_d4_integration(scored_panel, technical_frame)
    return {
        "methodology_version": SFC_METHODOLOGY_VERSION,
        "evaluation_start_date": SFC_PROOF_SPLIT_DATE.isoformat(),
        "d1": {key: value.to_dict(orient="records") for key, value in d1.items()},
        "d2": {key: value.to_dict(orient="records") for key, value in d2.items()},
        "d3": d3.to_dict(orient="records"),
        "d4": {key: value.to_dict(orient="records") for key, value in d4.items()},
    }


def _table(records: list[dict[str, Any]]) -> str:
    frame = pd.DataFrame(records)
    if frame.empty:
        return "_No rows._"
    return frame.round(4).to_markdown(index=False)


def format_validation_markdown(payload: dict[str, Any]) -> str:
    d1 = payload["d1"]
    d2 = payload["d2"]
    d4 = payload["d4"]
    return "\n".join(
        [
            "# 70 - SFC final validation",
            "",
            f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
            f"Methodology version: `{payload['methodology_version']}`",
            f"Evaluation / held-out-by-original-design period start: `{payload['evaluation_start_date']}`",
            "",
            "## Formulas",
            "",
            "- `sfc = mean(pillar_val, pillar_qual, pillar_fmom)` over available core pillars, requiring >=2 of 3.",
            "- `sfc_legacy = mean(pillar_val, pillar_qual, pillar_fmom, pillar_pmom)` over available legacy pillars, requiring >=2 of 4.",
            "- ICs are per-date Spearman correlations; HAC t-stats use the existing Newey-West helper over the date-level IC series.",
            "- D2 incremental PMOM IC uses per-date rank residualization of `pillar_pmom` on `technical_score` before the same IC calculation.",
            "- D4 uses Fama-MacBeth: cross-sectional regressions estimated per date, then HAC t-stats over the coefficient time series. No pooled OLS is used.",
            "",
            "## D1 Attribution",
            "",
            _table(d1["ic_table"]),
            "",
            "### Leave-one-pillar-out",
            "",
            _table(d1["leave_one_out"]),
            "",
            "### Per-date-averaged pillar rank-correlation matrix",
            "",
            _table(d1["rank_correlation_matrix"]),
            "",
            "### Per-pillar coverage counts",
            "",
            _table(d1["coverage"]),
            "",
            "## D2 PMOM overlap",
            "",
            _table(d2["correlation"]),
            "",
            "### PMOM incremental IC after per-date rank residualization on technical_score",
            "",
            _table(d2["incremental_ic"]),
            "",
            "## D3 Robustness",
            "",
            _table(payload["d3"]),
            "",
            "## D4 Secondary integration",
            "",
            _table(d4["fama_macbeth"]),
            "",
            "## Harvestability (construction ladder — not a causal decomposition)",
            "",
            _table(d4["harvestability"]),
            "",
            "## Sample sizes and limitations",
            "",
            "- The effective evidence window remains one regime: the evaluation / held-out-by-original-design period begins on 2023-07-31.",
            "- The panel still relies heavily on fallback PIT availability lags; interpret the diagnostics with the same fallback-coverage caveat used in brief 61.",
            "- `sfc` is value-dominated in this sample if exclusion or robustness rows weaken materially once `pillar_val` is removed.",
            "- Financials remain a thin bucket, so financials-removed and size-split robustness rows are descriptive rather than decisive.",
            "- IC is not alpha; the construction ladder is included to show harvestability under long-only constraints, not to claim causal decomposition.",
            "",
        ]
    ) + "\n"


def _latest_row(rows: list[dict[str, Any]], *, signal: str, horizon: str) -> dict[str, Any] | None:
    for row in rows:
        if row.get("signal") == signal and row.get("horizon") == horizon:
            return row
    return None


def format_methodology_markdown(payload: dict[str, Any]) -> str:
    d1_rows = payload["d1"]["ic_table"]
    d3_rows = payload["d3"]
    sfc_6m = _latest_row(d1_rows, signal="sfc", horizon="6m") or {}
    sfc_12m = _latest_row(d1_rows, signal="sfc", horizon="12m") or {}
    legacy_6m = _latest_row(d1_rows, signal="sfc_legacy", horizon="6m") or {}
    val_6m = _latest_row(d1_rows, signal="pillar_val", horizon="6m") or {}
    harvest = pd.DataFrame(payload["d4"]["harvestability"])
    bounded = harvest.loc[harvest["construction"] == "benchmark_active_pm3pct"].to_dict(orient="records")
    bounded_row = bounded[0] if bounded else {}
    return "\n".join(
        [
            "# 69 - Fundamental methodology",
            "",
            f"Methodology version: `{payload['methodology_version']}`",
            f"Evaluation / held-out-by-original-design period start: `{payload['evaluation_start_date']}`",
            "",
            "## Raw/PIT fundamentals",
            "",
            "The layer starts from point-in-time annual and period metrics joined only after publication date or the configured fallback lag. Consensus rows, where present, are joined as-of their own observation date. The output is a cross-sectional scored panel, not a valuation target sheet.",
            "",
            "## Normalization and robust preprocessing",
            "",
            "Each raw pillar component is MAD-winsorized within date, then z-scored within date and within the two peer buckets already used in production: financials versus non-financials. This keeps the preprocessing robust without pretending the market has enough names per date for fragile fine-grained neutralization.",
            "",
            "## Peer/bucket-relative scoring",
            "",
            "The peer step is intentionally two-bucket, not 19-sector. Financial statements for banks and insurers are structurally different from industrial names, so they are separated. Going further to 19-sector regression is rejected because the cross-sections are too thin; many date-sector cells would be too small for stable estimates.",
            "",
            "## Pillar construction",
            "",
            "VAL is the cross-sectional value pillar. QUAL is the quality pillar assembled from the existing Piotroski-lite, DuPont, accrual, and dividend-sustainability machinery. FMOM is the fundamental-momentum pillar built from revenue, earnings-growth, acceleration, and consensus-related metrics already in the scored panel. PMOM is still computed, unchanged, but it is now explicitly classified as a price-momentum market signal rather than a fundamental pillar.",
            "",
            "## Composite construction",
            "",
            "The production fundamental score is now `sfc = mean(VAL, QUAL, FMOM)` over available core pillars, requiring at least 2 of 3. `coverage_ratio` is therefore over the 3 core pillars. `sfc_legacy` is retained only for continuity and comparison as the prior 4-pillar mean. Equal weights remain a hard design choice; nothing is fitted. Current diagnostics should be read as value-dominated disclosure rather than as evidence for fitted reweighting.",
            "",
            "## Valuation context",
            "",
            "Intrinsic valuation and fair value stay where they belong: per-name anchors for desk discussion. They are not used to rank the cross-section here, and this pass does not redesign the valuation engine.",
            "",
            "## Predictive validation",
            "",
            f"D1 shows the evaluation / held-out-by-original-design period remains one regime, beginning on 2023-07-31. In this window the core `sfc` posts mean rank ICs of {sfc_6m.get('mean_ic', float('nan')):.4f} at 6m (HAC t {sfc_6m.get('nw_t_stat', float('nan')):.2f}, BH q {sfc_6m.get('bh_qvalue', float('nan')):.4f}, n_dates {int(sfc_6m.get('n_dates', 0))}, median N {sfc_6m.get('median_cross_section_n', float('nan')):.1f}) and {sfc_12m.get('mean_ic', float('nan')):.4f} at 12m (HAC t {sfc_12m.get('nw_t_stat', float('nan')):.2f}, BH q {sfc_12m.get('bh_qvalue', float('nan')):.4f}, n_dates {int(sfc_12m.get('n_dates', 0))}, median N {sfc_12m.get('median_cross_section_n', float('nan')):.1f}). The corresponding 6m VAL row is {val_6m.get('mean_ic', float('nan')):.4f} with HAC t {val_6m.get('nw_t_stat', float('nan')):.2f}; the 6m legacy composite row is {legacy_6m.get('mean_ic', float('nan')):.4f}. Read this honestly: the current sample is still value-dominated, and the non-value pillars are diversification inputs rather than independently validated standalone engines here.",
            "",
            "D2 is descriptive only. It measures the overlap between PMOM and the technical score and then checks PMOM IC after per-date rank residualization on the technical signal. It is included to keep the layer honest about cross-signal reuse, not to claim PMOM 'belongs' to either side.",
            "",
            "D3 is the robustness check. It reruns VAL and core SFC at 6m and 12m under date jackknife, 3-date block jackknife, influential-name drops, financials removal, and median size splits, all on the same evaluation window and with the same HAC framing. Those rows are descriptive bounds, not a license to tune toward the most flattering variant.",
            "",
            "## Portfolio interpretation",
            "",
            f"Claim C stays bounded: the score ranks names, but IC is not the same as harvestable alpha. The construction ladder reports proof-period active return, tracking error, and information ratio under equal-weight top tercile, benchmark-active uncapped, and benchmark-active ±3%. The bounded desk construction row currently shows active return {bounded_row.get('active_return', float('nan'))}, tracking error {bounded_row.get('tracking_error', float('nan'))}, and IR {bounded_row.get('information_ratio', float('nan'))}. That is the right place to discuss transfer-coefficient limits, not to backfill causal stories.",
            "",
            "## Limitations",
            "",
            "- Single reused regime: the effective evidence window is still one market regime.",
            "- Adaptive-reuse honesty: the same market history is reused across design, diagnostics, and desk interpretation, so all claims stay bounded to evaluation / held-out-by-original-design evidence rather than stronger language.",
            "- 88% fallback-PIT: most panel rows still arrive via fallback availability lags, not observed publication dates.",
            "- Value-domination: current evidence is led by VAL; equal weights remain a robustness choice, not a fitted optimum.",
            "- Thin financials: financial and insurer subsets are small, so financials-specific diagnostics are descriptive.",
            "- IC != alpha: predictive rank evidence does not guarantee long-only benchmark-relative harvestability.",
            "",
        ]
    ) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Final SFC diagnostics")
    parser.add_argument("--out-md", default="docs/fundamentals-layer/70-sfc-final-validation.md")
    parser.add_argument("--out-json", default="docs/fundamentals-layer/70-sfc-final-validation.json")
    parser.add_argument("--out-methodology", default="docs/fundamentals-layer/69-fundamental-methodology.md")
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
        config=PanelConfig(),
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
        technical = _technical_monthly_join(scored, db)
    finally:
        db.close()
    payload = run_diagnostics(scored, technical)
    Path(args.out_json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    Path(args.out_md).write_text(format_validation_markdown(payload), encoding="utf-8")
    Path(args.out_methodology).write_text(format_methodology_markdown(payload), encoding="utf-8")
    print(f"Wrote {args.out_json}")
    print(f"Wrote {args.out_md}")
    print(f"Wrote {args.out_methodology}")


if __name__ == "__main__":
    main()
