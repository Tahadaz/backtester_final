"""Layer A - Structured candidate universe generation."""

from __future__ import annotations

from typing import Callable

from core.quant_core.horizons import canonical_horizon

from ._hashing import compute_variant_id
from .domain import (
    CATEGORY_FAMILIES,
    HORIZON_PARAM_CAP,
    LEGACY_CATEGORY_FAMILIES,
    VALID_HORIZONS,
    VariantDef,
    cap_param_grid,
)
from .ta_combo import COMBO_ARCHETYPE, make_combo_variant, primary_category_for_families, variant_from_component

_CANDIDATE_GENERATORS: dict[str, Callable[[str], list[VariantDef]]] = {}


def register_family(family: str):
    """Decorator: register a candidate generator for *family*."""

    def _wrap(fn: Callable[[str], list[VariantDef]]):
        _CANDIDATE_GENERATORS[family] = fn
        return fn

    return _wrap


def generate_candidates(family: str, horizon: str) -> list[VariantDef]:
    """Return the admissible candidate universe for *family* x *horizon*."""
    horizon = canonical_horizon(horizon, allow_legacy=True)
    if horizon not in VALID_HORIZONS:
        raise ValueError(f"Unknown horizon {horizon!r}; expected one of {sorted(VALID_HORIZONS)}")
    gen = _CANDIDATE_GENERATORS.get(family)
    if gen is None:
        raise ValueError(f"No candidate generator registered for family {family!r}")
    return gen(horizon)


def variant_min_history(variant: VariantDef) -> int:
    """Minimum bars needed before a variant's signal is reasonably warmed."""
    p = variant.params
    arch = variant.archetype

    if arch == COMBO_ARCHETYPE and isinstance(p.get("components"), list):
        components = [
            variant_from_component(payload)
            for payload in p.get("components", [])
            if isinstance(payload, dict)
        ]
        if components:
            return max(variant_min_history(component) for component in components)
        return 1
    if arch == "price_vs_sma":
        return int(p["window"])
    if arch == "sma_cross":
        return int(p["slow"])
    if arch == "slope_confirmed":
        return int(p["window"]) + int(p.get("slope_lookback", 1))
    if arch == "price_vs_ema":
        return int(p["window"])
    if arch == "ema_cross":
        return int(p["slow"])
    if arch == "ichi_cloud":
        return int(p["senkou_b"])
    if arch == "psar_trend":
        return 2
    if arch == "rsi_level":
        return int(p["period"]) + 1
    if arch == "macd_cross":
        return int(p["slow"]) + int(p["signal"])
    if arch == "roc_zero":
        return int(p["period"])
    if arch == "trix_zero":
        return 3 * int(p["period"])
    if arch == "adx_trend":
        return 2 * int(p["period"])
    if arch == "tsi_zero":
        return int(p["quarterly_period"]) + int(p["weekly_period"])
    if arch == "stoch_level":
        return int(p["k_period"]) + int(p["d_period"])
    if arch == "cci_level":
        return int(p["period"])
    if arch == "mfi_level":
        return int(p["period"])
    if arch == "uo_level":
        return int(p["period_3"])
    if arch == "obv_trend":
        return int(p["ema_period"])
    if arch == "cmf_flow":
        return int(p["period"])
    if arch == "ad_trend":
        return int(p["ema_period"])
    if arch == "vwap_dev":
        return int(p["period"])
    if arch == "fi_trend":
        return int(p["period"])
    return 1


def filter_candidates_for_history(candidates: list[VariantDef], max_history: int) -> list[VariantDef]:
    """Keep candidates whose warmup fits inside the provided bar budget."""
    if max_history <= 0:
        return []
    return [c for c in candidates if variant_min_history(c) <= max_history]


def _dense_int_grid(low: int, high: int, n: int = 30) -> list[int]:
    """Build a dense integer grid, widening the upper bound until *n* values exist."""
    if high < low:
        raise ValueError(f"Expected low <= high, got {low} > {high}")
    values = list(range(low, high + 1))
    next_value = high + 1
    while len(values) < n:
        values.append(next_value)
        next_value += 1
    return values[:n]


