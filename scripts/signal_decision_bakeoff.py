"""Run an offline bake-off of TA aggregation and threshold methods.

This script does not touch the app, API, frontend, migrations, or live scoring.
It evaluates candidate methods out-of-sample and writes research artifacts under
``research-out/decision-bakeoff``.

Example:
    python scripts/signal_decision_bakeoff.py \
        --from-db --source wfo --horizon monthly --oos-only

    # Or with explicit exports:
    python scripts/signal_decision_bakeoff.py \
        --score-history-csv exports/signal_score_history.csv \
        --prices-csv exports/prices.csv \
        --source wfo --horizon monthly --oos-only
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import create_engine, text
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "core"))
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from quant_core.research.decision_bakeoff import (  # noqa: E402
    BakeoffConfig,
    HORIZON_FORWARD_WINDOWS,
    run_bakeoff,
    write_bakeoff_artifacts,
)
from services.api.app.market_data_loader import load_ohlcv_from_store  # noqa: E402


DEFAULT_DATABASE_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"
DEFAULT_PRICE_TIMEFRAME = "1D"


def _parse_csv_list(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return tuple(parts) or None


def _parse_int_list(value: str | None) -> tuple[int, ...] | None:
    if value is None:
        return None
    parts = [int(p.strip()) for p in value.split(",") if p.strip()]
    return tuple(parts) or None


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def _read_prices(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix not in {".xlsx", ".xls"}:
        return _read_table(path)

    sheets = pd.read_excel(path, sheet_name=None)
    frames: list[pd.DataFrame] = []
    for sheet_name, frame in sheets.items():
        if frame.empty:
            continue
        cur = frame.copy()
        if "symbol" not in {str(c).lower() for c in cur.columns}:
            cur["symbol"] = str(sheet_name).upper()
        frames.append(cur)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _to_datetime_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    date_candidates = ("date", "timestamp", "datetime", "time", "trading_date", "index")
    cols = {str(c).lower(): c for c in frame.columns}
    for candidate in date_candidates:
        raw = cols.get(candidate)
        if raw is not None:
            frame = frame.copy()
            frame["date"] = pd.to_datetime(frame[raw], errors="coerce")
            break
    else:
        # Already index based
        if isinstance(frame.index, pd.DatetimeIndex):
            frame = frame.reset_index().rename(columns={frame.index.name or "index": "date"})
        else:
            return pd.DataFrame()
    frame = frame.dropna(subset=["date"])
    return frame


def _dedupe_lowercase_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate columns after lowercasing while keeping first occurrence."""
    renamed = frame.copy()
    renamed.columns = [str(c).lower() for c in renamed.columns]
    if not renamed.columns.has_duplicates:
        return renamed

    keep_mask = ~renamed.columns.duplicated(keep="first")
    return renamed.loc[:, keep_mask]


def _load_ohlcv_long_from_db(
    db_url: str,
    symbols: tuple[str, ...] | None,
    timeframe: str = DEFAULT_PRICE_TIMEFRAME,
) -> pd.DataFrame:
    engine = create_engine(db_url, pool_pre_ping=True)
    symbol_filter = tuple(_normalize_symbol(s) for s in symbols) if symbols else None
    params: dict[str, object] = {"timeframe": str(timeframe).upper()}
    sql = (
        "SELECT symbol, object_key FROM market_data_store "
        "WHERE UPPER(timeframe) = :timeframe AND object_key IS NOT NULL"
    )
    if symbol_filter:
        sql += " AND symbol = ANY(:symbols)"
        params["symbols"] = list(symbol_filter)
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    if not rows:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    missing: list[str] = []
    for row in rows:
        symbol = _normalize_symbol(row["symbol"])
        object_key = str(row["object_key"] or "").strip()
        if not object_key:
            missing.append(symbol)
            continue
        try:
            ohlcv = load_ohlcv_from_store(object_key=object_key)
        except Exception:
            missing.append(symbol)
            continue

        frame = _to_datetime_columns(ohlcv.reset_index())
        if frame.empty or "close" not in {str(c).lower() for c in frame.columns}:
            continue
        frame = _dedupe_lowercase_columns(frame)
        frame["symbol"] = symbol
        if "open" not in frame.columns and "close" in frame.columns:
            frame["open"] = frame["close"]
        if "high" not in frame.columns and "open" in frame.columns and "low" in frame.columns:
            frame["high"] = frame["open"]
        if "low" not in frame.columns:
            frame["low"] = frame["open"]
        if "volume" not in frame.columns:
            frame["volume"] = float("nan")
        frames.append(
            frame.reindex(
                columns=["date", "symbol", "open", "high", "low", "close", "volume"]
            ).copy()
        )

    if not frames:
        return pd.DataFrame()
    if missing:
        missing_symbols = ", ".join(sorted(set(missing)))
        print(f"Skipped {len(missing)} symbols due to missing price load: {missing_symbols}")
    return pd.concat(frames, ignore_index=True)


