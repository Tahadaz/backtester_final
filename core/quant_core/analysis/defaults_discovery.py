from __future__ import annotations

from dataclasses import dataclass
from statistics import multimode
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from ..research.horizon import get_horizon_config

TRADING_HORIZON_VALUES: tuple[str, ...] = ("short", "medium", "long")


DEFAULT_SMA_BUCKETS: list[dict[str, int | str]] = [
    {"bucket_id": "B1", "low": 3, "high": 7},
    {"bucket_id": "B2", "low": 8, "high": 12},
    {"bucket_id": "B3", "low": 13, "high": 20},
    {"bucket_id": "B4", "low": 21, "high": 30},
    {"bucket_id": "B5", "low": 31, "high": 45},
    {"bucket_id": "B6", "low": 46, "high": 70},
    {"bucket_id": "B7", "low": 71, "high": 110},
    {"bucket_id": "B8", "low": 111, "high": 170},
    {"bucket_id": "B9", "low": 171, "high": 250},
]

DEFAULT_SMA_NICE_NUMBERS: list[int] = [
    3, 5, 7, 10, 12, 14, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 75, 80, 90, 100, 110, 125, 150, 170, 200, 225, 250
]


@dataclass(frozen=True)
class BucketRange:
    bucket_id: str
    low: int
    high: int

    @property
    def label(self) -> str:
        return f"{self.low}-{self.high}"

    def clamp(self, max_n: int) -> "BucketRange":
        hi = min(self.high, int(max_n))
        lo = min(self.low, hi)
        return BucketRange(bucket_id=self.bucket_id, low=lo, high=hi)


def _as_int(value: Any, *, field_name: str) -> int:
    try:
        out = int(value)
    except Exception as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc
    return out


def validate_buckets(
    raw_buckets: Sequence[Mapping[str, Any]],
    *,
    expected_count: int | None = None,
) -> list[BucketRange]:
    buckets: list[BucketRange] = []
    for i, raw in enumerate(list(raw_buckets or [])):
        bucket_id = str(raw.get("bucket_id") or f"B{i + 1}").strip().upper() or f"B{i + 1}"
        low = _as_int(raw.get("low"), field_name=f"{bucket_id}.low")
        high = _as_int(raw.get("high"), field_name=f"{bucket_id}.high")
        if low <= 0 or high <= 0:
            raise ValueError(f"{bucket_id} bounds must be positive.")
        if low > high:
            raise ValueError(f"{bucket_id} requires low <= high.")
        buckets.append(BucketRange(bucket_id=bucket_id, low=low, high=high))

    if expected_count is not None and len(buckets) != int(expected_count):
        raise ValueError(f"Expected {expected_count} buckets, got {len(buckets)}.")
    if not buckets:
        raise ValueError("At least one bucket is required.")

    prev_high = 0
    seen: set[str] = set()
    for b in buckets:
        if b.bucket_id in seen:
            raise ValueError(f"Duplicate bucket_id: {b.bucket_id}.")
        seen.add(b.bucket_id)
        if b.low <= prev_high:
            raise ValueError("Buckets must be strictly increasing and non-overlapping.")
        prev_high = b.high
    return buckets


def _walk_forward_windows(
    length: int,
    *,
    train_window: int,
    step_size: int,
    use_test_window: bool,
    test_window: int,
) -> list[dict[str, int]]:
    train_len = int(train_window)
    step = int(step_size)
    test_len = int(test_window)
    if train_len <= 1:
        raise ValueError("train_window must be > 1.")
    if step <= 0:
        raise ValueError("step_size must be > 0.")
    if use_test_window and test_len <= 0:
        raise ValueError("test_window must be > 0 when use_test_window is enabled.")

    windows: list[dict[str, int]] = []
    start = 0
    while True:
        train_start = int(start)
        train_end = train_start + train_len
        if train_end > length:
            break

        if use_test_window:
            test_start = train_end
            if test_start >= length:
                break
            test_end = min(test_start + test_len, length)
            if test_end <= test_start:
                break
            windows.append(
                {
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                }
            )
        else:
            windows.append(
                {
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": -1,
                    "test_end": -1,
                }
            )
        start += step

    if not windows:
        raise ValueError("Walk-forward generated zero windows. Adjust train/test/step settings.")
    return windows


def _cost_rate(cost_model: Mapping[str, Any] | None) -> float:
    cfg = dict(cost_model or {})
    brokerage = float(cfg.get("brokerage_bps", 0.0) or 0.0)
    comm = float(cfg.get("comm_bourse_bps", 0.0) or 0.0)
    reg = float(cfg.get("reg_liv_bps", 0.0) or 0.0)
    slip = float(cfg.get("slippage_bps", 0.0) or 0.0)
    tva = float(cfg.get("tva_rate", 0.0) or 0.0)
    commissions = ((brokerage + comm + reg) / 10000.0) * (1.0 + tva)
    slippage = slip / 10000.0
    return max(float(commissions + slippage), 0.0)


def _sharpe(returns: pd.Series, periods_per_year: int = 252) -> float:
    r = pd.to_numeric(returns, errors="coerce").dropna().astype(float)
    if len(r) < 2:
        return 0.0
    std = float(r.std(ddof=1))
    if std <= 1e-12:
        return 0.0
    return float((r.mean() / std) * np.sqrt(float(periods_per_year)))