def _anchored_int_grid(low: int, high: int, n: int, anchors: tuple[int, ...] = ()) -> list[int]:
    """Select *n* deterministic integers spanning a band while preserving anchors."""
    if high < low:
        raise ValueError(f"Expected low <= high, got {low} > {high}")
    if n <= 0:
        return []
    if (high - low + 1) <= n:
        return _dense_int_grid(low, high, n)

    selected = {low, high}
    selected.update(anchor for anchor in anchors if low <= anchor <= high)

    idx = 0
    while len(selected) < n:
        target = low + ((high - low) * idx / max(n - 1, 1))
        selected.add(int(round(target)))
        idx += 1
        if idx > (n * 4):
            break

    if len(selected) < n:
        for value in range(low, high + 1):
            selected.add(value)
            if len(selected) >= n:
                break

    return sorted(selected)[:n]


_TREND_WINDOWS: dict[str, list[int]] = {
    "weekly": _dense_int_grid(5, 20),
    "monthly": _anchored_int_grid(21, 80, 30, anchors=(50,)),
    "quarterly": _anchored_int_grid(120, 250, 30, anchors=(200,)),
}

_EMA_CROSS_PARAMS: dict[str, dict[str, list[int]]] = {
    "weekly": {"fast": [3, 4, 5, 6, 8, 10], "slow": [12, 15, 18, 20, 25]},
    "monthly": {"fast": [8, 10, 12, 14, 16, 20], "slow": [26, 34, 42, 50, 60]},
    "quarterly": {"fast": [20, 26, 32, 38, 44, 50], "slow": [60, 90, 120, 150, 200]},
}

_ICHIMOKU_PARAMS: dict[str, dict[str, list[int]]] = {
    "weekly": {"tenkan": [5, 6, 7, 9, 10], "kijun": [12, 16, 20], "senkou_b": [22, 40]},
    "monthly": {"tenkan": [9, 11, 13, 15, 18], "kijun": [22, 26, 40], "senkou_b": [52, 80]},
    "quarterly": {"tenkan": [18, 21, 24, 27, 30], "kijun": [40, 60, 80], "senkou_b": [90, 180]},
}

_PSAR_PARAMS: dict[str, dict[str, list[float]]] = {
    "weekly": {
        "af_step": [0.025, 0.03, 0.035, 0.04, 0.045, 0.05],
        "af_max": [0.20, 0.25, 0.30, 0.35, 0.40],
    },
    "monthly": {
        "af_step": [0.01, 0.015, 0.02, 0.025, 0.03],
        "af_max": [0.15, 0.20, 0.25, 0.30, 0.40, 0.50],
    },
    "quarterly": {
        "af_step": [0.005, 0.0075, 0.01, 0.0125, 0.015],
        "af_max": [0.08, 0.10, 0.12, 0.15, 0.18, 0.22],
    },
}

_MACD_PARAMS: dict[str, dict[str, list[int]]] = {
    "weekly": {"fast": [5, 6, 7, 8, 10], "slow": [12, 17, 20], "signal": [5, 9]},
    "monthly": {"fast": [10, 12, 14, 16, 18], "slow": [22, 26, 45], "signal": [7, 9]},
    "quarterly": {"fast": [18, 21, 24, 27, 30], "slow": [50, 75, 100], "signal": [9, 18]},
}

_ROC_PERIODS: dict[str, list[int]] = {
    "weekly": _dense_int_grid(5, 20),
    "monthly": _anchored_int_grid(22, 80, 30, anchors=(60,)),
    "quarterly": _anchored_int_grid(120, 250, 30, anchors=(200,)),
}

_TRIX_PERIODS: dict[str, list[int]] = {
    "weekly": _dense_int_grid(2, 7),
    # The recalibration ADR's raw 7-27 monthly band only yields 21 integers.
    # Apply the same widening rule used everywhere else to satisfy the 30-slot contract.
    "monthly": _dense_int_grid(7, 27),
    "quarterly": _anchored_int_grid(40, 84, 30),
}

_ADX_PERIODS: dict[str, list[int]] = {
    "weekly": list(range(5, 15)),
    "monthly": _anchored_int_grid(14, 30, 10, anchors=(14,)),
    "quarterly": _anchored_int_grid(25, 50, 10),
}
_ADX_THRESHOLDS: dict[str, list[int]] = {
    "weekly": [20, 25, 30],
    "monthly": [20, 25, 30],
    "quarterly": [25, 30, 35],
}

