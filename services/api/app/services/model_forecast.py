"""Service-layer model-forecaster helpers (brief 54 §3 Phase 4).

Wires the sector-relative mean-reversion + momentum Ridge forecaster
(`core/quant_core/fundamentals/forecast_model.py`) into the same
`assumptions`-dict seam `consensus.py`'s `load_forward_view()` uses, as a
FALLBACK: it fills `forward_revenue`/`forward_net_income` ONLY for keys the
consensus view doesn't already carry. Consensus always wins -- this module
never overrides a consensus estimate, it only backstops the gap (most MASI
names lack BKGR/MarketScreener coverage, and all pre-2026 PIT history always
will).

Phase-4 validation (expanding-window, point-in-time backtest against realized
actuals -- see `core/quant_core/fundamentals/forecast_model.py` and
`services/api/scripts/forecast_model_validation.py`) showed the model beats
the naive-CAGR mechanical baseline on both revenue and net-income growth
across every out-of-sample year tested (2021-2024), so it is wired in here.

DB access lives here, not in `core/quant_core/fundamentals` (which stays
DB-free) -- same architectural split as `consensus.py`.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from core.quant_core.fundamentals.domain import AnnualMetricRow
from core.quant_core.fundamentals.pit_ic_backtest import _filter_pit_history
from core.quant_core.fundamentals.projection import NET_INCOME_ALIASES, REVENUE_ALIASES
from core.quant_core.fundamentals.projection import _series as _metric_series

try:
    # forecast_model.py depends on scikit-learn, which is a dev/core-only
    # dependency (requirements-dev.txt) -- NOT declared in
    # services/api/pyproject.toml, so it is not installed in the deployed API
    # image. Import defensively so a missing sklearn degrades this optional
    # fallback to a no-op (load_model_forecast_view returns {}) instead of
    # crashing the whole API at import time. Same "hard isolation" philosophy
    # as the MarketScreener adapter (brief 54 §2): an enhancement must never
    # take down the base service.
    from core.quant_core.fundamentals.forecast_model import (
        build_growth_observations,
        forecast_symbol_growth,
    )
    _FORECAST_MODEL_AVAILABLE = True
except ImportError:
    _FORECAST_MODEL_AVAILABLE = False

from ..models import FundamentalAnnualMetric, StockMaster
from .consensus import (
    ASSUMPTIONS_FORWARD_NI,
    ASSUMPTIONS_FORWARD_REV,
    ASSUMPTIONS_FORWARD_SOURCE,
    ASSUMPTIONS_FORWARD_YEAR,
)

#: Provenance tag appended to the assumptions-dict `forward_source` key when
#: the model contributed a value (consensus keeps its own source string when
#: it fully covers a symbol/year; this is only appended when the model fills
#: a gap consensus left open).
MODEL_SOURCE_TAG = "model_forecaster"

# In-process cache of import_id -> (histories_by_symbol, sectors). The DB
# round trip (the whole import's annual-metric rows, ~100k+) is the expensive
# part; refitting the Ridge model per call is cheap (a few hundred rows) and
# is always redone so results stay exact for the caller's as_of_year. Cleared
# via `clear_model_forecast_cache()` (e.g. after a new import lands).
_panel_cache: dict[uuid.UUID, tuple[dict[str, list[AnnualMetricRow]], dict[str, str | None]]] = {}


def clear_model_forecast_cache() -> None:
    """Test/ops hook -- drop the cached cross-sectional panel."""
    _panel_cache.clear()


def _row_to_annual_metric(row: FundamentalAnnualMetric) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol=str(row.symbol).upper(),
        company_name=str(row.company_name or ""),
        statement_year=int(row.statement_year),
        metric_name=str(row.metric_name),
        metric_value=row.metric_value,
        raw_metric_name=row.raw_metric_name,
        source_sheet=row.source_sheet,
        source_field=row.source_field,
        is_proxy=bool(row.is_proxy),
        as_of_date=row.as_of_date,
        source_document_id=row.source_document_id,
    )


def _load_universe_panel(
    db: Session, import_id: uuid.UUID
) -> tuple[dict[str, list[AnnualMetricRow]], dict[str, str | None]]:
    """Bulk-load every symbol's annual metric history for `import_id`.

    The forecaster needs a cross-sectional view (sector-relative momentum,
    enough rows to fit at all) -- broader than the single-symbol history the
    rest of the valuation pipeline loads, so it's fetched once per import and
    cached in-process rather than re-queried per symbol in a batch recompute.
    """
    cached = _panel_cache.get(import_id)
    if cached is not None:
        return cached

    rows = (
        db.query(FundamentalAnnualMetric)
        .filter(FundamentalAnnualMetric.import_id == import_id)
        .order_by(FundamentalAnnualMetric.symbol.asc(), FundamentalAnnualMetric.statement_year.asc())
        .all()
    )
    histories_by_symbol: dict[str, list[AnnualMetricRow]] = defaultdict(list)
    for row in rows:
        metric = _row_to_annual_metric(row)
        histories_by_symbol[metric.symbol].append(metric)

    symbols = list(histories_by_symbol.keys())
    sector_rows = (
        db.query(StockMaster.symbol, StockMaster.sector).filter(StockMaster.symbol.in_(symbols)).all()
        if symbols
        else []
    )
    sectors = {str(sym).upper(): (str(sector).strip() if sector else None) for sym, sector in sector_rows}

    result = (dict(histories_by_symbol), sectors)
    _panel_cache[import_id] = result
    return result


def _latest_metric_value(pit_history: list[AnnualMetricRow], aliases: tuple[str, ...]) -> float | None:
    series = _metric_series(pit_history, aliases)
    return float(series[-1][1]) if series else None


def _forecast_growth(
    aliases: tuple[str, ...],
    symbol: str,
    histories_by_symbol: dict[str, list[AnnualMetricRow]],
    sectors: dict[str, str | None],
    as_of_year: int,
) -> float | None:
    """Fit on the FULL expanding-window panel (every prior year with a known
    realized target, across every symbol) and predict for `symbol` at
    `as_of_year`. A single as_of_year slice has no realized targets by
    construction (the forward year hasn't printed yet) -- training rows only
    exist for years strictly before as_of_year, exactly mirroring
    `run_expanding_window_backtest`'s per-split training set.
    """
    all_years = sorted({row.statement_year for rows in histories_by_symbol.values() for row in rows})
    if not all_years:
        return None
    min_year = all_years[0]

    panel = []
    for year in range(min_year, as_of_year):
        pit_histories = {
            sym: _filter_pit_history(sym_rows, year, sym) for sym, sym_rows in histories_by_symbol.items()
        }
        realized_histories = {
            sym: _filter_pit_history(sym_rows, year + 1, sym) for sym, sym_rows in histories_by_symbol.items()
        }
        panel.extend(
            build_growth_observations(
                pit_histories, sectors, year, aliases, realized_histories_by_symbol=realized_histories
            )
        )

    live_pit_histories = {
        sym: _filter_pit_history(sym_rows, as_of_year, sym) for sym, sym_rows in histories_by_symbol.items()
    }
    panel.extend(build_growth_observations(live_pit_histories, sectors, as_of_year, aliases))

    return forecast_symbol_growth(symbol, panel)


def load_model_forecast_view(
    db: Session,
    symbol: str,
    *,
    import_id: uuid.UUID,
    fiscal_year: int,
    as_of_year: int,
    existing_forward_view: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Model-forecaster fallback for the brief-54 forward-view assumptions seam.

    Fills ONLY the `forward_revenue`/`forward_net_income` keys
    `existing_forward_view` (the consensus view from `load_forward_view`)
    doesn't already carry -- consensus always wins; the model only backstops
    the gap. Returns {} when there's nothing to add (thin history, no
    computable momentum, or consensus already covers everything) so callers
    see no coverage regression versus the pre-Phase-4 mechanical path.

    `as_of_year` must be the latest statement year with known actuals (i.e.
    `fiscal_year - 1`) -- the caller is responsible for PIT-safe sequencing,
    same contract as `load_forward_view`'s `valuation_date`.
    """
    if not _FORECAST_MODEL_AVAILABLE:
        return {}
    existing = existing_forward_view or {}
    need_revenue = ASSUMPTIONS_FORWARD_REV not in existing
    need_ni = ASSUMPTIONS_FORWARD_NI not in existing
    if not need_revenue and not need_ni:
        return {}

    symbol = symbol.upper()
    histories_by_symbol, sectors = _load_universe_panel(db, import_id)
    if symbol not in histories_by_symbol:
        return {}

    pit_history = _filter_pit_history(histories_by_symbol[symbol], as_of_year, symbol)
    result: dict[str, Any] = {}

    if need_revenue:
        latest_revenue = _latest_metric_value(pit_history, REVENUE_ALIASES)
        growth = _forecast_growth(REVENUE_ALIASES, symbol, histories_by_symbol, sectors, as_of_year)
        if growth is not None and latest_revenue is not None and latest_revenue > 0:
            result[ASSUMPTIONS_FORWARD_REV] = latest_revenue * (1.0 + growth)

    if need_ni:
        latest_ni = _latest_metric_value(pit_history, NET_INCOME_ALIASES)
        growth = _forecast_growth(NET_INCOME_ALIASES, symbol, histories_by_symbol, sectors, as_of_year)
        if growth is not None and latest_ni is not None and latest_ni > 0:
            result[ASSUMPTIONS_FORWARD_NI] = latest_ni * (1.0 + growth)

    if not result:
        return {}

    result[ASSUMPTIONS_FORWARD_YEAR] = fiscal_year
    result[ASSUMPTIONS_FORWARD_SOURCE] = (
        f"{existing[ASSUMPTIONS_FORWARD_SOURCE]},{MODEL_SOURCE_TAG}"
        if ASSUMPTIONS_FORWARD_SOURCE in existing
        else MODEL_SOURCE_TAG
    )
    return result
