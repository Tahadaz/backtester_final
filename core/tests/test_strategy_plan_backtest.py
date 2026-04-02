from __future__ import annotations

import json

from fastapi.encoders import jsonable_encoder
import pandas as pd

from core.quant_core.strategy_plan.backtest import (
    _build_cost_model,
    _bucket_target_fraction,
    _simulate_stock,
    run_strategy_plan_backtest,
)


def _sample_bars() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=8, freq="D")
    return pd.DataFrame(
        {
            "Open": [100, 101, 102, 103, 104, 105, 106, 107],
            "High": [101, 102, 103, 104, 105, 106, 107, 108],
            "Low": [99, 100, 101, 102, 103, 104, 105, 106],
            "Close": [100.5, 101.5, 102.5, 103.5, 104.5, 105.5, 106.5, 107.5],
            "Volume": [100_000, 100_000, 101_000, 102_000, 103_000, 104_000, 105_000, 106_000],
        },
        index=idx,
    )


BET_SIZING = {
    "starter_threshold": 20,
    "starter_target_pct": 25,
    "medium_threshold": 40,
    "medium_target_pct": 50,
    "large_threshold": 60,
    "large_target_pct": 75,
    "max_threshold": 80,
    "max_target_pct": 100,
    "reduce_to_large_below": 70,
    "reduce_to_medium_below": 50,
    "reduce_to_starter_below": 30,
    "exit_below": 15,
}

EXPOSURE_LADDER = [
    {"score_low": 0.0, "score_high": 29.9999, "target_exposure_pct": 0},
    {"score_low": 30.0, "score_high": 49.9999, "target_exposure_pct": 25},
    {"score_low": 50.0, "score_high": 69.9999, "target_exposure_pct": 50},
    {"score_low": 70.0, "score_high": 84.9999, "target_exposure_pct": 75},
    {"score_low": 85.0, "score_high": 100.0, "target_exposure_pct": 100},
]


def test_bucket_target_fraction_uses_exposure_ladder() -> None:
    assert _bucket_target_fraction(19, side_policy="long_only", exposure_ladder=EXPOSURE_LADDER) == 0.0
    assert _bucket_target_fraction(30, side_policy="long_only", exposure_ladder=EXPOSURE_LADDER) == 0.25
    assert _bucket_target_fraction(69, side_policy="long_only", exposure_ladder=EXPOSURE_LADDER) == 0.5
    assert _bucket_target_fraction(85, side_policy="long_only", exposure_ladder=EXPOSURE_LADDER) == 1.0
    assert _bucket_target_fraction(-61, side_policy="long_only", exposure_ladder=EXPOSURE_LADDER) == 0.0
    assert _bucket_target_fraction(-61, side_policy="long_short", exposure_ladder=EXPOSURE_LADDER) == -0.5


def test_simulate_stock_exposes_signal_score_and_ledger() -> None:
    bars = _sample_bars()
    scores = pd.Series([85, 82, 79, 75, 60, 45, 20, 10], index=bars.index, dtype="float64")

    sim = _simulate_stock(
        symbol="AAA",
        bars=bars,
        score_series=scores,
        allocated_capital=100_000,
        side_policy="long_only",
        exposure_ladder=EXPOSURE_LADDER,
        risk={
            "max_holding_bars": 30,
            "stop_atr_multiplier": 1.5,
            "stop_buffer_pct": 0.005,
            "take_profit_rr": 1.5,
            "time_stop_enabled": True,
            "trailing_stop_enabled": False,
        },
        cost_model=_build_cost_model({}),
        cooldown_bars=0,
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
    )

    assert not sim.equity.empty
    assert sim.per_fill_ledger
    assert "signal_score" in sim.per_fill_ledger[0]


