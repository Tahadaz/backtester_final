from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import quant_core.pipeline as pipeline_mod  # noqa: E402
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


def _wf_multi_horizon_spec() -> dict:
    return {
        "source_key": "synthetic",
        "symbols": ["AAA"],
        "data": {
            "source": "synthetic",
            "symbols": ["AAA"],
            "start": "2018-01-01",
            "end": "2024-12-31",
            "interval": "1d",
            "synthetic": {"seed": 19, "start_price": 100.0, "mu": 0.0005, "sigma": 0.012},
        },
        "strategy": {"kind": "sma_price", "params": {"window": 20}},
        "optimization": {
            "method": "random",
            "seed": 23,
            "n_trials": 12,
            "kinds": ["sma_price"],
            "rank_metric": "pnl",
            "walk_forward": {
                "enabled": True,
                "multi_horizon": True,
                "horizons": ["short", "medium", "long"],
                "horizon": "medium",
                "resolved_start_date": "2018-01-01",
                "resolved_end_date": "2024-12-31",
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


def test_multi_horizon_wfo_top20_per_horizon_with_aggregate_summary(monkeypatch) -> None:
    def _fake_horizon_output(horizon: str) -> dict:
        horizon = str(horizon).strip().lower() or "medium"
        horizon_bias = {"short": 0.0, "medium": 10.0, "long": 20.0}.get(horizon, 0.0)
        rows: list[dict] = []
        for fold_idx in range(3):
            start = pd.Timestamp("2024-01-01") + pd.Timedelta(days=fold_idx * 30)
            end = start + pd.Timedelta(days=29)
            for window in range(1, 26):
                base = 500.0 - float(window) * 3.0 + horizon_bias
                objective = base - (fold_idx * 1.5)
                rows.append(
                    {
                        "fold_index": fold_idx,
                        "period": f"Fold {fold_idx + 1}",
                        "start": start.date().isoformat(),
                        "end": end.date().isoformat(),
                        "test_start": start.date().isoformat(),
                        "test_end": end.date().isoformat(),
                        "objective": "pnl",
                        "objective_value": objective,
                        "strategy_kind": "sma_price",
                        "stat.pnl": objective,
                        "stat.cagr": objective / 1000.0,
                        "stat.sharpe": objective / 200.0,
                        "signal_today": 1.0,
                        "signal_label": "BUY",
                        "signal_date": end.date().isoformat(),
                        "param.strategy.window": window,
                    }
                )
        return {
            "leaderboard": [],
            "plot_artifacts": {},
            "strategy_results": {"sma_price": {"metrics": {}, "trade_performance": [], "trade_ledger": []}},
            "decision_support": {},
            "batch_period": {"mode": "walk_forward", "objective": "pnl", "results": rows},
            "metrics": {},
            "fills": [],
            "position_ledger": [],
            "artifacts": {"walk_forward": {"horizon": horizon}},
        }

    original_run_pipeline = pipeline_mod.run_pipeline

    def _fake_run_pipeline(spec_json: dict) -> dict:
        opt = dict(spec_json.get("optimization") or {})
        wf = dict(opt.get("walk_forward") or {})
        if bool(wf.get("enabled")) and not bool(wf.get("multi_horizon", False)):
            return _fake_horizon_output(str(wf.get("horizon") or "medium"))
        return original_run_pipeline(spec_json)

    monkeypatch.setattr(pipeline_mod, "run_pipeline", _fake_run_pipeline)
    out = original_run_pipeline(_wf_multi_horizon_spec())
    simple = dict(out.get("simple_wfo_multi_horizon") or {})
    assert bool(simple.get("enabled")) is True

    rows_by_horizon = dict(simple.get("rows_by_horizon") or {})
    summary_by_horizon = dict(simple.get("summary_by_horizon") or {})
    assert rows_by_horizon

    for horizon, rows in rows_by_horizon.items():
        assert len(rows) <= 20
        available = int(_safe_int(summary_by_horizon.get(horizon, {}).get("n_candidates")) or 0)
        if available > 0:
            assert len(rows) == min(20, available)

    leaderboard = [r for r in list(out.get("leaderboard") or []) if isinstance(r, dict)]
    assert leaderboard
    for row in leaderboard:
        best_params = dict(row.get("best_params_json") or {})
        summary = dict(best_params.get("_summary") or {})
        assert {"objective_mean", "objective_median", "objective_std", "positive_ratio", "n_folds"}.issubset(summary.keys())
        assert best_params.get("last_test_start")
        assert best_params.get("last_test_end")

    by_horizon: dict[str, list[dict]] = {}
    for row in leaderboard:
        best_params = dict(row.get("best_params_json") or {})
        horizon = str(best_params.get("simple_wfo.horizon") or "").strip().lower()
        if not horizon:
            continue
        by_horizon.setdefault(horizon, []).append(row)

    for rows in by_horizon.values():
        ranked = sorted(
            rows,
            key=lambda r: int(r.get("rank") or 999999),
        )
        for idx in range(len(ranked) - 1):
            lhs_summary = dict((dict(ranked[idx].get("best_params_json") or {}).get("_summary") or {}))
            rhs_summary = dict((dict(ranked[idx + 1].get("best_params_json") or {}).get("_summary") or {}))
            lhs_mean = float(lhs_summary.get("objective_mean"))
            rhs_mean = float(rhs_summary.get("objective_mean"))
            if lhs_mean == rhs_mean:
                assert float(lhs_summary.get("objective_std")) <= float(rhs_summary.get("objective_std"))
            else:
                assert lhs_mean >= rhs_mean


def _safe_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return None
