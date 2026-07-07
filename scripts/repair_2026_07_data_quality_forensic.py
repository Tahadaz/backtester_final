"""Repair script for the 2026-07-06 data-quality forensic audit.

Source docs: research-out/data-quality-forensic-repair/2026-07-06/

Two independent, root-caused repairs:

1. REB source-document mis-mapping: 190 rows in fundamental_source_document
   tagged symbol='REB' are actually filings for Maghrebail, Maghreb Oxygene,
   Promopharm, and Societe Maghrebine de Monetique (ticker "REB" is a literal
   substring of "Maghreb"). This script marks those rows status='mismapped'
   (does not delete -- preserves provenance) and deletes the
   fundamental_annual_metric rows whose only source is one of those documents,
   for the affected years, so REB's book equity / cash / EBITDA figures stop
   being corrupted by other companies' financials.

2. EnterpriseValue = Total_Debt - Cash bug: 150 symbol-years have EV silently
   computed as net debt only (market-cap term dropped in the source workbook).
   This script writes a corrected EnterpriseValue row per affected
   symbol/year/import where a MarketCap_Calc value is available, tagged with
   raw_metric_name='REPAIR_2026-07-06_ev_recompute' for auditability. Rows
   where no market cap is available are left untouched and reported as
   unresolved.

3. demo_fixture contamination (found during Workstream 2 continuation,
   2026-07-06): two 'demo_fixture' imports (ca219b26-..., 4499aa3d-...)
   inserted synthetic test rows for ATW, BOA, IAM, MNG, TQM directly into
   fundamental_annual_metric with no import-level filter excluding them from
   the research panel. Confirmed live: ATW and IAM's PIT panel for all of
   2021 was reading Total_Equity=53300 (a synthetic placeholder) instead of
   the real ~59.8B/~16.4B book equity, because METRIC_ALIASES["book_equity"]
   checks "Total_Equity" first and the demo row won the tie-break. This
   repair deletes every fundamental_annual_metric and fundamental_period_metric
   row sourced from a demo_fixture import.

This script does NOT run automatically. Review the CSVs in the audit
directory first. Run with --dry-run (default) to see what would change;
pass --apply to write to the DB.
"""
import argparse
import csv
import os

import psycopg2

AUDIT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "research-out", "data-quality-forensic-repair", "2026-07-06"
)
REPAIR_TAG = "REPAIR_2026-07-06_ev_recompute"


def connect():
    return psycopg2.connect(host="127.0.0.1", port=5555, dbname="quant", user="app", password="app")


def repair_reb_documents(conn, apply: bool) -> None:
    with open(os.path.join(AUDIT_DIR, "reb_mismapped_documents.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"[REB] {len(rows)} mismapped source_document rows found in audit CSV")
    doc_ids = [int(r["document_id"]) for r in rows]
    cur = conn.cursor()
    cur.execute(
        "select count(*) from fundamental_annual_metric where symbol='REB' and source_document_id = any(%s)",
        (doc_ids,),
    )
    (n_metric_rows,) = cur.fetchone()
    print(f"[REB] {n_metric_rows} fundamental_annual_metric rows sourced from those documents will be deleted")
    if not apply:
        print("[REB] dry-run only, no changes made")
        return
    cur.execute(
        "update fundamental_source_document set status='mismapped' where id = any(%s)",
        (doc_ids,),
    )
    cur.execute(
        "delete from fundamental_annual_metric where symbol='REB' and source_document_id = any(%s)",
        (doc_ids,),
    )
    conn.commit()
    print("[REB] applied: source docs marked mismapped, derived metric rows deleted")


def repair_enterprise_value(conn, apply: bool) -> None:
    with open(os.path.join(AUDIT_DIR, "repaired_enterprisevalue_rows.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    repaired = [r for r in rows if r["status"] == "repaired"]
    unresolved = [r for r in rows if r["status"] != "repaired"]
    print(f"[EV] {len(repaired)} rows repairable, {len(unresolved)} unresolved (no market cap available)")
    if not apply:
        print("[EV] dry-run only, no changes made")
        return
    cur = conn.cursor()
    for r in repaired:
        cur.execute(
            """
            update fundamental_annual_metric
            set metric_value = %s, raw_metric_name = %s
            where symbol=%s and statement_year=%s and import_id=%s and metric_name='EnterpriseValue'
            """,
            (float(r["new_enterprise_value"]), REPAIR_TAG, r["symbol"], int(r["statement_year"]), r["import_id"]),
        )
    conn.commit()
    print(f"[EV] applied: {len(repaired)} EnterpriseValue rows updated, tagged '{REPAIR_TAG}'")


def repair_demo_fixture_contamination(conn, apply: bool) -> None:
    cur = conn.cursor()
    cur.execute("select id, filename, annual_metric_count from fundamental_import where data_source='demo_fixture'")
    imports = cur.fetchall()
    import_ids = [str(r[0]) for r in imports]
    print(f"[DEMO] {len(import_ids)} demo_fixture import(s): {import_ids}")
    cur.execute(
        "select symbol, count(*) from fundamental_annual_metric where import_id = any(%s::uuid[]) group by symbol order by symbol",
        (import_ids,),
    )
    by_symbol = cur.fetchall()
    print(f"[DEMO] fundamental_annual_metric rows by symbol: {by_symbol}")
    cur.execute(
        "select count(*) from fundamental_period_metric where import_id = any(%s::uuid[])",
        (import_ids,),
    )
    (n_period,) = cur.fetchone()
    print(f"[DEMO] fundamental_period_metric rows: {n_period}")
    if not apply:
        print("[DEMO] dry-run only, no changes made")
        return
    cur.execute("delete from fundamental_annual_metric where import_id = any(%s::uuid[])", (import_ids,))
    cur.execute("delete from fundamental_period_metric where import_id = any(%s::uuid[])", (import_ids,))
    conn.commit()
    print("[DEMO] applied: all demo_fixture-sourced metric rows deleted")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write changes to the DB (default: dry-run)")
    parser.add_argument("--only", choices=["reb", "ev", "demo"], help="Run only one repair")
    args = parser.parse_args()

    conn = connect()
    if args.only in (None, "reb"):
        repair_reb_documents(conn, args.apply)
    if args.only in (None, "ev"):
        repair_enterprise_value(conn, args.apply)
    if args.only in (None, "demo"):
        repair_demo_fixture_contamination(conn, args.apply)
    conn.close()


if __name__ == "__main__":
    main()
