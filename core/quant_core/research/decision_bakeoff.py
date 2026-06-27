"""Offline bake-off for TA score aggregation and action thresholds.

This module is intentionally app-agnostic.  It consumes exported
``signal_score_history``-style rows plus OHLCV/close prices, then evaluates
candidate decision policies out-of-sample.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from .stats.ic import _newey_west_var, _spearman_corr


CATEGORY_ORDER = ("tendance", "momentum", "oscillation", "volume")
ACTION_LABELS = ("strong_sell", "sell", "hold", "buy", "strong_buy")
FIXED_THRESHOLDS = (-50.0, -15.0, 15.0, 50.0)
HORIZON_FORWARD_WINDOWS: dict[str, tuple[int, ...]] = {
    "short": (1, 2, 3, 4, 5),
    "weekly": (1, 2, 3, 4, 5),
    "medium": (6, 10, 15, 21),
    "monthly": (6, 10, 15, 21),
    "long": (30, 60, 120, 200),
    "quarterly": (30, 60, 120, 200),
}


def _calculate_forward_returns(
    prices: pd.Series | pd.DataFrame, h: int, method: str = "close_to_close"
) -> pd.Series:
    """Replicate signal forward-return calculation without importing app modules."""
    if isinstance(prices, pd.Series):
        if method != "close_to_close":
            return prices.pct_change(h).shift(-h)
        return prices.pct_change(h).shift(-h)

    p = prices.copy()
    p.columns = [str(c).lower() for c in p.columns]

    if "close" not in p.columns:
        if "adj close" in p.columns:
            p["close"] = p["adj close"]
        else:
            p["close"] = p.iloc[:, 0]
    if "open" not in p.columns:
        p["open"] = p["close"]

    if method == "close_to_close":
        return p["close"].pct_change(h).shift(-h)
    if method == "open_to_open":
        return (p["open"].shift(-(h + 1)) / p["open"].shift(-1)) - 1
    if method == "close_to_open":
        return (p["open"].shift(-h) / p["close"]) - 1
    if method == "open_to_close":
        return (p["close"].shift(-h) / p["open"].shift(-1)) - 1
    return p["close"].pct_change(h).shift(-h)


@dataclass(frozen=True)
class BakeoffConfig:
    source: str
    horizon: str
    symbols: tuple[str, ...] | None = None
    categories: tuple[str, ...] = CATEGORY_ORDER
    fwd_horizons: tuple[int, ...] | None = None
    n_splits: int = 5
    min_train_dates: int = 120
    min_test_dates: int = 30
    min_action_obs: int = 8
    cost_bps: float = 10.0
    use_oos_only: bool = False
    include_optional_ml: bool = False
    random_seed: int = 42


@dataclass(frozen=True)
class FoldWindow:
    fold: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_index: np.ndarray
    test_index: np.ndarray


@dataclass
class PolicyState:
    method: str
    thresholds: tuple[float, float, float, float] = FIXED_THRESHOLDS
    coefficients: dict[str, float] = field(default_factory=dict)
    intercept: float = 0.0
    score_scale: float = 1.0
    category_weights: dict[str, float] = field(default_factory=dict)
    category_signs: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BakeoffResult:
    config: BakeoffConfig
    metrics: pd.DataFrame
    predictions: pd.DataFrame
    thresholds: pd.DataFrame
    feature_frame: pd.DataFrame

    def summary_markdown(self) -> str:
        if self.metrics.empty:
            return "# TA Decision Bake-Off\n\nNo valid folds were produced.\n"

        grouped = (
            self.metrics.groupby("method", as_index=False)
            .agg(
                mean_utility=("utility_mean", "mean"),
                median_utility=("utility_mean", "median"),
                mean_ic=("ic", "mean"),
                mean_hit_rate=("hit_rate", "mean"),
                mean_coverage=("coverage", "mean"),
                folds=("fold", "nunique"),
            )
            .sort_values(["mean_utility", "mean_ic"], ascending=[False, False])
        )
        baseline = grouped[grouped["method"] == "baseline_fixed"]
        baseline_utility = (
            float(baseline.iloc[0]["mean_utility"]) if not baseline.empty else float("nan")
        )

        lines = [
            "# TA Decision Bake-Off",
            "",
            "Offline research run only. No application scoring behavior was changed.",
            "",
            "## Configuration",
            "",
            f"- source: `{self.config.source}`",
            f"- horizon: `{self.config.horizon}`",
            f"- symbols: `{','.join(self.config.symbols) if self.config.symbols else 'all'}`",
            f"- forward horizons: `{','.join(map(str, self._forward_horizons()))}`",
            f"- cost bps: `{self.config.cost_bps}`",
            f"- OOS-only rows: `{self.config.use_oos_only}`",
            "",
            "## Method Ranking",
            "",
            "| rank | method | mean utility | delta vs baseline | mean IC | hit rate | coverage | folds |",
            "|---:|---|---:|---:|---:|---:|---:|---:|",
        ]
        for rank, row in enumerate(grouped.itertuples(index=False), start=1):
            utility = float(row.mean_utility)
            delta = utility - baseline_utility if math.isfinite(baseline_utility) else float("nan")
            lines.append(
                "| {rank} | `{method}` | {utility:.6f} | {delta:.6f} | "
                "{ic:.4f} | {hit:.3f} | {coverage:.3f} | {folds} |".format(
                    rank=rank,
                    method=row.method,
                    utility=utility,
                    delta=delta,
                    ic=float(row.mean_ic) if pd.notna(row.mean_ic) else float("nan"),
                    hit=float(row.mean_hit_rate) if pd.notna(row.mean_hit_rate) else float("nan"),
                    coverage=float(row.mean_coverage) if pd.notna(row.mean_coverage) else float("nan"),
                    folds=int(row.folds),
                )
            )

        winner = grouped.iloc[0]
        winner_method = str(winner["method"])
        winner_delta = (
            float(winner["mean_utility"]) - baseline_utility
            if math.isfinite(baseline_utility)
            else float("nan")
        )
        if winner_method == "baseline_fixed":
            recommendation = "Keep the current method for now."
        elif math.isfinite(winner_delta) and winner_delta > 0:
            recommendation = (
                f"`{winner_method}` won this offline run. Consider app changes only "
                "after repeating on a broader sample and confirming stability."
            )
        else:
            recommendation = "No alternative produced a reliable improvement over baseline."

        lines.extend(["", "## Recommendation", "", recommendation, ""])
        return "\n".join(lines)

    def _forward_horizons(self) -> tuple[int, ...]:
        if self.config.fwd_horizons:
            return self.config.fwd_horizons
        return HORIZON_FORWARD_WINDOWS.get(self.config.horizon, (1, 5, 10, 21))


def normalize_thresholds(
    thresholds: Sequence[float],
) -> tuple[float, float, float, float]:
    if len(thresholds) != 4:
        raise ValueError("Expected exactly four thresholds.")
    vals = tuple(float(x) for x in thresholds)
    if not all(math.isfinite(x) for x in vals):
        raise ValueError("Thresholds must be finite.")
    if not (vals[0] < vals[1] < vals[2] < vals[3]):
        raise ValueError("Thresholds must be strictly increasing.")
    return vals  # type: ignore[return-value]


def label_scores(
    scores: Sequence[float] | pd.Series | np.ndarray,
    thresholds: Sequence[float] = FIXED_THRESHOLDS,
) -> np.ndarray:
    t0, t1, t2, t3 = normalize_thresholds(thresholds)
    arr = np.asarray(scores, dtype="float64")
    labels = np.full(arr.shape, "strong_buy", dtype=object)
    labels[arr <= t3] = "buy"
    labels[arr <= t2] = "hold"
    labels[arr < t1] = "sell"
    labels[arr < t0] = "strong_sell"
    return labels


def action_direction(labels: Sequence[str] | np.ndarray) -> np.ndarray:
    mapping = {
        "strong_sell": -1.0,
        "sell": -1.0,
        "hold": 0.0,
        "buy": 1.0,
        "strong_buy": 1.0,
    }
    return np.asarray([mapping.get(str(label), 0.0) for label in labels], dtype="float64")


def action_utility(
    labels: Sequence[str] | np.ndarray,
    forward_returns: Sequence[float] | pd.Series | np.ndarray,
    *,
    cost_bps: float = 10.0,
) -> np.ndarray:
    direction = action_direction(labels)
    ret = np.asarray(forward_returns, dtype="float64")
    cost = float(cost_bps) / 10000.0
    return direction * ret - np.where(direction != 0.0, cost, 0.0)


def topsis_closeness(
    matrix: Sequence[Sequence[float]] | np.ndarray,
    *,
    weights: Sequence[float] | None = None,
    benefit: Sequence[bool] | None = None,
) -> np.ndarray:
    """Return TOPSIS closeness scores in [0, 1] for each row."""
    x = np.asarray(matrix, dtype="float64")
    if x.ndim != 2:
        raise ValueError("TOPSIS matrix must be 2-dimensional.")
    if x.shape[0] == 0 or x.shape[1] == 0:
        return np.zeros(x.shape[0], dtype="float64")

    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    denom = np.sqrt(np.sum(x * x, axis=0))
    denom = np.where(denom <= 1e-12, 1.0, denom)
    norm = x / denom

    if weights is None:
        w = np.ones(x.shape[1], dtype="float64") / x.shape[1]
    else:
        w = np.asarray(weights, dtype="float64")
        if len(w) != x.shape[1]:
            raise ValueError("TOPSIS weights length must match criteria count.")
        w = np.maximum(w, 0.0)
        total = float(np.sum(w))
        w = w / total if total > 0 else np.ones(x.shape[1], dtype="float64") / x.shape[1]

    if benefit is None:
        benefit_arr = np.ones(x.shape[1], dtype=bool)
    else:
        benefit_arr = np.asarray(benefit, dtype=bool)
        if len(benefit_arr) != x.shape[1]:
            raise ValueError("TOPSIS benefit flags length must match criteria count.")

    weighted = norm * w
    ideal = np.where(benefit_arr, np.max(weighted, axis=0), np.min(weighted, axis=0))
    anti = np.where(benefit_arr, np.min(weighted, axis=0), np.max(weighted, axis=0))
    d_pos = np.sqrt(np.sum((weighted - ideal) ** 2, axis=1))
    d_neg = np.sqrt(np.sum((weighted - anti) ** 2, axis=1))
    return d_neg / np.where((d_pos + d_neg) <= 1e-12, 1.0, d_pos + d_neg)


def prepare_feature_frame(
    score_history: pd.DataFrame,
    prices: pd.DataFrame | pd.Series,
    *,
    source: str,
    horizon: str,
    fwd_horizon: int,
    symbols: Iterable[str] | None = None,
    categories: Sequence[str] = CATEGORY_ORDER,
    return_calc_method: str = "close_to_close",
    use_oos_only: bool = False,
) -> pd.DataFrame:
    """Build a model-ready frame for one forward horizon."""
    scores = _normalize_score_history(score_history)
    prices_long = _normalize_prices(prices)
    symbol_filter = {str(s).upper() for s in symbols} if symbols is not None else None

    scores = scores[
        (scores["source"].astype(str) == str(source))
        & (scores["horizon"].astype(str) == str(horizon))
    ].copy()
    if symbol_filter is not None:
        scores = scores[scores["symbol"].astype(str).str.upper().isin(symbol_filter)]
    if use_oos_only and "is_oos" in scores.columns:
        scores = scores[scores["is_oos"].astype(bool)]
    if scores.empty:
        return pd.DataFrame()

    pivot = (
        scores.pivot_table(
            index=["date", "symbol"],
            columns="category",
            values="score_pct",
            aggfunc="mean",
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    for category in categories:
        if category not in pivot.columns:
            pivot[category] = np.nan
    pivot = pivot.dropna(subset=list(categories), how="all")
    if pivot.empty:
        return pd.DataFrame()

    out_parts: list[pd.DataFrame] = []
    for symbol, p_sym in prices_long.groupby("symbol", sort=False):
        p_sym = p_sym.sort_values("date").copy()
        if symbol_filter is not None and str(symbol).upper() not in symbol_filter:
            continue
        p_sym = p_sym.set_index("date")
        if p_sym.empty:
            continue
        if return_calc_method == "close_to_close":
            price_input: pd.Series | pd.DataFrame = p_sym["close"]
        else:
            cols = [c for c in ("open", "close") if c in p_sym.columns]
            price_input = p_sym[cols] if cols else p_sym["close"]
        fwd = _calculate_forward_returns(price_input, int(fwd_horizon), method=return_calc_method)
        frame = p_sym[["close"]].copy()
        frame["fwd_return"] = fwd
        frame["symbol"] = str(symbol)
        frame = frame.reset_index()
        out_parts.append(frame)

    if not out_parts:
        return pd.DataFrame()

    fwd_frame = pd.concat(out_parts, ignore_index=True)
    merged = pivot.merge(fwd_frame, on=["date", "symbol"], how="inner").dropna(subset=["fwd_return"])
    if merged.empty:
        return pd.DataFrame()

    merged = merged.sort_values(["date", "symbol"]).reset_index(drop=True)
    merged["fwd_horizon"] = int(fwd_horizon)
    merged["baseline_score"] = merged[list(categories)].mean(axis=1)
    return merged


def purged_walk_forward_splits(
    frame: pd.DataFrame,
    *,
    date_col: str = "date",
    n_splits: int = 5,
    min_train_dates: int = 120,
    min_test_dates: int = 30,
    embargo: int = 1,
) -> list[FoldWindow]:
    """Expanding walk-forward splits with a date-count embargo."""
    if frame.empty:
        return []
    dates = pd.Index(pd.to_datetime(frame[date_col]).sort_values().unique())
    n_dates = len(dates)
    if n_dates < min_train_dates + min_test_dates + embargo:
        return []

    test_size = max(int(min_test_dates), (n_dates - min_train_dates - embargo) // max(1, n_splits))
    if test_size <= 0:
        return []

    windows: list[FoldWindow] = []
    for fold in range(int(n_splits)):
        train_end_pos = int(min_train_dates) - 1 + fold * test_size
        test_start_pos = train_end_pos + int(embargo) + 1
        test_end_pos = min(test_start_pos + test_size - 1, n_dates - 1)
        if test_start_pos >= n_dates or test_end_pos < test_start_pos:
            break
        if (test_end_pos - test_start_pos + 1) < int(min_test_dates):
            break

        train_start = pd.Timestamp(dates[0])
        train_end = pd.Timestamp(dates[train_end_pos])
        test_start = pd.Timestamp(dates[test_start_pos])
        test_end = pd.Timestamp(dates[test_end_pos])
        date_values = pd.to_datetime(frame[date_col])
        train_index = frame.index[(date_values >= train_start) & (date_values <= train_end)].to_numpy()
        test_index = frame.index[(date_values >= test_start) & (date_values <= test_end)].to_numpy()
        if len(train_index) == 0 or len(test_index) == 0:
            continue
        windows.append(
            FoldWindow(
                fold=fold,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                train_index=train_index,
                test_index=test_index,
            )
        )
        if test_end_pos >= n_dates - 1:
            break
    return windows


def run_bakeoff(
    score_history: pd.DataFrame,
    prices: pd.DataFrame | pd.Series,
    config: BakeoffConfig,
) -> BakeoffResult:
    """Run all configured methods out-of-sample."""
    fwd_horizons = config.fwd_horizons or HORIZON_FORWARD_WINDOWS.get(config.horizon, (1, 5, 10, 21))
    all_metrics: list[dict[str, Any]] = []
    all_predictions: list[pd.DataFrame] = []
    all_thresholds: list[dict[str, Any]] = []
    all_features: list[pd.DataFrame] = []
    methods = _method_names(config.include_optional_ml)

    for fwd_h in fwd_horizons:
        frame = prepare_feature_frame(
            score_history,
            prices,
            source=config.source,
            horizon=config.horizon,
            fwd_horizon=int(fwd_h),
            symbols=config.symbols,
            categories=config.categories,
            use_oos_only=config.use_oos_only,
        )
        if frame.empty:
            continue
        frame = frame.reset_index(drop=True)
        frame["_row_id"] = np.arange(len(frame))
        all_features.append(frame.copy())
        folds = purged_walk_forward_splits(
            frame,
            n_splits=config.n_splits,
            min_train_dates=config.min_train_dates,
            min_test_dates=config.min_test_dates,
            embargo=int(fwd_h),
        )
        for window in folds:
            train = frame.loc[window.train_index].copy()
            test = frame.loc[window.test_index].copy()
            for method in methods:
                state = fit_policy(method, train, config)
                pred = predict_policy(state, test, config)
                metric = evaluate_predictions(
                    pred,
                    method=method,
                    fold=window.fold,
                    fwd_horizon=int(fwd_h),
                    cost_bps=config.cost_bps,
                )
                metric.update(
                    {
                        "train_start": window.train_start.date().isoformat(),
                        "train_end": window.train_end.date().isoformat(),
                        "test_start": window.test_start.date().isoformat(),
                        "test_end": window.test_end.date().isoformat(),
                    }
                )
                all_metrics.append(metric)
                pred["method"] = method
                pred["fold"] = window.fold
                pred["fwd_horizon"] = int(fwd_h)
                all_predictions.append(pred)
                all_thresholds.append(
                    {
                        "method": method,
                        "fold": window.fold,
                        "fwd_horizon": int(fwd_h),
                        "threshold_strong_sell": state.thresholds[0],
                        "threshold_sell": state.thresholds[1],
                        "threshold_buy": state.thresholds[2],
                        "threshold_strong_buy": state.thresholds[3],
                        "metadata": json.dumps(state.metadata, sort_keys=True),
                    }
                )

    metrics_df = pd.DataFrame(all_metrics)
    predictions_df = pd.concat(all_predictions, ignore_index=True) if all_predictions else pd.DataFrame()
    thresholds_df = pd.DataFrame(all_thresholds)
    features_df = pd.concat(all_features, ignore_index=True) if all_features else pd.DataFrame()
    return BakeoffResult(config=config, metrics=metrics_df, predictions=predictions_df, thresholds=thresholds_df, feature_frame=features_df)


def fit_policy(method: str, train: pd.DataFrame, config: BakeoffConfig) -> PolicyState:
    method = str(method)
    if method == "baseline_fixed":
        return PolicyState(method=method, thresholds=FIXED_THRESHOLDS)
    if method == "threshold_optimized":
        thresholds = optimize_thresholds(
            train["baseline_score"],
            train["fwd_return"],
            cost_bps=config.cost_bps,
            min_action_obs=config.min_action_obs,
        )
        return PolicyState(method=method, thresholds=thresholds)
    if method == "ridge_linear":
        return _fit_ridge_linear(train, config)
    if method == "isotonic_calibrated":
        return _fit_isotonic(train, config)
    if method == "topsis_category":
        return _fit_topsis_category(train, config, ahp_prior=False)
    if method == "ahp_topsis_prior":
        return _fit_topsis_category(train, config, ahp_prior=True)
    if method == "topsis_action":
        return _fit_topsis_action(train, config)
    if method == "tree_regressor":
        return _fit_tree_regressor(train, config)
    raise ValueError(f"Unknown decision bake-off method: {method}")


def predict_policy(state: PolicyState, test: pd.DataFrame, config: BakeoffConfig) -> pd.DataFrame:
    score = _score_policy(state, test, config)
    if state.method == "topsis_action":
        labels = _predict_topsis_action_labels(state, test, config)
        score = _score_from_labels(labels)
    else:
        labels = label_scores(score, state.thresholds)
    out = test[["date", "symbol", "fwd_return", "baseline_score"]].copy()
    out["decision_score"] = np.asarray(score, dtype="float64")
    out["decision_label"] = labels
    out["utility"] = action_utility(labels, out["fwd_return"], cost_bps=config.cost_bps)
    return out


def optimize_thresholds(
    score: Sequence[float] | pd.Series | np.ndarray,
    fwd_return: Sequence[float] | pd.Series | np.ndarray,
    *,
    cost_bps: float,
    min_action_obs: int = 8,
) -> tuple[float, float, float, float]:
    s = pd.Series(score, dtype="float64").replace([np.inf, -np.inf], np.nan)
    r = pd.Series(fwd_return, dtype="float64").replace([np.inf, -np.inf], np.nan)
    df = pd.concat([s.rename("s"), r.rename("r")], axis=1).dropna()
    if len(df) < max(30, min_action_obs * 4):
        return FIXED_THRESHOLDS

    candidates = set(FIXED_THRESHOLDS)
    qs = (0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90)
    candidates.update(float(x) for x in np.nanquantile(df["s"].to_numpy(), qs))
    candidates.update(float(x) for x in (-80.0, -60.0, -30.0, 0.0, 30.0, 60.0, 80.0))
    vals = sorted({round(max(-99.0, min(99.0, x)), 6) for x in candidates if math.isfinite(x)})
    if len(vals) < 4:
        return FIXED_THRESHOLDS

    best_thresholds = FIXED_THRESHOLDS
    best_score = _threshold_objective(df["s"], df["r"], FIXED_THRESHOLDS, cost_bps, min_action_obs)
    # Four nested loops are acceptable here: this is an offline research script
    # and the candidate grid is deliberately small.
    for i in range(len(vals) - 3):
        for j in range(i + 1, len(vals) - 2):
            for k in range(j + 1, len(vals) - 1):
                for l in range(k + 1, len(vals)):
                    thr = (vals[i], vals[j], vals[k], vals[l])
                    obj = _threshold_objective(df["s"], df["r"], thr, cost_bps, min_action_obs)
                    if obj > best_score:
                        best_score = obj
                        best_thresholds = thr
    return best_thresholds


def evaluate_predictions(
    predictions: pd.DataFrame,
    *,
    method: str,
    fold: int,
    fwd_horizon: int,
    cost_bps: float,
) -> dict[str, Any]:
    if predictions.empty:
        return {
            "method": method,
            "fold": fold,
            "fwd_horizon": fwd_horizon,
            "n": 0,
            "utility_mean": float("nan"),
            "ic": float("nan"),
            "ic_tstat": float("nan"),
            "hit_rate": float("nan"),
            "coverage": 0.0,
        }
    labels = predictions["decision_label"].astype(str).to_numpy()
    direction = action_direction(labels)
    active = direction != 0.0
    fwd = predictions["fwd_return"].to_numpy(dtype="float64")
    score = predictions["decision_score"].to_numpy(dtype="float64")
    utility = action_utility(labels, fwd, cost_bps=cost_bps)
    hits = (direction[active] * fwd[active]) > 0 if np.any(active) else np.asarray([], dtype=bool)
    ic, tstat = _ic_and_tstat(score, fwd, fwd_horizon)
    return {
        "method": method,
        "fold": int(fold),
        "fwd_horizon": int(fwd_horizon),
        "n": int(len(predictions)),
        "utility_mean": float(np.nanmean(utility)) if len(utility) else float("nan"),
        "utility_sum": float(np.nansum(utility)) if len(utility) else float("nan"),
        "ic": ic,
        "ic_tstat": tstat,
        "hit_rate": float(np.mean(hits)) if len(hits) else float("nan"),
        "coverage": float(np.mean(active)) if len(active) else 0.0,
        "cost_bps": float(cost_bps),
    }


def write_bakeoff_artifacts(result: BakeoffResult, out_dir: str | Path) -> Path:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    result.metrics.to_csv(out_path / "metrics.csv", index=False)
    result.predictions.to_csv(out_path / "predictions_by_fold.csv", index=False)
    result.thresholds.to_csv(out_path / "thresholds_by_method.csv", index=False)
    rankings = _rankings(result.metrics)
    rankings.to_csv(out_path / "method_rankings.csv", index=False)
    (out_path / "summary.md").write_text(result.summary_markdown(), encoding="utf-8")
    (out_path / "config.json").write_text(
        json.dumps(_config_to_json(result.config), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return out_path


def _method_names(include_optional_ml: bool) -> tuple[str, ...]:
    names = [
        "baseline_fixed",
        "threshold_optimized",
        "ridge_linear",
        "isotonic_calibrated",
        "topsis_category",
        "topsis_action",
        "ahp_topsis_prior",
    ]
    if include_optional_ml:
        names.append("tree_regressor")
    return tuple(names)


def _normalize_score_history(score_history: pd.DataFrame) -> pd.DataFrame:
    df = score_history.copy()
    rename: dict[str, str] = {}
    for col in df.columns:
        low = str(col).strip().lower()
        if low in {"date", "dt", "as_of", "asof"}:
            rename[col] = "date"
        elif low == "ticker":
            rename[col] = "symbol"
        elif low in {"score", "score_pct", "value"}:
            rename[col] = "score_pct"
    df = df.rename(columns=rename)
    required = {"date", "symbol", "source", "category", "horizon", "score_pct"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"score_history missing required columns: {sorted(missing)}")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df["score_pct"] = pd.to_numeric(df["score_pct"], errors="coerce")
    return df


def _normalize_prices(prices: pd.DataFrame | pd.Series) -> pd.DataFrame:
    if isinstance(prices, pd.Series):
        df = prices.rename("close").to_frame().reset_index()
        df = df.rename(columns={df.columns[0]: "date"})
        df["symbol"] = "SINGLE"
    else:
        df = prices.copy()
        lower = {str(c).strip().lower(): c for c in df.columns}
        if "date" not in lower and isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index().rename(columns={df.index.name or "index": "date"})
            lower = {str(c).strip().lower(): c for c in df.columns}
        if "symbol" not in lower:
            value_cols = [c for c in df.columns if str(c).strip().lower() != "date"]
            close_col = _first_present(df, ["close", "adj close", "adj_close", "cloture", "clôture"])
            open_col = _first_present(df, ["open", "ouverture"])
            if close_col is not None:
                df = df.rename(columns={close_col: "close"})
                if open_col is not None:
                    df = df.rename(columns={open_col: "open"})
                df["symbol"] = "SINGLE"
            elif value_cols:
                date_col = lower.get("date") or df.columns[0]
                df = df.melt(id_vars=[date_col], value_vars=value_cols, var_name="symbol", value_name="close")
                df = df.rename(columns={date_col: "date"})
            else:
                raise ValueError("prices must include close data")
        else:
            df = df.rename(columns={lower["symbol"]: "symbol"})
            date_key = lower.get("date") or "date"
            if date_key in df.columns and date_key != "date":
                df = df.rename(columns={date_key: "date"})
            close_col = _first_present(df, ["close", "adj close", "adj_close", "cloture", "clôture"])
            if close_col is None:
                raise ValueError("prices missing close column")
            df = df.rename(columns={close_col: "close"})
            open_col = _first_present(df, ["open", "ouverture"])
            if open_col is not None and open_col != "open":
                df = df.rename(columns={open_col: "open"})

    if "date" not in df.columns:
        raise ValueError("prices missing date column")
    if "close" not in df.columns:
        raise ValueError("prices missing close column")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    if "open" in df.columns:
        df["open"] = pd.to_numeric(df["open"], errors="coerce")
    else:
        df["open"] = df["close"]
    return df.dropna(subset=["date", "symbol", "close"]).sort_values(["symbol", "date"])


def _first_present(df: pd.DataFrame, names: Sequence[str]) -> str | None:
    lower = {str(c).strip().lower(): str(c) for c in df.columns}
    for name in names:
        if name in lower:
            return lower[name]
    return None


def _threshold_objective(
    score: pd.Series,
    fwd_return: pd.Series,
    thresholds: tuple[float, float, float, float],
    cost_bps: float,
    min_action_obs: int,
) -> float:
    labels = label_scores(score, thresholds)
    direction = action_direction(labels)
    active = direction != 0.0
    if int(np.sum(direction > 0)) < min_action_obs or int(np.sum(direction < 0)) < min_action_obs:
        return -1e9
    util = action_utility(labels, fwd_return, cost_bps=cost_bps)
    coverage = float(np.mean(active)) if len(active) else 0.0
    if coverage < 0.02:
        return -1e9
    return float(np.nanmean(util)) - 0.0001 * max(0.0, 0.05 - coverage)


def _fit_ridge_linear(train: pd.DataFrame, config: BakeoffConfig) -> PolicyState:
    x = train[list(config.categories)].astype(float).fillna(0.0).to_numpy()
    y = train["fwd_return"].astype(float).to_numpy()
    if len(train) < 30:
        return PolicyState(method="ridge_linear", metadata={"fallback": "too_few_rows"})
    means = x.mean(axis=0)
    stds = x.std(axis=0)
    stds = np.where(stds <= 1e-9, 1.0, stds)
    xz = (x - means) / stds
    design = np.column_stack([np.ones(len(xz)), xz])
    lam = 1.0
    penalty = np.eye(design.shape[1]) * lam
    penalty[0, 0] = 0.0
    try:
        beta = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    except np.linalg.LinAlgError:
        beta = np.linalg.pinv(design.T @ design + penalty) @ design.T @ y
    train_pred = design @ beta
    scale = _prediction_scale(train_pred)
    train_score = np.clip(train_pred / scale * 100.0, -100.0, 100.0)
    thresholds = optimize_thresholds(
        train_score,
        y,
        cost_bps=config.cost_bps,
        min_action_obs=config.min_action_obs,
    )
    coefficients = {cat: float(beta[i + 1] / stds[i]) for i, cat in enumerate(config.categories)}
    intercept = float(beta[0] - np.sum(beta[1:] * means / stds))
    return PolicyState(
        method="ridge_linear",
        thresholds=thresholds,
        coefficients=coefficients,
        intercept=intercept,
        score_scale=scale,
        metadata={
            "feature_means": dict(zip(config.categories, map(float, means))),
            "feature_stds": dict(zip(config.categories, map(float, stds))),
        },
    )


def _fit_isotonic(train: pd.DataFrame, config: BakeoffConfig) -> PolicyState:
    score = train["baseline_score"].to_numpy(dtype="float64")
    y = train["fwd_return"].to_numpy(dtype="float64")
    if len(train) < 30:
        return PolicyState(method="isotonic_calibrated", metadata={"fallback": "too_few_rows"})
    try:
        from sklearn.isotonic import IsotonicRegression
    except Exception:
        return _fit_quantile_calibrator(train, config)
    corr = _safe_spearman(score, y)
    increasing = bool(corr >= 0 or math.isnan(corr))
    model = IsotonicRegression(increasing=increasing, out_of_bounds="clip")
    pred = model.fit_transform(score, y)
    scale = _prediction_scale(pred)
    train_score = np.clip(pred / scale * 100.0, -100.0, 100.0)
    thresholds = optimize_thresholds(
        train_score,
        y,
        cost_bps=config.cost_bps,
        min_action_obs=config.min_action_obs,
    )
    return PolicyState(
        method="isotonic_calibrated",
        thresholds=thresholds,
        score_scale=scale,
        metadata={
            "increasing": increasing,
            "x_thresholds": [float(v) for v in model.X_thresholds_],
            "y_thresholds": [float(v) for v in model.y_thresholds_],
        },
    )


def _fit_quantile_calibrator(train: pd.DataFrame, config: BakeoffConfig) -> PolicyState:
    score = train["baseline_score"].to_numpy(dtype="float64")
    y = train["fwd_return"].to_numpy(dtype="float64")
    bins = np.unique(np.nanquantile(score, np.linspace(0.0, 1.0, 11)))
    if len(bins) < 3:
        return PolicyState(method="isotonic_calibrated", metadata={"fallback": "no_bins"})
    bucket = np.digitize(score, bins[1:-1], right=True)
    means = {int(b): float(np.nanmean(y[bucket == b])) for b in np.unique(bucket)}
    pred = np.asarray([means[int(b)] for b in bucket], dtype="float64")
    scale = _prediction_scale(pred)
    train_score = np.clip(pred / scale * 100.0, -100.0, 100.0)
    thresholds = optimize_thresholds(train_score, y, cost_bps=config.cost_bps, min_action_obs=config.min_action_obs)
    return PolicyState(
        method="isotonic_calibrated",
        thresholds=thresholds,
        score_scale=scale,
        metadata={"fallback": "quantile", "bins": [float(x) for x in bins], "bucket_means": means},
    )


def _fit_topsis_category(train: pd.DataFrame, config: BakeoffConfig, *, ahp_prior: bool) -> PolicyState:
    rows = []
    signs: dict[str, float] = {}
    for category in config.categories:
        s = train[category].astype(float)
        r = train["fwd_return"].astype(float)
        ic, tstat = _ic_and_tstat(s.to_numpy(), r.to_numpy(), int(train["fwd_horizon"].iloc[0]))
        sign = -1.0 if math.isfinite(ic) and ic < 0 else 1.0
        signs[category] = sign
        oriented = s * sign
        spread = _extreme_spread(oriented, r)
        stability = _half_stability(oriented, r)
        coverage = float(np.mean(np.abs(s.to_numpy()) > 15.0))
        rows.append([abs(ic) if math.isfinite(ic) else 0.0, abs(tstat) if math.isfinite(tstat) else 0.0, max(0.0, spread), stability, coverage])
    criteria_weights = (0.45, 0.20, 0.20, 0.10, 0.05) if ahp_prior else None
    closeness = topsis_closeness(rows, weights=criteria_weights)
    if float(np.sum(closeness)) <= 1e-12:
        weights_arr = np.ones(len(config.categories), dtype="float64") / len(config.categories)
    else:
        weights_arr = closeness / np.sum(closeness)
    weights = {cat: float(w) for cat, w in zip(config.categories, weights_arr)}
    train_score = _weighted_oriented_score(train, weights, signs, config.categories)
    thresholds = optimize_thresholds(
        train_score,
        train["fwd_return"],
        cost_bps=config.cost_bps,
        min_action_obs=config.min_action_obs,
    )
    return PolicyState(
        method="ahp_topsis_prior" if ahp_prior else "topsis_category",
        thresholds=thresholds,
        category_weights=weights,
        category_signs=signs,
        metadata={"criteria": rows, "criteria_weights": list(criteria_weights) if criteria_weights else "equal"},
    )


def _fit_topsis_action(train: pd.DataFrame, config: BakeoffConfig) -> PolicyState:
    score = train["baseline_score"].to_numpy(dtype="float64")
    fixed_labels = label_scores(score, FIXED_THRESHOLDS)
    fwd = train["fwd_return"].to_numpy(dtype="float64")
    stats: dict[str, dict[str, dict[str, float]]] = {}
    for bucket in ACTION_LABELS:
        mask = fixed_labels == bucket
        stats[bucket] = {}
        for action in ACTION_LABELS:
            labels = np.full(np.sum(mask), action, dtype=object)
            util = action_utility(labels, fwd[mask], cost_bps=config.cost_bps)
            stats[bucket][action] = {
                "mean_utility": float(np.nanmean(util)) if len(util) else 0.0,
                "hit_rate": float(np.mean(util > 0.0)) if len(util) else 0.0,
                "n": float(len(util)),
            }
    return PolicyState(method="topsis_action", thresholds=FIXED_THRESHOLDS, metadata={"bucket_action_stats": stats})


def _fit_tree_regressor(train: pd.DataFrame, config: BakeoffConfig) -> PolicyState:
    try:
        from sklearn.ensemble import GradientBoostingRegressor
    except Exception:
        return PolicyState(method="tree_regressor", metadata={"fallback": "sklearn_unavailable"})
    if len(train) < 80:
        return PolicyState(method="tree_regressor", metadata={"fallback": "too_few_rows"})
    x = train[list(config.categories)].astype(float).fillna(0.0).to_numpy()
    y = train["fwd_return"].astype(float).to_numpy()
    model = GradientBoostingRegressor(
        n_estimators=60,
        max_depth=2,
        learning_rate=0.05,
        random_state=config.random_seed,
    )
    model.fit(x, y)
    pred = model.predict(x)
    scale = _prediction_scale(pred)
    train_score = np.clip(pred / scale * 100.0, -100.0, 100.0)
    thresholds = optimize_thresholds(train_score, y, cost_bps=config.cost_bps, min_action_obs=config.min_action_obs)
    return PolicyState(
        method="tree_regressor",
        thresholds=thresholds,
        score_scale=scale,
        metadata={"model": model},
    )


def _score_policy(state: PolicyState, frame: pd.DataFrame, config: BakeoffConfig) -> np.ndarray:
    if state.method in {"baseline_fixed", "threshold_optimized", "topsis_action"}:
        return frame["baseline_score"].to_numpy(dtype="float64")
    if state.method == "ridge_linear":
        pred = np.full(len(frame), state.intercept, dtype="float64")
        for category in config.categories:
            pred += float(state.coefficients.get(category, 0.0)) * frame[category].fillna(0.0).to_numpy(dtype="float64")
        return np.clip(pred / max(state.score_scale, 1e-12) * 100.0, -100.0, 100.0)
    if state.method == "isotonic_calibrated":
        score = frame["baseline_score"].to_numpy(dtype="float64")
        if state.metadata.get("fallback") == "quantile":
            bins = np.asarray(state.metadata.get("bins") or [], dtype="float64")
            means = {int(k): float(v) for k, v in (state.metadata.get("bucket_means") or {}).items()}
            bucket = np.digitize(score, bins[1:-1], right=True) if len(bins) >= 3 else np.zeros(len(score), dtype=int)
            pred = np.asarray([means.get(int(b), 0.0) for b in bucket], dtype="float64")
        else:
            x = np.asarray(state.metadata.get("x_thresholds") or [], dtype="float64")
            y = np.asarray(state.metadata.get("y_thresholds") or [], dtype="float64")
            pred = np.interp(score, x, y) if len(x) and len(y) else np.zeros(len(score), dtype="float64")
        return np.clip(pred / max(state.score_scale, 1e-12) * 100.0, -100.0, 100.0)
    if state.method in {"topsis_category", "ahp_topsis_prior"}:
        return _weighted_oriented_score(frame, state.category_weights, state.category_signs, config.categories)
    if state.method == "tree_regressor":
        model = state.metadata.get("model")
        if model is None:
            return frame["baseline_score"].to_numpy(dtype="float64")
        x = frame[list(config.categories)].astype(float).fillna(0.0).to_numpy()
        pred = model.predict(x)
        return np.clip(pred / max(state.score_scale, 1e-12) * 100.0, -100.0, 100.0)
    return frame["baseline_score"].to_numpy(dtype="float64")


def _predict_topsis_action_labels(state: PolicyState, frame: pd.DataFrame, config: BakeoffConfig) -> np.ndarray:
    stats = state.metadata.get("bucket_action_stats") or {}
    out: list[str] = []
    for raw_score in frame["baseline_score"].to_numpy(dtype="float64"):
        bucket = str(label_scores([raw_score], FIXED_THRESHOLDS)[0])
        rows = []
        for action in ACTION_LABELS:
            direction = action_direction([action])[0]
            if direction == 0:
                alignment = max(0.0, 1.0 - abs(raw_score) / 100.0)
            elif "strong" in action:
                alignment = max(0.0, direction * raw_score / 100.0) * max(0.0, (abs(raw_score) - 30.0) / 70.0)
            else:
                alignment = max(0.0, direction * raw_score / 100.0)
            payload = ((stats.get(bucket) or {}).get(action) or {})
            rows.append(
                [
                    alignment,
                    float(payload.get("mean_utility", 0.0)),
                    float(payload.get("hit_rate", 0.0)),
                    0.0 if direction == 0 else float(config.cost_bps) / 10000.0,
                ]
            )
        closeness = topsis_closeness(rows, weights=(0.45, 0.35, 0.15, 0.05), benefit=(True, True, True, False))
        out.append(ACTION_LABELS[int(np.argmax(closeness))])
    return np.asarray(out, dtype=object)


def _score_from_labels(labels: Sequence[str] | np.ndarray) -> np.ndarray:
    values = {
        "strong_sell": -75.0,
        "sell": -30.0,
        "hold": 0.0,
        "buy": 30.0,
        "strong_buy": 75.0,
    }
    return np.asarray([values.get(str(label), 0.0) for label in labels], dtype="float64")


def _prediction_scale(pred: Sequence[float] | np.ndarray) -> float:
    arr = np.asarray(pred, dtype="float64")
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return 1.0
    scale = float(np.nanquantile(np.abs(arr), 0.95))
    return scale if scale > 1e-12 else 1.0


def _safe_spearman(a: Sequence[float], b: Sequence[float]) -> float:
    df = pd.DataFrame({"a": a, "b": b}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(df) < 5:
        return float("nan")
    return _spearman_corr(df["a"], df["b"])


def _ic_and_tstat(score: Sequence[float], fwd: Sequence[float], h: int) -> tuple[float, float]:
    df = pd.DataFrame({"s": score, "r": fwd}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(df) < 20:
        return float("nan"), float("nan")
    ic = _spearman_corr(df["s"], df["r"])
    if not math.isfinite(ic):
        return float("nan"), float("nan")
    ranks_s = df["s"].rank()
    ranks_r = df["r"].rank()
    zs = (ranks_s - ranks_s.mean()) / (ranks_s.std() or 1.0)
    zr = (ranks_r - ranks_r.mean()) / (ranks_r.std() or 1.0)
    prod = (zs * zr).to_numpy(dtype="float64")
    bandwidth = max(int(h), max(1, int(4 * (len(df) / 100) ** (2 / 9))))
    nw_var = _newey_west_var(prod, bandwidth=bandwidth)
    if nw_var is None or not math.isfinite(nw_var) or nw_var <= 0:
        return float(ic), float("nan")
    return float(ic), float(ic / math.sqrt(nw_var))


def _extreme_spread(score: pd.Series, fwd: pd.Series) -> float:
    df = pd.concat([score.rename("s"), fwd.rename("r")], axis=1).dropna()
    if len(df) < 20:
        return 0.0
    high = df[df["s"] >= df["s"].quantile(0.8)]["r"]
    low = df[df["s"] <= df["s"].quantile(0.2)]["r"]
    if len(high) < 5 or len(low) < 5:
        return 0.0
    return float(high.mean() - low.mean())


def _half_stability(score: pd.Series, fwd: pd.Series) -> float:
    df = pd.concat([score.rename("s"), fwd.rename("r")], axis=1).dropna()
    if len(df) < 40:
        return 0.0
    mid = len(df) // 2
    ic1 = _safe_spearman(df["s"].iloc[:mid], df["r"].iloc[:mid])
    ic2 = _safe_spearman(df["s"].iloc[mid:], df["r"].iloc[mid:])
    if not math.isfinite(ic1) or not math.isfinite(ic2):
        return 0.0
    return 1.0 if ic1 * ic2 > 0 else 0.0


def _weighted_oriented_score(
    frame: pd.DataFrame,
    weights: dict[str, float],
    signs: dict[str, float],
    categories: Sequence[str],
) -> np.ndarray:
    out = np.zeros(len(frame), dtype="float64")
    total = 0.0
    for category in categories:
        w = float(weights.get(category, 0.0))
        sign = float(signs.get(category, 1.0))
        out += w * sign * frame[category].fillna(0.0).to_numpy(dtype="float64")
        total += w
    if total <= 1e-12:
        return frame[list(categories)].mean(axis=1).to_numpy(dtype="float64")
    return np.clip(out / total, -100.0, 100.0)


def _rankings(metrics: pd.DataFrame) -> pd.DataFrame:
    if metrics.empty:
        return pd.DataFrame()
    return (
        metrics.groupby("method", as_index=False)
        .agg(
            mean_utility=("utility_mean", "mean"),
            median_utility=("utility_mean", "median"),
            mean_ic=("ic", "mean"),
            mean_hit_rate=("hit_rate", "mean"),
            mean_coverage=("coverage", "mean"),
            folds=("fold", "nunique"),
        )
        .sort_values(["mean_utility", "mean_ic"], ascending=[False, False])
        .reset_index(drop=True)
    )


def _config_to_json(config: BakeoffConfig) -> dict[str, Any]:
    return {
        "source": config.source,
        "horizon": config.horizon,
        "symbols": list(config.symbols) if config.symbols else None,
        "categories": list(config.categories),
        "fwd_horizons": list(config.fwd_horizons) if config.fwd_horizons else None,
        "n_splits": config.n_splits,
        "min_train_dates": config.min_train_dates,
        "min_test_dates": config.min_test_dates,
        "min_action_obs": config.min_action_obs,
        "cost_bps": config.cost_bps,
        "use_oos_only": config.use_oos_only,
        "include_optional_ml": config.include_optional_ml,
        "random_seed": config.random_seed,
    }
