from __future__ import annotations

import pandas as pd
import pytest

from core.quant_core.historical_portfolio import (
    ExecutionCapabilities,
    HistoricalOpportunity,
    PortfolioBacktestConfig,
    SelectionObservation,
    benchmark_curves,
    combine_sleeves_equal_risk,
    half_kelly_from_selection_sample,
    nested_capacity_frontier,
    portfolio_statistics,
    reconstruct_point_in_time,
    simulate_sleeve,
    snapshot_audit,
    stationary_bootstrap_drawdown_risk,
    UnsupportedCapabilityError,
    V5_DECISION_EDGE_COST_BPS,
    validate_execution_capabilities,
)
from core.quant_core.signal_engine.modes import TECHNICAL_SIGNAL_MODE_NAMES
from services.api.app.config import settings


def test_v5_decision_cost_and_execution_capability_guards() -> None:
    assert float(settings.EDGE_COST_BPS_PER_SIDE) == V5_DECISION_EDGE_COST_BPS
    with pytest.raises(UnsupportedCapabilityError, match="short execution not implemented"):
        validate_execution_capabilities(ExecutionCapabilities(allow_short=True))


def test_portfolio_statistics_rejects_nonfinite_equity_instead_of_forward_filling() -> None:
    curve = [
        {"date": "2024-01-01", "equity": 100_000.0, "exposure": 0.0},
        {"date": "2024-01-02", "equity": float("nan"), "exposure": 0.0},
        {"date": "2024-01-03", "equity": 101_000.0, "exposure": 0.0},
    ]

    stats = portfolio_statistics(
        curve, [], [], PortfolioBacktestConfig(bootstrap_samples=100), 0.0, 0.0,
    )

    assert stats == {"available": False, "reason": "invalid_equity_curve"}


def _prices(periods: int = 340, *, volume: float = 1_000_000.0) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=periods)
    close = pd.Series(range(100, 100 + periods), index=idx, dtype=float)
    return pd.DataFrame({"Open": close - 0.5, "Close": close, "Volume": volume}, index=idx)


def _observations() -> tuple[SelectionObservation, ...]:
    return (
        SelectionObservation("2024-01-10", 0.10),
        SelectionObservation("2024-01-20", -0.04),
        SelectionObservation("2024-01-30", 0.08),
        SelectionObservation("2024-02-10", 0.05),
    )


def _opportunity(decision: str, *, symbol: str = "AAA", horizon: str = "weekly", exit_lag: int = 5) -> HistoricalOpportunity:
    return HistoricalOpportunity(
        decision_date=decision, symbol=symbol, horizon=horizon,
        variant="expanded_ta_simple", direction="long", bucket="strong_buy", rank=(1.0,),
        training_end="2024-02-01", selection_sample_end="2024-02-10",
        proof_sample_end="2024-02-10", entry_lag_bars=1, exit_lag_bars=exit_lag,
        selection_observations=_observations(),
        provenance={"selector": "test", "return_calc_method": "open_to_exit_ladder"},
    )


def test_future_row_cannot_change_earlier_selection_and_all_modes_are_evaluated() -> None:
    base = _prices(80)
    decision = base.index[60]
    calls: list[tuple[str, str, int]] = []

    def selector(as_of, horizon, variant, sliced):
        calls.append((horizon, variant, len(sliced["AAA"])))
        score = float(sliced["AAA"]["Close"].iloc[-1])
        return [HistoricalOpportunity(
            decision_date=as_of.date().isoformat(), symbol="AAA", horizon=horizon,
            variant=variant, direction="long", rank=(score, -TECHNICAL_SIGNAL_MODE_NAMES.index(variant)),
            training_end=sliced["AAA"].index[-2].date().isoformat(),
            selection_sample_end=sliced["AAA"].index[-2].date().isoformat(),
            selection_observations=_observations(),
        )]

    before = reconstruct_point_in_time(market_data={"AAA": base}, decision_dates=[decision], selector=selector)
    future = base.copy()
    future.loc[future.index[-1] + pd.offsets.BDay(), ["Open", "Close", "Volume"]] = [1e9, 1e9, 1.0]
    after = reconstruct_point_in_time(market_data={"AAA": future}, decision_dates=[decision], selector=selector)
    assert [(r.symbol, r.variant, r.rank) for r in before] == [(r.symbol, r.variant, r.rank) for r in after]
    assert {variant for _, variant, _ in calls} == set(TECHNICAL_SIGNAL_MODE_NAMES)
    assert all(length == 61 for _, _, length in calls)


