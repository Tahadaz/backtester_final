"""Universe filtering — select eligible stocks for strategy execution."""

from __future__ import annotations

from typing import Any


def filter_universe(
    stocks: list[dict[str, Any]],
    signal_scores: dict[str, dict[str, Any]],
    *,
    min_bars: int = 252,
    min_abs_signal: float = 0.0,
    min_adv20: float = 0.0,
    sector_filter: list[str] | None = None,
    sort_by: str = "signal_score",
    sort_dir: str = "desc",
) -> list[dict[str, Any]]:
    """Filter and enrich stocks with signal scores and eligibility status.

    Parameters
    ----------
    stocks : list[dict]
        Raw stock records from StockMaster (must have ``symbol``, ``row_count``,
        ``sector``, ``display_name``, ``data_as_of``).
    signal_scores : dict[str, dict]
        Keyed by symbol.  Each value must contain at least
        ``aggregate_score_pct`` and ``aggregate_signal_label``.  May also
        contain ``per_family`` and ``categories``.
    min_bars : int
        Minimum number of OHLCV bars to be eligible (default 252 = ~1 year).
    min_abs_signal : float
        Minimum ``|aggregate_score_pct|`` to be eligible (0 = no filter).
    sector_filter : list[str] | None
        If provided, only stocks in these sectors are eligible.

    Returns
    -------
    list[dict]
        Each dict is the original stock enriched with:
        - ``signal_score`` (float | None)
        - ``signal_label`` (str | None)
        - ``per_family`` (dict | None)
        - ``eligible`` (bool)
        - ``exclusion_reason`` (str | None)

        Sorted by the requested metric with eligible names first. Stocks
        without the selected metric appear last, marked ineligible when
        applicable.
    """
    results: list[dict[str, Any]] = []

    for stock in stocks:
        symbol = stock.get("symbol", "")
        row_count = stock.get("row_count") or 0
        sector = stock.get("sector") or ""

        scores = signal_scores.get(symbol, {})
        score = scores.get("aggregate_score_pct")
        label = scores.get("aggregate_signal_label")
        per_family = scores.get("per_family")

        adv20 = stock.get("adv20")

        # --- eligibility checks (first failing reason wins) ---
        reason: str | None = None
        if row_count < min_bars:
            reason = f"Historique insuffisant ({row_count} barres < {min_bars})"
        elif sector_filter and sector not in sector_filter:
            reason = f"Secteur '{sector}' exclu du filtre"
        elif min_adv20 > 0 and (adv20 is None or adv20 < min_adv20):
            shown = f"{float(adv20):,.0f}".replace(",", " ") if adv20 is not None else "indisponible"
            reason = f"ADV20 {shown} < seuil {min_adv20:,.0f}".replace(",", " ")
        elif score is None:
            reason = "Score signal indisponible"
        elif min_abs_signal > 0 and abs(score) < min_abs_signal:
            reason = f"|Score| {abs(score):.1f} < seuil {min_abs_signal:.1f}"

        enriched: dict[str, Any] = {
            **stock,
            "signal_score": score,
            "signal_label": label,
            "per_family": per_family,
            "eligible": reason is None,
            "exclusion_reason": reason,
        }
        results.append(enriched)

    # Sort: eligible first, then requested ordering.
    def _metric_value(r: dict) -> float:
        if sort_by == "signal_score":
            score = r.get("signal_score")
            return abs(score) if score is not None else -1.0
        adv20 = r.get("adv20")
        return float(adv20) if adv20 is not None else -1.0

    descending = str(sort_dir or "desc").lower() != "asc"

    def _sort_key(r: dict) -> tuple[int, float]:
        metric = _metric_value(r)
        adjusted = -metric if descending else metric
        return (0 if r["eligible"] else 1, adjusted)

    results.sort(key=_sort_key)
    return results
