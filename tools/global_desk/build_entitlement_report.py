"""Render the W1 entitlement-discovery report skeleton from the security master.

The status columns are filled in from an actual Bloomberg discovery job run on
the terminal -- this script only guarantees the instrument list, the candidate
tickers and the free-fallback picture stay in sync with the registry.

    python tools/global_desk/build_entitlement_report.py

Writes docs/global-desk/reports/entitlement-discovery.md.
"""

from __future__ import annotations

import pathlib
import sys


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "core"))

from quant_core.cross_asset import universes  # noqa: E402
from quant_core.cross_asset.security_master import REGISTRY, by_asset_class  # noqa: E402


OUT_PATH = REPO_ROOT / "docs" / "global-desk" / "reports" / "entitlement-discovery.md"

ASSET_CLASS_TITLES = [
    ("fx", "FX"),
    ("rates", "Sovereign rates"),
    ("credit", "Credit"),
    ("commodity", "Commodities"),
    ("equity_index", "Equity index"),
]


def _rows(asset_class: str) -> list[str]:
    rows = []
    for entry in by_asset_class(asset_class):
        candidates = " / ".join(f"`{t}`" for t in entry.bloomberg_candidates)
        free = f"`{entry.free_proxy}`" if entry.free_proxy else "**none**"
        rows.append(
            f"| `{entry.canonical_id}` | {entry.description} | {candidates} | {free} | "
            f"{entry.history_start.isoformat()} | | | |"
        )
    return rows


def build() -> str:
    dark = [e.canonical_id for e in REGISTRY if not e.has_free_path]
    entitlement_risk = [e.canonical_id for e in REGISTRY if "entitlement_risk" in e.tags]

    lines: list[str] = [
        "# W1 — Bloomberg Entitlement Discovery Report",
        "",
        "**Status: AWAITING TERMINAL RUN.** This file is a skeleton generated from the",
        "security master. The three right-hand columns are empty until a discovery job",
        "runs on the Bloomberg machine — nothing here should be read as a known result.",
        "",
        "Regenerate the skeleton with:",
        "",
        "```bash",
        "python tools/global_desk/build_entitlement_report.py",
        "```",
        "",
        "## How to produce the data",
        "",
        "On the Bloomberg terminal machine, with the listener running (see",
        "`tools/bloomberg_bridge/FIELD_VISIT_RUNBOOK.md` steps 1-6), queue from **Data →",
        "Bloomberg**:",
        "",
        "```text",
        "Job:       Discovery",
        "Universe:  global_all",
        "Mode:      Discovery only",
        "Frequency: Daily",
        "Fields:    PX_LAST",
        "```",
        "",
        "Start with `Universe: g10_fx` as a smaller smoke test before `global_all`, the",
        "same way the MASI runbook tests one stock before the full index.",
        "",
        "Then fill the columns below from the job result:",
        "",
        "* **Status** — `available` / `partial` / `unavailable` / `not_entitled`",
        "* **Earliest** — first date the terminal actually returns",
        "* **Notes** — which candidate ticker resolved, field gaps, anything surprising",
        "",
        "## Why this report gates W4 and W5",
        "",
        "Two workstreams are scoped from these results rather than in advance:",
        "",
        f"* **Credit ({', '.join(f'`{c}`' for c in entitlement_risk)})** — the highest",
        "  entitlement risk in the registry, and the tickers are unverified candidates. If",
        "  credit is not entitled, W4's eurobond RV layer ships against ETF proxies with",
        "  mixed duration/spread exposure, which is a materially weaker claim and must be",
        "  labelled as such.",
        "* **Commodities** — the question is whether *per-contract chains* are available,",
        "  not just prices. Real chains are what turn the engine's roll accounting from",
        "  illustrative into tradable (decision G7). Price-only means commodities stay on",
        "  the non-tradable label.",
        "",
        "Also confirm, for anything that will size a real trade: **contract multipliers and",
        "tick sizes in the registry are taken from public specifications, not from the",
        "terminal.** Verify against `DES` / `CT` before live use — `unverified_for_live_sizing()`",
        "currently returns every instrument.",
        "",
        "## What goes dark without Bloomberg",
        "",
        "Program decision G9 requires that no sleeve *assume* Bloomberg. These instruments",
        "have no free fallback and are the exception — they are unavailable, not degraded,",
        "if the terminal is absent:",
        "",
    ]

    if dark:
        for cid in dark:
            entry = next(e for e in REGISTRY if e.canonical_id == cid)
            lines.append(f"* `{cid}` — {entry.description}. {entry.free_proxy_note}")
    else:
        lines.append("* (none)")

    lines += [
        "",
        f"Everything else ({len(REGISTRY) - len(dark)} of {len(REGISTRY)} instruments) has a",
        "documented free path and degrades in data quality rather than disappearing.",
        "",
        "## Instruments",
        "",
    ]

    for asset_class, title in ASSET_CLASS_TITLES:
        entries = by_asset_class(asset_class)
        lines += [
            f"### {title} ({len(entries)})",
            "",
            "| Id | Description | Bloomberg candidates | Free fallback | Requested from | Status | Earliest | Notes |",
            "|---|---|---|---|---|---|---|---|",
            *_rows(asset_class),
            "",
        ]

    lines += [
        "## Universe summary",
        "",
        "| Universe | Instruments |",
        "|---|---|",
    ]
    for name in universes.UNIVERSE_NAMES:
        lines.append(f"| `{name}` | {len(universes.resolve(name))} |")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)} ({len(REGISTRY)} instruments)")


if __name__ == "__main__":
    main()
