from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from ...significance import monte_carlo_luck_test, sharpe_ratio
from .benchmark_weights import benchmark_weights_from_panel
from .masi_float_shares import MASI_FLOAT_SHARES_SNAPSHOT_DATE

RebalanceFrequency = Literal["event", "monthly", "quarterly"]
WeightingMode = Literal["benchmark_active", "equal_top_tercile"]

SFC_METHODOLOGY_VERSION = "sfc_core_v2_2026_07_06"
SFC_PORTFOLIO_CONFIG_ID = "sfc_core_v2_2026_07_06__pmom_6_1"
SFC_PROOF_SPLIT_DATE = dt.date(2023, 7, 31)
SFC_STUDY_END_DATE = dt.date(2026, 7, 5)


@dataclass(frozen=True)
class SfcPortfolioBacktestConfig:
    rebalance: RebalanceFrequency = "event"
    cost_bps: float = 33.0
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    initial_equity: float = 1.0
    split_date: dt.date = SFC_PROOF_SPLIT_DATE
    study_end_date: dt.date = SFC_STUDY_END_DATE
    config_id: str = SFC_PORTFOLIO_CONFIG_ID
    config_hash: str | None = None
    weighting_mode: WeightingMode = "benchmark_active"
    active_weight_cap: float = 0.03
    sector_cap: float = 0.20
    adv_cap_multiplier: float | None = None


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


def segment_for_date(
    value: Any,
    *,
    split_date: dt.date = SFC_PROOF_SPLIT_DATE,
    study_end_date: dt.date = SFC_STUDY_END_DATE,
) -> str:
    date = _date(value)
    if date < split_date:
        return "selection"
    if date <= study_end_date:
        return "proof"
    return "live"


def _periods_per_year(rebalance: RebalanceFrequency) -> int:
    if rebalance in {"event", "quarterly"}:
        return 4
    return 12


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
    if config.rebalance == "quarterly":
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
    selected = []
    previous: dt.date | None = None
    for date in dates:
        sub = panel[panel["as_of_date"] == date]
        if sub.empty:
            previous = date
            continue
        max_avail = pd.to_datetime(sub.get("max_metric_availability_date"), errors="coerce").dt.date
        if previous is None:
            has_event = bool((max_avail == date).any())
        else:
            has_event = bool(((max_avail > previous) & (max_avail <= date)).any())
        if has_event:
            selected.append(date)
        previous = date
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
    ranked = _valid_score_rows(sub).sort_values(["sfc", "symbol"], ascending=[False, True]).copy()
    if ranked.empty:
        return ranked
    n_top = max(1, int(math.ceil(len(ranked) / 3.0)))
    top = ranked.head(n_top).copy()
    top["weight"] = 1.0 / float(n_top)
    top["benchmark_weight"] = np.nan
    top["active_weight"] = np.nan
    return top


def _top_middle_bottom_sets(sub: pd.DataFrame) -> tuple[pd.DataFrame, set[str], set[str], set[str]]:
    ranked = _valid_score_rows(sub).sort_values(["sfc", "symbol"], ascending=[False, True]).copy()
    if ranked.empty:
        return ranked, set(), set(), set()
    n_bucket = max(1, int(math.ceil(len(ranked) / 3.0)))
    top = set(ranked.head(n_bucket)["symbol"].astype(str).str.strip().str.upper())
    bottom = set(ranked.tail(n_bucket)["symbol"].astype(str).str.strip().str.upper())
    middle = set(ranked["symbol"].astype(str).str.strip().str.upper()) - top - bottom
    ranked["tercile"] = ranked["symbol"].astype(str).str.strip().str.upper().map(
        lambda symbol: "top" if symbol in top else "bottom" if symbol in bottom else "middle"
    )
    return ranked, top, middle, bottom