def _max_drawdown_abs(returns: pd.Series) -> float:
    r = pd.to_numeric(returns, errors="coerce").fillna(0.0).astype(float)
    if r.empty:
        return 0.0
    equity = (1.0 + r).cumprod()
    dd = equity / equity.cummax() - 1.0
    min_dd = float(dd.min()) if not dd.empty else 0.0
    return abs(min_dd)


def _positions_from_signal(
    close: pd.Series,
    *,
    n: int,
    allow_short: bool,
    signal_mode: str,
    buy_threshold_perc: float = 0.0,
    sell_threshold_perc: float = 0.0,
    cooldown_days: int = 0,
    volume: pd.Series | None = None,
    min_volume: float = 0.0,
) -> pd.Series:
    price = pd.to_numeric(close, errors="coerce").astype(float)
    sma = price.rolling(int(n), min_periods=int(n)).mean()

    mode = str(signal_mode or "level").strip().lower()
    if mode == "cross":
        prev_price = price.shift(1)
        prev_sma = sma.shift(1)
        cross_up = (price > sma) & (prev_price <= prev_sma)
        cross_down = (price < sma) & (prev_price >= prev_sma)
        event = pd.Series(0.0, index=price.index, dtype="float64")
        event.loc[cross_up] = 1.0
        if allow_short:
            event.loc[cross_down] = -1.0
        else:
            event.loc[cross_down] = -0.5

        pos = pd.Series(0.0, index=price.index, dtype="float64")
        current = 0.0
        for i, value in enumerate(event.to_numpy(dtype="float64", copy=False)):
            if value > 0:
                current = 1.0
            elif value < 0:
                current = -1.0 if allow_short else 0.0
            pos.iat[i] = current
        return pos.where(price.notna() & sma.notna(), 0.0)

    has_thresholds = float(buy_threshold_perc) != 0.0 or float(sell_threshold_perc) != 0.0
    has_cooldown = int(cooldown_days) > 0
    has_volume_filter = volume is not None and float(min_volume) > 0.0

    if not has_thresholds and not has_cooldown and not has_volume_filter:
        # Fast vectorized path — identical to original behaviour
        pos = pd.Series(0.0, index=price.index, dtype="float64")
        pos.loc[price > sma] = 1.0
        if allow_short:
            pos.loc[price < sma] = -1.0
        return pos.where(price.notna() & sma.notna(), 0.0)

    # Stateful path: supports thresholds, cooldown, and volume filter
    prices_arr = price.to_numpy(dtype="float64", copy=False)
    sma_arr = sma.to_numpy(dtype="float64", copy=False)
    vol_arr: np.ndarray | None = None
    if volume is not None:
        vol_arr = pd.to_numeric(volume, errors="coerce").astype(float).to_numpy(dtype="float64", copy=False)

    n_bars = len(prices_arr)
    pos_arr = np.zeros(n_bars, dtype="float64")
    current = 0.0
    last_trade_bar = -(10 ** 9)

    for i in range(n_bars):
        p = prices_arr[i]
        s = sma_arr[i]
        if not (np.isfinite(p) and np.isfinite(s)):
            pos_arr[i] = 0.0
            continue

        # Volume gate: hold current position if volume is too low to trade
        if has_volume_filter and vol_arr is not None:
            v = vol_arr[i]
            if np.isfinite(v) and v < float(min_volume):
                pos_arr[i] = current
                continue

        in_cooldown = (i - last_trade_bar) < int(cooldown_days)
        buy_level = s * (1.0 + float(buy_threshold_perc) / 100.0)
        sell_level = s * (1.0 - float(sell_threshold_perc) / 100.0)

        if not in_cooldown:
            if p > buy_level and current != 1.0:
                last_trade_bar = i
                current = 1.0
            elif p < sell_level and current != (-1.0 if allow_short else 0.0):
                last_trade_bar = i
                current = -1.0 if allow_short else 0.0
        pos_arr[i] = current

    return pd.Series(pos_arr, index=price.index, dtype="float64")