_TSI_PARAMS: dict[str, dict[str, list[int]]] = {
    "weekly": {"quarterly_period": [9, 11, 13, 15, 17, 18], "weekly_period": [4, 5, 6, 7, 8]},
    "monthly": {"quarterly_period": [20, 25, 28, 32, 36, 40], "weekly_period": [10, 12, 13, 15, 18]},
    "quarterly": {"quarterly_period": [45, 50, 55, 60, 70, 80], "weekly_period": [15, 18, 21, 24, 30]},
}

_RSI_PERIODS: dict[str, list[int]] = {
    "weekly": list(range(5, 15)),
    "monthly": _anchored_int_grid(14, 28, 10, anchors=(21,)),
    "quarterly": _anchored_int_grid(21, 50, 10),
}
_RSI_THRESHOLDS: dict[str, list[tuple[int, int]]] = {
    "weekly": [(30, 70), (25, 75), (20, 80)],
    "monthly": [(25, 75), (20, 80), (15, 85)],
    "quarterly": [(20, 80), (15, 85), (10, 90)],
}

_STOCHASTIC_PARAMS: dict[str, dict[str, list[int]]] = {
    "weekly": {"k_period": list(range(5, 15)), "d_period": [3, 5, 7]},
    "monthly": {"k_period": _anchored_int_grid(14, 28, 10, anchors=(14,)), "d_period": [3, 5, 7]},
    "quarterly": {"k_period": _anchored_int_grid(21, 50, 10), "d_period": [5, 7, 9]},
}

_CCI_PERIODS: dict[str, list[int]] = {
    "weekly": _dense_int_grid(5, 20),
    "monthly": _anchored_int_grid(22, 80, 30),
    "quarterly": _anchored_int_grid(120, 250, 30, anchors=(200,)),
}

_MFI_PERIODS: dict[str, list[int]] = {
    "weekly": list(range(5, 15)),
    "monthly": _anchored_int_grid(14, 28, 10, anchors=(14,)),
    "quarterly": _anchored_int_grid(21, 50, 10),
}
_MFI_THRESHOLDS: dict[str, list[tuple[int, int]]] = {
    "weekly": [(20, 80), (15, 85), (10, 90)],
    "monthly": [(20, 80), (15, 85), (10, 90)],
    "quarterly": [(20, 80), (15, 85), (10, 90)],
}

_UO_PARAMS: dict[str, dict[str, list[int]]] = {
    "weekly": {"period_1": [4, 5, 6, 7, 8], "period_2": [9, 11, 14], "period_3": [18, 28]},
    "monthly": {"period_1": [7, 8, 9, 11, 13], "period_2": [14, 21, 27], "period_3": [28, 56]},
    "quarterly": {"period_1": [14, 16, 18, 21, 24], "period_2": [25, 35, 49], "period_3": [50, 100]},
}

_OBV_EMA_PERIODS = _TREND_WINDOWS

_CMF_PERIODS: dict[str, list[int]] = {
    "weekly": _dense_int_grid(5, 20),
    "monthly": _anchored_int_grid(22, 80, 30),
    "quarterly": _anchored_int_grid(80, 150, 30),
}

_AD_EMA_PERIODS = _TREND_WINDOWS

_VWAP_PARAMS: dict[str, dict[str, list[float | int]]] = {
    "weekly": {"period": _anchored_int_grid(5, 20, 10), "threshold_pct": [0.5, 1.0, 2.0]},
    "monthly": {"period": _anchored_int_grid(22, 80, 10), "threshold_pct": [0.5, 1.0, 2.0]},
    "quarterly": {"period": _anchored_int_grid(120, 250, 10), "threshold_pct": [1.0, 2.0, 3.0]},
}

_FI_PERIODS: dict[str, list[int]] = {
    "weekly": _dense_int_grid(2, 2),
    "monthly": _TREND_WINDOWS["monthly"],
    "quarterly": _TREND_WINDOWS["quarterly"],
}


