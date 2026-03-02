from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd


CHECK_PASS = "pass"
CHECK_WARN = "warn"
CHECK_FAIL = "fail"


def _to_ts(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return pd.Timestamp(ts)
    except Exception:
        return None


def _collect_decision_symbol_payloads(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    decision_support = out.get("decision_support")
    if not isinstance(decision_support, dict):
        return payloads

    inputs_by_kind = decision_support.get("inputs_by_kind")
    if not isinstance(inputs_by_kind, dict):
        return payloads

    for kind_payload_any in inputs_by_kind.values():
        kind_payload = kind_payload_any if isinstance(kind_payload_any, dict) else {}
        decision_inputs = kind_payload.get("decision_inputs")
        if not isinstance(decision_inputs, dict):
            continue
        symbols_payload = decision_inputs.get("symbols")
        if not isinstance(symbols_payload, dict):
            continue
        for symbol_raw, symbol_payload_any in symbols_payload.items():
            symbol = str(symbol_raw or "").strip().upper()
            if not symbol:
                continue
            symbol_payload = symbol_payload_any if isinstance(symbol_payload_any, dict) else {}
            if symbol not in payloads:
                payloads[symbol] = symbol_payload
    return payloads


def _frame_from_records(records: Any) -> pd.DataFrame:
    rows = [row for row in list(records or []) if isinstance(row, dict)]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
    return df


def _check_lookahead_and_timing(
    fills: list[dict[str, Any]],
    symbol_payloads: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any], int]:
    signal_ts_by_symbol: dict[str, set[pd.Timestamp]] = {}

    for symbol, payload in symbol_payloads.items():
        sig_df = _frame_from_records(payload.get("signals"))
        if sig_df.empty or "signal" not in sig_df.columns:
            continue
        signal_vals = pd.to_numeric(sig_df["signal"], errors="coerce").fillna(0.0)
        signal_ts_by_symbol[symbol] = set(sig_df.index[signal_vals != 0.0].tolist())

    same_bar_count = 0
    fill_count = 0
    missing_signal_count = 0

    for row in fills:
        ts = _to_ts(row.get("timestamp"))
        if ts is None:
            continue
        symbol = str(row.get("symbol") or "").strip().upper() or "__ALL__"
        fill_count += 1
        signal_ts = signal_ts_by_symbol.get(symbol)
        if not signal_ts:
            missing_signal_count += 1
            continue
        if ts in signal_ts:
            same_bar_count += 1

    if same_bar_count > 0:
        status = CHECK_FAIL
    elif fill_count == 0:
        status = CHECK_WARN
    elif missing_signal_count > 0:
        status = CHECK_WARN
    else:
        status = CHECK_PASS

    details = {
        "fill_count": int(fill_count),
        "same_bar_execution_count": int(same_bar_count),
        "fills_without_signal_snapshot": int(missing_signal_count),
    }
    return status, details, same_bar_count


def _check_dataset_flags(dataset_meta: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not dataset_meta:
        return CHECK_WARN, {"reason": "dataset metadata unavailable"}

    split_adj = dataset_meta.get("adjusted_for_splits")
    div_adj = dataset_meta.get("adjusted_for_dividends")
    corp_adj = dataset_meta.get("corporate_actions_adjusted")
    survivorship_free = dataset_meta.get("survivorship_bias_free")

    known = [v for v in [split_adj, div_adj, corp_adj, survivorship_free] if isinstance(v, bool)]
    if not known:
        return CHECK_WARN, {"reason": "adjustment/survivorship flags unknown", "meta": dataset_meta}

    warnings: list[str] = []
    if split_adj is False:
        warnings.append("not split-adjusted")
    if div_adj is False:
        warnings.append("not dividend-adjusted")
    if corp_adj is False:
        warnings.append("corporate actions adjustment disabled")
    if survivorship_free is False:
        warnings.append("survivorship-bias-free flag is false")

    if warnings:
        return CHECK_WARN, {"warnings": warnings, "meta": dataset_meta}

    return CHECK_PASS, {"meta": dataset_meta}


def _check_price_validity(symbol_payloads: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    totals = {
        "symbols": 0,
        "rows": 0,
        "invalid_price_rows": 0,
        "invalid_volume_rows": 0,
        "missing_ohlc_rows": 0,
        "outlier_return_rows": 0,
        "large_gap_count": 0,
    }

    for payload in symbol_payloads.values():
        bars = _frame_from_records(payload.get("bars"))
        if bars.empty:
            continue

        totals["symbols"] += 1
        totals["rows"] += int(len(bars))

        for col in ["Open", "High", "Low", "Close"]:
            if col not in bars.columns:
                continue
            col_values = pd.to_numeric(bars[col], errors="coerce")
            totals["invalid_price_rows"] += int((col_values <= 0).sum())
            totals["missing_ohlc_rows"] += int(col_values.isna().sum())

        if "Volume" in bars.columns:
            vol = pd.to_numeric(bars["Volume"], errors="coerce")
            totals["invalid_volume_rows"] += int((vol <= 0).sum())
            totals["invalid_volume_rows"] += int(vol.isna().sum())

        if "Close" in bars.columns and len(bars) > 5:
            close = pd.to_numeric(bars["Close"], errors="coerce")
            rets = close.pct_change()
            med = float(np.nanmedian(rets))
            mad = float(np.nanmedian(np.abs(rets - med)))
            scale = max(mad * 1.4826, 1e-8)
            z = np.abs((rets - med) / scale)
            totals["outlier_return_rows"] += int((z > 8.0).sum())

        idx = pd.DatetimeIndex(bars.index)
        if len(idx) > 1:
            gap_days = np.diff(idx.values).astype("timedelta64[D]").astype(int)
            totals["large_gap_count"] += int((gap_days > 5).sum())

    has_issue = any(
        totals[key] > 0
        for key in (
            "invalid_price_rows",
            "invalid_volume_rows",
            "missing_ohlc_rows",
            "outlier_return_rows",
            "large_gap_count",
        )
    )
    if totals["symbols"] == 0:
        return CHECK_WARN, {"reason": "no bar snapshots available"}
    return (CHECK_WARN if has_issue else CHECK_PASS), totals


def _check_feature_leakage(symbol_payloads: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    suspicious_tokens = (
        "future",
        "lead",
        "t+1",
        "next_return",
        "forward_return",
        "shift_-",
        "ret_fwd",
    )

    suspicious: set[str] = set()
    feature_count = 0
    for payload in symbol_payloads.values():
        features = _frame_from_records(payload.get("features"))
        if features.empty:
            continue
        feature_count += len(features.columns)
        for col in features.columns:
            low = str(col).strip().lower()
            if any(tok in low for tok in suspicious_tokens):
                suspicious.add(str(col))

    if suspicious:
        return CHECK_FAIL, {
            "suspicious_features": sorted(suspicious),
            "feature_count": int(feature_count),
        }
    if feature_count == 0:
        return CHECK_WARN, {"reason": "no feature snapshots available"}
    return CHECK_PASS, {"feature_count": int(feature_count)}


def build_integrity_report(
    *,
    spec_json: dict[str, Any],
    pipeline_output: dict[str, Any],
    dataset_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    symbol_payloads = _collect_decision_symbol_payloads(pipeline_output)
    fills = [row for row in list(pipeline_output.get("fills") or []) if isinstance(row, dict)]

    checks: list[dict[str, Any]] = []

    look_status, look_details, same_bar_count = _check_lookahead_and_timing(fills, symbol_payloads)
    checks.append(
        {
            "check_name": "lookahead_bias_detection",
            "status": look_status,
            "details": look_details,
        }
    )

    dataset_status, dataset_details = _check_dataset_flags(dict(dataset_meta or {}))
    checks.append(
        {
            "check_name": "survivorship_corporate_actions",
            "status": dataset_status,
            "details": dataset_details,
        }
    )

    price_status, price_details = _check_price_validity(symbol_payloads)
    checks.append(
        {
            "check_name": "price_validity",
            "status": price_status,
            "details": price_details,
        }
    )

    portfolio_cfg = dict(spec_json.get("portfolio") or {})
    policy = {
        "signal_time": "close_t",
        "fill_time": "open_t1",
        "fill_price_model": str(portfolio_cfg.get("fill_price_model", "next_open")),
        "mtm_model": str(portfolio_cfg.get("mtm_model", "close_t1")),
    }
    timing_status = CHECK_PASS
    timing_notes: list[str] = []
    if policy["fill_price_model"] != "next_open":
        timing_status = CHECK_FAIL
        timing_notes.append("fill_price_model must be next_open")
    if policy["mtm_model"] != "close_t1":
        timing_status = CHECK_FAIL
        timing_notes.append("mtm_model must be close_t1")
    if same_bar_count > 0:
        timing_status = CHECK_FAIL
        timing_notes.append("same-bar fills detected")

    checks.append(
        {
            "check_name": "execution_timing_contract",
            "status": timing_status,
            "details": {"policy": policy, "notes": timing_notes},
        }
    )

    leakage_status, leakage_details = _check_feature_leakage(symbol_payloads)
    checks.append(
        {
            "check_name": "feature_data_leakage",
            "status": leakage_status,
            "details": leakage_details,
        }
    )

    statuses = [str(item["status"]) for item in checks]
    if CHECK_FAIL in statuses:
        overall = CHECK_FAIL
    elif CHECK_WARN in statuses:
        overall = CHECK_WARN
    else:
        overall = CHECK_PASS

    return {
        "status": overall,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "checks": checks,
    }
