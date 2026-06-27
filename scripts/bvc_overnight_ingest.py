"""Ingest a BVC factor workbook and re-verify/revalue affected symbols.

Runs host-side (DB on 127.0.0.1:5555). Mirrors the "Importer Excel" upload path,
then re-runs verification (with the fixed ni_link) and scenario revaluation so
newly-scraped balance sheets turn into ratings.

Usage:
    python scripts/bvc_overnight_ingest.py "C:\\path\\to\\factors.xlsx"
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://app:app@127.0.0.1:5555/quant")
os.environ["FUNDAMENTAL_DISABLE_LIVE_QUOTES"] = "1"

# services/api on path so `app.*` imports resolve (matches remediate_fundamentals).
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for p in (os.path.join(_ROOT, "services", "api"), _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import psycopg2  # noqa: E402
from app.db import _ensure_session_factory  # noqa: E402
from app.services.fundamentals import (  # noqa: E402
    create_import_run,
    execute_import_run,
    refresh_canonical_snapshot_flags,
)
from services.api.scripts.remediate_fundamentals import remediate_fundamentals  # noqa: E402

PG = "postgresql://app:app@127.0.0.1:5555/quant"


def _blocked_symbols() -> list[str]:
    """Canonical symbols that are data_unverified or missing a required field."""
    cur = psycopg2.connect(PG).cursor()
    cur.execute(
        """
        select s.symbol, s.import_id, s.latest_statement_year
        from fundamental_latest_snapshot s where s.is_canonical
        """
    )
    snaps = cur.fetchall()
    req = {
        ("Total_Actif", "Total_Assets"),
        ("Total_Passif", "Total_Liabilities", "Total_Liabilities_And_Equity"),
        ("Capitaux_propres", "Total_Equity", "Capitaux_propres_part_du_groupe"),
        ("Resultat_net", "NetIncome", "Resultat_net_part_du_groupe"),
    }
    blocked: set[str] = set()
    for sym, imp, yr in snaps:
        if yr is None:
            blocked.add(sym)
            continue
        cur.execute(
            "select metric_name from fundamental_annual_metric "
            "where import_id=%s and symbol=%s and statement_year=%s and metric_value is not null",
            (imp, sym, yr),
        )
        have = {r[0] for r in cur.fetchall()}
        if any(not (set(al) & have) for al in req):
            blocked.add(sym)
    cur.execute(
        """
        select v.symbol from fundamental_data_verification v
        join fundamental_latest_snapshot s
          on s.import_id=v.import_id and s.symbol=v.symbol and s.latest_statement_year=v.statement_year
        where s.is_canonical and v.status='data_unverified'
        """
    )
    blocked.update(r[0] for r in cur.fetchall())
    return sorted(blocked)


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python scripts/bvc_overnight_ingest.py <workbook.xlsx>")
        sys.exit(2)
    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"workbook not found: {path}")
        sys.exit(2)

    payload = open(path, "rb").read()
    before = set(_blocked_symbols())
    print(f"[1/3] ingesting workbook ({len(payload):,} bytes): {path}")
    sf = _ensure_session_factory()
    with sf() as db:
        run = create_import_run(db, data_source="workbook", source_universe="masi",
                                filename=os.path.basename(path))
        run_id = str(run.id)  # capture before commit expires the detached instance
        execute_import_run(db, import_id=run.id, payload=payload)
        refresh_canonical_snapshot_flags(db)
        db.commit()
    print(f"      import {run_id} ingested.")

    after_ingest = set(_blocked_symbols())
    targets = sorted(before | after_ingest)
    print(f"[2/3] re-verifying + revaluing {len(targets)} symbols...")
    with sf() as db:
        rows = remediate_fundamentals(db, symbols=targets, apply=True, revalue=True)

    verified = [r["symbol"] for r in rows if r["status"] == "verified"]
    recovered = sorted(set(verified) & before)
    print("[3/3] done.")
    print(f"      blocked before:        {len(before)}")
    print(f"      still blocked after:   {len(after_ingest)}")
    print(f"      verified this run:     {len(verified)}")
    print(f"      RECOVERED (was blocked -> verified): {len(recovered)} -> {' '.join(recovered) or '(none)'}")


if __name__ == "__main__":
    main()
