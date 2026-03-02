from __future__ import annotations
import sqlalchemy as sa
from sqlalchemy.orm import Session

def upsert_best_snapshot(
    session: Session,
    *,
    ticker: str,
    freq: str,
    dataset_id: str,
    start_at,
    end_at,
    strategy_name: str,
    portfolio_hash: str,
    best_trial_id: str,
    best_score: float,
    best_metrics: dict,
    best_params: dict,
):
    # Upsert: keep row if existing best_score is better
    stmt = sa.text("""
        INSERT INTO best_strategy_snapshot
            (ticker, freq, dataset_id, start_at, end_at, strategy_name, portfolio_hash,
             best_trial_id, best_score, best_metrics_json, best_params_json, updated_at)
        VALUES
            (:ticker, :freq, :dataset_id, :start_at, :end_at, :strategy_name, :portfolio_hash,
             :best_trial_id, :best_score, CAST(:best_metrics AS jsonb), CAST(:best_params AS jsonb), now())
        ON CONFLICT (ticker, freq, dataset_id, start_at, end_at, strategy_name, portfolio_hash)
        DO UPDATE SET
            best_trial_id = EXCLUDED.best_trial_id,
            best_score = EXCLUDED.best_score,
            best_metrics_json = EXCLUDED.best_metrics_json,
            best_params_json = EXCLUDED.best_params_json,
            updated_at = now()
        WHERE EXCLUDED.best_score > best_strategy_snapshot.best_score
    """)
    session.execute(stmt, {
        "ticker": ticker,
        "freq": freq,
        "dataset_id": dataset_id,
        "start_at": start_at,
        "end_at": end_at,
        "strategy_name": strategy_name,
        "portfolio_hash": portfolio_hash,
        "best_trial_id": best_trial_id,
        "best_score": best_score,
        "best_metrics": sa.text(f"'{_escape_json(best_metrics)}'"),
        "best_params": sa.text(f"'{_escape_json(best_params)}'"),
    })

def _escape_json(obj: dict) -> str:
    # safe minimal escaping for embedding; we pass through json.dumps then quote
    import json
    return json.dumps(obj, ensure_ascii=False).replace("'", "''")
