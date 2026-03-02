from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Artifact, Run, StrategyLeaderboard
from ..schemas.results import StockDetailOut, StockSummaryOut
from ..storage import presign_get


router = APIRouter(prefix="/results", tags=["results"])


def _as_summary_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _split_best_params_and_summary(raw: Any) -> tuple[dict[str, Any] | None, dict[str, float | None]]:
    if not isinstance(raw, dict):
        return None, {"total_return": None, "win_pct": None, "max_drawdown": None, "sharpe": None}
    params = dict(raw)
    summary_raw = params.pop("_summary", None)
    summary_dict = summary_raw if isinstance(summary_raw, dict) else {}
    summary = {
        "total_return": _as_summary_float(summary_dict.get("total_return")),
        "win_pct": _as_summary_float(summary_dict.get("win_pct")),
        "max_drawdown": _as_summary_float(summary_dict.get("max_drawdown")),
        "sharpe": _as_summary_float(summary_dict.get("sharpe")),
    }
    return params, summary


def _resolve_run(db: Session, run_id: UUID | None) -> Run:
    if run_id is not None:
        run = db.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    run = (
        db.query(Run)
        .filter(Run.status == "succeeded", Run.run_type == "optimization")
        .order_by(Run.finished_at.desc().nullslast(), Run.created_at.desc())
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="no succeeded optimization runs found")
    return run


def _signal_value(row: StrategyLeaderboard) -> float:
    if row.signal_today is not None:
        return float(row.signal_today)
    label = str(row.signal_label or "").upper()
    if label == "BUY":
        return 1.0
    if label == "SELL":
        return -1.0
    return 0.0


def _signal_label(signal: float) -> str:
    if signal > 0:
        return "BUY"
    if signal < 0:
        return "SELL"
    return "HOLD"


def _vote(rows: list[StrategyLeaderboard]) -> dict[str, float | int | str]:
    if not rows:
        return {
            "majority_vote": "HOLD",
            "weighted_vote": "HOLD",
            "majority_buys": 0,
            "majority_sells": 0,
            "majority_holds": 0,
            "weighted_score": 0.0,
            "strategy_count": 0,
        }

    signals = [_signal_value(r) for r in rows]
    buys = sum(1 for x in signals if x > 0)
    sells = sum(1 for x in signals if x < 0)
    holds = sum(1 for x in signals if x == 0)

    majority_vote = "HOLD"
    if buys > sells and buys > holds:
        majority_vote = "BUY"
    elif sells > buys and sells > holds:
        majority_vote = "SELL"

    weighted_sum = 0.0
    total_weight = 0.0
    for r, s in zip(rows, signals):
        w = float(max(float(r.cagr or 0.0), 0.0))
        weighted_sum += s * w
        total_weight += w
    weighted_score = (weighted_sum / total_weight) if total_weight > 0 else 0.0
    weighted_vote = "HOLD"
    if weighted_score > 0.1:
        weighted_vote = "BUY"
    elif weighted_score < -0.1:
        weighted_vote = "SELL"

    return {
        "majority_vote": majority_vote,
        "weighted_vote": weighted_vote,
        "majority_buys": int(buys),
        "majority_sells": int(sells),
        "majority_holds": int(holds),
        "weighted_score": float(weighted_score),
        "strategy_count": int(len(rows)),
    }


def _artifact_urls(db: Session, run_id: UUID, symbol: str) -> dict[tuple[str, str], str]:
    rows = (
        db.query(Artifact)
        .filter(
            Artifact.run_id == run_id,
            Artifact.symbol == symbol,
            Artifact.artifact_type.in_(("strategy_plotly_json", "strategy_trade_ledger_csv")),
        )
        .all()
    )
    out: dict[tuple[str, str, str], str] = {}
    for row in rows:
        name = str(row.name or "").strip().lower()
        kind = name.split(".", 1)[0].strip().lower()
        base = name.split(".", 1)[1].strip().lower() if "." in name else name
        if not kind:
            continue
        out[(kind, base, row.artifact_type)] = presign_get(row.object_key, expires_seconds=300)
    return out


@router.get("/stocks", response_model=list[StockSummaryOut])
def list_stocks(
    run_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    run = _resolve_run(db, run_id)
    rows = (
        db.query(StrategyLeaderboard)
        .filter(StrategyLeaderboard.run_id == run.id, StrategyLeaderboard.rank == 1)
        .order_by(StrategyLeaderboard.symbol.asc(), StrategyLeaderboard.strategy_kind.asc())
        .all()
    )
    grouped: dict[str, list[StrategyLeaderboard]] = defaultdict(list)
    for row in rows:
        grouped[str(row.symbol)].append(row)

    out: list[dict] = []
    for symbol, symbol_rows in grouped.items():
        vote = _vote(symbol_rows)
        out.append(
            {
                "run_id": run.id,
                "symbol": symbol,
                **vote,
            }
        )
    out.sort(key=lambda x: str(x["symbol"]))
    return out


@router.get("/stocks/{symbol}", response_model=StockDetailOut)
def get_stock_detail(
    symbol: str,
    run_id: UUID | None = Query(default=None),
    best_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    run = _resolve_run(db, run_id)

    q = db.query(StrategyLeaderboard).filter(
        StrategyLeaderboard.run_id == run.id,
        StrategyLeaderboard.symbol == symbol,
    )
    if best_only:
        q = q.filter(StrategyLeaderboard.rank == 1)

    rows = q.order_by(
        StrategyLeaderboard.rank.asc(),
        StrategyLeaderboard.cagr.desc().nullslast(),
        StrategyLeaderboard.strategy_kind.asc(),
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="no leaderboard rows found for symbol")

    best_rows = [r for r in rows if int(r.rank) == 1] if not best_only else rows
    vote = _vote(best_rows)
    urls = _artifact_urls(db, run.id, symbol)

    strategies = []
    for row in rows:
        kind = str(row.strategy_kind).lower()
        sig = _signal_value(row)
        best_params_json, summary = _split_best_params_and_summary(row.best_params_json)
        strategies.append(
            {
                "strategy_kind": row.strategy_kind,
                "rank": int(row.rank),
                "pnl": row.pnl,
                "cagr": row.cagr,
                "total_return": summary.get("total_return"),
                "win_pct": summary.get("win_pct"),
                "max_drawdown": summary.get("max_drawdown"),
                "sharpe": summary.get("sharpe"),
                "efficiency": row.efficiency,
                "n_fills": row.n_fills,
                "signal_today": sig,
                "signal_label": row.signal_label or _signal_label(sig),
                "signal_date": row.signal_date,
                "best_params_json": best_params_json,
                "plot_url": urls.get((kind, "price_indicators_trades", "strategy_plotly_json")),
                "ledger_url": urls.get((kind, "trade_ledger", "strategy_trade_ledger_csv")),
            }
        )

    return {
        "run_id": run.id,
        "symbol": symbol,
        **vote,
        "strategies": strategies,
        "generated_at": datetime.now(timezone.utc),
    }
