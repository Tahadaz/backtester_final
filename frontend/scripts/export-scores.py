"""Export signal engine scores to static JSON for the dashboard.

Usage:
    cd <repo-root>
    .venv/Scripts/python frontend/scripts/export-scores.py

Produces:
    frontend/public/data/scores-short.json
    frontend/public/data/scores-medium.json
    frontend/public/data/scores-long.json
    frontend/public/data/signals-short.json
    frontend/public/data/signals-medium.json
    frontend/public/data/signals-long.json
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from services.api.app.db import _ensure_session_factory  # noqa: E402
from services.api.app.market_data_loader import load_ohlcv_for_symbol  # noqa: E402
from services.api.app.masi_tickers import get_masi_info  # noqa: E402
from services.api.app.routers.strategy_signals import _sr_get_or_compute_variants  # noqa: E402

from core.quant_core.signal_engine.ensemble import (  # noqa: E402
    family_signal_is_available,
    run_family_ensemble_full,
    _score_to_label,
)
from core.quant_core.signal_engine.domain import (  # noqa: E402
    HORIZON_PARAMS,
    FAMILY_SIGNAL_TYPE,
    signal_type_label,
)
from core.quant_core.signal_engine.support_resistance import (  # noqa: E402
    round_number,
)
from core.quant_core.data import drop_incomplete_ohlcv_rows  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = REPO_ROOT / "frontend" / "public" / "data"
FAMILIES = ("sma", "macd", "rsi", "obv")
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
EXPANDED_FAMILIES = tuple(
    f for families in EXPANDED_CATEGORY_FAMILIES.values() for f in families
)
VOLUME_FAMILIES = frozenset(EXPANDED_CATEGORY_FAMILIES["volume"])
HORIZONS = {
    "short": "Court terme",
    "medium": "Moyen terme",
    "long": "Long terme",
}
COST_BPS = 10.0
COOLDOWN_BARS = 0
TIMEFRAME = "1D"


def _truncate_for_horizon(ohlcv, horizon: str):
    """Keep only the last N years of data for the given horizon."""
    max_bars = HORIZON_PARAMS[horizon]["max_years"] * 252
    if len(ohlcv) > max_bars:
        return ohlcv.iloc[-max_bars:]
    return ohlcv


def _clean_ohlcv(ohlcv):
    """Drop rows with NaN in any OHLCV column."""
    return drop_incomplete_ohlcv_rows(ohlcv)


def _has_valid_volume(ohlcv) -> bool:
    """Check if volume data is meaningful (>1% non-zero)."""
    if "Volume" not in ohlcv.columns:
        return False
    volume = ohlcv["Volume"].values.astype("float64")
    finite = volume[np.isfinite(volume)]
    if len(finite) == 0:
        return False
    return (finite != 0).mean() >= 0.01


def _to_json_value(value):
    """Convert numpy/scalar objects into JSON-safe native values."""
    if isinstance(value, (str, bool)) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, dict):
        return {str(k): _to_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    return str(value)


def _round_number(value, digits: int = 2):
    """Round number-like values when possible."""
    return round_number(value, digits)


def _sanitize_rep(rep: dict) -> dict:
    """Keep only public-safe representative fields."""
    return {
        "variant_id": str(rep.get("variant_id", "")),
        "signal": _round_number(rep.get("signal"), 4) or 0.0,
        "signal_label": str(rep.get("signal_label", "")),
        "reliability_weight": _round_number(rep.get("reliability_weight"), 6) or 0.0,
        "normalized_weight": _round_number(rep.get("normalized_weight"), 6) or 0.0,
        "contribution": _round_number(rep.get("contribution"), 6) or 0.0,
        "current_close": _round_number(rep.get("current_close"), 6),
        "indicator_value": _round_number(rep.get("indicator_value"), 6),
        "explanation": str(rep.get("explanation", "")),
        "description": str(rep.get("description", "")),
        "params": _to_json_value(rep.get("params", {})) or {},
        "archetype": str(rep.get("archetype", "")),
        "selection_status": str(rep.get("selection_status", "")),
    }


def _sanitize_sr_used_method(method: dict) -> dict:
    """Serialize one selected SR method for public static JSON."""
    return {
        "id": str(method.get("id") or ""),
        "label": str(method.get("label") or ""),
        "support": _round_number(method.get("support"), 6),
        "resistance": _round_number(method.get("resistance"), 6),
        "status": str(method.get("status") or ""),
        "selected_for_support": bool(method.get("selected_for_support")),
        "selected_for_resistance": bool(method.get("selected_for_resistance")),
        "explanation": str(method.get("explanation") or ""),
    }


def _compute_support_resistance_snapshot(
    db,
    symbol: str,
    horizon: str,
    *,
    fallback_close: float | None,
    fallback_as_of: str,
) -> tuple[dict, dict]:
    """Compute S/R from the final optimal variant grid.

    Uses _sr_get_or_compute_variants (full variant ranking) so that exported
    levels always reflect the best S/R pair, not the simpler preview/summary path.

    Returns:
      (technical_levels_compat, support_resistance_compact)
    """
    warning_message = ""
    response: dict = {}
    try:
        payload = _sr_get_or_compute_variants(
            db,
            symbol=symbol,
            horizon=horizon,
            timeframe=TIMEFRAME,
            cost_bps=COST_BPS,
            cooldown_bars=COOLDOWN_BARS,
        )
        response = payload["response"]
    except Exception as exc:
        warning_message = f"SR variants failed: {exc}"
        logger.debug("  %s/%s: support-resistance variants failed (%s)", symbol, horizon, exc)

    # Extract top-level fields from variants response.
    final_support_raw = response.get("final_support")
    final_resistance_raw = response.get("final_resistance")
    selected_support_method_id = response.get("selected_support_method_id")
    selected_resistance_method_id = response.get("selected_resistance_method_id")
    optimal_status = response.get("optimal_status", "unavailable")

    # When no viable optimal pair exists, export null levels with a clear message
    # rather than silently falling back to preview/cache levels.
    if optimal_status != "ready" or final_support_raw is None or final_resistance_raw is None:
        if not warning_message:
            warning_message = "Aucun couple S/R optimal disponible."
        final_support = None
        final_resistance = None
        selected_support_method_id = None
        selected_resistance_method_id = None
    else:
        final_support = _round_number(final_support_raw, 6)
        final_resistance = _round_number(final_resistance_raw, 6)

    support_method_id = str(selected_support_method_id) if selected_support_method_id else None
    resistance_method_id = str(selected_resistance_method_id) if selected_resistance_method_id else None
    current_close = _round_number(response.get("current_close") or fallback_close, 6)
    as_of = str(response.get("as_of") or fallback_as_of)

    # The variants response already sets selected_for_support / selected_for_resistance
    # on each method entry, so we can reuse _sanitize_sr_used_method directly.
    methods_raw = response.get("methods") or []
    methods_by_id = {
        str(m.get("id")): m
        for m in methods_raw
        if isinstance(m, dict) and m.get("id")
    }
    used_methods = [
        _sanitize_sr_used_method(m)
        for m in methods_raw
        if isinstance(m, dict)
        and (bool(m.get("selected_for_support")) or bool(m.get("selected_for_resistance")))
    ]

    used_variant = None
    if support_method_id and resistance_method_id:
        support_label = str(methods_by_id.get(support_method_id, {}).get("label") or support_method_id)
        resistance_label = str(methods_by_id.get(resistance_method_id, {}).get("label") or resistance_method_id)
        used_variant = {
            "variant_id": f"sr:{support_method_id}__{resistance_method_id}",
            "support_method_id": support_method_id,
            "resistance_method_id": resistance_method_id,
            "description": f"Support {support_label} / Resistance {resistance_label}",
        }

    summary_explanation = str(
        response.get("score_explanation") or "Support/resistance indisponible pour ce symbole."
    )

    technical_levels = {
        "close_used": current_close,
        "support_buy_trigger": final_support,
        "resistance_sell_trigger": final_resistance,
        # Keep compatibility with existing dashboard display fallback.
        "support_reference": final_support,
        "method": "sr_multi_method_v1",
        "selected_support_method_id": support_method_id,
        "selected_resistance_method_id": resistance_method_id,
    }
    support_resistance = {
        "final_support": final_support,
        "final_resistance": final_resistance,
        "selected_support_method_id": support_method_id,
        "selected_resistance_method_id": resistance_method_id,
        "summary_explanation": summary_explanation,
        "trend_score_pct": _round_number(response.get("trend_score_pct"), 2),
        "trend_label": str(response.get("trend_label") or ""),
        "as_of": as_of,
        "used_methods": used_methods,
        "used_variant": used_variant,
        "warning_message": warning_message,
    }
    return technical_levels, support_resistance


def load_wfo_data(db, horizon: str) -> dict[str, dict]:
    """Bulk-load WFO signal data for all symbols at a given horizon.

    Returns a dict keyed by symbol:
      { "global": {...} | None, "categories": { category: {...}, ... } }
    """
    from sqlalchemy import text

    global_rows = db.execute(
        text(
            """
            SELECT symbol, status, global_score_pct, signal_label,
                   weight_tendance, weight_momentum, weight_oscillation, weight_volume,
                   sr_support_level, sr_resistance_level,
                   sr_support_method, sr_resistance_method,
                   best_category, consensus_wfe_pct, consensus_robustness
            FROM wfo_global_signal
            WHERE horizon = :horizon AND variant = 'expanded'
            """
        ),
        {"horizon": horizon},
    ).fetchall()

    summary_rows = db.execute(
        text(
            """
            SELECT symbol, category, score_pct, signal_label
            FROM wfo_signal_summary
            WHERE horizon = :horizon AND variant = 'expanded' AND status = 'succeeded'
            """
        ),
        {"horizon": horizon},
    ).fetchall()

    by_symbol: dict[str, dict] = {}

    for row in global_rows:
        symbol = row[0]
        by_symbol[symbol] = {
            "global": {
                "status": str(row[1] or ""),
                "global_score_pct": row[2],
                "signal_label": str(row[3] or ""),
                "weight_tendance": row[4],
                "weight_momentum": row[5],
                "weight_oscillation": row[6],
                "weight_volume": row[7],
                "sr_support_level": row[8],
                "sr_resistance_level": row[9],
                "sr_support_method": str(row[10] or ""),
                "sr_resistance_method": str(row[11] or ""),
                "best_category": str(row[12] or ""),
                "consensus_wfe_pct": row[13],
                "consensus_robustness": row[14],
            },
            "categories": {},
        }

    for row in summary_rows:
        symbol, category, score_pct, signal_label = row[0], row[1], row[2], row[3]
        if symbol not in by_symbol:
            by_symbol[symbol] = {"global": None, "categories": {}}
        if score_pct is not None:
            by_symbol[symbol]["categories"][category] = {
                "score_pct": round(float(score_pct), 2),
                "label": str(signal_label or ""),
            }

    return by_symbol


def _build_wfo_scores(wfo_data: dict | None) -> dict | None:
    """Build the wfo score subobject from loaded DB data.

    Returns None when the row is missing, pending, or failed.
    """
    if wfo_data is None:
        return None

    global_row = wfo_data.get("global")
    if global_row is None or global_row.get("status") != "succeeded":
        return None

    per_family: dict[str, dict] = {}
    for category, cat_data in wfo_data.get("categories", {}).items():
        per_family[category] = {
            "score_pct": cat_data["score_pct"],
            "label": cat_data["label"],
        }

    sr_support = global_row.get("sr_support_level")
    sr_resistance = global_row.get("sr_resistance_level")
    technical_levels = {
        "support_buy_trigger": _round_number(sr_support, 6),
        "resistance_sell_trigger": _round_number(sr_resistance, 6),
        "support_reference": _round_number(sr_support, 6),
        "support_method": global_row.get("sr_support_method") or "",
        "resistance_method": global_row.get("sr_resistance_method") or "",
        "method": "wfo_sr",
    }

    global_score = global_row.get("global_score_pct")
    return {
        "variant": "expanded",
        "aggregate_score_pct": _round_number(global_score, 2) if global_score is not None else None,
        "aggregate_signal_label": global_row.get("signal_label") or "",
        "per_family": per_family,
        "technical_levels": technical_levels,
        "best_category": global_row.get("best_category") or "",
        "consensus_wfe_pct": _round_number(global_row.get("consensus_wfe_pct"), 2),
        "consensus_robustness": _round_number(global_row.get("consensus_robustness"), 4),
        "status": "succeeded",
    }


def _build_family_snapshot(family: str, signal) -> dict:
    """Serialize family signal detail for public static signals page."""
    representatives = [
        _sanitize_rep(rep)
        for rep in (signal.representatives or [])
        if isinstance(rep, dict)
    ]
    fallback_variants = [
        _sanitize_rep(rep)
        for rep in (signal.fallback_variants or [])
        if isinstance(rep, dict)
    ]
    return {
        "family": family,
        "family_score_pct": round(float(signal.family_score_pct), 2),
        "family_signal_label": str(signal.family_signal_label),
        "tested_count": int(signal.tested_count),
        "viable_count": int(signal.viable_count),
        "competitive_count": int(signal.competitive_count),
        "representative_count": int(signal.representative_count),
        "score_explanation": str(signal.score_explanation),
        "representatives": representatives,
        "fallback_variants": fallback_variants,
        "as_of": str(signal.as_of),
        "latest_close": _round_number(signal.latest_close, 6),
        "is_provisional": bool(signal.is_provisional),
        "warning_message": str(signal.warning_message or ""),
    }


def _load_family_results_from_db(db, symbol: str, horizon: str) -> dict[str, dict] | None:
    """Load persisted signal engine family results from DB.

    Returns a dict keyed by family name, or None if no rows exist yet.
    Each value contains family_detail_json (for JSON export) and metadata.
    """
    try:
        from sqlalchemy import text
        rows = db.execute(
            text(
                """
                SELECT family, status, family_score_pct, signal_label,
                       family_detail_json, is_provisional, data_as_of
                FROM signal_engine_family_result
                WHERE symbol = :symbol AND horizon = :horizon AND variant = 'expanded'
                  AND status IN ('succeeded', 'no_signal')
                """
            ),
            {"symbol": symbol, "horizon": horizon},
        ).fetchall()
    except Exception as exc:
        logger.debug("  %s/%s: DB family result load failed (%s)", symbol, horizon, exc)
        return None

    if not rows:
        return None

    result: dict[str, dict] = {}
    for row in rows:
        family, status, score_pct, signal_label, detail_json, is_provisional, data_as_of = row
        result[family] = {
            "status": status,
            "family_score_pct": score_pct,
            "signal_label": signal_label,
            "family_detail_json": detail_json,
            "is_provisional": bool(is_provisional),
            "data_as_of": data_as_of,
        }
    return result


def _check_db_results_fresh(db_family_results: dict[str, dict], ohlcv_data_as_of) -> bool:
    """Return True if all DB results match the current OHLCV data_as_of date."""
    if not db_family_results:
        return False
    ohlcv_str = str(ohlcv_data_as_of)[:10]
    for fr in db_family_results.values():
        row_as_of = fr.get("data_as_of")
        if row_as_of is None or str(row_as_of)[:10] != ohlcv_str:
            return False
    return True


def compute_symbol_scores(db, symbol: str, horizon: str) -> dict | None:
    """Compute all family scores for one symbol at one horizon.

    Strategy:
    1. Load OHLCV (needed for adv + S/R computation).
    2. Try reading persisted signal_engine_family_result rows from DB.
    3. If DB rows are present AND fresh (data_as_of matches): use family_detail_json
       directly (fast path — no A→G pipeline rerun).
    4. If DB rows are missing or stale: fall back to live run_family_ensemble_full
       (current behavior) and log a warning.
    """
    try:
        ohlcv = load_ohlcv_for_symbol(db, symbol, TIMEFRAME)
    except Exception as exc:
        logger.debug("  %s: no OHLCV data (%s)", symbol, exc)
        return None

    ohlcv = _truncate_for_horizon(ohlcv, horizon)
    ohlcv = _clean_ohlcv(ohlcv)

    if len(ohlcv) < 50:
        logger.debug("  %s: insufficient data (%d bars)", symbol, len(ohlcv))
        return None

    close = ohlcv["Close"].values.astype("float64")
    high = ohlcv["High"].values.astype("float64") if "High" in ohlcv.columns else None
    low = ohlcv["Low"].values.astype("float64") if "Low" in ohlcv.columns else None
    volume = ohlcv["Volume"].values.astype("float64") if "Volume" in ohlcv.columns else None

    if volume is not None:
        recent_close = close[-20:]
        recent_volume = volume[-20:]
        finite_adv = np.isfinite(recent_close) & np.isfinite(recent_volume)
        adv_values = recent_close[finite_adv] * recent_volume[finite_adv]
        adv = float(np.mean(adv_values)) if len(adv_values) > 0 else None
    else:
        adv = None

    ohlcv_data_as_of = ohlcv.index[-1].date() if len(ohlcv) > 0 else None
    has_volume = _has_valid_volume(ohlcv)

    family_scores: dict[str, float] = {}
    family_labels: dict[str, str] = {}
    family_snapshots: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Fast path: read from DB if rows are present and fresh
    # ------------------------------------------------------------------
    db_results = _load_family_results_from_db(db, symbol, horizon)
    use_db = db_results is not None and _check_db_results_fresh(db_results, ohlcv_data_as_of)

    if use_db:
        logger.debug("  %s/%s: using DB-cached signal engine results", symbol, horizon)
        for family, fr in db_results.items():
            if fr.get("status") != "succeeded":
                continue
            detail_json = fr.get("family_detail_json")
            if detail_json and isinstance(detail_json, dict):
                family_snapshots[family] = detail_json
            score = fr.get("family_score_pct")
            if score is not None and not fr.get("is_provisional"):
                family_scores[family] = float(score)
                family_labels[family] = str(fr.get("signal_label") or "")
    else:
        # ------------------------------------------------------------------
        # Fallback: live computation (original behavior)
        # ------------------------------------------------------------------
        if db_results is not None:
            logger.warning(
                "  %s/%s: DB results stale (data_as_of mismatch), falling back to live compute",
                symbol, horizon,
            )
        else:
            logger.debug("  %s/%s: no DB results, using live compute", symbol, horizon)

        for family in EXPANDED_FAMILIES:
            try:
                if family in VOLUME_FAMILIES and not has_volume:
                    continue

                detail = run_family_ensemble_full(
                    family,
                    close,
                    volume=volume,
                    high=high,
                    low=low,
                    symbol=symbol,
                    horizon=horizon,
                    timeframe=TIMEFRAME,
                    cost_bps=COST_BPS,
                    cooldown_bars=COOLDOWN_BARS,
                )
                family_signal = detail.signal
                family_snapshots[family] = _build_family_snapshot(family, family_signal)
                if not family_signal_is_available(family_signal):
                    continue
                family_scores[family] = family_signal.family_score_pct
                family_labels[family] = family_signal.family_signal_label
            except Exception as exc:
                logger.debug("  %s/%s: failed (%s)", symbol, family, exc)
                continue

    if not family_scores and not family_snapshots:
        return None

    # per_family keyed by category name (legacy: 1 family per category)
    per_family = {}
    for category_name, category_families in LEGACY_CATEGORY_FAMILIES.items():
        category_scores = [family_scores[f] for f in category_families if f in family_scores]
        if category_scores:
            category_avg = sum(category_scores) / len(category_scores)
            signal_type = FAMILY_SIGNAL_TYPE.get(category_families[0], "trend")
            per_family[category_name] = {
                "score_pct": round(category_avg, 2),
                "label": signal_type_label(signal_type, category_avg),
            }

    # expanded_per_family keyed by category name (expanded: up to 5 families per category)
    expanded_per_family = {}
    for category_name, category_families in EXPANDED_CATEGORY_FAMILIES.items():
        cat_scores = [family_scores[f] for f in category_families if f in family_scores]
        if cat_scores:
            category_avg = sum(cat_scores) / len(cat_scores)
            signal_type = FAMILY_SIGNAL_TYPE.get(category_families[0], "trend")
            expanded_per_family[category_name] = {
                "score_pct": round(category_avg, 2),
                "label": signal_type_label(signal_type, category_avg),
            }

    # Legacy aggregate: avg of category scores where each category has 1 family
    categories = {}
    for category_name, category_families in LEGACY_CATEGORY_FAMILIES.items():
        category_scores = [family_scores[f] for f in category_families if f in family_scores]
        if category_scores:
            category_avg = sum(category_scores) / len(category_scores)
            signal_type = FAMILY_SIGNAL_TYPE.get(category_families[0], "trend")
            categories[category_name] = {
                "score_pct": round(category_avg, 2),
                "label": signal_type_label(signal_type, category_avg),
                "families": category_families,
            }

    legacy_category_avgs = [v["score_pct"] for v in categories.values()]
    aggregate = sum(legacy_category_avgs) / len(legacy_category_avgs) if legacy_category_avgs else None

    # Expanded aggregate: same structure, each category now has up to 5 families
    expanded_category_avgs = []
    for category_name, category_families in EXPANDED_CATEGORY_FAMILIES.items():
        cat_scores = [family_scores[f] for f in category_families if f in family_scores]
        if cat_scores:
            expanded_category_avgs.append(sum(cat_scores) / len(cat_scores))

    expanded_aggregate = sum(expanded_category_avgs) / len(expanded_category_avgs) if expanded_category_avgs else None
    technical_levels, support_resistance = _compute_support_resistance_snapshot(
        db,
        symbol,
        horizon,
        fallback_close=float(close[-1]) if len(close) > 0 else None,
        fallback_as_of=str(ohlcv.index[-1])[:10],
    )

    se_scores = {
        "variant": "expanded",
        "aggregate_score_pct": round(aggregate, 2) if aggregate is not None else None,
        "aggregate_signal_label": _score_to_label(aggregate) if aggregate is not None else None,
        "expanded_aggregate_score_pct": round(expanded_aggregate, 2) if expanded_aggregate is not None else None,
        "expanded_aggregate_signal_label": _score_to_label(expanded_aggregate) if expanded_aggregate is not None else None,
        "per_family": per_family,
        "expanded_per_family": expanded_per_family,
        "categories": categories,
        "families": family_snapshots,
        "technical_levels": technical_levels,
        "support_resistance": support_resistance,
    }

    return {
        "adv": round(adv, 2) if adv is not None else None,
        # Nested shape (Phase 1); wfo filled in by main() after load_wfo_data()
        "scores": {
            "signal_engine": se_scores,
            "wfo": None,
        },
        # Backward-compat flat fields kept until Phase 2 updates the TypeScript layer
        "per_family": per_family,
        "expanded_per_family": expanded_per_family,
        "categories": categories,
        "aggregate_score_pct": se_scores["aggregate_score_pct"],
        "aggregate_signal_label": se_scores["aggregate_signal_label"],
        "expanded_aggregate_score_pct": se_scores["expanded_aggregate_score_pct"],
        "expanded_aggregate_signal_label": se_scores["expanded_aggregate_signal_label"],
        "families": family_snapshots,
        "technical_levels": technical_levels,
        "support_resistance": support_resistance,
    }


def aggregate_sectors(stocks: list[dict]) -> list[dict]:
    """Group stocks by sector and compute average scores."""
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for stock in stocks:
        sector = stock.get("sector") or "Autre"
        by_sector[sector].append(stock)

    sectors = []
    for sector_name, sector_stocks in sorted(by_sector.items()):
        se_category_sums: dict[str, list[float]] = defaultdict(list)
        se_expanded_sums: dict[str, list[float]] = defaultdict(list)
        se_aggregate_scores = []
        se_expanded_aggregate_scores = []

        wfo_category_sums: dict[str, list[float]] = defaultdict(list)
        wfo_aggregate_scores = []

        for stock in sector_stocks:
            se = stock["scores"]["signal_engine"]
            wfo = stock["scores"].get("wfo")

            if se["aggregate_score_pct"] is not None:
                se_aggregate_scores.append(se["aggregate_score_pct"])
            if se.get("expanded_aggregate_score_pct") is not None:
                se_expanded_aggregate_scores.append(se["expanded_aggregate_score_pct"])
            for category, category_data in se["per_family"].items():
                if category_data is not None:
                    se_category_sums[category].append(category_data["score_pct"])
            for category, category_data in se.get("expanded_per_family", {}).items():
                if category_data is not None:
                    se_expanded_sums[category].append(category_data["score_pct"])

            if wfo is not None:
                if wfo["aggregate_score_pct"] is not None:
                    wfo_aggregate_scores.append(wfo["aggregate_score_pct"])
                for category, cat_data in wfo["per_family"].items():
                    if cat_data is not None:
                        wfo_category_sums[category].append(cat_data["score_pct"])

        se_per_family = {}
        for category_name in LEGACY_CATEGORY_FAMILIES:
            scores = se_category_sums.get(category_name, [])
            if scores:
                avg_score = sum(scores) / len(scores)
                signal_type = FAMILY_SIGNAL_TYPE.get(LEGACY_CATEGORY_FAMILIES[category_name][0], "trend")
                se_per_family[category_name] = {
                    "score_pct": round(avg_score, 2),
                    "label": signal_type_label(signal_type, avg_score),
                }

        se_expanded_per_family = {}
        for category_name in EXPANDED_CATEGORY_FAMILIES:
            scores = se_expanded_sums.get(category_name, [])
            if scores:
                avg_score = sum(scores) / len(scores)
                signal_type = FAMILY_SIGNAL_TYPE.get(EXPANDED_CATEGORY_FAMILIES[category_name][0], "trend")
                se_expanded_per_family[category_name] = {
                    "score_pct": round(avg_score, 2),
                    "label": signal_type_label(signal_type, avg_score),
                }

        se_aggregate = sum(se_aggregate_scores) / len(se_aggregate_scores) if se_aggregate_scores else None
        se_expanded_aggregate = (
            sum(se_expanded_aggregate_scores) / len(se_expanded_aggregate_scores)
            if se_expanded_aggregate_scores
            else None
        )

        se_scores_obj = {
            "variant": "expanded",
            "aggregate_score_pct": round(se_aggregate, 2) if se_aggregate is not None else None,
            "aggregate_signal_label": _score_to_label(se_aggregate) if se_aggregate is not None else None,
            "expanded_aggregate_score_pct": round(se_expanded_aggregate, 2) if se_expanded_aggregate is not None else None,
            "expanded_aggregate_signal_label": _score_to_label(se_expanded_aggregate) if se_expanded_aggregate is not None else None,
            "per_family": se_per_family,
            "expanded_per_family": se_expanded_per_family,
        }

        wfo_scores_obj = None
        if wfo_aggregate_scores:
            wfo_per_family: dict[str, dict] = {}
            for category_name in EXPANDED_CATEGORY_FAMILIES:
                scores = wfo_category_sums.get(category_name, [])
                if scores:
                    avg_score = sum(scores) / len(scores)
                    signal_type = FAMILY_SIGNAL_TYPE.get(EXPANDED_CATEGORY_FAMILIES[category_name][0], "trend")
                    wfo_per_family[category_name] = {
                        "score_pct": round(avg_score, 2),
                        "label": signal_type_label(signal_type, avg_score),
                    }
            wfo_agg = sum(wfo_aggregate_scores) / len(wfo_aggregate_scores)
            wfo_scores_obj = {
                "variant": "expanded",
                "aggregate_score_pct": round(wfo_agg, 2),
                "aggregate_signal_label": _score_to_label(wfo_agg),
                "per_family": wfo_per_family,
            }

        sectors.append(
            {
                "sector": sector_name,
                "stock_count": len(sector_stocks),
                "scores": {
                    "signal_engine": se_scores_obj,
                    "wfo": wfo_scores_obj,
                },
                # Backward-compat flat fields kept until Phase 2
                "aggregate_score_pct": se_scores_obj["aggregate_score_pct"],
                "aggregate_signal_label": se_scores_obj["aggregate_signal_label"],
                "expanded_aggregate_score_pct": se_scores_obj["expanded_aggregate_score_pct"],
                "expanded_aggregate_signal_label": se_scores_obj["expanded_aggregate_signal_label"],
                "per_family": se_per_family,
                "expanded_per_family": se_expanded_per_family,
            }
        )

    return sectors


def aggregate_index(stocks: list[dict]) -> dict:
    """Compute MASI-wide aggregate scores and breadth."""
    se_category_sums: dict[str, list[float]] = defaultdict(list)
    se_expanded_sums: dict[str, list[float]] = defaultdict(list)
    se_aggregate_scores = []
    se_expanded_aggregate_scores = []
    se_count_achat = 0
    se_count_neutre = 0
    se_count_vente = 0
    se_count_indisponible = 0

    wfo_category_sums: dict[str, list[float]] = defaultdict(list)
    wfo_aggregate_scores = []
    wfo_count_achat = 0
    wfo_count_neutre = 0
    wfo_count_vente = 0
    wfo_count_indisponible = 0

    for stock in stocks:
        se = stock["scores"]["signal_engine"]
        wfo = stock["scores"].get("wfo")

        label = se.get("aggregate_signal_label")
        if label is None:
            se_count_indisponible += 1
        elif "Achat" in label:
            se_count_achat += 1
        elif "Vente" in label:
            se_count_vente += 1
        else:
            se_count_neutre += 1

        if se["aggregate_score_pct"] is not None:
            se_aggregate_scores.append(se["aggregate_score_pct"])
        if se.get("expanded_aggregate_score_pct") is not None:
            se_expanded_aggregate_scores.append(se["expanded_aggregate_score_pct"])

        for category, category_data in se["per_family"].items():
            if category_data is not None:
                se_category_sums[category].append(category_data["score_pct"])
        for category, category_data in se.get("expanded_per_family", {}).items():
            if category_data is not None:
                se_expanded_sums[category].append(category_data["score_pct"])

        if wfo is not None:
            wfo_label = wfo.get("aggregate_signal_label")
            if wfo_label is None:
                wfo_count_indisponible += 1
            elif "Achat" in wfo_label:
                wfo_count_achat += 1
            elif "Vente" in wfo_label:
                wfo_count_vente += 1
            else:
                wfo_count_neutre += 1

            if wfo["aggregate_score_pct"] is not None:
                wfo_aggregate_scores.append(wfo["aggregate_score_pct"])
            for category, cat_data in wfo["per_family"].items():
                if cat_data is not None:
                    wfo_category_sums[category].append(cat_data["score_pct"])
        else:
            wfo_count_indisponible += 1

    se_per_family = {}
    for category_name in LEGACY_CATEGORY_FAMILIES:
        scores = se_category_sums.get(category_name, [])
        if scores:
            avg_score = sum(scores) / len(scores)
            signal_type = FAMILY_SIGNAL_TYPE.get(LEGACY_CATEGORY_FAMILIES[category_name][0], "trend")
            se_per_family[category_name] = {
                "score_pct": round(avg_score, 2),
                "label": signal_type_label(signal_type, avg_score),
            }

    se_expanded_per_family = {}
    for category_name in EXPANDED_CATEGORY_FAMILIES:
        scores = se_expanded_sums.get(category_name, [])
        if scores:
            avg_score = sum(scores) / len(scores)
            signal_type = FAMILY_SIGNAL_TYPE.get(EXPANDED_CATEGORY_FAMILIES[category_name][0], "trend")
            se_expanded_per_family[category_name] = {
                "score_pct": round(avg_score, 2),
                "label": signal_type_label(signal_type, avg_score),
            }

    overall_aggregate = sum(se_aggregate_scores) / len(se_aggregate_scores) if se_aggregate_scores else None
    overall_expanded_aggregate = (
        sum(se_expanded_aggregate_scores) / len(se_expanded_aggregate_scores)
        if se_expanded_aggregate_scores
        else None
    )

    se_scores_obj = {
        "variant": "expanded",
        "aggregate_score_pct": round(overall_aggregate, 2) if overall_aggregate is not None else None,
        "aggregate_signal_label": _score_to_label(overall_aggregate) if overall_aggregate is not None else None,
        "expanded_aggregate_score_pct": round(overall_expanded_aggregate, 2) if overall_expanded_aggregate is not None else None,
        "expanded_aggregate_signal_label": _score_to_label(overall_expanded_aggregate) if overall_expanded_aggregate is not None else None,
        "per_family": se_per_family,
        "expanded_per_family": se_expanded_per_family,
        "breadth": {
            "achat": se_count_achat,
            "neutre": se_count_neutre,
            "vente": se_count_vente,
            "indisponible": se_count_indisponible,
        },
    }

    wfo_scores_obj = None
    if wfo_aggregate_scores:
        wfo_per_family: dict[str, dict] = {}
        for category_name in EXPANDED_CATEGORY_FAMILIES:
            scores = wfo_category_sums.get(category_name, [])
            if scores:
                avg_score = sum(scores) / len(scores)
                signal_type = FAMILY_SIGNAL_TYPE.get(EXPANDED_CATEGORY_FAMILIES[category_name][0], "trend")
                wfo_per_family[category_name] = {
                    "score_pct": round(avg_score, 2),
                    "label": signal_type_label(signal_type, avg_score),
                }
        wfo_agg = sum(wfo_aggregate_scores) / len(wfo_aggregate_scores)
        wfo_scores_obj = {
            "variant": "expanded",
            "aggregate_score_pct": round(wfo_agg, 2),
            "aggregate_signal_label": _score_to_label(wfo_agg),
            "per_family": wfo_per_family,
            "breadth": {
                "achat": wfo_count_achat,
                "neutre": wfo_count_neutre,
                "vente": wfo_count_vente,
                "indisponible": wfo_count_indisponible,
            },
        }

    return {
        "name": "MASI",
        "stock_count": len(stocks),
        "scores": {
            "signal_engine": se_scores_obj,
            "wfo": wfo_scores_obj,
        },
        # Backward-compat flat fields kept until Phase 2
        "aggregate_score_pct": se_scores_obj["aggregate_score_pct"],
        "aggregate_signal_label": se_scores_obj["aggregate_signal_label"],
        "expanded_aggregate_score_pct": se_scores_obj["expanded_aggregate_score_pct"],
        "expanded_aggregate_signal_label": se_scores_obj["expanded_aggregate_signal_label"],
        "per_family": se_per_family,
        "expanded_per_family": se_expanded_per_family,
        "breadth": se_scores_obj["breadth"],
    }


def load_custom_index_definitions(db) -> list[dict]:
    """Load persisted custom index definitions (if table exists)."""
    from sqlalchemy import text

    has_component_shares = True
    try:
        rows = db.execute(
            text(
                """
                SELECT id::text AS id, name, symbols, component_shares
                FROM dashboard_custom_index
                ORDER BY updated_at DESC, name ASC
                """
            )
        ).fetchall()
    except Exception:
        db.rollback()
        has_component_shares = False
        try:
            rows = db.execute(
                text(
                    """
                    SELECT id::text AS id, name, symbols
                    FROM dashboard_custom_index
                    ORDER BY updated_at DESC, name ASC
                    """
                )
            ).fetchall()
        except Exception:
            db.rollback()
            logger.info("dashboard_custom_index table not found or unavailable; exporting without custom indices")
            return []

    definitions: list[dict] = []
    for row in rows:
        raw_symbols = row[2] if isinstance(row[2], list) else []
        raw_component_shares = row[3] if has_component_shares and len(row) > 3 else {}
        if isinstance(raw_component_shares, str):
            try:
                raw_component_shares = json.loads(raw_component_shares)
            except json.JSONDecodeError:
                raw_component_shares = {}
        if not isinstance(raw_component_shares, dict):
            raw_component_shares = {}
        seen: set[str] = set()
        symbols: list[str] = []
        for raw in raw_symbols:
            token = str(raw or "").strip().upper()
            if not token or token in seen:
                continue
            seen.add(token)
            symbols.append(token)
        if not symbols:
            continue
        component_shares: dict[str, int] = {}
        for raw_symbol, raw_shares in raw_component_shares.items():
            symbol = str(raw_symbol or "").strip().upper()
            if symbol not in seen:
                continue
            try:
                shares = int(raw_shares)
            except (TypeError, ValueError):
                continue
            if shares <= 0:
                continue
            component_shares[symbol] = shares
        components = [
            {"symbol": symbol, "shares": component_shares[symbol]}
            for symbol in symbols
            if symbol in component_shares
        ]
        definitions.append(
            {
                "id": str(row[0]),
                "name": str(row[1]).strip(),
                "symbols": symbols,
                "component_shares": component_shares,
                "components": components,
                "is_weighted_complete": bool(symbols) and all(symbol in component_shares for symbol in symbols),
            }
        )

    logger.info("Loaded %d persisted custom indices", len(definitions))
    return definitions


def main() -> None:
    from sqlalchemy import text

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    SessionLocal = _ensure_session_factory()
    db = SessionLocal()

    try:
        rows = db.execute(
            text(
                """
                SELECT DISTINCT mds.symbol, sm.display_name, sm.sector
                FROM market_data_store mds
                LEFT JOIN stock_master sm ON sm.symbol = mds.symbol
                WHERE mds.timeframe = '1D'
                ORDER BY mds.symbol
                """
            )
        ).fetchall()

        symbols_info = []
        for row in rows:
            symbol = row[0]
            display_name = row[1]
            sector = row[2]

            masi = get_masi_info(symbol)
            if masi:
                display_name = masi.get("display_name") or display_name
                sector = sector or masi.get("sector")

            symbols_info.append(
                {
                    "symbol": symbol,
                    "display_name": display_name,
                    "sector": sector,
                }
            )

        logger.info("Found %d symbols with 1D data", len(symbols_info))
        custom_index_definitions = load_custom_index_definitions(db)

        for horizon, horizon_label in HORIZONS.items():
            logger.info("\n=== Horizon: %s (%s) ===", horizon, horizon_label)
            started_at = time.time()

            wfo_data_for_horizon = load_wfo_data(db, horizon)
            logger.info("Loaded WFO data for %d symbols", len(wfo_data_for_horizon))

            stocks = []
            for i, info in enumerate(symbols_info, 1):
                symbol = info["symbol"]
                result = compute_symbol_scores(db, symbol, horizon)

                if result is None:
                    logger.info(
                        "[%d/%d] %s: SKIPPED (no data or all families failed)",
                        i,
                        len(symbols_info),
                        symbol,
                    )
                    continue

                result["scores"]["wfo"] = _build_wfo_scores(wfo_data_for_horizon.get(symbol))

                se = result["scores"]["signal_engine"]
                family_summary = " ".join(
                    f"{category}={se['per_family'][category]['label']}"
                    for category in LEGACY_CATEGORY_FAMILIES
                    if category in se["per_family"]
                )
                wfo_tag = f" WFO={result['scores']['wfo']['aggregate_score_pct']:.1f}" if result["scores"]["wfo"] else ""
                logger.info(
                    "[%d/%d] %s: %s -> %s (%s)%s",
                    i,
                    len(symbols_info),
                    symbol,
                    family_summary or "aucune famille disponible",
                    se["aggregate_signal_label"] or "Indisponible",
                    f"{se['aggregate_score_pct']:.1f}" if se["aggregate_score_pct"] is not None else "-",
                    wfo_tag,
                )

                stocks.append(
                    {
                        "symbol": symbol,
                        "display_name": info["display_name"],
                        "sector": info["sector"],
                        **result,
                    }
                )

            sectors = aggregate_sectors(stocks)
            index = aggregate_index(stocks)

            output = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "horizon": horizon,
                "horizon_label": horizon_label,
                "stocks": stocks,
                "sectors": sectors,
                "index": index,
                "custom_index_definitions": custom_index_definitions,
            }

            out_path = OUTPUT_DIR / f"scores-{horizon}.json"
            with open(out_path, "w", encoding="utf-8") as file_obj:
                json.dump(output, file_obj, ensure_ascii=False, indent=2)

            signals_output = {
                "generated_at": output["generated_at"],
                "horizon": horizon,
                "horizon_label": horizon_label,
                "stocks": [
                    {
                        "symbol": stock["symbol"],
                        "display_name": stock["display_name"],
                        "sector": stock["sector"],
                        "aggregate_score_pct": stock["scores"]["signal_engine"]["aggregate_score_pct"],
                        "aggregate_signal_label": stock["scores"]["signal_engine"]["aggregate_signal_label"],
                        "expanded_aggregate_score_pct": stock["scores"]["signal_engine"].get("expanded_aggregate_score_pct"),
                        "expanded_aggregate_signal_label": stock["scores"]["signal_engine"].get("expanded_aggregate_signal_label"),
                        "per_family": stock["scores"]["signal_engine"].get("per_family", {}),
                        "expanded_per_family": stock["scores"]["signal_engine"].get("expanded_per_family", {}),
                        "families": stock["scores"]["signal_engine"].get("families", {}),
                        "support_resistance": stock["scores"]["signal_engine"].get("support_resistance"),
                    }
                    for stock in stocks
                ],
            }

            signals_path = OUTPUT_DIR / f"signals-{horizon}.json"
            with open(signals_path, "w", encoding="utf-8") as file_obj:
                json.dump(signals_output, file_obj, ensure_ascii=False, indent=2)

            elapsed = time.time() - started_at
            logger.info(
                "Wrote %s and %s (%d stocks, %d sectors) in %.1fs",
                out_path.name,
                signals_path.name,
                len(stocks),
                len(sectors),
                elapsed,
            )

    finally:
        db.close()

    logger.info("\nDone. Files in: %s", OUTPUT_DIR)


if __name__ == "__main__":
    main()