def _iterative_active_distribution(
    top_symbols: list[str],
    benchmark_weights: dict[str, float],
    total_overweight: float,
    active_cap: float,
) -> dict[str, float]:
    if total_overweight <= 0 or not top_symbols:
        return {symbol: 0.0 for symbol in top_symbols}
    active = {symbol: 0.0 for symbol in top_symbols}
    remaining = float(total_overweight)
    eligible = list(top_symbols)
    while remaining > 1e-12 and eligible:
        total_benchmark = sum(max(benchmark_weights.get(symbol, 0.0), 0.0) for symbol in eligible)
        proposal = (
            {symbol: remaining / float(len(eligible)) for symbol in eligible}
            if total_benchmark <= 0
            else {
                symbol: remaining * max(benchmark_weights.get(symbol, 0.0), 0.0) / total_benchmark
                for symbol in eligible
            }
        )
        spent = 0.0
        next_eligible: list[str] = []
        for symbol in eligible:
            capacity = max(float(active_cap) - active[symbol], 0.0)
            add = min(capacity, proposal.get(symbol, 0.0))
            active[symbol] += add
            spent += add
            if active[symbol] + 1e-12 < float(active_cap):
                next_eligible.append(symbol)
        if spent <= 1e-12:
            break
        remaining = max(remaining - spent, 0.0)
        eligible = next_eligible
    return active


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    clean = {symbol: max(float(weight), 0.0) for symbol, weight in weights.items() if float(weight) > 0.0}
    total = sum(clean.values())
    if total <= 0:
        return {}
    return {symbol: weight / total for symbol, weight in clean.items()}


def _apply_sector_cap(weights: dict[str, float], sector_map: dict[str, str | None], cap: float) -> dict[str, float]:
    adjusted = dict(weights)
    for _ in range(8):
        sector_totals: dict[str, float] = {}
        for symbol, weight in adjusted.items():
            sector = sector_map.get(symbol) or "UNSPECIFIED"
            sector_totals[sector] = sector_totals.get(sector, 0.0) + float(weight)
        capped_sectors = {sector: total for sector, total in sector_totals.items() if total > cap + 1e-12}
        if not capped_sectors:
            break
        reduced = dict(adjusted)
        freed = 0.0
        for sector, total in capped_sectors.items():
            ratio = cap / total if total > 0 else 1.0
            for symbol, weight in adjusted.items():
                if (sector_map.get(symbol) or "UNSPECIFIED") != sector:
                    continue
                new_weight = weight * ratio
                freed += weight - new_weight
                reduced[symbol] = new_weight
        uncapped = [symbol for symbol in reduced if (sector_map.get(symbol) or "UNSPECIFIED") not in capped_sectors]
        uncapped_total = sum(reduced[symbol] for symbol in uncapped)
        if freed > 0 and uncapped_total > 0:
            scale = (uncapped_total + freed) / uncapped_total
            for symbol in uncapped:
                reduced[symbol] *= scale
        adjusted = reduced
    return adjusted


def _apply_adv_caps(weights: dict[str, float], sub: pd.DataFrame, cfg: SfcPortfolioBacktestConfig) -> dict[str, float]:
    if cfg.adv_cap_multiplier is None or not weights:
        return dict(weights)
    adv_col = "adv20" if "adv20" in sub.columns else "adv_20d" if "adv_20d" in sub.columns else None
    if adv_col is None:
        return dict(weights)
    adv_by_symbol = {
        str(row["symbol"]).strip().upper(): _finite(row.get(adv_col))
        for _, row in sub.iterrows()
    }
    positive_adv = [value for value in adv_by_symbol.values() if value is not None and value > 0]
    if not positive_adv:
        return dict(weights)
    median_adv = float(np.median(positive_adv))
    capped = dict(weights)
    freed = 0.0
    uncapped_symbols: list[str] = []
    for symbol, weight in weights.items():
        adv = adv_by_symbol.get(symbol)
        if adv is None or adv <= 0 or median_adv <= 0:
            uncapped_symbols.append(symbol)
            continue
        cap = float(cfg.adv_cap_multiplier) * min(adv / median_adv, 1.0)
        if cap > 0 and weight > cap:
            capped[symbol] = cap
            freed += weight - cap
        else:
            uncapped_symbols.append(symbol)
    uncapped_total = sum(capped[symbol] for symbol in uncapped_symbols)
    if freed > 0 and uncapped_total > 0:
        scale = (uncapped_total + freed) / uncapped_total
        for symbol in uncapped_symbols:
            capped[symbol] *= scale
    return capped