def test_simulate_stock_does_not_rebalance_inside_same_bucket() -> None:
    idx = pd.date_range("2026-01-01", periods=7, freq="D")
    bars = pd.DataFrame(
        {
            "Open": [100, 100, 110, 120, 130, 140, 150],
            "High": [101, 101, 111, 121, 131, 141, 151],
            "Low": [99, 99, 109, 119, 129, 139, 149],
            "Close": [100, 100, 110, 120, 130, 140, 150],
            "Volume": [100_000] * 7,
        },
        index=idx,
    )
    scores = pd.Series([71, 72, 73, 74, 75, 76, 77], index=idx, dtype="float64")

    sim = _simulate_stock(
        symbol="AAA",
        bars=bars,
        score_series=scores,
        allocated_capital=100_000,
        side_policy="long_only",
        exposure_ladder=EXPOSURE_LADDER,
        risk={
            "max_holding_bars": 999,
            "stop_atr_multiplier": 1000,
            "stop_buffer_pct": 0.0,
            "take_profit_rr": 1000,
            "time_stop_enabled": False,
            "trailing_stop_enabled": False,
        },
        cost_model=_build_cost_model({}),
        cooldown_bars=0,
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
    )

    assert len(sim.per_fill_ledger) == 1
    assert sim.per_fill_ledger[0]["reason"] == "signal_entry"


def test_run_strategy_plan_backtest_returns_general_and_stock_sections(monkeypatch) -> None:
    bars_by_symbol = {"AAA": _sample_bars(), "BBB": _sample_bars()}

    def fake_scores(**kwargs):
        ohlcv = kwargs["ohlcv"]
        return pd.Series([80.0] * len(ohlcv), index=ohlcv.index, dtype="float64")

    monkeypatch.setattr(
        "core.quant_core.strategy_plan.backtest._compute_consensus_scores",
        fake_scores,
    )

    result = run_strategy_plan_backtest(
        strategy_id="strategy-1",
        strategy_name="Desk Test",
        side_policy="long_only",
        horizon="medium",
        timeframe="1D",
        config_json={
            "capital": {"total_capital_mad": 200_000},
            "universe": {"basket": ["AAA", "BBB"]},
            "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            "signal": {
                "enabled_families": ["sma", "rsi"],
            },
            "bet_sizing": BET_SIZING,
            "risk": {
                "max_holding_bars": 30,
                "stop_atr_multiplier": 1.5,
                "stop_buffer_pct": 0.005,
                "take_profit_rr": 1.5,
                "time_stop_enabled": True,
                "trailing_stop_enabled": False,
            },
        },
        bars_by_symbol=bars_by_symbol,
        start_date="2024-01-01",
        end_date="2024-01-08",
        cost_model_raw={"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0.0, "slippage_bps": 0.0, "tva_rate": 0.1},
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0.0, "adv_window": 20},
        cooldown_bars=0,
    )

    assert "general_results" in result
    assert "stocks" in result
    assert len(result["stocks"]) == 2
    assert "cumreturn_vs_benchmark" in result["general_results"]["plots"]
    assert result["stocks"][0]["trade_ledger"]
    assert result["general_results"]["calibration"]["status"] in {"fallback", "provisional", "ok"}
    payload = jsonable_encoder(result)
    encoded = json.dumps(payload)
    assert encoded
    assert isinstance(result["general_results"]["plots"]["cumreturn_vs_benchmark"]["data"][0]["x"], list)
    assert isinstance(result["stocks"][0]["price_chart"]["data"][0]["x"], list)
    assert result["strategy"]["signal"]["enabled_families"] == ["sma", "rsi"]
    assert result["strategy"]["bet_sizing"]["mode"] == "auto_calibrated"
    assert result["strategy"]["bet_sizing"]["active_ladder"]
    assert "logic" not in result["strategy"]


