"""Diagnose why DDM and Residual Income print far below market price for one symbol.

Usage:
    python services/api/scripts/diagnose_managem_inputs.py
    python services/api/scripts/diagnose_managem_inputs.py --symbol IAM
    python services/api/scripts/diagnose_managem_inputs.py --symbol MNG --scenario bear

Reads directly from the DB. Prints the snapshot metrics and history entries that
`_ddm` and `_residual_income` consume, computes the derived per-share quantities
the models use internally, and finally re-runs both models with the on-disk
inputs so you can compare to what the API returns.

If DPS, BVPS, or any ratio looks wrong, the bug is in ingest (the wrong number
was written), not in the valuation engine.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import _ensure_session_factory  # noqa: E402
from app import models  # noqa: E402

from core.quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot  # noqa: E402
from core.quant_core.fundamentals import valuation as v  # noqa: E402


# ----------------------------------------------------------------------------- helpers


def _fmt(value, places: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.{places}f}"
    return str(value)


def _row(label: str, value, suffix: str = "", warn: str | None = None) -> str:
    chunk = f"  {label:<32}{_fmt(value)}{suffix}"
    if warn:
        chunk += f"   <-- {warn}"
    return chunk


def _latest_snapshot(db: Session, symbol: str) -> models.FundamentalLatestSnapshot | None:
    stmt = (
        select(models.FundamentalLatestSnapshot)
        .where(models.FundamentalLatestSnapshot.symbol == symbol)
        .order_by(models.FundamentalLatestSnapshot.updated_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _annual_history(db: Session, symbol: str, import_id) -> list[models.FundamentalAnnualMetric]:
    stmt = (
        select(models.FundamentalAnnualMetric)
        .where(
            models.FundamentalAnnualMetric.symbol == symbol,
            models.FundamentalAnnualMetric.import_id == import_id,
        )
        .order_by(models.FundamentalAnnualMetric.statement_year.desc())
    )
    return list(db.execute(stmt).scalars().all())


def _stock_master(db: Session, symbol: str) -> models.StockMaster | None:
    return db.execute(select(models.StockMaster).where(models.StockMaster.symbol == symbol)).scalar_one_or_none()


# ----------------------------------------------------------------------------- main


def diagnose(symbol: str, scenario: str) -> int:
    SessionLocal = _ensure_session_factory()
    db: Session = SessionLocal()

    try:
        sm = _stock_master(db, symbol)
        snap_row = _latest_snapshot(db, symbol)

        if not sm:
            print(f"[ERROR] No StockMaster row for symbol {symbol!r}")
            return 2
        if not snap_row:
            print(f"[ERROR] No fundamental_latest_snapshot row for symbol {symbol!r}")
            return 2

        history_rows = _annual_history(db, symbol, snap_row.import_id)

        print("=" * 78)
        print(f"DIAGNOSTIC: {symbol}  (scenario = {scenario})")
        print("=" * 78)

        # --------------------------------------------------------------- stock_master
        print("\n[stock_master]")
        print(_row("display_name", sm.display_name))
        print(_row("sector", sm.sector))
        print(_row("asset_type", sm.asset_type))
        print(_row("shares_outstanding (DB)", sm.shares_outstanding, suffix="  (raw count, NOT millions)"))
        print(_row("shares_source", sm.shares_source))
        print(_row("shares_as_of", str(sm.shares_as_of) if sm.shares_as_of else None))

        if sm.shares_outstanding:
            if sm.shares_outstanding < 1_000:
                warn = "[!] suspiciously small - should be raw count (e.g. 10_000_000)"
            elif sm.shares_outstanding > 10_000_000_000:
                warn = "[!] suspiciously large - possible double-scale (x1M twice)"
            else:
                warn = None
            if warn:
                print(_row("    sanity", sm.shares_outstanding, warn=warn))

        # --------------------------------------------------------------- snapshot metrics
        metrics: dict = dict(snap_row.metrics_json or {})
        print("\n[fundamental_latest_snapshot.metrics_json - keys used by DDM / RI]")
        for key in [
            "Current_Price",
            "MarketCap_Calc",
            "Shares_Outstanding",
            "ROE",
            "Dividend_Yield",
            "Dividend_Payout",
            "Price_to_Book",
            "PER",
            "Book_Value_Per_Share",
            "NetIncome_Growth",
            "Revenue_Growth",
        ]:
            print(_row(key, metrics.get(key)))

        # --------------------------------------------------------------- latest dividend in history
        print("\n[fundamental_annual_metric - latest Dividendes / Clean_Dividendes]")
        div_rows = [r for r in history_rows if r.metric_name in ("Dividendes", "Clean_Dividendes")]
        div_rows = sorted(div_rows, key=lambda r: r.statement_year, reverse=True)
        if not div_rows:
            print("  (no Dividendes / Clean_Dividendes rows found)")
        else:
            for r in div_rows[:5]:
                print(_row(f"{r.metric_name} @ {r.statement_year}", r.metric_value))

        latest_div_total = div_rows[0].metric_value if div_rows else None
        latest_div_year = div_rows[0].statement_year if div_rows else None

        # --------------------------------------------------------------- derived per-share
        print("\n[Derived per-share quantities the models will compute]")
        snap_shares = metrics.get("Shares_Outstanding")
        ddm_shares = snap_shares  # _shares() reads from the snapshot
        if latest_div_total and ddm_shares:
            implied_dps = latest_div_total / ddm_shares
            print(_row("Implied DPS (latest / shares)", implied_dps, suffix=f"  ({latest_div_total:,.0f} / {ddm_shares:,.0f})"))
            print(_row(f"  using year {latest_div_year} divs", "", suffix=""))
        else:
            print("  Implied DPS: cannot compute (missing Dividendes total or Shares_Outstanding)")

        current_price = metrics.get("Current_Price")
        pb = metrics.get("Price_to_Book")
        if current_price and pb and pb > 0:
            implied_bvps = current_price / pb
            print(_row("Implied BVPS (price / PB)", implied_bvps, suffix=f"  ({current_price:,.2f} / {pb:.4f})"))
        else:
            print("  Implied BVPS: cannot compute (missing Current_Price or Price_to_Book)")

        # Dividend_Yield x Current_Price (the DDM fallback path)
        dy = metrics.get("Dividend_Yield")
        if dy is not None and current_price:
            print(_row("Current_Price x Div_Yield", current_price * dy, suffix=f"  (yield={dy})  <-- DDM fallback DPS"))

        # --------------------------------------------------------------- re-run models
        print("\n[Re-running _ddm and _residual_income with on-disk inputs]")

        snapshot = FundamentalSnapshot(
            symbol=symbol,
            company_name=snap_row.company_name,
            latest_statement_year=snap_row.latest_statement_year,
            metrics=metrics,
            scores=dict(snap_row.scores_json or {}),
            diagnostics=dict(snap_row.diagnostics_json or {}),
            coverage=dict(snap_row.coverage_json or {}),
            source=dict(snap_row.source_json or {}),
        )
        history = [
            AnnualMetricRow(
                symbol=r.symbol,
                company_name=r.company_name,
                statement_year=r.statement_year,
                metric_name=r.metric_name,
                metric_value=r.metric_value,
            )
            for r in history_rows
        ]

        # Try to load the per-symbol assumptions if they exist (brief 25 path)
        assumption_set = (
            db.execute(
                select(models.FundamentalAssumptionSet).where(
                    models.FundamentalAssumptionSet.scope_type == "symbol",
                    models.FundamentalAssumptionSet.scope_key == symbol,
                    models.FundamentalAssumptionSet.scenario == scenario,
                )
            )
            .scalars()
            .first()
        )
        if assumption_set:
            user_assumptions = dict(assumption_set.assumptions_json or {})
            print(f"  using assumption_set for ({symbol}, {scenario}): {len(user_assumptions)} keys")
        else:
            user_assumptions = {}
            print(f"  no per-symbol assumption_set for ({symbol}, {scenario}); using defaults")

        merged = {**v.default_assumptions_for_scenario(scenario), **user_assumptions}
        print(_row("  cost_of_equity", merged.get("cost_of_equity")))
        print(_row("  terminal_growth", merged.get("terminal_growth")))
        print(_row("  fade_years", merged.get("fade_years")))
        print(_row("  growth_cap", merged.get("growth_cap")))
        print(_row("  stable_payout_ratio", merged.get("stable_payout_ratio")))

        is_financial = (sm.sector or "").lower() in {"banques", "assurances", "credit", "financial", "financials"}

        ddm = v._ddm(snapshot, history, current_price, merged, scenario)
        ri = v._residual_income(snapshot, current_price, merged, scenario, is_financial)

        print("\n[DDM output]")
        print(_row("fair_value", ddm.fair_value))
        print(_row("confidence", ddm.confidence))
        print(_row("warnings", ", ".join(ddm.warnings) if ddm.warnings else "-"))
        for k in ("dividend_per_share", "dividend_source", "reported_dividend_total", "shares", "growth", "growth_source", "fade_years", "h_factor"):
            print(_row(f"  inputs.{k}", ddm.inputs.get(k)))

        print("\n[Residual Income output]")
        print(_row("fair_value", ri.fair_value))
        print(_row("confidence", ri.confidence))
        print(_row("warnings", ", ".join(ri.warnings) if ri.warnings else "-"))
        for k in ("book_value_per_share", "roe", "cost_of_equity", "fade_years", "payout"):
            print(_row(f"  inputs.{k}", ri.inputs.get(k)))

        # --------------------------------------------------------------- verdict
        print("\n" + "=" * 78)
        print("VERDICT")
        print("=" * 78)

        verdict_lines: list[str] = []

        if ddm.fair_value and current_price:
            implied_yield = (ddm.inputs.get("dividend_per_share") or 0) / current_price
            if implied_yield < 0.005:
                verdict_lines.append(
                    f"DDM is using a DPS of {ddm.inputs.get('dividend_per_share'):.2f} on a price of "
                    f"{current_price:.2f} -> implied yield {implied_yield*100:.2f}%. That is too low for "
                    f"this market; inspect Dividendes total ({latest_div_total}) and Shares_Outstanding ({ddm_shares})."
                )

        if ri.fair_value and ri.inputs.get("book_value_per_share"):
            ratio = ri.fair_value / ri.inputs["book_value_per_share"]
            if 0.95 <= ratio <= 1.05:
                verdict_lines.append(
                    f"RI fair value ({ri.fair_value:.0f}) ~ book value ({ri.inputs['book_value_per_share']:.0f}). "
                    f"This means ROE ~ cost_of_equity - the model is saying the firm earns exactly its cost of "
                    f"capital, so it's worth its book. Not a bug; legitimate signal if ROE input is correct."
                )

        if ddm.fair_value and ri.fair_value and current_price:
            ddm_disc = 1 - ddm.fair_value / current_price
            ri_disc = 1 - ri.fair_value / current_price
            if ddm_disc > 0.5 and ri_disc > 0.5:
                verdict_lines.append(
                    f"Both models price the stock at >50% discount (DDM {ddm_disc*100:.0f}%, RI {ri_disc*100:.0f}%). "
                    f"Either the market is genuinely irrationally exuberant on {symbol}, or one of the inputs above "
                    f"is wrong. Check the snapshot capture timestamp vs the price source - stale snapshot + live price "
                    f"is the most common cause."
                )

        if not verdict_lines:
            verdict_lines.append("Nothing obviously wrong in the inputs. The numbers may simply reflect a strong overvaluation signal.")

        for line in verdict_lines:
            print(f"\n* {line}")

        print()
        return 0

    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnose DDM / RI inputs for one symbol")
    ap.add_argument("--symbol", default="MNG", help="ticker (default: MNG = Managem)")
    ap.add_argument("--scenario", default="base", choices=["bear", "base", "bull"])
    args = ap.parse_args()
    return diagnose(args.symbol.upper().strip(), args.scenario)


if __name__ == "__main__":
    sys.exit(main())
