from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sqlalchemy import create_engine, text

from ...factor_selection.direct import _nw_maxlags
from ...significance import sharpe_ratio
from ..valuation import compute_valuation_ensemble, compute_symbol_valuations, default_assumptions_for_scenario
from .composite import compute_sfc
from .ic_study import SFC_PROOF_SPLIT_DATE, _build_price_loader, _load_rows_from_db, _norm_pvalue, _spearman
from .panel import PanelConfig, build_pit_panel, load_universe, publication_coverage_stats
from .market_equity import decision_date_market_equity
from .pillars import PillarConfig, compute_pillar_scores, mad_winsorized_z

HORIZONS = ("1m", "3m", "6m", "12m")
PRIMARY_HORIZON = "6m"
MIN_IC_PAIRS = 5
MIN_PORTFOLIO_NAMES = 9
DEFAULT_COST_BPS = 33.0
STRESS_COST_BPS = 75.0
METHODOLOGY_VERSION = "fundamental_methodology_bakeoff_v1_2026_07_06"
LEGACY_SFC_TAG = "sfc_custom_v2_legacy"

METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "book_equity": ("Total_Equity", "Shareholders_Equity", "Clean_Capitaux_propres", "Capitaux_propres", "Common_Equity"),
    "assets": ("Total_Assets", "Total_Actif", "Actif_Total", "Clean_Total_Assets"),
    "revenue": ("Revenue", "Chiffre_daffaires", "Clean_Chiffre_daffaires"),
    "operating_income": ("Operating_Income", "EBIT", "Resultat_Exploitation", "Clean_Resultat_Exploitation"),
    "net_income": ("NetIncome", "Net_Income", "Clean_Resultat_net", "Resultat_net", "RNPG", "Resultat_net_part_du_groupe"),
    "cash_flow_ops": ("Operating_Cash_Flow", "Cash_Flow_Operations", "CFO"),
    "free_cash_flow": ("Free_Cash_Flow", "FCF"),
    "debt": ("Total_Debt", "Debt_Total", "Dettes_de_financement"),
    "cash": ("Cash_and_Equivalents", "Cash", "Tresorerie_Actif"),
}

FINANCIAL_SECTOR_TOKENS = ("banque", "bank", "assurance", "insurance", "leasing", "financement", "credit")


@dataclass(frozen=True)
class BakeoffConfig:
    start: dt.date | None = None
    end: dt.date | None = None
    output_dir: Path = Path("research-out/fundamental-methodology-bakeoff")
    cost_bps: float = DEFAULT_COST_BPS
    stress_cost_bps: float = STRESS_COST_BPS
    primary_horizon: str = PRIMARY_HORIZON
    valuation_sample_step: int = 3
    max_valuation_rows: int | None = None
    require_observed_publication_date: bool = True


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _ratio(value: Any) -> float | None:
    out = _finite(value)
    if out is None:
        return None
    return out / 100.0 if abs(out) > 2.0 else out


def _metric(metrics: dict[str, Any], *names: str) -> float | None:
    for name in names:
        val = _finite(metrics.get(name))
        if val is not None:
            return val
    return None


def _history_value(history: list[Any], metric_names: tuple[str, ...], offset: int = 0) -> tuple[int, float] | None:
    by_year: dict[int, float] = {}
    for row in history:
        if getattr(row, "metric_name", "") not in metric_names:
            continue
        val = _finite(getattr(row, "metric_value", None))
        year = getattr(row, "statement_year", None)
        if val is None or year is None:
            continue
        by_year[int(year)] = val
    years = sorted(by_year)
    if len(years) <= offset:
        return None
    year = years[-1 - offset]
    return year, by_year[year]


def _is_financial_sector(row: pd.Series) -> bool:
    sector = str(row.get("sector") or "").lower()
    return bool(row.get("is_financial", False)) or any(token in sector for token in FINANCIAL_SECTOR_TOKENS)


def _signed_z(frame: pd.DataFrame, raw_col: str, *, positive: bool = True) -> pd.Series:
    values = pd.to_numeric(frame[raw_col], errors="coerce")
    z = pd.Series(np.nan, index=frame.index, dtype=float)
    for as_of, sub in frame.groupby("as_of_date", dropna=False):
        vals = values.loc[sub.index].dropna()
        if len(vals) < MIN_IC_PAIRS:
            continue
        z.loc[vals.index] = mad_winsorized_z(vals)
    return z if positive else -z