def _load_score_history_from_db(
    db_url: str,
    source: str,
    horizon: str,
    symbols: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    engine = create_engine(db_url, pool_pre_ping=True)
    params: dict[str, object] = {
        "source": source,
        "horizon": horizon,
    }
    sql = (
        "SELECT date, symbol, source, horizon, category, score_pct, is_oos "
        "FROM signal_score_history WHERE source = :source AND horizon = :horizon"
    )
    symbol_filter = tuple(_normalize_symbol(s) for s in symbols) if symbols else None
    if symbol_filter:
        sql += " AND symbol = ANY(:symbols)"
        params["symbols"] = list(symbol_filter)
    with engine.connect() as conn:
        score_history = pd.read_sql_query(text(sql), conn, params=params)

    if score_history.empty:
        return score_history
    score_history["date"] = pd.to_datetime(score_history["date"], errors="coerce")
    score_history["symbol"] = score_history["symbol"].astype(str).str.upper().str.strip()
    score_history = score_history.dropna(subset=["date", "symbol", "category"])
    return score_history


def _resolve_matching_sources(
    db_url: str,
    source_prefix: str,
    horizon: str,
) -> list[str]:
    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT source FROM signal_score_history WHERE source LIKE :source_prefix AND horizon = :horizon"),
            {"source_prefix": f"{source_prefix}:%", "horizon": horizon},
        ).fetchall()
    return sorted({str(row[0]) for row in rows})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline TA decision-method bake-off. Writes research artifacts only.",
    )
    parser.add_argument("--from-db", action="store_true",
                        help="Load score history + prices from app database storage.")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
                        help=f"SQLAlchemy database URL (defaults to DATABASE_URL or {DEFAULT_DATABASE_URL}).")
    parser.add_argument("--score-history-csv", type=Path,
                        help="CSV/parquet/xlsx export of signal_score_history.")
    parser.add_argument("--prices-csv", type=Path,
                        help="CSV/parquet/xlsx price export. Long format or Excel sheet-per-symbol is accepted.")
    parser.add_argument("--price-timeframe", default=DEFAULT_PRICE_TIMEFRAME,
                        help="Market data timeframe when loading from DB (default: 1D).")
    parser.add_argument("--source", required=True,
                        help="Score source to evaluate, e.g. wfo or engine:expanded_ta_simple.")
    parser.add_argument("--horizon", required=True,
                        help="Signal horizon, e.g. weekly/monthly/quarterly or short/medium/long.")
    parser.add_argument("--symbols", default=None,
                        help="Optional comma-separated symbol filter.")
    parser.add_argument("--fwd-horizons", default=None,
                        help="Optional comma-separated forward horizons. Defaults by horizon.")
    parser.add_argument("--oos-only", action="store_true",
                        help="Use only rows where signal_score_history.is_oos is true.")
    parser.add_argument("--include-optional-ml", action="store_true",
                        help="Also test the optional tree_regressor challenger.")
    parser.add_argument("--cost-bps", type=float, default=10.0,
                        help="Per-decision cost applied to non-hold actions.")
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--min-train-dates", type=int, default=120)
    parser.add_argument("--min-test-dates", type=int, default=30)
    parser.add_argument("--min-action-obs", type=int, default=8)
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="Output directory. Defaults to research-out/decision-bakeoff/<timestamp>.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.source
    if args.from_db:
        symbol_filter = _parse_csv_list(args.symbols)
        score_history = _load_score_history_from_db(args.db_url, source, args.horizon, symbol_filter)
        if score_history.empty and ":" not in source:
            candidates = _resolve_matching_sources(args.db_url, source, args.horizon)
            if len(candidates) == 1:
                source = candidates[0]
                print(f"Resolved source {args.source!r} to {source!r} for horizon {args.horizon!r}.")
                score_history = _load_score_history_from_db(args.db_url, source, args.horizon, symbol_filter)
            elif candidates:
                raise SystemExit(
                    f"No rows for source={args.source!r}, horizon={args.horizon!r}. "
                    "Available matching sources: " + ", ".join(candidates)
                )
            else:
                raise SystemExit(
                    f"No rows for source={args.source!r}, horizon={args.horizon!r}. "
                    "No source variants found with this prefix."
                )

        if score_history.empty:
            raise SystemExit(
                f"No rows in signal_score_history for source={source!r}, horizon={args.horizon!r}."
            )
        symbols = tuple(score_history["symbol"].dropna().astype(str).str.upper().unique().tolist())
        prices = _load_ohlcv_long_from_db(args.db_url, symbols, timeframe=args.price_timeframe)
    else:
        if args.score_history_csv is None or args.prices_csv is None:
            raise SystemExit(
                "Either run with --from-db or provide both --score-history-csv and --prices-csv."
            )

        score_path = args.score_history_csv.resolve()
        price_path = args.prices_csv.resolve()

        if not score_path.exists():
            raise SystemExit(f"score history file not found: {score_path}")
        if not price_path.exists():
            raise SystemExit(f"prices file not found: {price_path}")

        score_history = _read_table(score_path)
        prices = _read_prices(price_path)
    if score_history.empty:
        raise SystemExit("score history input is empty")
    if prices.empty:
        raise SystemExit("prices input is empty")

    fwd_horizons = _parse_int_list(args.fwd_horizons)
    if fwd_horizons is None:
        fwd_horizons = HORIZON_FORWARD_WINDOWS.get(args.horizon)

    config = BakeoffConfig(
        source=source,
        horizon=args.horizon,
        symbols=_parse_csv_list(args.symbols),
        fwd_horizons=fwd_horizons,
        n_splits=args.n_splits,
        min_train_dates=args.min_train_dates,
        min_test_dates=args.min_test_dates,
        min_action_obs=args.min_action_obs,
        cost_bps=args.cost_bps,
        use_oos_only=args.oos_only,
        include_optional_ml=args.include_optional_ml,
    )
    result = run_bakeoff(score_history, prices, config)

    if args.out_dir is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = REPO_ROOT / "research-out" / "decision-bakeoff" / stamp
    else:
        out_dir = args.out_dir
    out_path = write_bakeoff_artifacts(result, out_dir)

    print(result.summary_markdown())
    print(f"\nArtifacts written to: {out_path}")
    if result.metrics.empty:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
