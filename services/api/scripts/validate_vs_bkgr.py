from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.quant_core.fundamentals import DEFAULT_ASSUMPTIONS  # noqa: E402
from services.api.app.services import fundamentals as fundamental_service  # noqa: E402


DEFAULT_DB_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"
DEFAULT_FIXTURE = ROOT / "core" / "tests" / "fixtures" / "bkgr_jun2026.csv"
SUCCEEDED_IMPORT_STATUSES = ("succeeded", "partial")


@dataclass(frozen=True)
class BkgrRow:
    ticker: str
    name: str
    bkgr_target: float
    bkgr_upside_pct: float
    bkgr_rating: str


@dataclass
class ValidationRow:
    ticker: str
    name: str
    bkgr_target: float
    bkgr_upside_pct: float
    bkgr_rating: str
    engine_target: float | None
    current_price: float | None
    engine_upside_pct: float | None
    engine_rating: str
    confidence: float | None
    usable_models: int
    agreement: float | None
    import_id: str | None
    valuation_date: str | None
    warnings: list[str]


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _positive(value: Any) -> float | None:
    out = _num(value)
    return out if out is not None and out > 0 else None


def _load_fixture(path: Path) -> list[BkgrRow]:
    rows: list[BkgrRow] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            rows.append(
                BkgrRow(
                    ticker=str(raw["ticker"]).strip().upper(),
                    name=str(raw["name"]).strip(),
                    bkgr_target=float(raw["bkgr_target"]),
                    bkgr_upside_pct=float(raw["bkgr_upside_pct"]),
                    bkgr_rating=str(raw["bkgr_rating"]).strip(),
                )
            )
    return rows


def _latest_ensembles(db_url: str, symbols: list[str], scenario: str) -> dict[str, dict[str, Any]]:
    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with SessionLocal() as db:
        latest_snapshots = fundamental_service.latest_snapshot_rows_by_symbol(db, symbols=symbols, scope="all")
    latest_import_by_symbol = {
        symbol.upper(): str(row.import_id)
        for symbol, row in latest_snapshots.items()
    }
    latest_import_ids = sorted(set(latest_import_by_symbol.values()))
    if not latest_import_ids:
        return {}
    query = text(
        """
        SELECT
            e.symbol,
            e.import_id::text AS import_id,
            e.fair_value_base,
            e.current_price,
            e.upside_pct,
            e.confidence_score,
            e.usable_model_count,
            e.model_dispersion_cv,
            e.warnings_json,
            e.computed_at
        FROM fundamental_ensemble_result e
        JOIN fundamental_import i ON i.id = e.import_id
        WHERE e.scenario = :scenario
          AND e.symbol = ANY(:symbols)
          AND e.import_id::text = ANY(:import_ids)
          AND i.status = ANY(:statuses)
        ORDER BY e.symbol, e.computed_at DESC NULLS LAST
        """
    )
    cost_query = text(
        """
        SELECT v.symbol, v.import_id::text AS import_id, v.inputs_json
        FROM fundamental_valuation_result v
        WHERE v.scenario = :scenario
          AND v.symbol = ANY(:symbols)
          AND v.import_id::text = ANY(:import_ids)
        """
    )
    with engine.connect() as con:
        params = {
            "scenario": scenario,
            "symbols": symbols,
            "import_ids": latest_import_ids,
            "statuses": list(SUCCEEDED_IMPORT_STATUSES),
        }
        ensemble_rows = [dict(row) for row in con.execute(query, params).mappings()]
        valuation_rows = [dict(row) for row in con.execute(cost_query, params).mappings()]

    by_symbol: dict[str, dict[str, Any]] = {}
    for row in ensemble_rows:
        symbol = str(row["symbol"]).upper()
        if latest_import_by_symbol.get(symbol) != str(row.get("import_id")):
            continue
        if symbol not in by_symbol:
            by_symbol[symbol] = row
    input_values: dict[tuple[str, str], dict[str, list[float]]] = {}
    for row in valuation_rows:
        symbol = str(row["symbol"]).upper()
        import_id = str(row["import_id"])
        inputs = row.get("inputs_json") or {}
        bucket = input_values.setdefault((symbol, import_id), {"cost_of_equity": [], "dividend_yield": []})
        cost = _positive(inputs.get("cost_of_equity"))
        if cost is not None:
            bucket["cost_of_equity"].append(cost)
        dividend_yield = _num(inputs.get("dividend_yield"))
        if dividend_yield is not None and dividend_yield >= 0:
            bucket["dividend_yield"].append(dividend_yield)

    for symbol, row in by_symbol.items():
        key = (symbol, str(row.get("import_id")))
        bucket = input_values.get(key, {})
        costs = bucket.get("cost_of_equity", [])
        yields = bucket.get("dividend_yield", [])
        row["cost_of_equity"] = float(median(costs)) if costs else None
        row["dividend_yield"] = float(median(yields)) if yields else 0.0
    return by_symbol


