from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_core.decision.policy_backtest import simulate_decision_policy  # noqa: E402


def _bars_from_rows(rows: list[dict[str, float]], start: str = "2024-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(rows), freq="B", tz="UTC")
    frame = pd.DataFrame(rows, index=idx)
    frame["Volume"] = frame.get("Volume", 100_000.0)
    return frame[["Open", "High", "Low", "Close", "Volume"]]


def _forced_trade_page(
    *,
    status: str,
    stop: float,
    target: float,
    direction: str = "long",
) -> dict:
    return {
        "symbol": "AAA",
        "strategy_kind": "buy_hold",
        "trial_id": "forced",
        "direction": direction,
        "status": status,
        "when_to_act": [],
        "levels": {
            "support": None,
            "resistance": None,
            "entry": 100.0,
            "stop": stop,
            "target": target,
        },
        "invalidation": "",
        "risk": {"rr": 2.0, "risk_per_share": 5.0, "reward_per_share": 10.0, "score": 90.0, "invalidation": ""},
        "opportunity": {"total": 95.0, "layers": {}},
        "confidence": {"total": 95.0, "layers": {}},
        "opportunity_score": 95.0,
        "confidence_score": 95.0,
        "explain": {},
    }


def test_decision_policy_no_leakage_close_t_minus_1() -> None:
    rows = []
    px = 100.0
    for _ in range(40):
        rows.append({"Open": px, "High": px + 1.0, "Low": px - 1.0, "Close": px + 0.2, "Volume": 100_000.0})
        px += 0.3
    bars = _bars_from_rows(rows)

    bundle = simulate_decision_policy(
        bars=bars,
        strategy_name="buy_hold",
        params={},
        test_start=bars.index[10],
        test_end=bars.index[35],
        warmup_bars=5,
        execution="next_open",
        decision_asof="close_t-1",
        op_threshold=0.0,
        conf_threshold=0.0,
        max_holding_days=3,
        symbol="AAA",
    )

    trace = pd.DataFrame(bundle.meta.get("decision_trace") or [])
    assert not trace.empty
    assert (trace["slice_end_date"] == trace["as_of_date"]).all()
    assert (trace["as_of_date"] < trace["decision_date"]).all()


def test_decision_policy_stop_precedence_and_max_holding_exit() -> None:
    bars_stop_target = _bars_from_rows(
        [
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0},
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0},
            {"Open": 100.0, "High": 106.0, "Low": 94.0, "Close": 100.0},
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0},
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0},
        ]
    )

    bundle_a = simulate_decision_policy(
        bars=bars_stop_target,
        strategy_name="buy_hold",
        params={},
        test_start=bars_stop_target.index[1],
        test_end=bars_stop_target.index[3],
        warmup_bars=1,
        execution="next_open",
        decision_asof="close_t",
        op_threshold=70.0,
        conf_threshold=60.0,
        max_holding_days=5,
        symbol="AAA",
        stop_target_precedence="stop_first",
        _decision_page_override=lambda ctx: _forced_trade_page(
            status="trade" if int(ctx["decision_index"]) == 1 else "no_trade",
            stop=95.0,
            target=105.0,
            direction="long",
        ),
    )

    trades_a = pd.DataFrame(bundle_a.report.tables.get("trades"))
    assert len(trades_a) == 1
    assert str(trades_a.iloc[0]["exit_reason"]) == "stop_hit"
    assert float(trades_a.iloc[0]["exit_price"]) == 95.0

    bars_max_hold = _bars_from_rows(
        [
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0},
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0},
            {"Open": 100.0, "High": 102.0, "Low": 99.0, "Close": 100.5},
            {"Open": 100.5, "High": 102.0, "Low": 99.5, "Close": 100.8},
            {"Open": 100.8, "High": 102.0, "Low": 100.0, "Close": 101.0},
        ]
    )

    bundle_b = simulate_decision_policy(
        bars=bars_max_hold,
        strategy_name="buy_hold",
        params={},
        test_start=bars_max_hold.index[1],
        test_end=bars_max_hold.index[3],
        warmup_bars=1,
        execution="next_open",
        decision_asof="close_t",
        op_threshold=70.0,
        conf_threshold=60.0,
        max_holding_days=2,
        symbol="AAA",
        _decision_page_override=lambda ctx: _forced_trade_page(
            status="trade" if int(ctx["decision_index"]) == 1 else "no_trade",
            stop=95.0,
            target=110.0,
            direction="long",
        ),
    )

    trades_b = pd.DataFrame(bundle_b.report.tables.get("trades"))
    assert len(trades_b) == 1
    assert str(trades_b.iloc[0]["exit_reason"]) == "max_holding_days"

