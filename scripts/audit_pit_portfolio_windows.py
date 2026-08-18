#!/usr/bin/env python3
"""Publish deterministic, persisted-only PIT portfolio window attribution."""

from __future__ import annotations

import argparse
import csv
from datetime import date
import json
from pathlib import Path
import shutil
import sys
import uuid

from sqlalchemy.orm import Session

from core.quant_core.historical_portfolio import METHODOLOGY_VERSION
from services.api.app import models
from services.api.app.db import _ensure_session_factory


DEFAULT_WINDOWS = ((date(2024, 1, 1), date(2024, 5, 31)), (date(2024, 10, 1), date(2025, 1, 31)))
ATTRIBUTIONS = (
    "missing_data", "actionability_rejection", "no_actionable_winner", "gate_veto",
    "sizing_rejection", "short_signal_liquidation", "long_entry",
    "hold_existing_exposure", "flat_no_action",
)
MISSING_STATUSES = {"no_price_data", "no_score_data", "stale_score", "insufficient_history", "evidence_unavailable"}
SIZING_REASONS = {
    "insufficient_point_in_time_kelly_history", "non_positive_kelly", "adv20_unavailable",
    "capacity_rejected", "insufficient_cash", "missing_entry_open", "missing_opportunity_payload",
}


def _window(value: str) -> tuple[date, date]:
    try:
        start_raw, end_raw = value.split(":", 1)
        start, end = date.fromisoformat(start_raw), date.fromisoformat(end_raw)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("window must be START:END using ISO dates") from exc
    if end < start:
        raise argparse.ArgumentTypeError("window end must be on or after start")
    return start, end


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _build_rows(db: Session, run, windows: list[tuple[date, date]]):
    config = run.config_json or {}
    run_start, run_end = date.fromisoformat(str(config["start_date"])), date.fromisoformat(str(config["end_date"]))
    for start, end in windows:
        if start < run_start or end > run_end:
            raise ValueError(f"requested window {start}:{end} is outside run coverage {run_start}:{run_end}")
    query = db.query(models.HistoricalTradeOpportunity).filter(
        models.HistoricalTradeOpportunity.methodology_version == run.methodology_version,
        models.HistoricalTradeOpportunity.decision_date >= min(start for start, _ in windows),
        models.HistoricalTradeOpportunity.decision_date <= max(end for _, end in windows),
    )
    symbols = list(config.get("symbols") or [])
    if symbols:
        query = query.filter(models.HistoricalTradeOpportunity.symbol.in_(symbols))
    decisions = query.order_by(
        models.HistoricalTradeOpportunity.decision_date,
        models.HistoricalTradeOpportunity.symbol,
        models.HistoricalTradeOpportunity.horizon,
        models.HistoricalTradeOpportunity.variant,
    ).all()
    groups = {}
    for item in decisions:
        if not any(start <= item.decision_date <= end for start, end in windows):
            continue
        groups.setdefault((item.decision_date.isoformat(), item.symbol, item.horizon), []).append(item)
    if not groups:
        raise ValueError("required decision records are missing")
    events = (run.diagnostics_json or {}).get("execution_events_v1")
    if not isinstance(events, list):
        raise ValueError("required diagnostics_json.execution_events_v1 is missing")
    baseline = {
        (item.get("decision_date"), item.get("symbol"), item.get("horizon")): item
        for item in events if item.get("scenario") == "baseline"
    }
    trades = run.trades_json or []
    rows, details = [], []
    for key, items in sorted(groups.items()):
        if len(items) != 8:
            raise ValueError(f"required decision records are incomplete for {key}: expected 8, got {len(items)}")
        event = baseline.get(key)
        if event is None:
            raise ValueError(f"required baseline execution event is missing for {key}")
        winner = next((item for item in items if item.reconstructed_dashboard_winner), None)
        statuses = {item.status for item in items}
        reasons = {
            reason
            for item in items
            for reason in ((item.decision_json or {}).get("actionability_reasons") or [])
        }
        reason = event.get("reason")
        flags = {
            "missing_data": bool(statuses & MISSING_STATUSES) or reason in {
                "missing_next_available_open", "missing_entry_open", "missing_market_data",
            },
            "actionability_rejection": bool(reasons),
            "no_actionable_winner": winner is None,
            "gate_veto": reason == "user_gate_rejected_winner",
            "sizing_rejection": reason in SIZING_REASONS,
            "short_signal_liquidation": reason == "short_signal_liquidation",
            "long_entry": event.get("execution_action") == "enter_long",
            "hold_existing_exposure": event.get("execution_action") == "hold",
            "flat_no_action": event.get("execution_action") == "no_action" and event.get("position_before") == "flat",
        }
        if not any(flags.values()):
            flags["flat_no_action"] = True
        primary = next(name for name in ATTRIBUTIONS if flags[name])
        row = {
            "decision_date": key[0], "symbol": key[1], "horizon": key[2],
            **flags, "primary_attribution": primary,
            "winner_variant": winner.variant if winner else None,
            "signal_direction": (winner.decision_json or {}).get("signal_direction") if winner else None,
            "execution_action": event.get("execution_action"), "execution_reason": reason,
        }
        rows.append(row)
        relevant_trades = [
            trade for trade in trades
            if trade.get("symbol") == key[1] and trade.get("horizon") == key[2]
            and trade.get("decision_date") == key[0]
        ]
        details.append({
            "key": {"decision_date": key[0], "symbol": key[1], "horizon": key[2]},
            "attribution": row,
            "decisions": [{
                "variant": item.variant, "status": item.status, "actionable": item.actionable,
                "winner": item.reconstructed_dashboard_winner, "decision": item.decision_json,
                "input_hash": item.input_hash,
            } for item in items],
            "execution_event": event, "trades": relevant_trades,
        })
    return rows, details