def _agreement(model_dispersion_cv: Any) -> float | None:
    cv = _num(model_dispersion_cv)
    if cv is None:
        return None
    return max(0.0, 1.0 - min(1.0, cv))


def _engine_rating(row: dict[str, Any] | None) -> str:
    if row is None:
        return "NR"
    warnings = list(row.get("warnings_json") or [])
    if "no_usable_valuation_models" in warnings:
        return "NR"
    target = _positive(row.get("fair_value_base"))
    current = _positive(row.get("current_price"))
    confidence = _num(row.get("confidence_score"))
    usable = int(row.get("usable_model_count") or 0)
    agreement = _agreement(row.get("model_dispersion_cv"))
    if agreement is None:
        agreement = 1.0
    cost = _positive(row.get("cost_of_equity"))
    dividend_yield = _num(row.get("dividend_yield")) or 0.0
    if (
        target is None
        or current is None
        or confidence is None
        or cost is None
        or usable < 3
        or agreement < float(DEFAULT_ASSUMPTIONS["rating_agreement_min"])
        or confidence < float(DEFAULT_ASSUMPTIONS["rating_confidence_min"])
    ):
        return "NR"
    excess = target / current - 1.0 + dividend_yield - cost
    if excess > float(DEFAULT_ASSUMPTIONS["rating_buy_excess_return"]):
        return "BUY"
    if excess >= float(DEFAULT_ASSUMPTIONS["rating_accumulate_excess_return"]):
        return "ACCUMULATE"
    if excess >= float(DEFAULT_ASSUMPTIONS["rating_reduce_excess_return"]):
        return "HOLD"
    if excess >= float(DEFAULT_ASSUMPTIONS["rating_sell_excess_return"]):
        return "REDUCE"
    return "SELL"


def _validation_rows(fixture: list[BkgrRow], ensembles: dict[str, dict[str, Any]]) -> list[ValidationRow]:
    out: list[ValidationRow] = []
    for bkgr in fixture:
        row = ensembles.get(bkgr.ticker)
        target = _positive(row.get("fair_value_base")) if row else None
        current = _positive(row.get("current_price")) if row else None
        upside_pct = (target / current - 1.0) * 100.0 if target is not None and current is not None else None
        computed_at = row.get("computed_at") if row else None
        out.append(
            ValidationRow(
                ticker=bkgr.ticker,
                name=bkgr.name,
                bkgr_target=bkgr.bkgr_target,
                bkgr_upside_pct=bkgr.bkgr_upside_pct,
                bkgr_rating=bkgr.bkgr_rating,
                engine_target=target,
                current_price=current,
                engine_upside_pct=upside_pct,
                engine_rating=_engine_rating(row),
                confidence=_num(row.get("confidence_score")) if row else None,
                usable_models=int(row.get("usable_model_count") or 0) if row else 0,
                agreement=_agreement(row.get("model_dispersion_cv")) if row else None,
                import_id=str(row.get("import_id")) if row and row.get("import_id") else None,
                valuation_date=str(computed_at.date()) if hasattr(computed_at, "date") else str(computed_at)[:10] if computed_at else None,
                warnings=[str(item) for item in (row.get("warnings_json") or [])] if row else ["missing_engine_ensemble"],
            )
        )
    return out


