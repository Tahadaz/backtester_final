"""Apply the per-symbol assumption sets in data/research/assumption_sets/*.json
to a running API via PUT /fundamentals/stocks/{symbol}/assumptions/{scenario}.

Usage:
  python services/api/scripts/apply_assumption_sets.py --dry-run
  python services/api/scripts/apply_assumption_sets.py --api http://localhost:8000 --token <bearer>

Only keys present in DEFAULT_ASSUMPTIONS are sent; per-stock metadata like
unlevered_beta and gearing_de are stripped out (they live in the research
JSON for human reference but the engine doesn't store them).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
ASSUMPTION_DIR = REPO_ROOT / "data" / "research" / "assumption_sets"

# Mirror of DEFAULT_ASSUMPTIONS keys accepted by the API. Anything outside this
# set is silently dropped from the payload.
ACCEPTED_KEYS = {
    "risk_free_rate",
    "equity_risk_premium",
    "country_risk_premium",
    "cost_of_equity",
    "cost_of_debt",
    "tax_rate",
    "wacc",
    "default_debt_weight",
    "default_equity_weight",
    "terminal_growth",
    "forecast_years",
    "fade_years",
    "growth_cap",
    "stable_payout_ratio",
    "peer_min_count",
    "proxy_weight_cap",
    "bs_balance_warn_bps",
    "bs_balance_fail_bps",
    "sensitivity_wacc_step",
    "sensitivity_terminal_growth_step",
    "sensitivity_growth_cap_step",
    "currency",
}


def filter_payload(assumptions: dict) -> dict:
    payload = {k: v for k, v in assumptions.items() if k in ACCEPTED_KEYS}
    de = assumptions.get("gearing_de")
    if de is not None and de > 0 and "default_debt_weight" not in payload:
        we = 1.0 / (1.0 + de)
        payload["default_debt_weight"] = round(1.0 - we, 4)
        payload["default_equity_weight"] = round(we, 4)
    return payload


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000", help="API base URL")
    p.add_argument("--token", default=None, help="Admin bearer token")
    p.add_argument("--scenario", default="base", choices=["bear", "base", "bull"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--only", nargs="*", help="Optional list of symbols to restrict to")
    args = p.parse_args()

    files = sorted(ASSUMPTION_DIR.glob("*.json"))
    if not files:
        print(f"No JSON files in {ASSUMPTION_DIR}", file=sys.stderr)
        sys.exit(1)

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    only = set(s.upper() for s in (args.only or []))
    successes = 0
    skipped = 0
    failures: list[tuple[str, str]] = []

    with httpx.Client(timeout=30.0) as client:
        for path in files:
            doc = json.loads(path.read_text(encoding="utf-8"))
            symbol = doc["symbol"].upper()
            if only and symbol not in only:
                continue
            payload_assumptions = filter_payload(doc["assumptions_json"])
            body = {
                "scope_type": "symbol",
                "scope_key": symbol,
                "scenario": args.scenario,
                "assumptions_json": payload_assumptions,
                "version_label": "calibrated-2026-05",
            }
            url = f"{args.api}/fundamentals/stocks/{symbol}/assumptions/{args.scenario}"
            if args.dry_run:
                print(f"DRY {symbol}  WACC={payload_assumptions.get('wacc'):.4f}  COE={payload_assumptions.get('cost_of_equity'):.4f}  g={payload_assumptions.get('terminal_growth')}")
                successes += 1
                continue
            try:
                resp = client.put(url, json=body, headers=headers)
                if resp.status_code in (200, 201):
                    successes += 1
                    print(f"OK  {symbol}  status={resp.status_code}")
                elif resp.status_code == 404:
                    skipped += 1
                    print(f"SKIP {symbol}  (no snapshot found)")
                else:
                    failures.append((symbol, f"HTTP {resp.status_code}: {resp.text[:200]}"))
                    print(f"FAIL {symbol}  status={resp.status_code}  body={resp.text[:200]}")
            except httpx.HTTPError as exc:
                failures.append((symbol, str(exc)))
                print(f"ERR  {symbol}  {exc}")

    print()
    print(f"Done. ok={successes} skipped={skipped} failed={len(failures)}")
    if failures:
        for sym, err in failures:
            print(f"  - {sym}: {err}")
        sys.exit(2)


if __name__ == "__main__":
    main()