def _install_canonical_horizon_keys(grid: dict) -> None:
    """Expose the new horizon names while preserving existing grid definitions."""
    aliases = {"weekly": "weekly", "monthly": "monthly", "quarterly": "quarterly"}
    for new_key, old_key in aliases.items():
        if old_key in grid and new_key not in grid:
            grid[new_key] = grid[old_key]


for _grid in (
    _TREND_WINDOWS,
    _EMA_CROSS_PARAMS,
    _ICHIMOKU_PARAMS,
    _PSAR_PARAMS,
    _MACD_PARAMS,
    _ROC_PERIODS,
    _TRIX_PERIODS,
    _ADX_PERIODS,
    _ADX_THRESHOLDS,
    _TSI_PARAMS,
    _RSI_PERIODS,
    _RSI_THRESHOLDS,
    _STOCHASTIC_PARAMS,
    _CCI_PERIODS,
    _MFI_PERIODS,
    _MFI_THRESHOLDS,
    _UO_PARAMS,
    _OBV_EMA_PERIODS,
    _CMF_PERIODS,
    _AD_EMA_PERIODS,
    _VWAP_PARAMS,
    _FI_PERIODS,
):
    _install_canonical_horizon_keys(_grid)


def _make_variant(family: str, archetype: str, params: dict, horizon: str) -> VariantDef:
    hash_params = {"archetype": archetype, **params}
    variant_id = compute_variant_id(family, hash_params)
    if archetype == "price_vs_sma":
        description = f"SMA-{params['window']}"
    elif archetype == "price_vs_ema":
        description = f"EMA-{params['window']}"
    elif archetype == "ema_cross":
        description = f"EMA({params['fast']},{params['slow']})"
    elif archetype == "ichi_cloud":
        description = f"Ichimoku({params['tenkan']},{params['kijun']},{params['senkou_b']})"
    elif archetype == "psar_trend":
        description = f"PSAR({params['af_step']},{params['af_max']})"
    elif archetype == "rsi_level":
        description = f"RSI-{params['period']} ({params['oversold']}/{params['overbought']})"
    elif archetype == "macd_cross":
        description = f"MACD({params['fast']},{params['slow']},{params['signal']})"
    elif archetype == "roc_zero":
        description = f"ROC-{params['period']}"
    elif archetype == "trix_zero":
        description = f"TRIX-{params['period']}"
    elif archetype == "adx_trend":
        description = f"ADX({params['period']},{params['adx_threshold']})"
    elif archetype == "tsi_zero":
        description = f"TSI({params['quarterly_period']},{params['weekly_period']})"
    elif archetype == "stoch_level":
        description = f"STOCH({params['k_period']},{params['d_period']})"
    elif archetype == "cci_level":
        description = f"CCI-{params['period']}"
    elif archetype == "mfi_level":
        description = f"MFI-{params['period']} ({params['oversold']}/{params['overbought']})"
    elif archetype == "uo_level":
        description = f"UO({params['period_1']},{params['period_2']},{params['period_3']})"
    elif archetype == "obv_trend":
        description = f"OBV-EMA-{params['ema_period']}"
    elif archetype == "cmf_flow":
        description = f"CMF-{params['period']}"
    elif archetype == "ad_trend":
        description = f"AD-EMA-{params['ema_period']}"
    elif archetype == "vwap_dev":
        description = f"VWAP({params['period']},{params['threshold_pct']})"
    elif archetype == "fi_trend":
        description = f"FI-{params['period']}"
    else:
        description = f"{family}:{archetype}"
    return VariantDef(
        variant_id=variant_id,
        family=family,
        archetype=archetype,
        params=params,
        description=f"{description} ({horizon})",
    )


def _take_first_n(items: list[VariantDef], expected: int = 30) -> list[VariantDef]:
    if len(items) < expected:
        raise ValueError(f"Expected at least {expected} candidates, got {len(items)}")
    return items[:expected]


@register_family("sma")
def generate_sma_candidates(horizon: str) -> list[VariantDef]:
    windows = cap_param_grid(_TREND_WINDOWS[horizon], HORIZON_PARAM_CAP[horizon]["sma"])
    return [_make_variant("sma", "price_vs_sma", {"window": w}, horizon) for w in windows]


