"""Execution plan — convert consensus + levels into trade geometry."""

from __future__ import annotations

from typing import Any


def compute_execution_plan(
    consensus: float | None,
    side_policy: str,
    nearest_support: float | None,
    nearest_resistance: float | None,
    supports: list[dict[str, Any]],
    resistances: list[dict[str, Any]],
    atr: float,
    current_close: float,
    *,
    entry_threshold: float = 20.0,
    atr_multiplier: float = 1.5,
    buffer_pct: float = 0.005,
    min_rr: float = 1.5,
    holding_bars: int | None = None,
) -> dict[str, Any]:
    """Compute a full execution plan from pre-fetched data.

    Parameters
    ----------
    consensus : float | None
        Aggregate signal score on [-100, +100]. None if unavailable.
    side_policy : str
        ``"long_only"`` or ``"long_short"``.
    nearest_support, nearest_resistance : float | None
        From ``detect_swing_levels()``.
    supports, resistances : list[dict]
        Full level lists from ``detect_swing_levels()``.
    atr : float
        ATR(14) absolute value.
    current_close : float
        Latest closing price.
    entry_threshold : float
        Minimum |consensus| to consider a setup (default 20).
    atr_multiplier : float
        ATR multiplier for volatility stop (default 1.5).
    buffer_pct : float
        Buffer below/above structural stop (default 0.5%).
    min_rr : float
        Minimum reward-to-risk ratio (default 1.5).

    Returns
    -------
    dict with keys:
        direction, status, entry_price, entry_zone_low, entry_zone_high,
        stop_loss, target_1, target_2, rr_ratio, atr_14, adjusted_consensus,
        explain
    """
    result: dict[str, Any] = {
        "direction": None,
        "status": "no_setup",
        "entry_price": None,
        "entry_zone_low": None,
        "entry_zone_high": None,
        "stop_loss": None,
        "target_1": None,
        "target_2": None,
        "rr_ratio": None,
        "atr_14": round(atr, 4) if atr else None,
        "adjusted_consensus": consensus,
        "explain": "",
    }

    # Step 1: Conviction filter
    if consensus is None or abs(consensus) < entry_threshold:
        result["explain"] = (
            f"Conviction insuffisante: "
            f"|consensus| = {abs(consensus):.1f} < seuil {entry_threshold:.0f}."
            if consensus is not None
            else "Consensus indisponible."
        )
        return result

    # Step 2: Direction
    if consensus > 0:
        direction = "long"
    else:
        direction = "short"

    if side_policy == "long_only" and direction == "short":
        result["explain"] = (
            f"Signal baissier (consensus = {consensus:.1f}) "
            f"mais politique Long Only active."
        )
        return result

    result["direction"] = direction

    # Step 3: Entry zone
    if direction == "long":
        if nearest_support is not None:
            entry_zone_low = nearest_support
            entry_zone_high = nearest_support + atr
        else:
            # No support found — use current close - ATR as fallback
            entry_zone_low = current_close - atr
            entry_zone_high = current_close
    else:  # short
        if nearest_resistance is not None:
            entry_zone_low = nearest_resistance - atr
            entry_zone_high = nearest_resistance
        else:
            entry_zone_low = current_close
            entry_zone_high = current_close + atr

    result["entry_zone_low"] = round(entry_zone_low, 4)
    result["entry_zone_high"] = round(entry_zone_high, 4)

    # Step 4: Status — is price in entry zone?
    if entry_zone_low <= current_close <= entry_zone_high:
        result["status"] = "entry_zone"
        entry_price = current_close
    else:
        result["status"] = "watching"
        # Use midpoint of zone as reference entry
        entry_price = (entry_zone_low + entry_zone_high) / 2.0

    result["entry_price"] = round(entry_price, 4)

    # Step 5: Stop loss
    if direction == "long":
        # Structural stop: below support with buffer
        structural_stop = (
            supports[0]["price"] * (1 - buffer_pct) if supports else None
        )
        # Volatility stop: entry - ATR * multiplier
        volatility_stop = entry_price - atr * atr_multiplier

        if structural_stop is not None:
            stop = min(structural_stop, volatility_stop)
        else:
            stop = volatility_stop
    else:  # short
        structural_stop = (
            resistances[0]["price"] * (1 + buffer_pct) if resistances else None
        )
        volatility_stop = entry_price + atr * atr_multiplier

        if structural_stop is not None:
            stop = max(structural_stop, volatility_stop)
        else:
            stop = volatility_stop

    result["stop_loss"] = round(stop, 4)

    # Step 6: Targets
    if direction == "long":
        target_1 = resistances[0]["price"] if resistances else None
        target_2 = resistances[1]["price"] if len(resistances) > 1 else None
    else:
        target_1 = supports[0]["price"] if supports else None
        target_2 = supports[1]["price"] if len(supports) > 1 else None

    result["target_1"] = round(target_1, 4) if target_1 is not None else None
    result["target_2"] = round(target_2, 4) if target_2 is not None else None

    if target_1 is None:
        result["status"] = "no_setup"
        if holding_bars is not None:
            result["explain"] = (
                f"Aucune cible structurelle valide pour l'horizon d'execution "
                f"({holding_bars} barres)."
            )
        else:
            result["explain"] = "Aucune cible structurelle valide pour l'horizon d'execution."
        return result

    # Step 7: R:R ratio
    risk = abs(entry_price - stop)
    if risk > 0 and target_1 is not None:
        reward = abs(target_1 - entry_price)
        rr = reward / risk
        result["rr_ratio"] = round(rr, 2)

        if rr < min_rr:
            result["status"] = "unfavorable_rr"
            result["explain"] = (
                f"R:R = {rr:.2f} < seuil minimum {min_rr:.1f}. "
                f"Setup defavorable."
            )
            return result

    # Build explain
    dir_label = "Achat" if direction == "long" else "Vente"
    status_labels = {
        "entry_zone": "en zone d'entree",
        "watching": "en attente",
    }
    result["explain"] = (
        f"{dir_label} — prix {status_labels.get(result['status'], result['status'])}. "
        f"Zone [{entry_zone_low:.2f}, {entry_zone_high:.2f}], "
        f"stop {stop:.2f}, "
        f"cible {target_1:.2f}."
        if target_1 is not None
        else f"{dir_label} — {status_labels.get(result['status'], result['status'])}. "
        f"Zone [{entry_zone_low:.2f}, {entry_zone_high:.2f}], stop {stop:.2f}."
    )

    return result
