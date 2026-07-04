"""Coverage/state audit for the fundamentals layer.

For every active MASI equity, report exactly one resolved state:
  - OK               ensemble published, quorum met
  - BELOW_QUORUM     ensemble published but usable_model_count < 3
  - NR_UNVERIFIED    tie-out failed -> data_unverified NR (with reason)
  - HEADLINE_REVIEW  fair value deliberately withheld by the brief-44 review gate
  - NR_NO_MODELS     verified but no usable valuation models
  - NO_ENSEMBLE      snapshot exists but no ensemble row for the latest import
  - NO_FUNDAMENTALS  no fundamental snapshot at all

Also classifies the ensemble weight mode per symbol (real IC spread vs
fallback concentration on relative_multiples) so the "7-model ensemble is
really 1 model" problem is quantified across the universe, and lists the
blocking warning for every unavailable model.

Usage:
  python services/api/scripts/audit_fundamental_coverage.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.api.app.services import fundamentals as fundamental_service  # noqa: E402

DEFAULT_DB_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"

MODEL_ORDER = (
    "fcff_dcf",
    "fcfe_dcf",
    "ddm",
    "residual_income",
    "justified_multiples",
    "relative_multiples",
    "reverse_dcf",
)
IC_FALLBACK_WARNING = "ic_weight_fallback_for_uncovered_models"
RELMULT_CONCENTRATION = 0.99


@dataclass
class SymbolAudit:
    symbol: str
    name: str | None
    sector: str | None
    state: str
    reason: str | None
    import_id: str | None
    data_source: str | None
    verification_status: str | None
    verified_years: list[int] = field(default_factory=list)
    unverified_years: list[int] = field(default_factory=list)
    fair_value_base: float | None = None
    current_price: float | None = None
    upside_pct: float | None = None
    confidence_score: float | None = None
    usable_model_count: int = 0
    weight_mode: str | None = None
    model_weights: dict[str, float] = field(default_factory=dict)
    models_available: list[str] = field(default_factory=list)
    models_blocked: dict[str, str] = field(default_factory=dict)
    ensemble_warnings: list[str] = field(default_factory=list)


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _active_masi_equities(con) -> list[dict[str, Any]]:
    rows = con.execute(
        text(
            """
            SELECT symbol, display_name, sector
            FROM stock_master
            WHERE is_active
              AND asset_type = 'equity'
              AND (market_region = 'masi' OR market_region IS NULL)
            ORDER BY symbol
            """
        )
    ).mappings()
    return [dict(row) for row in rows]


def _ensembles(con, import_ids: list[str], scenario: str) -> dict[tuple[str, str], dict[str, Any]]:
    if not import_ids:
        return {}
    rows = con.execute(
        text(
            """
            SELECT symbol, import_id::text AS import_id, fair_value_base, current_price,
                   upside_pct, confidence_score, usable_model_count, model_weights_json,
                   warnings_json, computed_at
            FROM fundamental_ensemble_result
            WHERE scenario = :scenario AND import_id::text = ANY(:import_ids)
            ORDER BY computed_at DESC NULLS LAST
            """
        ),
        {"scenario": scenario, "import_ids": import_ids},
    ).mappings()
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["symbol"]).upper(), str(row["import_id"]))
        out.setdefault(key, dict(row))
    return out


def _valuations(con, import_ids: list[str], scenario: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    if not import_ids:
        return {}
    rows = con.execute(
        text(
            """
            SELECT symbol, import_id::text AS import_id, model, fair_value, warnings_json
            FROM fundamental_valuation_result
            WHERE scenario = :scenario AND import_id::text = ANY(:import_ids)
            """
        ),
        {"scenario": scenario, "import_ids": import_ids},
    ).mappings()
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault((str(row["symbol"]).upper(), str(row["import_id"])), []).append(dict(row))
    return out


def _verifications(con, import_ids: list[str]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    if not import_ids:
        return {}
    rows = con.execute(
        text(
            """
            SELECT symbol, import_id::text AS import_id, statement_year, status, reason
            FROM fundamental_data_verification
            WHERE import_id::text = ANY(:import_ids)
            ORDER BY statement_year
            """
        ),
        {"import_ids": import_ids},
    ).mappings()
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault((str(row["symbol"]).upper(), str(row["import_id"])), []).append(dict(row))
    return out


def _import_sources(con, import_ids: list[str]) -> dict[str, str]:
    if not import_ids:
        return {}
    rows = con.execute(
        text(
            "SELECT id::text AS import_id, data_source FROM fundamental_import WHERE id::text = ANY(:import_ids)"
        ),
        {"import_ids": import_ids},
    ).mappings()
    return {str(row["import_id"]): str(row["data_source"] or "") for row in rows}


def _weight_mode(weights: dict[str, Any], warnings: list[str]) -> str:
    numeric = {k: (_num(v) or 0.0) for k, v in (weights or {}).items()}
    positive = {k: v for k, v in numeric.items() if v > 0}
    relmult = numeric.get("relative_multiples", 0.0)
    if not positive:
        return "no_weights"
    if IC_FALLBACK_WARNING in warnings:
        if relmult >= RELMULT_CONCENTRATION:
            return "ic_fallback_100pct_relative_multiples"
        return "ic_fallback_partial"
    if len(positive) == 1:
        only = next(iter(positive))
        return f"single_model_{only}"
    return "ic_spread"


def _audit_symbol(
    stock: dict[str, Any],
    snapshot_row: Any | None,
    ensembles: dict[tuple[str, str], dict[str, Any]],
    valuations: dict[tuple[str, str], list[dict[str, Any]]],
    verifications: dict[tuple[str, str], list[dict[str, Any]]],
    sources: dict[str, str],
) -> SymbolAudit:
    symbol = str(stock["symbol"]).upper()
    base = SymbolAudit(
        symbol=symbol,
        name=stock.get("display_name"),
        sector=stock.get("sector"),
        state="NO_FUNDAMENTALS",
        reason="no fundamental snapshot for symbol",
        import_id=None,
        data_source=None,
        verification_status=None,
    )
    if snapshot_row is None:
        return base
    import_id = str(snapshot_row.import_id)
    key = (symbol, import_id)
    base.import_id = import_id
    base.data_source = sources.get(import_id)

    ver_rows = verifications.get(key, [])
    base.verified_years = sorted(int(r["statement_year"]) for r in ver_rows if r["status"] == "verified")
    base.unverified_years = sorted(int(r["statement_year"]) for r in ver_rows if r["status"] == "data_unverified")
    if ver_rows:
        base.verification_status = "data_unverified" if base.unverified_years else "verified"

    for row in valuations.get(key, []):
        model = str(row["model"])
        if _num(row.get("fair_value")) is not None:
            base.models_available.append(model)
        else:
            warns = [str(w) for w in (row.get("warnings_json") or [])]
            base.models_blocked[model] = warns[0] if warns else "unavailable"
    base.models_available.sort(key=lambda m: MODEL_ORDER.index(m) if m in MODEL_ORDER else 99)

    ens = ensembles.get(key)
    if ens is None:
        base.state = "NO_ENSEMBLE"
        base.reason = "snapshot exists but no ensemble row for latest import"
        return base

    warnings = [str(w) for w in (ens.get("warnings_json") or [])]
    base.ensemble_warnings = warnings
    base.fair_value_base = _num(ens.get("fair_value_base"))
    base.current_price = _num(ens.get("current_price"))
    base.upside_pct = _num(ens.get("upside_pct"))
    base.confidence_score = _num(ens.get("confidence_score"))
    base.usable_model_count = int(ens.get("usable_model_count") or 0)
    base.model_weights = {k: round(_num(v) or 0.0, 4) for k, v in (ens.get("model_weights_json") or {}).items()}
    base.weight_mode = _weight_mode(ens.get("model_weights_json") or {}, warnings)

    nr_unverified = next((w for w in warnings if w.startswith("data_unverified_nr")), None)
    review_flags = [w for w in warnings if w.startswith("headline_review_")]
    if nr_unverified:
        base.state = "NR_UNVERIFIED"
        base.reason = nr_unverified
    elif base.fair_value_base is None and review_flags:
        # Brief 44 governance gate: headline deliberately withheld for review
        # (e.g. lone thin comp carrying ~100% weight with uncorroborated upside).
        base.state = "HEADLINE_REVIEW"
        base.reason = ";".join(review_flags)
    elif "no_usable_valuation_models" in warnings or base.fair_value_base is None:
        base.state = "NR_NO_MODELS"
        blocked = "; ".join(f"{m}:{w}" for m, w in sorted(base.models_blocked.items()))
        base.reason = blocked or "no usable valuation models"
    elif base.usable_model_count < 3:
        base.state = "BELOW_QUORUM"
        base.reason = f"usable_model_count={base.usable_model_count} < 3"
    else:
        base.state = "OK"
        base.reason = None
    return base


def _print_report(audits: list[SymbolAudit]) -> None:
    states = Counter(a.state for a in audits)
    modes = Counter(a.weight_mode for a in audits if a.weight_mode)
    blocked = Counter()
    for a in audits:
        for model, warning in a.models_blocked.items():
            blocked[(model, warning)] += 1

    print("Fundamental coverage audit")
    print(f"universe={len(audits)}")
    print("states: " + " ".join(f"{k}={v}" for k, v in sorted(states.items())))
    print("weight modes: " + " ".join(f"{k}={v}" for k, v in sorted(modes.items())))
    print()
    print("symbol,state,weight_mode,usable,upside_pct,confidence,verification,source,reason")
    for a in sorted(audits, key=lambda x: (x.state, x.symbol)):
        print(
            ",".join(
                [
                    a.symbol,
                    a.state,
                    a.weight_mode or "-",
                    str(a.usable_model_count),
                    f"{a.upside_pct * 100.0:.1f}" if a.upside_pct is not None else "NA",
                    f"{a.confidence_score:.2f}" if a.confidence_score is not None else "NA",
                    a.verification_status or "-",
                    a.data_source or "-",
                    (a.reason or "").replace(",", ";"),
                ]
            )
        )
    print()
    print("Top model-blocking warnings:")
    for (model, warning), count in blocked.most_common(15):
        print(f"  {count:3d}  {model}: {warning}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit fundamentals coverage across the active MASI universe.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", DEFAULT_DB_URL))
    parser.add_argument("--scenario", default="base")
    parser.add_argument("--json", type=Path, default=None, help="Also write the full audit to this JSON file.")
    args = parser.parse_args()

    engine = create_engine(args.database_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with engine.connect() as con:
        stocks = _active_masi_equities(con)
    symbols = [str(s["symbol"]).upper() for s in stocks]

    with SessionLocal() as db:
        snapshots = fundamental_service.latest_snapshot_rows_by_symbol(db, symbols=symbols, scope="all")
    snapshots = {sym.upper(): row for sym, row in snapshots.items()}
    import_ids = sorted({str(row.import_id) for row in snapshots.values()})

    with engine.connect() as con:
        ensembles = _ensembles(con, import_ids, args.scenario)
        valuations = _valuations(con, import_ids, args.scenario)
        verifications = _verifications(con, import_ids)
        sources = _import_sources(con, import_ids)

    audits = [
        _audit_symbol(stock, snapshots.get(str(stock["symbol"]).upper()), ensembles, valuations, verifications, sources)
        for stock in stocks
    ]
    _print_report(audits)
    if args.json:
        args.json.write_text(
            json.dumps([asdict(a) for a in audits], indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"\nJSON written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