@register_family("ema")
def generate_ema_candidates(horizon: str) -> list[VariantDef]:
    windows = cap_param_grid(_TREND_WINDOWS[horizon], HORIZON_PARAM_CAP[horizon]["ema"])
    return [_make_variant("ema", "price_vs_ema", {"window": w}, horizon) for w in windows]


@register_family("ema_cross")
def generate_ema_cross_candidates(horizon: str) -> list[VariantDef]:
    cfg = _EMA_CROSS_PARAMS[horizon]
    items = [
        _make_variant("ema_cross", "ema_cross", {"fast": fast, "slow": slow}, horizon)
        for slow in cfg["slow"]
        for fast in cfg["fast"]
        if fast < slow
    ]
    return _take_first_n(items)


@register_family("ichimoku")
def generate_ichimoku_candidates(horizon: str) -> list[VariantDef]:
    cfg = _ICHIMOKU_PARAMS[horizon]
    kijun_vals = cap_param_grid(cfg["kijun"], HORIZON_PARAM_CAP[horizon]["ichimoku_kijun"])
    return [
        _make_variant(
            "ichimoku",
            "ichi_cloud",
            {"tenkan": tenkan, "kijun": kijun, "senkou_b": senkou_b},
            horizon,
        )
        for senkou_b in cfg["senkou_b"]
        for kijun in kijun_vals
        for tenkan in cfg["tenkan"]
        if tenkan < kijun < senkou_b
    ]


@register_family("psar")
def generate_psar_candidates(horizon: str) -> list[VariantDef]:
    cfg = _PSAR_PARAMS[horizon]
    return [
        _make_variant("psar", "psar_trend", {"af_step": step, "af_max": max_}, horizon)
        for step in cfg["af_step"]
        for max_ in cfg["af_max"]
    ]


@register_family("macd")
def generate_macd_candidates(horizon: str) -> list[VariantDef]:
    cfg = _MACD_PARAMS[horizon]
    slow_vals = cap_param_grid(cfg["slow"], HORIZON_PARAM_CAP[horizon]["macd_slow"])
    return [
        _make_variant(
            "macd",
            "macd_cross",
            {"fast": fast, "slow": slow, "signal": signal},
            horizon,
        )
        for slow in slow_vals
        for fast in cfg["fast"]
        for signal in cfg["signal"]
        if fast < slow
    ]


@register_family("roc")
def generate_roc_candidates(horizon: str) -> list[VariantDef]:
    return [_make_variant("roc", "roc_zero", {"period": p}, horizon) for p in _ROC_PERIODS[horizon]]


@register_family("trix")
def generate_trix_candidates(horizon: str) -> list[VariantDef]:
    return [_make_variant("trix", "trix_zero", {"period": p}, horizon) for p in _TRIX_PERIODS[horizon]]


@register_family("adx")
def generate_adx_candidates(horizon: str) -> list[VariantDef]:
    return [
        _make_variant("adx", "adx_trend", {"period": period, "adx_threshold": threshold}, horizon)
        for period in _ADX_PERIODS[horizon]
        for threshold in _ADX_THRESHOLDS[horizon]
    ]


@register_family("tsi")
def generate_tsi_candidates(horizon: str) -> list[VariantDef]:
    cfg = _TSI_PARAMS[horizon]
    items = [
        _make_variant(
            "tsi",
            "tsi_zero",
            {"quarterly_period": quarterly_period, "weekly_period": weekly_period},
            horizon,
        )
        for quarterly_period in cfg["quarterly_period"]
        for weekly_period in cfg["weekly_period"]
        if quarterly_period > weekly_period
    ]
    return _take_first_n(items)


@register_family("rsi")
def generate_rsi_candidates(horizon: str) -> list[VariantDef]:
    periods = cap_param_grid(_RSI_PERIODS[horizon], HORIZON_PARAM_CAP[horizon]["rsi"])
    return [
        _make_variant(
            "rsi",
            "rsi_level",
            {"period": period, "oversold": oversold, "overbought": overbought},
            horizon,
        )
        for period in periods
        for oversold, overbought in _RSI_THRESHOLDS[horizon]
    ]


@register_family("stochastic")
def generate_stochastic_candidates(horizon: str) -> list[VariantDef]:
    cfg = _STOCHASTIC_PARAMS[horizon]
    k_periods = cap_param_grid(cfg["k_period"], HORIZON_PARAM_CAP[horizon]["stoch"])
    return [
        _make_variant("stochastic", "stoch_level", {"k_period": k, "d_period": d}, horizon)
        for k in k_periods
        for d in cfg["d_period"]
    ]