def _benchmark_relative_holdings(
    sub: pd.DataFrame,
    cfg: SfcPortfolioBacktestConfig,
) -> tuple[pd.DataFrame, dict[str, float]]:
    ranked, top, middle, bottom = _top_middle_bottom_sets(sub)
    if ranked.empty:
        return ranked, {}
    benchmark = benchmark_weights_from_panel(ranked)
    if not benchmark:
        return _top_tercile_holdings(sub), {}
    weights = {symbol: benchmark.get(symbol, 0.0) for symbol in benchmark}
    total_underweight = 0.0
    for symbol in bottom:
        if symbol in weights:
            total_underweight += weights[symbol]
            weights[symbol] = 0.0
    for symbol, extra in _iterative_active_distribution(
        sorted(symbol for symbol in top if symbol in weights),
        benchmark,
        total_underweight,
        cfg.active_weight_cap,
    ).items():
        weights[symbol] = benchmark.get(symbol, 0.0) + extra
    residual = max(1.0 - sum(weights.values()), 0.0)
    middle_symbols = [symbol for symbol in sorted(middle) if symbol in weights]
    middle_total = sum(benchmark.get(symbol, 0.0) for symbol in middle_symbols)
    if residual > 0 and middle_total > 0:
        for symbol in middle_symbols:
            weights[symbol] += residual * benchmark.get(symbol, 0.0) / middle_total
    sector_map = {
        str(row["symbol"]).strip().upper(): row.get("sector")
        for _, row in ranked.iterrows()
    }
    weights = _apply_sector_cap(weights, sector_map, float(cfg.sector_cap))
    weights = _apply_adv_caps(weights, ranked, cfg)
    weights = _normalize_weights(weights)
    holdings = ranked[ranked["symbol"].astype(str).str.strip().str.upper().isin(weights)].copy()
    holdings["benchmark_weight"] = holdings["symbol"].astype(str).str.strip().str.upper().map(benchmark).fillna(0.0)
    holdings["weight"] = holdings["symbol"].astype(str).str.strip().str.upper().map(weights).fillna(0.0)
    holdings["active_weight"] = holdings["weight"] - holdings["benchmark_weight"]
    holdings = holdings[holdings["weight"] > 0].copy()
    return holdings.sort_values(["weight", "sfc", "symbol"], ascending=[False, False, True]), benchmark


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