def _evaluate_sma_window(
    bars: pd.DataFrame,
    *,
    n: int,
    allow_short: bool,
    signal_mode: str,
    score_drawdown_weight: float,
    score_turnover_weight: float,
    use_net_after_costs: bool,
    cost_rate: float,
    buy_threshold_perc: float = 0.0,
    sell_threshold_perc: float = 0.0,
    cooldown_days: int = 0,
    min_volume: float = 0.0,
) -> dict[str, float]:
    close = pd.to_numeric(bars.get("Close"), errors="coerce")
    if close is None or close.dropna().empty:
        return {
            "score": float("-inf"),
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "turnover": 0.0,
            "net_sharpe": 0.0,
            "total_return": 0.0,
            "net_total_return": 0.0,
            "sample_count": 0.0,
        }

    volume_series: pd.Series | None = None
    if "Volume" in bars.columns:
        volume_series = pd.to_numeric(bars["Volume"], errors="coerce")

    pos = _positions_from_signal(
        close,
        n=int(n),
        allow_short=bool(allow_short),
        signal_mode=signal_mode,
        buy_threshold_perc=float(buy_threshold_perc),
        sell_threshold_perc=float(sell_threshold_perc),
        cooldown_days=int(cooldown_days),
        volume=volume_series,
        min_volume=float(min_volume),
    )
    px_ret = close.pct_change().fillna(0.0)
    pos_lag = pos.shift(1).fillna(0.0)
    gross_ret = pos_lag * px_ret

    pos_change = pos.diff().abs().fillna(pos.abs())
    turnover = float(pos_change.mean()) if len(pos_change) else 0.0
    cost = pos_change * float(cost_rate)
    net_ret = gross_ret - cost

    active_ret = net_ret if use_net_after_costs else gross_ret
    sharpe_gross = _sharpe(gross_ret)
    sharpe_net = _sharpe(net_ret)
    sharpe = sharpe_net if use_net_after_costs else sharpe_gross
    max_dd = _max_drawdown_abs(active_ret)
    score = float(sharpe - (float(score_drawdown_weight) * max_dd) - (float(score_turnover_weight) * turnover))

    total_return = float((1.0 + gross_ret.fillna(0.0)).prod() - 1.0)
    net_total_return = float((1.0 + net_ret.fillna(0.0)).prod() - 1.0)

    return {
        "score": score,
        "sharpe": float(sharpe),
        "max_drawdown": float(max_dd),
        "turnover": float(turnover),
        "net_sharpe": float(sharpe_net),
        "total_return": float(total_return),
        "net_total_return": float(net_total_return),
        "sample_count": float(len(close)),
    }


def _dominant_mode(values: Sequence[int]) -> tuple[int | None, float]:
    data = [int(v) for v in values]
    if not data:
        return None, 0.0
    modes = multimode(data)
    if not modes:
        return None, 0.0
    chosen = int(sorted(modes)[0])
    freq = float(data.count(chosen) / len(data))
    return chosen, freq


def _snap_to_nice(value: int, *, low: int, high: int, nice_numbers: Sequence[int]) -> int:
    candidates = [int(x) for x in nice_numbers if int(low) <= int(x) <= int(high)]
    if not candidates:
        return int(min(max(value, low), high))
    return int(min(candidates, key=lambda x: (abs(x - int(value)), x)))


def aggregate_bucket_defaults(
    best_n_values: Sequence[int],
    *,
    bucket_low: int,
    bucket_high: int,
    mode_threshold: float = 0.20,
    snap_to_nice: bool = True,
    nice_numbers: Sequence[int] | None = None,
) -> tuple[int, dict[str, float]]:
    values = [int(v) for v in best_n_values]
    if not values:
        chosen = int(bucket_low)
        return chosen, {"mode_frequency": 0.0, "used_mode": 0.0, "median": float(chosen)}

    mode_value, mode_freq = _dominant_mode(values)
    median_value = int(round(float(np.median(np.array(values, dtype="float64")))))
    if mode_value is not None and mode_freq >= float(mode_threshold):
        chosen = int(mode_value)
        used_mode = 1.0
    else:
        chosen = int(median_value)
        used_mode = 0.0

    chosen = int(min(max(chosen, int(bucket_low)), int(bucket_high)))
    if snap_to_nice:
        chosen = _snap_to_nice(
            chosen,
            low=int(bucket_low),
            high=int(bucket_high),
            nice_numbers=nice_numbers or DEFAULT_SMA_NICE_NUMBERS,
        )

    return chosen, {
        "mode_frequency": float(mode_freq),
        "used_mode": float(used_mode),
        "median": float(median_value),
    }


def _enforce_strict_increasing(defaults: list[int], buckets: list[BucketRange]) -> list[int]:
    out: list[int] = []
    prev = -10**9
    for i, current in enumerate(defaults):
        b = buckets[i]
        value = int(current)
        min_allowed = max(int(b.low), int(prev + 1))
        max_allowed = int(b.high)
        if min_allowed > max_allowed:
            raise ValueError("Cannot enforce strictly increasing defaults with current bucket bounds.")
        value = min(max(value, min_allowed), max_allowed)
        out.append(int(value))
        prev = int(value)
    return out


def _safe_mean(values: Sequence[float]) -> float | None:
    data = [float(v) for v in values]
    if not data:
        return None
    return float(np.mean(np.array(data, dtype="float64")))


def _safe_std(values: Sequence[float]) -> float | None:
    data = [float(v) for v in values]
    if not data:
        return None
    return float(np.std(np.array(data, dtype="float64")))


