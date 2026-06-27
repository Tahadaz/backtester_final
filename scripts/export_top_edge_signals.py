"""Export the top Edge signal candidates from the live app database.

This intentionally recomputes Edge from DB-backed score history and market data.
It does not read report artifacts, frontend static samples, or Redis cache.

Example:
    python scripts/export_top_edge_signals.py --output top_edge_signals.csv

Use DATABASE_URL or --db-url to point at the migrated app database.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

DEFAULT_DATABASE_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"
DEFAULT_OUTPUT = REPO_ROOT / "top_edge_signals.csv"
DEFAULT_MARKDOWN_OUTPUT = REPO_ROOT / "top_edge_signals.md"

DEFAULT_HORIZONS = ("weekly", "monthly", "quarterly")
DEFAULT_SOURCES = ("wfo", "signal_engine")
DEFAULT_BUCKETS = ("strong_buy", "buy", "sell", "strong_sell")

REQUIRED_TABLES = (
    "stock_master",
    "market_data_store",
    "signal_score_history",
    "wfo_signal_summary",
    "wfo_global_signal",
    "signal_engine_family_result",
    "signal_engine_global_result",
)


@dataclass(frozen=True)
class EdgeRow:
    rank: int | None
    symbol: str
    horizon: str
    source: str
    variant: str
    bucket: str
    direction: str
    edge_score: float | None
    n: int
    action_expected_return_net: float | None
    net_ci_lower: float | None
    net_ci_upper: float | None
    hit_rate: float | None
    hit_ci_lower: float | None
    fwd_horizon_bars: int | None
    mc_luck_pvalue_net: float | None
    mc_luck_pvalue_net_adj: float | None
    label_shuffle_pvalue_net: float | None
    label_shuffle_pvalue_net_adj: float | None
    n_gate: str
    wilson_gate: str
    mc_gate: str
    perm_gate: str
    freshness_gate: str
    positive_net_gate: str
    proven_edge_net: str
    freshness_n: int
    freshness_status: str
    proof_window_start: str | None
    proof_window_end: str | None
    methodology_version: str
    error: str | None = None


def _parse_csv_tokens(raw: str | None, defaults: Iterable[str]) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return tuple(defaults)
    return tuple(token.strip() for token in raw.split(",") if token.strip())


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _gate(value: bool) -> str:
    return "PASS" if bool(value) else "FAIL"


def _required_table_check(engine: Any) -> None:
    inspector = inspect(engine)
    existing = set(inspector.get_table_names(schema="public"))
    missing = [table for table in REQUIRED_TABLES if table not in existing]
    if missing:
        existing_preview = ", ".join(sorted(existing)[:30]) or "<none>"
        raise RuntimeError(
            "Connected database is not the migrated app DB. "
            f"Missing required tables: {', '.join(missing)}. "
            f"Existing public tables include: {existing_preview}."
        )


def _load_symbols(db: Session, requested: tuple[str, ...] | None) -> list[str]:
    from services.api.app.services.market_universe import is_masi_dashboard_member, list_signal_universe

    if requested:
        return sorted({symbol.strip().upper() for symbol in requested if symbol.strip()})

    rows = list_signal_universe(db)
    return sorted(
        {
            row.symbol.strip().upper()
            for row in rows
            if row.symbol and row.is_active and is_masi_dashboard_member(row)
        }
    )


def _row_from_metrics(
    *,
    metrics: Any,
    symbol: str,
    horizon: str,
    source: str,
    variant: str,
    bucket: str,
) -> EdgeRow:
    gates = metrics.gates
    expected_net = _finite(metrics.action_expected_return_net)
    return EdgeRow(
        rank=None,
        symbol=symbol,
        horizon=horizon,
        source=source,
        variant=variant,
        bucket=bucket,
        direction=str(metrics.direction),
        edge_score=_finite(metrics.edge_score),
        n=int(metrics.n or 0),
        action_expected_return_net=expected_net,
        net_ci_lower=_finite(metrics.action_expected_return_net_ci_lower),
        net_ci_upper=_finite(metrics.action_expected_return_net_ci_upper),
        hit_rate=_finite(metrics.hit_rate),
        hit_ci_lower=_finite(metrics.hit_ci_lower),
        fwd_horizon_bars=metrics.fwd_horizon_bars,
        mc_luck_pvalue_net=_finite(metrics.mc_luck_pvalue_net),
        mc_luck_pvalue_net_adj=_finite(metrics.mc_luck_pvalue_net_adj),
        label_shuffle_pvalue_net=_finite(metrics.label_shuffle_pvalue_net),
        label_shuffle_pvalue_net_adj=_finite(metrics.label_shuffle_pvalue_net_adj),
        n_gate=_gate(gates.n),
        wilson_gate=_gate(gates.wilson),
        mc_gate=_gate(gates.mc_net),
        perm_gate=_gate(gates.label_shuffle_net),
        freshness_gate=_gate(gates.freshness_net),
        positive_net_gate=_gate(expected_net is not None and expected_net > 0.0),
        proven_edge_net=_gate(metrics.proven_edge_net),
        freshness_n=int(metrics.freshness_n or 0),
        freshness_status=str(metrics.freshness_status or ""),
        proof_window_start=_iso_date(metrics.proof_window_start),
        proof_window_end=_iso_date(metrics.proof_window_end),
        methodology_version=str(metrics.methodology_version),
    )


def _rank_key(row: EdgeRow) -> tuple[int, float, float, float, int]:
    proven = 1 if row.proven_edge_net == "PASS" else 0
    return (
        proven,
        row.edge_score if row.edge_score is not None else float("-inf"),
        row.net_ci_lower if row.net_ci_lower is not None else float("-inf"),
        row.action_expected_return_net if row.action_expected_return_net is not None else float("-inf"),
        row.n,
    )


def _format_float(value: float | None, digits: int = 6) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def _format_pct(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value * 100.0:.2f}%"


def _write_csv(path: Path, rows: list[EdgeRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(rows[0]).keys()) if rows else list(EdgeRow.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _markdown_table(rows: list[EdgeRow]) -> str:
    columns = (
        "rank",
        "symbol",
        "horizon",
        "source",
        "variant",
        "bucket",
        "edge",
        "n",
        "net_er",
        "hit",
        "mc_adj",
        "perm_adj",
        "n_gate",
        "wilson",
        "mc",
        "perm",
        "fresh",
        "positive",
        "proven",
    )
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        values = (
            str(row.rank or ""),
            row.symbol,
            row.horizon,
            row.source,
            row.variant,
            row.bucket,
            _format_float(row.edge_score, 2),
            str(row.n),
            _format_pct(row.action_expected_return_net),
            _format_pct(row.hit_rate),
            _format_float(row.mc_luck_pvalue_net_adj, 4),
            _format_float(row.label_shuffle_pvalue_net_adj, 4),
            row.n_gate,
            row.wilson_gate,
            row.mc_gate,
            row.perm_gate,
            row.freshness_gate,
            row.positive_net_gate,
            row.proven_edge_net,
        )
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _write_markdown(path: Path, rows: list[EdgeRow], *, evaluated: int, missing: int, errors: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = [
        "# Top Edge Signals",
        "",
        f"Evaluated combinations with metrics: {evaluated}",
        f"Missing combinations: {missing}",
        f"Errored combinations: {errors}",
        "",
        _markdown_table(rows),
        "",
    ]
    path.write_text("\n".join(content), encoding="utf-8")


def export_top_edge_signals(args: argparse.Namespace) -> list[EdgeRow]:
    if args.db_url:
        os.environ["DATABASE_URL"] = args.db_url

    from core.quant_core.signal_engine.modes import ALL_SIGNAL_MODE_NAMES
    from services.api.app.routers.analytics import _build_edge_metrics_from_db

    db_url = args.db_url or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    engine = create_engine(db_url, pool_pre_ping=True)
    _required_table_check(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    horizons = _parse_csv_tokens(args.horizons, DEFAULT_HORIZONS)
    sources = _parse_csv_tokens(args.sources, DEFAULT_SOURCES)
    variants = _parse_csv_tokens(args.variants, ALL_SIGNAL_MODE_NAMES)
    buckets = _parse_csv_tokens(args.buckets, DEFAULT_BUCKETS)
    requested_symbols = _parse_csv_tokens(args.symbols, ()) if args.symbols else None
    multiple_testing_count = int(args.multiple_testing_count or (2 * len(ALL_SIGNAL_MODE_NAMES)))

    rows: list[EdgeRow] = []
    missing = 0
    errors = 0
    total = 0
    with session_factory() as db:
        symbols = _load_symbols(db, requested_symbols)
        if not symbols:
            raise RuntimeError("No symbols found for the requested universe.")
        combinations = len(symbols) * len(horizons) * len(sources) * len(variants) * len(buckets)
        print(
            "Evaluating "
            f"{combinations} combinations "
            f"({len(symbols)} symbols x {len(horizons)} horizons x {len(sources)} sources "
            f"x {len(variants)} variants x {len(buckets)} buckets)."
        )
        for symbol in symbols:
            for horizon in horizons:
                for source in sources:
                    for variant in variants:
                        for bucket in buckets:
                            total += 1
                            try:
                                metrics = _build_edge_metrics_from_db(
                                    symbol=symbol,
                                    horizon=horizon,
                                    source=source,
                                    variant=variant,
                                    cost_bps=float(args.cost_bps),
                                    db=db,
                                    multiple_testing_count=multiple_testing_count,
                                    bucket_override=bucket,
                                )
                            except Exception as exc:
                                errors += 1
                                db.rollback()
                                if args.include_errors:
                                    rows.append(
                                        EdgeRow(
                                            rank=None,
                                            symbol=symbol,
                                            horizon=horizon,
                                            source=source,
                                            variant=variant,
                                            bucket=bucket,
                                            direction="",
                                            edge_score=None,
                                            n=0,
                                            action_expected_return_net=None,
                                            net_ci_lower=None,
                                            net_ci_upper=None,
                                            hit_rate=None,
                                            hit_ci_lower=None,
                                            fwd_horizon_bars=None,
                                            mc_luck_pvalue_net=None,
                                            mc_luck_pvalue_net_adj=None,
                                            label_shuffle_pvalue_net=None,
                                            label_shuffle_pvalue_net_adj=None,
                                            n_gate="FAIL",
                                            wilson_gate="FAIL",
                                            mc_gate="FAIL",
                                            perm_gate="FAIL",
                                            freshness_gate="FAIL",
                                            positive_net_gate="FAIL",
                                            proven_edge_net="FAIL",
                                            freshness_n=0,
                                            freshness_status="error",
                                            proof_window_start=None,
                                            proof_window_end=None,
                                            methodology_version="",
                                            error=repr(exc),
                                        )
                                    )
                                continue
                            if metrics is None:
                                missing += 1
                                continue
                            if str(metrics.direction) == "none":
                                continue
                            rows.append(
                                _row_from_metrics(
                                    metrics=metrics,
                                    symbol=symbol,
                                    horizon=horizon,
                                    source=source,
                                    variant=variant,
                                    bucket=bucket,
                                )
                            )
                            if args.progress_every and total % int(args.progress_every) == 0:
                                print(f"Processed {total}/{combinations} combinations...")

    ranked = sorted(rows, key=_rank_key, reverse=True)[: int(args.limit)]
    ranked = [
        EdgeRow(rank=idx, **{k: v for k, v in asdict(row).items() if k != "rank"})
        for idx, row in enumerate(ranked, start=1)
    ]
    _write_csv(Path(args.output), ranked)
    _write_markdown(Path(args.markdown_output), ranked, evaluated=len(rows), missing=missing, errors=errors)
    print(f"Evaluated rows with metrics: {len(rows)}")
    print(f"Missing combinations: {missing}")
    print(f"Errored combinations: {errors}")
    print(f"Wrote CSV: {Path(args.output).resolve()}")
    print(f"Wrote Markdown: {Path(args.markdown_output).resolve()}")
    print()
    print(_markdown_table(ranked[: int(args.preview)]))
    return ranked


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--preview", type=int, default=25)
    parser.add_argument("--cost-bps", type=float, default=float(os.environ.get("EDGE_COST_BPS_PER_SIDE", "33")))
    parser.add_argument("--horizons", help="Comma-separated horizons. Default: weekly,monthly,quarterly")
    parser.add_argument("--sources", help="Comma-separated sources. Default: wfo,signal_engine")
    parser.add_argument("--variants", help="Comma-separated signal modes. Default: all registered modes")
    parser.add_argument("--buckets", help="Comma-separated buckets. Default: strong_buy,buy,sell,strong_sell")
    parser.add_argument("--symbols", help="Comma-separated symbol override. Default: active MASI signal universe")
    parser.add_argument("--multiple-testing-count", type=int)
    parser.add_argument("--include-errors", action="store_true")
    parser.add_argument("--progress-every", type=int, default=250)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        export_top_edge_signals(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
