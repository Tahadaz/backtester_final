from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.quant_core.fundamentals.signal_backtest import (  # noqa: E402
    PITSignalSnapshot,
    SignalBacktestConfig,
    run_signal_backtest,
)
from services.api.app import models  # noqa: E402
from services.api.app.json_sanitize import sanitize_json_compatible  # noqa: E402
from services.api.app.services.fundamentals import (  # noqa: E402
    SUCCEEDED_IMPORT_STATUSES,
    _price_history_for_signal_backtest,
    _signal_backtest_symbols,
)
from services.worker.db import SessionLocal  # noqa: E402


INTERIM_PERIOD_TYPES = ("quarterly", "semiannual")
MONEY_METRIC_BUCKETS = {
    "PNB": "topline",
    "CHIFFRE_DAFFAIRES": "topline",
    "CLEAN_CHIFFRE_DAFFAIRES": "topline",
    "REVENUE": "topline",
    "RBE": "operating",
    "RESULTAT_DEXPLOITATION": "operating",
    "OPERATING_INCOME": "operating",
    "EBIT": "operating",
    "RNPG": "net_income",
    "RESULTAT_NET": "net_income",
    "CLEAN_RESULTAT_NET": "net_income",
    "NETINCOME": "net_income",
    "NET_INCOME": "net_income",
}


@dataclass(frozen=True)
class PeriodValue:
    symbol: str
    as_of_date: dt.date
    fiscal_year: int
    period_type: str
    period_label: str
    bucket: str
    metric_name: str
    metric_value: float
    source_id: str


def _normalize_metric(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
    return re.sub(r"_+", "_", text)


def _metric_bucket(metric_name: str) -> str | None:
    return MONEY_METRIC_BUCKETS.get(_normalize_metric(metric_name))


def _finite(value: Any) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric)


def _safe_growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0) or not _finite(current) or not _finite(previous):
        return None
    return float((current - previous) / abs(previous))


def _winsor(value: float, limit: float | None) -> float:
    if limit is None or limit <= 0:
        return value
    return max(-float(limit), min(float(limit), value))


def _period_values(db, *, symbols: list[str], mode: str) -> list[PeriodValue]:
    query = (
        db.query(models.FundamentalPeriodMetric, models.FundamentalSourceDocument)
        .join(models.FundamentalSourceDocument, models.FundamentalPeriodMetric.source_document_id == models.FundamentalSourceDocument.id)
        .join(models.FundamentalImport, models.FundamentalPeriodMetric.import_id == models.FundamentalImport.id)
        .filter(models.FundamentalImport.status.in_(SUCCEEDED_IMPORT_STATUSES))
        .filter(models.FundamentalPeriodMetric.symbol.in_(symbols))
        .filter(models.FundamentalPeriodMetric.metric_value.isnot(None))
        .filter(models.FundamentalPeriodMetric.is_proxy.is_(False))
        .filter(models.FundamentalSourceDocument.publication_date.isnot(None))
    )
    if mode == "annual":
        query = query.filter(models.FundamentalPeriodMetric.period_type == "annual")
    elif mode == "interim":
        query = query.filter(models.FundamentalPeriodMetric.period_type.in_(INTERIM_PERIOD_TYPES))
    else:
        raise ValueError("mode must be annual or interim")

    best: dict[tuple[str, dt.date, int, str, str, str], tuple[int, PeriodValue]] = {}
    for metric, document in query.all():
        bucket = _metric_bucket(str(metric.metric_name))
        if bucket is None or not _finite(metric.metric_value):
            continue
        as_of_date = document.publication_date
        if as_of_date is None:
            continue
        value = PeriodValue(
            symbol=str(metric.symbol).upper(),
            as_of_date=as_of_date,
            fiscal_year=int(metric.fiscal_year),
            period_type=str(metric.period_type),
            period_label=str(metric.period_label),
            bucket=bucket,
            metric_name=str(metric.metric_name),
            metric_value=float(metric.metric_value),
            source_id=f"{metric.import_id}:{metric.source_document_id}:{metric.id}",
        )
        key = (value.symbol, value.as_of_date, value.fiscal_year, value.period_type, value.period_label, value.bucket)
        rank = int(metric.id or 0)
        if key not in best or rank > best[key][0]:
            best[key] = (rank, value)
    return sorted(
        [value for _rank, value in best.values()],
        key=lambda item: (item.as_of_date, item.symbol, item.fiscal_year, item.period_type, item.period_label, item.bucket),
    )


def build_growth_snapshots(
    period_values: list[PeriodValue],
    *,
    mode: str,
    winsor_limit: float | None,
) -> dict[str, list[PITSignalSnapshot]]:
    by_event: dict[tuple[dt.date, str], list[PeriodValue]] = defaultdict(list)
    for row in period_values:
        by_event[(row.as_of_date, row.symbol)].append(row)

    state: dict[str, dict[tuple[str, str, str, int], float]] = defaultdict(dict)
    snapshots: dict[str, list[PITSignalSnapshot]] = defaultdict(list)
    for as_of_date, symbol in sorted(by_event):
        for row in by_event[(as_of_date, symbol)]:
            state[symbol][(row.bucket, row.period_type, row.period_label, row.fiscal_year)] = row.metric_value

        growths: list[float] = []
        series_keys = sorted({key[:3] for key in state[symbol]})
        for bucket, period_type, period_label in series_keys:
            years = sorted(
                year
                for item_bucket, item_type, item_label, year in state[symbol]
                if item_bucket == bucket and item_type == period_type and item_label == period_label
            )
            if not years:
                continue
            current_year = years[-1]
            current = state[symbol].get((bucket, period_type, period_label, current_year))
            previous = state[symbol].get((bucket, period_type, period_label, current_year - 1))
            growth = _safe_growth(current, previous)
            if growth is not None:
                growths.append(_winsor(growth, winsor_limit))

        if growths:
            snapshots[symbol].append(
                PITSignalSnapshot(
                    symbol=symbol,
                    as_of_date=as_of_date,
                    pillar_score=float(np.mean(growths)),
                    source_id=f"{mode}:{as_of_date.isoformat()}:{len(growths)}",
                )
            )
    return dict(snapshots)


