from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from quant_core.significance import monte_carlo_luck_test, sharpe_ratio

RebalanceFrequency = Literal["monthly", "quarterly"]

SFC_PORTFOLIO_CONFIG_ID = "pmom_6_1"
SFC_PROOF_SPLIT_DATE = dt.date(2023, 7, 31)
SFC_STUDY_END_DATE = dt.date(2026, 7, 5)


@dataclass(frozen=True)
class SfcPortfolioBacktestConfig:
    rebalance: RebalanceFrequency = "monthly"
    cost_bps: float = 33.0
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    initial_equity: float = 1.0
    split_date: dt.date = SFC_PROOF_SPLIT_DATE
    study_end_date: dt.date = SFC_STUDY_END_DATE
    config_id: str = SFC_PORTFOLIO_CONFIG_ID
    config_hash: str | None = None


def _date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return pd.Timestamp(value).date()


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def segment_for_date(value: Any, *, split_date: dt.date = SFC_PROOF_SPLIT_DATE, study_end_date: dt.date = SFC_STUDY_END_DATE) -> str:
    date = _date(value)
    if date < split_date:
        return "selection"
    if date <= study_end_date:
        return "proof"
    return "live"


def _periods_per_year(rebalance: RebalanceFrequency) -> int:
    return 4 if rebalance == "quarterly" else 12


def _as_series(series: pd.Series | None) -> pd.Series | None:
    if series is None:
        return None
    out = pd.Series(series).dropna().astype(float).sort_index()
    if out.empty:
        return None
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out


def _pit_price(series: pd.Series | None, as_of: dt.date) -> tuple[float | None, dt.date | None]:
    prices = _as_series(series)
    if prices is None:
        return None, None
    idx = prices.index.searchsorted(pd.Timestamp(as_of), side="right") - 1
    if idx < 0:
        return None, None
    value = float(prices.iloc[idx])
    if not math.isfinite(value) or value <= 0:
        return None, None
    return value, pd.Timestamp(prices.index[idx]).date()


def _target_rebalance_dates(panel: pd.DataFrame, config: SfcPortfolioBacktestConfig) -> list[dt.date]:
    dates = sorted({_date(v) for v in panel.get("as_of_date", [])})
    if config.start_date is not None:
        dates = [d for d in dates if d >= config.start_date]
    if config.end_date is not None:
        dates = [d for d in dates if d <= config.end_date]
    if config.rebalance == "monthly":
        return dates
    selected: list[dt.date] = []
    seen: set[tuple[int, int]] = set()
    for date in dates:
        quarter = (date.month - 1) // 3 + 1
        key = (date.year, quarter)
        if key in seen:
            continue
        seen.add(key)
        selected.append(date)
    return selected


