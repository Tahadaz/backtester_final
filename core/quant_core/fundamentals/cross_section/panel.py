from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

import pandas as pd

from quant_core.fundamentals.cgnc_mapping import FINANCIAL_ARCHETYPES, infer_statement_archetype
from quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot
from quant_core.fundamentals.pit_ic_backtest import UNIVERSE_PATH, _is_live, _pit_close

PriceLoader = Callable[[str], pd.Series | None]

HORIZON_BARS = {"3m": 63, "6m": 126, "12m": 252}


@dataclass(frozen=True)
class PanelConfig:
    start: dt.date | None = None
    end: dt.date | None = None
    freq: str = "ME"
    min_history_year: int = 2016
    horizons: tuple[str, ...] = ("3m", "6m", "12m")


def _date(value: Any) -> dt.date | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return pd.Timestamp(value).date()
    except Exception:
        return None


def _float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _get(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def availability_date(
    *,
    statement_year: int,
    period_type: str = "annual",
    publication_date: dt.date | None = None,
    period_end_date: dt.date | None = None,
    as_of_date: dt.date | None = None,
) -> dt.date:
    if publication_date is not None:
        return publication_date
    if as_of_date is not None:
        return as_of_date
    end = period_end_date or dt.date(int(statement_year), 12, 31)
    ptype = str(period_type or "annual").lower()
    lag = 90
    if ptype in {"semiannual", "half", "h1", "h2"}:
        lag = 60
    elif ptype in {"quarterly", "quarter", "q1", "q2", "q3", "q4"}:
        lag = 45
    return end + dt.timedelta(days=lag)


def _as_annual_metric(row: Any) -> dict[str, Any]:
    statement_year = int(_get(row, "statement_year", _get(row, "fiscal_year")))
    period_type = str(_get(row, "period_type", "annual") or "annual")
    period_end = _date(_get(row, "period_end_date")) or dt.date(statement_year, 12, 31)
    pub = _date(_get(row, "publication_date"))
    avail = availability_date(
        statement_year=statement_year,
        period_type=period_type,
        publication_date=pub,
        period_end_date=period_end,
        as_of_date=_date(_get(row, "as_of_date")),
    )
    return {
        "symbol": str(_get(row, "symbol")).strip().upper(),
        "company_name": str(_get(row, "company_name", "") or ""),
        "statement_year": statement_year,
        "period_type": period_type,
        "period_label": str(_get(row, "period_label", "FY") or "FY"),
        "period_end_date": period_end,
        "metric_name": str(_get(row, "metric_name")),
        "metric_value": _float(_get(row, "metric_value")),
        "availability_date": avail,
        "source_document_id": _get(row, "source_document_id"),
    }


def _as_consensus(row: Any) -> dict[str, Any]:
    return {
        "symbol": str(_get(row, "symbol")).strip().upper(),
        "fiscal_year": int(_get(row, "fiscal_year")),
        "metric": str(_get(row, "metric")),
        "value": _float(_get(row, "value")),
        "source": str(_get(row, "source", "") or ""),
        "as_of_date": _date(_get(row, "as_of_date")),
    }


def _assert_no_lookahead(panel: pd.DataFrame) -> None:
    if panel.empty:
        return
    as_of = pd.to_datetime(panel["as_of_date"]).dt.date
    max_avail = panel["max_metric_availability_date"]
    bad = panel[max_avail.notna() & (pd.to_datetime(max_avail).dt.date > as_of)]
    if not bad.empty:
        sample = bad[["symbol", "as_of_date", "max_metric_availability_date"]].head(3).to_dict("records")
        raise AssertionError(f"LOOK-AHEAD VIOLATION in SFC panel: {sample!r}")


def assert_metric_rows_no_lookahead(rows: Iterable[Any], as_of_date: dt.date) -> None:
    bad = []
    for row in rows:
        item = _as_annual_metric(row)
        if item["availability_date"] > as_of_date:
            bad.append((item["symbol"], item["metric_name"], item["availability_date"]))
    if bad:
        raise AssertionError(f"LOOK-AHEAD VIOLATION for as_of={as_of_date}: {bad[:3]!r}")


def _latest_metric_map(rows: list[dict[str, Any]], as_of_date: dt.date) -> tuple[dict[str, float], list[AnnualMetricRow], dt.date | None]:
    eligible = [r for r in rows if r["availability_date"] <= as_of_date]
    latest: dict[str, tuple[dt.date, int, float]] = {}
    history: list[AnnualMetricRow] = []
    max_avail: dt.date | None = None
    for row in eligible:
        val = row["metric_value"]
        if val is None:
            continue
        max_avail = row["availability_date"] if max_avail is None else max(max_avail, row["availability_date"])
        history.append(
            AnnualMetricRow(
                symbol=row["symbol"],
                company_name=row["company_name"],
                statement_year=row["statement_year"],
                metric_name=row["metric_name"],
                metric_value=val,
                as_of_date=row["availability_date"],
                source_document_id=row.get("source_document_id"),
            )
        )
        prev = latest.get(row["metric_name"])
        key = (row["availability_date"], row["statement_year"])
        if prev is None or key >= (prev[0], prev[1]):
            latest[row["metric_name"]] = (row["availability_date"], row["statement_year"], val)
    return {name: val for name, (_, _, val) in latest.items()}, history, max_avail


def _latest_consensus(rows: list[dict[str, Any]], as_of_date: dt.date) -> dict[str, float]:
    out: dict[tuple[str, int], tuple[dt.date, float]] = {}
    for row in rows:
        d = row["as_of_date"]
        val = row["value"]
        if d is None or d > as_of_date or val is None:
            continue
        key = (row["metric"], row["fiscal_year"])
        if key not in out or d >= out[key][0]:
            out[key] = (d, val)
    return {f"Consensus_{metric}_{year}": val for (metric, year), (_, val) in out.items()}


def _forward_return(prices: pd.Series | None, as_of_date: dt.date, bars: int) -> float | None:
    if prices is None or prices.empty:
        return None
    series = prices.sort_index().dropna()
    current = _pit_close(series, as_of_date)
    if current is None:
        return None
    idx = series.index.searchsorted(pd.Timestamp(as_of_date), side="right") - 1
    fwd_idx = idx + int(bars)
    if idx < 0 or fwd_idx >= len(series):
        return None
    future = float(series.iloc[fwd_idx])
    if not math.isfinite(future) or future <= 0:
        return None
    return future / current - 1.0


def _default_monthly_dates(config: PanelConfig, metric_rows: list[dict[str, Any]], price_by_symbol: dict[str, pd.Series | None]) -> list[dt.date]:
    starts = [r["availability_date"] for r in metric_rows if r.get("availability_date")]
    ends = []
    for prices in price_by_symbol.values():
        if prices is not None and not prices.empty:
            ends.append(pd.Timestamp(prices.index.max()).date())
    start = config.start or (min(starts) if starts else dt.date(2018, 1, 31))
    end = config.end or (max(ends) if ends else dt.date.today())
    return [ts.date() for ts in pd.date_range(start, end, freq=config.freq)]


def build_pit_panel(
    *,
    annual_rows: Iterable[Any],
    price_loader: PriceLoader,
    universe_df: pd.DataFrame,
    config: PanelConfig | None = None,
    period_rows: Iterable[Any] | None = None,
    consensus_rows: Iterable[Any] | None = None,
    sectors: dict[str, str | None] | None = None,
) -> pd.DataFrame:
    """Build a monthly point-in-time cross-section.

    Every fundamental value is included only after its publication date or
    conservative fallback availability date. The returned frame carries raw
    metrics, per-symbol PIT history, PIT close, and forward returns.
    """
    cfg = config or PanelConfig()
    metrics = [_as_annual_metric(r) for r in annual_rows]
    metrics.extend(_as_annual_metric(r) for r in (period_rows or []))
    metrics = [r for r in metrics if r["statement_year"] >= cfg.min_history_year and r["symbol"]]
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in metrics:
        by_symbol.setdefault(row["symbol"], []).append(row)

    consensus_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in (consensus_rows or []):
        item = _as_consensus(row)
        consensus_by_symbol.setdefault(item["symbol"], []).append(item)

    universe_by_symbol = {
        str(r["symbol"]).strip().upper(): r
        for _, r in universe_df.iterrows()
        if pd.notna(r.get("symbol"))
    }
    all_symbols = sorted(set(universe_by_symbol) & set(by_symbol))
    price_cache = {sym: price_loader(sym) for sym in all_symbols}
    dates = _default_monthly_dates(cfg, metrics, price_cache)
    sector_map = sectors or {}

    records: list[dict[str, Any]] = []
    for as_of_date in dates:
        for sym in all_symbols:
            uni_row = universe_by_symbol[sym]
            if not _is_live(uni_row, as_of_date):
                continue
            prices = price_cache.get(sym)
            close = _pit_close(prices, as_of_date)
            if close is None:
                continue
            metric_map, history, max_avail = _latest_metric_map(by_symbol.get(sym, []), as_of_date)
            if not metric_map:
                continue
            metric_map.update(_latest_consensus(consensus_by_symbol.get(sym, []), as_of_date))
            archetype = infer_statement_archetype(metric_map.keys())
            latest_year = max((row.statement_year for row in history), default=None)
            snapshot = FundamentalSnapshot(
                symbol=sym,
                company_name=str(uni_row.get("name") or sym),
                latest_statement_year=latest_year,
                metrics=metric_map,
                diagnostics={"archetype": archetype},
                source={"archetype": archetype},
                as_of_date=as_of_date,
            )
            row: dict[str, Any] = {
                "symbol": sym,
                "as_of_date": as_of_date,
                "close": close,
                "metrics": metric_map,
                "history": history,
                "snapshot": snapshot,
                "archetype": archetype,
                "is_financial": archetype in FINANCIAL_ARCHETYPES,
                "sector": sector_map.get(sym),
                "max_metric_availability_date": max_avail,
            }
            for horizon in cfg.horizons:
                row[f"fwd_return_{horizon}"] = _forward_return(prices, as_of_date, HORIZON_BARS[horizon])
            records.append(row)

    frame = pd.DataFrame(records)
    if not frame.empty:
        _assert_no_lookahead(frame)
    return frame


def load_universe(path: str | None = None) -> pd.DataFrame:
    return pd.read_csv(path or UNIVERSE_PATH)