def _residual_by_date(frame: pd.DataFrame, y_col: str, x_cols: list[str], *, min_obs: int = 12) -> pd.Series:
    out = pd.Series(np.nan, index=frame.index, dtype=float)
    for _, sub in frame.groupby("as_of_date", dropna=False):
        cols = [y_col, *x_cols]
        work = sub[cols].replace([np.inf, -np.inf], np.nan).dropna()
        if len(work) < max(min_obs, len(x_cols) + 5):
            continue
        x = sm.add_constant(work[x_cols], has_constant="add")
        try:
            fit = sm.OLS(work[y_col], x).fit()
        except Exception:
            continue
        out.loc[work.index] = fit.resid
    return out


def add_classical_and_change_signals(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    rows: list[dict[str, Any]] = []
    for idx, row in out.iterrows():
        metrics = dict(row["metrics"])
        history = list(row["history"])
        close = _finite(row.get("close"))
        shares = _metric(metrics, "Shares_Outstanding")
        mcap = decision_date_market_equity(close=close, shares_outstanding=shares)
        book = _metric(metrics, *METRIC_ALIASES["book_equity"])
        assets = _metric(metrics, *METRIC_ALIASES["assets"])
        revenue = _metric(metrics, *METRIC_ALIASES["revenue"])
        operating_income = _metric(metrics, *METRIC_ALIASES["operating_income"])
        net_income = _metric(metrics, *METRIC_ALIASES["net_income"])
        cfo = _metric(metrics, *METRIC_ALIASES["cash_flow_ops"])
        is_fin = _is_financial_sector(row)

        current_assets = _history_value(history, METRIC_ALIASES["assets"], 0)
        previous_assets = _history_value(history, METRIC_ALIASES["assets"], 1)
        asset_growth = None
        if current_assets and previous_assets and previous_assets[1] > 0 and current_assets[0] > previous_assets[0]:
            asset_growth = current_assets[1] / previous_assets[1] - 1.0

        current_roe = _ratio(_metric(metrics, "ROE"))
        current_roa = _ratio(_metric(metrics, "ROA"))
        if current_roe is None and book and book > 0 and net_income is not None:
            current_roe = net_income / book
        if current_roa is None and assets and assets > 0 and net_income is not None:
            current_roa = net_income / assets
        op_margin = (operating_income / revenue) if revenue and revenue > 0 and operating_income is not None else None
        fcf_conversion = (cfo / net_income) if net_income and net_income > 0 and cfo is not None else None

        prev_net_income = _history_value(history, METRIC_ALIASES["net_income"], 1)
        prev_revenue = _history_value(history, METRIC_ALIASES["revenue"], 1)
        prev_operating_income = _history_value(history, METRIC_ALIASES["operating_income"], 1)
        prev_assets = _history_value(history, METRIC_ALIASES["assets"], 1)
        prev_book = _history_value(history, METRIC_ALIASES["book_equity"], 1)
        prev_cfo = _history_value(history, METRIC_ALIASES["cash_flow_ops"], 1)

        prev_roe = (prev_net_income[1] / prev_book[1]) if prev_net_income and prev_book and prev_book[1] > 0 else None
        prev_roa = (prev_net_income[1] / prev_assets[1]) if prev_net_income and prev_assets and prev_assets[1] > 0 else None
        prev_margin = (
            prev_operating_income[1] / prev_revenue[1]
            if prev_operating_income and prev_revenue and prev_revenue[1] > 0
            else None
        )
        prev_fcf_conv = (
            prev_cfo[1] / prev_net_income[1]
            if prev_cfo and prev_net_income and prev_net_income[1] > 0
            else None
        )
        rows.append(
            {
                "_idx": idx,
                "book_to_market_raw": (book / mcap) if book and book > 0 and mcap and mcap > 0 else None,
                "size_log_mcap": math.log(mcap) if mcap and mcap > 0 else None,
                "profitability_raw": current_roe if is_fin else (operating_income / book if operating_income is not None and book and book > 0 else current_roa),
                "investment_raw": None if is_fin else asset_growth,
                "op_margin_change_raw": (op_margin - prev_margin) if op_margin is not None and prev_margin is not None else None,
                "roe_change_raw": (current_roe - prev_roe) if current_roe is not None and prev_roe is not None else None,
                "roa_change_raw": (current_roa - prev_roa) if current_roa is not None and prev_roa is not None else None,
                "cashflow_conversion_change_raw": (
                    fcf_conversion - prev_fcf_conv if fcf_conversion is not None and prev_fcf_conv is not None else None
                ),
                "revenue_growth_raw": (
                    revenue / prev_revenue[1] - 1.0 if revenue is not None and prev_revenue and prev_revenue[1] > 0 else None
                ),
                "earnings_growth_raw": (
                    net_income / prev_net_income[1] - 1.0
                    if net_income is not None and prev_net_income and prev_net_income[1] > 0
                    else None
                ),
                "price_to_book_raw": (mcap / book) if book and book > 0 and mcap and mcap > 0 else None,
                "roe_level_raw": current_roe,
            }
        )
    raw = pd.DataFrame(rows).set_index("_idx")
    for col in raw.columns:
        out[col] = raw[col]
    out["book_to_market"] = _signed_z(out, "book_to_market_raw", positive=True)
    out["profitability"] = _signed_z(out, "profitability_raw", positive=True)
    out["investment_conservative"] = _signed_z(out, "investment_raw", positive=False)
    out["classical_characteristics"] = out[["book_to_market", "profitability", "investment_conservative"]].mean(axis=1, skipna=True)
    out.loc[out[["book_to_market", "profitability", "investment_conservative"]].notna().sum(axis=1) < 2, "classical_characteristics"] = np.nan
    for col in (
        "op_margin_change_raw",
        "roe_change_raw",
        "roa_change_raw",
        "cashflow_conversion_change_raw",
        "revenue_growth_raw",
        "earnings_growth_raw",
    ):
        out[col.replace("_raw", "")] = _signed_z(out, col, positive=True)
    change_cols = [
        "op_margin_change",
        "roe_change",
        "roa_change",
        "cashflow_conversion_change",
        "revenue_growth",
        "earnings_growth",
    ]
    out["fundamental_momentum"] = out[change_cols].mean(axis=1, skipna=True)
    out.loc[out[change_cols].notna().sum(axis=1) < 2, "fundamental_momentum"] = np.nan
    return out


def add_residual_value_signal(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = panel.copy()
    out["log_pb_raw"] = pd.to_numeric(out["price_to_book_raw"], errors="coerce").where(lambda s: s > 0).map(math.log)
    out["log_size_control"] = pd.to_numeric(out["size_log_mcap"], errors="coerce")
    out["residual_value_no_sector_raw"] = -_residual_by_date(out, "log_pb_raw", ["roe_level_raw", "revenue_growth_raw", "log_size_control"])
    sector_dummies = pd.get_dummies(out["sector"].fillna("UNSPECIFIED"), prefix="sector", dtype=float)
    sector_cols = list(sector_dummies.columns)
    with_sector = pd.concat([out, sector_dummies], axis=1)
    out["residual_value_sector_raw"] = -_residual_by_date(
        with_sector,
        "log_pb_raw",
        ["roe_level_raw", "revenue_growth_raw", "log_size_control", *sector_cols],
        min_obs=18,
    )
    out["residual_value"] = _signed_z(out, "residual_value_no_sector_raw", positive=True)
    fit_rows: list[dict[str, Any]] = []
    for as_of, sub in out.groupby("as_of_date", dropna=False):
        work = sub[["log_pb_raw", "roe_level_raw", "revenue_growth_raw", "log_size_control"]].dropna()
        if len(work) < 12:
            continue
        fit = sm.OLS(work["log_pb_raw"], sm.add_constant(work[["roe_level_raw", "revenue_growth_raw", "log_size_control"]], has_constant="add")).fit()
        fit_rows.append({"as_of_date": as_of, "n": len(work), "r2": float(fit.rsquared)})
    return out, pd.DataFrame(fit_rows)


def add_valuation_signal(panel: pd.DataFrame, *, sample_step: int = 3, max_rows: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = panel.copy()
    out["valuation_gap"] = np.nan
    out["valuation_usable_models"] = np.nan
    out["valuation_confidence"] = np.nan
    out["valuation_warnings"] = None
    valuation_rows: list[dict[str, Any]] = []
    assumptions = default_assumptions_for_scenario("base")
    eligible_dates = sorted(out["as_of_date"].dropna().unique())[:: max(1, int(sample_step))]
    work = out[out["as_of_date"].isin(eligible_dates)].copy()
    if max_rows is not None:
        work = work.head(max_rows)
    sectors = {str(r["symbol"]): r.get("sector") for _, r in out.drop_duplicates("symbol").iterrows()}
    for idx, row in work.iterrows():
        date_slice = out[out["as_of_date"] == row["as_of_date"]]
        peer_snapshots = list(date_slice["snapshot"])
        try:
            _, model_results = compute_symbol_valuations(
                snapshot=row["snapshot"],
                history=list(row["history"]),
                peer_snapshots=peer_snapshots,
                sectors=sectors,
                assumptions=assumptions,
                scenario="base",
            )
            ensemble = compute_valuation_ensemble(str(row["symbol"]), "base", model_results)
        except Exception as exc:
            valuation_rows.append({"symbol": row["symbol"], "as_of_date": row["as_of_date"], "error": str(exc)})
            continue
        close = _finite(row.get("close"))
        fair = _finite(ensemble.fair_value_base)
        gap = fair / close - 1.0 if fair is not None and close and close > 0 else None
        if gap is not None:
            out.loc[idx, "valuation_gap"] = gap
        out.loc[idx, "valuation_usable_models"] = ensemble.usable_model_count
        out.loc[idx, "valuation_confidence"] = ensemble.confidence_score
        out.at[idx, "valuation_warnings"] = list(ensemble.warnings)
        valuation_rows.append(
            {
                "symbol": row["symbol"],
                "as_of_date": row["as_of_date"],
                "fair_value": fair,
                "close": close,
                "valuation_gap": gap,
                "usable_model_count": ensemble.usable_model_count,
                "confidence_score": ensemble.confidence_score,
                "warnings": ";".join(ensemble.warnings),
            }
        )
    out["intrinsic_valuation"] = _signed_z(out, "valuation_gap", positive=True)
    return out, pd.DataFrame(valuation_rows)


def add_legacy_sfc(panel: pd.DataFrame, price_by_symbol: dict[str, pd.Series | None]) -> pd.DataFrame:
    scored = compute_sfc(compute_pillar_scores(panel, price_by_symbol=price_by_symbol, config=PillarConfig(pmom_months=6)))
    out = panel.copy()
    out["sfc_custom_v2"] = scored["sfc"]
    out["sfc_custom_v2_legacy"] = scored["sfc_legacy"]
    return out


def _hac_mean_t(values: list[float], *, horizon: str) -> float:
    series = pd.Series([v for v in values if math.isfinite(float(v))], dtype=float)
    if len(series) < 3:
        return 0.0
    horizon_lag = {"1m": 1, "3m": 3, "6m": 6, "12m": 12}.get(horizon, _nw_maxlags(len(series)))
    try:
        fit = sm.OLS(series, np.ones((len(series), 1))).fit(
            cov_type="HAC",
            cov_kwds={"maxlags": min(horizon_lag, max(1, len(series) - 1))},
        )
        value = float(fit.tvalues.iloc[0])
    except Exception:
        return 0.0
    return value if math.isfinite(value) else 0.0


def ic_table(frame: pd.DataFrame, signals: dict[str, str], *, sample_label: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for signal, definition in signals.items():
        for horizon in HORIZONS:
            date_ics: list[float] = []
            pair_count = 0
            for as_of, sub in frame.groupby("as_of_date", dropna=False):
                pairs = sub[[signal, f"fwd_return_{horizon}"]].replace([np.inf, -np.inf], np.nan).dropna()
                if len(pairs) < MIN_IC_PAIRS:
                    continue
                ic = _spearman(pairs[signal], pairs[f"fwd_return_{horizon}"])
                if math.isfinite(ic):
                    date_ics.append(ic)
                    pair_count += len(pairs)
            mean_ic = float(np.mean(date_ics)) if date_ics else float("nan")
            std_ic = float(np.std(date_ics, ddof=1)) if len(date_ics) > 1 else float("nan")
            t_stat = _hac_mean_t(date_ics, horizon=horizon)
            rows.append(
                {
                    "sample": sample_label,
                    "signal": signal,
                    "definition": definition,
                    "horizon": horizon,
                    "periods": len(date_ics),
                    "pairs": int(pair_count),
                    "mean_ic": mean_ic,
                    "median_ic": float(np.median(date_ics)) if date_ics else float("nan"),
                    "ic_std": std_ic,
                    "hit_rate": float(np.mean([v > 0 for v in date_ics])) if date_ics else float("nan"),
                    "hac_t_stat": t_stat,
                    "pvalue": _norm_pvalue(t_stat),
                }
            )
    return pd.DataFrame(rows)


def portfolio_table(frame: pd.DataFrame, signals: dict[str, str], *, horizon: str, cost_bps: float, sample_label: str) -> pd.DataFrame:
    """PREDICTIVE DIAGNOSTIC ONLY -- NOT A VALID STRATEGY BACKTEST.

    This samples monthly, but each `fwd_return_{horizon}` observation is an
    OVERLAPPING N-month-forward return (e.g. 6 monthly samples of a 6-month
    window share 5 of their 6 months). The `net_sharpe`/`max_drawdown`
    returned here are computed by np.cumprod-ing these overlapping monthly
    top-minus-bottom spreads as if they were sequential, non-overlapping
    per-period P&L -- they are NOT. Do not report these Sharpe/drawdown/
    cumulative-wealth numbers as tradable strategy performance, and do not
    pass a `fwd_return_*` column into a live-strategy return engine.

    For a genuine, live-like realized-return backtest use
    `live_like_strategy.py` (six-overlapping-monthly-vintage engine, real
    month-to-month price returns, real turnover/costs) -- see
    research-out/live-like-value-strategy/ for the validated results.
    Use this function only for cross-sectional predictive comparison
    (top-bottom spread as a diagnostic proxy for IC, not a return series).
    """
    rows: list[dict[str, Any]] = []
    for signal, definition in signals.items():
        returns: list[float] = []
        gross_returns: list[float] = []
        turnovers: list[float] = []
        prev_top: set[str] = set()
        for as_of, sub in frame[[signal, f"fwd_return_{horizon}", "symbol"]].replace([np.inf, -np.inf], np.nan).dropna().groupby(frame["as_of_date"]):
            ranked = sub.sort_values(signal, ascending=False)
            if len(ranked) < MIN_PORTFOLIO_NAMES:
                continue
            n_bucket = max(1, len(ranked) // 3)
            top = ranked.head(n_bucket)
            bottom = ranked.tail(n_bucket)
            top_symbols = set(top["symbol"].astype(str))
            turnover = 1.0 if not prev_top else len(top_symbols.symmetric_difference(prev_top)) / max(len(top_symbols | prev_top), 1)
            prev_top = top_symbols
            gross = float(top[f"fwd_return_{horizon}"].mean() - bottom[f"fwd_return_{horizon}"].mean())
            cost = (float(cost_bps) / 10000.0) * 2.0 * turnover
            gross_returns.append(gross)
            returns.append(gross - cost)
            turnovers.append(turnover)
        equity = np.cumprod([1.0 + r for r in returns]) if returns else np.array([])
        dd = float(np.min(equity / np.maximum.accumulate(equity) - 1.0)) if len(equity) else float("nan")
        rows.append(
            {
                "sample": sample_label,
                "signal": signal,
                "definition": definition,
                "horizon": horizon,
                "cost_bps": cost_bps,
                "periods": len(returns),
                "top_bottom_spread": float(np.mean(returns)) if returns else float("nan"),
                "gross_top_bottom_spread": float(np.mean(gross_returns)) if gross_returns else float("nan"),
                "net_sharpe": sharpe_ratio(returns, periods_per_year={"1m": 12, "3m": 4, "6m": 2, "12m": 1}[horizon]) if returns else float("nan"),
                "max_drawdown": dd,
                "turnover": float(np.mean(turnovers)) if turnovers else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def coverage_table(frame: pd.DataFrame, signals: dict[str, str], *, sample_label: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for signal, definition in signals.items():
        valid = frame[frame[signal].replace([np.inf, -np.inf], np.nan).notna()]
        rows.append(
            {
                "sample": sample_label,
                "signal": signal,
                "definition": definition,
                "observations": int(len(valid)),
                "dates": int(valid["as_of_date"].nunique()) if not valid.empty else 0,
                "symbols": int(valid["symbol"].nunique()) if not valid.empty else 0,
                "avg_names_per_date": float(valid.groupby("as_of_date")["symbol"].nunique().mean()) if not valid.empty else float("nan"),
                "financial_obs": int(valid["is_financial"].sum()) if "is_financial" in valid else 0,
                "nonfinancial_obs": int((~valid["is_financial"].astype(bool)).sum()) if "is_financial" in valid and not valid.empty else 0,
                "sectors": int(valid["sector"].nunique()) if "sector" in valid and not valid.empty else 0,
            }
        )
    return pd.DataFrame(rows)


def neutralized_ic(frame: pd.DataFrame, signals: dict[str, str], *, controls: list[str], sample_label: str) -> pd.DataFrame:
    adjusted = frame.copy()
    for signal in signals:
        adjusted[f"{signal}__neutral"] = _residual_by_date(adjusted, signal, controls, min_obs=10)
    renamed = {f"{signal}__neutral": definition for signal, definition in signals.items()}
    table = ic_table(adjusted, renamed, sample_label=sample_label)
    table["controls"] = ",".join(controls)
    table["signal"] = table["signal"].str.replace("__neutral", "", regex=False)
    return table


def pairwise_rank_correlations(frame: pd.DataFrame, signals: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for i, left in enumerate(signals):
        for right in signals[i + 1 :]:
            cors = []
            for _, sub in frame[[left, right, "as_of_date"]].dropna().groupby("as_of_date"):
                if len(sub) >= MIN_IC_PAIRS:
                    corr = _spearman(sub[left], sub[right])
                    if math.isfinite(corr):
                        cors.append(corr)
            rows.append({"left": left, "right": right, "periods": len(cors), "mean_rank_corr": float(np.mean(cors)) if cors else float("nan")})
    return pd.DataFrame(rows)


def incremental_regression(frame: pd.DataFrame, signals: list[str], *, horizon: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for as_of, sub in frame[[*signals, "size_log_mcap", f"fwd_return_{horizon}", "as_of_date"]].dropna().groupby("as_of_date"):
        if len(sub) < len(signals) + 6:
            continue
        y = sub[f"fwd_return_{horizon}"]
        x = sm.add_constant(sub[[*signals, "size_log_mcap"]], has_constant="add")
        try:
            fit = sm.OLS(y, x).fit()
        except Exception:
            continue
        for name in signals:
            rows.append({"as_of_date": as_of, "signal": name, "coef": float(fit.params.get(name, np.nan)), "n": len(sub)})
    coef = pd.DataFrame(rows)
    if coef.empty:
        return coef
    out = []
    for signal, sub in coef.groupby("signal"):
        vals = sub["coef"].dropna().tolist()
        out.append(
            {
                "signal": signal,
                "periods": len(vals),
                "mean_coef": float(np.mean(vals)) if vals else float("nan"),
                "hac_t_stat": _hac_mean_t(vals, horizon=horizon),
                "avg_n": float(sub["n"].mean()),
            }
        )
    return pd.DataFrame(out)


def _write_markdown(path: Path, title: str, sections: list[tuple[str, str]]) -> None:
    lines = [f"# {title}", "", f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}", ""]
    for heading, body in sections:
        lines.extend([f"## {heading}", "", body if body.strip() else "_No rows._", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _load_panel(config: BakeoffConfig) -> tuple[pd.DataFrame, dict[str, pd.Series | None]]:
    os.environ.setdefault("S3_ENDPOINT_URL", "http://127.0.0.1:9000")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", os.environ.get("S3_ACCESS_KEY", "minio"))
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", os.environ.get("S3_SECRET_KEY", "minio12345"))
    os.environ.setdefault("S3_BUCKET", "quant-artifacts")
    annual, period, consensus, sectors = _load_rows_from_db()
    price_loader, price_by_symbol = _build_price_loader()
    panel = build_pit_panel(
        annual_rows=annual,
        period_rows=period,
        consensus_rows=consensus,
        price_loader=price_loader,
        universe_df=load_universe(),
        sectors=sectors,
        config=PanelConfig(
            start=config.start,
            end=config.end,
            horizons=HORIZONS,
            require_observed_publication_date=config.require_observed_publication_date,
        ),
    )
    symbols = set(panel["symbol"].astype(str)) if not panel.empty else set()
    loaded: dict[str, pd.Series | None] = {}
    for symbol in symbols:
        loaded[symbol] = price_by_symbol[symbol] if symbol in price_by_symbol else price_loader(symbol)
    return panel, loaded


def _audit_database() -> dict[str, Any]:
    db_url = os.environ.get("DATABASE_URL", "postgresql+psycopg2://app:app@127.0.0.1:5555/quant")
    engine = create_engine(db_url, pool_pre_ping=True)
    out: dict[str, Any] = {}
    with engine.connect() as conn:
        for table in (
            "fundamental_annual_metric",
            "fundamental_period_metric",
            "fundamental_consensus_estimate",
            "fundamental_ensemble_result",
            "fundamental_valuation_result",
            "market_data_store",
            "stock_master",
            "fundamental_cross_section_score",
        ):
            out[table] = int(conn.execute(text(f"select count(*) from {table}")).scalar() or 0)
        out["consensus_range"] = tuple(conn.execute(text("select min(as_of_date), max(as_of_date), count(distinct symbol) from fundamental_consensus_estimate")).fetchone())
        out["persisted_valuation_range"] = tuple(conn.execute(text("select min(computed_at), max(computed_at), count(distinct symbol), count(distinct import_id) from fundamental_ensemble_result")).fetchone())
    return out


def run_bakeoff(config: BakeoffConfig) -> dict[str, Path]:
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = config.output_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    panel, price_by_symbol = _load_panel(config)
    if panel.empty:
        raise RuntimeError("PIT panel is empty; cannot run methodology bakeoff.")

    panel = add_classical_and_change_signals(panel)
    panel, residual_fit = add_residual_value_signal(panel)
    panel, valuation_details = add_valuation_signal(
        panel,
        sample_step=config.valuation_sample_step,
        max_rows=config.max_valuation_rows,
    )
    legacy = add_legacy_sfc(panel, price_by_symbol)
    panel["sfc_custom_v2"] = legacy["sfc_custom_v2"]
    panel["sfc_custom_v2_legacy"] = legacy["sfc_custom_v2_legacy"]

    primary_signals = {
        "classical_characteristics": "A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components",
        "intrinsic_valuation": "B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions",
        "fundamental_momentum": "C accounting change/improvement composite; no analyst revisions due lack of true revision history",
        "residual_value": "D cheapness residual from log(P/B) explained by ROE, revenue growth, and size",
    }
    individual_signals = {
        "book_to_market": "A1 PIT book equity / PIT market cap",
        "profitability": "A3 profitability approximation: financial ROE, non-financial operating profit/book or ROA fallback",
        "investment_conservative": "A4 negative asset growth for non-financials",
        "op_margin_change": "C delta operating margin",
        "roe_change": "C delta ROE",
        "roa_change": "C delta ROA",
        "cashflow_conversion_change": "C delta CFO/net-income conversion",
        "revenue_growth": "C latest revenue growth",
        "earnings_growth": "C latest positive-base earnings growth",
        "sfc_custom_v2": "Legacy benchmark current SFC core score",
    }
    common = panel.dropna(subset=list(primary_signals))

    native_ic = ic_table(panel, {**primary_signals, **individual_signals}, sample_label="native")
    common_ic = ic_table(common, primary_signals, sample_label="common")
    native_port = portfolio_table(panel, {**primary_signals, "sfc_custom_v2": individual_signals["sfc_custom_v2"]}, horizon=config.primary_horizon, cost_bps=config.cost_bps, sample_label="native")
    native_port_stress = portfolio_table(panel, primary_signals, horizon=config.primary_horizon, cost_bps=config.stress_cost_bps, sample_label="native_stress")
    common_port = portfolio_table(common, primary_signals, horizon=config.primary_horizon, cost_bps=config.cost_bps, sample_label="common")
    coverage = pd.concat(
        [
            coverage_table(panel, {**primary_signals, **individual_signals}, sample_label="native"),
            coverage_table(common, primary_signals, sample_label="common"),
        ],
        ignore_index=True,
    )
    controls = neutralized_ic(panel, primary_signals, controls=["size_log_mcap"], sample_label="native_size_neutral")
    corr = pairwise_rank_correlations(common, list(primary_signals))
    incremental = incremental_regression(common, list(primary_signals), horizon=config.primary_horizon)

    summary = (
        native_ic[(native_ic["horizon"] == config.primary_horizon) & (native_ic["signal"].isin(primary_signals))]
        .merge(native_port[["signal", "top_bottom_spread", "net_sharpe", "max_drawdown", "turnover"]], on="signal", how="left")
        .merge(coverage[coverage["sample"] == "native"][["signal", "observations", "dates", "avg_names_per_date"]], on="signal", how="left")
    )
    summary["methodology"] = summary["signal"].map(
        {
            "classical_characteristics": "A. Classical characteristics",
            "intrinsic_valuation": "B. Systematic intrinsic valuation",
            "fundamental_momentum": "C. Fundamental momentum/change",
            "residual_value": "D. Relative/residual valuation",
        }
    )

    tables = {
        "panel.csv": panel.drop(columns=["metrics", "history", "snapshot"], errors="ignore"),
        "coverage.csv": coverage,
        "native_ic.csv": native_ic,
        "common_ic.csv": common_ic,
        "native_portfolio.csv": native_port,
        "native_portfolio_stress.csv": native_port_stress,
        "common_portfolio.csv": common_port,
        "size_neutral_ic.csv": controls,
        "pairwise_rank_correlations.csv": corr,
        "incremental_information.csv": incremental,
        "residual_fit.csv": residual_fit,
        "valuation_details.csv": valuation_details,
        "summary.csv": summary,
    }
    for name, table in tables.items():
        table.to_csv(out_dir / name, index=False)

    db_audit = _audit_database()
    spec = {
        "methodology_version": METHODOLOGY_VERSION,
        "run_id": run_id,
        "config": {
            "primary_horizon": config.primary_horizon,
            "horizons": list(HORIZONS),
            "rebalance_frequency": "monthly panel dates",
            "portfolio": "top tercile minus bottom tercile, equal-weight, same rules for all methods",
            "cost_bps": config.cost_bps,
            "stress_cost_bps": config.stress_cost_bps,
            "valuation_sample_step": config.valuation_sample_step,
            "valuation_assumptions": "valuation.py default base assumptions treated as fixed methodology parameters",
            "common_sample_rule": "drop stock-date rows missing any of A/B/C/D primary signals",
        },
        "signals": {**primary_signals, **individual_signals},
        "signal_directions": {
            "book_to_market": "higher is better",
            "profitability": "higher is better",
            "investment_conservative": "lower asset growth is better",
            "intrinsic_valuation": "higher fair-value gap is better",
            "fundamental_momentum": "improvement is better",
            "residual_value": "lower valuation than fundamentals predict is better",
        },
        "database_audit": {k: str(v) for k, v in db_audit.items()},
        "config_hash": hashlib.sha256(json.dumps({**primary_signals, **individual_signals}, sort_keys=True).encode()).hexdigest()[:16],
    }
    (out_dir / "experiment_spec.json").write_text(json.dumps(spec, indent=2, default=str), encoding="utf-8")

    audit_body = pd.DataFrame(
        [
            {"file/module": "core/quant_core/fundamentals/cross_section/panel.py", "relevant function": "build_pit_panel", "reuse/add": "Reused canonical PIT panel, added 1m horizon", "defect/caveat": "Fallback publication lags still dominate rows"},
            {"file/module": "core/quant_core/fundamentals/cross_section/ic_study.py", "relevant function": "compute_ic_table/_load_rows_from_db/_build_price_loader", "reuse/add": "Reused DB/price loaders and IC conventions", "defect/caveat": "Existing SFC FMOM uses dt.date.today().year; not reused for Model C"},
            {"file/module": "core/quant_core/fundamentals/valuation.py", "relevant function": "compute_symbol_valuations", "reuse/add": "Reused for Model B with PIT snapshots and fixed base assumptions", "defect/caveat": "Historical WACC/assumption vintages unavailable; this is reconstructed PIT, not persisted historical desk valuation"},
            {"file/module": "services/api/app/models.py", "relevant function": "FundamentalConsensusEstimate", "reuse/add": "Audited for analyst data", "defect/caveat": "Consensus range is recent only; no true historical revision signal"},
            {"file/module": "core/quant_core/fundamentals/cross_section/methodology_bakeoff.py", "relevant function": "run_bakeoff", "reuse/add": "Added four-methodology comparison", "defect/caveat": "Small universe; residual regressions intentionally parsimonious"},
        ]
    ).to_markdown(index=False)
    _write_markdown(out_dir / "audit.md", "Repository And Data Audit", [("Code-Grounded Mapping", audit_body), ("Database Counts", pd.DataFrame([db_audit]).to_markdown(index=False))])
    _write_markdown(out_dir / "frozen_experiment_spec.md", "Frozen Experiment Specification", [("Specification", "```json\n" + json.dumps(spec, indent=2, default=str) + "\n```")])
    _write_markdown(out_dir / "coverage_report.md", "Coverage Report", [("Coverage", coverage.round(4).to_markdown(index=False)), ("Publication Availability", pd.DataFrame([publication_coverage_stats(panel)]).to_markdown(index=False))])
    _write_markdown(out_dir / "native_sample_comparison.md", "Native Sample Comparison", [("Primary Summary", summary.round(4).to_markdown(index=False)), ("Native IC", native_ic.round(4).to_markdown(index=False)), ("Native Portfolio", native_port.round(4).to_markdown(index=False))])
    _write_markdown(out_dir / "common_sample_comparison.md", "Common Sample Comparison", [("Common IC", common_ic.round(4).to_markdown(index=False)), ("Common Portfolio", common_port.round(4).to_markdown(index=False)), ("Common Coverage", coverage[coverage["sample"] == "common"].round(4).to_markdown(index=False))])
    _write_markdown(out_dir / "incremental_information_analysis.md", "Incremental Information Analysis", [("Pairwise Rank Correlations", corr.round(4).to_markdown(index=False)), ("Incremental Regression", incremental.round(4).to_markdown(index=False)), ("Size Neutral IC", controls.round(4).to_markdown(index=False))])
    _write_markdown(out_dir / "per_method_detailed_report.md", "Per-Method Detailed Report", [("Individual Signal IC", native_ic.round(4).to_markdown(index=False)), ("Residual Valuation Fit", residual_fit.round(4).to_markdown(index=False)), ("Valuation Details", valuation_details.round(4).head(200).to_markdown(index=False))])
    caveat = (
        "Decision framework: prioritize 6m native and common IC, stability/hit-rate, size robustness, net spread/Sharpe after costs, coverage, and simplicity. "
        "No weighted meta-score is used. Model B is marked reconstructed-PIT because persisted valuation vintages start in 2026 and cannot support the historical test."
    )
    _write_markdown(out_dir / "final_decision_report.md", "Final Decision Report", [("Decision Framework", caveat), ("Head-To-Head Summary", summary.round(4).to_markdown(index=False)), ("Common-Sample IC", common_ic.round(4).to_markdown(index=False)), ("Caveats", "Analyst revisions excluded; current SFC retained only as legacy benchmark; no causal claims.")])
    return {name: out_dir / name for name in ["audit.md", "frozen_experiment_spec.md", "coverage_report.md", "native_sample_comparison.md", "common_sample_comparison.md", "incremental_information_analysis.md", "per_method_detailed_report.md", "final_decision_report.md", "summary.csv"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run four-methodology fundamental signal bakeoff.")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--output-dir", default="research-out/fundamental-methodology-bakeoff")
    parser.add_argument("--valuation-sample-step", type=int, default=3)
    parser.add_argument("--max-valuation-rows", type=int, default=None)
    args = parser.parse_args()
    config = BakeoffConfig(
        start=pd.Timestamp(args.start).date() if args.start else None,
        end=pd.Timestamp(args.end).date() if args.end else None,
        output_dir=Path(args.output_dir),
        valuation_sample_step=args.valuation_sample_step,
        max_valuation_rows=args.max_valuation_rows,
    )
    paths = run_bakeoff(config)
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=2))


if __name__ == "__main__":
    main()
