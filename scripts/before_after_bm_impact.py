"""Before/after impact reconstruction for the REB and ATW/IAM data repairs on B/M (Workstream 3).

Rather than re-running the full expensive characteristic study twice against two different
DB snapshots (the corrupted DB state no longer exists -- it was repaired in place), this
script takes the AFTER (repaired, actually-computed) panel_characteristics.csv and
reconstructs the BEFORE book_to_market_raw for the three affected symbols (REB, ATW, IAM)
using the exact old values recorded during the forensic audit:

- REB: Total_Equity was corrupted for statement years 2020/2023/2024/2025 by mis-mapped
  documents (Maghrebail/Promopharm/Maghreb Oxygene/Ste Maghrebine de Monetique). Old values
  are recorded in known_cases_reb_sah_sbm.md.
- ATW, IAM: Total_Equity=53300 / a similarly tiny demo_fixture placeholder silently won the
  metric resolver for 2021 dates before the demo_fixture purge.

All other symbols' values are held at their AFTER (current, real) state, since they were not
touched by these two repairs -- this isolates the causal effect of exactly these two
data-repairs on the B/M cross-section, holding methodology (this session's canonical B/M
definition) fixed.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

AFTER_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "research-out/data-quality-forensic-repair/2026-07-06/characteristic-study-after-repair"
)

# Old REB Total_Equity by statement year (from known_cases_reb_sah_sbm.md)
REB_OLD_BOOK_EQUITY_BY_YEAR = {
    2020: 921_090_000.00,   # actually Maghrebail FY2022 filing
    2022: 24_000_192.62,    # genuine Rebab Company FY2022 -- unaffected, same as after
    2023: 475_765_782.17,   # actually a different mismapped filing
    2024: 530_925_751.86,   # actually Promopharm FY2024
    2025: 319_225_000.00,   # actually Maghreb Oxygene FY2025
}
# ATW/IAM demo_fixture placeholder that won the resolver for 2021 dates
DEMO_TOTAL_EQUITY = 53_300.0


def find_latest_run_dir(base: Path) -> Path:
    runs = sorted(base.glob("2*"))
    if not runs:
        raise SystemExit(f"No run directories found under {base}")
    return runs[-1]


def main() -> None:
    run_dir = find_latest_run_dir(AFTER_DIR)
    panel = pd.read_csv(run_dir / "panel_characteristics.csv")
    panel["as_of_date"] = pd.to_datetime(panel["as_of_date"])

    before = panel.copy()

    # REB: recompute book_to_market_raw using the old (corrupted) book equity for the
    # years it was wrong, applied to whatever market cap the AFTER panel already carries
    # at each date (market cap was not touched by the REB document-mismap repair).
    reb_mask = before["symbol"] == "REB"
    for idx in before.index[reb_mask]:
        row = before.loc[idx]
        mcap = row.get("market_cap_raw")
        year = row["as_of_date"].year
        # approximate which statement year's book equity would have been the latest
        # available as of this date, using the same year buckets as the known corrupted years
        old_book = None
        for y in sorted(REB_OLD_BOOK_EQUITY_BY_YEAR):
            if year >= y:
                old_book = REB_OLD_BOOK_EQUITY_BY_YEAR[y]
        if old_book is not None and mcap and mcap > 0 and old_book > 0:
            before.loc[idx, "book_to_market_raw"] = old_book / mcap

    # ATW, IAM: 2021 dates used the demo_fixture Total_Equity=53300 placeholder.
    for sym in ("ATW", "IAM"):
        mask = (before["symbol"] == sym) & (before["as_of_date"].dt.year == 2021)
        for idx in before.index[mask]:
            mcap = before.loc[idx, "market_cap_raw"]
            if mcap and mcap > 0:
                before.loc[idx, "book_to_market_raw"] = DEMO_TOTAL_EQUITY / mcap

    # Re-standardize book_to_market (signed z-score) per date, matching add_characteristics'
    # own z-scoring convention (mad_winsorized_z, positive direction), for both panels.
    from core.quant_core.fundamentals.cross_section.methodology_bakeoff import _signed_z, ic_table

    for frame in (before, panel):
        frame["book_to_market"] = _signed_z(frame, "book_to_market_raw", positive=True)

    # Compute IC for both, native sample, all available horizons already in the panel.
    horizons = [c.replace("fwd_return_", "") for c in panel.columns if c.startswith("fwd_return_")]
    signals = {"book_to_market": "Book equity / market cap"}

    def ic_for(frame: pd.DataFrame, label: str) -> pd.DataFrame:
        # ic_table expects fwd_return_<horizon> columns and HORIZONS constant; monkeypatch scope
        import core.quant_core.fundamentals.cross_section.methodology_bakeoff as mb
        old_horizons = mb.HORIZONS
        mb.HORIZONS = tuple(horizons)
        try:
            return ic_table(frame, signals, sample_label=label)
        finally:
            mb.HORIZONS = old_horizons

    ic_before = ic_for(before, "before_repair_reconstructed")
    ic_after = ic_for(panel, "after_repair_actual")

    out = pd.concat([ic_before, ic_after], ignore_index=True)
    out_path = run_dir / "bm_before_after_ic.csv"
    out.to_csv(out_path, index=False)
    print(out.to_string(index=False))
    print(f"\nWritten: {out_path}")

    # Observation-level diff for REB/ATW/IAM
    diff_rows = []
    for sym in ("REB", "ATW", "IAM"):
        b = before[before["symbol"] == sym][["as_of_date", "book_to_market_raw"]].rename(columns={"book_to_market_raw": "before"})
        a = panel[panel["symbol"] == sym][["as_of_date", "book_to_market_raw"]].rename(columns={"book_to_market_raw": "after"})
        merged = b.merge(a, on="as_of_date")
        merged["symbol"] = sym
        diff_rows.append(merged)
    diffs = pd.concat(diff_rows, ignore_index=True)
    diffs["changed"] = (diffs["before"] - diffs["after"]).abs() > 1e-9
    diffs.to_csv(run_dir / "bm_reb_atw_iam_observation_diff.csv", index=False)
    print(f"\n{diffs['changed'].sum()} of {len(diffs)} REB/ATW/IAM stock-month observations changed value")
    print(diffs.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
