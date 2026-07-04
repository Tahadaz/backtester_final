"""Fundamentals-layer validation gate (brief 54 Phase 5).

One rerunnable command answering "is the fundamentals layer still healthy
after this engine change?" It bundles three existing checks and reduces
them to a single PASS/FAIL verdict + exit code:

  1. Coverage audit    -> services/api/scripts/audit_fundamental_coverage.py
  2. BKGR validation    -> services/api/scripts/validate_vs_bkgr.py
  3. IC-weight provenance -> core/quant_core/fundamentals/ic_ensemble_weights.json

Each check's internal functions are imported and re-run directly (not
shelled out) so the gate shares exactly the same DB queries and audit
logic as the standalone scripts -- no drift between "the audit" and "the
gate that reads the audit".

Usage:
  python services/api/scripts/validation_gate.py [--json out.json]
  python services/api/scripts/validation_gate.py --allow-unverified AFM XYZ

Exit code: 0 on PASS (including PASS-with-WARN), 1 on FAIL.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.api.app.services import fundamentals as fundamental_service  # noqa: E402
from services.api.scripts import audit_fundamental_coverage as coverage_mod  # noqa: E402
from services.api.scripts import validate_vs_bkgr as bkgr_mod  # noqa: E402

DEFAULT_DB_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"
DEFAULT_ALLOW_UNVERIFIED = ["AFM"]
DEFAULT_MIN_OVERLAP = 30
DEFAULT_WEIGHTS_PATH = ROOT / "core" / "quant_core" / "fundamentals" / "ic_ensemble_weights.json"
WEIGHTS_WATCH_FILES = (
    ROOT / "core" / "quant_core" / "fundamentals" / "valuation.py",
    ROOT / "core" / "quant_core" / "fundamentals" / "projection.py",
    ROOT / "core" / "quant_core" / "fundamentals" / "pit_ic_backtest.py",
)
DOC55_VERDICT = (
    "ddm structural zero; residual_income watch-list (re-estimate after >=2 FY of real "
    "consensus history); fcff_dcf seeding validated."
)
COVERAGE_BAD_STATES = ("NO_ENSEMBLE", "NO_FUNDAMENTALS", "NR_NO_MODELS")

STATUS_RANK = {"PASS": 0, "WARN": 1, "FAIL": 2}


@dataclass
class Gate:
    name: str
    status: str  # PASS | FAIL | WARN
    detail: str


@dataclass
class CheckResult:
    check: str
    status: str
    gates: list[Gate] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


def _combine(statuses: list[str]) -> str:
    if not statuses:
        return "PASS"
    return max(statuses, key=lambda s: STATUS_RANK.get(s, 0))


# ---------------------------------------------------------------------------
# Check 1: coverage audit
# ---------------------------------------------------------------------------

def run_coverage_check(database_url: str, scenario: str, allow_unverified: list[str]) -> CheckResult:
    allow_set = {s.upper() for s in allow_unverified}
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with engine.connect() as con:
        stocks = coverage_mod._active_masi_equities(con)
    symbols = [str(s["symbol"]).upper() for s in stocks]

    with SessionLocal() as db:
        snapshots = fundamental_service.latest_snapshot_rows_by_symbol(db, symbols=symbols, scope="all")
    snapshots = {sym.upper(): row for sym, row in snapshots.items()}
    import_ids = sorted({str(row.import_id) for row in snapshots.values()})

    with engine.connect() as con:
        ensembles = coverage_mod._ensembles(con, import_ids, scenario)
        valuations = coverage_mod._valuations(con, import_ids, scenario)
        verifications = coverage_mod._verifications(con, import_ids)
        sources = coverage_mod._import_sources(con, import_ids)

    audits = [
        coverage_mod._audit_symbol(
            stock, snapshots.get(str(stock["symbol"]).upper()), ensembles, valuations, verifications, sources
        )
        for stock in stocks
    ]

    states: dict[str, int] = {}
    weight_modes: dict[str, int] = {}
    for a in audits:
        states[a.state] = states.get(a.state, 0) + 1
        if a.weight_mode:
            weight_modes[a.weight_mode] = weight_modes.get(a.weight_mode, 0) + 1

    bad_symbols = sorted(a.symbol for a in audits if a.state in COVERAGE_BAD_STATES)
    nr_unverified = sorted(a.symbol for a in audits if a.state == "NR_UNVERIFIED")
    nr_unverified_not_whitelisted = sorted(s for s in nr_unverified if s not in allow_set)

    gates = [
        Gate(
            name="no_ensemble_or_no_fundamentals_or_nr_no_models",
            status="FAIL" if bad_symbols else "PASS",
            detail=(f"{len(bad_symbols)} symbol(s): {', '.join(bad_symbols)}" if bad_symbols else "none"),
        ),
        Gate(
            name="nr_unverified_whitelist",
            status="FAIL" if nr_unverified_not_whitelisted else "PASS",
            detail=(
                f"{len(nr_unverified_not_whitelisted)} unwhitelisted symbol(s): "
                f"{', '.join(nr_unverified_not_whitelisted)}"
                if nr_unverified_not_whitelisted
                else f"NR_UNVERIFIED={nr_unverified or '[]'} all in allow-list {sorted(allow_set)}"
            ),
        ),
    ]
    status = _combine([g.status for g in gates])

    return CheckResult(
        check="coverage_audit",
        status=status,
        gates=gates,
        context={
            "universe": len(audits),
            "states": states,
            "weight_modes": weight_modes,
            "allow_unverified": sorted(allow_set),
            "nr_unverified_symbols": nr_unverified,
            "audits": [asdict(a) for a in audits],
        },
    )


# ---------------------------------------------------------------------------
# Check 2: BKGR broker validation
# ---------------------------------------------------------------------------

def run_bkgr_check(database_url: str, scenario: str, fixture_path: Path, min_overlap: int) -> CheckResult:
    fixture = bkgr_mod._load_fixture(fixture_path)
    ensembles = bkgr_mod._latest_ensembles(database_url, [row.ticker for row in fixture], scenario)
    rows = bkgr_mod._validation_rows(fixture, ensembles)
    metrics = bkgr_mod._metrics(rows)

    floor_count = int(metrics["floor_count"])
    tail_count = int(metrics["tail_count"])
    overlap_count = int(metrics["overlap_count"])

    gates = [
        Gate(
            name="floor_count_zero",
            status="FAIL" if floor_count > 0 else "PASS",
            detail=f"floor_count={floor_count} tickers={metrics['floor_tickers'] or '[]'}",
        ),
        Gate(
            name="tail_count_zero",
            status="FAIL" if tail_count > 0 else "PASS",
            detail=f"tail_count={tail_count} tickers={metrics['tail_tickers'] or '[]'}",
        ),
        Gate(
            name=f"overlap_count_ge_{min_overlap}",
            status="FAIL" if overlap_count < min_overlap else "PASS",
            detail=f"overlap_count={overlap_count} (min={min_overlap})",
        ),
    ]
    status = _combine([g.status for g in gates])

    return CheckResult(
        check="bkgr_validation",
        status=status,
        gates=gates,
        context={
            "fixture_count": metrics["fixture_count"],
            "overlap_count": overlap_count,
            "quorum_count": metrics["quorum_count"],
            "floor_count": floor_count,
            "tail_count": tail_count,
            # Context metrics only (brief 48: BKGR is a sanity reference, not a target) -- reported, not gated.
            "mean_diff_vs_bkgr_pct": metrics["mean_diff_vs_bkgr_pct"],
            "spearman": metrics["spearman"],
            "directional_agreement": metrics["directional_agreement"],
        },
    )


# ---------------------------------------------------------------------------
# Check 3: IC-weight provenance
# ---------------------------------------------------------------------------

def run_ic_provenance_check(weights_path: Path, watch_files: tuple[Path, ...]) -> CheckResult:
    if not weights_path.exists():
        gate = Gate(name="weights_file_present", status="FAIL", detail=f"missing: {weights_path}")
        return CheckResult(check="ic_weight_provenance", status="FAIL", gates=[gate], context={"weights_path": str(weights_path)})

    try:
        raw = weights_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        gate = Gate(name="weights_file_parsable", status="FAIL", detail=f"{type(exc).__name__}: {exc}")
        return CheckResult(check="ic_weight_provenance", status="FAIL", gates=[gate], context={"weights_path": str(weights_path)})

    gates = [Gate(name="weights_file_present_and_parsable", status="PASS", detail=str(weights_path))]

    weights = {k: float(v) for k, v in (data.get("weights") or {}).items()}
    raw_ic = {k: float(v) for k, v in (data.get("raw_ic") or {}).items()}
    estimated_date = data.get("estimated_date")
    source = data.get("source")

    weights_mtime = weights_path.stat().st_mtime
    stale_sources = []
    for f in watch_files:
        if f.exists() and f.stat().st_mtime > weights_mtime:
            stale_sources.append(
                {
                    "file": str(f.relative_to(ROOT)).replace("\\", "/"),
                    "mtime": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
                }
            )

    weights_mtime_iso = datetime.fromtimestamp(weights_mtime, tz=timezone.utc).isoformat()
    if stale_sources:
        names = ", ".join(s["file"] for s in stale_sources)
        gates.append(
            Gate(
                name="weights_not_stale_vs_model_sources",
                status="WARN",
                detail=(
                    f"weights file dated {estimated_date} (mtime {weights_mtime_iso}) is older than: {names} "
                    "-- re-examine weights per doc 55."
                ),
            )
        )
    else:
        gates.append(
            Gate(
                name="weights_not_stale_vs_model_sources",
                status="PASS",
                detail=f"weights file (mtime {weights_mtime_iso}) is newer than all watched model sources",
            )
        )

    status = _combine([g.status for g in gates])

    return CheckResult(
        check="ic_weight_provenance",
        status=status,
        gates=gates,
        context={
            "weights_path": str(weights_path),
            "estimated_date": estimated_date,
            "source": source,
            "weights": weights,
            "raw_ic": raw_ic,
            "stale_sources": stale_sources,
            "doc55_verdict": DOC55_VERDICT,
        },
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_gate(gate: Gate) -> None:
    print(f"  [{gate.status:4s}] {gate.name} -- {gate.detail}")


def _print_report(results: list[CheckResult], overall: str) -> None:
    print("=" * 72)
    print("FUNDAMENTALS LAYER VALIDATION GATE  (brief 54 Phase 5)")
    print("=" * 72)

    for r in results:
        print()
        print(f"-- {r.check} : {r.status} --")
        if r.check == "coverage_audit":
            ctx = r.context
            print(f"  universe={ctx['universe']}")
            print("  states: " + " ".join(f"{k}={v}" for k, v in sorted(ctx["states"].items())))
            print("  weight_modes: " + " ".join(f"{k}={v}" for k, v in sorted(ctx["weight_modes"].items())))
            print(f"  allow_unverified={ctx['allow_unverified']}  nr_unverified_symbols={ctx['nr_unverified_symbols']}")
        elif r.check == "bkgr_validation":
            ctx = r.context
            print(
                f"  fixture_count={ctx['fixture_count']} overlap_count={ctx['overlap_count']} "
                f"quorum_count={ctx['quorum_count']} floor_count={ctx['floor_count']} tail_count={ctx['tail_count']}"
            )
            mdb = ctx["mean_diff_vs_bkgr_pct"]
            sp = ctx["spearman"]
            da = ctx["directional_agreement"]
            print(
                "  context (reported, not gated): "
                f"mean_diff_vs_bkgr_pct={mdb:.2f} spearman={sp:.4f} directional_agreement={da:.4f}"
                if mdb is not None and sp is not None and da is not None
                else f"  context (reported, not gated): mean_diff_vs_bkgr_pct={mdb} spearman={sp} directional_agreement={da}"
            )
        elif r.check == "ic_weight_provenance":
            ctx = r.context
            print(f"  weights_path={ctx['weights_path']}")
            if ctx.get("estimated_date"):
                print(f"  estimated_date={ctx['estimated_date']}  source={ctx.get('source')}")
                print("  weights: " + " ".join(f"{k}={v:.4f}" for k, v in sorted(ctx["weights"].items())))
            print(f"  doc-55 verdict: {ctx.get('doc55_verdict')}")
        for gate in r.gates:
            _print_gate(gate)

    print()
    print("=" * 72)
    print(f"VALIDATION GATE: {overall}")
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rerunnable PASS/FAIL health gate for the fundamentals layer.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", DEFAULT_DB_URL))
    parser.add_argument("--scenario", default="base")
    parser.add_argument(
        "--allow-unverified",
        nargs="*",
        default=DEFAULT_ALLOW_UNVERIFIED,
        help=f"Symbols allowed to be NR_UNVERIFIED without failing the gate (default: {DEFAULT_ALLOW_UNVERIFIED}).",
    )
    parser.add_argument("--bkgr-fixture", type=Path, default=bkgr_mod.DEFAULT_FIXTURE)
    parser.add_argument("--min-overlap", type=int, default=DEFAULT_MIN_OVERLAP)
    parser.add_argument("--weights-path", type=Path, default=DEFAULT_WEIGHTS_PATH)
    parser.add_argument("--json", type=Path, default=None, help="Also write the full structured result to this JSON file.")
    args = parser.parse_args()

    results = [
        run_coverage_check(args.database_url, args.scenario, args.allow_unverified),
        run_bkgr_check(args.database_url, args.scenario, args.bkgr_fixture, args.min_overlap),
        run_ic_provenance_check(args.weights_path, WEIGHTS_WATCH_FILES),
    ]
    overall = _combine([r.status for r in results])
    overall_gate = "FAIL" if overall == "FAIL" else "PASS"

    _print_report(results, overall_gate)

    if args.json:
        payload = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "database_url": args.database_url,
            "scenario": args.scenario,
            "overall_status": overall,
            "overall_gate": overall_gate,
            "checks": [
                {
                    "check": r.check,
                    "status": r.status,
                    "gates": [asdict(g) for g in r.gates],
                    "context": r.context,
                }
                for r in results
            ],
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        print(f"\nJSON written to {args.json}")

    return 1 if overall_gate == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
