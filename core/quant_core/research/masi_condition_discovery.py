from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ThresholdRule:
    feature: str
    operator: str
    threshold: float

    def __post_init__(self) -> None:
        if self.operator not in {">=", "<="}:
            raise ValueError("operator must be >= or <=")


@dataclass(frozen=True)
class DiscoveryConfig:
    min_train_dates: int = 52
    outer_test_dates: int = 13
    inner_validation_fraction: float = 0.25
    min_inner_trades: int = 8
    min_outer_trades: int = 15
    max_rules: int = 2
    top_atomic_rules: int = 20
    bootstrap_samples: int = 2000
    bootstrap_block_dates: int = 4
    seed: int = 5107
    multiple_testing_q: float = 0.10

    def __post_init__(self) -> None:
        if self.max_rules not in {1, 2}:
            raise ValueError("max_rules must be one or two")
        if self.min_outer_trades < 1 or self.min_inner_trades < 1:
            raise ValueError("trade-count floors must be positive")


DEFAULT_FEATURES = (
    "edge_score", "expected_return_net", "ci_lower_net", "hit_ci_lower", "proof_n",
    "mc_luck_pvalue_net_adj", "label_shuffle_pvalue_net_adj",
    "component_sample_n", "component_bootstrap_er", "component_wilson",
    "component_mc_luck", "component_label_shuffle", "component_freshness",
    "signal_strength", "stock_return_20", "stock_return_60", "stock_return_120",
    "stock_volatility_20", "stock_volatility_60", "stock_drawdown_60",
    "stock_ma_distance_50", "stock_ma_distance_200", "stock_adv20",
    "masi_return_20", "masi_return_60", "masi_return_120", "masi_volatility_20",
    "masi_volatility_60", "masi_drawdown_60", "masi_ma_distance_50",
    "masi_ma_distance_200",
)


def apply_policy(frame: pd.DataFrame, rules: Sequence[ThresholdRule]) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for rule in rules:
        values = pd.to_numeric(frame.get(rule.feature), errors="coerce")
        current = values >= rule.threshold if rule.operator == ">=" else values <= rule.threshold
        mask &= current.fillna(False)
    return mask


def select_policy_winners(frame: pd.DataFrame, rules: Sequence[ThresholdRule]) -> pd.DataFrame:
    selected = frame.loc[apply_policy(frame, rules)].copy()
    if selected.empty:
        return selected
    rank_columns = [name for name in ("rank_proven", "rank_edge", "rank_ci", "rank_expected") if name in selected]
    selected = selected.sort_values(
        ["decision_date", "symbol", "horizon", *rank_columns, "variant"],
        ascending=[True, True, True, *([False] * len(rank_columns)), True],
        kind="mergesort",
    )
    return selected.groupby(["decision_date", "symbol", "horizon"], as_index=False).first()


def purged_walk_forward_folds(frame: pd.DataFrame, config: DiscoveryConfig) -> list[dict[str, Any]]:
    dates = sorted(pd.to_datetime(frame["decision_date"]).dt.normalize().unique())
    folds: list[dict[str, Any]] = []
    for start in range(config.min_train_dates, len(dates), config.outer_test_dates):
        test_dates = dates[start:start + config.outer_test_dates]
        if not test_dates:
            break
        test_start = pd.Timestamp(test_dates[0])
        train = frame.loc[
            (pd.to_datetime(frame["decision_date"]) < test_start)
            & (pd.to_datetime(frame["exit_date"]) < test_start)
        ].copy()
        test = frame.loc[pd.to_datetime(frame["decision_date"]).isin(test_dates)].copy()
        if train.empty or test.empty:
            continue
        folds.append({
            "fold": len(folds), "train": train, "test": test,
            "train_end": pd.to_datetime(train["decision_date"]).max().date().isoformat(),
            "test_start": test_start.date().isoformat(),
            "test_end": pd.Timestamp(test_dates[-1]).date().isoformat(),
        })
    return folds