@register_family("cci")
def generate_cci_candidates(horizon: str) -> list[VariantDef]:
    return [_make_variant("cci", "cci_level", {"period": p}, horizon) for p in _CCI_PERIODS[horizon]]


@register_family("mfi")
def generate_mfi_candidates(horizon: str) -> list[VariantDef]:
    return [
        _make_variant(
            "mfi",
            "mfi_level",
            {"period": period, "oversold": oversold, "overbought": overbought},
            horizon,
        )
        for period in _MFI_PERIODS[horizon]
        for oversold, overbought in _MFI_THRESHOLDS[horizon]
    ]


@register_family("uo")
def generate_uo_candidates(horizon: str) -> list[VariantDef]:
    cfg = _UO_PARAMS[horizon]
    items = [
        _make_variant(
            "uo",
            "uo_level",
            {"period_1": p1, "period_2": p2, "period_3": p3},
            horizon,
        )
        for p3 in cfg["period_3"]
        for p2 in cfg["period_2"]
        for p1 in cfg["period_1"]
        if p1 < p2 < p3
    ]
    return _take_first_n(items)


@register_family("obv")
def generate_obv_candidates(horizon: str) -> list[VariantDef]:
    periods = cap_param_grid(_OBV_EMA_PERIODS[horizon], HORIZON_PARAM_CAP[horizon]["obv_ema"])
    return [_make_variant("obv", "obv_trend", {"ema_period": p}, horizon) for p in periods]


@register_family("cmf")
def generate_cmf_candidates(horizon: str) -> list[VariantDef]:
    return [_make_variant("cmf", "cmf_flow", {"period": p}, horizon) for p in _CMF_PERIODS[horizon]]


@register_family("ad")
def generate_ad_candidates(horizon: str) -> list[VariantDef]:
    return [_make_variant("ad", "ad_trend", {"ema_period": p}, horizon) for p in _AD_EMA_PERIODS[horizon]]


@register_family("vwap")
def generate_vwap_candidates(horizon: str) -> list[VariantDef]:
    cfg = _VWAP_PARAMS[horizon]
    return [
        _make_variant("vwap", "vwap_dev", {"period": int(period), "threshold_pct": float(threshold)}, horizon)
        for period in cfg["period"]
        for threshold in cfg["threshold_pct"]
    ]


@register_family("fi")
def generate_fi_candidates(horizon: str) -> list[VariantDef]:
    return [_make_variant("fi", "fi_trend", {"period": p}, horizon) for p in _FI_PERIODS[horizon]]


# ---------------------------------------------------------------------------
# Phase 2 — factor-conditioned candidate generation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# TA combo candidate generation
# ---------------------------------------------------------------------------

_COMBO_SEEDS_PER_FAMILY = 5
_PURE_COMBO_FAMILY_PREFIXES: dict[str, dict[str, list[str]]] = {
    "legacy_ta_combo": LEGACY_CATEGORY_FAMILIES,
    "expanded_ta_combo": CATEGORY_FAMILIES,
}


def _select_evenly_spaced(items: list[VariantDef], limit: int = _COMBO_SEEDS_PER_FAMILY) -> list[VariantDef]:
    if len(items) <= limit:
        return list(items)
    if limit <= 1:
        return [items[0]]
    indices: list[int] = []
    for idx in range(limit):
        raw = round(idx * (len(items) - 1) / (limit - 1))
        if raw not in indices:
            indices.append(raw)
    return [items[idx] for idx in indices]


def _combo_meta_for_family(family: str) -> tuple[str, str, dict[str, list[str]]] | None:
    for prefix, category_map in _PURE_COMBO_FAMILY_PREFIXES.items():
        marker = f"{prefix}_"
        if family.startswith(marker):
            category = family[len(marker):]
            if category in CATEGORY_FAMILIES:
                return prefix, category, category_map
    return None


