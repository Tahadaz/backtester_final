from __future__ import annotations

import datetime as dt
import logging
from typing import Any, cast

import pandas as pd
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.quant_core.fundamentals.cost_of_capital import BetaConfig, BetaEstimate, BetaFrequency, estimate_beta

from .. import models
from ..market_data_loader import load_ohlcv_for_symbol

logger = logging.getLogger(__name__)


def compute_beta_from_market_data(
    db: Session,
    *,
    symbol: str,
    proxy: str = "MASI",
    as_of: dt.date | None = None,
    config: BetaConfig | None = None,
    peer_unlevered_beta: float | None = None,
    debt_to_equity: float | None = None,
    tax_rate: float = 0.35,
) -> BetaEstimate:
    """Load market_data_store OHLCV and estimate a stock beta."""

    cfg = config or BetaConfig(proxy_symbol=proxy)
    stock = _close_from_ohlcv(load_ohlcv_for_symbol(db, symbol, timeframe="1D"))
    market = _close_from_ohlcv(load_ohlcv_for_symbol(db, cfg.proxy_symbol, timeframe="1D"))
    return estimate_beta(
        symbol=symbol,
        stock_close=stock,
        market_close=market,
        as_of=as_of,
        config=cfg,
        peer_unlevered_beta=peer_unlevered_beta,
        debt_to_equity=debt_to_equity,
        tax_rate=tax_rate,
    )


def upsert_beta_history(db: Session, estimate: BetaEstimate) -> models.FundamentalBetaHistory:
    """Persist one PIT beta estimate keyed by symbol/as_of/proxy/frequency/window."""

    row = (
        db.query(models.FundamentalBetaHistory)
        .filter(
            models.FundamentalBetaHistory.symbol == estimate.symbol,
            models.FundamentalBetaHistory.as_of == estimate.as_of,
            models.FundamentalBetaHistory.proxy == estimate.proxy,
            models.FundamentalBetaHistory.frequency == estimate.frequency,
            models.FundamentalBetaHistory.window_years == float(estimate.window_years),
        )
        .first()
    )
    values: dict[str, Any] = {
        "symbol": estimate.symbol,
        "as_of": estimate.as_of,
        "beta": estimate.beta,
        "raw_beta": estimate.raw_beta,
        "method": estimate.method,
        "r2": estimate.r2,
        "n_obs": int(estimate.n_obs),
        "zero_week_frac": estimate.zero_week_frac,
        "liquidity_flag": bool(estimate.liquidity_flag),
        "proxy": estimate.proxy,
        "frequency": estimate.frequency,
        "window_years": float(estimate.window_years),
        "warnings_json": list(estimate.warnings),
    }
    if row is None:
        row = models.FundamentalBetaHistory(**values)
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    db.flush()
    return row


def recompute_universe_betas(
    db: Session,
    *,
    as_of: dt.date | None = None,
    window_years: float = 2.0,
    frequency: str = "weekly",
    proxy_symbol: str = "MASI",
) -> dict[str, Any]:
    """Compute and persist PIT betas for the data-backed MASI universe."""

    from .fundamentals import _signal_backtest_symbols

    freq = _coerce_beta_frequency(frequency)
    resolved_proxy = _resolve_market_proxy_symbol(db, proxy_symbol)
    symbols = _signal_backtest_symbols(db, universe="full_masi")
    summary: dict[str, Any] = {
        "computed": 0,
        "skipped": 0,
        "liquidity_flagged": 0,
        "symbols_total": len(symbols),
        "proxy_symbol": resolved_proxy,
        "requested_proxy_symbol": (proxy_symbol or "MASI").strip().upper(),
        "frequency": freq,
        "window_years": float(window_years),
        "as_of": as_of.isoformat() if as_of else None,
        "computed_symbols": [],
        "liquidity_flagged_symbols": [],
        "skipped_symbols": [],
    }
    cfg = BetaConfig(proxy_symbol=resolved_proxy, frequency=freq, window_years=window_years)  # type: ignore[arg-type]
    for symbol in symbols:
        try:
            estimate = compute_beta_from_market_data(
                db,
                symbol=symbol,
                proxy=resolved_proxy,
                as_of=as_of,
                config=cfg,
            )
        except SQLAlchemyError:
            raise
        except Exception as exc:
            logger.debug("Skipping beta estimate for %s: %s", symbol, exc)
            summary["skipped"] += 1
            summary["skipped_symbols"].append({"symbol": symbol, "reason": str(exc)})
            continue

        upsert_beta_history(db, estimate)
        summary["computed"] += 1
        summary["computed_symbols"].append(symbol)
        if estimate.liquidity_flag:
            summary["liquidity_flagged"] += 1
            summary["liquidity_flagged_symbols"].append(symbol)
    return summary


def compute_and_persist_beta(
    db: Session,
    *,
    symbol: str,
    proxy: str = "MASI",
    as_of: dt.date | None = None,
    config: BetaConfig | None = None,
    peer_unlevered_beta: float | None = None,
    debt_to_equity: float | None = None,
    tax_rate: float = 0.35,
) -> models.FundamentalBetaHistory:
    estimate = compute_beta_from_market_data(
        db,
        symbol=symbol,
        proxy=proxy,
        as_of=as_of,
        config=config,
        peer_unlevered_beta=peer_unlevered_beta,
        debt_to_equity=debt_to_equity,
        tax_rate=tax_rate,
    )
    return upsert_beta_history(db, estimate)


def _close_from_ohlcv(frame: pd.DataFrame) -> pd.Series:
    close = pd.to_numeric(frame["Close"], errors="coerce")
    close = close.where(close > 0).dropna()
    return close.sort_index()


def _coerce_beta_frequency(value: str) -> BetaFrequency:
    normalized = str(value or "weekly").strip().lower()
    if normalized not in {"weekly", "monthly"}:
        raise ValueError("frequency must be 'weekly' or 'monthly'")
    return cast(BetaFrequency, normalized)


def _resolve_market_proxy_symbol(db: Session, proxy_symbol: str) -> str:
    requested = (proxy_symbol or "MASI").strip().upper()
    candidates = [requested]
    for fallback in ("MASI", "MASI_20", "MASI20", "MSI"):
        if fallback not in candidates:
            candidates.append(fallback)
    for candidate in candidates:
        row = (
            db.query(models.MarketDataStore.symbol)
            .filter(
                models.MarketDataStore.symbol == candidate,
                models.MarketDataStore.timeframe == "1D",
                models.MarketDataStore.object_key.isnot(None),
            )
            .first()
        )
        if row is not None:
            return str(row[0]).upper()
    raise ValueError(f"No market proxy with 1D data found in market_data_store. Tried: {', '.join(candidates)}")