def _valid_score_rows(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["sfc"] = pd.to_numeric(out["sfc"], errors="coerce")
    out = out.dropna(subset=["sfc"])
    if "is_covered" in out.columns:
        out = out[out["is_covered"].astype(bool)]
    if "liquidity_pass" in out.columns:
        out = out[out["liquidity_pass"].fillna(False).astype(bool)]
    return out


def _top_tercile_holdings(sub: pd.DataFrame) -> pd.DataFrame:
    ranked = _valid_score_rows(sub).sort_values(["sfc", "symbol"], ascending=[False, True])
    if ranked.empty:
        return ranked
    n_top = max(1, int(math.ceil(len(ranked) / 3.0)))
    top = ranked.head(n_top).copy()
    top["weight"] = 1.0 / float(n_top)
    return top


def one_way_turnover(previous: dict[str, float], current: dict[str, float]) -> float:
    symbols = set(previous) | set(current)
    if not symbols:
        return 0.0
    if not previous or not current:
        return min(1.0, sum(abs(float(current.get(sym, 0.0)) - float(previous.get(sym, 0.0))) for sym in symbols))
    return 0.5 * sum(abs(float(current.get(sym, 0.0)) - float(previous.get(sym, 0.0))) for sym in symbols)


def _weighted_return(
    weights: dict[str, float],
    *,
    start: dt.date,
    end: dt.date,
    price_by_symbol: dict[str, pd.Series | None],
) -> tuple[float | None, int]:
    returns: list[float] = []
    weighted = 0.0
    stale_count = 0
    for symbol, weight in weights.items():
        start_px, start_px_date = _pit_price(price_by_symbol.get(symbol), start)
        end_px, end_px_date = _pit_price(price_by_symbol.get(symbol), end)
        if start_px is None or end_px is None:
            continue
        if start_px_date != start:
            stale_count += 1
        if end_px_date != end:
            stale_count += 1
        ret = end_px / start_px - 1.0
        weighted += float(weight) * ret
        returns.append(ret)
    if not returns:
        return None, stale_count
    return weighted, stale_count


def _universe_weights(sub: pd.DataFrame) -> dict[str, float]:
    valid = _valid_score_rows(sub)
    symbols = sorted(str(sym).strip().upper() for sym in valid["symbol"].dropna().unique())
    if not symbols:
        return {}
    weight = 1.0 / float(len(symbols))
    return {sym: weight for sym in symbols}


def _benchmark_return(series: pd.Series | None, *, start: dt.date, end: dt.date) -> float | None:
    start_px, _ = _pit_price(series, start)
    end_px, _ = _pit_price(series, end)
    if start_px is None or end_px is None:
        return None
    return end_px / start_px - 1.0


def _max_drawdown(equity: list[float]) -> float | None:
    if not equity:
        return None
    peak = equity[0]
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            max_dd = min(max_dd, value / peak - 1.0)
    return float(max_dd)


def _summary_stats(
    rows: list[dict[str, Any]],
    *,
    equity_curve: list[dict[str, Any]],
    segment: str,
    periods_per_year: int,
) -> dict[str, Any]:
    period_rows = [r for r in rows if segment == "combined" or r["segment"] == segment]
    curve_rows = [p for p in equity_curve if segment == "combined" or p["segment"] == segment]
    returns = [float(r["strategy_return_net"]) for r in period_rows if _finite(r.get("strategy_return_net")) is not None]
    active = [float(r["active_return"]) for r in period_rows if _finite(r.get("active_return")) is not None]
    tracking = float(np.std(active, ddof=1) * math.sqrt(periods_per_year)) if len(active) >= 2 else None
    years = None
    cagr = None
    if len(curve_rows) >= 2:
        start = _date(curve_rows[0]["date"])
        end = _date(curve_rows[-1]["date"])
        years = max((end - start).days / 365.25, 0.0)
        start_eq = _finite(curve_rows[0].get("strategy"))
        end_eq = _finite(curve_rows[-1].get("strategy"))
        if start_eq and end_eq and years > 0:
            cagr = (end_eq / start_eq) ** (1.0 / years) - 1.0
    return {
        "segment": segment,
        "label": {
            "selection": "sélection",
            "proof": "validé sur 2023–2026 (une seule période de marché)",
            "live": "live",
            "combined": "combiné",
        }.get(segment, segment),
        "periods": len(period_rows),
        "start_date": curve_rows[0]["date"] if curve_rows else None,
        "end_date": curve_rows[-1]["date"] if curve_rows else None,
        "total_return": (curve_rows[-1]["strategy"] / curve_rows[0]["strategy"] - 1.0) if len(curve_rows) >= 2 else None,
        "cagr": cagr,
        "annualized_vol": float(np.std(returns, ddof=1) * math.sqrt(periods_per_year)) if len(returns) >= 2 else None,
        "sharpe": sharpe_ratio(returns, periods_per_year=periods_per_year) if len(returns) >= 2 else None,
        "max_drawdown": _max_drawdown([float(p["strategy"]) for p in curve_rows]),
        "hit_rate": float(np.mean([r > 0 for r in returns])) if returns else None,
        "avg_turnover": float(np.mean([float(r["turnover"]) for r in period_rows])) if period_rows else None,
        "mean_active_return": float(np.mean(active)) if active else None,
        "tracking_error": tracking,
        "information_ratio": (float(np.mean(active)) * periods_per_year / tracking) if tracking and active else None,
    }


def run_sfc_portfolio_backtest(
    scored_panel: pd.DataFrame,
    *,
    price_by_symbol: dict[str, pd.Series | None],
    config: SfcPortfolioBacktestConfig | None = None,
    masi_series: pd.Series | None = None,
) -> dict[str, Any]:
    cfg = config or SfcPortfolioBacktestConfig()
    if cfg.rebalance not in {"monthly", "quarterly"}:
        raise ValueError("rebalance must be 'monthly' or 'quarterly'")
    if scored_panel.empty:
        return _empty_result(cfg, "empty_panel")
    panel = scored_panel.copy()
    panel["symbol"] = panel["symbol"].astype(str).str.strip().str.upper()
    panel["as_of_date"] = pd.to_datetime(panel["as_of_date"]).dt.date
    rebalance_dates = _target_rebalance_dates(panel, cfg)
    if len(rebalance_dates) < 2:
        return _empty_result(cfg, "not_enough_rebalance_dates")

    strategy_equity = float(cfg.initial_equity)
    universe_equity = float(cfg.initial_equity)
    masi_equity = float(cfg.initial_equity)
    equity_curve = [
        {
            "date": rebalance_dates[0].isoformat(),
            "strategy": strategy_equity,
            "universe_equal_weight": universe_equity,
            "masi": masi_equity if masi_series is not None else None,
            "segment": segment_for_date(rebalance_dates[0], split_date=cfg.split_date, study_end_date=cfg.study_end_date),
        }
    ]
    rebalance_rows: list[dict[str, Any]] = []
    previous_weights: dict[str, float] = {}
    latest_holdings: list[dict[str, Any]] = []

    for start, end in zip(rebalance_dates[:-1], rebalance_dates[1:]):
        sub = panel[panel["as_of_date"] == start]
        holdings = _top_tercile_holdings(sub)
        current_weights = {str(r["symbol"]).strip().upper(): float(r["weight"]) for _, r in holdings.iterrows()}
        if not current_weights:
            continue
        universe_weights = _universe_weights(sub)
        turnover = one_way_turnover(previous_weights, current_weights)
        cost = (float(cfg.cost_bps) / 10000.0) * 2.0 * turnover
        gross_ret, stale_strategy = _weighted_return(current_weights, start=start, end=end, price_by_symbol=price_by_symbol)
        universe_ret, stale_universe = _weighted_return(universe_weights, start=start, end=end, price_by_symbol=price_by_symbol)
        if gross_ret is None or universe_ret is None:
            previous_weights = current_weights
            continue
        net_ret = gross_ret - cost
        masi_ret = _benchmark_return(masi_series, start=start, end=end)
        strategy_equity *= 1.0 + net_ret
        universe_equity *= 1.0 + universe_ret
        if masi_ret is not None:
            masi_equity *= 1.0 + masi_ret
        segment = segment_for_date(end, split_date=cfg.split_date, study_end_date=cfg.study_end_date)
        in_symbols = sorted(set(current_weights) - set(previous_weights))
        out_symbols = sorted(set(previous_weights) - set(current_weights))
        row = {
            "date": start.isoformat(),
            "period_end": end.isoformat(),
            "segment": segment,
            "holdings": sorted(current_weights),
            "holdings_in": in_symbols,
            "holdings_out": out_symbols,
            "turnover": turnover,
            "strategy_return_gross": gross_ret,
            "strategy_return_net": net_ret,
            "universe_return": universe_ret,
            "active_return": net_ret - universe_ret,
            "cost_drag": cost,
            "cost_bps": float(cfg.cost_bps),
            "stale_price_count": int(stale_strategy + stale_universe),
        }
        rebalance_rows.append(row)
        equity_curve.append(
            {
                "date": end.isoformat(),
                "strategy": strategy_equity,
                "universe_equal_weight": universe_equity,
                "masi": masi_equity if masi_series is not None and masi_ret is not None else None,
                "segment": segment,
            }
        )
        latest_holdings = _holding_rows(holdings, in_symbols=in_symbols, out_symbols=out_symbols)
        previous_weights = current_weights

    periods_per_year = _periods_per_year(cfg.rebalance)
    active_returns = [float(r["active_return"]) for r in rebalance_rows]
    block_mean = 3 if cfg.rebalance == "monthly" else 1
    significance = monte_carlo_luck_test(
        active_returns,
        metric="total_return",
        n_iter=1000,
        seed=42,
        periods_per_year=periods_per_year,
        block_mean=block_mean,
    )
    summary = [
        _summary_stats(rebalance_rows, equity_curve=equity_curve, segment=segment, periods_per_year=periods_per_year)
        for segment in ("proof", "selection", "live", "combined")
    ]
    return {
        "config": {
            "config_id": cfg.config_id,
            "config_hash": cfg.config_hash,
            "rebalance": cfg.rebalance,
            "cost_bps": float(cfg.cost_bps),
            "long_only": True,
            "kelly": False,
            "split_date": cfg.split_date.isoformat(),
            "study_end_date": cfg.study_end_date.isoformat(),
        },
        "equity_curve": equity_curve,
        "rebalance_rows": rebalance_rows,
        "summary": summary,
        "headline_segment": "proof",
        "headline_label": "validé sur 2023–2026 (une seule période de marché)",
        "latest_holdings": latest_holdings,
        "significance": significance,
        "warnings": [],
    }


def _holding_rows(holdings: pd.DataFrame, *, in_symbols: list[str], out_symbols: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, row in holdings.sort_values(["weight", "sfc", "symbol"], ascending=[False, False, True]).iterrows():
        symbol = str(row["symbol"]).strip().upper()
        rows.append(
            {
                "symbol": symbol,
                "name": row.get("company_name") or row.get("name") or symbol,
                "sector": row.get("sector"),
                "sfc": _finite(row.get("sfc")),
                "pillars": {
                    "val": _finite(row.get("pillar_val")),
                    "qual": _finite(row.get("pillar_qual")),
                    "fmom": _finite(row.get("pillar_fmom")),
                    "pmom": _finite(row.get("pillar_pmom")),
                },
                "weight": _finite(row.get("weight")),
                "badge": "in" if symbol in in_symbols else "held",
            }
        )
    for symbol in out_symbols:
        rows.append({"symbol": symbol, "name": symbol, "sector": None, "sfc": None, "pillars": {}, "weight": 0.0, "badge": "out"})
    return rows


def _empty_result(cfg: SfcPortfolioBacktestConfig, warning: str) -> dict[str, Any]:
    return {
        "config": {
            "config_id": cfg.config_id,
            "config_hash": cfg.config_hash,
            "rebalance": cfg.rebalance,
            "cost_bps": float(cfg.cost_bps),
            "long_only": True,
            "kelly": False,
            "split_date": cfg.split_date.isoformat(),
            "study_end_date": cfg.study_end_date.isoformat(),
        },
        "equity_curve": [],
        "rebalance_rows": [],
        "summary": [],
        "headline_segment": "proof",
        "headline_label": "validé sur 2023–2026 (une seule période de marché)",
        "latest_holdings": [],
        "significance": {},
        "warnings": [warning],
    }
