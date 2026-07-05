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
from core.quant_core.fundamentals.cross_section.pillars import PillarConfig, compute_pillar_scores

from .. import models
from ..json_sanitize import sanitize_json_compatible
from ..market_data_loader import load_close_series_from_store


SFC_METHODOLOGY_VERSION = "sfc_phase1_2026_07_05"
SFC_CONFIG = {
    "methodology_version": SFC_METHODOLOGY_VERSION,
    "pmom_variant": "pmom_6_1",
    "pillar_weights": {"val": 0.25, "qual": 0.25, "fmom": 0.25, "pmom": 0.25},
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
                       fam.as_of_date, fam.source_document_id, fsd.publication_date
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
                       fsd.publication_date
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
            cache[sym] = load_close_series_from_store(object_key=key)
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
        config=PanelConfig(as_of_dates=(date,)),
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
    db.commit()
    return {**meta, "persisted": persisted}


def latest_sfc_as_of(db: Session, as_of: dt.date | None = None) -> dt.date | None:
    query = db.query(models.FundamentalCrossSectionScore.as_of_date)
    if as_of is not None:
        query = query.filter(models.FundamentalCrossSectionScore.as_of_date <= as_of)
    row = query.order_by(models.FundamentalCrossSectionScore.as_of_date.desc()).first()
    return row[0] if row else None
