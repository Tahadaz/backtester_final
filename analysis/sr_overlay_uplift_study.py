#!/usr/bin/env python3
"""Live universe study for validated S/R overlay added value.

The study uses stored ``signal_best_evidence_snapshot`` rows only to identify
the universe to study. It recomputes the signal evidence payload in-process and
reads the S/R decision, validation reason codes, and proof-window uplift from
the freshly computed overlay, so stale pre-gate snapshots cannot mask results.

Usage:
    python analysis/sr_overlay_uplift_study.py
    python analysis/sr_overlay_uplift_study.py --horizon weekly --variant expanded_ta_simple
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException

from services.api.app import models
from services.api.app.db import _ensure_session_factory
from services.api.app.routers.strategy_signals._evidence import _build_signal_evidence_payload


def _float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if out == out else None


def _median(values: list[float]) -> str:
    return "n/a" if not values else f"{statistics.median(values):.4f}"


def _pct(count: int, total: int) -> str:
    return "n/a" if total <= 0 else f"{100.0 * count / total:.1f}%"


def _universe_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    SessionLocal = _ensure_session_factory()
    with SessionLocal() as db:
        query = db.query(models.SignalBestEvidenceSnapshot).filter(
            models.SignalBestEvidenceSnapshot.status == "succeeded",
        )
        if args.horizon:
            query = query.filter(models.SignalBestEvidenceSnapshot.horizon == args.horizon)
        if args.variant:
            query = query.filter(models.SignalBestEvidenceSnapshot.variant == args.variant)
        return [
            {
                "symbol": row.symbol,
                "horizon": row.horizon,
                "variant": row.variant,
                "cooldown_bars": int(row.cooldown_bars or 0),
                "side_policy": row.side_policy,
            }
            for row in query.order_by(models.SignalBestEvidenceSnapshot.horizon, models.SignalBestEvidenceSnapshot.symbol).all()
        ]


def _fresh_overlay_record(row: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    SessionLocal = _ensure_session_factory()
    with SessionLocal() as db:
        try:
            payload = _build_signal_evidence_payload(
                db,
                symbol=str(row.get("symbol") or ""),
                horizon=str(row.get("horizon") or ""),
                source="wfo",
                variant=str(row.get("variant") or "") or None,
                cooldown_bars=int(row.get("cooldown_bars") or 0),
                proof_limit="100",
                include_sr_overlay=True,
            )
        except HTTPException as exc:
            return _unavailable_record(row, f"http_{exc.status_code}", str(exc.detail), started)
        except Exception as exc:
            return _unavailable_record(row, "live_recompute_error", f"{type(exc).__name__}: {exc}", started)

    overlay = payload.get("sr_overlay") if isinstance(payload.get("sr_overlay"), dict) else {}
    stitched = payload.get("stitched_oos_backtest") if isinstance(payload.get("stitched_oos_backtest"), dict) else {}
    if not overlay and isinstance(stitched.get("sr_overlay"), dict):
        overlay = stitched["sr_overlay"]
    validation = overlay.get("validation") if isinstance(overlay.get("validation"), dict) else {}
    proof = validation.get("proof") if isinstance(validation.get("proof"), dict) else {}
    proof_uplift = proof.get("uplift") if isinstance(proof.get("uplift"), dict) else {}
    reason_codes = [str(code) for code in (validation.get("reason_codes") or [])]
    decision = str(overlay.get("decision") or validation.get("decision") or overlay.get("status") or "unavailable")
    reason = str(overlay.get("reason") or validation.get("reason") or "")
    if decision == "unavailable" and not reason_codes:
        reason_codes = [reason or "unavailable"]

    return {
        "symbol": row.get("symbol"),
        "horizon": row.get("horizon"),
        "variant": row.get("variant"),
        "decision": decision,
        "reason": reason,
        "reason_codes": reason_codes,
        "tested": int(overlay.get("tested_count") or 0),
        "viable": int(overlay.get("viable_count") or 0),
        "invalid_pairs": int(overlay.get("invalid_pair_count") or 0),
        "unavailable_pairs": int(overlay.get("unavailable_count") or 0),
        "proof_uplift": _float(proof_uplift.get("total_return")),
        "proof_pvalue": _float(proof.get("mean_uplift_pvalue")),
        "best_variant_id": overlay.get("best_variant_id"),
        "source": "live_recompute",
        "baseline_source": "live_evidence_rebuild",
        "elapsed_s": time.perf_counter() - started,
    }


def _unavailable_record(
    row: dict[str, Any],
    reason: str,
    detail: str,
    started: float,
) -> dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "horizon": row.get("horizon"),
        "variant": row.get("variant"),
        "decision": "unavailable",
        "reason": reason,
        "reason_codes": [reason],
        "tested": 0,
        "viable": 0,
        "invalid_pairs": 0,
        "unavailable_pairs": 0,
        "proof_uplift": None,
        "proof_pvalue": None,
        "best_variant_id": None,
        "source": "live_recompute_error",
        "detail": detail,
        "elapsed_s": time.perf_counter() - started,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", choices=["weekly", "monthly", "quarterly"], default=None)
    parser.add_argument("--variant", default=None)
    parser.add_argument("--limit", type=int, default=20, help="top rows to print")
    parser.add_argument("--workers", type=int, default=8, help="parallel live recompute workers")
    parser.add_argument(
        "--output-jsonl",
        default="analysis/sr_overlay_uplift_study_live_evidence_results.jsonl",
        help="incremental result cache for long live recomputes",
    )
    parser.add_argument("--no-resume", action="store_true", help="ignore existing JSONL cache")
    parser.add_argument("--max-rows", type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    rows = _universe_rows(args)
    if args.max_rows is not None:
        rows = rows[: max(0, int(args.max_rows))]

    output_path = Path(args.output_jsonl)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    done_keys: set[tuple[str, str, str]] = set()
    if output_path.exists() and not args.no_resume:
        for line in output_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (str(record.get("symbol") or ""), str(record.get("horizon") or ""), str(record.get("variant") or ""))
            records.append(record)
            done_keys.add(key)
    if args.no_resume and output_path.exists():
        output_path.unlink()

    pending_rows = [
        row
        for row in rows
        if (str(row.get("symbol") or ""), str(row.get("horizon") or ""), str(row.get("variant") or "")) not in done_keys
    ]
    workers = max(1, int(args.workers or 1))
    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_by_row = {executor.submit(_fresh_overlay_record, row): row for row in pending_rows}
        for idx, future in enumerate(as_completed(future_by_row), start=1):
            row = future_by_row[future]
            print(
                f"[{len(done_keys) + idx}/{len(rows)}] recomputed {row.get('symbol')} {row.get('horizon')} {row.get('variant')}",
                file=sys.stderr,
                flush=True,
            )
            record = future.result()
            records.append(record)
            with output_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")

    total = len(records)
    decisions = Counter(r["decision"] for r in records)
    reasons = Counter(code for r in records for code in r["reason_codes"])
    unavailable_reasons = Counter(
        (r["reason"] or (r["reason_codes"][0] if r["reason_codes"] else "unavailable"))
        for r in records
        if r["decision"] == "unavailable"
    )
    proof_uplifts = [v for r in records if (v := r["proof_uplift"]) is not None]
    pvalues = [v for r in records if (v := r["proof_pvalue"]) is not None]

    print("=" * 88)
    print("S/R OVERLAY UPLIFT STUDY")
    print("=" * 88)
    print("mode: live evidence recompute (snapshot rows provide universe only)")
    print(f"rows: {total}")
    for key in ("actionable", "research_only", "unavailable"):
        print(f"{key:<14} {decisions.get(key, 0):>5}  {_pct(decisions.get(key, 0), total)}")
    print(f"median proof total-return uplift: {_median(proof_uplifts)}")
    print(f"median proof p-value:             {_median(pvalues)}")
    print()
    print("Top failure gates:")
    for code, count in reasons.most_common(10):
        print(f"  {code:<24} {count:>5}  {_pct(count, total)}")
    print()
    print("Unavailable reasons:")
    for reason, count in unavailable_reasons.most_common(10):
        print(f"  {reason:<24} {count:>5}  {_pct(count, total)}")
    print()
    print("Top actionable/research rows:")
    ranked = sorted(
        records,
        key=lambda r: (
            0 if r["decision"] == "actionable" else 1 if r["decision"] == "research_only" else 2,
            -float(r["proof_uplift"] if r["proof_uplift"] is not None else -999.0),
            r["horizon"],
            r["symbol"],
        ),
    )
    for row in ranked[: max(1, int(args.limit))]:
        print(
            f"{row['decision']:<13} {row['symbol']:<8} {row['horizon']:<9} "
            f"uplift={row['proof_uplift']} p={row['proof_pvalue']} "
            f"tested={row['tested']} viable={row['viable']} {row['best_variant_id'] or ''}"
        )


if __name__ == "__main__":
    main()
