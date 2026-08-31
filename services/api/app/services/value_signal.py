"""Canonical B/M + Cash-Flow Value (CF/P) cross-section — the production entrypoint for the
validated, repaired-data value signal (research-out/data-quality-forensic-repair/2026-07-06,
research-out/live-like-value-strategy/2026-07-06).

This reuses the canonical eligibility logic (`eligibility_mask`, `TRUSTED_UNIVERSE_EXCLUSIONS`)
directly from `core/quant_core/fundamentals/cross_section/live_like_strategy.py` -- the single
source of truth for the trusted-universe policy. `METRIC_ALIASES`/`_metric`/`_finite`/
`_ratio_or_none` below are deliberately LOCAL COPIES of the same-named helpers in
`methodology_bakeoff.py`/`characteristic_study.py`, NOT imports -- those modules pull in
`statsmodels` (needed for their own beta/momentum regressions, unrelated to B/M or CF/P), which
is not installed in the lightweight API container (services/api/pyproject.toml has no
statsmodels; only the worker's requirements-dev.txt does -- confirmed by a real container
crash-loop during 2026-07-06 operational hardening). Importing the full research module here
would break API startup. `core/tests/test_value_signal_parity.py` asserts byte-for-byte
behavioral parity with the canonical originals so this copy cannot silently drift.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from core.quant_core.fundamentals.cross_section.live_like_strategy import (
    TRUSTED_UNIVERSE_EXCLUSIONS,
    eligibility_mask,
)
from core.quant_core.fundamentals.cross_section.panel import PanelConfig, build_pit_panel, load_universe, publication_coverage_stats
from core.quant_core.fundamentals.cross_section.market_equity import decision_date_market_equity

METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "book_equity": ("Total_Equity", "Shareholders_Equity", "Clean_Capitaux_propres", "Capitaux_propres", "Common_Equity"),
    "cash_flow_ops": ("Operating_Cash_Flow", "Cash_Flow_Operations", "CFO"),
}


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _metric(metrics: dict[str, Any], *names: str) -> float | None:
    for name in names:
        val = _finite(metrics.get(name))
        if val is not None:
            return val
    return None


def _metric_with_name(metrics: dict[str, Any], *names: str) -> tuple[str | None, float | None]:
    for name in names:
        value = _finite(metrics.get(name))
        if value is not None:
            return name, value
    return None, None


def _serialized_provenance(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    availability_date = item.get("availability_date")
    return {
        "statement_year": item.get("statement_year"),
        "availability_date": availability_date.isoformat() if hasattr(availability_date, "isoformat") else availability_date,
        "availability_kind": item.get("availability_kind"),
        "source_document_id": item.get("source_document_id"),
    }


def _ratio_or_none(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den <= 0:
        return None
    out = num / den
    return out if math.isfinite(out) else None

from .fundamental_cross_section import _load_fundamental_rows, _price_loader

VALUE_SIGNAL_METHODOLOGY_VERSION = "structural_value_bm_v2_2026_08_30"


def _sah_exclusion_reason() -> str:
    return (
        "SAH excluded from the trusted universe: workbook-sourced market cap confirmed wrong "
        "by a persistent ~29.3x factor 2021-2024, root cause not proven (see "
        "research-out/data-quality-forensic-repair/2026-07-06/known_cases_reb_sah_sbm.md)."
    )


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _exclusion_reasons(row: pd.Series) -> list[str]:
    reasons: list[str] = []
    symbol = str(row.get("symbol") or "")
    if symbol in TRUSTED_UNIVERSE_EXCLUSIONS:
        reasons.append(_sah_exclusion_reason())
    if _is_missing(row.get("close")):
        reasons.append("No PIT-available price at this date.")
    if _is_missing(row.get("market_cap_raw")):
        reasons.append("No decision-date market equity: verified PIT shares or the decision-date close is missing.")
    if not row.get("eligible_bm", False) and _is_missing(row.get("book_to_market_raw")):
        book = row.get("_book_equity")
        if not _is_missing(book) and book <= 0:
            reasons.append("Negative book equity: excluded from B/M by canonical policy (not signed), see bm_canonical_definition.md.")
        else:
            reasons.append("No PIT-available book equity for B/M.")
    if not row.get("eligible_cfp", False) and _is_missing(row.get("cashflow_price_raw")):
        if row.get("is_financial"):
            reasons.append("CF/P not applicable: bank/insurance sector excluded by canonical policy, see cfp_canonical_definition.md.")
        else:
            reasons.append("No PIT-available operating cash flow for CF/P.")
    return reasons


def compute_value_signal_frame(db: Session, *, as_of_date: dt.date | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    date = as_of_date or dt.date.today()
    annual, period, consensus, sectors = _load_fundamental_rows(db)
    load_price, _price_cache = _price_loader(db)
    panel = build_pit_panel(
        annual_rows=annual,
        period_rows=period,
        consensus_rows=consensus,
        price_loader=load_price,
        universe_df=load_universe(),
        config=PanelConfig(as_of_dates=(date,), require_observed_publication_date=True),
        sectors=sectors,
    )
    meta: dict[str, Any] = {
        "as_of_date": date.isoformat(),
        "methodology_version": VALUE_SIGNAL_METHODOLOGY_VERSION,
        "rows": int(len(panel)),
        "publication_coverage": publication_coverage_stats(panel),
        "market_equity_formula": "decision_date_close_x_pit_shares",
    }
    if panel.empty:
        return panel, meta

    computed: list[dict[str, Any]] = []
    for idx, row in panel.iterrows():
        metrics = dict(row["metrics"])
        provenance = dict(row.get("metric_provenance") or {})
        close = _finite(row.get("close"))
        shares_name, shares = _metric_with_name(metrics, "Shares_Outstanding")
        mcap = decision_date_market_equity(close=close, shares_outstanding=shares)
        book_name, book = _metric_with_name(metrics, *METRIC_ALIASES["book_equity"])
        cfo = _metric(metrics, *METRIC_ALIASES["cash_flow_ops"])
        is_financial = bool(row.get("is_financial", False))
        computed.append(
            {
                "_idx": idx,
                "market_cap_raw": mcap,
                "_book_equity": book,
                "_cfo": cfo,
                "_shares_outstanding": shares,
                "_decision_close": close,
                "_book_equity_provenance": _serialized_provenance(provenance.get(book_name)) if book_name else None,
                "_shares_provenance": _serialized_provenance(provenance.get(shares_name)) if shares_name else None,
                # Canonical B/M policy (bm_canonical_definition.md): exclude negative book equity.
                "book_to_market_raw": _ratio_or_none(book, mcap) if book is not None and book > 0 else None,
                # Canonical CF/P policy (cfp_canonical_definition.md): exclude financial-sector issuers.
                "cashflow_price_raw": _ratio_or_none(cfo, mcap) if not is_financial else None,
            }
        )
    raw = pd.DataFrame(computed).set_index("_idx")
    panel = panel.join(raw)
    panel = eligibility_mask(panel)

    panel["bm_percentile"] = None
    panel["cfp_percentile"] = None
    panel["bm_rank"] = None
    panel["cfp_rank"] = None
    bm_valid = panel[panel["eligible_bm"]]
    if not bm_valid.empty:
        panel.loc[bm_valid.index, "bm_percentile"] = bm_valid["book_to_market_raw"].rank(pct=True)
        panel.loc[bm_valid.index, "bm_rank"] = bm_valid["book_to_market_raw"].rank(ascending=False, method="min").astype(int)
    cfp_valid = panel[panel["eligible_cfp"]]
    if not cfp_valid.empty:
        panel.loc[cfp_valid.index, "cfp_percentile"] = cfp_valid["cashflow_price_raw"].rank(pct=True)
        panel.loc[cfp_valid.index, "cfp_rank"] = cfp_valid["cashflow_price_raw"].rank(ascending=False, method="min").astype(int)

    panel["exclusion_reasons"] = panel.apply(_exclusion_reasons, axis=1)
    meta["eligible_bm_count"] = int(panel["eligible_bm"].sum())
    meta["eligible_cfp_count"] = int(panel["eligible_cfp"].sum())
    return panel, meta


def value_signal_row_to_dict(row: pd.Series) -> dict[str, Any]:
    return {
        "symbol": str(row["symbol"]),
        "as_of_date": row["as_of_date"].isoformat() if hasattr(row["as_of_date"], "isoformat") else str(row["as_of_date"]),
        "bm_raw": _finite(row.get("book_to_market_raw")),
        "market_equity": _finite(row.get("market_cap_raw")),
        "decision_close": _finite(row.get("_decision_close")),
        "shares_outstanding": _finite(row.get("_shares_outstanding")),
        "book_equity": _finite(row.get("_book_equity")),
        "book_equity_provenance": row.get("_book_equity_provenance"),
        "shares_provenance": row.get("_shares_provenance"),
        "bm_percentile": _finite(row.get("bm_percentile")),
        "bm_rank": int(row["bm_rank"]) if pd.notna(row.get("bm_rank")) else None,
        "cfp_raw": _finite(row.get("cashflow_price_raw")),
        "cfp_percentile": _finite(row.get("cfp_percentile")),
        "cfp_rank": int(row["cfp_rank"]) if pd.notna(row.get("cfp_rank")) else None,
        "cfp_applicable": not bool(row.get("is_financial", False)),
        "eligible_bm": bool(row.get("eligible_bm", False)),
        "eligible_cfp": bool(row.get("eligible_cfp", False)),
        "eligible_universe": bool(row.get("eligible_universe", False)),
        "exclusion_reasons": list(row.get("exclusion_reasons") or []),
        "sector": row.get("sector"),
        "is_financial": bool(row.get("is_financial", False)),
        "methodology_version": VALUE_SIGNAL_METHODOLOGY_VERSION,
    }
