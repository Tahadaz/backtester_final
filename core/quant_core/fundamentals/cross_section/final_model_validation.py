from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm

from ...significance import sharpe_ratio
from .characteristic_study import benjamini_hochberg_frame, bucket_table
from .methodology_bakeoff import (
    DEFAULT_COST_BPS,
    HORIZONS,
    MIN_IC_PAIRS,
    _hac_mean_t,
    _residual_by_date,
    _signed_z,
    coverage_table,
    ic_table,
    pairwise_rank_correlations,
    portfolio_table,
)
from .pillars import mad_winsorized_z

SOURCE_RUN = Path("research-out/established-characteristic-study/20260706-150440")
PANEL_PATH = SOURCE_RUN / "panel_characteristics.csv"
PRIMARY_HORIZON = "6m"
LEADERS = ("book_to_market", "cashflow_price")
CHALLENGERS = (
    "operating_profitability_approx",
    "conservative_investment",
    "sales_price",
    "small_size",
    "momentum_12_1",
    "accrual_quality",
    "ebitda_ev_yield",
)


@dataclass(frozen=True)
class FinalValidationConfig:
    output_dir: Path = Path("research-out/final-fundamental-model-validation")
    cost_bps: float = DEFAULT_COST_BPS
    horizon: str = PRIMARY_HORIZON


def _to_float_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for col in out.columns:
        if col in {"symbol", "sector", "archetype", "availability_counts"}:
            continue
        converted = pd.to_numeric(out[col], errors="coerce")
        if converted.notna().any() or out[col].isna().all():
            out[col] = converted
    out["as_of_date"] = pd.to_datetime(out["as_of_date"]).dt.date
    if "is_financial" in out:
        out["is_financial"] = out["is_financial"].astype(str).str.lower().isin({"true", "1"})
    return out


def load_panel(path: Path = PANEL_PATH) -> pd.DataFrame:
    return _to_float_columns(pd.read_csv(path))


def rank_transform(values: pd.Series) -> pd.Series:
    vals = pd.to_numeric(values, errors="coerce")
    return vals.rank(pct=True)


def winsorize_series(values: pd.Series, lower: float, upper: float) -> pd.Series:
    vals = pd.to_numeric(values, errors="coerce")
    clean = vals.dropna()
    if len(clean) < 3:
        return vals
    lo = float(clean.quantile(lower))
    hi = float(clean.quantile(upper))
    return vals.clip(lo, hi)


def transform_by_date(frame: pd.DataFrame, raw_col: str, method: str) -> pd.Series:
    out = pd.Series(np.nan, index=frame.index, dtype=float)
    for _, sub in frame.groupby("as_of_date", dropna=False):
        vals = pd.to_numeric(sub[raw_col], errors="coerce")
        if vals.notna().sum() < MIN_IC_PAIRS:
            continue
        if method == "raw":
            transformed = vals
        elif method == "rank":
            transformed = rank_transform(vals)
        elif method == "winsor_1_99":
            transformed = winsorize_series(vals, 0.01, 0.99)
        elif method == "winsor_2_5_97_5":
            transformed = winsorize_series(vals, 0.025, 0.975)
        elif method == "mad":
            transformed = mad_winsorized_z(vals)
        else:
            raise ValueError(f"unknown transform {method!r}")
        out.loc[sub.index] = transformed
    return out


def standardized_signal(frame: pd.DataFrame, raw_col: str, method: str) -> pd.Series:
    tmp = frame.copy()
    tmp[f"__{raw_col}_{method}"] = transform_by_date(tmp, raw_col, method)
    return _signed_z(tmp, f"__{raw_col}_{method}", positive=True)


