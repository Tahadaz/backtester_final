"""Service-layer consensus helpers (brief 54 §3 Phase 3).

Loads reconciled forward estimates from the DB and builds the `assumptions`-dict
keys that inject a forward view into core/quant_core/fundamentals (which is
DB-free).  The core stays pure; all DB access lives here.

PIT discipline: only estimates with as_of_date <= valuation_date are returned.

Reconciliation: delegates to reconcile_consensus() so the median-vs-priority
policy is centralised in one place.  The unique (symbol, fiscal_year, metric,
source) DB constraint means one row per source per call, so today's median ==
the single-source value — but the delegation ensures future policy changes
(e.g. source-priority) are automatically honoured here.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from core.quant_core.fundamentals.consensus.domain import (
    METRIC_EPS_FORWARD,
    METRIC_NI_FORWARD,
    METRIC_REV_FORWARD,
    METRIC_TARGET_PRICE,
    ConsensusEstimate,
)
from core.quant_core.fundamentals.consensus.reconcile import reconcile_consensus
from ..models import FundamentalConsensusEstimate

# assumptions-dict keys consumed by valuation.py
ASSUMPTIONS_FORWARD_EPS = "forward_eps"
ASSUMPTIONS_FORWARD_NI = "forward_net_income"
ASSUMPTIONS_FORWARD_REV = "forward_revenue"
ASSUMPTIONS_FORWARD_YEAR = "forward_fiscal_year"
ASSUMPTIONS_FORWARD_SOURCE = "forward_source"
ASSUMPTIONS_FORWARD_ASOF = "forward_as_of_date"

# Map domain metric names → assumptions-dict keys
_METRIC_TO_KEY = {
    METRIC_EPS_FORWARD: ASSUMPTIONS_FORWARD_EPS,
    METRIC_NI_FORWARD: ASSUMPTIONS_FORWARD_NI,
    METRIC_REV_FORWARD: ASSUMPTIONS_FORWARD_REV,
}


def _missing_consensus_table(exc: Exception) -> bool:
    text = str(exc).lower()
    return "fundamental_consensus_estimate" in text and (
        "no such table" in text or "does not exist" in text
    )


def load_forward_view(
    db: Session,
    symbol: str,
    *,
    fiscal_year: int,
    valuation_date: dt.date | None = None,
) -> dict[str, Any]:
    """Return an assumptions-dict fragment carrying the reconciled forward view.

    Callers must supply fiscal_year explicitly — the anchor year is a deliberate
    choice (currently FY2026e while in mid-2026; rolls to FY2027e once the
    caller decides).  There is no silent default.

    valuation_date defaults to today; only rows with as_of_date <= valuation_date
    are considered (PIT discipline).

    Returns {} if no estimates are present so the caller falls back to the
    trailing/mechanical path — no coverage regression, no new N/R.
    """
    val_date = valuation_date or dt.date.today()

    try:
        rows = (
            db.query(FundamentalConsensusEstimate)
            .filter(
                FundamentalConsensusEstimate.symbol == symbol.upper(),
                FundamentalConsensusEstimate.fiscal_year == fiscal_year,
                FundamentalConsensusEstimate.as_of_date <= val_date,
                FundamentalConsensusEstimate.is_estimate.is_(True),
            )
            .all()
        )
    except (OperationalError, ProgrammingError) as exc:
        if _missing_consensus_table(exc):
            return {}
        raise
    if not rows:
        return {}

    # Convert to domain objects so reconcile_consensus() owns all policy
    estimates = [
        ConsensusEstimate(
            symbol=r.symbol,
            fiscal_year=r.fiscal_year,
            period_type=r.period_type,
            metric=r.metric,
            value=r.value,
            source=r.source,
            as_of_date=r.as_of_date,
            currency=r.currency,
            raw_label=r.raw_label,
        )
        for r in rows
    ]
    reconciled = reconcile_consensus(estimates)

    sources = sorted({r.source for r in rows})
    as_of = max((r.as_of_date for r in rows), default=None)

    result: dict[str, Any] = {
        ASSUMPTIONS_FORWARD_YEAR: fiscal_year,
        ASSUMPTIONS_FORWARD_SOURCE: ",".join(sources),
    }
    if as_of is not None:
        result[ASSUMPTIONS_FORWARD_ASOF] = as_of.isoformat()

    for rec in reconciled:
        key = _METRIC_TO_KEY.get(rec.metric)
        if key is not None and rec.reconciled_value is not None:
            result[key] = rec.reconciled_value

    return result


def load_broker_target(
    db: Session,
    symbol: str,
    *,
    valuation_date: dt.date | None = None,
) -> dict[str, Any] | None:
    """Return the latest broker target price for *symbol*, or None.

    PIT discipline mirrors load_forward_view: only rows with
    as_of_date <= valuation_date are considered. Target prices are 12-month
    anchors, so the latest as_of wins regardless of fiscal_year.
    """
    val_date = valuation_date or dt.date.today()
    try:
        row = (
            db.query(FundamentalConsensusEstimate)
            .filter(
                FundamentalConsensusEstimate.symbol == symbol.upper(),
                FundamentalConsensusEstimate.metric == METRIC_TARGET_PRICE,
                FundamentalConsensusEstimate.as_of_date <= val_date,
                FundamentalConsensusEstimate.value.isnot(None),
            )
            .order_by(FundamentalConsensusEstimate.as_of_date.desc())
            .first()
        )
    except (OperationalError, ProgrammingError) as exc:
        if _missing_consensus_table(exc):
            return None
        raise
    if row is None or row.value is None or float(row.value) <= 0:
        return None
    return {
        "value": float(row.value),
        "source": row.source,
        "as_of_date": row.as_of_date.isoformat() if row.as_of_date else None,
        "fiscal_year": row.fiscal_year,
        "currency": row.currency,
    }


def upsert_consensus_estimates(
    db: Session,
    estimates: list[Any],  # list[ConsensusEstimate] — avoid importing core in models path
) -> int:
    """Upsert ConsensusEstimate rows into fundamental_consensus_estimate.

    Latest as_of_date wins per (symbol, fiscal_year, metric, source).
    Returns count of rows written.
    """
    written = 0
    for est in estimates:
        existing = (
            db.query(FundamentalConsensusEstimate)
            .filter(
                FundamentalConsensusEstimate.symbol == est.symbol.upper(),
                FundamentalConsensusEstimate.fiscal_year == est.fiscal_year,
                FundamentalConsensusEstimate.metric == est.metric,
                FundamentalConsensusEstimate.source == est.source,
            )
            .one_or_none()
        )
        if existing is None:
            db.add(FundamentalConsensusEstimate(
                symbol=est.symbol.upper(),
                fiscal_year=est.fiscal_year,
                period_type=est.period_type,
                metric=est.metric,
                value=est.value,
                source=est.source,
                as_of_date=est.as_of_date,
                currency=est.currency,
                raw_label=est.raw_label,
                data_source=est.source,
                is_estimate=True,
                analyst_count=est.analyst_count,
            ))
            written += 1
        elif est.as_of_date >= existing.as_of_date:
            existing.value = est.value
            existing.as_of_date = est.as_of_date
            existing.raw_label = est.raw_label
            existing.analyst_count = est.analyst_count
            written += 1
    db.flush()
    return written