def test_current_selected_configuration_cannot_be_substituted() -> None:
    with pytest.raises(ValueError, match="all eight"):
        reconstruct_point_in_time(
            market_data={"AAA": _prices(50)}, decision_dates=["2024-02-01"],
            selector=lambda *_: [], variants=["expanded_ta_simple"],
        )


def test_training_selection_and_kelly_samples_must_precede_decision() -> None:
    bad = HistoricalOpportunity(
        decision_date="2024-03-01", symbol="AAA", horizon="weekly",
        variant="expanded_ta_simple", direction="long", training_end="2024-03-01",
    )
    with pytest.raises(ValueError, match="training_end"):
        bad.validate_point_in_time()
    assert half_kelly_from_selection_sample(
        [SelectionObservation("2024-03-02", 0.50)], decision_date="2024-03-01",
    ) is None


def test_j_plus_timing_one_lot_cash_costs_and_capacity_reconcile() -> None:
    prices = _prices()
    decision1 = prices.index[60].date().isoformat()
    decision2 = prices.index[62].date().isoformat()  # overlaps first lot
    result = simulate_sleeve(
        [_opportunity(decision1), _opportunity(decision2)], {"AAA": prices},
        PortfolioBacktestConfig(capacity_fraction=0.01), horizon="weekly",
    )
    assert len(result["trades"]) == 1
    assert any(row["reason"] == "one_live_lot" for row in result["rejected_trades"])
    trade = result["trades"][0]
    loc = prices.index.get_loc(pd.Timestamp(decision1))
    assert trade["entry_date"] == prices.index[loc + 1].date().isoformat()
    assert trade["exit_date"] == prices.index[loc + 5].date().isoformat()
    end = result["equity_curve"][-1]
    assert end["open_lots"] == 0
    expected = 100_000.0 + trade["realized_pnl"]
    assert end["equity"] == pytest.approx(expected)
    assert result["statistics"]["cost_impact_mad"] == pytest.approx(trade["entry_cost"] + trade["exit_cost"])


def test_no_synthetic_starter_and_capacity_reject_or_constrain() -> None:
    prices = _prices(volume=100.0)
    decision = prices.index[60].date().isoformat()
    insufficient = _opportunity(decision)
    insufficient = HistoricalOpportunity(**{
        **insufficient.__dict__, "selection_observations": _observations()[:2]
    })
    no_start = simulate_sleeve(
        [insufficient], {"AAA": prices}, PortfolioBacktestConfig(capacity_fraction=0.01), horizon="weekly",
    )
    assert not no_start["trades"]
    assert no_start["rejected_trades"][0]["reason"] == "insufficient_point_in_time_kelly_history"

    rejected = simulate_sleeve(
        [_opportunity(decision)], {"AAA": prices},
        PortfolioBacktestConfig(capacity_fraction=0.01, allow_partial_fills=False), horizon="weekly",
    )
    assert rejected["rejected_trades"][0]["reason"] == "capacity_rejected"
    constrained = simulate_sleeve(
        [_opportunity(decision)], {"AAA": prices},
        PortfolioBacktestConfig(capacity_fraction=0.01, allow_partial_fills=True), horizon="weekly",
    )
    assert constrained["trades"][0]["capacity_constrained"] is True
    assert constrained["trades"][0]["entry_notional"] <= constrained["trades"][0]["adv20_mad"] * 0.01


