from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pandas as pd

from core.quant_core.historical_portfolio import V5_DECISION_EDGE_COST_BPS
from core.quant_core.signal_ranking import AsOfInputs, build_asof_decision, rank_and_actionability


def test_golden_rank_actionability_contract() -> None:
    fixture = json.loads((Path(__file__).parent / "fixtures" / "pit_v5_ranking_golden.json").read_text())
    for case in fixture:
        rank, reasons = rank_and_actionability(case["edge"])
        actual_rank = list(rank) if rank is not None else None
        assert actual_rank == case["rank"]
        assert reasons == case["reasons"]


@dataclass
class _Gates:
    n: bool = True


class _Metrics:
    edge_score = None
    edge_score_components = {}
    expected_return_net = 0.02
    action_expected_return_net = 0.02
    expected_return_net_ci_lower = 0.01
    action_expected_return_net_ci_lower = 0.01
    hit_ci_lower = 0.55
    proven_edge_net = False
    gates = _Gates()
    mc_luck_pvalue_net_adj = 0.01
    label_shuffle_pvalue_net_adj = 0.01
    freshness_status = "pass"
    selection_n = 20
    proof_n = 30
    n = 30
    exit_lag_bars = 5
    entry_lag_bars = 1
    entry_price_kind = "open"
    exit_price_kind = "open"
    return_calc_method = "open_to_exit_ladder"
    methodology_version = "edge-v2"
    selection_window_end = pd.Timestamp("2024-01-25")
    proof_window_end = pd.Timestamp("2024-01-30")


def _inputs(*, future: bool = False) -> AsOfInputs:
    dates = pd.date_range("2023-01-02", "2024-02-05" if future else "2024-01-31", freq="B")
    values = pd.Series(80.0, index=dates)
    prices = pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 10000.0},
        index=dates,
    )
    return AsOfInputs(
        symbol="IAM", horizon="weekly", variant="expanded_ta_simple",
        as_of=pd.Timestamp("2024-01-31"),
        category_series={key: values for key in ("tendance", "momentum", "oscillation", "volume")},
        prices=prices,
        oos=tuple(pd.Timestamp(value) for value in dates),
        decision_edge_cost_bps=V5_DECISION_EDGE_COST_BPS,
        mc_iterations=100,
        mc_seed=5107,
    )


def test_builder_is_pure_deterministic_and_filters_future_inputs(monkeypatch) -> None:
    captured = []

    def fake_edge(**kwargs):
        captured.append(kwargs)
        assert kwargs["score_series"].index.max() < pd.Timestamp("2024-01-31")
        assert kwargs["prices"].index.max() < pd.Timestamp("2024-01-31")
        assert kwargs["oos_sample"].dates.max() < pd.Timestamp("2024-01-31")
        return _Metrics()

    monkeypatch.setattr("core.quant_core.signal_ranking.build_edge_payload", fake_edge)
    first = build_asof_decision(_inputs())
    second = build_asof_decision(_inputs(future=True))
    assert first == second
    assert first.status == "evaluated"
    assert first.actionable is True
    assert first.rank == (1, 0.01, 0.01, 0.02)
    assert first.opportunity is not None
    assert first.selection_observations
    assert all(pd.Timestamp(item.exit_date) < pd.Timestamp("2024-01-31") for item in first.selection_observations)
    assert len(captured) == 2


def test_builder_rejects_decision_cost_drift() -> None:
    inputs = _inputs()
    bad = AsOfInputs(**{**inputs.__dict__, "decision_edge_cost_bps": 34.0})
    try:
        build_asof_decision(bad)
    except ValueError as exc:
        assert "version bump" in str(exc)
    else:
        raise AssertionError("cost drift must fail")