def _inner_split(frame: pd.DataFrame, config: DiscoveryConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = sorted(pd.to_datetime(frame["decision_date"]).dt.normalize().unique())
    validation_count = max(3, int(math.ceil(len(dates) * config.inner_validation_fraction)))
    if len(dates) <= validation_count + 2:
        return frame.iloc[0:0].copy(), frame.iloc[0:0].copy()
    validation_dates = dates[-validation_count:]
    validation_start = pd.Timestamp(validation_dates[0])
    training = frame.loc[
        (pd.to_datetime(frame["decision_date"]) < validation_start)
        & (pd.to_datetime(frame["exit_date"]) < validation_start)
    ].copy()
    validation = frame.loc[pd.to_datetime(frame["decision_date"]).isin(validation_dates)].copy()
    return training, validation


def _one_sided_cluster_pvalue(frame: pd.DataFrame, column: str) -> float:
    if frame.empty:
        return 1.0
    values = frame.groupby("decision_date")[column].mean().dropna().to_numpy(dtype=float)
    if len(values) < 2:
        return 1.0
    standard_error = float(np.std(values, ddof=1) / math.sqrt(len(values)))
    if standard_error <= 0:
        return 0.0 if float(np.mean(values)) > 0 else 1.0
    z_score = float(np.mean(values)) / standard_error
    return 0.5 * math.erfc(z_score / math.sqrt(2.0))


def _bh_qvalues(pvalues: Sequence[float]) -> list[float]:
    if not pvalues:
        return []
    order = np.argsort(np.asarray(pvalues, dtype=float))
    adjusted = np.ones(len(pvalues), dtype=float)
    running = 1.0
    for reverse_rank in range(len(order) - 1, -1, -1):
        idx = int(order[reverse_rank])
        rank = reverse_rank + 1
        running = min(running, float(pvalues[idx]) * len(order) / rank)
        adjusted[idx] = min(1.0, running)
    return adjusted.tolist()


def _rule_key(rules: Sequence[ThresholdRule]) -> tuple:
    return tuple((rule.feature, rule.operator, round(rule.threshold, 12)) for rule in rules)


def _atomic_rules(frame: pd.DataFrame, features: Iterable[str]) -> list[ThresholdRule]:
    rules: dict[tuple, ThresholdRule] = {}
    for feature in features:
        if feature not in frame:
            continue
        values = pd.to_numeric(frame[feature], errors="coerce").dropna()
        if values.nunique() < 4:
            continue
        for quantile in (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90):
            threshold = float(values.quantile(quantile))
            for operator in (">=", "<="):
                rule = ThresholdRule(feature, operator, threshold)
                rules[_rule_key((rule,))] = rule
    return list(rules.values())


def _policy_metrics(frame: pd.DataFrame, rules: Sequence[ThresholdRule]) -> dict[str, Any]:
    selected = select_policy_winners(frame, rules)
    return {
        "rules": [asdict(rule) for rule in rules],
        "selected": selected,
        "trade_count": len(selected),
        "mean_net_return": float(selected["realized_net_return"].mean()) if len(selected) else None,
        "mean_masi_alpha": float(selected["masi_alpha"].mean()) if len(selected) else None,
        "alpha_pvalue": _one_sided_cluster_pvalue(selected, "masi_alpha"),
    }


def discover_policy(
    frame: pd.DataFrame,
    *,
    features: Sequence[str] = DEFAULT_FEATURES,
    config: DiscoveryConfig,
) -> dict[str, Any] | None:
    training, validation = _inner_split(frame, config)
    if training.empty or validation.empty:
        return None
    atomics = _atomic_rules(training, features)
    atomic_metrics = []
    for rule in atomics:
        metrics = _policy_metrics(validation, (rule,))
        if metrics["trade_count"] >= config.min_inner_trades:
            atomic_metrics.append(metrics)
    atomic_metrics.sort(
        key=lambda item: (
            item["mean_masi_alpha"] if item["mean_masi_alpha"] is not None else -math.inf,
            item["mean_net_return"] if item["mean_net_return"] is not None else -math.inf,
        ),
        reverse=True,
    )
    candidates = list(atomic_metrics)
    if config.max_rules >= 2:
        top_rules = [ThresholdRule(**item["rules"][0]) for item in atomic_metrics[:config.top_atomic_rules]]
        for first_index, first in enumerate(top_rules):
            for second in top_rules[first_index + 1:]:
                if first.feature == second.feature:
                    continue
                metrics = _policy_metrics(validation, (first, second))
                if metrics["trade_count"] >= config.min_inner_trades:
                    candidates.append(metrics)
    if not candidates:
        return None
    qvalues = _bh_qvalues([float(item["alpha_pvalue"]) for item in candidates])
    for item, qvalue in zip(candidates, qvalues):
        item["alpha_qvalue"] = qvalue
        item["multiple_testing_passed"] = qvalue <= config.multiple_testing_q
    eligible = [
        item for item in candidates
        if item["mean_net_return"] is not None and item["mean_net_return"] > 0
        and item["mean_masi_alpha"] is not None and item["mean_masi_alpha"] > 0
    ]
    pool = eligible or candidates
    winner = max(pool, key=lambda item: (
        bool(item["multiple_testing_passed"]),
        float(item["mean_masi_alpha"] or -math.inf),
        float(item["mean_net_return"] or -math.inf),
        int(item["trade_count"]),
    ))
    ranked = sorted(candidates, key=lambda item: (
        bool(item["multiple_testing_passed"]),
        float(item["mean_masi_alpha"] or -math.inf),
        float(item["mean_net_return"] or -math.inf),
    ), reverse=True)
    alternatives = []
    for item in ranked:
        if _rule_key(tuple(ThresholdRule(**rule) for rule in item["rules"])) == _rule_key(
            tuple(ThresholdRule(**rule) for rule in winner["rules"])
        ):
            continue
        reasons = []
        if not item["multiple_testing_passed"]:
            reasons.append("multiple_testing")
        if item["mean_net_return"] is None or item["mean_net_return"] <= 0:
            reasons.append("nonpositive_net_return")
        if item["mean_masi_alpha"] is None or item["mean_masi_alpha"] <= 0:
            reasons.append("nonpositive_masi_alpha")
        alternatives.append({
            "rules": item["rules"], "trade_count": item["trade_count"],
            "mean_net_return": item["mean_net_return"], "mean_masi_alpha": item["mean_masi_alpha"],
            "alpha_qvalue": item["alpha_qvalue"], "rejection_reasons": reasons or ["lower_ranked"],
        })
        if len(alternatives) == 10:
            break
    return {
        **{key: value for key, value in winner.items() if key != "selected"},
        "searched_policy_count": len(candidates),
        "rejected_rule_examples": alternatives,
    }


def _block_bootstrap_ci(
    frame: pd.DataFrame, column: str, *, samples: int, block_dates: int, seed: int,
) -> list[float | None]:
    dates = sorted(frame["decision_date"].unique())
    if len(dates) < 2 or frame.empty:
        return [None, None]
    by_date = {date: frame.loc[frame["decision_date"] == date] for date in dates}
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(samples):
        sampled_dates = []
        while len(sampled_dates) < len(dates):
            start = int(rng.integers(0, len(dates)))
            sampled_dates.extend(dates[(start + offset) % len(dates)] for offset in range(block_dates))
        draw = pd.concat([by_date[date] for date in sampled_dates[:len(dates)]], ignore_index=True)
        means.append(float(draw[column].mean()))
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def _risk_diagnostics(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}
    ordered = frame.sort_values(["exit_date", "decision_date", "symbol"])
    curve = (1.0 + ordered["realized_net_return"].clip(lower=-0.999)).cumprod()
    drawdown = curve / curve.cummax() - 1.0
    wins = ordered.loc[ordered["realized_net_return"] > 0, "realized_net_return"]
    losses = ordered.loc[ordered["realized_net_return"] <= 0, "realized_net_return"].abs()
    start = pd.to_datetime(ordered["decision_date"]).min()
    end = pd.to_datetime(ordered["decision_date"]).max()
    years = max((end - start).days / 365.25, 1 / 12)
    concentrations = ordered["symbol"].value_counts(normalize=True)
    calendar = pd.date_range(start, pd.to_datetime(ordered["exit_date"]).max(), freq="D")
    active_days = sum(
        any(pd.Timestamp(row.decision_date) <= date <= pd.Timestamp(row.exit_date) for row in ordered.itertuples())
        for date in calendar
    )
    return {
        "hit_rate": float((ordered["realized_net_return"] > 0).mean()),
        "payoff_ratio": float(wins.mean() / losses.mean()) if len(wins) and len(losses) and losses.mean() > 0 else None,
        "trade_return_curve_max_drawdown": float(drawdown.min()),
        "trades_per_year": float(len(ordered) / years),
        "market_exposure_day_fraction": float(active_days / len(calendar)) if len(calendar) else None,
        "largest_symbol_trade_share": float(concentrations.iloc[0]) if len(concentrations) else None,
    }


def run_horizon_study(
    frame: pd.DataFrame,
    *,
    horizon: str,
    features: Sequence[str] = DEFAULT_FEATURES,
    config: DiscoveryConfig | None = None,
) -> dict[str, Any]:
    config = config or DiscoveryConfig()
    scoped = frame.loc[frame["horizon"] == horizon].copy()
    folds = purged_walk_forward_folds(scoped, config)
    outer_rows = []
    fold_payloads = []
    for fold in folds:
        discovered = discover_policy(fold["train"], features=features, config=config)
        if discovered is None:
            fold_payloads.append({key: fold[key] for key in ("fold", "train_end", "test_start", "test_end")} | {"status": "insufficient_training"})
            continue
        rules = tuple(ThresholdRule(**item) for item in discovered["rules"])
        selected = select_policy_winners(fold["test"], rules)
        selected["outer_fold"] = fold["fold"]
        outer_rows.append(selected)
        fold_payloads.append({
            **{key: fold[key] for key in ("fold", "train_end", "test_start", "test_end")},
            "status": "evaluated", "rules": discovered["rules"], "trade_count": len(selected),
            "mean_net_return": float(selected["realized_net_return"].mean()) if len(selected) else None,
            "mean_masi_alpha": float(selected["masi_alpha"].mean()) if len(selected) else None,
        })
    outer = pd.concat(outer_rows, ignore_index=True) if outer_rows else scoped.iloc[0:0].copy()
    final_policy = discover_policy(scoped, features=features, config=config)
    net_ci = _block_bootstrap_ci(
        outer, "realized_net_return", samples=config.bootstrap_samples,
        block_dates=config.bootstrap_block_dates, seed=config.seed,
    )
    alpha_ci = _block_bootstrap_ci(
        outer, "masi_alpha", samples=config.bootstrap_samples,
        block_dates=config.bootstrap_block_dates, seed=config.seed + 1,
    )
    evaluated_folds = [row for row in fold_payloads if row["status"] == "evaluated"]
    positive_fold_fraction = (
        sum(
            row["trade_count"] > 0 and float(row["mean_masi_alpha"] or 0) > 0
            for row in evaluated_folds
        ) / len(evaluated_folds)
        if evaluated_folds else 0.0
    )
    symbols = sorted(outer["symbol"].unique()) if len(outer) else []
    leave_one_out = {
        symbol: float(outer.loc[outer["symbol"] != symbol, "masi_alpha"].mean())
        for symbol in symbols if len(outer.loc[outer["symbol"] != symbol])
    }
    loo_positive_fraction = (
        sum(value > 0 for value in leave_one_out.values()) / len(leave_one_out)
        if leave_one_out else 0.0
    )
    accepted = bool(
        len(outer) >= config.min_outer_trades
        and net_ci[0] is not None and net_ci[0] > 0
        and alpha_ci[0] is not None and alpha_ci[0] > 0
        and positive_fold_fraction > 0.5
        and loo_positive_fraction >= 0.8
        and final_policy is not None
        and bool(final_policy.get("multiple_testing_passed"))
    )
    return {
        "horizon": horizon,
        "status": "accepted" if accepted else "rejected",
        "candidate_rows": len(scoped), "decision_dates": int(scoped["decision_date"].nunique()),
        "outer_trade_count": len(outer), "outer_fold_count": len(evaluated_folds),
        "outer_mean_net_return": float(outer["realized_net_return"].mean()) if len(outer) else None,
        "outer_mean_net_return_ci95": net_ci,
        "outer_mean_masi_alpha": float(outer["masi_alpha"].mean()) if len(outer) else None,
        "outer_mean_masi_alpha_ci95": alpha_ci,
        "positive_alpha_fold_fraction": positive_fold_fraction,
        "leave_one_symbol_out_positive_fraction": loo_positive_fraction,
        "leave_one_symbol_out_alpha": leave_one_out,
        "final_policy": final_policy,
        "folds": fold_payloads,
        "diagnostics": _risk_diagnostics(outer),
        "outer_rows": outer,
    }
