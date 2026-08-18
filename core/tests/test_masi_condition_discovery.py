from __future__ import annotations

import pandas as pd
import pytest

from core.quant_core.research.masi_condition_discovery import (
    DiscoveryConfig,
    ThresholdRule,
    _bh_qvalues,
    apply_policy,
    purged_walk_forward_folds,
    run_horizon_study,
    select_policy_winners,
)
from scripts.study_pit_edge_conditions import _benchmark_return, _market_features


def test_market_features_are_truncated_at_decision_date() -> None:
    index = pd.bdate_range("2024-01-01", periods=230)
    frame = pd.DataFrame({
        "Open": range(100, 330), "Close": range(100, 330), "Volume": 1_000.0,
    }, index=index)
    decision = index[210]
    before = _market_features(frame, decision, "stock")
    changed = frame.copy()
    changed.loc[index[211]:, "Close"] = 1_000_000.0
    after = _market_features(changed, decision, "stock")
    assert before == after
    assert before["stock_return_20"] == pytest.approx(310 / 290 - 1)


def test_benchmark_return_matches_price_kind_and_dates() -> None:
    frame = pd.DataFrame(
        {"Open": [100.0, 110.0], "Close": [105.0, 120.0]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )
    value = _benchmark_return(
        frame, entry_date="2024-01-02", exit_date="2024-01-03",
        entry_kind="open", exit_kind="close",
    )
    assert value == pytest.approx(0.20)


def test_purged_fold_excludes_training_labels_crossing_test_start() -> None:
    dates = pd.bdate_range("2024-01-01", periods=8)
    frame = pd.DataFrame({
        "decision_date": dates,
        "exit_date": [*dates[1:5], dates[6], dates[6], dates[7], dates[7]],
    })
    config = DiscoveryConfig(min_train_dates=5, outer_test_dates=2, min_inner_trades=1, min_outer_trades=1)
    fold = purged_walk_forward_folds(frame, config)[0]
    assert pd.to_datetime(fold["train"]["exit_date"]).max() < pd.Timestamp(fold["test_start"])
    assert dates[4] not in set(pd.to_datetime(fold["train"]["decision_date"]))


def test_policy_uses_and_semantics_and_highest_ranked_variant() -> None:
    frame = pd.DataFrame([
        {"decision_date": "2024-01-05", "symbol": "AAA", "horizon": "weekly", "variant": "low", "x": 2, "y": 2, "rank_edge": 10},
        {"decision_date": "2024-01-05", "symbol": "AAA", "horizon": "weekly", "variant": "high", "x": 3, "y": 3, "rank_edge": 20},
        {"decision_date": "2024-01-05", "symbol": "BBB", "horizon": "weekly", "variant": "fails-y", "x": 3, "y": 0, "rank_edge": 99},
    ])
    rules = (ThresholdRule("x", ">=", 2), ThresholdRule("y", ">=", 2))
    assert apply_policy(frame, rules).tolist() == [True, True, False]
    selected = select_policy_winners(frame, rules)
    assert selected[["symbol", "variant"]].to_dict("records") == [{"symbol": "AAA", "variant": "high"}]


def test_bh_correction_accounts_for_all_searched_rules() -> None:
    qvalues = _bh_qvalues([0.001, 0.02, 0.04, 0.8])
    assert qvalues[0] == pytest.approx(0.004)
    assert qvalues[1] >= 0.02
    assert qvalues == sorted(qvalues)


def _synthetic_study_frame() -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2023-01-02", periods=36)
    symbols = ("AAA", "BBB", "CCC")
    for date_index, date in enumerate(dates):
        for symbol_index, symbol in enumerate(symbols):
            for edge, suffix, outcome in (
                (75.0 + date_index % 7 + symbol_index * 0.1, "good", 0.03),
                (10.0 + date_index % 7 + symbol_index * 0.1, "bad", -0.02),
            ):
                rows.append({
                    "decision_date": date, "entry_date": date + pd.Timedelta(days=1),
                    "exit_date": date + pd.Timedelta(days=2), "symbol": symbol,
                    "horizon": "weekly", "variant": suffix,
                    "edge_score": edge, "rank_proven": 1.0, "rank_edge": edge,
                    "rank_ci": edge, "rank_expected": edge,
                    "realized_net_return": outcome + symbol_index * 0.0001,
                    "masi_alpha": outcome - 0.005 + symbol_index * 0.0001,
                })
    return pd.DataFrame(rows)


def test_study_accepts_only_stable_positive_net_and_alpha_policy() -> None:
    config = DiscoveryConfig(
        min_train_dates=12, outer_test_dates=6, min_inner_trades=3, min_outer_trades=15,
        bootstrap_samples=100, bootstrap_block_dates=2, multiple_testing_q=1.0,
    )
    result = run_horizon_study(
        _synthetic_study_frame(), horizon="weekly", features=("edge_score",), config=config,
    )
    assert result["status"] == "accepted"
    assert result["outer_trade_count"] >= 15
    assert result["outer_mean_net_return_ci95"][0] > 0
    assert result["outer_mean_masi_alpha_ci95"][0] > 0
    assert len(result["final_policy"]["rules"]) <= 2


def test_study_rejects_policy_that_has_alpha_but_loses_money() -> None:
    frame = _synthetic_study_frame()
    frame.loc[frame["variant"] == "good", "realized_net_return"] = -0.01
    frame.loc[frame["variant"] == "good", "masi_alpha"] = 0.02
    config = DiscoveryConfig(
        min_train_dates=12, outer_test_dates=6, min_inner_trades=3, min_outer_trades=15,
        bootstrap_samples=100, bootstrap_block_dates=2, multiple_testing_q=1.0,
    )
    result = run_horizon_study(frame, horizon="weekly", features=("edge_score",), config=config)
    assert result["status"] == "rejected"
    assert result["outer_mean_net_return_ci95"][0] < 0


def test_more_than_two_rules_is_rejected() -> None:
    with pytest.raises(ValueError, match="one or two"):
        DiscoveryConfig(max_rules=3)