def _pick_top_row(
    rows: Sequence[dict[str, Any]],
    *,
    score_key: str,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("rows must not be empty when picking top row.")
    return sorted(
        list(rows),
        key=lambda row: (-float(row.get(score_key, float("-inf"))), int(row.get("n", 10**9))),
    )[0]


def _apply_report_metrics(report: dict[str, Any], rank_row: dict[str, Any], *, use_test_window: bool) -> None:
    selection_avg_score = rank_row.get("mean_selection_score")
    report["avg_score"] = float(selection_avg_score) if selection_avg_score is not None else 0.0
    report["avg_train_score"] = rank_row.get("mean_train_score")
    report["avg_test_score"] = rank_row.get("mean_test_score")
    report["avg_test_sharpe"] = rank_row.get("mean_test_sharpe")
    report["avg_test_dd"] = rank_row.get("mean_test_max_drawdown")
    report["avg_test_turnover"] = rank_row.get("mean_test_turnover")
    report["win_rate_global"] = float(rank_row.get("win_rate_global", 0.0) or 0.0)
    report["stability_std_test_score"] = rank_row.get("stability_std_test_score")
    report["sample_count_windows"] = int(rank_row.get("sample_count_windows", 0) or 0)

    if use_test_window:
        report["avg_sharpe"] = report["avg_test_sharpe"] if report["avg_test_sharpe"] is not None else 0.0
        report["avg_turnover"] = report["avg_test_turnover"] if report["avg_test_turnover"] is not None else 0.0
        report["avg_drawdown"] = report["avg_test_dd"] if report["avg_test_dd"] is not None else 0.0
        report["stability_std"] = (
            float(report["stability_std_test_score"]) if report["stability_std_test_score"] is not None else 0.0
        )
    else:
        report["avg_sharpe"] = float(rank_row.get("mean_train_sharpe") or 0.0)
        report["avg_turnover"] = float(rank_row.get("mean_train_turnover") or 0.0)
        report["avg_drawdown"] = float(rank_row.get("mean_train_max_drawdown") or 0.0)
        report["stability_std"] = float(rank_row.get("stability_std_selection_score") or 0.0)


def _normalize_trading_horizon(raw: Any, *, default: str = "medium") -> str:
    token = str(raw or "").strip().lower()
    if token in TRADING_HORIZON_VALUES:
        return token
    return str(default)


def discover_sma_defaults(
    bars: pd.DataFrame,
    *,
    buckets: Sequence[Mapping[str, Any]] | None = None,
    train_window: int | None = None,
    step_size: int | None = None,
    use_test_window: bool | None = None,
    test_window: int | None = None,
    enforce_feasible_train_half: bool = True,
    override_feasible_max_n: int | None = None,
    allow_short: bool = False,
    signal_mode: str = "level",
    buy_threshold_perc: float = 0.0,
    sell_threshold_perc: float = 0.0,
    cooldown_days: int = 0,
    min_volume: float = 0.0,
    score_drawdown_weight: float = 0.5,
    score_turnover_weight: float = 0.1,
    use_net_after_costs: bool = False,
    cost_model: Mapping[str, Any] | None = None,
    mode_threshold: float = 0.20,
    snap_to_nice: bool = True,
    nice_numbers: Sequence[int] | None = None,
    horizon: str | None = None,
    horizon_overrides: Mapping[str, Any] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Discover bucket defaults for SMA price strategy.

    Selection basis:
    - Ranking/selection is always based on in-sample train score.
    - When `use_test_window=True`, out-of-sample test metrics are computed for diagnostics only.

    Example:
    ```python
    res = discover_sma_defaults(bars, horizon="medium")
    print(res["meta"]["horizon"], res["meta"]["train_window"], res["defaults"])
    ```
    """
    frame = bars.copy()
    if frame.empty:
        raise ValueError("bars is empty.")
    if "Close" not in frame.columns:
        raise ValueError("bars must include Close column.")
    mode = str(signal_mode or "").strip().lower()
    if mode != "level":
        raise ValueError("Only SMA-price level mode allowed for horizon calibration.")
    signal_mode = "level"

    horizon_cfg = get_horizon_config(horizon, overrides=horizon_overrides)
    train_window = int(train_window) if train_window is not None else int(horizon_cfg.train_window)
    test_window = int(test_window) if test_window is not None else int(horizon_cfg.test_window)
    step_size = int(step_size) if step_size is not None else int(horizon_cfg.step_size)
    use_test_window = bool(use_test_window) if use_test_window is not None else bool(horizon_cfg.use_test_window)

    frame = frame.sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame[~frame.index.isna()]
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.sort_index()

    valid_buckets = validate_buckets(
        list(buckets or DEFAULT_SMA_BUCKETS),
        expected_count=9,
    )

    warnings: list[str] = []
    max_feasible_n = int(override_feasible_max_n) if override_feasible_max_n is not None else int(train_window // 2)
    max_bucket_high = max(b.high for b in valid_buckets)
    if not enforce_feasible_train_half:
        max_feasible_n = max(max_feasible_n, max_bucket_high)

    bucket_set = list(valid_buckets)
    if enforce_feasible_train_half:
        truncated: list[BucketRange] = []
        for b in bucket_set:
            tb = b.clamp(max_feasible_n)
            if tb.high != b.high or tb.low != b.low:
                warnings.append(
                    f"{b.bucket_id} truncated from {b.low}-{b.high} to {tb.low}-{tb.high} (max feasible n={max_feasible_n})."
                )
            truncated.append(tb)
        bucket_set = truncated

    windows = _walk_forward_windows(
        len(frame),
        train_window=int(train_window),
        step_size=int(step_size),
        use_test_window=bool(use_test_window),
        test_window=int(test_window),
    )

    cost = _cost_rate(cost_model)
    # Keep OOS as pure diagnostics: parameter selection must be train-only.
    selection_basis = "train"
    winners: list[dict[str, Any]] = []
    matrix: list[dict[str, Any]] = []
    grid_results: list[dict[str, Any]] = []
    aggregates: dict[str, dict[int, dict[str, list[float]]]] = {}
    top1_counts: dict[str, dict[int, int]] = {}
    bucket_window_counts: dict[str, int] = {}

    for w_idx, w in enumerate(windows):
        train_df = frame.iloc[int(w["train_start"]) : int(w["train_end"])]
        test_df = (
            frame.iloc[int(w["test_start"]) : int(w["test_end"])]
            if bool(use_test_window) and int(w["test_start"]) >= 0
            else None
        )

        row_select: dict[str, int] = {}
        for bucket in bucket_set:
            _all_ns = list(range(int(bucket.low), int(bucket.high) + 1))
            if snap_to_nice:
                _nice = sorted(set(int(x) for x in (nice_numbers or DEFAULT_SMA_NICE_NUMBERS)))
                _nice_in_range = [n for n in _nice if bucket.low <= n <= bucket.high]
                candidate_ns = _nice_in_range if _nice_in_range else _all_ns[:1]
            else:
                candidate_ns = _all_ns
            candidate_rows: list[dict[str, Any]] = []
            agg_bucket = aggregates.setdefault(bucket.bucket_id, {})
            for n in candidate_ns:
                train_eval = _evaluate_sma_window(
                    train_df,
                    n=int(n),
                    allow_short=bool(allow_short),
                    signal_mode=signal_mode,
                    score_drawdown_weight=float(score_drawdown_weight),
                    score_turnover_weight=float(score_turnover_weight),
                    use_net_after_costs=bool(use_net_after_costs),
                    cost_rate=float(cost),
                    buy_threshold_perc=float(buy_threshold_perc),
                    sell_threshold_perc=float(sell_threshold_perc),
                    cooldown_days=int(cooldown_days),
                    min_volume=float(min_volume),
                )
                test_eval: dict[str, float] | None = None

                if bool(use_test_window) and test_df is not None and not test_df.empty:
                    test_eval = _evaluate_sma_window(
                        test_df,
                        n=int(n),
                        allow_short=bool(allow_short),
                        signal_mode=signal_mode,
                        score_drawdown_weight=float(score_drawdown_weight),
                        score_turnover_weight=float(score_turnover_weight),
                        use_net_after_costs=bool(use_net_after_costs),
                        cost_rate=float(cost),
                        buy_threshold_perc=float(buy_threshold_perc),
                        sell_threshold_perc=float(sell_threshold_perc),
                        cooldown_days=int(cooldown_days),
                        min_volume=float(min_volume),
                    )

                train_score = float(train_eval.get("score", float("-inf")))
                train_sharpe = float(train_eval.get("sharpe", 0.0))
                train_dd = float(train_eval.get("max_drawdown", 0.0))
                train_turnover = float(train_eval.get("turnover", 0.0))

                test_score = float(test_eval.get("score", float("-inf"))) if test_eval is not None else None
                test_sharpe = float(test_eval.get("sharpe", 0.0)) if test_eval is not None else None
                test_dd = float(test_eval.get("max_drawdown", 0.0)) if test_eval is not None else None
                test_turnover = float(test_eval.get("turnover", 0.0)) if test_eval is not None else None

                selection_score = test_score if selection_basis == "test" else train_score
                if selection_score is None:
                    selection_score = float("-inf")

                candidate_row = {
                    "n": int(n),
                    "train_score": float(train_score),
                    "train_sharpe": float(train_sharpe),
                    "train_max_drawdown": float(train_dd),
                    "train_turnover": float(train_turnover),
                    "test_score": float(test_score) if test_score is not None else None,
                    "test_sharpe": float(test_sharpe) if test_sharpe is not None else None,
                    "test_max_drawdown": float(test_dd) if test_dd is not None else None,
                    "test_turnover": float(test_turnover) if test_turnover is not None else None,
                    "selection_score": float(selection_score),
                }
                candidate_rows.append(candidate_row)

                n_agg = agg_bucket.setdefault(
                    int(n),
                    {
                        "train_score": [],
                        "train_sharpe": [],
                        "train_max_drawdown": [],
                        "train_turnover": [],
                        "test_score": [],
                        "test_sharpe": [],
                        "test_max_drawdown": [],
                        "test_turnover": [],
                        "selection_score": [],
                    },
                )
                n_agg["train_score"].append(float(train_score))
                n_agg["train_sharpe"].append(float(train_sharpe))
                n_agg["train_max_drawdown"].append(float(train_dd))
                n_agg["train_turnover"].append(float(train_turnover))
                if test_score is not None:
                    n_agg["test_score"].append(float(test_score))
                if test_sharpe is not None:
                    n_agg["test_sharpe"].append(float(test_sharpe))
                if test_dd is not None:
                    n_agg["test_max_drawdown"].append(float(test_dd))
                if test_turnover is not None:
                    n_agg["test_turnover"].append(float(test_turnover))
                n_agg["selection_score"].append(float(selection_score))

                train_start_ts = train_df.index[0]
                train_end_ts = train_df.index[-1]
                test_start_ts = test_df.index[0] if test_df is not None and not test_df.empty else None
                test_end_ts = test_df.index[-1] if test_df is not None and not test_df.empty else None
                grid_results.append(
                    {
                        "window_index": int(w_idx),
                        "bucket_id": bucket.bucket_id,
                        "bucket_low": int(bucket.low),
                        "bucket_high": int(bucket.high),
                        "n": int(n),
                        "train_start": train_start_ts.isoformat(),
                        "train_end": train_end_ts.isoformat(),
                        "test_start": test_start_ts.isoformat() if test_start_ts is not None else None,
                        "test_end": test_end_ts.isoformat() if test_end_ts is not None else None,
                        "train_score": float(train_score),
                        "train_sharpe": float(train_sharpe),
                        "train_max_drawdown": float(train_dd),
                        "train_turnover": float(train_turnover),
                        "test_score": float(test_score) if test_score is not None else None,
                        "test_sharpe": float(test_sharpe) if test_sharpe is not None else None,
                        "test_max_drawdown": float(test_dd) if test_dd is not None else None,
                        "test_turnover": float(test_turnover) if test_turnover is not None else None,
                        "selection_basis": selection_basis,
                        "selection_score": float(selection_score),
                    }
                )

            best_for_window = _pick_top_row(candidate_rows, score_key="selection_score")
            best_n = int(best_for_window["n"])
            row_select[bucket.bucket_id] = best_n

            bucket_counts = top1_counts.setdefault(bucket.bucket_id, {})
            bucket_counts[best_n] = int(bucket_counts.get(best_n, 0)) + 1
            bucket_window_counts[bucket.bucket_id] = int(bucket_window_counts.get(bucket.bucket_id, 0)) + 1

            winner = {
                "window_index": int(w_idx),
                "bucket_id": bucket.bucket_id,
                "bucket_low": int(bucket.low),
                "bucket_high": int(bucket.high),
                "best_n": int(best_n),
                "train_start": train_df.index[0].isoformat(),
                "train_end": train_df.index[-1].isoformat(),
                "test_start": (test_df.index[0].isoformat() if test_df is not None and not test_df.empty else None),
                "test_end": (test_df.index[-1].isoformat() if test_df is not None and not test_df.empty else None),
                "score": float(best_for_window.get("selection_score", 0.0)),
                "sharpe": (
                    float(best_for_window.get("test_sharpe", 0.0))
                    if selection_basis == "test"
                    else float(best_for_window.get("train_sharpe", 0.0))
                ),
                "max_drawdown": (
                    float(best_for_window.get("test_max_drawdown", 0.0))
                    if selection_basis == "test"
                    else float(best_for_window.get("train_max_drawdown", 0.0))
                ),
                "turnover": (
                    float(best_for_window.get("test_turnover", 0.0))
                    if selection_basis == "test"
                    else float(best_for_window.get("train_turnover", 0.0))
                ),
                "train_score": float(best_for_window.get("train_score", 0.0)),
                "train_sharpe": float(best_for_window.get("train_sharpe", 0.0)),
                "train_max_drawdown": float(best_for_window.get("train_max_drawdown", 0.0)),
                "train_turnover": float(best_for_window.get("train_turnover", 0.0)),
                "test_score": best_for_window.get("test_score"),
                "test_sharpe": best_for_window.get("test_sharpe"),
                "test_max_drawdown": best_for_window.get("test_max_drawdown"),
                "test_turnover": best_for_window.get("test_turnover"),
                "selection_basis": selection_basis,
            }
            winners.append(winner)

        matrix.append(
            {
                "window_index": int(w_idx),
                "train_start": train_df.index[0].isoformat(),
                "train_end": train_df.index[-1].isoformat(),
                "test_start": (test_df.index[0].isoformat() if test_df is not None and not test_df.empty else None),
                "test_end": (test_df.index[-1].isoformat() if test_df is not None and not test_df.empty else None),
                "selections": row_select,
            }
        )
        if progress_callback is not None:
            try:
                progress_callback(int(w_idx + 1), int(len(windows)))
            except Exception:
                pass

    bucket_reports: list[dict[str, Any]] = []
    bucket_global_rankings: list[dict[str, Any]] = []
    defaults: list[int] = []
    selected_rank_rows: list[dict[str, Any]] = []

    for bucket in bucket_set:
        bucket_aggs = aggregates.get(bucket.bucket_id, {})
        ranking_rows: list[dict[str, Any]] = []
        for n in sorted(bucket_aggs.keys()):
            metrics = bucket_aggs[n]
            mean_train_score = _safe_mean(metrics["train_score"])
            mean_test_score = _safe_mean(metrics["test_score"])
            mean_selection_score = _safe_mean(metrics["selection_score"])
            window_count_for_n = int(len(metrics["selection_score"]))
            top_count = int(top1_counts.get(bucket.bucket_id, {}).get(int(n), 0))
            bucket_window_count = int(bucket_window_counts.get(bucket.bucket_id, 0))
            win_rate_global = float(top_count / bucket_window_count) if bucket_window_count > 0 else 0.0
            ranking_rows.append(
                {
                    "n": int(n),
                    "mean_train_score": mean_train_score,
                    "mean_test_score": mean_test_score,
                    "mean_train_sharpe": _safe_mean(metrics["train_sharpe"]),
                    "mean_test_sharpe": _safe_mean(metrics["test_sharpe"]),
                    "mean_train_max_drawdown": _safe_mean(metrics["train_max_drawdown"]),
                    "mean_test_max_drawdown": _safe_mean(metrics["test_max_drawdown"]),
                    "mean_train_turnover": _safe_mean(metrics["train_turnover"]),
                    "mean_test_turnover": _safe_mean(metrics["test_turnover"]),
                    "mean_selection_score": mean_selection_score,
                    "stability_std_selection_score": _safe_std(metrics["selection_score"]),
                    "stability_std_test_score": _safe_std(metrics["test_score"]),
                    "sample_count_windows": window_count_for_n,
                    "top1_window_count": top_count,
                    "win_rate_global": win_rate_global,
                    "selection_basis": selection_basis,
                }
            )

        ranking_rows = sorted(
            ranking_rows,
            key=lambda row: (-float(row.get("mean_selection_score", float("-inf"))), int(row.get("n", 10**9))),
        )
        if not ranking_rows:
            raise ValueError(f"No ranking rows computed for bucket {bucket.bucket_id}.")

        best_n_global = int(ranking_rows[0]["n"])
        chosen_default = int(best_n_global)
        if snap_to_nice:
            chosen_default = _snap_to_nice(
                chosen_default,
                low=int(bucket.low),
                high=int(bucket.high),
                nice_numbers=nice_numbers or DEFAULT_SMA_NICE_NUMBERS,
            )
        chosen_rank = next((r for r in ranking_rows if int(r.get("n", -1)) == int(chosen_default)), ranking_rows[0])

        defaults.append(int(chosen_default))
        selected_rank_rows.append(dict(chosen_rank))

        report = {
            "bucket_id": bucket.bucket_id,
            "bucket_label": bucket.label,
            "bucket_low": int(bucket.low),
            "bucket_high": int(bucket.high),
            "chosen_default_n": int(chosen_default),
            "best_n_global_unsnapped": int(best_n_global),
            "selection_basis": selection_basis,
            "selection_tie_breaker": "highest mean selection score, then smallest n",
            "sample_count": int(chosen_rank.get("sample_count_windows", 0) or 0),
            "win_rate": float(chosen_rank.get("win_rate_global", 0.0) or 0.0),
        }
        _apply_report_metrics(report, chosen_rank, use_test_window=bool(use_test_window))
        bucket_reports.append(report)

        bucket_global_rankings.append(
            {
                "bucket_id": bucket.bucket_id,
                "bucket_label": bucket.label,
                "bucket_low": int(bucket.low),
                "bucket_high": int(bucket.high),
                "selection_basis": selection_basis,
                "tie_breaker": "highest mean selection score, then smallest n",
                "rows": ranking_rows,
            }
        )

    defaults = _enforce_strict_increasing(defaults, bucket_set)
    for i, report in enumerate(bucket_reports):
        final_n = int(defaults[i])
        report["chosen_default_n"] = final_n
        ranking_rows = bucket_global_rankings[i]["rows"]
        rank_row = next((r for r in ranking_rows if int(r.get("n", -1)) == final_n), selected_rank_rows[i])
        _apply_report_metrics(report, rank_row, use_test_window=bool(use_test_window))
        report["sample_count"] = int(rank_row.get("sample_count_windows", 0) or 0)
        report["win_rate"] = float(rank_row.get("win_rate_global", 0.0) or 0.0)

    return {
        "meta": {
            "train_window": int(train_window),
            "step_size": int(step_size),
            "use_test_window": bool(use_test_window),
            "test_window": int(test_window),
            "horizon": str(horizon_cfg.name.value),
            "horizon_label": str(horizon_cfg.label),
            "horizon_cfg": {
                "train_window": int(horizon_cfg.train_window),
                "test_window": int(horizon_cfg.test_window),
                "step_size": int(horizon_cfg.step_size),
                "use_test_window": bool(horizon_cfg.use_test_window),
            },
            "max_feasible_n": int(max_feasible_n),
            "enforce_feasible_train_half": bool(enforce_feasible_train_half),
            "signal_mode": str(signal_mode),
            "allow_short": bool(allow_short),
            "buy_threshold_perc": float(buy_threshold_perc),
            "sell_threshold_perc": float(sell_threshold_perc),
            "cooldown_days": int(cooldown_days),
            "min_volume": float(min_volume),
            "score_weights": {
                "drawdown": float(score_drawdown_weight),
                "turnover": float(score_turnover_weight),
            },
            "use_net_after_costs": bool(use_net_after_costs),
            "cost_rate_applied": float(cost),
            "mode_threshold": float(mode_threshold),
            "snap_to_nice": bool(snap_to_nice),
            "selection_basis": selection_basis,
        },
        "warnings": warnings,
        "window_count": int(len(windows)),
        "defaults": [int(x) for x in defaults],
        "bucket_reports": bucket_reports,
        "bucket_global_rankings": bucket_global_rankings,
        "grid_results": grid_results,
        "walk_forward_winners": winners,
        "selection_matrix": matrix,
        "selection_matrix_basis": selection_basis,
    }


def discover_sma_defaults_all_horizons(
    bars: pd.DataFrame,
    *,
    buckets: Sequence[Mapping[str, Any]] | None = None,
    train_window: int | None = None,
    step_size: int | None = None,
    use_test_window: bool | None = None,
    test_window: int | None = None,
    enforce_feasible_train_half: bool = True,
    override_feasible_max_n: int | None = None,
    allow_short: bool = False,
    signal_mode: str = "level",
    buy_threshold_perc: float = 0.0,
    sell_threshold_perc: float = 0.0,
    cooldown_days: int = 0,
    min_volume: float = 0.0,
    score_drawdown_weight: float = 0.5,
    score_turnover_weight: float = 0.1,
    use_net_after_costs: bool = False,
    cost_model: Mapping[str, Any] | None = None,
    mode_threshold: float = 0.20,
    snap_to_nice: bool = True,
    nice_numbers: Sequence[int] | None = None,
    primary_horizon: str | None = None,
    horizons: Sequence[str] | None = None,
    horizon_overrides: Mapping[str, Any] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    requested_horizons = list(horizons or TRADING_HORIZON_VALUES)
    normalized_horizons: list[str] = []
    for raw in requested_horizons:
        token = _normalize_trading_horizon(raw, default="")
        if token and token not in normalized_horizons:
            normalized_horizons.append(token)
    if not normalized_horizons:
        normalized_horizons = list(TRADING_HORIZON_VALUES)

    active_horizon = _normalize_trading_horizon(primary_horizon, default=normalized_horizons[0])
    if active_horizon not in normalized_horizons:
        normalized_horizons.insert(0, active_horizon)

    total_hint = 0
    per_horizon_window_hint: dict[str, int] = {}
    for hz in normalized_horizons:
        cfg = get_horizon_config(hz, overrides=horizon_overrides)
        use_explicit_windows = hz == active_horizon
        hint_train = int(train_window) if use_explicit_windows and train_window is not None else int(cfg.train_window)
        hint_step = int(step_size) if use_explicit_windows and step_size is not None else int(cfg.step_size)
        hint_test = int(test_window) if use_explicit_windows and test_window is not None else int(cfg.test_window)
        hint_use_test = bool(use_test_window) if use_test_window is not None else bool(cfg.use_test_window)
        try:
            hint_windows = len(
                _walk_forward_windows(
                    int(len(bars)),
                    train_window=int(hint_train),
                    step_size=int(hint_step),
                    use_test_window=bool(hint_use_test),
                    test_window=int(hint_test),
                )
            )
        except Exception:
            hint_windows = 1
        per_horizon_window_hint[hz] = max(int(hint_windows), 1)
        total_hint += int(per_horizon_window_hint[hz])
    total_hint = max(int(total_hint), 1)

    global_done = 0
    by_horizon: dict[str, dict[str, Any]] = {}
    for hz in normalized_horizons:
        local_hint = max(int(per_horizon_window_hint.get(hz, 1)), 1)

        def _on_progress(done: int, total: int) -> None:
            if progress_callback is None:
                return
            denom = max(total_hint, 1)
            local_total = max(int(total), local_hint, 1)
            local_done = min(max(int(done), 0), local_total)
            progress_callback(min(global_done + local_done, denom), denom)

        use_explicit_windows = hz == active_horizon
        result = discover_sma_defaults(
            bars,
            buckets=buckets,
            train_window=(int(train_window) if use_explicit_windows and train_window is not None else None),
            step_size=(int(step_size) if use_explicit_windows and step_size is not None else None),
            use_test_window=use_test_window,
            test_window=(int(test_window) if use_explicit_windows and test_window is not None else None),
            enforce_feasible_train_half=bool(enforce_feasible_train_half),
            override_feasible_max_n=override_feasible_max_n,
            allow_short=bool(allow_short),
            signal_mode=str(signal_mode),
            buy_threshold_perc=float(buy_threshold_perc),
            sell_threshold_perc=float(sell_threshold_perc),
            cooldown_days=int(cooldown_days),
            min_volume=float(min_volume),
            score_drawdown_weight=float(score_drawdown_weight),
            score_turnover_weight=float(score_turnover_weight),
            use_net_after_costs=bool(use_net_after_costs),
            cost_model=cost_model,
            mode_threshold=float(mode_threshold),
            snap_to_nice=bool(snap_to_nice),
            nice_numbers=nice_numbers,
            horizon=hz,
            horizon_overrides=horizon_overrides,
            progress_callback=_on_progress if progress_callback is not None else None,
        )
        by_horizon[hz] = dict(result)
        global_done += local_hint
        if progress_callback is not None:
            progress_callback(min(global_done, total_hint), total_hint)

    active_payload = dict(by_horizon.get(active_horizon) or by_horizon[normalized_horizons[0]])
    active_meta = dict(active_payload.get("meta") or {})
    active_meta["active_horizon"] = str(active_horizon)
    active_meta["computed_horizons"] = list(normalized_horizons)
    active_payload["meta"] = active_meta
    active_payload["active_horizon"] = str(active_horizon)
    active_payload["computed_horizons"] = list(normalized_horizons)
    active_payload["horizons"] = {key: value for key, value in by_horizon.items()}
    active_payload["defaults_by_horizon"] = {
        key: [int(x) for x in list((value or {}).get("defaults") or [])]
        for key, value in by_horizon.items()
    }
    active_payload["horizon_summaries"] = [
        {
            "horizon": key,
            "horizon_label": str(((value.get("meta") or {}).get("horizon_label")) if isinstance(value, dict) else ""),
            "window_count": int((value.get("window_count") or 0) if isinstance(value, dict) else 0),
            "defaults": [int(x) for x in list((value.get("defaults") or []) if isinstance(value, dict) else [])],
        }
        for key, value in by_horizon.items()
    ]
    return active_payload