def test_exposure_matched_masi_uses_lagged_historical_exposure() -> None:
    curve = [
        {"date": "2024-01-01", "equity": 100.0, "exposure": 0.0},
        {"date": "2024-01-02", "equity": 100.0, "exposure": 1.0},
        {"date": "2024-01-03", "equity": 100.0, "exposure": 0.0},
    ]
    masi = pd.Series([100.0, 110.0, 121.0], index=pd.to_datetime([r["date"] for r in curve]))
    out = benchmark_curves(curve, masi)
    assert out["full_investment_masi"]["total_return"] == pytest.approx(0.21)
    # Day-2 return is missed (prior exposure 0), day-3 return is captured (prior exposure 1).
    assert out["exposure_matched_masi"]["total_return"] == pytest.approx(0.10)


def test_masi_benchmarks_use_only_strategy_dates() -> None:
    curve = [
        {"date": "2024-01-02", "equity": 100.0, "exposure": 0.5},
        {"date": "2024-01-03", "equity": 101.0, "exposure": 0.5},
    ]
    masi = pd.Series(
        [90.0, 100.0, 110.0, 120.0],
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
    )

    out = benchmark_curves(curve, masi)

    assert [point["date"] for point in out["full_investment_masi"]["curve"]] == [
        "2024-01-02", "2024-01-03",
    ]
    assert [point["date"] for point in out["exposure_matched_masi"]["curve"]] == [
        "2024-01-02", "2024-01-03",
    ]


def test_combined_sleeve_preserves_strategy_exposure() -> None:
    sleeves = {
        "weekly": {"equity_curve": [
            {"date": "2024-01-01", "equity": 100.0, "exposure": 0.0},
            {"date": "2024-01-02", "equity": 101.0, "exposure": 0.5},
        ]},
        "monthly": {"equity_curve": [
            {"date": "2024-01-01", "equity": 100.0, "exposure": 0.0},
            {"date": "2024-01-02", "equity": 100.0, "exposure": 0.0},
        ]},
    }
    combined = combine_sleeves_equal_risk(sleeves, 100.0)
    assert combined["equity_curve"][-1]["exposure"] == pytest.approx(0.25)


def test_bootstrap_is_deterministic_and_snapshot_audit_uses_existing_dates_only() -> None:
    returns = [0.001, -0.002, 0.003, -0.001] * 80
    left = stationary_bootstrap_drawdown_risk(returns, seed=42, samples=50)
    right = stationary_bootstrap_drawdown_risk(returns, seed=42, samples=50)
    assert left == right
    audit = snapshot_audit(
        [_opportunity("2024-03-01")],
        [{"as_of_date": "2024-03-01", "horizon": "weekly", "payload_jsonb": {
            "stocks": [{"symbol": "AAA", "best_signal": {
                "variant": "expanded_ta_simple", "direction": "long", "bucket": "strong_buy",
                "entry_lag_bars": 1, "entry_price_kind": "open", "exit_lag_bars": 5,
                "exit_price_kind": "open", "return_calc_method": "open_to_exit_ladder",
            }}]
        }}],
    )
    assert audit["snapshot_dates"] == ["2024-03-01"]
    assert audit["statistically_equivalent_to_reconstruction"] is False
    assert audit["discrepancy_count"] == 0


def test_nested_capacity_frontier_is_deterministic_and_training_ends_before_test() -> None:
    idx = pd.bdate_range("2022-01-03", periods=330)
    candidates = {
        0.01: pd.Series([0.0005, -0.0002, 0.0004] * 110, index=idx),
        0.025: pd.Series([0.0008, -0.0007, 0.0005] * 110, index=idx),
    }
    left = nested_capacity_frontier(candidates, risk_limit=0.5, seed=9)
    right = nested_capacity_frontier(candidates, risk_limit=0.5, seed=9)
    assert left == right
    assert all(fold["train_end"] < fold["test_start"] for fold in left["folds"] if fold["test_start"])
