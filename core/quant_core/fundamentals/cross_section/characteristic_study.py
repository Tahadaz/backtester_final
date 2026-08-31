from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import boto3
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sqlalchemy import create_engine, text

from .methodology_bakeoff import (
    DEFAULT_COST_BPS,
    HORIZONS,
    MIN_IC_PAIRS,
    PRIMARY_HORIZON,
    _finite,
    _hac_mean_t,
    _history_value,
    _metric,
    _residual_by_date,
    _signed_z,
    coverage_table,
    ic_table,
    incremental_regression,
    pairwise_rank_correlations,
    portfolio_table,
)
from .methodology_bakeoff import METRIC_ALIASES, _load_panel
from .market_equity import decision_date_market_equity
from .panel import _pit_close
from ..scoring import _piotroski_lite

METHODOLOGY_VERSION = "established_characteristic_study_v1_2026_07_06"
PREVIOUS_RUN = Path("research-out/fundamental-methodology-bakeoff/20260706-142824")


@dataclass(frozen=True)
class CharacteristicSpec:
    signal: str
    raw: str
    group: str
    formula: str
    expected_direction: str
    literature: str
    implementation: str
    required_fields: str
    applicability: str = "all where defined"


@dataclass(frozen=True)
class CharacteristicStudyConfig:
    start: dt.date | None = None
    end: dt.date | None = None
    output_dir: Path = Path("research-out/established-characteristic-study")
    cost_bps: float = DEFAULT_COST_BPS
    primary_horizon: str = PRIMARY_HORIZON
    beta_lookback: int = 252
    beta_min_obs: int = 126
    reversal_lookback: int = 21


