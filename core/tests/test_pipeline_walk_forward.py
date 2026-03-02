from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_core.pipeline import run_pipeline  # noqa: E402


def _wf_spec(*, train: int, test: int, step: int) -> dict:
    return {
        "source_key": "synthetic",
        "symbols": ["AAA"],
        "data": {
            "source": "synthetic",
            "symbols": ["AAA"],
            "start": "2021-01-01",
            "end": "2022-12-31",
            "interval": "1d",
            "synthetic": {"seed": 7, "start_price": 100.0, "mu": 0.0004, "sigma": 0.01},
        },
        "strategy": {"kind": "sma_price", "params": {"window": 20}},
        "optimization": {
            "method": "random",
            "seed": 11,
            "n_trials": 10,
            "top_k": 3,
            "kinds": ["sma_price"],
            "walk_forward": {
                "enabled": True,
                "horizon": "short",
                "resolved_start_date": "2021-01-01",
                "resolved_end_date": "2022-12-31",
                "train": {"value": int(train), "unit": "days"},
                "test": {"value": int(test), "unit": "days"},
                "step": {"value": int(step), "unit": "days"},
            },
        },
        "plots": {"enabled": False},
    }


def test_walk_forward_leaderboard_contains_variants_and_signals() -> None:
    out = run_pipeline(_wf_spec(train=120, test=30, step=30))

    leaderboard = [r for r in list(out.get("leaderboard") or []) if isinstance(r, dict)]
    assert leaderboard

    periods = {str(r.get("period")) for r in leaderboard if r.get("period")}
    assert periods
    # We expect >1 trial row per fold when top_k > 1.
    assert any(int(r.get("trial_rank") or 0) > 1 for r in leaderboard)

    # Strategy params must be surfaced for variants in best_params_json.
    assert any(
        isinstance(r.get("best_params_json"), dict)
        and "strategy.window" in (r.get("best_params_json") or {})
        for r in leaderboard
    )

    # Signal fields should come from actual backtests, not hardcoded HOLD defaults.
    labels = {str(r.get("signal_label") or "").upper() for r in leaderboard}
    assert labels.intersection({"BUY", "SELL", "HOLD"})
    signal_vals = pd.to_numeric(pd.Series([r.get("signal_today") for r in leaderboard]), errors="coerce").dropna()
    assert not signal_vals.empty

    strategy_payload = dict(out.get("strategy_results") or {}).get("sma_price") or {}
    assert isinstance(strategy_payload.get("metrics"), dict)
    assert len(strategy_payload.get("trade_performance") or []) > 0


def test_walk_forward_changes_when_windows_change() -> None:
    out_fast = run_pipeline(_wf_spec(train=120, test=30, step=30))
    out_slow = run_pipeline(_wf_spec(train=180, test=45, step=45))

    rows_fast = [r for r in list(out_fast.get("leaderboard") or []) if isinstance(r, dict)]
    rows_slow = [r for r in list(out_slow.get("leaderboard") or []) if isinstance(r, dict)]
    assert rows_fast and rows_slow
    assert len(rows_fast) != len(rows_slow)

    vals_fast = pd.to_numeric(pd.Series([r.get("objective_value") for r in rows_fast]), errors="coerce").dropna()
    vals_slow = pd.to_numeric(pd.Series([r.get("objective_value") for r in rows_slow]), errors="coerce").dropna()
    assert not vals_fast.equals(vals_slow)

    wf_fast = dict((dict(out_fast.get("artifacts") or {}).get("walk_forward") or {}))
    wf_slow = dict((dict(out_slow.get("artifacts") or {}).get("walk_forward") or {}))
    assert int(dict(wf_fast.get("train") or {}).get("value") or 0) == 120
    assert int(dict(wf_slow.get("train") or {}).get("value") or 0) == 180
