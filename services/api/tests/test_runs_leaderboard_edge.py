from __future__ import annotations

import datetime as dt
import uuid

from services.api.app.models import Artifact, Run, RunMetric, StrategyDecision, StrategyLeaderboard
from services.api.app.routers import analytics, runs


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *_args, **_kwargs):
        return self

    def filter_by(self, **kwargs):
        rows = [
            row
            for row in self._rows
            if all(getattr(row, key, None) == value for key, value in kwargs.items())
        ]
        return _FakeQuery(rows)

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, count):
        return _FakeQuery(self._rows[:count])

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, run, rows_by_model):
        self._run = run
        self._rows_by_model = rows_by_model

    def get(self, model, key):
        if model is Run and key == self._run.id:
            return self._run
        return None

    def query(self, model):
        return _FakeQuery(self._rows_by_model.get(model, []))


def test_list_strategy_leaderboard_attaches_cached_edge(monkeypatch) -> None:
    run_id = uuid.uuid4()
    run = Run(id=run_id, spec_json={"portfolio": {"initial_cash": 100000}})
    row = StrategyLeaderboard(
        run_id=run_id,
        symbol="ATW",
        strategy_kind="sma",
        rank=1,
        pnl=1500.0,
        cagr=0.12,
        efficiency=0.8,
        n_fills=12,
        best_params_json={"simple_wfo.horizon": "monthly"},
        signal_label="BUY",
        signal_today=72.0,
        signal_date=dt.datetime(2026, 5, 7, tzinfo=dt.timezone.utc),
    )
    db = _FakeDB(
        run,
        {
            StrategyLeaderboard: [row],
            StrategyDecision: [],
            RunMetric: [],
            Artifact: [],
        },
    )
    edge_payload = {
        "symbol": "ATW",
        "horizon": "monthly",
        "source": "signal_engine",
        "bucket": "buy",
        "direction": "long",
        "n": 40,
        "window_start": "2026-01-01",
        "window_end": "2026-03-01",
        "side_policy": "long_short",
        "action_expected_return_gross": 0.01,
        "action_expected_return_net": 0.0034,
        "stock_expected_return": 0.01,
        "expected_return_gross": 0.01,
        "expected_return_net": 0.0034,
        "hit_rate": 0.62,
        "hit_ci_lower": 0.51,
        "hit_ci_upper": 0.72,
        "expectancy_gross": None,
        "expectancy_net": None,
        "edge_ratio_gross": 0.4,
        "edge_ratio_net": 0.14,
        "profit_factor_gross": 1.8,
        "profit_factor_net": 1.2,
        "mc_luck_pvalue_gross": 0.004,
        "mc_luck_pvalue_net": 0.008,
        "label_shuffle_pvalue_gross": 0.02,
        "label_shuffle_pvalue_net": 0.03,
        "proven_edge_gross": True,
        "proven_edge_net": True,
        "gates": {"mc_gross": True, "mc_net": True, "label_shuffle_gross": True, "label_shuffle_net": True, "wilson": True, "n": True},
        "cost_bps_per_side": 33.0,
        "methodology_version": "2026-05-07",
    }
    monkeypatch.setattr(analytics, "_edge_cache_payload", lambda **kwargs: (edge_payload, "hit"))

    out = runs.list_strategy_leaderboard(
        run_id=run_id,
        limit=20,
        best_only=None,
        edge_source="signal_engine",
        edge_cost_bps=None,
        db=db,
    )
    assert len(out) == 1
    assert out[0]["edge"]["symbol"] == "ATW"
    assert out[0]["edge"]["proven_edge_net"] is True