def _sign(value: float, deadband: float = 0.0) -> int:
    if value > deadband:
        return 1
    if value < -deadband:
        return -1
    return 0


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = (index + 1 + end) / 2.0
        for original_index, _value in ordered[index:end]:
            ranks[original_index] = rank
        index = end
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mean_x = mean(xs)
    mean_y = mean(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sum((x - mean_x) ** 2 for x in xs)
    den_y = sum((y - mean_y) ** 2 for y in ys)
    if den_x <= 0 or den_y <= 0:
        return None
    return num / math.sqrt(den_x * den_y)


def _spearman(rows: list[ValidationRow]) -> float | None:
    pairs = [(row.engine_upside_pct, row.bkgr_upside_pct) for row in rows if row.engine_upside_pct is not None]
    if len(pairs) < 2:
        return None
    engine = [float(pair[0]) for pair in pairs]
    bkgr = [float(pair[1]) for pair in pairs]
    return _pearson(_ranks(engine), _ranks(bkgr))


def _metrics(rows: list[ValidationRow]) -> dict[str, Any]:
    with_upside = [row for row in rows if row.engine_upside_pct is not None]
    quorum = [row for row in with_upside if row.usable_models >= 3 and row.confidence is not None]
    agreement_rows = [row for row in quorum if _sign(float(row.engine_upside_pct)) == _sign(row.bkgr_upside_pct)]
    active = [row for row in with_upside if row.engine_rating != "NR" and row.usable_models >= 3]
    floor_rows = [row for row in active if row.engine_upside_pct is not None and row.engine_upside_pct <= -95.0]
    tail_rows = [row for row in active if row.engine_upside_pct is not None and row.engine_upside_pct > 150.0]
    engine_upsides = [float(row.engine_upside_pct) for row in with_upside]
    diff = [float(row.engine_upside_pct) - row.bkgr_upside_pct for row in with_upside]
    return {
        "fixture_count": len(rows),
        "overlap_count": len(with_upside),
        "quorum_count": len(quorum),
        "directional_agreement": (len(agreement_rows) / len(quorum)) if quorum else None,
        "mean_bias_pct": mean(engine_upsides) if engine_upsides else None,
        "median_engine_upside_pct": median(engine_upsides) if engine_upsides else None,
        "mean_diff_vs_bkgr_pct": mean(diff) if diff else None,
        "spearman": _spearman(with_upside),
        "buy_count": sum(1 for row in rows if row.engine_rating == "BUY"),
        "buy_or_accumulate_count": sum(1 for row in rows if row.engine_rating in {"BUY", "ACCUMULATE"}),
        "floor_count": len(floor_rows),
        "tail_count": len(tail_rows),
        "floor_tickers": [row.ticker for row in floor_rows],
        "tail_tickers": [row.ticker for row in tail_rows],
    }


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _print_report(rows: list[ValidationRow], metrics: dict[str, Any]) -> None:
    print("BKGR validation summary")
    print(f"fixture_count={metrics['fixture_count']} overlap_count={metrics['overlap_count']} quorum_count={metrics['quorum_count']}")
    print(f"directional_agreement={_fmt(metrics['directional_agreement'], 4)}")
    print(f"mean_bias_pct={_fmt(metrics['mean_bias_pct'])} median_engine_upside_pct={_fmt(metrics['median_engine_upside_pct'])}")
    print(f"mean_diff_vs_bkgr_pct={_fmt(metrics['mean_diff_vs_bkgr_pct'])} spearman={_fmt(metrics['spearman'], 4)}")
    print(f"buy_count={metrics['buy_count']} buy_or_accumulate_count={metrics['buy_or_accumulate_count']}")
    print(f"floor_count={metrics['floor_count']} floor_tickers={','.join(metrics['floor_tickers']) or '-'}")
    print(f"tail_count={metrics['tail_count']} tail_tickers={','.join(metrics['tail_tickers']) or '-'}")
    print()
    print("ticker,bkgr_upside_pct,engine_upside_pct,bkgr_rating,engine_rating,usable_models,confidence,agreement,target,current,warnings")
    for row in rows:
        print(
            ",".join(
                [
                    row.ticker,
                    _fmt(row.bkgr_upside_pct),
                    _fmt(row.engine_upside_pct),
                    row.bkgr_rating,
                    row.engine_rating,
                    str(row.usable_models),
                    _fmt(row.confidence, 3),
                    _fmt(row.agreement, 3),
                    _fmt(row.engine_target),
                    _fmt(row.current_price),
                    "|".join(row.warnings),
                ]
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate latest base fundamental ensembles against the BKGR Jun-2026 fixture.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", DEFAULT_DB_URL))
    parser.add_argument("--scenario", default="base")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of the text report.")
    args = parser.parse_args()

    fixture = _load_fixture(args.fixture)
    ensembles = _latest_ensembles(args.database_url, [row.ticker for row in fixture], args.scenario)
    rows = _validation_rows(fixture, ensembles)
    metrics = _metrics(rows)
    if args.json:
        print(json.dumps({"metrics": metrics, "rows": [asdict(row) for row in rows]}, indent=2, sort_keys=True))
    else:
        _print_report(rows, metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