def _ratio_or_none(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den <= 0:
        return None
    out = num / den
    return out if math.isfinite(out) else None


def _full_price_loader() -> dict[str, pd.DataFrame]:
    os.environ.setdefault("S3_ENDPOINT_URL", "http://127.0.0.1:9000")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", os.environ.get("S3_ACCESS_KEY", "minio"))
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", os.environ.get("S3_SECRET_KEY", "minio12345"))
    os.environ.setdefault("S3_BUCKET", "quant-artifacts")
    db_url = os.environ.get("DATABASE_URL", "postgresql+psycopg2://app:app@127.0.0.1:5555/quant")
    engine = create_engine(db_url, pool_pre_ping=True)
    keys: dict[str, str] = {}
    with engine.connect() as conn:
        for r in conn.execute(text("SELECT symbol, object_key FROM market_data_store WHERE timeframe='1D' AND object_key IS NOT NULL")):
            keys[str(r[0]).strip().upper()] = str(r[1])
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT_URL"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )
    out: dict[str, pd.DataFrame] = {}
    for symbol, key in keys.items():
        try:
            payload = s3.get_object(Bucket=os.environ["S3_BUCKET"], Key=key)["Body"].read()
            df = pd.read_parquet(BytesIO(payload))
        except Exception:
            continue
        if not isinstance(df.index, pd.DatetimeIndex):
            for col in ("Date", "date", "timestamp", "Timestamp"):
                if col in df.columns:
                    df = df.set_index(col)
                    break
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        out[symbol] = df.sort_index()
    return out


def _past_return(prices: pd.Series | None, as_of_date: dt.date, *, formation_days: int, skip_days: int = 0) -> float | None:
    if prices is None or prices.empty:
        return None
    series = prices.sort_index().dropna()
    end_ts = pd.Timestamp(as_of_date) - pd.tseries.offsets.BDay(skip_days)
    start_ts = pd.Timestamp(as_of_date) - pd.tseries.offsets.BDay(skip_days + formation_days)
    end = series[series.index <= end_ts]
    start = series[series.index <= start_ts]
    if end.empty or start.empty:
        return None
    p0 = _finite(start.iloc[-1])
    p1 = _finite(end.iloc[-1])
    return _ratio_or_none(p1 - p0, p0)


def _market_returns(price_frames: dict[str, pd.DataFrame]) -> pd.Series:
    returns = []
    for df in price_frames.values():
        if "Close" not in df:
            continue
        close = pd.to_numeric(df["Close"], errors="coerce").dropna().sort_index()
        close = close.groupby(level=0).last()
        returns.append(close.pct_change())
    if not returns:
        return pd.Series(dtype=float)
    market = pd.concat(returns, axis=1).mean(axis=1).dropna().sort_index()
    return market.groupby(level=0).last()


def _risk_stats(
    symbol: str,
    as_of_date: dt.date,
    price_frames: dict[str, pd.DataFrame],
    market_ret: pd.Series,
    *,
    lookback: int,
    min_obs: int,
) -> dict[str, float | None]:
    df = price_frames.get(symbol)
    if df is None or "Close" not in df:
        return {"beta": None, "total_vol": None, "idio_vol": None, "adv20": None}
    close = pd.to_numeric(df["Close"], errors="coerce").dropna().sort_index()
    close = close.groupby(level=0).last()
    ret = close.pct_change().dropna()
    end = pd.Timestamp(as_of_date)
    stock = ret[ret.index <= end].tail(lookback)
    mkt = market_ret[market_ret.index <= end].tail(lookback)
    joined = pd.concat([stock.rename("stock"), mkt.rename("market")], axis=1).dropna()
    beta = total_vol = idio_vol = None
    if len(joined) >= min_obs:
        total_vol = float(joined["stock"].std(ddof=1) * math.sqrt(252))
        x = sm.add_constant(joined["market"], has_constant="add")
        try:
            fit = sm.OLS(joined["stock"], x).fit()
            beta = float(fit.params.get("market", np.nan))
            idio_vol = float(fit.resid.std(ddof=1) * math.sqrt(252))
        except Exception:
            pass
    adv20 = None
    if "Volume" in df:
        vol = pd.to_numeric(df["Volume"], errors="coerce")
        px = pd.to_numeric(df.get("Close"), errors="coerce")
        adv = (vol * px).loc[lambda s: s.index <= end].tail(20)
        if adv.notna().sum() >= 10:
            adv20 = float(adv.mean())
    return {"beta": beta, "total_vol": total_vol, "idio_vol": idio_vol, "adv20": adv20}


def characteristic_specs() -> dict[str, CharacteristicSpec]:
    rows = [
        ("earnings_yield", "earnings_yield_raw", "value", "Net income / market cap; negative earnings retained", "higher", "Basu earnings yield / value", "approx exact using PIT net income", "NetIncome, MarketCap"),
        ("book_to_market", "book_to_market_raw", "value", "Book equity / market cap", "higher", "Rosenberg-Reid-Lanstein; Fama-French HML characteristic", "exact where book equity exists", "Book equity, MarketCap"),
        ("dividend_yield", "dividend_yield_raw", "value", "Dividends / market cap; fallback stored Dividend_Yield", "higher", "classic dividend yield", "approx exact; dividend timing annual PIT", "Dividendes, MarketCap"),
        ("cashflow_price", "cashflow_price_raw", "value", "Operating cash flow / market cap", "higher", "Lakonishok-Shleifer-Vishny cash-flow yield", "exact where CFO exists", "Operating_Cash_Flow, MarketCap"),
        ("sales_price", "sales_price_raw", "value", "Revenue / market cap", "higher", "classic sales-to-price value", "exact where revenue exists", "Revenue, MarketCap"),
        ("ebitda_ev_yield", "ebitda_ev_yield_raw", "value", "EBITDA / enterprise value", "higher", "practitioner EV/EBITDA value", "exact where EBITDA and EV exist", "EBITDA, EnterpriseValue"),
        ("small_size", "size_log_mcap", "risk_size", "-log(MarketCap)", "higher means smaller", "Banz size effect", "exact market-cap proxy", "MarketCap"),
        ("size_log_mcap", "size_log_mcap", "risk_size", "log(MarketCap)", "diagnostic/control", "size control", "exact market-cap proxy", "MarketCap"),
        ("operating_profitability_approx", "operating_profitability_raw", "profitability_quality", "Operating income / book equity; ROE fallback for financials", "higher", "Fama-French operating profitability analogue", "approximation, not exact RMW", "Operating income, book equity"),
        ("gross_profitability", "gross_profitability_raw", "profitability_quality", "Gross profit / total assets", "higher", "Novy-Marx gross profitability", "exact where gross profit exists", "Gross_Profit, Total_Assets"),
        ("roe_standalone", "roe_raw", "profitability_quality", "Net income / book equity or stored ROE", "higher", "ROE quality/profitability", "exact/derived", "NetIncome, book equity"),
        ("roa_standalone", "roa_raw", "profitability_quality", "Net income / total assets or stored ROA", "higher", "ROA profitability", "exact/derived", "NetIncome, assets"),
        ("accrual_quality", "accruals_raw", "profitability_quality", "-(Net income - CFO) / assets", "higher means lower accruals", "Sloan accruals", "approximation using earnings less CFO", "NetIncome, CFO, assets"),
        ("piotroski_lite", "piotroski_lite_raw", "profitability_quality", "Existing PIT Piotroski-lite score", "higher", "Piotroski F-score", "approximation; not exact original F-score", "multiple accounting fields"),
        ("conservative_investment", "investment_raw", "investment", "-asset growth", "higher means lower investment", "Fama-French CMA characteristic", "exact for non-financials where assets history exists", "Total assets t,t-1"),
        ("low_leverage", "leverage_raw", "distress", "-debt/assets", "higher means lower leverage", "leverage/distress anomaly", "simple established leverage proxy", "Debt, assets"),
        ("momentum_12_1", "momentum_12_1_raw", "market_behavior", "prior 252 trading-day return skipping 21 days", "higher", "Jegadeesh-Titman momentum", "exact price momentum", "daily prices"),
        ("momentum_6_1", "momentum_6_1_raw", "market_behavior", "prior 126 trading-day return skipping 21 days", "higher", "medium-term momentum variant", "exact price momentum", "daily prices"),
        ("short_reversal", "short_reversal_raw", "market_behavior", "-prior 21 trading-day return", "higher means recent loser", "short-term reversal", "exact price reversal", "daily prices"),
        ("beta_high", "beta_raw", "risk_size", "market beta over 252 days", "higher beta hypothesis", "CAPM beta", "historical market-model estimate", "daily prices"),
        ("beta_low", "beta_raw", "risk_size", "-market beta over 252 days", "low beta hypothesis", "low-beta anomaly", "historical market-model estimate", "daily prices"),
        ("low_total_volatility", "total_vol_raw", "risk_size", "-annualized realized volatility", "higher means lower vol", "low-volatility anomaly", "historical realized vol", "daily prices"),
        ("low_idio_volatility", "idio_vol_raw", "risk_size", "-market-model residual volatility", "higher means lower idio vol", "Ang-Hodrick-Xing-Zhang idiosyncratic volatility", "historical market-model residual vol", "daily prices"),
    ]
    return {r[0]: CharacteristicSpec(*r) for r in rows}


def add_characteristics(panel: pd.DataFrame, price_frames: dict[str, pd.DataFrame], config: CharacteristicStudyConfig) -> pd.DataFrame:
    out = panel.copy()
    market_ret = _market_returns(price_frames)
    rows: list[dict[str, Any]] = []
    for idx, row in out.iterrows():
        metrics = dict(row["metrics"])
        history = list(row["history"])
        close = _finite(row.get("close"))
        is_financial = bool(row.get("is_financial", False))
        shares = _metric(metrics, "Shares_Outstanding")
        mcap = decision_date_market_equity(close=close, shares_outstanding=shares)
        book = _metric(metrics, *METRIC_ALIASES["book_equity"])
        assets = _metric(metrics, *METRIC_ALIASES["assets"])
        revenue = _metric(metrics, *METRIC_ALIASES["revenue"])
        net_income = _metric(metrics, *METRIC_ALIASES["net_income"])
        cfo = _metric(metrics, *METRIC_ALIASES["cash_flow_ops"])
        dividends = _metric(metrics, "Dividendes", "Dividends_Paid", "Common_Dividends_Paid")
        ebitda = _metric(metrics, "EBITDA")
        ev = _metric(metrics, "EnterpriseValue")
        gross_profit = _metric(metrics, "Gross_Profit")
        operating_income = _metric(metrics, *METRIC_ALIASES["operating_income"])
        debt = _metric(metrics, *METRIC_ALIASES["debt"])
        roe = _metric(metrics, "ROE")
        roa = _metric(metrics, "ROA")
        if roe is not None:
            roe = roe / 100.0 if abs(roe) > 2 else roe
        if roa is not None:
            roa = roa / 100.0 if abs(roa) > 2 else roa
        if roe is None:
            roe = _ratio_or_none(net_income, book)
        if roa is None:
            roa = _ratio_or_none(net_income, assets)
        current_assets = _history_value(history, METRIC_ALIASES["assets"], 0)
        previous_assets = _history_value(history, METRIC_ALIASES["assets"], 1)
        asset_growth = None
        if current_assets and previous_assets and previous_assets[1] > 0 and current_assets[0] > previous_assets[0]:
            asset_growth = current_assets[1] / previous_assets[1] - 1.0
        accrual_ratio = _ratio_or_none((net_income - cfo) if net_income is not None and cfo is not None else None, assets)
        leverage_ratio = _ratio_or_none(debt, assets)
        df = price_frames.get(str(row["symbol"]).strip().upper())
        close_series = pd.to_numeric(df["Close"], errors="coerce").dropna() if df is not None and "Close" in df else None
        as_of = pd.Timestamp(row["as_of_date"]).date()
        risk = _risk_stats(str(row["symbol"]), as_of, price_frames, market_ret, lookback=config.beta_lookback, min_obs=config.beta_min_obs)
        piotroski = _finite(_piotroski_lite(row["snapshot"], history).get("score"))
        rows.append(
            {
                "_idx": idx,
                "market_cap_raw": mcap,
                "earnings_yield_raw": _ratio_or_none(net_income, mcap),
                # Canonical B/M policy (bm_canonical_definition.md, 2026-07-06): negative book
                # equity is excluded, not signed, matching Fama-French HML convention and
                # methodology_bakeoff.py's existing book_to_market_raw treatment. A negative
                # B/M would otherwise register as "cheap" for a handful of distressed names
                # (SNA, STR, MDP, IBC) whose book equity is negative, which is not the intended
                # economic signal.
                "book_to_market_raw": _ratio_or_none(book, mcap) if book is not None and book > 0 else None,
                "dividend_yield_raw": _ratio_or_none(dividends, mcap) if dividends is not None else _metric(metrics, "Dividend_Yield"),
                # Canonical CF/P policy (cfp_canonical_definition.md, 2026-07-06): excluded for
                # financial-sector issuers (banks, insurers, leasing/financing). Their reported
                # "Operating_Cash_Flow" is dominated by deposit-taking, policyholder float, and
                # loan-book movements rather than operating cash generation, so CFO/MarketCap is
                # not economically comparable to the non-financial CF/P characteristic.
                "cashflow_price_raw": _ratio_or_none(cfo, mcap) if not is_financial else None,
                "sales_price_raw": _ratio_or_none(revenue, mcap),
                "ebitda_ev_yield_raw": _ratio_or_none(ebitda, ev),
                "size_log_mcap": math.log(mcap) if mcap and mcap > 0 else None,
                "operating_profitability_raw": _ratio_or_none(operating_income, book) if operating_income is not None else roe,
                "gross_profitability_raw": _ratio_or_none(gross_profit, assets),
                "roe_raw": roe,
                "roa_raw": roa,
                "accruals_raw": -accrual_ratio if accrual_ratio is not None else None,
                "piotroski_lite_raw": piotroski,
                "investment_raw": asset_growth,
                "leverage_raw": -leverage_ratio if leverage_ratio is not None else None,
                "momentum_12_1_raw": _past_return(close_series, as_of, formation_days=252, skip_days=21),
                "momentum_6_1_raw": _past_return(close_series, as_of, formation_days=126, skip_days=21),
                "short_reversal_raw": -(_past_return(close_series, as_of, formation_days=config.reversal_lookback, skip_days=0) or np.nan),
                "beta_raw": risk["beta"],
                "total_vol_raw": risk["total_vol"],
                "idio_vol_raw": risk["idio_vol"],
                "adv20": risk["adv20"],
            }
        )
    raw = pd.DataFrame(rows).set_index("_idx")
    for col in raw.columns:
        out[col] = raw[col]
    specs = characteristic_specs()
    for signal, spec in specs.items():
        if signal == "book_to_market":
            out[signal] = _signed_z(out, spec.raw, positive=True)
        elif signal == "size_log_mcap":
            out[signal] = _signed_z(out, "size_log_mcap", positive=True)
        elif signal in {"small_size", "conservative_investment", "beta_low", "low_total_volatility", "low_idio_volatility"}:
            out[signal] = _signed_z(out, spec.raw, positive=False)
        else:
            out[signal] = _signed_z(out, spec.raw, positive=True)
    return out


def benjamini_hochberg_frame(table: pd.DataFrame, *, group_cols: list[str] | None = None) -> pd.DataFrame:
    out = table.copy()
    out["fdr_qvalue"] = np.nan
    out["fdr_reject_10pct"] = False
    groups = [("", out)] if not group_cols else out.groupby(group_cols, dropna=False)
    for _, sub in groups:
        clean = sub["pvalue"].astype(float).replace([np.inf, -np.inf], np.nan)
        valid = clean.dropna().sort_values()
        m = len(valid)
        if m == 0:
            continue
        qvals: dict[int, float] = {}
        min_q = 1.0
        for rank, (idx, p) in reversed(list(enumerate(valid.items(), start=1))):
            min_q = min(min_q, float(p) * m / rank)
            qvals[idx] = min_q
        reject_rank = 0
        for rank, (_, p) in enumerate(valid.items(), start=1):
            if p <= 0.10 * rank / m:
                reject_rank = rank
        rejected = set(valid.index[:reject_rank])
        for idx, q in qvals.items():
            out.loc[idx, "fdr_qvalue"] = min(float(q), 1.0)
            out.loc[idx, "fdr_reject_10pct"] = idx in rejected
    return out


def bucket_table(frame: pd.DataFrame, signals: dict[str, str], *, horizon: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for signal in signals:
        per_date = []
        for as_of, sub in frame.dropna(subset=[signal, f"fwd_return_{horizon}"]).groupby("as_of_date"):
            if len(sub) < 9:
                continue
            ranked = sub.sort_values(signal)
            try:
                bucket = pd.qcut(ranked[signal].rank(method="first"), 3, labels=["bottom", "middle", "top"])
            except ValueError:
                continue
            tmp = ranked.assign(bucket=bucket)
            means = tmp.groupby("bucket", observed=True)[f"fwd_return_{horizon}"].mean()
            counts = tmp.groupby("bucket", observed=True)["symbol"].count()
            per_date.append((means, counts))
        if not per_date:
            continue
        means_df = pd.DataFrame([x[0] for x in per_date])
        counts_df = pd.DataFrame([x[1] for x in per_date])
        rows.append(
            {
                "signal": signal,
                "periods": len(per_date),
                "bottom_return": float(means_df.get("bottom", pd.Series(dtype=float)).mean()),
                "middle_return": float(means_df.get("middle", pd.Series(dtype=float)).mean()),
                "top_return": float(means_df.get("top", pd.Series(dtype=float)).mean()),
                "top_minus_bottom": float((means_df.get("top", 0) - means_df.get("bottom", 0)).mean()),
                "avg_names_bottom": float(counts_df.get("bottom", pd.Series(dtype=float)).mean()),
                "avg_names_top": float(counts_df.get("top", pd.Series(dtype=float)).mean()),
                "monotonic": bool(
                    float(means_df.get("top", pd.Series([np.nan])).mean())
                    >= float(means_df.get("middle", pd.Series([np.nan])).mean())
                    >= float(means_df.get("bottom", pd.Series([np.nan])).mean())
                ),
            }
        )
    return pd.DataFrame(rows)


def orthogonal_ic(frame: pd.DataFrame, signals: dict[str, str]) -> pd.DataFrame:
    work = frame.copy()
    derived: dict[str, str] = {}
    for signal, definition in signals.items():
        if signal == "book_to_market":
            continue
        if "book_to_market" in work:
            col = f"{signal}__net_bm"
            work[col] = _residual_by_date(work, signal, ["book_to_market"], min_obs=10)
            derived[col] = f"{definition}; orthogonalized to B/M"
        controls = [c for c in ["book_to_market", "size_log_mcap", "adv20"] if c in work.columns and c != signal]
        if len(controls) >= 2:
            col = f"{signal}__net_bm_size_liq"
            work[col] = _residual_by_date(work, signal, controls, min_obs=12)
            derived[col] = f"{definition}; orthogonalized to B/M+size+liquidity"
    out = ic_table(work, derived, sample_label="orthogonalized")
    out["base_signal"] = out["signal"].str.replace("__net_bm_size_liq", "", regex=False).str.replace("__net_bm", "", regex=False)
    return out


def family_incremental_tables(frame: pd.DataFrame, signals_by_family: dict[str, list[str]], *, horizon: str) -> pd.DataFrame:
    rows = []
    for family, signals in signals_by_family.items():
        available = [s for s in signals if s in frame.columns and frame[s].notna().sum() > 0]
        if not available:
            continue
        controls = ["size_log_mcap"] if "size_log_mcap" not in available else []
        inc = incremental_regression(frame.dropna(subset=[*available, f"fwd_return_{horizon}"]), [*available], horizon=horizon)
        if inc.empty:
            continue
        inc["family"] = family
        rows.append(inc)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def factor_mimicking_diagnostics(frame: pd.DataFrame, *, horizon: str, cost_bps: float) -> pd.DataFrame:
    labels = {
        "small_size": "SMB_small_minus_big",
        "book_to_market": "HML_high_minus_low_bm",
        "operating_profitability_approx": "RMW_robust_minus_weak_op_prof",
        "conservative_investment": "CMA_conservative_minus_aggressive",
        "momentum_12_1": "MOM_winner_minus_loser_12_1",
    }
    port = portfolio_table(frame, labels, horizon=horizon, cost_bps=cost_bps, sample_label="factor_mimic")
    port["factor_portfolio"] = port["signal"].map(labels)
    return port


def _to_md(df: pd.DataFrame, *, rows: int | None = None) -> str:
    if df.empty:
        return "_No rows._"
    view = df.head(rows) if rows else df
    return view.round(4).to_markdown(index=False)


def _write_report(path: Path, title: str, sections: list[tuple[str, str]]) -> None:
    lines = [f"# {title}", "", f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}", ""]
    for heading, body in sections:
        lines.extend([f"## {heading}", "", body, ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def run_characteristic_study(config: CharacteristicStudyConfig) -> dict[str, Path]:
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = config.output_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    panel, _ = _load_panel(config)  # type: ignore[arg-type]
    price_frames = _full_price_loader()
    panel = add_characteristics(panel, price_frames, config)
    specs = characteristic_specs()
    signals = {name: spec.formula for name, spec in specs.items()}
    native_ic = benjamini_hochberg_frame(ic_table(panel, signals, sample_label="native"), group_cols=["horizon"])
    native_port = portfolio_table(panel, signals, horizon=config.primary_horizon, cost_bps=config.cost_bps, sample_label="native")
    coverage = coverage_table(panel, signals, sample_label="native")
    buckets = bucket_table(panel, signals, horizon=config.primary_horizon)
    primary = native_ic[native_ic["horizon"] == config.primary_horizon].copy()
    leaderboard = (
        primary.merge(native_port[["signal", "top_bottom_spread", "net_sharpe", "max_drawdown", "turnover"]], on="signal", how="left")
        .merge(coverage[["signal", "observations", "dates", "symbols", "avg_names_per_date"]], on="signal", how="left")
        .merge(buckets[["signal", "bottom_return", "middle_return", "top_return", "monotonic"]], on="signal", how="left")
    )
    leaderboard["group"] = leaderboard["signal"].map({k: v.group for k, v in specs.items()})
    leaderboard = leaderboard.sort_values(["mean_ic", "net_sharpe"], ascending=False)
    sufficient = coverage.loc[(coverage["dates"].astype(float) >= 20) & (coverage["avg_names_per_date"].astype(float) >= 20), "signal"].tolist()
    global_common = panel.dropna(subset=sufficient) if sufficient else pd.DataFrame()
    common_ic = benjamini_hochberg_frame(ic_table(global_common, {s: signals[s] for s in sufficient}, sample_label="global_common"), group_cols=["horizon"]) if not global_common.empty else pd.DataFrame()
    common_port = portfolio_table(global_common, {s: signals[s] for s in sufficient}, horizon=config.primary_horizon, cost_bps=config.cost_bps, sample_label="global_common") if not global_common.empty else pd.DataFrame()
    corr = pairwise_rank_correlations(panel, list(signals))
    orth = orthogonal_ic(panel, signals)
    family_signals = {
        "value": ["book_to_market", "earnings_yield", "cashflow_price", "dividend_yield", "sales_price", "ebitda_ev_yield"],
        "profitability_quality": ["operating_profitability_approx", "gross_profitability", "roe_standalone", "roa_standalone", "accrual_quality", "piotroski_lite"],
        "investment": ["conservative_investment"],
        "risk": ["small_size", "beta_high", "beta_low", "low_total_volatility", "low_idio_volatility"],
        "market_behavior": ["momentum_12_1", "momentum_6_1", "short_reversal"],
    }
    incremental = family_incremental_tables(panel, family_signals, horizon=config.primary_horizon)
    mimics = factor_mimicking_diagnostics(panel, horizon=config.primary_horizon, cost_bps=config.cost_bps)

    inventory = pd.DataFrame([spec.__dict__ for spec in specs.values()])
    tier_rows = []
    for _, row in leaderboard.iterrows():
        ic = float(row.get("mean_ic", np.nan))
        t = float(row.get("hac_t_stat", np.nan))
        spread = float(row.get("top_bottom_spread", np.nan))
        sharpe = float(row.get("net_sharpe", np.nan))
        monotonic = bool(row.get("monotonic", False))
        q = float(row.get("fdr_qvalue", np.nan))
        corr_match = corr[
            ((corr["left"] == "book_to_market") & (corr["right"] == row["signal"]))
            | ((corr["right"] == "book_to_market") & (corr["left"] == row["signal"]))
        ]["mean_rank_corr"].abs()
        max_corr = float(corr_match.max()) if not corr_match.empty else 0.0
        if not math.isfinite(ic) or int(float(row.get("periods", 0))) < 8:
            tier = "Tier 5 - infeasible/thin coverage"
        elif row["signal"] != "book_to_market" and row["group"] == "value" and max_corr > 0.55:
            tier = "Tier 3 - redundant with B/M/value"
        elif ic > 0.10 and t >= 2.0 and spread > 0 and sharpe > 0.5 and monotonic:
            tier = "Tier 1 - strong candidate"
        elif ic > 0.05 and spread > 0 and sharpe > 0:
            tier = "Tier 2 - promising but uncertain"
        else:
            tier = "Tier 4 - not supported"
        tier_rows.append({"signal": row["signal"], "group": row["group"], "tier": tier, "mean_ic": ic, "hac_t_stat": t, "fdr_qvalue": q, "spread": spread, "sharpe": sharpe})
    tiers = pd.DataFrame(tier_rows)

    tables = {
        "characteristic_inventory.csv": inventory,
        "native_ic.csv": native_ic,
        "native_portfolio.csv": native_port,
        "coverage.csv": coverage,
        "bucket_monotonicity.csv": buckets,
        "leaderboard.csv": leaderboard,
        "global_common_ic.csv": common_ic,
        "global_common_portfolio.csv": common_port,
        "pairwise_rank_correlations.csv": corr,
        "orthogonalized_ic.csv": orth,
        "family_incremental_regressions.csv": incremental,
        "factor_mimicking_portfolios.csv": mimics,
        "factor_tiers.csv": tiers,
        "panel_characteristics.csv": panel.drop(columns=["metrics", "history", "snapshot"], errors="ignore"),
    }
    for name, df in tables.items():
        df.to_csv(out_dir / name, index=False)
    spec = {
        "methodology_version": METHODOLOGY_VERSION,
        "continued_from": str(PREVIOUS_RUN),
        "primary_horizon": config.primary_horizon,
        "horizons": list(HORIZONS),
        "cost_bps": config.cost_bps,
        "beta_lookback": config.beta_lookback,
        "beta_min_obs": config.beta_min_obs,
        "reversal_lookback": config.reversal_lookback,
        "portfolio_rule": "equal-weight top tercile minus bottom tercile, net of same cost rule as prior bakeoff",
        "multiple_testing": "BH-FDR at 10% within each horizon across all tested characteristics",
    }
    (out_dir / "frozen_characteristic_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    _write_report(out_dir / "audit_and_inventory.md", "Audit And Curated Characteristic Inventory", [
        ("Reuse From Previous Bakeoff", f"Continues from `{PREVIOUS_RUN}`. Reuses PIT panel, 1m/3m/6m/12m forward returns, IC/HAC machinery, portfolio machinery, costs, B/M and SFC benchmarks."),
        ("Inventory", _to_md(inventory)),
        ("Coverage", _to_md(coverage)),
    ])
    _write_report(out_dir / "native_factor_leaderboard.md", "Native Coverage Factor Leaderboard", [
        ("6m Leaderboard", _to_md(leaderboard[["signal", "group", "periods", "pairs", "mean_ic", "hac_t_stat", "fdr_qvalue", "hit_rate", "top_bottom_spread", "net_sharpe", "turnover", "monotonic"]], rows=80)),
        ("Bucket Monotonicity", _to_md(buckets, rows=80)),
    ])
    _write_report(out_dir / "common_sample_comparison.md", "Common Sample Comparison", [
        ("Global Common Sample", f"Global common uses {len(sufficient)} sufficiently covered signals and {len(global_common)} stock-date rows. Very low coverage signals are excluded from this global common sample to avoid destroying the comparison."),
        ("Common IC", _to_md(common_ic, rows=120)),
        ("Common Portfolio", _to_md(common_port, rows=80)),
    ])
    _write_report(out_dir / "redundancy_incremental_analysis.md", "Redundancy And Incremental Analysis", [
        ("Pairwise Rank Correlations", _to_md(corr.sort_values("mean_rank_corr", ascending=False), rows=120)),
        ("Orthogonalized IC", _to_md(orth[orth["horizon"] == config.primary_horizon], rows=120)),
        ("Family Incremental Regressions", _to_md(incremental, rows=120)),
    ])
    _write_report(out_dir / "factor_mimicking_portfolios.md", "Canonical Factor-Mimicking Portfolio Diagnostics", [
        ("Diagnostics", _to_md(mimics, rows=80)),
        ("Construction Caveat", "These are tercile approximations, not full FF 2x3 independent sorts. Morocco breadth is too small for high-dimensional canonical sorts."),
    ])
    recommendation = (
        "Preliminary rule: promote B/M from benchmark to primary standalone fundamental signal if it remains Tier 1. "
        "Use other Tier 1/Tier 2 signals only as separate sleeves when incremental regressions and orthogonalized IC support them. "
        "Do not create an equal-weight composite from weak or redundant characteristics."
    )
    _write_report(out_dir / "final_factor_map_and_recommendation.md", "Final Factor Map And Methodology Recommendation", [
        ("Factor Tiers", _to_md(tiers, rows=100)),
        ("Recommendation", recommendation),
        ("Top Leaderboard Rows", _to_md(leaderboard[["signal", "group", "mean_ic", "hac_t_stat", "fdr_qvalue", "top_bottom_spread", "net_sharpe", "turnover", "monotonic"]], rows=30)),
    ])
    return {name: out_dir / name for name in ["audit_and_inventory.md", "native_factor_leaderboard.md", "common_sample_comparison.md", "redundancy_incremental_analysis.md", "factor_mimicking_portfolios.md", "final_factor_map_and_recommendation.md", "leaderboard.csv", "factor_tiers.csv"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Established equity characteristic study.")
    parser.add_argument("--output-dir", default="research-out/established-characteristic-study")
    args = parser.parse_args()
    paths = run_characteristic_study(CharacteristicStudyConfig(output_dir=Path(args.output_dir)))
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=2))


if __name__ == "__main__":
    main()
