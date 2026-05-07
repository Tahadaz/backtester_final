from datetime import datetime
from typing import Any
import math

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..db import get_db
from ..models import StockMaster

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

HORIZONS = {
    "short": "Court terme",
    "medium": "Moyen terme",
    "long": "Long terme",
}

FAMILY_SIGNAL_TYPE = {
    "sma": "trend",
    "ema": "trend",
    "ema_cross": "trend",
    "ichimoku": "trend",
    "psar": "trend",
    "macd": "strength",
    "roc": "strength",
    "trix": "strength",
    "adx": "strength",
    "tsi": "strength",
    "rsi": "oscillator",
    "stochastic": "oscillator",
    "cci": "oscillator",
    "mfi": "oscillator",
    "uo": "oscillator",
    "obv": "volume",
    "cmf": "volume",
    "ad": "volume",
    "vwap": "volume",
    "fi": "volume",
}

LEGACY_CATEGORY_FAMILIES = {
    "tendance": ["sma"],
    "momentum": ["macd"],
    "oscillation": ["rsi"],
    "volume": ["obv"],
}
EXPANDED_CATEGORY_FAMILIES = {
    "tendance": ["sma", "ema", "ema_cross", "ichimoku", "psar"],
    "momentum": ["macd", "roc", "trix", "adx", "tsi"],
    "oscillation": ["rsi", "stochastic", "cci", "mfi", "uo"],
    "volume": ["obv", "cmf", "ad", "vwap", "fi"],
}

def signal_type_label(signal_type: str, score_pct: float) -> str:
    if signal_type == "trend":
        if score_pct >= 66.6:
            return "Hausse"
        if score_pct <= 33.3:
            return "Baisse"
        return "Neutre"
    if signal_type == "strength":
        if score_pct >= 66.6:
            return "Fort"
        if score_pct <= 33.3:
            return "Faible"
        return "Neutre"
    if signal_type == "oscillator":
        if score_pct >= 66.6:
            return "Surachat"
        if score_pct <= 33.3:
            return "Survente"
        return "Neutre"
    if signal_type == "volume":
        if score_pct >= 66.6:
            return "Accumulation"
        if score_pct <= 33.3:
            return "Distribution"
        return "Neutre"
    return "Neutre"

def _score_to_label(score_pct: float | None) -> str:
    if score_pct is None:
        return "Indisponible"
    if score_pct >= 66.6:
        return "Achat"
    if score_pct <= 33.3:
        return "Vente"
    return "Neutre"

def _round(val):
    if val is None:
        return None
    try:
        if math.isnan(val):
            return None
        return round(float(val), 2)
    except:
        return val


