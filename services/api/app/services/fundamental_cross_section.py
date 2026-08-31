from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.quant_core.fundamentals.cross_section.composite import compute_sfc
from core.quant_core.fundamentals.cross_section.panel import PanelConfig, build_pit_panel, load_universe, publication_coverage_stats
from core.quant_core.fundamentals.cross_section.portfolio_backtest import (
    SFC_METHODOLOGY_VERSION,
    SfcPortfolioBacktestConfig,
    run_sfc_portfolio_backtest,
)
from core.quant_core.fundamentals.cross_section.pillars import PillarConfig, compute_pillar_scores
from core.quant_core.fundamentals.pit_ic_backtest import normalize_price_index

from .. import models
from ..json_sanitize import sanitize_json_compatible
from ..market_data_loader import load_close_series_from_store


SFC_CONFIG = {
    "methodology_version": SFC_METHODOLOGY_VERSION,
    "pmom_variant": "pmom_6_1",
    "core_pillar_weights": {"val": 1.0 / 3.0, "qual": 1.0 / 3.0, "fmom": 1.0 / 3.0},
    "legacy_pillar_weights": {"val": 0.25, "qual": 0.25, "fmom": 0.25, "pmom": 0.25},
    "min_pillars": 2,
    "mad_clip": 3.0,
    "min_bucket": 8,
    "validation_label_fr": "validé sur 2023-2026 (une seule période de marché)",
}
SFC_CONFIG_HASH = hashlib.sha256(json.dumps(SFC_CONFIG, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _load_fundamental_rows(db: Session) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, str | None]]:
    annual = [
        dict(r._mapping)
        for r in db.execute(
            text(
                """
                SELECT fam.symbol, fam.company_name, fam.statement_year, fam.metric_name, fam.metric_value,
                       fam.as_of_date, fam.source_document_id, fsd.publication_date,
                       fsd.document_title, fsd.created_at AS source_document_created_at,
                       fsd.source_url, fsd.raw_json AS source_document_raw_json
                FROM fundamental_annual_metric fam
                LEFT JOIN fundamental_source_document fsd ON fsd.id = fam.source_document_id
                WHERE fam.statement_year >= 2016
                ORDER BY fam.symbol, fam.statement_year, fam.metric_name
                """
            )
        )
    ]
    period = [
        dict(r._mapping)
        for r in db.execute(
            text(
                """
                SELECT fpm.symbol, fpm.company_name, fpm.fiscal_year AS statement_year,
                       fpm.period_type, fpm.period_label, fpm.period_end_date,
                       fpm.metric_name, fpm.metric_value, fpm.source_document_id,
                       fsd.publication_date, fsd.document_title,
                       fsd.created_at AS source_document_created_at,
                       fsd.source_url, fsd.raw_json AS source_document_raw_json
                FROM fundamental_period_metric fpm
                LEFT JOIN fundamental_source_document fsd ON fsd.id = fpm.source_document_id
                WHERE fpm.fiscal_year >= 2016
                ORDER BY fpm.symbol, fpm.fiscal_year, fpm.period_type, fpm.metric_name
                """
            )
        )
    ]
    try:
        consensus = [
            dict(r._mapping)
            for r in db.execute(
                text(
                    """
                    SELECT symbol, fiscal_year, metric, value, source, as_of_date
                    FROM fundamental_consensus_estimate
                    ORDER BY symbol, fiscal_year, metric, as_of_date
                    """
                )
            )
        ]
    except Exception:
        consensus = []
    sectors = {
        str(r[0]).strip().upper(): (str(r[1]).strip() if r[1] else None)
        for r in db.execute(text("SELECT symbol, sector FROM stock_master WHERE symbol IS NOT NULL"))
    }
    return annual, period, consensus, sectors


def _price_loader(db: Session):
    rows = db.query(models.MarketDataStore).filter(
        models.MarketDataStore.timeframe.in_(["1D", "1d"]),
        models.MarketDataStore.object_key.isnot(None),
    ).all()
    keys = {str(row.symbol).strip().upper(): str(row.object_key) for row in rows}
    cache: dict[str, pd.Series | None] = {}

    def load(symbol: str) -> pd.Series | None:
        sym = str(symbol).strip().upper()
        if sym in cache:
            return cache[sym]
        key = keys.get(sym)
        if not key:
            cache[sym] = None
            return None
        try:
            cache[sym] = normalize_price_index(load_close_series_from_store(object_key=key))
        except Exception:
            cache[sym] = None
        return cache[sym]

    return load, cache


