"""Portfolio allocation helpers for strategy construction previews."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _equal_weights(symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    w = 1.0 / float(len(symbols))
    return {symbol: w for symbol in symbols}


def _prepare_returns(
    price_history: dict[str, pd.Series],
    symbols: list[str],
    lookback_bars: int,
) -> pd.DataFrame:
    frames: list[pd.Series] = []
    for symbol in symbols:
        series = price_history.get(symbol)
        if series is None:
            continue
        cleaned = pd.Series(series).dropna().astype(float)
        if cleaned.empty:
            continue
        if lookback_bars > 0 and len(cleaned) > lookback_bars + 1:
            cleaned = cleaned.iloc[-(lookback_bars + 1):]
        frames.append(cleaned.rename(symbol))

    if not frames:
        return pd.DataFrame()

    prices = pd.concat(frames, axis=1, join="inner").sort_index()
    returns = prices.pct_change().replace([np.inf, -np.inf], np.nan).dropna(how="any")
    if returns.empty:
        return pd.DataFrame()

    non_constant = returns.std(axis=0) > 0
    returns = returns.loc[:, non_constant]
    return returns.dropna(how="any")


def _single_linkage(corr: np.ndarray) -> np.ndarray:
    n = corr.shape[0]
    if n <= 1:
        return np.zeros((0, 4), dtype=float)

    dist = np.sqrt(np.clip((1.0 - corr) / 2.0, 0.0, 1.0))
    clusters: dict[int, list[int]] = {i: [i] for i in range(n)}
    linkage_rows: list[list[float]] = []
    next_id = n

    while len(clusters) > 1:
        ids = sorted(clusters)
        best_left: int | None = None
        best_right: int | None = None
        best_dist: float | None = None

        for i, left in enumerate(ids[:-1]):
            left_members = clusters[left]
            for right in ids[i + 1 :]:
                right_members = clusters[right]
                current_dist = float(dist[np.ix_(left_members, right_members)].min())
                if (
                    best_dist is None
                    or current_dist < best_dist
                    or (
                        np.isclose(current_dist, best_dist)
                        and (left, right) < (best_left or left, best_right or right)
                    )
                ):
                    best_left = left
                    best_right = right
                    best_dist = current_dist

        if best_left is None or best_right is None or best_dist is None:
            break

        merged = clusters.pop(best_left) + clusters.pop(best_right)
        linkage_rows.append([float(best_left), float(best_right), float(best_dist), float(len(merged))])
        clusters[next_id] = merged
        next_id += 1

    return np.asarray(linkage_rows, dtype=float)


def _quasi_diagonalize(linkage: np.ndarray, n_items: int) -> list[int]:
    if n_items <= 1 or linkage.size == 0:
        return list(range(n_items))

    def _expand(node_id: int) -> list[int]:
        if node_id < n_items:
            return [node_id]
        row = linkage[int(node_id - n_items)]
        left = int(row[0])
        right = int(row[1])
        return _expand(left) + _expand(right)

    root_id = n_items + linkage.shape[0] - 1
    return _expand(root_id)


def _cluster_variance(cov: np.ndarray, cluster_items: list[int]) -> float:
    cov_slice = cov[np.ix_(cluster_items, cluster_items)]
    diag = np.diag(cov_slice)
    diag = np.where(diag <= 0, 1e-8, diag)
    ivp = 1.0 / diag
    ivp = ivp / ivp.sum()
    variance = float(ivp @ cov_slice @ ivp)
    return max(variance, 1e-8)


def compute_hrp_weights(
    price_history: dict[str, pd.Series],
    symbols: list[str],
    *,
    lookback_bars: int = 252,
) -> dict[str, float]:
    """Compute de Prado-style HRP weights from close history."""
    clean_symbols = [symbol for symbol in symbols if symbol]
    if len(clean_symbols) <= 1:
        return _equal_weights(clean_symbols)

    returns = _prepare_returns(price_history, clean_symbols, lookback_bars)
    if returns.empty or returns.shape[1] <= 1 or returns.shape[0] < 10:
        return _equal_weights(clean_symbols)

    ordered_symbols = list(returns.columns)
    cov = returns.cov().to_numpy(dtype=float)
    corr = returns.corr().fillna(0.0).to_numpy(dtype=float)
    np.fill_diagonal(corr, 1.0)

    linkage = _single_linkage(corr)
    sort_ix = _quasi_diagonalize(linkage, len(ordered_symbols))
    ordered = [ordered_symbols[i] for i in sort_ix]

    weights = pd.Series(1.0, index=ordered, dtype=float)
    pending: list[list[str]] = [ordered]
    cov_df = pd.DataFrame(cov, index=ordered_symbols, columns=ordered_symbols)

    while pending:
        cluster = pending.pop(0)
        if len(cluster) <= 1:
            continue

        split = len(cluster) // 2
        left = cluster[:split]
        right = cluster[split:]
        left_items = [ordered_symbols.index(symbol) for symbol in left]
        right_items = [ordered_symbols.index(symbol) for symbol in right]

        left_var = _cluster_variance(cov_df.to_numpy(dtype=float), left_items)
        right_var = _cluster_variance(cov_df.to_numpy(dtype=float), right_items)
        alpha = 1.0 - left_var / (left_var + right_var)

        weights[left] *= alpha
        weights[right] *= 1.0 - alpha

        pending.append(left)
        pending.append(right)

    weights = weights / weights.sum()
    return {symbol: float(weights.get(symbol, 0.0)) for symbol in clean_symbols}


def compute_strategy_allocation(
    *,
    symbols: list[str],
    total_capital_mad: float,
    price_history: dict[str, pd.Series],
    manual_overrides_by_symbol: dict[str, float] | None = None,
    lookback_bars: int = 252,
) -> dict[str, Any]:
    """Allocate strategy capital across selected stocks using HRP + manual overrides."""
    clean_symbols = [symbol for symbol in symbols if symbol]
    total_capital = max(float(total_capital_mad or 0.0), 0.0)
    manual_raw = dict(manual_overrides_by_symbol or {})

    hrp_weights = compute_hrp_weights(
        price_history,
        clean_symbols,
        lookback_bars=int(lookback_bars or 252),
    )
    if not hrp_weights:
        hrp_weights = _equal_weights(clean_symbols)

    manual: dict[str, float] = {}
    for symbol in clean_symbols:
        raw_value = manual_raw.get(symbol)
        if raw_value is None:
            continue
        value = max(float(raw_value or 0.0), 0.0)
        if value > 0:
            manual[symbol] = value

    explain_parts: list[str] = []
    manual_total = sum(manual.values())
    if total_capital <= 0 or not clean_symbols:
        return {
            "rows": [],
            "total_capital_mad": round(total_capital, 2),
            "allocated_capital_mad": 0.0,
            "remaining_capital_mad": round(total_capital, 2),
            "explain": "Aucun capital ou aucune action selectionnee.",
        }

    if manual_total > total_capital and manual_total > 0:
        scale = total_capital / manual_total
        manual = {symbol: value * scale for symbol, value in manual.items()}
        manual_total = total_capital
        explain_parts.append("Overrides manuels normalises pour respecter le capital total.")

    remaining_capital = max(total_capital - manual_total, 0.0)
    auto_symbols = [symbol for symbol in clean_symbols if symbol not in manual]
    auto_base = {symbol: hrp_weights.get(symbol, 0.0) for symbol in auto_symbols}
    auto_sum = sum(auto_base.values())
    if auto_symbols and auto_sum <= 0:
        auto_base = _equal_weights(auto_symbols)
        auto_sum = sum(auto_base.values())

    rows: list[dict[str, Any]] = []
    allocated_total = 0.0
    for symbol in clean_symbols:
        hrp_weight = float(hrp_weights.get(symbol, 0.0))
        if symbol in manual:
            capital = float(manual[symbol])
            source = "manual"
        else:
            norm_weight = (auto_base.get(symbol, 0.0) / auto_sum) if auto_sum > 0 else 0.0
            capital = remaining_capital * norm_weight
            source = "hrp"

        allocated_total += capital
        weight_pct = (capital / total_capital * 100.0) if total_capital > 0 else 0.0
        rows.append({
            "symbol": symbol,
            "source": source,
            "hrp_weight_pct": round(hrp_weight * 100.0, 2),
            "weight_pct": round(weight_pct, 2),
            "capital_mad": round(capital, 2),
        })

    remaining_after_rows = max(total_capital - allocated_total, 0.0)
    if not explain_parts:
        explain_parts.append("Allocation HRP avec overrides manuels optionnels.")

    return {
        "rows": rows,
        "total_capital_mad": round(total_capital, 2),
        "allocated_capital_mad": round(allocated_total, 2),
        "remaining_capital_mad": round(remaining_after_rows, 2),
        "explain": " ".join(explain_parts),
    }
