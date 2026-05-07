from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

SELECTION_HORIZONS: tuple[str, ...] = ("short", "mid", "long")
PIPELINE_TO_SELECTION_HORIZON = {
    "short": "short",
    "mid": "mid",
    "medium": "mid",
    "long": "long",
}
SELECTION_TO_PIPELINE_HORIZON = {
    "short": "short",
    "mid": "medium",
    "long": "long",
}


def normalize_selection_horizon(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in PIPELINE_TO_SELECTION_HORIZON:
        raise ValueError(f"Unsupported horizon {value!r}")
    return PIPELINE_TO_SELECTION_HORIZON[normalized]


def to_pipeline_horizon(value: str) -> str:
    normalized = normalize_selection_horizon(value)
    return SELECTION_TO_PIPELINE_HORIZON[normalized]


def next_forced_recalibration(now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    return base + timedelta(days=91)


def active_status_to_legacy_flag(status: str) -> bool:
    return status == "valid"


def invalidate_factor_x_ta_results(db: Session, symbol: str, selection_horizon: str) -> None:
    pipeline_horizon = to_pipeline_horizon(selection_horizon)
    params = {"symbol": symbol.upper(), "horizon": pipeline_horizon}
    db.execute(
        text("DELETE FROM signal_engine_family_result WHERE symbol = :symbol AND horizon = :horizon AND variant = 'factor_x_ta'"),
        params,
    )
    db.execute(
        text("DELETE FROM signal_engine_global_result WHERE symbol = :symbol AND horizon = :horizon AND variant = 'factor_x_ta'"),
        params,
    )
    db.execute(
        text("DELETE FROM wfo_signal_summary WHERE symbol = :symbol AND horizon = :horizon AND variant = 'factor_x_ta'"),
        params,
    )
    db.execute(
        text("DELETE FROM wfo_global_signal WHERE symbol = :symbol AND horizon = :horizon AND variant = 'factor_x_ta'"),
        params,
    )


def active_factor_ids_for_symbol_horizon(db: Session, symbol: str, selection_horizon: str) -> list[str]:
    rows = db.execute(
        text(
            """
            SELECT factor_canonical_id
            FROM stock_factor_relevance
            WHERE symbol = :symbol
              AND horizon = :horizon
              AND cusum_status = 'valid'
            ORDER BY CASE WHEN rank IS NULL THEN 1 ELSE 0 END,
                     rank ASC,
                     ABS(relevance_score) DESC,
                     factor_canonical_id
            """
        ),
        {"symbol": symbol.upper(), "horizon": normalize_selection_horizon(selection_horizon)},
    ).fetchall()
    return [str(row[0]) for row in rows]


def selected_factors_changed(previous: Iterable[str], current: Iterable[str]) -> bool:
    return list(previous) != list(current)