def compute_cross_section_frame(db: Session, *, as_of_date: dt.date | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    date = as_of_date or dt.date.today()
    annual, period, consensus, sectors = _load_fundamental_rows(db)
    load_price, price_cache = _price_loader(db)
    panel = build_pit_panel(
        annual_rows=annual,
        period_rows=period,
        consensus_rows=consensus,
        price_loader=load_price,
        universe_df=load_universe(),
        config=PanelConfig(as_of_dates=(date,), require_observed_publication_date=True),
        sectors=sectors,
    )
    scored = compute_sfc(
        compute_pillar_scores(
            panel,
            price_by_symbol=price_cache,
            config=PillarConfig(pmom_months=6, min_bucket=8, mad_clip=3.0),
        )
    )
    if scored.empty:
        return scored, {"publication_coverage": publication_coverage_stats(panel), "config_hash": SFC_CONFIG_HASH}
    covered = scored[scored["is_covered"].astype(bool)].copy()
    covered = covered.sort_values(["sfc", "symbol"], ascending=[False, True])
    ranks = {symbol: idx + 1 for idx, symbol in enumerate(covered["symbol"].astype(str).tolist())}
    n = len(covered)
    terciles: dict[str, str] = {}
    for idx, symbol in enumerate(covered["symbol"].astype(str).tolist(), start=1):
        if idx <= max(1, math.ceil(n / 3)):
            terciles[symbol] = "top"
        elif idx > math.floor(2 * n / 3):
            terciles[symbol] = "bottom"
        else:
            terciles[symbol] = "middle"
    scored["rank"] = scored["symbol"].map(ranks)
    scored["tercile"] = scored["symbol"].map(terciles).fillna("uncovered")
    meta = {
        "publication_coverage": publication_coverage_stats(panel),
        "config_hash": SFC_CONFIG_HASH,
        "methodology_version": SFC_METHODOLOGY_VERSION,
        "as_of_date": date.isoformat(),
        "rows": int(len(scored)),
        "covered_rows": int(scored["is_covered"].sum()),
    }
    return scored, meta


def compute_sfc_panel(
    db: Session,
    *,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> tuple[pd.DataFrame, dict[str, pd.Series | None], dict[str, Any]]:
    annual, period, consensus, sectors = _load_fundamental_rows(db)
    load_price, price_cache = _price_loader(db)
    panel = build_pit_panel(
        annual_rows=annual,
        period_rows=period,
        consensus_rows=consensus,
        price_loader=load_price,
        universe_df=load_universe(),
        config=PanelConfig(start=start_date, end=end_date, require_observed_publication_date=True),
        sectors=sectors,
    )
    scored = compute_sfc(
        compute_pillar_scores(
            panel,
            price_by_symbol=price_cache,
            config=PillarConfig(pmom_months=6, min_bucket=8, mad_clip=3.0),
        )
    )
    meta = {
        "publication_coverage": publication_coverage_stats(panel),
        "config_hash": SFC_CONFIG_HASH,
        "methodology_version": SFC_METHODOLOGY_VERSION,
        "rows": int(len(scored)),
        "covered_rows": int(scored["is_covered"].sum()) if not scored.empty and "is_covered" in scored else 0,
    }
    return scored, price_cache, meta


def _load_masi_close_series(db: Session) -> pd.Series | None:
    row = db.query(models.MarketDataStore).filter(
        models.MarketDataStore.symbol == "MASI",
        models.MarketDataStore.timeframe.in_(["1D", "1d"]),
        models.MarketDataStore.object_key.isnot(None),
    ).first()
    if row is None:
        return None
    try:
        return load_close_series_from_store(object_key=str(row.object_key))
    except Exception:
        return None


def _normalize_backtest_params(params: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = dict(params or {})
    rebalance = str(raw.get("rebalance") or "event").strip().lower()
    if rebalance not in {"event", "monthly", "quarterly"}:
        raise ValueError("rebalance must be 'event', 'monthly', or 'quarterly'")
    cost_bps = float(raw.get("cost_bps", 33.0))
    if cost_bps < 0 or cost_bps > 500:
        raise ValueError("cost_bps must be between 0 and 500")
    out: dict[str, Any] = {
        "rebalance": rebalance,
        "cost_bps": cost_bps,
        "start_date": raw.get("start_date"),
        "end_date": raw.get("end_date"),
    }
    return out


def _parse_date(value: Any) -> dt.date | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def compute_sfc_portfolio_backtest_snapshot(db: Session, params: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = _normalize_backtest_params(params)
    start_date = _parse_date(normalized.get("start_date"))
    end_date = _parse_date(normalized.get("end_date"))
    scored, price_cache, meta = compute_sfc_panel(db, start_date=start_date, end_date=end_date)
    result = run_sfc_portfolio_backtest(
        scored,
        price_by_symbol=price_cache,
        masi_series=_load_masi_close_series(db),
        config=SfcPortfolioBacktestConfig(
            rebalance=normalized["rebalance"],
            cost_bps=float(normalized["cost_bps"]),
            start_date=start_date,
            end_date=end_date,
            config_hash=SFC_CONFIG_HASH,
        ),
    )
    return {
        "params": normalized,
        "result": result,
        "meta": meta,
    }


def persist_sfc_portfolio_backtest_snapshot(db: Session, *, params: dict[str, Any] | None = None) -> models.FundamentalSfcBacktestSnapshot:
    payload = compute_sfc_portfolio_backtest_snapshot(db, params)
    row = models.FundamentalSfcBacktestSnapshot(
        config_hash=SFC_CONFIG_HASH,
        params_json=sanitize_json_compatible(payload["params"]),
        result_json=sanitize_json_compatible(payload["result"]),
        computed_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


def recompute_and_persist_sfc_backtest(db: Session, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    row = persist_sfc_portfolio_backtest_snapshot(db, params=params)
    db.commit()
    return {
        "snapshot_id": int(row.id),
        "config_hash": row.config_hash,
        "params": row.params_json,
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
    }


def persist_cross_section_scores(db: Session, frame: pd.DataFrame, *, as_of_date: dt.date) -> int:
    if frame.empty:
        return 0
    rows = []
    computed_at = dt.datetime.now(dt.timezone.utc)
    for _, row in frame.iterrows():
        rows.append(
            models.FundamentalCrossSectionScore(
                symbol=str(row["symbol"]).strip().upper(),
                as_of_date=as_of_date,
                sfc=_finite(row.get("sfc")),
                sfc_legacy=_finite(row.get("sfc_legacy")),
                rank=int(row["rank"]) if pd.notna(row.get("rank")) else None,
                tercile=str(row.get("tercile") or "uncovered"),
                pillar_val=_finite(row.get("pillar_val")),
                pillar_qual=_finite(row.get("pillar_qual")),
                pillar_fmom=_finite(row.get("pillar_fmom")),
                pillar_pmom=_finite(row.get("pillar_pmom")),
                coverage_ratio=float(row.get("coverage_ratio") or 0.0),
                attribution_json=sanitize_json_compatible(row.get("pillar_attribution") or {}),
                config_hash=SFC_CONFIG_HASH,
                methodology_version=SFC_METHODOLOGY_VERSION,
                computed_at=computed_at,
            )
        )
    db.query(models.FundamentalCrossSectionScore).filter(
        models.FundamentalCrossSectionScore.as_of_date == as_of_date,
        models.FundamentalCrossSectionScore.methodology_version == SFC_METHODOLOGY_VERSION,
        models.FundamentalCrossSectionScore.config_hash == SFC_CONFIG_HASH,
    ).delete(synchronize_session=False)
    db.add_all(rows)
    db.flush()
    return len(rows)


def recompute_and_persist_sfc(db: Session, *, as_of_date: dt.date | None = None) -> dict[str, Any]:
    date = as_of_date or dt.date.today()
    frame, meta = compute_cross_section_frame(db, as_of_date=date)
    persisted = persist_cross_section_scores(db, frame, as_of_date=date)
    backtest = persist_sfc_portfolio_backtest_snapshot(
        db,
        params={"rebalance": "event", "cost_bps": 33.0, "start_date": None, "end_date": None},
    )
    db.commit()
    return {**meta, "persisted": persisted, "backtest_snapshot_id": int(backtest.id)}


def latest_sfc_as_of(db: Session, as_of: dt.date | None = None) -> dt.date | None:
    query = db.query(models.FundamentalCrossSectionScore.as_of_date)
    if as_of is not None:
        query = query.filter(models.FundamentalCrossSectionScore.as_of_date <= as_of)
    row = query.order_by(models.FundamentalCrossSectionScore.as_of_date.desc()).first()
    return row[0] if row else None