def publish_audit(
    db: Session,
    *,
    run_id: uuid.UUID,
    windows: list[tuple[date, date]],
    destination: Path,
) -> dict:
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    run = db.query(models.HistoricalPortfolioBacktestRun).filter_by(id=run_id).first()
    if run is None:
        raise ValueError(f"run not found: {run_id}")
    if run.status != "succeeded":
        raise ValueError(f"run is not succeeded: {run.status}")
    rows, details = _build_rows(db, run, windows)
    summary = {
        "schema_version": "pit-portfolio-window-audit-v1", "run_id": str(run_id),
        "methodology_version": run.methodology_version, "windows": [
            {"start": start.isoformat(), "end": end.isoformat()} for start, end in windows
        ],
        "row_count": len(rows),
        "primary_attribution_counts": {
            name: sum(row["primary_attribution"] == name for row in rows) for name in ATTRIBUTIONS
        },
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    temporary.mkdir()
    try:
        (temporary / "summary.json").write_text(_json(summary) + "\n", encoding="utf-8")
        fieldnames = list(rows[0])
        with (temporary / "weekly_attribution.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        with (temporary / "decision_details.jsonl").open("w", encoding="utf-8") as handle:
            for item in details:
                handle.write(_json(item) + "\n")
        if not all((temporary / name).is_file() and (temporary / name).stat().st_size > 0 for name in (
            "summary.json", "weekly_attribution.csv", "decision_details.jsonl",
        )):
            raise RuntimeError("artifact validation failed")
        temporary.replace(destination)
    except Exception:
        if temporary.exists() and temporary.parent == destination.parent and temporary.name.startswith(f".{destination.name}.tmp-"):
            shutil.rmtree(temporary)
        raise
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True, type=uuid.UUID)
    parser.add_argument("--window", action="append", type=_window)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    windows = list(args.window or DEFAULT_WINDOWS)
    destination = args.output_dir or Path("results/pit-portfolio-window-audit") / str(args.run_id)
    db = _ensure_session_factory()()
    try:
        summary = publish_audit(db, run_id=args.run_id, windows=windows, destination=destination)
        print(_json(summary))
        return 0
    except Exception as exc:
        print(f"audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
