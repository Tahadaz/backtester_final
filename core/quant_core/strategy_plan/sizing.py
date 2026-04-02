"""Position sizing — Kelly criterion + portfolio allocation."""

from __future__ import annotations

import math
from typing import Any


def compute_kelly_ceiling(
    win_rate: float,
    avg_wl_ratio: float,
    modifier: float,
    entry_price: float,
    stop_price: float,
    account_equity: float,
) -> dict[str, Any]:
    """Compute Kelly-optimal position size for a single trade.

    Parameters
    ----------
    win_rate : float
        Estimated probability of winning (0-1).
    avg_wl_ratio : float
        Average win / average loss ratio (> 0).
    modifier : float
        Kelly fraction modifier (1.0 = full, 0.5 = half, 0.25 = quarter).
    entry_price : float
        Planned entry price.
    stop_price : float
        Planned stop loss price.
    account_equity : float
        Total account equity in currency units.

    Returns
    -------
    dict with keys:
        full_kelly_pct, modified_kelly_pct, position_size_shares,
        position_value, trade_risk, pct_of_account_risked
    """
    # Kelly formula: f* = (p * b - q) / b  where p=win_rate, q=1-p, b=avg_wl_ratio
    if avg_wl_ratio <= 0 or win_rate <= 0 or win_rate >= 1:
        return {
            "full_kelly_pct": 0.0,
            "modified_kelly_pct": 0.0,
            "position_size_shares": 0,
            "position_value": 0.0,
            "trade_risk": 0.0,
            "pct_of_account_risked": 0.0,
        }

    q = 1.0 - win_rate
    f_star = (win_rate * avg_wl_ratio - q) / avg_wl_ratio
    f_star = max(f_star, 0.0)  # No edge → no bet

    modified_f = f_star * modifier

    risk_per_share = abs(entry_price - stop_price)
    if risk_per_share <= 0 or account_equity <= 0:
        return {
            "full_kelly_pct": round(f_star * 100, 2),
            "modified_kelly_pct": round(modified_f * 100, 2),
            "position_size_shares": 0,
            "position_value": 0.0,
            "trade_risk": 0.0,
            "pct_of_account_risked": 0.0,
        }

    capital_at_risk = account_equity * modified_f
    shares = math.floor(capital_at_risk / risk_per_share)
    position_value = shares * entry_price
    trade_risk = shares * risk_per_share
    pct_risked = (trade_risk / account_equity * 100) if account_equity > 0 else 0.0

    return {
        "full_kelly_pct": round(f_star * 100, 2),
        "modified_kelly_pct": round(modified_f * 100, 2),
        "position_size_shares": shares,
        "position_value": round(position_value, 2),
        "trade_risk": round(trade_risk, 2),
        "pct_of_account_risked": round(pct_risked, 2),
    }