def test_run_strategy_plan_backtest_accepts_legacy_logic_config(monkeypatch) -> None:
    bars = _sample_bars()
    bars_by_symbol = {"AAA": bars}

    def fake_scores(**kwargs):
        ohlcv = kwargs["ohlcv"]
        return pd.Series([80.0] * len(ohlcv), index=ohlcv.index, dtype="float64")

    monkeypatch.setattr(
        "core.quant_core.strategy_plan.backtest._compute_consensus_scores",
        fake_scores,
    )

    result = run_strategy_plan_backtest(
        strategy_id="strategy-1",
        strategy_name="Desk Test",
        side_policy="long_only",
        horizon="medium",
        timeframe="1D",
        config_json={
            "capital": {"total_capital_mad": 100_000},
            "universe": {"basket": ["AAA"]},
            "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            "logic": {
                "enabled_families": ["sma"],
                "entry_threshold": 999,
                "holding_threshold": 999,
                "exit_threshold": 999,
                "bet_sizing": BET_SIZING,
            },
            "risk": {
                "max_holding_bars": 30,
                "stop_atr_multiplier": 1.5,
                "stop_buffer_pct": 0.005,
                "take_profit_rr": 1.5,
                "time_stop_enabled": True,
                "trailing_stop_enabled": False,
            },
        },
        bars_by_symbol=bars_by_symbol,
        start_date="2024-01-01",
        end_date="2024-01-08",
        cost_model_raw={"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0.0, "slippage_bps": 0.0, "tva_rate": 0.1},
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0.0, "adv_window": 20},
        cooldown_bars=0,
    )

    assert result["general_results"]["metrics"]["number_of_trades"] >= 0
    assert len(result["stocks"]) == 1
    assert result["strategy"]["enabled_families"] == ["sma"]
    assert result["strategy"]["bet_sizing"]["legacy_manual_ladder"]["exit_below"] == 15


def test_run_strategy_plan_backtest_accepts_tz_aware_bars(monkeypatch) -> None:
    bars = _sample_bars()
    bars.index = bars.index.tz_localize("UTC")
    bars_by_symbol = {"AAA": bars}

    def fake_scores(**kwargs):
        ohlcv = kwargs["ohlcv"]
        return pd.Series([80.0] * len(ohlcv), index=ohlcv.index, dtype="float64")

    monkeypatch.setattr(
        "core.quant_core.strategy_plan.backtest._compute_consensus_scores",
        fake_scores,
    )

    result = run_strategy_plan_backtest(
        strategy_id="strategy-1",
        strategy_name="Desk Test",
        side_policy="long_only",
        horizon="medium",
        timeframe="1D",
        config_json={
            "capital": {"total_capital_mad": 100_000},
            "universe": {"basket": ["AAA"]},
            "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            "signal": {"enabled_families": ["sma"]},
            "bet_sizing": BET_SIZING,
            "risk": {
                "max_holding_bars": 30,
                "stop_atr_multiplier": 1.5,
                "stop_buffer_pct": 0.005,
                "take_profit_rr": 1.5,
                "time_stop_enabled": True,
                "trailing_stop_enabled": False,
            },
        },
        bars_by_symbol=bars_by_symbol,
        start_date="2024-01-01",
        end_date="2024-01-08",
        cost_model_raw={"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0.0, "slippage_bps": 0.0, "tva_rate": 0.1},
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0.0, "adv_window": 20},
        cooldown_bars=0,
    )

    assert result["general_results"]["metrics"]["number_of_trades"] >= 0
    assert len(result["stocks"]) == 1


def test_simulate_stock_short_reversal_respects_cash_for_extra_long() -> None:
    bars = pd.DataFrame(
        {
            "Open": [100, 100, 400, 410],
            "High": [101, 401, 411, 421],
            "Low": [99, 99, 399, 409],
            "Close": [100, 100, 405, 415],
            "Volume": [100_000, 100_000, 100_000, 100_000],
        },
        index=pd.date_range("2024-01-01", periods=4, freq="D"),
    )
    scores = pd.Series([-85, 85, 85, 85], index=bars.index, dtype="float64")

    sim = _simulate_stock(
        symbol="AAA",
        bars=bars,
        score_series=scores,
        allocated_capital=100_000,
        side_policy="long_short",
        exposure_ladder=EXPOSURE_LADDER,
        risk={
            "max_holding_bars": 30,
            "stop_atr_multiplier": 1.5,
            "stop_buffer_pct": 0.005,
            "take_profit_rr": 1.5,
            "time_stop_enabled": True,
            "trailing_stop_enabled": False,
        },
        cost_model=_build_cost_model({}),
        cooldown_bars=0,
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
    )

    fills = sim.fills.sort_values("timestamp").reset_index(drop=True)
    assert list(fills["side"])[:2] == ["SELL", "BUY"]
    assert int(fills.loc[0, "qty"]) == -1000
    assert int(fills.loc[1, "qty"]) == 1000
