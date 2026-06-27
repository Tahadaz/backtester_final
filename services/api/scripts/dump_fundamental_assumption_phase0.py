"""Phase 0 inventory for the fundamentals assumption refactor.

This script is intentionally read-only against the application database.  It
captures the current resolved assumption/provenance stack for every symbol and
an in-memory Managem valuation baseline using the same calculation path as the
valuation recompute service, without persisting replacement valuation rows.

Usage:
    ./.venv/Scripts/python.exe services/api/scripts/dump_fundamental_assumption_phase0.py
    ./.venv/Scripts/python.exe services/api/scripts/dump_fundamental_assumption_phase0.py --symbol MNG
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from app import models  # noqa: E402
from app.db import _ensure_session_factory  # noqa: E402
from app.json_sanitize import sanitize_json_compatible  # noqa: E402
from app.services.fundamentals import (  # noqa: E402
    _apply_live_cost_of_capital,
    _integrity_with_projection,
    _load_history,
    _scope_for_symbols,
    _snapshot_from_model,
    _stock_sectors,
    active_assumptions_for,
    enriched_snapshots_by_symbol,
    latest_integrity_report,
    latest_snapshot_rows_by_symbol,
    resolved_assumptions_with_provenance,
    source_integrity_report_for_history,
)
from core.quant_core.fundamentals.projection import build_projection  # noqa: E402
from core.quant_core.fundamentals.valuation import (  # noqa: E402
    DEFAULT_ASSUMPTIONS,
    compute_symbol_valuations,
    compute_valuation_ensemble,
)


DEFAULT_OUT_DIR = REPO_ROOT / "research-out" / "fundamentals_assumptions_phase0"
ECONOMIC_ASSUMPTION_KEYS = {
    "beta",
    "cost_of_debt",
    "cost_of_equity",
    "country_risk_premium",
    "default_debt_weight",
    "default_equity_weight",
    "equity_risk_premium",
    "growth_cap",
    "risk_free_rate",
    "stable_payout_ratio",
    "tax_rate",
    "terminal_growth",
    "terminal_growth_equity",
    "terminal_growth_firm",
    "wacc",
}
STATIC_ROW_PROVENANCE = {"scenario", "symbol"}
VALUATION_MODEL_ORDER = (
    "ddm",
    "residual_income",
    "fcff_dcf",
    "fcfe_dcf",
    "justified_multiples",
    "relative_multiples",
    "reverse_dcf",
)


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def _json_write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(sanitize_json_compatible(payload), indent=2, sort_keys=True), encoding="utf-8")


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _assumption_entries(assumptions: dict[str, Any], provenance: dict[str, str]) -> dict[str, dict[str, Any]]:
    keys = sorted(set(assumptions) | set(provenance))
    return {
        key: {
            "value": assumptions.get(key),
            "provenance": provenance.get(key),
        }
        for key in keys
        if not key.startswith("_")
    }


def build_inventory(db: Session, *, scenario: str, symbols: list[str] | None = None) -> dict[str, Any]:
    snapshot_rows = latest_snapshot_rows_by_symbol(db, symbols=symbols)
    inventory_symbols = sorted(snapshot_rows)
    sectors = _stock_sectors(db, inventory_symbols)
    provenance_counts: Counter[str] = Counter()
    key_provenance_counts: dict[str, Counter[str]] = {}
    static_economic_hits: list[dict[str, Any]] = []
    per_symbol: dict[str, Any] = {}

    for symbol in inventory_symbols:
        assumptions, provenance = resolved_assumptions_with_provenance(
            db,
            symbol=symbol,
            sector=sectors.get(symbol),
            scenario=scenario,
        )
        entries = _assumption_entries(assumptions, provenance)
        for key, item in entries.items():
            source = str(item.get("provenance") or "missing")
            provenance_counts[source] += 1
            key_provenance_counts.setdefault(key, Counter())[source] += 1
            if key in ECONOMIC_ASSUMPTION_KEYS and source in STATIC_ROW_PROVENANCE:
                static_economic_hits.append(
                    {
                        "symbol": symbol,
                        "sector": sectors.get(symbol),
                        "key": key,
                        "value": item.get("value"),
                        "provenance": source,
                    }
                )
        per_symbol[symbol] = {
            "sector": sectors.get(symbol),
            "import_id": str(snapshot_rows[symbol].import_id),
            "company_name": snapshot_rows[symbol].company_name,
            "latest_statement_year": snapshot_rows[symbol].latest_statement_year,
            "assumptions": entries,
        }

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "scenario": scenario,
        "symbol_count": len(inventory_symbols),
        "economic_assumption_keys": sorted(ECONOMIC_ASSUMPTION_KEYS),
        "static_row_provenance": sorted(STATIC_ROW_PROVENANCE),
        "provenance_counts": dict(sorted(provenance_counts.items())),
        "key_provenance_counts": {
            key: dict(sorted(counter.items())) for key, counter in sorted(key_provenance_counts.items())
        },
        "static_economic_hit_count": len(static_economic_hits),
        "static_economic_hits": static_economic_hits,
        "symbols": per_symbol,
    }


def build_managem_baseline(db: Session, *, symbol: str, scenario: str) -> dict[str, Any]:
    symbol = symbol.upper()
    current_rows = latest_snapshot_rows_by_symbol(db, symbols=[symbol])
    snapshot_row = current_rows.get(symbol)
    if snapshot_row is None:
        raise RuntimeError(f"No latest fundamental snapshot found for {symbol}")

    scope = _scope_for_symbols(db, [symbol])
    latest_rows = latest_snapshot_rows_by_symbol(db, scope=scope)
    current_snapshot = latest_rows.get(symbol)
    is_current_snapshot = current_snapshot is not None and current_snapshot.import_id == snapshot_row.import_id
    latest_rows[symbol] = snapshot_row
    enriched = enriched_snapshots_by_symbol(db, latest_rows)
    peer_snapshots = list(enriched.values())
    target_snapshot = enriched.get(symbol) or _snapshot_from_model(snapshot_row)
    history = _load_history(db, snapshot_row.import_id, symbol)
    sectors = _stock_sectors(db, [row.symbol for row in peer_snapshots])

    resolved, provenance = resolved_assumptions_with_provenance(
        db,
        symbol=symbol,
        sector=sectors.get(symbol),
        scenario=scenario,
    )
    assumptions = active_assumptions_for(
        db,
        symbol=symbol,
        sector=sectors.get(symbol),
        scenario=scenario,
    )
    assumptions, _ = _apply_live_cost_of_capital(
        db,
        symbol=symbol,
        assumptions=assumptions,
        sector=sectors.get(symbol),
        scenario=scenario,
        snapshot_row=snapshot_row,
        snapshot=target_snapshot,
        history=history,
        use_snapshot_beta_as_of=not is_current_snapshot,
    )
    integrity = latest_integrity_report(
        db,
        import_id=snapshot_row.import_id,
        symbol=symbol,
        statement_year=target_snapshot.latest_statement_year,
    )
    integrity = source_integrity_report_for_history(
        integrity,
        history=history,
        symbol=symbol,
        statement_year=target_snapshot.latest_statement_year,
    )
    projection = build_projection(target_snapshot, history, assumptions, scenario=scenario)
    assumptions_with_projection = {**assumptions, "_projection": projection}
    integrity = _integrity_with_projection(
        report=integrity,
        projection=projection,
        symbol=symbol,
        statement_year=target_snapshot.latest_statement_year,
    )
    eligibility, valuations = compute_symbol_valuations(
        snapshot=target_snapshot,
        history=history,
        peer_snapshots=peer_snapshots,
        sectors=sectors,
        assumptions=assumptions_with_projection,
        scenario=scenario,
        integrity=integrity,
    )
    ensemble = compute_valuation_ensemble(symbol, scenario, valuations)
    valuations_by_model = {row.model: row for row in valuations}
    persisted_rows = (
        db.query(models.FundamentalValuationResult)
        .filter(
            models.FundamentalValuationResult.import_id == snapshot_row.import_id,
            models.FundamentalValuationResult.symbol == symbol,
            models.FundamentalValuationResult.scenario == scenario,
        )
        .order_by(models.FundamentalValuationResult.model.asc())
        .all()
    )

    first_projection = projection.statements[0] if projection.statements else {}
    model_rows = []
    for model in VALUATION_MODEL_ORDER:
        row = valuations_by_model.get(model)
        if row is None:
            continue
        model_rows.append(
            {
                "model": row.model,
                "fair_value": row.fair_value,
                "current_price": row.current_price,
                "upside_pct": row.upside_pct,
                "confidence": row.confidence,
                "confidence_score": row.confidence_score,
                "weight": row.weight,
                "family": row.family,
                "warnings": list(row.warnings),
                "inputs": row.inputs,
            }
        )

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "symbol": symbol,
        "company_name": target_snapshot.company_name,
        "sector": sectors.get(symbol),
        "scenario": scenario,
        "import_id": str(snapshot_row.import_id),
        "latest_statement_year": target_snapshot.latest_statement_year,
        "current_price": target_snapshot.metrics.get("Current_Price"),
        "engine": "in_memory_recompute_path",
        "resolved_terminal_growth": {
            "terminal_growth": resolved.get("terminal_growth"),
            "terminal_growth_provenance": provenance.get("terminal_growth"),
            "terminal_growth_firm": assumptions.get("terminal_growth_firm"),
            "terminal_growth_firm_provenance": provenance.get("terminal_growth_firm"),
            "terminal_growth_equity": assumptions.get("terminal_growth_equity"),
            "terminal_growth_equity_provenance": provenance.get("terminal_growth_equity"),
            "terminal_growth_basis": assumptions.get("terminal_growth_basis"),
        },
        "year1_revenue_growth": first_projection.get("revenue_growth"),
        "year1_revenue": first_projection.get("revenue"),
        "projection_growth_driver": projection.drivers.get("revenue_growth").to_dict()
        if projection.drivers.get("revenue_growth")
        else None,
        "projection_warnings": list(projection.warnings),
        "model_eligibility": eligibility,
        "valuations": model_rows,
        "ensemble": {
            "fair_value_low": ensemble.fair_value_low,
            "fair_value_base": ensemble.fair_value_base,
            "fair_value_high": ensemble.fair_value_high,
            "fair_value_mean": ensemble.fair_value_mean,
            "current_price": ensemble.current_price,
            "upside_pct": ensemble.upside_pct,
            "confidence_score": ensemble.confidence_score,
            "usable_model_count": ensemble.usable_model_count,
            "excluded_model_count": ensemble.excluded_model_count,
            "warnings": list(ensemble.warnings),
            "model_weights": dict(ensemble.model_weights),
        },
        "persisted_valuation_rows": [
            {
                "model": row.model,
                "fair_value": row.fair_value,
                "current_price": row.current_price,
                "upside_pct": row.upside_pct,
                "confidence": row.confidence,
                "computed_at": row.computed_at,
            }
            for row in persisted_rows
        ],
    }


def write_inventory_csv(path: Path, inventory: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "sector", "key", "value", "provenance"])
        writer.writeheader()
        for symbol, payload in sorted(inventory["symbols"].items()):
            for key, item in sorted(payload["assumptions"].items()):
                writer.writerow(
                    {
                        "symbol": symbol,
                        "sector": payload.get("sector"),
                        "key": key,
                        "value": json.dumps(sanitize_json_compatible(item.get("value")), sort_keys=True)
                        if isinstance(item.get("value"), (dict, list))
                        else item.get("value"),
                        "provenance": item.get("provenance"),
                    }
                )


def write_managem_markdown(path: Path, baseline: dict[str, Any]) -> None:
    lines = [
        "# Phase 0 Managem Baseline",
        "",
        f"- Generated at: `{baseline['generated_at']}`",
        f"- Git commit: `{baseline.get('git_commit') or '-'}`",
        f"- Symbol: `{baseline['symbol']}` ({baseline.get('company_name') or '-'})",
        f"- Scenario: `{baseline['scenario']}`",
        f"- Engine: `{baseline['engine']}`",
        f"- Import ID: `{baseline['import_id']}`",
        f"- Current price: `{_fmt(baseline.get('current_price'))}`",
        "",
        "## Key Assumptions",
        "",
        "| Field | Value | Provenance |",
        "|---|---:|---|",
    ]
    tg = baseline["resolved_terminal_growth"]
    for field, provenance_field in (
        ("terminal_growth", "terminal_growth_provenance"),
        ("terminal_growth_firm", "terminal_growth_firm_provenance"),
        ("terminal_growth_equity", "terminal_growth_equity_provenance"),
    ):
        lines.append(f"| `{field}` | `{_fmt(tg.get(field))}` | `{tg.get(provenance_field) or '-'}` |")
    lines.extend(
        [
            f"| `year1_revenue_growth` | `{_fmt(baseline.get('year1_revenue_growth'))}` | `projection` |",
            "",
            "## Per-Model Fair Values",
            "",
            "| Model | Fair value | Current price | Upside | Confidence |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for row in baseline["valuations"]:
        lines.append(
            "| "
            f"`{row['model']}` | "
            f"`{_fmt(row.get('fair_value'))}` | "
            f"`{_fmt(row.get('current_price'))}` | "
            f"`{_fmt(row.get('upside_pct'))}` | "
            f"`{row.get('confidence') or '-'}` |"
        )
    ensemble = baseline["ensemble"]
    lines.extend(
        [
            "",
            "## Ensemble",
            "",
            "| Low | Base | High | Mean | Usable models | Confidence |",
            "|---:|---:|---:|---:|---:|---:|",
            "| "
            f"`{_fmt(ensemble.get('fair_value_low'))}` | "
            f"`{_fmt(ensemble.get('fair_value_base'))}` | "
            f"`{_fmt(ensemble.get('fair_value_high'))}` | "
            f"`{_fmt(ensemble.get('fair_value_mean'))}` | "
            f"`{ensemble.get('usable_model_count')}` | "
            f"`{_fmt(ensemble.get('confidence_score'))}` |",
            "",
            "## Revenue Growth Driver",
            "",
            "```json",
            json.dumps(
                sanitize_json_compatible(baseline.get("projection_growth_driver")),
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_summary(path: Path, *, inventory: dict[str, Any], baseline: dict[str, Any]) -> None:
    lines = [
        "# Phase 0 Assumption Inventory Summary",
        "",
        f"- Generated at: `{inventory['generated_at']}`",
        f"- Scenario: `{inventory['scenario']}`",
        f"- Symbols inventoried: `{inventory['symbol_count']}`",
        f"- Static economic hits: `{inventory['static_economic_hit_count']}`",
        "",
        "## Provenance Counts",
        "",
        "| Provenance | Count |",
        "|---|---:|",
    ]
    for source, count in inventory["provenance_counts"].items():
        lines.append(f"| `{source}` | `{count}` |")
    lines.extend(
        [
            "",
            "## Static Economic Hits",
            "",
            "| Symbol | Sector | Key | Value | Provenance |",
            "|---|---|---|---:|---|",
        ]
    )
    for hit in inventory["static_economic_hits"][:200]:
        lines.append(
            "| "
            f"`{hit['symbol']}` | "
            f"{hit.get('sector') or '-'} | "
            f"`{hit['key']}` | "
            f"`{_fmt(hit.get('value'))}` | "
            f"`{hit['provenance']}` |"
        )
    if len(inventory["static_economic_hits"]) > 200:
        lines.append(f"| ... | ... | ... | ... | `{len(inventory['static_economic_hits']) - 200} more` |")
    lines.extend(
        [
            "",
            "## Managem Baseline Pointer",
            "",
            f"- Fair value table: `managem_baseline.md`",
            f"- Terminal growth: `{_fmt(baseline['resolved_terminal_growth'].get('terminal_growth'))}`",
            f"- Year-1 revenue growth: `{_fmt(baseline.get('year1_revenue_growth'))}`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dump Phase 0 assumption provenance and Managem baseline.")
    parser.add_argument("--scenario", default="base", choices=["bear", "base", "bull"])
    parser.add_argument("--symbol", default="MNG", help="Baseline symbol; default MNG.")
    parser.add_argument(
        "--only",
        nargs="*",
        help="Optional list of symbols to inventory. Defaults to all latest fundamental snapshots.",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    SessionLocal = _ensure_session_factory()
    db: Session = SessionLocal()
    try:
        inventory = build_inventory(
            db,
            scenario=args.scenario,
            symbols=[symbol.upper() for symbol in args.only] if args.only else None,
        )
        baseline = build_managem_baseline(db, symbol=args.symbol, scenario=args.scenario)
        _json_write(out_dir / "assumption_inventory.json", inventory)
        _json_write(out_dir / "managem_baseline.json", baseline)
        write_inventory_csv(out_dir / "assumption_inventory.csv", inventory)
        write_managem_markdown(out_dir / "managem_baseline.md", baseline)
        write_summary(out_dir / "README.md", inventory=inventory, baseline=baseline)
    finally:
        db.rollback()
        db.close()

    print(f"Wrote Phase 0 assumption inventory to {out_dir}")
    print(f"Symbols: {inventory['symbol_count']}")
    print(f"Static economic hits: {inventory['static_economic_hit_count']}")
    print(f"{args.symbol.upper()} year-1 revenue growth: {_fmt(baseline.get('year1_revenue_growth'))}")
    print(
        f"{args.symbol.upper()} terminal_growth: "
        f"{_fmt(baseline['resolved_terminal_growth'].get('terminal_growth'))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