def strategy_period_returns(
    frame: pd.DataFrame,
    signal: str,
    *,
    horizon: str,
    mode: str = "top_bottom",
    cost_bps: float = DEFAULT_COST_BPS,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    prev_top: set[str] = set()
    for as_of, sub in frame.dropna(subset=[signal, f"fwd_return_{horizon}"]).groupby("as_of_date"):
        if len(sub) < 9:
            continue
        ranked = sub.sort_values(signal, ascending=False)
        n = max(1, len(ranked) // 3)
        top = ranked.head(n)
        bottom = ranked.tail(n)
        top_symbols = set(top["symbol"].astype(str))
        turnover = 1.0 if not prev_top else len(top_symbols.symmetric_difference(prev_top)) / max(len(top_symbols | prev_top), 1)
        prev_top = top_symbols
        cost = (float(cost_bps) / 10000.0) * 2.0 * turnover
        market_ret = float(ranked[f"fwd_return_{horizon}"].mean())
        top_ret = float(top[f"fwd_return_{horizon}"].mean())
        bottom_ret = float(bottom[f"fwd_return_{horizon}"].mean())
        gross = top_ret - bottom_ret if mode == "top_bottom" else top_ret
        net = gross - cost
        rows.append(
            {
                "as_of_date": as_of,
                "return": net,
                "gross_return": gross,
                "market_return": market_ret,
                "top_return": top_ret,
                "bottom_return": bottom_ret,
                "turnover": turnover,
                "holdings": n,
                "avg_log_mcap": float(pd.to_numeric(top.get("size_log_mcap"), errors="coerce").mean()),
                "avg_adv20": float(pd.to_numeric(top.get("adv20"), errors="coerce").mean()),
            }
        )
    return pd.DataFrame(rows)


def performance_from_returns(returns: pd.Series, *, periods_per_year: int = 2) -> dict[str, float]:
    vals = pd.to_numeric(returns, errors="coerce").dropna()
    if vals.empty:
        return {"mean_return": np.nan, "sharpe": np.nan, "max_drawdown": np.nan}
    equity = (1.0 + vals).cumprod()
    dd = equity / equity.cummax() - 1.0
    return {"mean_return": float(vals.mean()), "sharpe": sharpe_ratio(vals, periods_per_year=periods_per_year), "max_drawdown": float(dd.min())}


def market_alpha_table(series_map: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, df in series_map.items():
        work = df[["return", "market_return"]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(work) < 8:
            rows.append({"strategy": name, "periods": len(work), "alpha": np.nan, "alpha_hac_t": np.nan, "beta": np.nan, "r2": np.nan, "resid_vol": np.nan})
            continue
        x = sm.add_constant(work["market_return"], has_constant="add")
        fit = sm.OLS(work["return"], x).fit(cov_type="HAC", cov_kwds={"maxlags": min(6, len(work) - 1)})
        rows.append(
            {
                "strategy": name,
                "periods": len(work),
                "alpha": float(fit.params.get("const", np.nan)),
                "alpha_hac_t": float(fit.tvalues.get("const", np.nan)),
                "beta": float(fit.params.get("market_return", np.nan)),
                "r2": float(fit.rsquared),
                "resid_vol": float(fit.resid.std(ddof=1)),
            }
        )
    return pd.DataFrame(rows)


def extreme_audit(frame: pd.DataFrame, signals: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    extremes = []
    for signal in signals:
        raw = f"{signal}_raw" if f"{signal}_raw" in frame.columns else signal
        vals = pd.to_numeric(frame.get(raw), errors="coerce")
        rows.append(
            {
                "signal": signal,
                "raw_col": raw,
                "count": int(vals.notna().sum()),
                "non_finite": int((~np.isfinite(vals.dropna())).sum()),
                "min": float(vals.min()) if vals.notna().any() else np.nan,
                "p0_5": float(vals.quantile(0.005)) if vals.notna().any() else np.nan,
                "p1": float(vals.quantile(0.01)) if vals.notna().any() else np.nan,
                "p5": float(vals.quantile(0.05)) if vals.notna().any() else np.nan,
                "median": float(vals.median()) if vals.notna().any() else np.nan,
                "p95": float(vals.quantile(0.95)) if vals.notna().any() else np.nan,
                "p99": float(vals.quantile(0.99)) if vals.notna().any() else np.nan,
                "p99_5": float(vals.quantile(0.995)) if vals.notna().any() else np.nan,
                "max": float(vals.max()) if vals.notna().any() else np.nan,
                "negative_values": int((vals < 0).sum()),
                "near_zero_market_cap": int((pd.to_numeric(frame.get("market_cap_raw"), errors="coerce").abs() < 1e-6).sum()),
                "negative_book_equity": int((pd.to_numeric(frame.get("book_to_market_raw"), errors="coerce") < 0).sum()) if signal == "book_to_market" else 0,
                "negative_cfo": int((pd.to_numeric(frame.get("cashflow_price_raw"), errors="coerce") < 0).sum()) if signal == "cashflow_price" else 0,
            }
        )
        top = frame.assign(abs_signal=vals.abs()).sort_values("abs_signal", ascending=False).head(10)
        for _, row in top.iterrows():
            extremes.append(
                {
                    "signal": signal,
                    "symbol": row.get("symbol"),
                    "as_of_date": row.get("as_of_date"),
                    "value": row.get(raw),
                    "market_cap_raw": row.get("market_cap_raw"),
                    "book_to_market_raw": row.get("book_to_market_raw"),
                    "cashflow_price_raw": row.get("cashflow_price_raw"),
                    "sales_price_raw": row.get("sales_price_raw"),
                    "sector": row.get("sector"),
                    "is_financial": row.get("is_financial"),
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(extremes)


def outlier_robustness(frame: pd.DataFrame, raw_map: dict[str, str], *, horizon: str, cost_bps: float) -> pd.DataFrame:
    rows = []
    methods = ("raw", "rank", "winsor_1_99", "winsor_2_5_97_5", "mad")
    for signal, raw_col in raw_map.items():
        for method in methods:
            work = frame.copy()
            col = f"{signal}_{method}"
            work[col] = standardized_signal(work, raw_col, method)
            ic = ic_table(work, {col: f"{signal} {method}"}, sample_label=method)
            port = portfolio_table(work, {col: f"{signal} {method}"}, horizon=horizon, cost_bps=cost_bps, sample_label=method)
            bucket = bucket_table(work, {col: col}, horizon=horizon)
            row = ic[ic["horizon"] == horizon].iloc[0].to_dict()
            if not port.empty:
                row.update(port.iloc[0].to_dict())
            if not bucket.empty:
                row["monotonic"] = bool(bucket.iloc[0]["monotonic"])
            row["base_signal"] = signal
            row["method"] = method
            rows.append(row)
    return pd.DataFrame(rows)


def leave_one_influence(frame: pd.DataFrame, signal: str, *, by: str, horizon: str) -> pd.DataFrame:
    base = ic_table(frame, {signal: signal}, sample_label="base")
    base_ic = float(base[(base["signal"] == signal) & (base["horizon"] == horizon)]["mean_ic"].iloc[0])
    rows = []
    for value in sorted(frame[by].dropna().unique()):
        sub = frame[frame[by] != value]
        table = ic_table(sub, {signal: signal}, sample_label=f"minus_{value}")
        line = table[(table["signal"] == signal) & (table["horizon"] == horizon)]
        if line.empty:
            continue
        rows.append({"signal": signal, "excluded": value, "by": by, "mean_ic": float(line.iloc[0]["mean_ic"]), "delta_vs_base": float(line.iloc[0]["mean_ic"]) - base_ic, "hac_t_stat": float(line.iloc[0]["hac_t_stat"])})
    return pd.DataFrame(rows).sort_values("delta_vs_base")


def filtered_comparisons(frame: pd.DataFrame, signals: dict[str, str], *, horizon: str, cost_bps: float) -> pd.DataFrame:
    filters: dict[str, pd.Series] = {"full": pd.Series(True, index=frame.index)}
    filters["nonfinancial"] = ~frame["is_financial"].astype(bool)
    filters["financial"] = frame["is_financial"].astype(bool)
    mcap = pd.to_numeric(frame["market_cap_raw"], errors="coerce")
    adv = pd.to_numeric(frame["adv20"], errors="coerce")
    filters["exclude_bottom_10pct_mcap"] = mcap >= mcap.quantile(0.10)
    filters["exclude_bottom_20pct_mcap"] = mcap >= mcap.quantile(0.20)
    filters["large_cap_half"] = mcap >= mcap.median()
    filters["exclude_lowest_liquidity_quintile"] = adv >= adv.quantile(0.20)
    rows = []
    for name, mask in filters.items():
        sub = frame[mask.fillna(False)].copy()
        ic = ic_table(sub, signals, sample_label=name)
        port = portfolio_table(sub, signals, horizon=horizon, cost_bps=cost_bps, sample_label=name)
        cov = coverage_table(sub, signals, sample_label=name)
        merged = ic[ic["horizon"] == horizon].merge(port[["signal", "top_bottom_spread", "net_sharpe", "max_drawdown", "turnover"]], on="signal", how="left").merge(cov[["signal", "avg_names_per_date", "dates", "symbols"]], on="signal", how="left")
        rows.append(merged)
    return pd.concat(rows, ignore_index=True)


def combination_signals(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["value_equal_rank"] = out.groupby("as_of_date")[["book_to_market", "cashflow_price"]].transform(lambda s: s.rank(pct=True)).mean(axis=1)
    # Separate sleeves are evaluated at portfolio-return level; this score is only for IC comparability.
    out["value_intersection_top_tercile"] = np.nan
    out["value_bm_confirmed"] = np.nan
    out["value_cfp_confirmed"] = np.nan
    out["cashflow_price_net_bm"] = _residual_by_date(out, "cashflow_price", ["book_to_market"], min_obs=10)
    out["value_orthogonal_combo"] = out[["book_to_market", "cashflow_price_net_bm"]].mean(axis=1)
    for _, sub in out.groupby("as_of_date"):
        if len(sub.dropna(subset=["book_to_market", "cashflow_price"])) < 9:
            continue
        bm_rank = sub["book_to_market"].rank(pct=True)
        cfp_rank = sub["cashflow_price"].rank(pct=True)
        both_top = (bm_rank >= 2 / 3) & (cfp_rank >= 2 / 3)
        out.loc[sub.index, "value_intersection_top_tercile"] = both_top.astype(float)
        out.loc[sub.index, "value_bm_confirmed"] = sub["book_to_market"].where(cfp_rank > 1 / 3)
        out.loc[sub.index, "value_cfp_confirmed"] = sub["cashflow_price"].where(bm_rank > 1 / 3)
    return out


def sleeve_returns(frame: pd.DataFrame, *, horizon: str, cost_bps: float) -> pd.DataFrame:
    bm = strategy_period_returns(frame, "book_to_market", horizon=horizon, cost_bps=cost_bps)
    cfp = strategy_period_returns(frame, "cashflow_price", horizon=horizon, cost_bps=cost_bps)
    merged = bm[["as_of_date", "return", "market_return"]].rename(columns={"return": "bm"}).merge(
        cfp[["as_of_date", "return"]].rename(columns={"return": "cfp"}), on="as_of_date", how="inner"
    )
    merged["return"] = 0.5 * merged["bm"] + 0.5 * merged["cfp"]
    merged["gross_return"] = merged["return"]
    merged["turnover"] = np.nan
    return merged


def architecture_bakeoff(frame: pd.DataFrame, *, horizon: str, cost_bps: float) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    work = combination_signals(frame)
    score_signals = {
        "book_to_market": "M1 B/M alone",
        "cashflow_price": "M2 CF/P alone",
        "value_equal_rank": "M3 equal-weight rank composite",
        "value_intersection_top_tercile": "M5 top tercile in both",
        "value_bm_confirmed": "M6 B/M primary, CF/P not bottom tercile",
        "value_cfp_confirmed": "M6 CF/P primary, B/M not bottom tercile",
        "value_orthogonal_combo": "M7 B/M + CF/P residualized against B/M",
    }
    port = portfolio_table(work, score_signals, horizon=horizon, cost_bps=cost_bps, sample_label="architecture")
    ic = ic_table(work, score_signals, sample_label="architecture")
    rows = ic[ic["horizon"] == horizon].merge(port[["signal", "top_bottom_spread", "net_sharpe", "max_drawdown", "turnover"]], on="signal", how="left")
    series = {sig: strategy_period_returns(work, sig, horizon=horizon, cost_bps=cost_bps) for sig in score_signals}
    series["separate_sleeves_50_50"] = sleeve_returns(work, horizon=horizon, cost_bps=cost_bps)
    sleeve_perf = performance_from_returns(series["separate_sleeves_50_50"]["return"])
    rows = pd.concat([rows, pd.DataFrame([{"signal": "separate_sleeves_50_50", "mean_ic": np.nan, "hac_t_stat": np.nan, "hit_rate": np.nan, "top_bottom_spread": sleeve_perf["mean_return"], "net_sharpe": sleeve_perf["sharpe"], "max_drawdown": sleeve_perf["max_drawdown"], "turnover": np.nan}])], ignore_index=True)
    return rows, series


def third_factor_tests(frame: pd.DataFrame, challengers: tuple[str, ...], *, horizon: str) -> pd.DataFrame:
    rows = []
    for ch in challengers:
        if ch not in frame:
            continue
        work = frame.dropna(subset=["book_to_market", "cashflow_price", ch, f"fwd_return_{horizon}", "size_log_mcap", "adv20"])
        if work.empty:
            continue
        # Per-date coefficient on challenger in parsimonious BM+CFP+controls regression.
        coefs = []
        for _, sub in work.groupby("as_of_date"):
            if len(sub) < 12:
                continue
            x = sm.add_constant(sub[["book_to_market", "cashflow_price", ch, "size_log_mcap", "adv20"]], has_constant="add")
            try:
                fit = sm.OLS(sub[f"fwd_return_{horizon}"], x).fit()
            except Exception:
                continue
            coefs.append(float(fit.params.get(ch, np.nan)))
        rows.append({"challenger": ch, "periods": len(coefs), "mean_coef": float(np.nanmean(coefs)) if coefs else np.nan, "hac_t_stat": _hac_mean_t(coefs, horizon=horizon) if coefs else np.nan})
    return pd.DataFrame(rows)


def _md(df: pd.DataFrame, rows: int | None = None) -> str:
    if df.empty:
        return "_No rows._"
    view = df.head(rows) if rows else df
    return view.round(4).to_markdown(index=False)


def _write(path: Path, title: str, sections: list[tuple[str, str]]) -> None:
    lines = [f"# {title}", "", f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}", ""]
    for h, body in sections:
        lines.extend([f"## {h}", "", body, ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def run_final_validation(config: FinalValidationConfig) -> dict[str, Path]:
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = config.output_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    frame = load_panel()
    # Recompute the two leader standardized columns from raw values to avoid relying on early-date blank z-scores.
    frame["book_to_market"] = standardized_signal(frame, "book_to_market_raw", "raw")
    frame["cashflow_price"] = standardized_signal(frame, "cashflow_price_raw", "raw")
    audit_signals = ["book_to_market", "cashflow_price", "sales_price", "earnings_yield", "ebitda_ev_yield", "operating_profitability_approx", "gross_profitability", "conservative_investment", "small_size", "momentum_12_1"]
    audit, extremes = extreme_audit(frame, audit_signals)
    robust = outlier_robustness(frame, {"book_to_market": "book_to_market_raw", "cashflow_price": "cashflow_price_raw"}, horizon=config.horizon, cost_bps=config.cost_bps)
    loo_stock = pd.concat([leave_one_influence(frame, s, by="symbol", horizon=config.horizon) for s in LEADERS], ignore_index=True)
    loo_date = pd.concat([leave_one_influence(frame, s, by="as_of_date", horizon=config.horizon) for s in LEADERS], ignore_index=True)
    filters = filtered_comparisons(frame, {"book_to_market": "B/M", "cashflow_price": "CF/P"}, horizon=config.horizon, cost_bps=config.cost_bps)
    sector_rows = []
    for sector in sorted(frame["sector"].dropna().unique()):
        sub = frame[frame["sector"] != sector]
        if len(sub) < 100:
            continue
        table = ic_table(sub, {"book_to_market": "B/M", "cashflow_price": "CF/P"}, sample_label=f"minus_{sector}")
        sector_rows.append(table[table["horizon"] == config.horizon].assign(excluded_sector=sector))
    sector_influence = pd.concat(sector_rows, ignore_index=True) if sector_rows else pd.DataFrame()
    leader_series = {
        "bm_top_bottom": strategy_period_returns(frame, "book_to_market", horizon=config.horizon, mode="top_bottom", cost_bps=config.cost_bps),
        "cfp_top_bottom": strategy_period_returns(frame, "cashflow_price", horizon=config.horizon, mode="top_bottom", cost_bps=config.cost_bps),
        "bm_long_top": strategy_period_returns(frame, "book_to_market", horizon=config.horizon, mode="long_top", cost_bps=config.cost_bps),
        "cfp_long_top": strategy_period_returns(frame, "cashflow_price", horizon=config.horizon, mode="long_top", cost_bps=config.cost_bps),
    }
    arch, arch_series = architecture_bakeoff(frame, horizon=config.horizon, cost_bps=config.cost_bps)
    leader_series.update({f"arch_{k}": v for k, v in arch_series.items()})
    market_alpha = market_alpha_table(leader_series)
    third = third_factor_tests(frame, CHALLENGERS, horizon=config.horizon)
    corr = pairwise_rank_correlations(frame, ["book_to_market", "cashflow_price", *CHALLENGERS])
    common = frame.dropna(subset=["book_to_market", "cashflow_price"])
    common_cmp = ic_table(common, {"book_to_market": "B/M", "cashflow_price": "CF/P"}, sample_label="pairwise_common")
    common_port = portfolio_table(common, {"book_to_market": "B/M", "cashflow_price": "CF/P"}, horizon=config.horizon, cost_bps=config.cost_bps, sample_label="pairwise_common")
    bm_cfp = common_cmp[common_cmp["horizon"] == config.horizon].merge(common_port[["signal", "top_bottom_spread", "net_sharpe", "max_drawdown", "turnover"]], on="signal", how="left")
    profitability_diag = audit[audit["signal"].isin(["operating_profitability_approx", "gross_profitability"])].copy()
    for name, df in {
        "extreme_audit.csv": audit,
        "extreme_observations.csv": extremes,
        "outlier_robustness.csv": robust,
        "leave_one_stock.csv": loo_stock,
        "leave_one_date.csv": loo_date,
        "size_liquidity_sector_filters.csv": filters,
        "leave_one_sector.csv": sector_influence,
        "market_alpha.csv": market_alpha,
        "bm_cfp_common_comparison.csv": bm_cfp,
        "third_factor_tests.csv": third,
        "architecture_bakeoff.csv": arch,
        "pairwise_correlations.csv": corr,
        "profitability_diagnostic.csv": profitability_diag,
    }.items():
        df.to_csv(out_dir / name, index=False)
    _write(out_dir / "audit_extreme_values.md", "Extreme Values And Data Quality Audit", [("Distributions", _md(audit)), ("Top Extremes", _md(extremes, 120)), ("Conclusion", "No automatic deletions were applied. Negative CFO and negative earnings are preserved as economic states; CF/P production should exclude financial firms unless CFO comparability is explicitly approved.")])
    _write(out_dir / "outlier_robustness.md", "Outlier Robustness", [("Transform Specifications", _md(robust)), ("Leave-One-Stock", _md(loo_stock, 80)), ("Leave-One-Date", _md(loo_date, 80))])
    _write(out_dir / "sector_financials_robustness.md", "Sector And Financial-Firm Robustness", [("Financial/Nonfinancial Filters", _md(filters[filters["sample"].isin(["full", "nonfinancial", "financial"])])), ("Leave-One-Sector", _md(sector_influence, 120))])
    _write(out_dir / "size_liquidity_robustness.md", "Size Liquidity And Microcap Robustness", [("Filters", _md(filters)), ("Interpretation", "B/M and CF/P are compared under fixed cap/liquidity exclusions. These are robustness checks, not optimized cutoffs.")])
    _write(out_dir / "market_alpha_attribution.md", "Market Alpha Attribution", [("Raw Market Attribution", _md(market_alpha)), ("Risk-Free Caveat", "No historical Moroccan risk-free series was available in the saved artifacts; alpha is raw return alpha versus equal-weight universe forward return.")])
    _write(out_dir / "bm_vs_cfp_final_comparison.md", "B/M Vs CF/P Final Comparison", [("Pairwise Common", _md(bm_cfp)), ("Correlation", _md(corr[((corr["left"].isin(LEADERS)) & (corr["right"].isin(LEADERS))) | ((corr["left"].eq("book_to_market")) & (corr["right"].eq("cashflow_price")))]))])
    _write(out_dir / "third_factor_admission_test.md", "Third Factor Admission Test", [("Challengers", _md(third)), ("Pairwise Correlations", _md(corr, 120)), ("Decision Rule", "Admit no third factor unless it is stable standalone, incremental beyond B/M+CF/P+size+liquidity, and harvestable.")])
    _write(out_dir / "profitability_anomaly_diagnostic.md", "Profitability Anomaly Diagnostic", [("Distribution", _md(profitability_diag)), ("Conclusion", "The profitability results are best classified as accounting-comparability/confounding plus insufficient evidence. Do not flip the sign into a production alpha.")])
    _write(out_dir / "combination_architecture_bakeoff.md", "Combination Architecture Bakeoff", [("Architectures", _md(arch)), ("Market Alpha For Architectures", _md(market_alpha[market_alpha["strategy"].str.startswith("arch_")]))])
    verdict = (
        "Freeze production as two transparent separate signals: Structural Value (B/M) and Cash-Flow Value (CF/P for non-financials by default). "
        "Do not use old SFC as production selector; keep as legacy benchmark/research. "
        "Implement first strategy as separate 50/50 B/M and CF/P sleeves with displayed component disagreement; keep B/M-only as fallback when CF/P is not economically applicable."
    )
    _write(out_dir / "final_production_recommendation.md", "Final Production Recommendation", [("Verdict", verdict), ("Architecture Bakeoff", _md(arch)), ("B/M Vs CF/P", _md(bm_cfp)), ("Market Alpha", _md(market_alpha)), ("Third Factor Decision", _md(third))])
    (out_dir / "run_config.json").write_text(json.dumps({"source_run": str(SOURCE_RUN), "horizon": config.horizon, "cost_bps": config.cost_bps}, indent=2), encoding="utf-8")
    return {name: out_dir / name for name in [
        "audit_extreme_values.md",
        "outlier_robustness.md",
        "sector_financials_robustness.md",
        "size_liquidity_robustness.md",
        "market_alpha_attribution.md",
        "bm_vs_cfp_final_comparison.md",
        "third_factor_admission_test.md",
        "profitability_anomaly_diagnostic.md",
        "combination_architecture_bakeoff.md",
        "final_production_recommendation.md",
    ]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Final validation gate for fundamental production model.")
    parser.add_argument("--output-dir", default="research-out/final-fundamental-model-validation")
    args = parser.parse_args()
    paths = run_final_validation(FinalValidationConfig(output_dir=Path(args.output_dir)))
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=2))


if __name__ == "__main__":
    main()
