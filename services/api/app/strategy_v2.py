"""Canonical Strategy V2 helpers for the four-page flow.

This module intentionally keeps the new Strategy/Backtest data model isolated
from legacy page contracts while still providing migration helpers so existing
saved strategies can be read safely.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from core.quant_core.strategy_plan.score_sources import (
    BASE_SCORE_KEYS,
    BASE_SCORE_LABELS,
    FAMILY_IDS,
    default_family_signal_config,
    score_variable_keys,
)

HORIZON_KEYS = ("short", "medium", "long")
CONFIG_OPTIONS = {"A", "B", "C", "D", "E"}
RULE_OPERATORS = {">", ">=", "<", "<="}
RULE_SIZING_MODELS = {"manual", "wfo", "kelly_wfo"}
INTEGER_WFO_PARAM_SUFFIXES = (
    ".window",
    ".period",
    ".fast",
    ".slow",
    ".signal",
    ".ema_period",
    ".tenkan",
    ".kijun",
    ".senkou_b",
    ".k_period",
    ".d_period",
    ".period_1",
    ".period_2",
    ".period_3",
    ".long_period",
    ".short_period",
    ".adx_threshold",
    ".bars",
    ".cooldown_bars",
)
RULE_DIRECT_SIZING_DEFAULT = {"scan_min": 25.0, "scan_max": 100.0, "scan_step": 25.0}


def default_holding_bars(horizon: str) -> int:
    if str(horizon).strip().lower() == "short":
        return 10
    if str(horizon).strip().lower() == "long":
        return 60
    return 30


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def _to_float(value: Any, default: float) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _to_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return bool(value)


def _to_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _normalize_signal_candidate_ref(raw: Any) -> dict[str, Any] | None:
    record = raw if _is_record(raw) else {}
    symbol = _optional_string(record.get("symbol"))
    source = _optional_string(record.get("source"))
    variant = _optional_string(record.get("variant"))
    if not symbol or not source or not variant:
        return None

    candidate_id = _optional_string(record.get("candidate_id")) or ":".join(
        [
            symbol.upper(),
            source,
            variant,
            _optional_string(record.get("bucket")) or "",
            _optional_string(record.get("direction")) or "",
            str(_optional_int(record.get("fwd_horizon_bars")) or ""),
        ]
    ).lower()
    gates_raw = record.get("gates") if _is_record(record.get("gates")) else {}
    gates = {str(key): bool(value) for key, value in gates_raw.items()}
    return {
        "candidate_id": candidate_id,
        "symbol": symbol.upper(),
        "source": source,
        "variant": variant,
        "label": _optional_string(record.get("label")),
        "triage": _optional_string(record.get("triage")) or "watch",
        "bucket": _optional_string(record.get("bucket")),
        "direction": _optional_string(record.get("direction")),
        "signal_label": _optional_string(record.get("signal_label")),
        "score": _optional_float(record.get("score")),
        "action_expected_return_net": _optional_float(record.get("action_expected_return_net")),
        "action_expected_return_net_ci_lower": _optional_float(record.get("action_expected_return_net_ci_lower")),
        "action_expected_return_net_ci_upper": _optional_float(record.get("action_expected_return_net_ci_upper")),
        "hit_rate": _optional_float(record.get("hit_rate")),
        "hit_ci_lower": _optional_float(record.get("hit_ci_lower")),
        "hit_ci_upper": _optional_float(record.get("hit_ci_upper")),
        "n": _optional_int(record.get("n")),
        "proof_n": _optional_int(record.get("proof_n")),
        "proof_window_start": _optional_string(record.get("proof_window_start")),
        "proof_window_end": _optional_string(record.get("proof_window_end")),
        "fwd_horizon_bars": _optional_int(record.get("fwd_horizon_bars")),
        "return_calc_method": _optional_string(record.get("return_calc_method")),
        "entry_price_kind": _optional_string(record.get("entry_price_kind")),
        "entry_lag_bars": _optional_int(record.get("entry_lag_bars")),
        "exit_price_kind": _optional_string(record.get("exit_price_kind")),
        "exit_lag_bars": _optional_int(record.get("exit_lag_bars")),
        "exit_timing_label": _optional_string(record.get("exit_timing_label")),
        "gates": gates,
        "proven_edge_net": bool(record.get("proven_edge_net")) if record.get("proven_edge_net") is not None else None,
    }


def _normalize_signal_candidate_refs(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        ref = _normalize_signal_candidate_ref(item)
        if ref is None:
            continue
        key = str(ref.get("candidate_id") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _manual_param(value: float | int) -> dict[str, Any]:
    return {"mode": "manual", "value": value}


def _wfo_param(
    value: float | int,
    *,
    search_spaces_by_horizon: dict[str, dict[str, float]] | None = None,
    horizon: str,
) -> dict[str, Any]:
    spaces = search_spaces_by_horizon or _ensure_horizon_search_spaces(
        None,
        scan_min=float(value),
        scan_max=float(value),
        scan_step=_default_scan_step(float(value)),
    )
    active_space = spaces[_normalize_horizon_key(horizon)]
    return {
        "mode": "wfo",
        "value": float(value),
        "scan_min": active_space["scan_min"],
        "scan_max": active_space["scan_max"],
        "scan_step": active_space["scan_step"],
        "search_spaces_by_horizon": spaces,
    }


def _normalize_horizon_key(horizon: str) -> str:
    value = str(horizon).strip().lower()
    if value in HORIZON_KEYS:
        return value
    return "medium"


def _default_scan_step(value: float) -> float:
    return 1.0 if float(value).is_integer() else 0.1


def _ensure_horizon_search_spaces(
    raw: Any,
    *,
    scan_min: float,
    scan_max: float,
    scan_step: float,
) -> dict[str, dict[str, float]]:
    record = raw if _is_record(raw) else {}
    out: dict[str, dict[str, float]] = {}
    for horizon in HORIZON_KEYS:
        item = record.get(horizon) if _is_record(record) else None
        item_record = item if _is_record(item) else {}
        out[horizon] = {
            "scan_min": _to_float(item_record.get("scan_min"), scan_min),
            "scan_max": _to_float(item_record.get("scan_max"), scan_max),
            "scan_step": _to_float(item_record.get("scan_step"), scan_step),
        }
    return out


def _rule_direct_sizing_default_spaces(value: float) -> dict[str, dict[str, float]]:
    return {
        horizon: {
            "scan_min": min(RULE_DIRECT_SIZING_DEFAULT["scan_min"], value),
            "scan_max": max(RULE_DIRECT_SIZING_DEFAULT["scan_max"], value),
            "scan_step": RULE_DIRECT_SIZING_DEFAULT["scan_step"],
        }
        for horizon in HORIZON_KEYS
    }


def default_family_configs() -> dict[str, Any]:
    return {
        family_id: default_family_signal_config(family_id=family_id, enabled=family_id == "sma")
        for family_id in FAMILY_IDS
    }


def default_entry_rule(index: int = 0) -> dict[str, Any]:
    return {
        "id": f"entry_{index + 1}",
        "label": f"Entree {index + 1}",
        "config_option": "A",
        "conditions": [],
        "sizing": {
            "mode": "manual",
            "manual_pct": 25.0,
            "size_pct": None,
            "kelly_modifier": None,
        },
    }


def default_exit_rule(index: int = 0) -> dict[str, Any]:
    return {
        "id": f"exit_{index + 1}",
        "label": f"Sortie {index + 1}",
        "config_option": "A",
        "conditions": [],
        "sizing": {
            "mode": "manual",
            "manual_pct": 100.0,
            "reduction_pct": None,
            "kelly_modifier": None,
        },
    }


def default_stock_strategy_config(*, horizon: str) -> dict[str, Any]:
    return {
        "strategy_type": "trend_following",
        "signal_construction": {
            "families": default_family_configs(),
        },
        "entry_rules": [],
        "exit_rules": [],
        "risk": {
            "stop_loss": {
                "mode": "atr_based",
                "atr_multiplier": _manual_param(1.5),
            },
            "take_profit": {
                "mode": "rr_target",
                "rr_ratio": _manual_param(1.5),
            },
            "cooldown_bars": _manual_param(0),
            "time_stop": {
                "enabled": True,
                "bars": _manual_param(default_holding_bars(horizon)),
            },
            "trailing_stop_enabled": False,
            "max_position_pct": 20.0,
            "max_sector_pct": 40.0,
        },
    }


def _normalize_wfo_param(raw: Any, *, default_value: float | int, horizon: str) -> dict[str, Any]:
    if not _is_record(raw):
        return _manual_param(default_value)

    mode = str(raw.get("mode") or "manual").strip().lower()
    if mode != "wfo":
        return {
            "mode": "manual",
            "value": _to_float(raw.get("value"), float(default_value)),
        }

    value = _to_float(raw.get("value"), float(default_value))
    scan_min = _to_float(raw.get("scan_min"), value)
    scan_max = _to_float(raw.get("scan_max"), value)
    scan_step = _to_float(raw.get("scan_step"), max(abs(value) * 0.1, _default_scan_step(value)))
    search_spaces_by_horizon = _ensure_horizon_search_spaces(
        raw.get("search_spaces_by_horizon"),
        scan_min=scan_min,
        scan_max=scan_max,
        scan_step=scan_step,
    )
    active_space = search_spaces_by_horizon[_normalize_horizon_key(horizon)]
    return {
        "mode": "wfo",
        "value": value,
        "scan_min": active_space["scan_min"],
        "scan_max": active_space["scan_max"],
        "scan_step": active_space["scan_step"],
        "search_spaces_by_horizon": search_spaces_by_horizon,
    }


def _normalize_rule_direct_sizing_param(raw: Any, *, default_value: float, horizon: str) -> dict[str, Any]:
    record = raw if _is_record(raw) else {}
    mode = str(record.get("mode") or "wfo").strip().lower()
    value = _to_float(record.get("value"), default_value)
    default_spaces = _rule_direct_sizing_default_spaces(value)
    if mode != "wfo":
        active_space = default_spaces[_normalize_horizon_key(horizon)]
        record = {
            "mode": "wfo",
            "value": value,
            "scan_min": active_space["scan_min"],
            "scan_max": active_space["scan_max"],
            "scan_step": active_space["scan_step"],
            "search_spaces_by_horizon": default_spaces,
        }
    elif (
        not _is_record(record.get("search_spaces_by_horizon"))
        and record.get("scan_min") is None
        and record.get("scan_max") is None
        and record.get("scan_step") is None
    ):
        active_space = default_spaces[_normalize_horizon_key(horizon)]
        record = {
            **record,
            "search_spaces_by_horizon": default_spaces,
            "scan_min": active_space["scan_min"],
            "scan_max": active_space["scan_max"],
            "scan_step": active_space["scan_step"],
        }
    return _normalize_wfo_param(record, default_value=default_value, horizon=horizon)


def _normalize_rule_sizing_mode(value: Any, *, allow_kelly: bool) -> str:
    mode = str(value or "manual").strip().lower()
    allowed = RULE_SIZING_MODELS if allow_kelly else {"manual", "wfo"}
    return mode if mode in allowed else "manual"


def _legacy_direct_sizing_source(sizing: dict[str, Any], key: str) -> Any:
    source = sizing.get(key)
    if _is_record(source):
        return source
    legacy = sizing.get("kelly_modifier")
    if _is_record(legacy) and str(legacy.get("mode") or "").strip().lower() == "wfo":
        return legacy
    return None


def _default_family_row_config(family_id: str, index: int = 0) -> dict[str, Any]:
    family = default_family_signal_config(family_id=family_id)
    return deepcopy((family.get("rows") or [{}])[0])


def _family_score_key(family_id: str) -> str:
    return BASE_SCORE_KEYS[family_id]


def _family_score_label(family_id: str) -> str:
    return BASE_SCORE_LABELS[family_id]


def _next_score_key(family_id: str, used_keys: set[str]) -> str:
    base = _family_score_key(family_id)
    if base not in used_keys:
        return base
    suffix = 2
    while f"{base}_{suffix}" in used_keys:
        suffix += 1
    return f"{base}_{suffix}"


def _normalize_indicator_row(
    raw: Any,
    *,
    family_id: str,
    index: int,
    horizon: str,
    used_keys: set[str],
) -> dict[str, Any]:
    record = raw if _is_record(raw) else {}
    default_row = _default_family_row_config(family_id, index=index)
    score_key_raw = str(record.get("score_key") or "").strip().lower()
    score_key = score_key_raw or _next_score_key(family_id, used_keys)
    if score_key in used_keys and score_key != score_key_raw:
        score_key = _next_score_key(family_id, used_keys)
    used_keys.add(score_key)
    params_raw = record.get("params") if _is_record(record.get("params")) else {}
    params_template = default_row.get("params") if _is_record(default_row.get("params")) else {}
    return {
        "id": str(record.get("id") or f"{family_id}_row_{index + 1}"),
        "enabled": _to_bool(record.get("enabled"), True),
        "score_key": score_key,
        "label": str(record.get("label") or default_row.get("label") or _family_score_label(family_id)).strip() or _family_score_label(family_id),
        "params": {
            param_name: _normalize_wfo_param(
                params_raw.get(param_name),
                default_value=(default_param.get("value") if _is_record(default_param) else 0.0),
                horizon=horizon,
            )
            for param_name, default_param in params_template.items()
        },
    }


def _normalize_family_config(raw: Any, *, family_id: str, horizon: str) -> dict[str, Any]:
    default_family = default_family_configs()[family_id]
    record = raw if _is_record(raw) else {}
    source_mode = str(record.get("source_mode") or "").strip().lower()
    if source_mode not in {"family_ensemble", "indicator_rows"}:
        source_mode = "indicator_rows"
    rows_raw = list(record.get("rows") or []) if isinstance(record.get("rows"), list) else []
    used_keys: set[str] = set()
    rows = [
        _normalize_indicator_row(item, family_id=family_id, index=index, horizon=horizon, used_keys=used_keys)
        for index, item in enumerate(rows_raw)
    ]

    if rows:
        return {
            "enabled": _to_bool(record.get("enabled"), default_family["enabled"]),
            "source_mode": source_mode,
            "rows": rows,
        }

    legacy_indicator_type = str(record.get("indicator_type") or "").strip().lower()
    legacy_params = record.get("params") if _is_record(record.get("params")) else {}
    if legacy_indicator_type or legacy_params:
        legacy_row = _normalize_indicator_row(
            {
                "id": f"{family_id}_row_1",
                "enabled": True,
                "score_key": _family_score_key(family_id),
                "label": _family_score_label(family_id),
                "params": legacy_params,
            },
            family_id=family_id,
            index=0,
            horizon=horizon,
            used_keys=used_keys,
        )
        return {
            "enabled": _to_bool(record.get("enabled"), default_family["enabled"]),
            "source_mode": "indicator_rows",
            "rows": [legacy_row],
        }

    return {
        "enabled": _to_bool(record.get("enabled"), default_family["enabled"]),
        "source_mode": source_mode,
        "rows": deepcopy(default_family["rows"]),
    }


def _normalize_rule_condition(raw: Any, *, index: int, horizon: str) -> dict[str, Any]:
    record = raw if _is_record(raw) else {}
    variable = str(record.get("variable") or "consensus_score").strip().lower()
    if not variable:
        variable = "consensus_score"
    operator = str(record.get("operator") or ">=").strip()
    if operator not in RULE_OPERATORS:
        operator = ">="
    return {
        "id": str(record.get("id") or f"condition_{index + 1}"),
        "variable": variable,
        "operator": operator,
        "threshold": _normalize_wfo_param(record.get("threshold"), default_value=0.0, horizon=horizon),
    }


def _normalize_entry_rule(raw: Any, *, index: int, horizon: str) -> dict[str, Any]:
    record = raw if _is_record(raw) else {}
    config_option = str(record.get("config_option") or "A").strip().upper()
    if config_option not in CONFIG_OPTIONS:
        config_option = "A"
    sizing = record.get("sizing") if _is_record(record.get("sizing")) else {}
    sizing_mode = _normalize_rule_sizing_mode(sizing.get("mode"), allow_kelly=True)
    manual_pct = _to_float(sizing.get("manual_pct"), _to_float(sizing.get("value"), 25.0))
    kelly_modifier = sizing.get("kelly_modifier")
    rule_expression = record.get("rule_expression") if _is_record(record.get("rule_expression")) else record.get("expression")
    out = {
        "id": str(record.get("id") or f"entry_{index + 1}"),
        "label": str(record.get("label") or f"Entree {index + 1}"),
        "config_option": config_option,
        "conditions": [
            _normalize_rule_condition(item, index=condition_index, horizon=horizon)
            for condition_index, item in enumerate(list(record.get("conditions") or []))
        ],
        "sizing": {
            "mode": sizing_mode,
            "manual_pct": manual_pct,
            "size_pct": _normalize_rule_direct_sizing_param(
                _legacy_direct_sizing_source(sizing, "size_pct") or {"mode": "wfo", "value": manual_pct},
                default_value=manual_pct,
                horizon=horizon,
            )
            if sizing_mode == "wfo"
            else None,
            "kelly_modifier": _normalize_wfo_param(kelly_modifier, default_value=0.5, horizon=horizon)
            if sizing_mode == "kelly_wfo"
            else None,
        },
    }
    if _is_record(rule_expression):
        out["rule_expression"] = deepcopy(rule_expression)
    return out


def _normalize_exit_rule(raw: Any, *, index: int, horizon: str) -> dict[str, Any]:
    record = raw if _is_record(raw) else {}
    config_option = str(record.get("config_option") or "A").strip().upper()
    if config_option not in CONFIG_OPTIONS:
        config_option = "A"
    sizing = record.get("sizing") if _is_record(record.get("sizing")) else {}
    sizing_mode = _normalize_rule_sizing_mode(sizing.get("mode"), allow_kelly=True)
    manual_pct = _to_float(sizing.get("manual_pct"), _to_float(sizing.get("value"), 100.0))
    rule_expression = record.get("rule_expression") if _is_record(record.get("rule_expression")) else record.get("expression")
    out = {
        "id": str(record.get("id") or f"exit_{index + 1}"),
        "label": str(record.get("label") or f"Sortie {index + 1}"),
        "config_option": config_option,
        "conditions": [
            _normalize_rule_condition(item, index=condition_index, horizon=horizon)
            for condition_index, item in enumerate(list(record.get("conditions") or []))
        ],
        "sizing": {
            "mode": sizing_mode,
            "manual_pct": manual_pct,
            "reduction_pct": _normalize_rule_direct_sizing_param(
                _legacy_direct_sizing_source(sizing, "reduction_pct") or {"mode": "wfo", "value": manual_pct},
                default_value=manual_pct,
                horizon=horizon,
            )
            if sizing_mode == "wfo"
            else None,
            "kelly_modifier": _normalize_wfo_param(sizing.get("kelly_modifier"), default_value=0.5, horizon=horizon)
            if sizing_mode == "kelly_wfo"
            else None,
        },
    }
    if _is_record(rule_expression):
        out["rule_expression"] = deepcopy(rule_expression)
    return out


def _normalize_stock_strategy_config(raw: Any, *, horizon: str) -> dict[str, Any]:
    base = default_stock_strategy_config(horizon=horizon)
    if not _is_record(raw):
        return base

    strategy_type = str(raw.get("strategy_type") or "trend_following").strip().lower()
    if strategy_type not in {"trend_following", "mean_reversion"}:
        strategy_type = "trend_following"
    base["strategy_type"] = strategy_type

    signal_construction_raw = raw.get("signal_construction") if _is_record(raw.get("signal_construction")) else {}
    signal_source_mode = str(signal_construction_raw.get("source_mode") or "manual").strip().lower()
    if signal_source_mode == "dashboard_edge_signal":
        base["signal_construction"]["source_mode"] = "dashboard_edge_signal"
        selected_signal = _normalize_signal_candidate_ref(signal_construction_raw.get("selected_signal_candidate"))
        if selected_signal is not None:
            base["signal_construction"]["selected_signal_candidate"] = selected_signal

    families_raw = (
        signal_construction_raw.get("families")
        if _is_record(signal_construction_raw.get("families"))
        else {}
    )
    for family_id in FAMILY_IDS:
        incoming = families_raw.get(family_id) if _is_record(families_raw) else None
        base["signal_construction"]["families"][family_id] = _normalize_family_config(
            incoming,
            family_id=family_id,
            horizon=horizon,
        )

    base["entry_rules"] = [
        _normalize_entry_rule(item, index=index, horizon=horizon)
        for index, item in enumerate(list(raw.get("entry_rules") or []))
    ]
    base["exit_rules"] = [
        _normalize_exit_rule(item, index=index, horizon=horizon)
        for index, item in enumerate(list(raw.get("exit_rules") or []))
    ]

    risk_raw = raw.get("risk") if _is_record(raw.get("risk")) else {}
    stop_loss_raw = risk_raw.get("stop_loss") if _is_record(risk_raw.get("stop_loss")) else {}
    take_profit_raw = risk_raw.get("take_profit") if _is_record(risk_raw.get("take_profit")) else {}
    time_stop_raw = risk_raw.get("time_stop") if _is_record(risk_raw.get("time_stop")) else {}

    stop_loss_mode = str(stop_loss_raw.get("mode") or "atr_based").strip().lower()
    if stop_loss_mode not in {"manual_pct", "atr_based", "wfo"}:
        stop_loss_mode = "atr_based"
    take_profit_mode = str(take_profit_raw.get("mode") or "rr_target").strip().lower()
    if take_profit_mode not in {"manual_pct", "rr_target", "wfo"}:
        take_profit_mode = "rr_target"

    base["risk"] = {
        "stop_loss": {
            "mode": stop_loss_mode,
            "manual_pct": _to_float(stop_loss_raw.get("manual_pct"), 0.02),
            "atr_multiplier": _normalize_wfo_param(stop_loss_raw.get("atr_multiplier"), default_value=1.5, horizon=horizon),
        },
        "take_profit": {
            "mode": take_profit_mode,
            "manual_pct": _to_float(take_profit_raw.get("manual_pct"), 0.03),
            "rr_ratio": _normalize_wfo_param(take_profit_raw.get("rr_ratio"), default_value=1.5, horizon=horizon),
        },
        "cooldown_bars": _normalize_wfo_param(risk_raw.get("cooldown_bars"), default_value=0, horizon=horizon),
        "time_stop": {
            "enabled": _to_bool(time_stop_raw.get("enabled"), True),
            "bars": _normalize_wfo_param(time_stop_raw.get("bars"), default_value=default_holding_bars(horizon), horizon=horizon),
        },
        "trailing_stop_enabled": _to_bool(risk_raw.get("trailing_stop_enabled"), False),
        "max_position_pct": _to_float(risk_raw.get("max_position_pct"), 20.0),
        "max_sector_pct": _to_float(risk_raw.get("max_sector_pct"), 40.0),
    }
    return base


def migrate_strategy_config_v2(raw: Any, *, horizon: str) -> dict[str, Any]:
    if _is_record(raw) and int(raw.get("schema_version") or 0) in {2, 3, 4} and str(raw.get("app_domain") or "").strip() == "four_pages":
        portfolio_raw = raw.get("portfolio") if _is_record(raw.get("portfolio")) else {}
        universe_raw = portfolio_raw.get("universe") if _is_record(portfolio_raw.get("universe")) else {}
        allocation_raw = portfolio_raw.get("allocation") if _is_record(portfolio_raw.get("allocation")) else {}
        basket = [symbol.upper() for symbol in _to_string_list(universe_raw.get("basket"))]
        selected_signal_candidates = _normalize_signal_candidate_refs(universe_raw.get("selected_signal_candidates"))
        selection_mode = str(universe_raw.get("selection_mode") or "").strip().lower()
        if selection_mode != "edge_candidates" and selected_signal_candidates:
            selection_mode = "edge_candidates"
        if selection_mode != "edge_candidates":
            selection_mode = "manual"
        stocks_raw = raw.get("stocks") if _is_record(raw.get("stocks")) else {}
        if not basket and stocks_raw:
            basket = [str(symbol).strip().upper() for symbol in stocks_raw.keys() if str(symbol).strip()]
        manual_raw = allocation_raw.get("manual_overrides_by_symbol") if _is_record(allocation_raw.get("manual_overrides_by_symbol")) else {}
        manual_overrides: dict[str, Any] = {}
        for symbol, value in manual_raw.items():
            if not _is_record(value):
                continue
            manual_overrides[str(symbol).upper()] = {
                "enabled": _to_bool(value.get("enabled"), False),
                "capital_mad": _to_float(value.get("capital_mad"), 0.0),
            }

        stocks: dict[str, Any] = {}
        for symbol in basket:
            stocks[symbol] = _normalize_stock_strategy_config(stocks_raw.get(symbol), horizon=horizon)

        return {
            "schema_version": 3,
            "app_domain": "four_pages",
            "legacy_snapshot": raw.get("legacy_snapshot") if raw.get("legacy_snapshot") is None or _is_record(raw.get("legacy_snapshot")) else None,
            "portfolio": {
                "total_capital_mad": _to_float(portfolio_raw.get("total_capital_mad"), 1_000_000.0),
                "universe": {
                    "basket": basket,
                    "sector_filter": _to_string_list(universe_raw.get("sector_filter")),
                    "min_abs_signal": _to_float(universe_raw.get("min_abs_signal"), 0.0),
                    "min_adv20": _to_float(universe_raw.get("min_adv20"), 0.0),
                    "sort_by": "signal_score" if str(universe_raw.get("sort_by") or "").strip() == "signal_score" else "adv20",
                    "sort_dir": "asc" if str(universe_raw.get("sort_dir") or "").strip() == "asc" else "desc",
                    "selection_mode": selection_mode,
                    "selected_signal_candidates": selected_signal_candidates,
                },
                "allocation": {
                    "method": "hrp",
                    "hrp_lookback_bars": max(_to_int(allocation_raw.get("hrp_lookback_bars"), 252), 20),
                    "manual_overrides_by_symbol": manual_overrides,
                },
            },
            "stocks": stocks,
            "snapshot": raw.get("snapshot") if raw.get("snapshot") is None or _is_record(raw.get("snapshot")) else None,
        }

    record = raw if _is_record(raw) else {}
    capital = record.get("capital") if _is_record(record.get("capital")) else {}
    universe = record.get("universe") if _is_record(record.get("universe")) else {}
    allocation = record.get("allocation") if _is_record(record.get("allocation")) else {}
    signal = record.get("signal") if _is_record(record.get("signal")) else {}
    logic = record.get("logic") if _is_record(record.get("logic")) else {}
    risk = record.get("risk") if _is_record(record.get("risk")) else {}
    basket = [symbol.upper() for symbol in _to_string_list(universe.get("basket"))]
    enabled_families = {
        item.lower()
        for item in _to_string_list(signal.get("enabled_families")) + _to_string_list(logic.get("enabled_families"))
        if item.lower() in FAMILY_IDS
    }
    if not enabled_families:
        enabled_families = {"sma"}

    manual_raw = allocation.get("manual_overrides_by_symbol") if _is_record(allocation.get("manual_overrides_by_symbol")) else {}
    manual_overrides: dict[str, Any] = {}
    for symbol, value in manual_raw.items():
        if _is_record(value):
            enabled = _to_bool(value.get("enabled"), False)
            capital_mad = _to_float(value.get("capital_mad"), 0.0)
        else:
            enabled = _to_float(value, 0.0) > 0
            capital_mad = _to_float(value, 0.0)
        manual_overrides[str(symbol).upper()] = {
            "enabled": enabled,
            "capital_mad": capital_mad,
        }

    stocks: dict[str, Any] = {}
    for symbol in basket:
        stock = default_stock_strategy_config(horizon=horizon)
        for family_id in FAMILY_IDS:
            stock["signal_construction"]["families"][family_id]["enabled"] = family_id in enabled_families
        stock["risk"] = {
            "stop_loss": {
                "mode": "atr_based",
                "manual_pct": 0.02,
                "atr_multiplier": _manual_param(_to_float(risk.get("stop_atr_multiplier"), 1.5)),
            },
            "take_profit": {
                "mode": "rr_target",
                "manual_pct": 0.03,
                "rr_ratio": _manual_param(_to_float(risk.get("take_profit_rr"), 1.5)),
            },
            "cooldown_bars": _manual_param(0),
            "time_stop": {
                "enabled": _to_bool(risk.get("time_stop_enabled"), True),
                "bars": _manual_param(_to_int(risk.get("max_holding_bars"), default_holding_bars(horizon))),
            },
            "trailing_stop_enabled": _to_bool(risk.get("trailing_stop_enabled"), False),
            "max_position_pct": 20.0,
            "max_sector_pct": 40.0,
        }
        stocks[symbol] = stock

    return {
        "schema_version": 3,
        "app_domain": "four_pages",
        "legacy_snapshot": deepcopy(record) if record else None,
        "portfolio": {
            "total_capital_mad": _to_float(capital.get("total_capital_mad"), 1_000_000.0),
            "universe": {
                "basket": basket,
                "sector_filter": _to_string_list(universe.get("sector_filter")),
                "min_abs_signal": _to_float(universe.get("min_abs_signal"), 0.0),
                "min_adv20": _to_float(universe.get("min_adv20"), 0.0),
                "sort_by": "signal_score" if str(universe.get("sort_by") or "").strip() == "signal_score" else "adv20",
                "sort_dir": "asc" if str(universe.get("sort_dir") or "").strip() == "asc" else "desc",
                "selection_mode": "manual",
                "selected_signal_candidates": [],
            },
            "allocation": {
                "method": "hrp",
                "hrp_lookback_bars": max(_to_int(allocation.get("hrp_lookback_bars"), 252), 20),
                "manual_overrides_by_symbol": manual_overrides,
            },
        },
        "stocks": stocks,
        "snapshot": None,
    }


def get_basket_from_strategy_config(raw: Any, *, horizon: str) -> list[str]:
    config = migrate_strategy_config_v2(raw, horizon=horizon)
    portfolio = config.get("portfolio") if _is_record(config.get("portfolio")) else {}
    universe = portfolio.get("universe") if _is_record(portfolio.get("universe")) else {}
    return [str(symbol).upper() for symbol in list(universe.get("basket") or []) if str(symbol).strip()]


def _collect_wfo_params(stock: str, section: str, value: Any, path: str, out: list[dict[str, Any]]) -> None:
    if _is_record(value):
        mode = str(value.get("mode") or "").strip().lower()
        if mode == "wfo" and value.get("value") is not None:
            out.append(
                {
                    "stock": stock,
                    "section": section,
                    "param_path": path,
                    "scan_min": _to_float(value.get("scan_min"), _to_float(value.get("value"), 0.0)),
                    "scan_max": _to_float(value.get("scan_max"), _to_float(value.get("value"), 0.0)),
                    "scan_step": _to_float(value.get("scan_step"), 0.0),
                }
            )
            return
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            _collect_wfo_params(stock, section, child, child_path, out)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            _collect_wfo_params(stock, section, child, child_path, out)


def _is_integer_wfo_path(path: str) -> bool:
    return any(str(path).endswith(suffix) for suffix in INTEGER_WFO_PARAM_SUFFIXES)


def _is_integral_number(value: float, *, tol: float = 1e-9) -> bool:
    return math.isfinite(value) and abs(value - round(value)) <= tol


def _validate_manifest_entry(entry: dict[str, Any]) -> tuple[list[str], list[str]]:
    path = str(entry.get("param_path") or "")
    scan_min = _to_float(entry.get("scan_min"), 0.0)
    scan_max = _to_float(entry.get("scan_max"), 0.0)
    scan_step = _to_float(entry.get("scan_step"), 0.0)
    blocking_issues: list[str] = []
    warnings: list[str] = []

    if scan_step <= 0:
        blocking_issues.append(f"{path}: scan_step must be positive.")
    if scan_max < scan_min:
        blocking_issues.append(f"{path}: scan_max must be >= scan_min.")
    value = _to_float(entry.get("value"), scan_min)
    if value < scan_min or value > scan_max:
        blocking_issues.append(f"{path}: value must stay inside [scan_min, scan_max].")
    if _is_integer_wfo_path(path):
        if not _is_integral_number(value):
            blocking_issues.append(f"{path}: value must be integer-compatible.")
        if not _is_integral_number(scan_min):
            blocking_issues.append(f"{path}: scan_min must be integer-compatible.")
        if not _is_integral_number(scan_max):
            blocking_issues.append(f"{path}: scan_max must be integer-compatible.")
        if not _is_integral_number(scan_step):
            blocking_issues.append(f"{path}: scan_step must be integer-compatible.")
    elif scan_min == scan_max:
        warnings.append(f"{path}: WFO range collapses to one value.")

    return blocking_issues, warnings


def _collect_wfo_entries_with_values(
    stock: str,
    section: str,
    value: Any,
    path: str,
    out: list[dict[str, Any]],
) -> None:
    if _is_record(value):
        mode = str(value.get("mode") or "").strip().lower()
        if mode == "wfo" and value.get("value") is not None:
            out.append(
                {
                    "stock": stock,
                    "section": section,
                    "param_path": path,
                    "value": _to_float(value.get("value"), 0.0),
                    "scan_min": _to_float(value.get("scan_min"), _to_float(value.get("value"), 0.0)),
                    "scan_max": _to_float(value.get("scan_max"), _to_float(value.get("value"), 0.0)),
                    "scan_step": _to_float(value.get("scan_step"), 0.0),
                }
            )
            return
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            _collect_wfo_entries_with_values(stock, section, child, child_path, out)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            _collect_wfo_entries_with_values(stock, section, child, child_path, out)


def _family_has_active_source(family: dict[str, Any]) -> bool:
    if not _is_record(family) or not bool(family.get("enabled")):
        return False
    source_mode = str(family.get("source_mode") or "indicator_rows").strip().lower()
    if source_mode == "family_ensemble":
        return True
    rows = [item for item in list(family.get("rows") or []) if _is_record(item) and bool(item.get("enabled", True))]
    return len(rows) > 0


def _stock_uses_dashboard_edge_signal(stock_config: dict[str, Any]) -> bool:
    signal_construction = stock_config.get("signal_construction") if _is_record(stock_config.get("signal_construction")) else {}
    if str(signal_construction.get("source_mode") or "").strip().lower() != "dashboard_edge_signal":
        return False
    return _is_record(signal_construction.get("selected_signal_candidate"))


def _rule_variable_blockers(stock: str, stock_config: dict[str, Any]) -> list[str]:
    available_variables = score_variable_keys(stock_config)
    out: list[str] = []
    for rule_group_name, rule_group in (
        ("entry", list(stock_config.get("entry_rules") or [])),
        ("exit", list(stock_config.get("exit_rules") or [])),
    ):
        for rule in rule_group:
            if not _is_record(rule):
                continue
            for condition in [item for item in list(rule.get("conditions") or []) if _is_record(item)]:
                variable = str(condition.get("variable") or "consensus_score").strip().lower()
                if variable not in available_variables:
                    out.append(
                        f"{stock}: {rule_group_name} rule '{rule.get('label') or rule.get('id') or 'rule'}' references missing score variable '{variable}'."
                    )
    return out


def _stock_execution_constraints(
    stock: str,
    stock_config: dict[str, Any],
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    blocking_issues: list[str] = []

    blocking_issues.extend(_rule_variable_blockers(stock, stock_config))

    entries: list[dict[str, Any]] = []
    for section in ("signal_construction", "entry_rules", "exit_rules", "risk"):
        if section in stock_config:
            _collect_wfo_entries_with_values(stock, section, stock_config.get(section), section, entries)
    for entry in entries:
        param_blockers, param_warnings = _validate_manifest_entry(entry)
        blocking_issues.extend(f"{stock}: {message}" for message in param_blockers)
        warnings.extend(f"{stock}: {message}" for message in param_warnings)

    return warnings, blocking_issues


def build_wfo_param_manifest(config: dict[str, Any]) -> list[dict[str, Any]]:
    stocks = config.get("stocks") if _is_record(config.get("stocks")) else {}
    out: list[dict[str, Any]] = []
    for stock, stock_config in stocks.items():
        if not _is_record(stock_config):
            continue
        for section in ("signal_construction", "entry_rules", "exit_rules", "risk"):
            if section in stock_config:
                _collect_wfo_params(str(stock), section, stock_config.get(section), section, out)
    return out


def _stock_readiness(stock: str, stock_config: dict[str, Any]) -> dict[str, Any]:
    families = (
        stock_config.get("signal_construction", {}).get("families")
        if _is_record(stock_config.get("signal_construction")) and _is_record(stock_config.get("signal_construction", {}).get("families"))
        else {}
    )
    has_signal = _stock_uses_dashboard_edge_signal(stock_config) or any(_family_has_active_source(value if _is_record(value) else {}) for value in families.values())
    entry_rules = list(stock_config.get("entry_rules") or [])
    exit_rules = list(stock_config.get("exit_rules") or [])
    has_risk = _is_record(stock_config.get("risk"))
    warnings: list[str] = []
    blocking_issues: list[str] = []

    if not has_signal:
        blocking_issues.append("Aucune famille de signal active.")
    if len(entry_rules) == 0:
        blocking_issues.append("Aucune regle d'entree.")
    if len(exit_rules) == 0:
        warnings.append("Aucune regle de sortie.")
    if not has_risk:
        blocking_issues.append("Configuration de risque manquante.")

    execution_warnings, execution_blockers = _stock_execution_constraints(stock, stock_config)
    warnings.extend(execution_warnings)
    blocking_issues.extend(execution_blockers)

    wfo_params = build_wfo_param_manifest({"stocks": {stock: stock_config}})
    return {
        "symbol": stock,
        "has_signal": has_signal,
        "has_entry_rules": len(entry_rules) > 0,
        "has_exit_rules": len(exit_rules) > 0,
        "has_risk": has_risk,
        "wfo_param_count": len(wfo_params),
        "ready": len(blocking_issues) == 0,
        "warnings": warnings,
        "blocking_issues": blocking_issues,
    }
def build_strategy_review(raw: Any, *, horizon: str, for_wfo: bool = False) -> dict[str, Any]:
    config = migrate_strategy_config_v2(raw, horizon=horizon)
    basket = get_basket_from_strategy_config(config, horizon=horizon)
    stocks = config.get("stocks") if _is_record(config.get("stocks")) else {}
    stock_summaries = []
    for symbol in basket:
        stock_config = stocks.get(symbol) if _is_record(stocks.get(symbol)) else {}
        summary = _stock_readiness(symbol, stock_config)
        stock_summaries.append(summary)
    manifest = build_wfo_param_manifest(config)
    total_wfo_param_count = len(manifest)
    global_warnings: list[str] = []
    blocking_issues: list[str] = []

    if not basket:
        blocking_issues.append("Aucun titre dans le panier.")
    if total_wfo_param_count > 15:
        global_warnings.append("Le nombre total de parametres WFO est eleve et augmente le risque d'overfitting.")
    elif total_wfo_param_count > 10:
        global_warnings.append("Le nombre de parametres WFO commence a devenir eleve.")

    for item in stock_summaries:
        if not item["ready"]:
            blocking_issues.append(f"{item['symbol']}: configuration incomplete.")

    if total_wfo_param_count <= 10:
        severity = "ok"
    elif total_wfo_param_count <= 15:
        severity = "warning"
    else:
        severity = "danger"

    pardo_df_ok = total_wfo_param_count <= 15
    pardo_df_message = (
        "Parametrage WFO dans une zone prudente."
        if pardo_df_ok
        else "Charge de degres de liberte elevee. Simplifiez le nombre de parametres WFO."
    )
    return {
        "total_wfo_param_count": total_wfo_param_count,
        "wfo_param_severity": severity,
        "pardo_df_ok": pardo_df_ok,
        "pardo_df_message": pardo_df_message,
        "stocks": stock_summaries,
        "global_warnings": global_warnings,
        "blocking_issues": blocking_issues,
        "ready": len(blocking_issues) == 0,
        "canonical_config": config,
    }


def build_strategy_handoff(*, strategy_id: str, strategy_name: str, raw: Any, horizon: str) -> dict[str, Any]:
    review = build_strategy_review(raw, horizon=horizon)
    config = review["canonical_config"]
    warnings = list(review["global_warnings"])
    for item in list(review["stocks"]):
        for warning in list(item.get("warnings") or []):
            warnings.append(f"{item['symbol']}: {warning}")
        for issue in list(item.get("blocking_issues") or []):
            warnings.append(f"{item['symbol']}: {issue}")
    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy_name,
        "portfolio": config["portfolio"],
        "stocks": config["stocks"],
        "selected_signal_candidates": list(config["portfolio"]["universe"].get("selected_signal_candidates") or []),
        "wfo_params": {"params": build_wfo_param_manifest(config)},
        "total_wfo_param_count": review["total_wfo_param_count"],
        "warnings": warnings,
        "ready": review["ready"],
        "blocking_issues": review["blocking_issues"],
        "schema_version": 3,
        "app_domain": "four_pages",
    }


def _canonical_signal_signature(stock_config: dict[str, Any]) -> tuple[tuple[str, bool], ...]:
    families = stock_config.get("signal_construction", {}).get("families")
    if not _is_record(families):
        return tuple()
    return tuple(
        (
            family_id,
            _family_has_active_source(families.get(family_id) if _is_record(families.get(family_id)) else {}),
        )
        for family_id in FAMILY_IDS
    )


def _canonical_risk_signature(stock_config: dict[str, Any]) -> tuple[Any, ...]:
    risk = stock_config.get("risk") if _is_record(stock_config.get("risk")) else {}
    stop_loss = risk.get("stop_loss") if _is_record(risk.get("stop_loss")) else {}
    take_profit = risk.get("take_profit") if _is_record(risk.get("take_profit")) else {}
    time_stop = risk.get("time_stop") if _is_record(risk.get("time_stop")) else {}
    return (
        str(stop_loss.get("mode") or "atr_based"),
        _to_float((stop_loss.get("atr_multiplier") or {}).get("value"), 1.5) if _is_record(stop_loss.get("atr_multiplier")) else 1.5,
        str(take_profit.get("mode") or "rr_target"),
        _to_float((take_profit.get("rr_ratio") or {}).get("value"), 1.5) if _is_record(take_profit.get("rr_ratio")) else 1.5,
        _to_bool(time_stop.get("enabled"), True),
        _to_int((time_stop.get("bars") or {}).get("value"), 30) if _is_record(time_stop.get("bars")) else 30,
        _to_bool(risk.get("trailing_stop_enabled"), False),
    )


def build_legacy_backtest_config_from_v2(raw: Any, *, horizon: str) -> dict[str, Any]:
    config = migrate_strategy_config_v2(raw, horizon=horizon)
    basket = get_basket_from_strategy_config(config, horizon=horizon)
    universe = config["portfolio"]["universe"]
    selected_signal_candidates = list(universe.get("selected_signal_candidates") or [])
    candidates_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for ref in selected_signal_candidates:
        if not _is_record(ref):
            continue
        symbol = str(ref.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        candidates_by_symbol.setdefault(symbol, []).append(deepcopy(ref))
    if not basket:
        return {
            "capital": {"total_capital_mad": config["portfolio"]["total_capital_mad"]},
            "universe": {
                "basket": [],
                "selection_mode": universe.get("selection_mode", "manual"),
                "selected_signal_candidates": selected_signal_candidates,
            },
            "allocation": config["portfolio"]["allocation"],
            "signal": {"enabled_families": list(FAMILY_IDS)},
            "bet_sizing": {
                "mode": "auto_calibrated",
                "calibration_lookback_bars": 756,
                "min_observations": 200,
                "min_bucket_observations": 25,
                "primary_metric": "avg_r_multiple",
                "bucket_count": 10,
                "exposure_levels": [0, 25, 50, 75, 100],
                "sample_method": "event_deduped",
                "last_calibration": None,
            },
            "risk": {
                "max_holding_bars": default_holding_bars(horizon),
                "stop_atr_multiplier": 1.5,

                "take_profit_rr": 1.5,
                "time_stop_enabled": True,
                "trailing_stop_enabled": False,
            },
        }

    stocks = config["stocks"]
    first = stocks[basket[0]]
    reference_signal_signature = _canonical_signal_signature(first)
    enabled_families = [family_id for family_id, enabled in reference_signal_signature if enabled]
    risk = first["risk"]
    stop_loss = risk["stop_loss"]
    take_profit = risk["take_profit"]
    time_stop = risk["time_stop"]
    per_stock: dict[str, Any] = {}
    for symbol in basket:
        candidate = stocks[symbol]
        candidate_risk = candidate["risk"]
        candidate_stop_loss = candidate_risk["stop_loss"]
        candidate_take_profit = candidate_risk["take_profit"]
        candidate_time_stop = candidate_risk["time_stop"]
        per_stock[symbol] = {
            "signal": {
                "enabled_families": [
                    family_id
                    for family_id, enabled in _canonical_signal_signature(candidate)
                    if enabled
                ],
                "selected_signal_candidates": candidates_by_symbol.get(symbol, []),
            },
            "signal_construction": deepcopy(candidate.get("signal_construction") or {}),
            "entry_rules": deepcopy(list(candidate.get("entry_rules") or [])),
            "exit_rules": deepcopy(list(candidate.get("exit_rules") or [])),
            "risk": {
                "max_holding_bars": _to_int((candidate_time_stop.get("bars") or {}).get("value"), default_holding_bars(horizon))
                if _is_record(candidate_time_stop.get("bars"))
                else default_holding_bars(horizon),
                "stop_atr_multiplier": _to_float((candidate_stop_loss.get("atr_multiplier") or {}).get("value"), 1.5)
                if _is_record(candidate_stop_loss.get("atr_multiplier"))
                else 1.5,

                "take_profit_rr": _to_float((candidate_take_profit.get("rr_ratio") or {}).get("value"), 1.5)
                if _is_record(candidate_take_profit.get("rr_ratio"))
                else 1.5,
                "time_stop_enabled": _to_bool(candidate_time_stop.get("enabled"), True),
                "trailing_stop_enabled": _to_bool(candidate_risk.get("trailing_stop_enabled"), False),
            },
        }
    return {
        "capital": {"total_capital_mad": config["portfolio"]["total_capital_mad"]},
        "universe": {
            "basket": basket,
            "selection_mode": universe.get("selection_mode", "manual"),
            "selected_signal_candidates": selected_signal_candidates,
        },
        "allocation": config["portfolio"]["allocation"],
        "signal": {"enabled_families": enabled_families},
        "bet_sizing": {
            "mode": "auto_calibrated",
            "calibration_lookback_bars": 756,
            "min_observations": 200,
            "min_bucket_observations": 25,
            "primary_metric": "avg_r_multiple",
            "bucket_count": 10,
            "exposure_levels": [0, 25, 50, 75, 100],
            "sample_method": "event_deduped",
            "last_calibration": None,
        },
        "risk": {
            "max_holding_bars": _to_int((time_stop.get("bars") or {}).get("value"), default_holding_bars(horizon))
            if _is_record(time_stop.get("bars"))
            else default_holding_bars(horizon),
            "stop_atr_multiplier": _to_float((stop_loss.get("atr_multiplier") or {}).get("value"), 1.5)
            if _is_record(stop_loss.get("atr_multiplier"))
            else 1.5,
            "take_profit_rr": _to_float((take_profit.get("rr_ratio") or {}).get("value"), 1.5)
            if _is_record(take_profit.get("rr_ratio"))
            else 1.5,
            "time_stop_enabled": _to_bool(time_stop.get("enabled"), True),
            "trailing_stop_enabled": _to_bool(risk.get("trailing_stop_enabled"), False),
        },
        "per_stock": per_stock,
    }