def _financial_active_exposure(holdings: pd.DataFrame) -> dict[str, float]:
    if holdings.empty or "active_weight" not in holdings.columns or "is_financial" not in holdings.columns:
        return {"financials": 0.0, "non_financials": 0.0}
    financials = float(holdings.loc[holdings["is_financial"].fillna(False), "active_weight"].sum())
    total = float(holdings["active_weight"].sum())
    return {"financials": financials, "non_financials": total - financials}


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
    if cfg.rebalance not in {"event", "monthly", "quarterly"}:
        raise ValueError("rebalance must be 'event', 'monthly', or 'quarterly'")
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
        benchmark_weights: dict[str, float] = {}
        if cfg.weighting_mode == "equal_top_tercile":
            holdings = _top_tercile_holdings(sub)
        else:
            holdings, benchmark_weights = _benchmark_relative_holdings(sub, cfg)
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
        rebalance_rows.append(
            {
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
                "benchmark_weights": benchmark_weights,
                "financials_vs_non_financials_active_exposure": _financial_active_exposure(holdings),
            }
        )
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
    significance = monte_carlo_luck_test(
        active_returns,
        metric="total_return",
        n_iter=1000,
        seed=42,
        periods_per_year=periods_per_year,
        block_mean=3 if cfg.rebalance == "monthly" else 1,
    )
    summary = [
        _summary_stats(rebalance_rows, equity_curve=equity_curve, segment=segment, periods_per_year=periods_per_year)
        for segment in ("proof", "selection", "live", "combined")
    ]
    turnover_vs_monthly_baseline = None
    if cfg.rebalance != "monthly":
        monthly = run_sfc_portfolio_backtest(
            panel,
            price_by_symbol=price_by_symbol,
            masi_series=masi_series,
            config=SfcPortfolioBacktestConfig(
                rebalance="monthly",
                cost_bps=cfg.cost_bps,
                start_date=cfg.start_date,
                end_date=cfg.end_date,
                initial_equity=cfg.initial_equity,
                split_date=cfg.split_date,
                study_end_date=cfg.study_end_date,
                config_id=cfg.config_id,
                config_hash=cfg.config_hash,
                weighting_mode=cfg.weighting_mode,
                active_weight_cap=cfg.active_weight_cap,
                sector_cap=cfg.sector_cap,
                adv_cap_multiplier=cfg.adv_cap_multiplier,
            ),
        )
        turnover_vs_monthly_baseline = {
            "monthly_avg_turnover": next(
                (row.get("avg_turnover") for row in monthly.get("summary", []) if row.get("segment") == "combined"),
                None,
            ),
            "selected_avg_turnover": next(
                (row.get("avg_turnover") for row in summary if row.get("segment") == "combined"),
                None,
            ),
        }
    return {
        "config": {
            "config_id": cfg.config_id,
            "config_hash": cfg.config_hash,
            "methodology_version": SFC_METHODOLOGY_VERSION,
            "rebalance": cfg.rebalance,
            "cost_bps": float(cfg.cost_bps),
            "long_only": True,
            "kelly": False,
            "split_date": cfg.split_date.isoformat(),
            "study_end_date": cfg.study_end_date.isoformat(),
            "weighting_mode": cfg.weighting_mode,
            "active_weight_cap": float(cfg.active_weight_cap),
            "sector_cap": float(cfg.sector_cap),
        },
        "equity_curve": equity_curve,
        "rebalance_rows": rebalance_rows,
        "summary": summary,
        "headline_segment": "proof",
        "headline_label": "validé sur 2023–2026 (une seule période de marché)",
        "latest_holdings": latest_holdings,
        "significance": significance,
        "turnover_vs_monthly_baseline": turnover_vs_monthly_baseline,
        "warnings": [
            (
                "Float shares use the MASI all-share snapshot dated "
                f"{MASI_FLOAT_SHARES_SNAPSHOT_DATE}; exact for live, approximate across backtest history."
            ),
            "Full-cap approximation of MASI benchmark weights may overweight mega-caps versus the published free-float index.",
            "Latest snapshot shares are not PIT; this is a mild look-ahead in benchmark weights only.",
        ],
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
                "benchmark_weight": _finite(row.get("benchmark_weight")),
                "active_weight": _finite(row.get("active_weight")),
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
            "methodology_version": SFC_METHODOLOGY_VERSION,
            "rebalance": cfg.rebalance,
            "cost_bps": float(cfg.cost_bps),
            "long_only": True,
            "kelly": False,
            "split_date": cfg.split_date.isoformat(),
            "study_end_date": cfg.study_end_date.isoformat(),
            "weighting_mode": cfg.weighting_mode,
            "active_weight_cap": float(cfg.active_weight_cap),
            "sector_cap": float(cfg.sector_cap),
        },
        "equity_curve": [],
        "rebalance_rows": [],
        "summary": [],
        "headline_segment": "proof",
        "headline_label": "validé sur 2023–2026 (une seule période de marché)",
        "latest_holdings": [],
        "significance": {},
        "turnover_vs_monthly_baseline": None,
        "warnings": [warning],
    }
