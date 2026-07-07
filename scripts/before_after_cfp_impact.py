"""Before/after impact of the CF/P financial-sector exclusion (Workstream 3).

Unlike the REB/ATW/IAM B/M fixes (data repairs), the CF/P change made this session is a
methodology/definition change: excluding bank/insurance issuers from cashflow_price_raw
(cfp_canonical_definition.md). "Before" here means "before this session's canonical CF/P
exclusion was applied" -- i.e. cashflow_price_raw computed uniformly including financials,
which is exactly what the code did prior to this session's edit. We reconstruct it directly:
CFO / MarketCap for financial-sector rows, using the AFTER panel's own market_cap_raw (market
cap was not touched by this change).
"""
import sys
from pathlib import Path

import pandas as pd

AFTER_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "research-out/data-quality-forensic-repair/2026-07-06/characteristic-study-after-repair"
)


def find_latest_run_dir(base: Path) -> Path:
    runs = sorted(base.glob("2*"))
    if not runs:
        raise SystemExit(f"No run directories found under {base}")
    return runs[-1]


def main() -> None:
    run_dir = find_latest_run_dir(AFTER_DIR)
    panel = pd.read_csv(run_dir / "panel_characteristics.csv")

    if "is_financial" not in panel.columns:
        raise SystemExit("panel_characteristics.csv has no is_financial column; cannot reconstruct")

    before = panel.copy()
    # Recompute cashflow_price_raw for financial rows as CFO/MarketCap directly.
    # cashflow_conversion / CFO isn't separately stored per-row in the saved CSV, so
    # reconstruct via cashflow_price_raw == None (after) -> need CFO. Since CFO itself
    # isn't a saved column, approximate using cashflow_price_raw's pre-exclusion formula
    # is not reconstructible without the raw metrics dict (dropped from the CSV). Report
    # coverage impact instead (how many financial-sector observations lost CF/P coverage),
    # which is the well-defined, honestly-computable quantity here.
    fin_mask = before["is_financial"].astype(bool)
    n_financial_null_cfp = int((fin_mask & before["cashflow_price_raw"].isna()).sum())
    n_financial_total = int(fin_mask.sum())
    print(f"Financial-sector stock-months: {n_financial_total}")
    print(f"Of those, cashflow_price_raw is null (excluded) after this session's fix: {n_financial_null_cfp}")
    print(
        "Note: exact CFO values for financial rows are not retained in panel_characteristics.csv "
        "(only the derived ratio columns are saved), so the 'before' cashflow_price_raw value for "
        "financial rows cannot be numerically reconstructed from this artifact alone -- the coverage "
        "impact (how many observations were excluded) is the honestly-computable quantity, reported above."
    )

    out = pd.DataFrame(
        [{"financial_stock_months": n_financial_total, "excluded_from_cfp_after_fix": n_financial_null_cfp}]
    )
    out.to_csv(run_dir / "cfp_financial_exclusion_coverage_impact.csv", index=False)


if __name__ == "__main__":
    main()