@router.get("/data/{horizon}", response_model=None)
def get_dashboard_data(horizon: str, db: Session = Depends(get_db)):
    if horizon not in HORIZONS:
        raise HTTPException(status_code=400, detail="Invalid horizon")

    # Fetch stocks
    stocks_info = db.query(StockMaster).filter_by(is_active=True).all()
    stock_dict = {s.symbol: s for s in stocks_info}

    # Fetch SE global results
    se_rows = db.execute(
        text("""
        SELECT symbol, aggregate_score_pct, expanded_aggregate_score_pct, signal_label,
               per_family_json, technical_levels_json, support_resistance_json
        FROM signal_engine_global_result
        WHERE horizon = :horizon AND variant = 'expanded' AND status = 'succeeded'
        """),
        {"horizon": horizon}
    ).fetchall()
    
    se_by_symbol = {row[0]: row for row in se_rows}

    # Fetch WFO global results
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
        {"horizon": horizon}
    ).fetchall()
    
    wfo_global_by_symbol = {row[0]: row for row in wfo_rows}

    wfo_summary_rows = db.execute(
        text("""
        SELECT symbol, category, score_pct, signal_label
        FROM wfo_signal_summary
        WHERE horizon = :horizon AND variant = 'expanded' AND status = 'succeeded'
        """),
        {"horizon": horizon}
    ).fetchall()

    wfo_summary_by_symbol = {}
    for row in wfo_summary_rows:
        sym, b, c, d = row
        if sym not in wfo_summary_by_symbol:
            wfo_summary_by_symbol[sym] = {}
        wfo_summary_by_symbol[sym][b] = {"score_pct": _round(c), "label": d}

    stocks_out = []
    
    for symbol, stock in stock_dict.items():
        if not stock.sector:
            continue
            
        # Signal Engine block
        se_row = se_by_symbol.get(symbol)
        se_scores_obj = {
            "variant": "expanded",
            "aggregate_score_pct": None,
            "aggregate_signal_label": "Indisponible",
            "expanded_aggregate_score_pct": None,
            "expanded_aggregate_signal_label": "Indisponible",
            "per_family": {},
            "expanded_per_family": {},
            "technical_levels": None,
            "support_resistance": None
        }
        
        if se_row:
            se_scores_obj["aggregate_score_pct"] = _round(se_row[1])
            se_scores_obj["expanded_aggregate_score_pct"] = _round(se_row[2])
            se_scores_obj["aggregate_signal_label"] = se_row[3] or "Indisponible"
            se_scores_obj["expanded_aggregate_signal_label"] = _score_to_label(se_row[2])
            
            per_family_json = se_row[4] or {}
            
            # Reconstruct per_family shape expected by frontend logic (grouped by category!)
            # In export-scores.py: se_scores["per_family"] is keyed by category name.
            per_family = {}
            for cat, fams in LEGACY_CATEGORY_FAMILIES.items():
                cat_scores = []
                for f in fams:
                    if f in per_family_json and per_family_json[f].get("family_score_pct") is not None:
                        cat_scores.append(per_family_json[f]["family_score_pct"])
                if cat_scores:
                    avg_score = sum(cat_scores) / len(cat_scores)
                    sig_type = FAMILY_SIGNAL_TYPE.get(fams[0], "trend")
                    per_family[cat] = {"score_pct": _round(avg_score), "label": signal_type_label(sig_type, avg_score)}
            se_scores_obj["per_family"] = per_family

            exp_per_family = {}
            for cat, fams in EXPANDED_CATEGORY_FAMILIES.items():
                cat_scores = []
                for f in fams:
                    if f in per_family_json and per_family_json[f].get("family_score_pct") is not None:
                        cat_scores.append(per_family_json[f]["family_score_pct"])
                if cat_scores:
                    avg_score = sum(cat_scores) / len(cat_scores)
                    sig_type = FAMILY_SIGNAL_TYPE.get(fams[0], "trend")
                    exp_per_family[cat] = {"score_pct": _round(avg_score), "label": signal_type_label(sig_type, avg_score)}
            se_scores_obj["expanded_per_family"] = exp_per_family
            se_scores_obj["technical_levels"] = se_row[5]
            se_scores_obj["support_resistance"] = se_row[6]
            
        # WFO block
        wfo_row = wfo_global_by_symbol.get(symbol)
        wfo_scores_obj = None
        
        if wfo_row and wfo_row[1] == "succeeded":
            w_cat_data = wfo_summary_by_symbol.get(symbol, {})
            per_fam = {}
            for cat in EXPANDED_CATEGORY_FAMILIES:
                if cat in w_cat_data:
                    per_fam[cat] = w_cat_data[cat]
            
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
                    "method": "wfo_sr"
                }
            }
            
        stock_obj = {
            "symbol": symbol,
            "display_name": stock.display_name,
            "sector": stock.sector,
            "scores": {
                "signal_engine": se_scores_obj,
                "wfo": wfo_scores_obj
            },
            # flat backwards compat properties
            "aggregate_score_pct": se_scores_obj["aggregate_score_pct"],
            "aggregate_signal_label": se_scores_obj["aggregate_signal_label"],
            "expanded_aggregate_score_pct": se_scores_obj["expanded_aggregate_score_pct"],
            "expanded_aggregate_signal_label": se_scores_obj["expanded_aggregate_signal_label"],
            "per_family": se_scores_obj["per_family"],
            "expanded_per_family": se_scores_obj["expanded_per_family"],
        }
        stocks_out.append(stock_obj)
        
    # Sector aggregation
    from collections import defaultdict
    by_sector = defaultdict(list)
    for s in stocks_out:
        by_sector[s["sector"]].append(s)
        
    sectors_out = []
    for sector_name, sector_stocks in sorted(by_sector.items()):
        se_aggs = []
        se_exp_aggs = []
        wfo_aggs = []
        
        se_cats = defaultdict(list)
        se_exp_cats = defaultdict(list)
        wfo_cats = defaultdict(list)
        
        for st in sector_stocks:
            se = st["scores"]["signal_engine"]
            if se["aggregate_score_pct"] is not None: se_aggs.append(se["aggregate_score_pct"])
            if se.get("expanded_aggregate_score_pct") is not None: se_exp_aggs.append(se["expanded_aggregate_score_pct"])
            for c, d in se.get("per_family", {}).items(): se_cats[c].append(d["score_pct"])
            for c, d in se.get("expanded_per_family", {}).items(): se_exp_cats[c].append(d["score_pct"])
            
            wfo = st["scores"].get("wfo")
            if wfo:
                if wfo["aggregate_score_pct"] is not None: wfo_aggs.append(wfo["aggregate_score_pct"])
                for c, d in wfo.get("per_family", {}).items(): wfo_cats[c].append(d["score_pct"])
                
        def _avg_cats(cat_dict, family_map):
            out = {}
            for c, vals in cat_dict.items():
                if vals:
                    avg = sum(vals)/len(vals)
                    sig = FAMILY_SIGNAL_TYPE.get(family_map[c][0], "trend")
                    out[c] = {"score_pct": _round(avg), "label": signal_type_label(sig, avg)}
            return out

        se_per_fam = _avg_cats(se_cats, LEGACY_CATEGORY_FAMILIES)
        se_exp_per_fam = _avg_cats(se_exp_cats, EXPANDED_CATEGORY_FAMILIES)
        wfo_per_fam = _avg_cats(wfo_cats, EXPANDED_CATEGORY_FAMILIES)
        
        se_agg_avg = sum(se_aggs)/len(se_aggs) if se_aggs else None
        se_exp_agg_avg = sum(se_exp_aggs)/len(se_exp_aggs) if se_exp_aggs else None
        wfo_agg_avg = sum(wfo_aggs)/len(wfo_aggs) if wfo_aggs else None
        
        se_obj = {
            "variant": "expanded",
            "aggregate_score_pct": _round(se_agg_avg),
            "aggregate_signal_label": _score_to_label(se_agg_avg),
            "expanded_aggregate_score_pct": _round(se_exp_agg_avg),
            "expanded_aggregate_signal_label": _score_to_label(se_exp_agg_avg),
            "per_family": se_per_fam,
            "expanded_per_family": se_exp_per_fam
        }
        
        wfo_obj = None
        if wfo_aggs:
            wfo_obj = {
                "variant": "expanded",
                "aggregate_score_pct": _round(wfo_agg_avg),
                "aggregate_signal_label": _score_to_label(wfo_agg_avg),
                "per_family": wfo_per_fam
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
        
    # Index aggregation (MASI)
    se_aggs = []
    se_exp_aggs = []
    wfo_aggs = []
    se_cats = defaultdict(list)
    se_exp_cats = defaultdict(list)
    wfo_cats = defaultdict(list)
    
    se_breadth = {"achat": 0, "neutre": 0, "vente": 0, "indisponible": 0}
    wfo_breadth = {"achat": 0, "neutre": 0, "vente": 0, "indisponible": 0}
    
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
            
        if se.get("expanded_aggregate_score_pct") is not None: se_exp_aggs.append(se["expanded_aggregate_score_pct"])
        for c, d in se.get("per_family", {}).items(): se_cats[c].append(d["score_pct"])
        for c, d in se.get("expanded_per_family", {}).items(): se_exp_cats[c].append(d["score_pct"])
        
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
            
    se_per_fam = _avg_cats(se_cats, LEGACY_CATEGORY_FAMILIES)
    se_exp_per_fam = _avg_cats(se_exp_cats, EXPANDED_CATEGORY_FAMILIES)
    wfo_per_fam = _avg_cats(wfo_cats, EXPANDED_CATEGORY_FAMILIES)
    
    se_agg_avg = sum(se_aggs)/len(se_aggs) if se_aggs else None
    se_exp_agg_avg = sum(se_exp_aggs)/len(se_exp_aggs) if se_exp_aggs else None
    wfo_agg_avg = sum(wfo_aggs)/len(wfo_aggs) if wfo_aggs else None
    
    se_obj = {
        "variant": "expanded",
        "aggregate_score_pct": _round(se_agg_avg),
        "aggregate_signal_label": _score_to_label(se_agg_avg),
        "expanded_aggregate_score_pct": _round(se_exp_agg_avg),
        "expanded_aggregate_signal_label": _score_to_label(se_exp_agg_avg),
        "per_family": se_per_fam,
        "expanded_per_family": se_exp_per_fam,
        "breadth": se_breadth
    }
    
    wfo_obj = None
    if wfo_aggs:
        wfo_obj = {
            "variant": "expanded",
            "aggregate_score_pct": _round(wfo_agg_avg),
            "aggregate_signal_label": _score_to_label(wfo_agg_avg),
            "per_family": wfo_per_fam,
            "breadth": wfo_breadth
        }
        
    index_out = {
        "name": "MASI",
        "stock_count": len(stocks_out),
        "scores": {"signal_engine": se_obj, "wfo": wfo_obj},
        "aggregate_score_pct": se_obj["aggregate_score_pct"],
        "aggregate_signal_label": se_obj["aggregate_signal_label"],
        "expanded_aggregate_score_pct": se_obj["expanded_aggregate_score_pct"],
        "expanded_aggregate_signal_label": se_obj["expanded_aggregate_signal_label"],
        "per_family": se_per_fam,
        "expanded_per_family": se_exp_per_fam,
    }

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "horizon": horizon,
        "horizon_label": HORIZONS[horizon],
        "stocks": stocks_out,
        "sectors": sectors_out,
        "index": index_out,
        "custom_index_definitions": []
    }