def compute_portfolio_allocation(
    stocks: list[dict[str, Any]],
    method: str,
    max_position_pct: float,
    max_sector_pct: float,
    account_equity: float,
    kelly_modifier: float,
    win_rate: float,
    avg_wl_ratio: float,
) -> dict[str, Any]:
    """Allocate capital across basket stocks.

    Parameters
    ----------
    stocks : list[dict]
        Each dict: ``{symbol, entry_price, stop_price, atr_pct, consensus,
        sector, status}``.  Only ``status == "entry_zone"`` receives weight.
    method : str
        ``"equal_weight"``, ``"inverse_volatility"``, or ``"signal_weighted"``.
    max_position_pct : float
        Max single-position weight (0-100).
    max_sector_pct : float
        Max sector weight (0-100).
    account_equity : float
        Total account equity.
    kelly_modifier : float
        Kelly fraction modifier (0-1).
    win_rate, avg_wl_ratio : float
        For per-stock Kelly ceiling.

    Returns
    -------
    dict with keys:
        portfolio_table (list[dict]), total_exposure_pct, total_risk_pct,
        capital_deployed, explain
    """
    active = [s for s in stocks if s.get("status") == "entry_zone"]

    if not active or account_equity <= 0:
        table = [
            {
                "symbol": s["symbol"],
                "weight_pct": 0.0,
                "shares": 0,
                "position_value": 0.0,
                "trade_risk": 0.0,
                "status": s.get("status", "no_setup"),
            }
            for s in stocks
        ]
        return {
            "portfolio_table": table,
            "total_exposure_pct": 0.0,
            "total_risk_pct": 0.0,
            "capital_deployed": 0.0,
            "explain": "Aucune position active dans le panier.",
        }

    # Step 1: Raw weights for active stocks
    raw_weights: dict[str, float] = {}
    if method == "inverse_volatility":
        total_inv = 0.0
        for s in active:
            atr_pct = s.get("atr_pct", 0)
            inv = 1.0 / atr_pct if atr_pct and atr_pct > 0 else 0.0
            raw_weights[s["symbol"]] = inv
            total_inv += inv
        if total_inv > 0:
            raw_weights = {k: v / total_inv for k, v in raw_weights.items()}
        else:
            raw_weights = {s["symbol"]: 1.0 / len(active) for s in active}
    elif method == "signal_weighted":
        total_abs = 0.0
        for s in active:
            c = abs(s.get("consensus", 0) or 0)
            raw_weights[s["symbol"]] = c
            total_abs += c
        if total_abs > 0:
            raw_weights = {k: v / total_abs for k, v in raw_weights.items()}
        else:
            raw_weights = {s["symbol"]: 1.0 / len(active) for s in active}
    else:  # equal_weight
        raw_weights = {s["symbol"]: 1.0 / len(active) for s in active}

    # Step 2: Constraint clipping (position cap + sector cap)
    max_pos = max_position_pct / 100.0
    max_sec = max_sector_pct / 100.0
    weights = dict(raw_weights)

    for _ in range(10):  # iterate until stable
        changed = False

        # Position cap
        for sym in list(weights):
            if weights[sym] > max_pos:
                weights[sym] = max_pos
                changed = True

        # Sector cap
        sector_map: dict[str, list[str]] = {}
        for s in active:
            sec = s.get("sector") or "Other"
            sector_map.setdefault(sec, []).append(s["symbol"])

        for sec, syms in sector_map.items():
            sec_weight = sum(weights.get(s, 0) for s in syms)
            if sec_weight > max_sec:
                scale = max_sec / sec_weight
                for s in syms:
                    weights[s] = weights.get(s, 0) * scale
                changed = True

        # Renormalize
        total_w = sum(weights.values())
        if total_w > 0 and abs(total_w - 1.0) > 1e-9:
            weights = {k: v / total_w for k, v in weights.items()}

        if not changed:
            break

    # Step 3: Build portfolio table with Kelly ceiling
    active_map = {s["symbol"]: s for s in active}
    table: list[dict[str, Any]] = []
    total_value = 0.0
    total_risk = 0.0

    for s in stocks:
        sym = s["symbol"]
        if sym in weights and sym in active_map:
            a = active_map[sym]
            entry_price = a.get("entry_price", 0) or 0
            stop_price = a.get("stop_price", 0) or 0
            w = weights[sym]

            # Allocation-based shares
            if entry_price > 0:
                alloc_shares = math.floor(w * account_equity / entry_price)
            else:
                alloc_shares = 0

            # Kelly ceiling
            kelly = compute_kelly_ceiling(
                win_rate, avg_wl_ratio, kelly_modifier,
                entry_price, stop_price, account_equity,
            )
            kelly_shares = kelly["position_size_shares"]

            # Final = min(allocation, kelly)
            final_shares = min(alloc_shares, kelly_shares)
            pos_value = final_shares * entry_price
            risk_per_share = abs(entry_price - stop_price)
            pos_risk = final_shares * risk_per_share

            table.append({
                "symbol": sym,
                "weight_pct": round(w * 100, 2),
                "shares": final_shares,
                "position_value": round(pos_value, 2),
                "trade_risk": round(pos_risk, 2),
                "status": "entry_zone",
            })
            total_value += pos_value
            total_risk += pos_risk
        else:
            table.append({
                "symbol": sym,
                "weight_pct": 0.0,
                "shares": 0,
                "position_value": 0.0,
                "trade_risk": 0.0,
                "status": s.get("status", "no_setup"),
            })

    exposure_pct = (total_value / account_equity * 100) if account_equity > 0 else 0.0
    risk_pct = (total_risk / account_equity * 100) if account_equity > 0 else 0.0

    n_active = len(active)
    method_labels = {
        "equal_weight": "Equipondere",
        "inverse_volatility": "Volatilite inverse",
        "signal_weighted": "Signal",
    }
    explain = (
        f"{n_active} position(s) active(s) — methode {method_labels.get(method, method)}. "
        f"Exposition {exposure_pct:.1f}%, risque {risk_pct:.1f}%."
    )

    return {
        "portfolio_table": table,
        "total_exposure_pct": round(exposure_pct, 2),
        "total_risk_pct": round(risk_pct, 2),
        "capital_deployed": round(total_value, 2),
        "explain": explain,
    }