def _generate_ta_combo_candidates_for_family(family: str, horizon: str) -> list[VariantDef]:
    meta = _combo_meta_for_family(family)
    if meta is None:
        raise ValueError(f"Unknown TA combo family {family!r}")
    _prefix, target_category, category_map = meta
    family_to_category = {
        base_family: category
        for category, families in category_map.items()
        for base_family in families
    }
    ordered_families = [
        base_family
        for category in ("tendance", "momentum", "oscillation", "volume")
        for base_family in category_map.get(category, [])
    ]
    seeds_by_family = {
        base_family: _select_evenly_spaced(generate_candidates(base_family, horizon))
        for base_family in ordered_families
    }

    out: list[VariantDef] = []
    for left_idx, left_family in enumerate(ordered_families):
        for right_family in ordered_families[left_idx + 1:]:
            primary_category = primary_category_for_families([left_family, right_family], family_to_category)
            if primary_category != target_category:
                continue
            for left_variant, right_variant in zip(
                seeds_by_family[left_family],
                seeds_by_family[right_family],
                strict=False,
            ):
                out.append(
                    make_combo_variant(
                        family=family,
                        components=[left_variant, right_variant],
                        primary_category=primary_category,
                        horizon=horizon,
                        conditioning="ta",
                    )
                )
    return out


for _combo_family in (
    "legacy_ta_combo_tendance",
    "legacy_ta_combo_momentum",
    "legacy_ta_combo_oscillation",
    "legacy_ta_combo_volume",
    "expanded_ta_combo_tendance",
    "expanded_ta_combo_momentum",
    "expanded_ta_combo_oscillation",
    "expanded_ta_combo_volume",
):
    _CANDIDATE_GENERATORS[_combo_family] = (
        lambda horizon, _family=_combo_family: _generate_ta_combo_candidates_for_family(_family, horizon)
    )


def generate_factor_conditioned_candidates(
    ta_candidates: list[VariantDef],
    conditions: list,  # list[FactorConditionMeta]
    channel_tags: dict[str, list[str]] | None = None,
    stock_sector: str | None = None,
    active_factors: list[str] | None = None,
) -> list[VariantDef]:
    """Cross-product Layer A extension: TA variants × factor conditions.

    Args:
        ta_candidates:  Native TA variants from generate_candidates().
        conditions:     List of FactorConditionMeta to cross with.
        channel_tags:   Optional {factor_ticker: [sector, ...]} gate. When provided
                        and stock_sector is set, only conditions whose factor_ticker
                        has a channel tag matching the stock's sector are included.
                        Pass None or omit to disable gating (all conditions used).
        stock_sector:   Sector string for the target stock, used with channel_tags.
        active_factors: Optional list of factor tickers that were dynamically selected 
                        for this stock by the Phase 3 econometric pipeline. If provided,
                        only conditions matching these factors are generated.

    Returns:
        List of VariantDef with family="{ta_family}@fx" and factor_condition set.
        The list is bounded to len(ta_candidates) × len(applicable_conditions).
    """
    from core.quant_core.research.factors.conditioned_variants import make_conditioned_variant

    applicable_conditions = _filter_conditions_by_channel(conditions, channel_tags, stock_sector)
    
    if active_factors is not None:
        # Filter down to only those dynamically selected for this stock
        applicable_conditions = [
            c for c in applicable_conditions if c.factor_ticker in active_factors
        ]

    if not applicable_conditions:
        return []

    result: list[VariantDef] = []
    for ta_variant in ta_candidates:
        for condition in applicable_conditions:
            result.append(make_conditioned_variant(ta_variant, condition))
    return result


def _filter_conditions_by_channel(
    conditions: list,
    channel_tags: dict[str, list[str]] | None,
    stock_sector: str | None,
) -> list:
    """Return only conditions applicable to the given stock sector.

    If channel_tags is None or stock_sector is None, all conditions pass.
    A condition passes if its factor_ticker has no explicit channel restriction,
    or if the stock_sector is in the factor's channel tag list.
    """
    if channel_tags is None or stock_sector is None:
        return conditions
    sector = stock_sector.lower()
    out = []
    for cond in conditions:
        allowed_sectors = channel_tags.get(cond.factor_ticker)
        allowed = [str(s).lower() for s in allowed_sectors or []]
        if allowed_sectors is None or not allowed or "all" in allowed or sector in allowed:
            out.append(cond)
    return out