def _result_summary(result, *, signal_events: dict[str, list[PITSignalSnapshot]]) -> dict[str, Any]:
    equity_curve = result.equity_curve
    last_equity = float(equity_curve[-1]["equity"]) if equity_curve else None
    last_drawdown = float(equity_curve[-1].get("drawdown") or 0.0) if equity_curve else None
    last_sharpe = float(equity_curve[-1].get("sharpe_to_date") or 0.0) if equity_curve else None
    return {
        "symbols_with_signals": len(signal_events),
        "signal_event_count": sum(len(items) for items in signal_events.values()),
        "rebalance_count": len(equity_curve),
        "final_equity": last_equity,
        "total_return": (last_equity - 1.0) if last_equity is not None else None,
        "rank_ic": result.ic.get("rank_ic"),
        "sharpe": last_sharpe,
        "last_drawdown": last_drawdown,
        "quintile_returns": result.quintile_returns,
        "ic_decay": result.ic.get("ic_decay"),
        "warnings": result.warnings,
    }


def run_comparison(args: argparse.Namespace) -> dict[str, Any]:
    db = SessionLocal()
    try:
        symbols = _signal_backtest_symbols(db, universe=args.universe, symbols=args.symbols)
        prices, price_warnings = _price_history_for_signal_backtest(db, symbols=symbols)
        annual_values = _period_values(db, symbols=symbols, mode="annual")
        interim_values = _period_values(db, symbols=symbols, mode="interim")
    finally:
        db.close()

    annual_signals = build_growth_snapshots(annual_values, mode="annual", winsor_limit=args.winsor)
    interim_signals = build_growth_snapshots(interim_values, mode="interim", winsor_limit=args.winsor)
    config = SignalBacktestConfig(
        signal="pillar_score",
        universe=args.universe,
        start=args.start,
        end=args.end,
        transaction_cost_bps=args.transaction_cost_bps,
        long_short=args.long_short,
        quintiles=args.quintiles,
    )
    annual_result = run_signal_backtest(
        price_history=prices,
        snapshots_by_symbol=annual_signals,
        config=config,
        run_id="annual_period_growth",
    )
    interim_result = run_signal_backtest(
        price_history=prices,
        snapshots_by_symbol=interim_signals,
        config=config,
        run_id="interim_period_growth",
    )
    annual_summary = _result_summary(annual_result, signal_events=annual_signals)
    interim_summary = _result_summary(interim_result, signal_events=interim_signals)
    return sanitize_json_compatible(
        {
            "signal_definition": {
                "annual": "FY same-metric YoY growth from FundamentalPeriodMetric",
                "interim": "quarterly + semiannual same-period YoY growth from FundamentalPeriodMetric",
                "metric_buckets": sorted(set(MONEY_METRIC_BUCKETS.values())),
                "winsor_limit": args.winsor,
            },
            "params": {
                "universe": args.universe,
                "symbols": symbols,
                "start": args.start.isoformat() if args.start else None,
                "end": args.end.isoformat() if args.end else None,
                "transaction_cost_bps": args.transaction_cost_bps,
                "long_short": args.long_short,
                "quintiles": args.quintiles,
            },
            "data": {
                "price_symbols": sorted(prices),
                "price_warnings": price_warnings,
                "annual_period_rows": len(annual_values),
                "interim_period_rows": len(interim_values),
            },
            "annual": annual_summary,
            "interim": interim_summary,
            "delta_interim_minus_annual": {
                "total_return": (
                    interim_summary["total_return"] - annual_summary["total_return"]
                    if interim_summary["total_return"] is not None and annual_summary["total_return"] is not None
                    else None
                ),
                "rank_ic": (
                    interim_summary["rank_ic"] - annual_summary["rank_ic"]
                    if interim_summary["rank_ic"] is not None and annual_summary["rank_ic"] is not None
                    else None
                ),
                "sharpe": (
                    interim_summary["sharpe"] - annual_summary["sharpe"]
                    if interim_summary["sharpe"] is not None and annual_summary["sharpe"] is not None
                    else None
                ),
            },
        }
    )


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    return dt.date.fromisoformat(value)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare annual FY growth signals against joined quarterly+semiannual interim growth signals.")
    parser.add_argument("--universe", choices=("masi20", "full_masi", "custom"), default="full_masi")
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--start", type=_parse_date, default=None)
    parser.add_argument("--end", type=_parse_date, default=None)
    parser.add_argument("--transaction-cost-bps", type=float, default=25.0)
    parser.add_argument("--long-short", action="store_true")
    parser.add_argument("--quintiles", type=int, default=5)
    parser.add_argument("--winsor", type=float, default=2.0, help="Cap YoY growth at +/- this value. Use 0 to disable.")
    return parser.parse_args()


def main() -> None:
    print(json.dumps(run_comparison(_parse_args()), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
