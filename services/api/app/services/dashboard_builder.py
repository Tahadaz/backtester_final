"""Shared dashboard payload builder.

Called by both the live-compute API path (legacy/shadow mode) and the
background worker that persists snapshots to ``dashboard_snapshot``.
Keeps the aggregation logic in exactly one place.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Lookup tables (duplicated from dashboard_data.py; authoritative copy here)
# ---------------------------------------------------------------------------

HORIZON_ALIASES: dict[str, str] = {
    "short": "weekly",
    "medium": "monthly",
    "long": "quarterly",
}

HORIZONS: dict[str, str] = {
    "weekly": "Hebdomadaire",
    "monthly": "Mensuel",
    "quarterly": "Trimestriel",
}

FAMILY_SIGNAL_TYPE: dict[str, str] = {
    "sma": "trend", "ema": "trend", "ema_cross": "trend",
    "ichimoku": "trend", "psar": "trend",
    "macd": "strength", "roc": "strength", "trix": "strength",
    "adx": "strength", "tsi": "strength",
    "rsi": "oscillator", "stochastic": "oscillator", "cci": "oscillator",
    "mfi": "oscillator", "uo": "oscillator",
    "obv": "volume", "cmf": "volume", "ad": "volume",
    "vwap": "volume", "fi": "volume",
}

LEGACY_CATEGORY_FAMILIES: dict[str, list[str]] = {
    "tendance": ["sma"],
    "momentum": ["macd"],
    "oscillation": ["rsi"],
    "volume": ["obv"],
}
EXPANDED_CATEGORY_FAMILIES: dict[str, list[str]] = {
    "tendance": ["sma", "ema", "ema_cross", "ichimoku", "psar"],
    "momentum": ["macd", "roc", "trix", "adx", "tsi"],
    "oscillation": ["rsi", "stochastic", "cci", "mfi", "uo"],
    "volume": ["obv", "cmf", "ad", "vwap", "fi"],
}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _round(val: Any) -> Any:
    if val is None:
        return None
    try:
        if math.isnan(val):
            return None
        return round(float(val), 2)
    except Exception:
        return val


def _score_to_label(score_pct: float | None) -> str:
    if score_pct is None:
        return "Indisponible"
    if score_pct >= 66.6:
        return "Achat"
    if score_pct <= 33.3:
        return "Vente"
    return "Neutre"


def _signal_type_label(signal_type: str, score_pct: float) -> str:
    if signal_type == "trend":
        if score_pct >= 66.6: return "Hausse"
        if score_pct <= 33.3: return "Baisse"
        return "Neutre"
    if signal_type == "strength":
        if score_pct >= 66.6: return "Fort"
        if score_pct <= 33.3: return "Faible"
        return "Neutre"
    if signal_type == "oscillator":
        if score_pct >= 66.6: return "Surachat"
        if score_pct <= 33.3: return "Survente"
        return "Neutre"
    if signal_type == "volume":
        if score_pct >= 66.6: return "Accumulation"
        if score_pct <= 33.3: return "Distribution"
        return "Neutre"
    return "Neutre"


def _avg_cats(
    cat_dict: dict[str, list[float]],
    family_map: dict[str, list[str]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for cat, vals in cat_dict.items():
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        sig = FAMILY_SIGNAL_TYPE.get(family_map[cat][0], "trend")
        out[cat] = {"score_pct": _round(avg), "label": _signal_type_label(sig, avg)}
    return out


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_dashboard_payload(db: Session, horizon: str) -> dict[str, Any]:
    """Compute the full dashboard payload for *horizon* using *db*.

    ``horizon`` must already be normalized (weekly/monthly/quarterly).
    This is the single source of truth for dashboard aggregation; both the
    live-compute API path and the snapshot worker call this function.
    """
    from ..models import StockMaster

    stocks_info = db.query(StockMaster).filter_by(is_active=True).all()
    stock_dict = {s.symbol: s for s in stocks_info}

    se_rows = db.execute(
        text("""
        SELECT symbol, aggregate_score_pct, expanded_aggregate_score_pct, signal_label,
               per_family_json, technical_levels_json, support_resistance_json
        FROM signal_engine_global_result
        WHERE horizon = :horizon AND variant = 'expanded' AND status = 'succeeded'
        """),
        {"horizon": horizon},
    ).fetchall()
    se_by_symbol = {row[0]: row for row in se_rows}

    wfo_rows = db.execute(
        text("""
        SELECT symbol, status, global_score_pct, signal_label,
               weight_tendance, weight_momentum, weight_oscillation, weight_volume,
               sr_support_level, sr_resistance_level,
               sr_support_method, sr_resistance_method,
               best_category, consensus_wfe_pct, consensus_robustness
        FROM wfo_global_signal
        WHERE horizon = :horizon AND variant = 'expanded'
        """),
        {"horizon": horizon},
    ).fetchall()
    wfo_global_by_symbol = {row[0]: row for row in wfo_rows}

    wfo_summary_rows = db.execute(
        text("""
        SELECT symbol, category, score_pct, signal_label
        FROM wfo_signal_summary
        WHERE horizon = :horizon AND variant = 'expanded' AND status = 'succeeded'
        """),
        {"horizon": horizon},
    ).fetchall()
    wfo_summary_by_symbol: dict[str, dict[str, Any]] = {}
    for row in wfo_summary_rows:
        sym, cat, score, label = row
        wfo_summary_by_symbol.setdefault(sym, {})[cat] = {
            "score_pct": _round(score), "label": label
        }

    stocks_out: list[dict[str, Any]] = []

    for symbol, stock in stock_dict.items():
        if not stock.sector:
            continue

        se_row = se_by_symbol.get(symbol)
        se_scores_obj: dict[str, Any] = {
            "variant": "expanded",
            "aggregate_score_pct": None,
            "aggregate_signal_label": "Indisponible",
            "expanded_aggregate_score_pct": None,
            "expanded_aggregate_signal_label": "Indisponible",
            "per_family": {},
            "expanded_per_family": {},
            "technical_levels": None,
            "support_resistance": None,
        }

        if se_row:
            se_scores_obj["aggregate_score_pct"] = _round(se_row[1])
            se_scores_obj["expanded_aggregate_score_pct"] = _round(se_row[2])
            se_scores_obj["aggregate_signal_label"] = se_row[3] or "Indisponible"
            se_scores_obj["expanded_aggregate_signal_label"] = _score_to_label(se_row[2])

            per_family_json: dict[str, Any] = se_row[4] or {}

            per_family: dict[str, Any] = {}
            for cat, fams in LEGACY_CATEGORY_FAMILIES.items():
                scores = [
                    per_family_json[f]["family_score_pct"]
                    for f in fams
                    if f in per_family_json and per_family_json[f].get("family_score_pct") is not None
                ]
                if scores:
                    avg = sum(scores) / len(scores)
                    sig = FAMILY_SIGNAL_TYPE.get(fams[0], "trend")
                    per_family[cat] = {"score_pct": _round(avg), "label": _signal_type_label(sig, avg)}
            se_scores_obj["per_family"] = per_family

            exp_per_family: dict[str, Any] = {}
            for cat, fams in EXPANDED_CATEGORY_FAMILIES.items():
                scores = [
                    per_family_json[f]["family_score_pct"]
                    for f in fams
                    if f in per_family_json and per_family_json[f].get("family_score_pct") is not None
                ]
                if scores:
                    avg = sum(scores) / len(scores)
                    sig = FAMILY_SIGNAL_TYPE.get(fams[0], "trend")
                    exp_per_family[cat] = {"score_pct": _round(avg), "label": _signal_type_label(sig, avg)}
            se_scores_obj["expanded_per_family"] = exp_per_family
            se_scores_obj["technical_levels"] = se_row[5]
            se_scores_obj["support_resistance"] = se_row[6]

        wfo_row = wfo_global_by_symbol.get(symbol)
        wfo_scores_obj: dict[str, Any] | None = None
        if wfo_row and wfo_row[1] == "succeeded":
            w_cat = wfo_summary_by_symbol.get(symbol, {})
            per_fam = {c: w_cat[c] for c in EXPANDED_CATEGORY_FAMILIES if c in w_cat}
            wfo_scores_obj = {
                "variant": "expanded",
                "aggregate_score_pct": _round(wfo_row[2]),
                "aggregate_signal_label": wfo_row[3],
                "per_family": per_fam,
                "best_category": wfo_row[12],
                "consensus_wfe_pct": _round(wfo_row[13]),
                "consensus_robustness": _round(wfo_row[14]),
                "status": "succeeded",
                "technical_levels": {
                    "support_buy_trigger": _round(wfo_row[8]),
                    "resistance_sell_trigger": _round(wfo_row[9]),
                    "support_reference": _round(wfo_row[8]),
                    "support_method": wfo_row[10] or "",
                    "resistance_method": wfo_row[11] or "",
                    "method": "wfo_sr",
                },
            }

        stock_obj: dict[str, Any] = {
            "symbol": symbol,
            "display_name": stock.display_name,
            "sector": stock.sector,
            "asset_type": stock.asset_type,
            "market_region": stock.market_region,
            "adv": None,
            "scores": {"signal_engine": se_scores_obj, "wfo": wfo_scores_obj},
            # flat backwards-compat fields
            "aggregate_score_pct": se_scores_obj["aggregate_score_pct"],
            "aggregate_signal_label": se_scores_obj["aggregate_signal_label"],
            "expanded_aggregate_score_pct": se_scores_obj["expanded_aggregate_score_pct"],
            "expanded_aggregate_signal_label": se_scores_obj["expanded_aggregate_signal_label"],
            "per_family": se_scores_obj["per_family"],
            "expanded_per_family": se_scores_obj["expanded_per_family"],
        }
        stocks_out.append(stock_obj)

    # ------------------------------------------------------------------
    # Sector aggregation
    # ------------------------------------------------------------------
    by_sector: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in stocks_out:
        by_sector[s["sector"]].append(s)

    sectors_out: list[dict[str, Any]] = []
    for sector_name, sector_stocks in sorted(by_sector.items()):
        se_aggs: list[float] = []
        se_exp_aggs: list[float] = []
        wfo_aggs: list[float] = []
        se_cats: dict[str, list[float]] = defaultdict(list)
        se_exp_cats: dict[str, list[float]] = defaultdict(list)
        wfo_cats: dict[str, list[float]] = defaultdict(list)

        for st in sector_stocks:
            se = st["scores"]["signal_engine"]
            if se["aggregate_score_pct"] is not None:
                se_aggs.append(se["aggregate_score_pct"])
            if se.get("expanded_aggregate_score_pct") is not None:
                se_exp_aggs.append(se["expanded_aggregate_score_pct"])
            for c, d in se.get("per_family", {}).items():
                se_cats[c].append(d["score_pct"])
            for c, d in se.get("expanded_per_family", {}).items():
                se_exp_cats[c].append(d["score_pct"])
            wfo = st["scores"].get("wfo")
            if wfo:
                if wfo["aggregate_score_pct"] is not None:
                    wfo_aggs.append(wfo["aggregate_score_pct"])
                for c, d in wfo.get("per_family", {}).items():
                    wfo_cats[c].append(d["score_pct"])

        se_per_fam = _avg_cats(dict(se_cats), LEGACY_CATEGORY_FAMILIES)
        se_exp_per_fam = _avg_cats(dict(se_exp_cats), EXPANDED_CATEGORY_FAMILIES)
        wfo_per_fam = _avg_cats(dict(wfo_cats), EXPANDED_CATEGORY_FAMILIES)
        se_agg_avg = sum(se_aggs) / len(se_aggs) if se_aggs else None
        se_exp_agg_avg = sum(se_exp_aggs) / len(se_exp_aggs) if se_exp_aggs else None
        wfo_agg_avg = sum(wfo_aggs) / len(wfo_aggs) if wfo_aggs else None

        se_obj: dict[str, Any] = {
            "variant": "expanded",
            "aggregate_score_pct": _round(se_agg_avg),
            "aggregate_signal_label": _score_to_label(se_agg_avg),
            "expanded_aggregate_score_pct": _round(se_exp_agg_avg),
            "expanded_aggregate_signal_label": _score_to_label(se_exp_agg_avg),
            "per_family": se_per_fam,
            "expanded_per_family": se_exp_per_fam,
        }
        wfo_obj: dict[str, Any] | None = None
        if wfo_aggs:
            wfo_obj = {
                "variant": "expanded",
                "aggregate_score_pct": _round(wfo_agg_avg),
                "aggregate_signal_label": _score_to_label(wfo_agg_avg),
                "per_family": wfo_per_fam,
            }

        sectors_out.append({
            "sector": sector_name,
            "stock_count": len(sector_stocks),
            "scores": {"signal_engine": se_obj, "wfo": wfo_obj},
            "aggregate_score_pct": se_obj["aggregate_score_pct"],
            "aggregate_signal_label": se_obj["aggregate_signal_label"],
            "expanded_aggregate_score_pct": se_obj["expanded_aggregate_score_pct"],
            "expanded_aggregate_signal_label": se_obj["expanded_aggregate_signal_label"],
            "per_family": se_per_fam,
            "expanded_per_family": se_exp_per_fam,
        })

    # ------------------------------------------------------------------
    # Index (MASI) aggregation
    # ------------------------------------------------------------------
    se_aggs = []
    se_exp_aggs = []
    wfo_aggs = []
    se_cats_idx: dict[str, list[float]] = defaultdict(list)
    se_exp_cats_idx: dict[str, list[float]] = defaultdict(list)
    wfo_cats_idx: dict[str, list[float]] = defaultdict(list)
    se_breadth: dict[str, int] = {"achat": 0, "neutre": 0, "vente": 0, "indisponible": 0}
    wfo_breadth: dict[str, int] = {"achat": 0, "neutre": 0, "vente": 0, "indisponible": 0}

    for st in stocks_out:
        se = st["scores"]["signal_engine"]
        score = se["aggregate_score_pct"]
        if score is not None:
            se_aggs.append(score)
            if score >= 66.6: se_breadth["achat"] += 1
            elif score <= 33.3: se_breadth["vente"] += 1
            else: se_breadth["neutre"] += 1
        else:
            se_breadth["indisponible"] += 1
        if se.get("expanded_aggregate_score_pct") is not None:
            se_exp_aggs.append(se["expanded_aggregate_score_pct"])
        for c, d in se.get("per_family", {}).items():
            se_cats_idx[c].append(d["score_pct"])
        for c, d in se.get("expanded_per_family", {}).items():
            se_exp_cats_idx[c].append(d["score_pct"])

        wfo = st["scores"].get("wfo")
        if wfo:
            score = wfo["aggregate_score_pct"]
            if score is not None:
                wfo_aggs.append(score)
                if score >= 66.6: wfo_breadth["achat"] += 1
                elif score <= 33.3: wfo_breadth["vente"] += 1
                else: wfo_breadth["neutre"] += 1
            else:
                wfo_breadth["indisponible"] += 1
        else:
            wfo_breadth["indisponible"] += 1

    se_per_fam_idx = _avg_cats(dict(se_cats_idx), LEGACY_CATEGORY_FAMILIES)
    se_exp_per_fam_idx = _avg_cats(dict(se_exp_cats_idx), EXPANDED_CATEGORY_FAMILIES)
    wfo_per_fam_idx = _avg_cats(dict(wfo_cats_idx), EXPANDED_CATEGORY_FAMILIES)
    se_agg_avg = sum(se_aggs) / len(se_aggs) if se_aggs else None
    se_exp_agg_avg = sum(se_exp_aggs) / len(se_exp_aggs) if se_exp_aggs else None
    wfo_agg_avg = sum(wfo_aggs) / len(wfo_aggs) if wfo_aggs else None

    se_obj_idx: dict[str, Any] = {
        "variant": "expanded",
        "aggregate_score_pct": _round(se_agg_avg),
        "aggregate_signal_label": _score_to_label(se_agg_avg),
        "expanded_aggregate_score_pct": _round(se_exp_agg_avg),
        "expanded_aggregate_signal_label": _score_to_label(se_exp_agg_avg),
        "per_family": se_per_fam_idx,
        "expanded_per_family": se_exp_per_fam_idx,
        "breadth": se_breadth,
    }
    wfo_obj_idx: dict[str, Any] | None = None
    if wfo_aggs:
        wfo_obj_idx = {
            "variant": "expanded",
            "aggregate_score_pct": _round(wfo_agg_avg),
            "aggregate_signal_label": _score_to_label(wfo_agg_avg),
            "per_family": wfo_per_fam_idx,
            "breadth": wfo_breadth,
        }

    generated_at = datetime.now(tz=timezone.utc).isoformat()

    return {
        "generated_at": generated_at,
        "horizon": horizon,
        "horizon_label": HORIZONS[horizon],
        "stocks": stocks_out,
        "sectors": sectors_out,
        "index": {
            "name": "MASI",
            "stock_count": len(stocks_out),
            "scores": {"signal_engine": se_obj_idx, "wfo": wfo_obj_idx},
            "aggregate_score_pct": se_obj_idx["aggregate_score_pct"],
            "aggregate_signal_label": se_obj_idx["aggregate_signal_label"],
            "expanded_aggregate_score_pct": se_obj_idx["expanded_aggregate_score_pct"],
            "expanded_aggregate_signal_label": se_obj_idx["expanded_aggregate_signal_label"],
            "per_family": se_per_fam_idx,
            "expanded_per_family": se_exp_per_fam_idx,
        },
        "custom_index_definitions": [],
    }


def derive_upstream_rev(db: Session, horizon: str) -> dict[str, Any]:
    """Return the upstream revision tuple consumed to build a snapshot.

    Used to populate ``dashboard_snapshot.upstream_rev`` so a CAS upsert
    can guard against stale overwrites.
    """
    data_as_of_row = db.execute(
        text("SELECT MAX(data_as_of) FROM market_data_store WHERE asset_class = 'equity'")
    ).scalar()
    engine_run_row = db.execute(
        text("""
        SELECT MAX(batch_id) FROM signal_engine_batch_job
        WHERE horizon = :horizon AND status = 'succeeded'
        """),
        {"horizon": horizon},
    ).scalar()
    wfo_run_row = db.execute(
        text("""
        SELECT MAX(id::text)
        FROM wfo_global_signal
        WHERE horizon = :horizon AND variant = 'expanded'
        """),
        {"horizon": horizon},
    ).scalar()

    return {
        "data_as_of": str(data_as_of_row) if data_as_of_row else None,
        "engine_batch_id": str(engine_run_row) if engine_run_row else None,
        "wfo_run_id": str(wfo_run_row) if wfo_run_row else None,
    }
