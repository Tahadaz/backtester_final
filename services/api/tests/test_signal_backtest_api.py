from __future__ import annotations

import datetime as dt
import sys
import types
import uuid

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.db import get_db
from services.api.app.models import (
    MarketDataStore,
    SignalBacktestRun,
    SignalBestEvidenceSnapshot,
    SignalEngineBatchJob,
    SignalEngineFamilyResult,
    SignalEngineGlobalResult,
    SignalScoreHistory,
    WfoGlobalSignal,
    WfoSignalSummary,
)
from services.api.app.routers import strategy_signals
from services.api.app.services import signal_engine_persistence as signal_engine_persistence_mod


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter_by(self, **kwargs):
        rows = [
            row
            for row in self._rows
            if all(getattr(row, key, None) == value for key, value in kwargs.items())
        ]
        return _FakeQuery(rows)

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, count):
        return _FakeQuery(self._rows[:count])

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, rows_by_model):
        self.rows_by_model = {**rows_by_model}

    def query(self, model):
        return _FakeQuery(self.rows_by_model.get(model, []))


def _app(db) -> FastAPI:
    app = FastAPI()
    app.include_router(strategy_signals.router)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return app


def test_engine_result_returns_persisted_support_resistance_payload():
    global_row = SignalEngineGlobalResult(
        symbol="AAA",
        horizon="weekly",
        variant="legacy",
        status="succeeded",
        aggregate_score_pct=10.0,
        expanded_aggregate_score_pct=20.0,
        signal_label="Haussier",
        per_category_json={"tendance": {"score_pct": 20.0}},
        per_family_json={"sma": {"score_pct": 20.0}},
        technical_levels_json={"support_buy_trigger": 99.0},
        support_resistance_json={"final_support": 99.0, "final_resistance": 110.0},
        computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
        data_as_of=dt.date(2026, 4, 21),
    )
    family_rows = [
        SignalEngineFamilyResult(
            symbol="AAA",
            family="sma",
            category="tendance",
            horizon="weekly",
            variant="legacy",
            status="succeeded",
            family_score_pct=20.0,
            signal_label="Haussier",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "sma_v1", "archetype": "price_vs_sma", "params": {"window": 20}}],
        ),
        SignalEngineFamilyResult(
            symbol="AAA",
            family="macd",
            category="momentum",
            horizon="weekly",
            variant="legacy",
            status="succeeded",
            family_score_pct=10.0,
            signal_label="Haussier",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "macd_v1", "archetype": "macd_cross", "params": {"fast": 12, "slow": 26, "signal": 9}}],
        ),
        SignalEngineFamilyResult(
            symbol="AAA",
            family="rsi",
            category="oscillation",
            horizon="weekly",
            variant="legacy",
            status="succeeded",
            family_score_pct=5.0,
            signal_label="Neutre",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "rsi_v1", "archetype": "rsi_level", "params": {"period": 14, "oversold": 30, "overbought": 70}}],
        ),
        SignalEngineFamilyResult(
            symbol="AAA",
            family="obv",
            category="volume",
            horizon="weekly",
            variant="legacy",
            status="succeeded",
            family_score_pct=15.0,
            signal_label="Haussier",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "obv_v1", "archetype": "obv_trend", "params": {"ema_period": 20}}],
        ),
    ]
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 4, 21))
    client = TestClient(
        _app(
            _FakeDB(
                {
                    SignalEngineGlobalResult: [global_row],
                    SignalEngineFamilyResult: family_rows,
                    MarketDataStore: [market_row],
                }
            )
        )
    )

    response = client.get("/strategy/engine/result?symbol=AAA&horizon=weekly&variant=legacy")

    assert response.status_code == 200
    payload = response.json()
    assert payload["technical_levels"] == {"support_buy_trigger": 99.0}
    assert payload["support_resistance"] == {"final_support": 99.0, "final_resistance": 110.0}
    assert payload["resolution_mode"] == "fresh_cache"


def test_engine_result_returns_stale_cache_without_refresh_or_rebuild(monkeypatch):
    global_row = SignalEngineGlobalResult(
        symbol="AAA",
        horizon="weekly",
        variant="legacy",
        status="succeeded",
        aggregate_score_pct=10.0,
        expanded_aggregate_score_pct=20.0,
        signal_label="Haussier",
        per_category_json={"tendance": {"score_pct": 20.0}},
        per_family_json={"sma": {"score_pct": 20.0}},
        technical_levels_json={"support_buy_trigger": 99.0},
        support_resistance_json={"final_support": 99.0, "final_resistance": 110.0},
        computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
        data_as_of=dt.date(2026, 4, 21),
    )
    family_rows = [
        SignalEngineFamilyResult(
            symbol="AAA",
            family="sma",
            category="tendance",
            horizon="weekly",
            variant="legacy",
            status="succeeded",
            family_score_pct=20.0,
            signal_label="Haussier",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "sma_v1", "archetype": "price_vs_sma", "params": {"window": 20}}],
        ),
        SignalEngineFamilyResult(
            symbol="AAA",
            family="macd",
            category="momentum",
            horizon="weekly",
            variant="legacy",
            status="succeeded",
            family_score_pct=10.0,
            signal_label="Haussier",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "macd_v1", "archetype": "macd_cross", "params": {"fast": 12, "slow": 26, "signal": 9}}],
        ),
        SignalEngineFamilyResult(
            symbol="AAA",
            family="rsi",
            category="oscillation",
            horizon="weekly",
            variant="legacy",
            status="succeeded",
            family_score_pct=5.0,
            signal_label="Neutre",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "rsi_v1", "archetype": "rsi_level", "params": {"period": 14, "oversold": 30, "overbought": 70}}],
        ),
        SignalEngineFamilyResult(
            symbol="AAA",
            family="obv",
            category="volume",
            horizon="weekly",
            variant="legacy",
            status="succeeded",
            family_score_pct=15.0,
            signal_label="Haussier",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "obv_v1", "archetype": "obv_trend", "params": {"ema_period": 20}}],
        ),
    ]
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 4, 22))
    client = TestClient(
        _app(
            _FakeDB(
                {
                    SignalEngineGlobalResult: [global_row],
                    SignalEngineFamilyResult: family_rows,
                    MarketDataStore: [market_row],
                }
            )
        )
    )

    monkeypatch.setattr(
        signal_engine_persistence_mod,
        "refresh_from_persisted_reps",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("stale GET should not refresh")),
    )
    monkeypatch.setattr(
        signal_engine_persistence_mod,
        "full_rebuild_from_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("stale GET should not rebuild")),
    )

    response = client.get("/strategy/engine/result?symbol=AAA&horizon=weekly&variant=legacy")

    assert response.status_code == 200
    payload = response.json()
    assert payload["resolution_mode"] == "stale_cache"
    assert payload["cache_state"] == "stale"
    assert payload["is_stale"] is True
    assert payload["market_data_as_of"] == "2026-04-22"


def test_persisted_signal_engine_summaries_follow_variant_specific_persisted_scores():
    rows = [
        SignalEngineGlobalResult(
            symbol="AAA",
            horizon="weekly",
            variant="expanded",
            status="succeeded",
            aggregate_score_pct=10.0,
            expanded_aggregate_score_pct=44.0,
            signal_label="Achat",
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
        ),
        SignalEngineGlobalResult(
            symbol="AAA",
            horizon="weekly",
            variant="legacy",
            status="succeeded",
            aggregate_score_pct=10.0,
            expanded_aggregate_score_pct=44.0,
            signal_label="Achat",
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
        ),
    ]
    market_rows = [MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 4, 22))]
    client = TestClient(_app(_FakeDB({SignalEngineGlobalResult: rows, MarketDataStore: market_rows})))

    expanded = client.post(
        "/strategy/engine/persisted-summaries",
        json={"symbols": ["AAA", "BBB"], "horizon": "weekly", "variant": "expanded"},
    )
    legacy = client.post(
        "/strategy/engine/persisted-summaries",
        json={"symbols": ["AAA"], "horizon": "weekly", "variant": "legacy"},
    )

    assert expanded.status_code == 200
    assert legacy.status_code == 200

    expanded_payload = expanded.json()
    legacy_payload = legacy.json()

    assert expanded_payload[0]["symbol"] == "AAA"
    assert expanded_payload[0]["aggregate_score_pct"] == 44.0
    assert expanded_payload[0]["is_stale"] is True
    assert expanded_payload[1]["symbol"] == "BBB"
    assert expanded_payload[1]["aggregate_score_pct"] is None

    assert legacy_payload[0]["symbol"] == "AAA"
    assert legacy_payload[0]["aggregate_score_pct"] == 10.0


def test_signal_evidence_endpoint_respects_requested_source_and_keeps_requested_variant(monkeypatch):
    captured: dict[str, object] = {}
    edge_payload = {
        "symbol": "AAA",
        "horizon": "weekly",
        "source": "signal_engine",
        "variant": "expanded_factor_x_ta_combo",
        "bucket": "buy",
        "direction": "long",
        "n": 35,
        "window_start": "2026-01-01",
        "window_end": "2026-04-21",
        "proof_n": 35,
        "proof_method": "same_oos_sample",
        "action_expected_return_net": 0.014,
        "hit_rate": 0.64,
        "cost_bps_per_side": 33.0,
    }

    def fake_select_edge(_db, **kwargs):
        captured.update(kwargs)
        return edge_payload, "signal_engine", "expanded_factor_x_ta_combo", "Signal Engine - Expanded Factor x TA Combo"

    monkeypatch.setattr(strategy_signals, "_select_signal_evidence_edge", fake_select_edge)
    monkeypatch.setattr(strategy_signals, "_current_evidence_signal", lambda *_args, **_kwargs: {"score_pct": 72.0})
    monkeypatch.setattr(strategy_signals, "_signal_evidence_contributors", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(strategy_signals, "_signal_evidence_oos_periods", lambda *_args, **_kwargs: ([], 0, None))

    client = TestClient(_app(_FakeDB({})))
    response = client.get(
        "/strategy/signal/evidence?symbol=AAA&horizon=weekly&source=signal_engine&variant=expanded_factor_x_ta_combo"
    )

    assert response.status_code == 200
    assert captured["source"] == "signal_engine"
    assert captured["variant"] == "expanded_factor_x_ta_combo"
    payload = response.json()
    assert payload["source"] == "signal_engine"
    assert payload["variant"] == "expanded_factor_x_ta_combo"
    assert payload["edge"]["variant"] == "expanded_factor_x_ta_combo"


def test_signal_evidence_auto_prefers_relaxed_wfo_even_when_unproven(monkeypatch):
    from services.api.app.services import dashboard_builder

    calls: list[tuple[str, str]] = []

    def edge_payload(source: str, variant: str, *, n: int, expected: float, edge_score: float) -> dict[str, object]:
        return {
            "symbol": "AAA",
            "horizon": "weekly",
            "source": source,
            "variant": variant,
            "bucket": "buy",
            "direction": "long",
            "n": n,
            "proof_n": n,
            "action_expected_return_net": expected,
            "expected_return_net": expected,
            "edge_score": edge_score,
            "proven_edge_net": False,
            "gates": {"n": False},
            "cost_bps_per_side": 33.0,
        }

    def fake_edge(_db, **kwargs):
        source = str(kwargs["source"])
        variant = str(kwargs["variant"])
        calls.append((source, variant))
        if source == "signal_engine":
            return edge_payload(source, variant, n=80, expected=0.05, edge_score=95.0)
        if variant == "legacy_ta_simple":
            return edge_payload(source, variant, n=2, expected=-0.01, edge_score=3.0)
        if variant == "expanded_factor_x_ta_simple":
            return edge_payload(source, variant, n=4, expected=0.002, edge_score=12.0)
        return None

    monkeypatch.setattr(strategy_signals, "_edge_payload_for_evidence", fake_edge)
    monkeypatch.setattr(
        dashboard_builder,
        "_apply_wfo_all_oos_proof_to_edge",
        lambda _db, **kwargs: kwargs["edge"],
    )

    edge, selected_source, selected_variant, _label = strategy_signals._select_signal_evidence_edge(
        _FakeDB({}),
        symbol="AAA",
        horizon="weekly",
        source="auto",
        variant=None,
        cost_bps=33.0,
    )

    assert selected_source == "wfo"
    assert selected_variant == "expanded_factor_x_ta_simple"
    assert edge["n"] == 4
    assert calls
    assert {source for source, _variant in calls} == {"wfo"}

    calls.clear()
    _edge, selected_source, selected_variant, _label = strategy_signals._select_signal_evidence_edge(
        _FakeDB({}),
        symbol="AAA",
        horizon="weekly",
        source="signal_engine",
        variant=None,
        cost_bps=33.0,
    )

    assert selected_source == "wfo"
    assert selected_variant == "expanded_factor_x_ta_simple"
    assert {source for source, _variant in calls} == {"wfo"}


def test_signal_evidence_endpoint_uses_wfo_stitched_oos_when_wfo_requested(monkeypatch):
    edge_payload = {
        "symbol": "AAA",
        "horizon": "weekly",
        "source": "wfo",
        "variant": "expanded_ta_simple",
        "bucket": "sell",
        "direction": "short",
        "n": 44,
        "window_start": "2026-01-01",
        "window_end": "2026-04-21",
        "proof_n": 44,
        "proof_method": "same_oos_sample",
        "fwd_horizon_bars": 1,
        "return_calc_method": "open_to_exit_ladder",
        "exit_price_kind": "close",
        "exit_timing_label": "close T+1",
        "selection_n": 30,
        "selection_action_expected_return_net": 0.012,
        "selection_hit_rate": 0.61,
        "cost_bps_per_side": 0.0,
    }

    def fake_select_edge(_db, **kwargs):
        assert kwargs["symbol"] == "AAA"
        assert kwargs["horizon"] == "weekly"
        assert kwargs["source"] == "wfo"
        return edge_payload, "wfo", "expanded_ta_simple", "WFO / Expanded"

    monkeypatch.setattr(strategy_signals, "_select_signal_evidence_edge", fake_select_edge)

    prices = pd.DataFrame(
        {
            "Open": [100.0, 100.0, 99.0, 98.0, 97.0, 96.0],
            "High": [101.0, 101.0, 100.0, 99.0, 98.0, 97.0],
            "Low": [99.0, 99.0, 97.0, 96.0, 95.0, 94.0],
            "Close": [100.0, 100.0, 98.0, 97.0, 96.0, 95.0],
            "Volume": [1000.0] * 6,
        },
        index=pd.DatetimeIndex([
            "2026-01-01",
            "2026-01-02",
            "2026-01-05",
            "2026-01-06",
            "2026-01-07",
            "2026-01-08",
        ]),
    )
    from services.api.app.routers import analytics as analytics_mod

    monkeypatch.setattr(analytics_mod, "_load_pricing_data", lambda _db, _symbol: prices)

    global_row = WfoGlobalSignal(
        symbol="AAA",
        horizon="weekly",
        variant="expanded_ta_simple",
        status="succeeded",
        global_score_pct=-25.0,
        raw_score_pct=-25.0,
        signal_label="Vente",
        recommendation="vente",
        best_category="tendance",
        best_category_score=-25.0,
        computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
        data_as_of=dt.date(2026, 4, 21),
    )
    summary_row = WfoSignalSummary(
        symbol="AAA",
        category="tendance",
        horizon="weekly",
        variant="expanded_ta_simple",
        status="succeeded",
        score_pct=-25.0,
        signal_label="Vente",
        computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
        data_as_of=dt.date(2026, 4, 21),
        representatives_json=[
            {
                "variant_id": "sma_20",
                "family": "sma",
                "archetype": "price_vs_sma",
                "description": "Price below SMA 20",
                "params": {"window": 20},
                "normalized_weight": 0.7,
                "signal_label": "Vente",
                "indicator_value": 101.5,
            },
            {
                "variant_id": "sma_50",
                "family": "sma",
                "archetype": "price_vs_sma",
                "description": "Price below SMA 50",
                "params": {"window": 50},
                "normalized_weight": 0.8,
                "signal_label": "Vente",
                "indicator_value": 103.5,
            },
        ],
        folds_json=[
            {
                "index": 0,
                "oos_start": 1,
                "oos_end": 3,
                "winner_variant_id": "sma_20",
                "winner_description": "Price below SMA 20",
                "winner_params": {"window": 20},
            },
            {
                "index": 1,
                "oos_start": 3,
                "oos_end": 5,
                "winner_variant_id": "sma_50",
                "winner_description": "Price below SMA 50",
                "winner_params": {"window": 50},
            },
        ],
    )
    score_rows = [
        SignalScoreHistory(
            date=dt.date(2026, 1, 2),
            symbol="AAA",
            source="wfo:expanded_ta_simple",
            category="tendance",
            horizon="weekly",
            score_pct=-25.0,
            is_oos=True,
        ),
        SignalScoreHistory(
            date=dt.date(2026, 1, 5),
            symbol="AAA",
            source="wfo:expanded_ta_simple",
            category="tendance",
            horizon="weekly",
            score_pct=-60.0,
            is_oos=True,
        ),
        SignalScoreHistory(
            date=dt.date(2026, 1, 6),
            symbol="AAA",
            source="wfo:expanded_ta_simple",
            category="tendance",
            horizon="weekly",
            score_pct=-25.0,
            is_oos=True,
        ),
        SignalScoreHistory(
            date=dt.date(2026, 1, 7),
            symbol="AAA",
            source="wfo:expanded_ta_simple",
            category="tendance",
            horizon="weekly",
            score_pct=25.0,
            is_oos=True,
        ),
    ]
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 1, 8))
    client = TestClient(
        _app(
            _FakeDB(
                {
                    WfoGlobalSignal: [global_row],
                    WfoSignalSummary: [summary_row],
                    SignalScoreHistory: score_rows,
                    MarketDataStore: [market_row],
                }
            )
        )
    )

    response = client.get("/strategy/signal/evidence?symbol=AAA&horizon=weekly&source=wfo")

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "AAA"
    assert payload["source"] == "wfo"
    assert payload["current_signal"]["score_pct"] == -25.0
    assert payload["current_signal"]["bucket"] == "sell"
    assert payload["edge"]["proof_method"] == "all_wfo_oos_folds_exact_bucket"
    assert payload["edge"]["n"] == 2
    assert payload["oos"]["proof_window_start"] == "2026-01-02"
    assert payload["oos"]["proof_window_end"] == "2026-01-06"
    assert payload["oos"]["proof_limit"] == "100"
    assert payload["oos"]["stitched_window_start"] == "2026-01-02"
    assert payload["oos"]["stitched_window_end"] == "2026-01-07"
    assert payload["contributor_count"] == 2
    assert payload["evidence_trade_count"] == 2
    assert [period["sample_n"] for period in payload["oos_periods"]] == [1, 1]
    assert payload["oos_periods"][0]["contributors"][0]["variant_id"] == "sma_20"
    assert payload["oos_periods"][1]["contributors"][0]["variant_id"] == "sma_50"
    assert [trade["signal_date"] for period in payload["oos_periods"] for trade in period["trades"]] == [
        "2026-01-02",
        "2026-01-06",
    ]
    stitched = payload["stitched_oos_backtest"]
    assert stitched["source"] == "wfo"
    assert stitched["match_mode"] == "exact_bucket"
    assert stitched["dates"] == ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
    assert stitched["open_series"] == [100.0, 99.0, 98.0, 97.0]
    assert stitched["high_series"] == [101.0, 100.0, 99.0, 98.0]
    assert stitched["low_series"] == [99.0, 97.0, 96.0, 95.0]
    assert stitched["close_series"] == [100.0, 98.0, 97.0, 96.0]
    assert stitched["metrics"]["n_trades"] == 2
    assert stitched["warnings"] == [
        "Too few OOS trades: n=2, minimum=30. Shown for audit only; do not treat as a proven edge."
    ]
    assert stitched["metrics"]["hit_rate"] == 1.0
    assert [row["marker_label"] for row in stitched["trade_ledger"]] == ["Short 1", "Cover 1", "Short 2", "Cover 2"]
    assert [row["position"] for row in stitched["trade_ledger"]] == [-1.0, 0.0, -1.0, 0.0]
    assert [row["transaction_index"] for row in stitched["trade_ledger"]] == [1, 2, 3, 4]
    assert stitched["trade_ledger"][0]["prix_execution"] == 99.0
    assert stitched["trade_ledger"][0]["close_du_jour"] == 98.0

    cooldown_response = client.get("/strategy/signal/evidence?symbol=AAA&horizon=weekly&source=wfo&cooldown_bars=3")

    assert cooldown_response.status_code == 200
    cooldown_payload = cooldown_response.json()
    assert cooldown_payload["edge"]["n"] == 1
    assert cooldown_payload["evidence_trade_count"] == 1
    assert [period["sample_n"] for period in cooldown_payload["oos_periods"]] == [1, 0]
    assert [trade["signal_date"] for period in cooldown_payload["oos_periods"] for trade in period["trades"]] == [
        "2026-01-02",
    ]
    cooldown_stitched = cooldown_payload["stitched_oos_backtest"]
    assert cooldown_stitched["cooldown_bars"] == 3
    assert cooldown_stitched["metrics"]["n_trades"] == 1
    assert cooldown_stitched["metrics"]["cooldown_bars"] == 3
    assert cooldown_stitched["metrics"]["cooldown_filtered_trades"] == 1
    assert [row["marker_label"] for row in cooldown_stitched["trade_ledger"]] == ["Short 1", "Cover 1"]


def test_signal_evidence_proof_limit_uses_latest_bucket_trades_and_keeps_full_stitch(monkeypatch):
    dates = pd.bdate_range("2026-01-01", periods=130)
    opens = [200.0 - float(i) for i in range(len(dates))]
    prices = pd.DataFrame(
        {
            "Open": opens,
            "High": [value + 1.0 for value in opens],
            "Low": [value - 2.0 for value in opens],
            "Close": [value - 1.0 for value in opens],
            "Volume": [1000.0] * len(dates),
        },
        index=dates,
    )
    from services.api.app.routers import analytics as analytics_mod

    monkeypatch.setattr(analytics_mod, "_load_pricing_data", lambda _db, _symbol: prices)

    edge_payload = {
        "symbol": "AAA",
        "horizon": "weekly",
        "source": "wfo",
        "variant": "expanded_ta_simple",
        "bucket": "sell",
        "direction": "short",
        "n": 100,
        "window_start": dates[20].date().isoformat(),
        "window_end": dates[119].date().isoformat(),
        "proof_n": 100,
        "proof_method": "same_oos_sample",
        "fwd_horizon_bars": 1,
        "return_calc_method": "open_to_exit_ladder",
        "exit_price_kind": "close",
        "exit_timing_label": "close T+1",
        "cost_bps_per_side": 0.0,
    }

    monkeypatch.setattr(
        strategy_signals,
        "_select_signal_evidence_edge",
        lambda _db, **_kwargs: (edge_payload, "wfo", "expanded_ta_simple", "WFO / Expanded"),
    )

    global_row = WfoGlobalSignal(
        symbol="AAA",
        horizon="weekly",
        variant="expanded_ta_simple",
        status="succeeded",
        global_score_pct=-25.0,
        raw_score_pct=-25.0,
        signal_label="Vente",
        recommendation="vente",
        best_category="tendance",
        best_category_score=-25.0,
        computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
        data_as_of=dt.date(2026, 4, 21),
    )
    summary_row = WfoSignalSummary(
        symbol="AAA",
        category="tendance",
        horizon="weekly",
        variant="expanded_ta_simple",
        status="succeeded",
        score_pct=-25.0,
        signal_label="Vente",
        computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
        data_as_of=dt.date(2026, 4, 21),
        representatives_json=[
            {
                "variant_id": "sma_20",
                "family": "sma",
                "archetype": "price_vs_sma",
                "description": "Price below SMA 20",
                "params": {"window": 20},
                "normalized_weight": 1.0,
                "signal_label": "Vente",
            },
        ],
        folds_json=[
            {
                "index": 0,
                "oos_start": 0,
                "oos_end": 120,
                "winner_variant_id": "sma_20",
                "winner_description": "Price below SMA 20",
                "winner_params": {"window": 20},
            },
        ],
    )
    score_rows = [
        SignalScoreHistory(
            date=date.date(),
            symbol="AAA",
            source="wfo:expanded_ta_simple",
            category="tendance",
            horizon="weekly",
            score_pct=-25.0,
            is_oos=True,
        )
        for date in dates[:120]
    ]
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 4, 21))
    client = TestClient(
        _app(
            _FakeDB(
                {
                    WfoGlobalSignal: [global_row],
                    WfoSignalSummary: [summary_row],
                    SignalScoreHistory: score_rows,
                    MarketDataStore: [market_row],
                }
            )
        )
    )

    response = client.get("/strategy/signal/evidence?symbol=AAA&horizon=weekly&source=wfo")
    assert response.status_code == 200
    payload = response.json()
    assert payload["edge"]["n"] == 100
    assert payload["oos"]["proof_n"] == 100
    assert payload["oos"]["proof_window_start"] == dates[20].date().isoformat()
    assert payload["oos"]["proof_window_end"] == dates[119].date().isoformat()
    assert payload["evidence_trade_count"] == 120
    assert payload["stitched_oos_backtest"]["metrics"]["n_trades"] == 120
    assert isinstance(payload["stitched_oos_backtest"]["metrics"]["var95"], float)
    assert isinstance(payload["stitched_oos_backtest"]["metrics"]["cvar95"], float)
    assert payload["stitched_oos_backtest"]["metrics"]["cvar95"] <= payload["stitched_oos_backtest"]["metrics"]["var95"]
    assert payload["stitched_oos_backtest"]["proof"]["n_trades"] == 100
    assert payload["oos"]["stitched_window_start"] == dates[0].date().isoformat()
    assert payload["oos"]["stitched_window_end"] == dates[119].date().isoformat()

    all_response = client.get("/strategy/signal/evidence?symbol=AAA&horizon=weekly&source=wfo&proof_limit=all")
    assert all_response.status_code == 200
    all_payload = all_response.json()
    assert all_payload["edge"]["n"] == 120
    assert all_payload["oos"]["proof_n"] == 120
    assert all_payload["oos"]["proof_limit"] == "all"
    assert all_payload["oos"]["proof_window_start"] == dates[0].date().isoformat()
    assert all_payload["oos"]["proof_window_end"] == dates[119].date().isoformat()
    assert all_payload["stitched_oos_backtest"]["metrics"]["n_trades"] == 120
    assert isinstance(all_payload["stitched_oos_backtest"]["metrics"]["var95"], float)
    assert isinstance(all_payload["stitched_oos_backtest"]["metrics"]["cvar95"], float)


def test_signal_best_evidence_reads_stored_payload_without_live_build(monkeypatch):
    payload = {
        "symbol": "AAA",
        "horizon": "weekly",
        "source": "wfo",
        "variant": "expanded_ta_simple",
        "method_label": "WFO - Expanded TA Simple",
        "current_signal": {"bucket": "buy", "direction": "long", "data_as_of": "2026-01-08"},
        "edge": {"bucket": "buy", "direction": "long", "n": 42},
        "oos": {"proof_n": 42},
        "contributors": [],
        "contributor_count": 0,
        "factor_condition_count": 0,
        "oos_periods": [],
        "evidence_trade_count": 0,
        "stitched_oos_backtest": None,
    }
    snapshot = SignalBestEvidenceSnapshot(
        symbol="AAA",
        horizon="weekly",
        cooldown_bars=0,
        status="succeeded",
        source="wfo",
        variant="expanded_ta_simple",
        evidence_payload_jsonb=payload,
        chart_payload_jsonb=None,
        data_as_of=dt.date(2026, 1, 8),
        market_data_as_of=dt.date(2026, 1, 8),
    )
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 1, 8))
    client = TestClient(_app(_FakeDB({SignalBestEvidenceSnapshot: [snapshot], MarketDataStore: [market_row]})))

    monkeypatch.setattr(
        strategy_signals,
        "_select_signal_evidence_edge",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("live selector should not run")),
    )

    response = client.get("/strategy/signal/best-evidence?symbol=AAA&horizon=weekly")

    assert response.status_code == 200
    assert response.json() == payload


def test_signal_best_backtest_chart_reads_stored_payload_without_trigger():
    chart_payload = {
        "symbol": "AAA",
        "horizon": "weekly",
        "variant": "expanded_ta_simple",
        "market_data_as_of": "2026-01-08",
        "results": [
            {
                "source": "wfo",
                "scope": "global",
                "scope_key": "global",
                "status": "succeeded",
                "side_policy": "long_short",
                "cooldown_bars": 0,
                "dates": ["2026-01-07", "2026-01-08"],
                "close_series": [100.0, 101.0],
                "position_series": [0.0, 1.0],
            }
        ],
    }
    snapshot = SignalBestEvidenceSnapshot(
        symbol="AAA",
        horizon="weekly",
        cooldown_bars=0,
        status="succeeded",
        source="wfo",
        variant="expanded_ta_simple",
        evidence_payload_jsonb=None,
        chart_payload_jsonb=chart_payload,
        data_as_of=dt.date(2026, 1, 8),
        market_data_as_of=dt.date(2026, 1, 8),
    )
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 1, 8))
    client = TestClient(_app(_FakeDB({SignalBestEvidenceSnapshot: [snapshot], MarketDataStore: [market_row]})))

    response = client.get("/strategy/backtest-mc/best-chart?symbol=AAA&horizon=weekly")

    assert response.status_code == 200
    assert response.json() == chart_payload


def test_signal_best_snapshot_rejects_stale_payload():
    payload = {
        "symbol": "AAA",
        "horizon": "weekly",
        "source": "wfo",
        "variant": "expanded_ta_simple",
        "method_label": "WFO",
        "current_signal": {},
        "edge": {},
        "oos": {},
        "contributors": [],
        "contributor_count": 0,
        "factor_condition_count": 0,
        "oos_periods": [],
        "evidence_trade_count": 0,
    }
    snapshot = SignalBestEvidenceSnapshot(
        symbol="AAA",
        horizon="weekly",
        cooldown_bars=0,
        status="succeeded",
        source="wfo",
        variant="expanded_ta_simple",
        evidence_payload_jsonb=payload,
        data_as_of=dt.date(2026, 1, 7),
        market_data_as_of=dt.date(2026, 1, 7),
    )
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 1, 8))
    client = TestClient(_app(_FakeDB({SignalBestEvidenceSnapshot: [snapshot], MarketDataStore: [market_row]})))

    response = client.get("/strategy/signal/best-evidence?symbol=AAA&horizon=weekly")

    assert response.status_code == 409
    assert "stale" in response.json()["detail"]


def test_normalize_wfo_folds_rebases_stale_horizon_capped_rows():
    from services.api.app.services.wfo_folds import normalize_wfo_folds_json

    index = pd.bdate_range("2021-01-01", periods=1300)
    folds = [
        {
            "index": 0,
            "oos_start": 224,
            "oos_end": 268,
            "oos_start_date": "2005-11-29",
            "oos_end_date": "2006-02-02",
        }
    ]

    normalized = normalize_wfo_folds_json(
        folds,
        config_json={"horizon_cap_bars_used": 1260, "data_bars": 1300},
        ohlcv_index=index,
    )

    assert normalized is not None
    assert normalized[0]["oos_start_abs_idx"] == 264
    assert normalized[0]["oos_end_abs_idx"] == 308
    assert normalized[0]["oos_start_date"] == index[264].date().isoformat()
    assert normalized[0]["oos_end_date"] == index[307].date().isoformat()


def test_evidence_trade_ledger_sorts_by_transaction_date_and_stacks_positions():
    trades = [
        {
            "trade_id": "later",
            "signal_date": "2026-01-03",
            "entry_date": "2026-01-03",
            "exit_date": "2026-01-24",
            "direction": "long",
            "bucket": "strong_buy",
            "score_pct": 80.0,
            "entry_price": 102.0,
            "exit_price": 108.0,
            "action_return_net": 0.0588,
        },
        {
            "trade_id": "first",
            "signal_date": "2026-01-02",
            "entry_date": "2026-01-02",
            "exit_date": "2026-01-23",
            "direction": "long",
            "bucket": "strong_buy",
            "score_pct": 75.0,
            "entry_price": 100.0,
            "exit_price": 105.0,
            "action_return_net": 0.05,
        },
    ]

    ledger = strategy_signals._evidence_trade_ledger(trades, cost_bps=0.0)

    assert [row["date"] for row in ledger] == ["2026-01-02", "2026-01-03", "2026-01-23", "2026-01-24"]
    assert [row["marker_label"] for row in ledger] == ["Buy 1", "Buy 2", "Sell 1", "Sell 2"]
    assert [row["position"] for row in ledger] == [1.0, 2.0, 1.0, 0.0]
    assert [row["cmp"] for row in ledger] == [100.0, 101.0, 101.0, 101.0]
    assert [row["pnl_realise"] for row in ledger] == [0.0, 0.0, 4.0, 7.0]
    assert [row["pnl_realise_cumule"] for row in ledger] == [0.0, 0.0, 4.0, 11.0]
    assert [row["global_score_pct"] for row in ledger] == [75.0, 80.0, 75.0, 80.0]
    assert [row["transaction_index"] for row in ledger] == [1, 2, 3, 4]


def test_evidence_trade_ledger_sorts_same_day_events_by_execution_timing():
    trades = [
        {
            "trade_id": "first",
            "signal_date": "2026-01-01",
            "entry_date": "2026-01-02",
            "entry_price_kind": "open",
            "exit_date": "2026-01-02",
            "exit_price_kind": "close",
            "direction": "long",
            "score_pct": 70.0,
            "entry_price": 100.0,
            "exit_price": 101.0,
            "action_return_net": 0.01,
        },
        {
            "trade_id": "second",
            "signal_date": "2026-01-02",
            "entry_date": "2026-01-02",
            "entry_price_kind": "open",
            "exit_date": "2026-01-02",
            "exit_price_kind": "close",
            "direction": "long",
            "score_pct": 72.0,
            "entry_price": 102.0,
            "exit_price": 103.0,
            "action_return_net": 0.0098,
        },
    ]

    ledger = strategy_signals._evidence_trade_ledger(trades, cost_bps=0.0)

    assert [row["marker_label"] for row in ledger] == ["Buy 1", "Buy 2", "Sell 1", "Sell 2"]
    assert [row["position"] for row in ledger] == [1.0, 2.0, 1.0, 0.0]
    assert [row["cmp"] for row in ledger] == [100.0, 101.0, 101.0, 101.0]
    assert [row["transaction_index"] for row in ledger] == [1, 2, 3, 4]


def test_evidence_trade_ledger_includes_costs_in_weighted_cmp():
    trades = [
        {
            "trade_id": "first",
            "entry_date": "2026-01-02",
            "exit_date": "2026-01-23",
            "direction": "long",
            "entry_price": 100.0,
            "exit_price": 105.0,
        },
        {
            "trade_id": "second",
            "entry_date": "2026-01-03",
            "exit_date": "2026-01-24",
            "direction": "long",
            "entry_price": 102.0,
            "exit_price": 108.0,
        },
    ]

    ledger = strategy_signals._evidence_trade_ledger(trades, cost_bps=100.0)

    assert [row["cmp"] for row in ledger] == [101.0, 102.01, 102.01, 102.01]
    assert [row["pnl_realise"] for row in ledger] == [0.0, 0.0, 1.94, 4.91]
    assert ledger[-1]["pnl_realise_cumule"] == 6.85


def test_evidence_trade_ledger_uses_weighted_cmp_for_stacked_shorts():
    trades = [
        {
            "trade_id": "first",
            "entry_date": "2026-01-02",
            "exit_date": "2026-01-23",
            "direction": "short",
            "entry_price": 100.0,
            "exit_price": 95.0,
        },
        {
            "trade_id": "second",
            "entry_date": "2026-01-03",
            "exit_date": "2026-01-24",
            "direction": "short",
            "entry_price": 98.0,
            "exit_price": 94.0,
        },
    ]

    ledger = strategy_signals._evidence_trade_ledger(trades, cost_bps=0.0)

    assert [row["marker_label"] for row in ledger] == ["Short 1", "Short 2", "Cover 1", "Cover 2"]
    assert [row["position"] for row in ledger] == [-1.0, -2.0, -1.0, 0.0]
    assert [row["cmp"] for row in ledger] == [100.0, 99.0, 99.0, 99.0]
    assert [row["pnl_realise"] for row in ledger] == [0.0, 0.0, 4.0, 5.0]


def test_evidence_trade_ledger_uses_daily_close_for_mark_to_market():
    trades = [
        {
            "trade_id": "first",
            "entry_date": "2026-01-02",
            "entry_price_kind": "open",
            "entry_price": 100.0,
            "entry_close_price": 101.0,
            "exit_date": "2026-01-06",
            "exit_price_kind": "open",
            "exit_price": 103.0,
            "exit_close_price": 104.0,
            "direction": "long",
        }
    ]

    ledger = strategy_signals._evidence_trade_ledger(trades, cost_bps=0.0)

    assert ledger[0]["prix_execution"] == 100.0
    assert ledger[0]["close_du_jour"] == 101.0
    assert ledger[0]["pnl_latent"] == 1.0
    assert ledger[1]["prix_execution"] == 103.0
    assert ledger[1]["close_du_jour"] == 104.0
    assert ledger[1]["pnl_realise"] == 3.0


def test_evidence_stitched_backtest_returns_pnl_over_opened_notional_not_compounded_returns():
    trades = [
        {
            "trade_id": "first",
            "entry_date": "2026-01-01",
            "exit_date": "2026-01-03",
            "direction": "long",
            "entry_price": 100.0,
            "exit_price": 200.0,
            "action_return_net": 1.0,
            "action_return_gross": 1.0,
        },
        {
            "trade_id": "second",
            "entry_date": "2026-01-02",
            "exit_date": "2026-01-03",
            "direction": "long",
            "entry_price": 100.0,
            "exit_price": 200.0,
            "action_return_net": 1.0,
            "action_return_gross": 1.0,
        },
    ]

    stitched = strategy_signals._evidence_stitched_backtest(
        dates=["2026-01-01", "2026-01-02", "2026-01-03"],
        close=[100.0, 100.0, 200.0],
        trades=trades,
        bucket="buy",
        direction="long",
        score_mode="test",
        cost_bps=0.0,
    )

    assert stitched["metrics"]["total_return"] == 1.0
    assert stitched["equity"] == [1.0, 1.0, 2.0]


def test_evidence_stitched_backtest_treats_none_direction_as_no_action():
    trades = [
        {
            "trade_id": "neutral-one",
            "entry_date": "2026-01-01",
            "exit_date": "2026-01-03",
            "direction": "none",
            "entry_price": 100.0,
            "exit_price": 104.0,
            "stock_return": 0.04,
            "action_return_net": None,
            "action_return_gross": None,
        },
        {
            "trade_id": "neutral-two",
            "entry_date": "2026-01-02",
            "exit_date": "2026-01-03",
            "direction": "none",
            "entry_price": 100.0,
            "exit_price": 102.0,
            "stock_return": 0.02,
            "action_return_net": None,
            "action_return_gross": None,
        },
    ]

    stitched = strategy_signals._evidence_stitched_backtest(
        dates=["2026-01-01", "2026-01-02", "2026-01-03"],
        close=[100.0, 101.0, 102.0],
        trades=trades,
        bucket="hold",
        direction="none",
        score_mode="test",
        cost_bps=0.0,
    )

    assert stitched["trade_ledger"] == []
    assert stitched["position_series"] == [0.0, 0.0, 0.0]
    assert stitched["metrics"]["n_trades"] == 0
    assert stitched["metrics"]["expected_return_net"] is None
    assert stitched["metrics"]["hit_rate"] is None
    assert stitched["metrics"]["sharpe"] is None
    assert abs(stitched["metrics"]["stock_expected_return"] - 0.03) < 1e-12


def test_batch_status_endpoints_filter_by_job_type():
    engine_job = SignalEngineBatchJob(
        id=uuid.uuid4(),
        symbol="AAA",
        horizon="weekly",
        variant="expanded",
        job_type="signal_engine",
        status="succeeded",
        created_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
    )
    backtest_job = SignalEngineBatchJob(
        id=uuid.uuid4(),
        symbol="AAA",
        horizon="weekly",
        variant="expanded",
        job_type="signal_backtest",
        status="running",
        created_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
    )
    client = TestClient(_app(_FakeDB({SignalEngineBatchJob: [engine_job, backtest_job]})))

    engine_response = client.get("/strategy/engine/batch-status?symbol=AAA&horizon=weekly&variant=expanded")
    backtest_response = client.get("/strategy/backtest-mc/batch-status?symbol=AAA&horizon=weekly&variant=expanded")

    assert engine_response.status_code == 200
    assert backtest_response.status_code == 200
    assert [job["job_type"] for job in engine_response.json()["jobs"]] == ["signal_engine"]
    assert [job["job_type"] for job in backtest_response.json()["jobs"]] == ["signal_backtest"]


def test_signal_backtest_results_include_accounting_trade_ledger():
    row = SignalBacktestRun(
        symbol="AAA",
        horizon="weekly",
        variant="expanded_ta_simple",
        source="engine",
        scope="global",
        scope_key="global",
        status="succeeded",
        window_start=dt.date(2026, 1, 1),
        window_end=dt.date(2026, 1, 6),
        n_bars=3,
        n_trades=1,
        dates_json=["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"],
        equity_json=[1.0, 1.0, 1.1, 1.1],
        close_series_json=[100.0, 101.0, 110.0, 109.0],
        position_series_json=[0.0, 1.0, 1.0, 0.0],
        trades_json=[
            {
                "open_date": "2026-01-02",
                "close_date": "2026-01-06",
                "open_price": 101.0,
                "close_price": 109.0,
                "pnl_return": 0.07,
            }
        ],
        total_return=0.1,
        cagr=0.1,
        sharpe=1.2,
        max_drawdown=-0.01,
        win_rate=1.0,
        cost_bps=0.0,
        slippage_bps=0.0,
        side_policy="long_short",
        cooldown_bars=0,
        mc_method="block_bootstrap",
        n_paths=10,
        computed_at=dt.datetime(2026, 1, 6, tzinfo=dt.timezone.utc),
        data_as_of=dt.date(2026, 1, 6),
    )
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 1, 6))
    score_rows = [
        SignalScoreHistory(
            date=dt.date(2026, 1, 2),
            symbol="AAA",
            source="engine:expanded_ta_simple",
            category="tendance",
            horizon="weekly",
            score_pct=20.0,
        ),
        SignalScoreHistory(
            date=dt.date(2026, 1, 2),
            symbol="AAA",
            source="engine:expanded_ta_simple",
            category="momentum",
            horizon="weekly",
            score_pct=40.0,
        ),
        SignalScoreHistory(
            date=dt.date(2026, 1, 6),
            symbol="AAA",
            source="engine:expanded_ta_simple",
            category="tendance",
            horizon="weekly",
            score_pct=50.0,
        ),
        SignalScoreHistory(
            date=dt.date(2026, 1, 6),
            symbol="AAA",
            source="engine:expanded_ta_simple",
            category="momentum",
            horizon="weekly",
            score_pct=70.0,
        ),
    ]
    client = TestClient(_app(_FakeDB({
        SignalBacktestRun: [row],
        MarketDataStore: [market_row],
        SignalScoreHistory: score_rows,
    })))

    response = client.get("/strategy/backtest-mc?symbol=AAA&horizon=weekly&variant=expanded_ta_simple")

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["side_policy"] == "long_short"
    assert result["cooldown_bars"] == 0
    assert result["trades"][0]["open_date"] == "2026-01-02"
    assert [entry["side"] for entry in result["trade_ledger"]] == ["ACHAT", "VENTE"]
    assert result["trade_ledger"][0]["cmp"] == 101.0
    assert result["trade_ledger"][0]["global_score_pct"] == 30.0
    assert result["trade_ledger"][0]["pnl_latent"] == 0.0
    assert result["trade_ledger"][1]["pnl_realise"] == 8.0
    assert result["trade_ledger"][1]["pnl_realise_cumule"] == 8.0
    assert result["trade_ledger"][1]["global_score_pct"] == 60.0
    assert result["score_series"] == [None, 30.0, None, 60.0]
    assert result["global_score_series"] == [None, 30.0, None, 60.0]


def test_signal_backtest_results_enqueues_and_returns_404_on_cache_miss(monkeypatch):
    # The read endpoint must never compute the heavy WFO + Monte Carlo in-band. On a
    # cache miss it enqueues the worker job and returns 404 immediately so the frontend
    # can poll via fetchSignalBacktestResultsWithBootstrap.
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 1, 6))
    fake_db = _FakeDB({SignalBacktestRun: [], MarketDataStore: [market_row]})
    calls: list[dict[str, object]] = []

    def _fake_enqueue(symbol, horizon, *, variant="expanded", triggered_by="manual", **_kwargs):
        calls.append(
            {
                "symbol": symbol,
                "horizon": horizon,
                "variant": variant,
                "triggered_by": triggered_by,
            }
        )
        return "job-1"

    fake_enqueue_module = types.ModuleType("services.worker.tasks.signal_enqueue")
    fake_enqueue_module.enqueue_signal_backtest_for_symbol = _fake_enqueue
    monkeypatch.setitem(sys.modules, "services.worker.tasks.signal_enqueue", fake_enqueue_module)
    client = TestClient(_app(fake_db))

    response = client.get("/strategy/backtest-mc?symbol=AAA&horizon=weekly&variant=expanded_ta_simple")

    assert response.status_code == 404
    assert "no backtest results" in response.json()["detail"].lower()
    assert calls == [
        {
            "symbol": "AAA",
            "horizon": "weekly",
            "variant": "expanded_ta_simple",
            "triggered_by": "api_read_miss",
        }
    ]


def test_signal_backtest_results_expanded_alias_enqueues_canonical_variant(monkeypatch):
    # The `expanded` alias must be resolved to its canonical storage variant before the
    # worker job is enqueued on a cache miss.
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 1, 6))
    fake_db = _FakeDB({SignalBacktestRun: [], MarketDataStore: [market_row]})
    enqueued_variants: list[str] = []

    def _fake_enqueue(symbol, horizon, *, variant="expanded", **_kwargs):
        enqueued_variants.append(variant)
        return "job-1"

    fake_enqueue_module = types.ModuleType("services.worker.tasks.signal_enqueue")
    fake_enqueue_module.enqueue_signal_backtest_for_symbol = _fake_enqueue
    monkeypatch.setitem(sys.modules, "services.worker.tasks.signal_enqueue", fake_enqueue_module)
    client = TestClient(_app(fake_db))

    response = client.get("/strategy/backtest-mc?symbol=AAA&horizon=weekly&variant=expanded")

    assert response.status_code == 404
    assert enqueued_variants == ["expanded_ta_simple"]


def test_signal_backtest_results_score_series_uses_row_scope():
    base_kwargs = dict(
        symbol="AAA",
        horizon="weekly",
        variant="expanded_ta_simple",
        source="engine",
        status="succeeded",
        window_start=dt.date(2026, 1, 1),
        window_end=dt.date(2026, 1, 6),
        n_bars=3,
        n_trades=0,
        dates_json=["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"],
        equity_json=[1.0, 1.0, 1.0, 1.0],
        close_series_json=[100.0, 101.0, 110.0, 109.0],
        position_series_json=[0.0, 0.0, 0.0, 0.0],
        trades_json=[],
        total_return=0.0,
        cagr=0.0,
        sharpe=0.0,
        max_drawdown=0.0,
        win_rate=0.0,
        cost_bps=0.0,
        slippage_bps=0.0,
        side_policy="long_short",
        cooldown_bars=0,
        mc_method="block_bootstrap",
        n_paths=10,
        computed_at=dt.datetime(2026, 1, 6, tzinfo=dt.timezone.utc),
        data_as_of=dt.date(2026, 1, 6),
    )
    rows = [
        SignalBacktestRun(scope="per_category", scope_key="tendance", **base_kwargs),
        SignalBacktestRun(scope="combination", scope_key="tendance+volume", **base_kwargs),
    ]
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 1, 6))
    score_rows = [
        SignalScoreHistory(date=dt.date(2026, 1, 2), symbol="AAA", source="engine:expanded_ta_simple", category="tendance", horizon="weekly", score_pct=20.0),
        SignalScoreHistory(date=dt.date(2026, 1, 2), symbol="AAA", source="engine:expanded_ta_simple", category="momentum", horizon="weekly", score_pct=40.0),
        SignalScoreHistory(date=dt.date(2026, 1, 2), symbol="AAA", source="engine:expanded_ta_simple", category="volume", horizon="weekly", score_pct=100.0),
        SignalScoreHistory(date=dt.date(2026, 1, 6), symbol="AAA", source="engine:expanded_ta_simple", category="tendance", horizon="weekly", score_pct=50.0),
        SignalScoreHistory(date=dt.date(2026, 1, 6), symbol="AAA", source="engine:expanded_ta_simple", category="momentum", horizon="weekly", score_pct=70.0),
        SignalScoreHistory(date=dt.date(2026, 1, 6), symbol="AAA", source="engine:expanded_ta_simple", category="volume", horizon="weekly", score_pct=80.0),
    ]
    client = TestClient(_app(_FakeDB({
        SignalBacktestRun: rows,
        MarketDataStore: [market_row],
        SignalScoreHistory: score_rows,
    })))

    response = client.get("/strategy/backtest-mc?symbol=AAA&horizon=weekly&variant=expanded_ta_simple")

    assert response.status_code == 200
    by_scope = {(row["scope"], row["scope_key"]): row for row in response.json()["results"]}
    per_category = by_scope[("per_category", "tendance")]
    combination = by_scope[("combination", "tendance+volume")]
    assert per_category["score_series"] == [None, 20.0, None, 50.0]
    assert per_category["global_score_series"] == [None, 20.0, None, 50.0]
    assert per_category["score_scope"] == "per_category"
    assert per_category["score_scope_key"] == "tendance"
    assert combination["score_series"] == [None, 60.0, None, 65.0]
    assert combination["global_score_series"] == [None, 60.0, None, 65.0]
    assert combination["score_scope"] == "combination"
    assert combination["score_scope_key"] == "tendance+volume"


def test_signal_backtest_results_accounting_trade_ledger_handles_short_positions():
    row = SignalBacktestRun(
        symbol="AAA",
        horizon="weekly",
        variant="expanded_ta_simple",
        source="engine",
        scope="global",
        scope_key="global",
        status="succeeded",
        window_start=dt.date(2026, 1, 1),
        window_end=dt.date(2026, 1, 6),
        n_bars=3,
        n_trades=1,
        dates_json=["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"],
        equity_json=[1.0, 1.0, 1.04, 1.03],
        close_series_json=[100.0, 99.0, 95.0, 96.0],
        position_series_json=[0.0, -1.0, -1.0, 0.0],
        trades_json=[
            {
                "open_date": "2026-01-02",
                "close_date": "2026-01-06",
                "open_price": 99.0,
                "close_price": 96.0,
                "pnl_return": 0.03,
                "direction": -1.0,
            }
        ],
        total_return=0.03,
        cagr=0.03,
        sharpe=1.1,
        max_drawdown=-0.01,
        win_rate=1.0,
        cost_bps=0.0,
        slippage_bps=0.0,
        side_policy="long_short",
        cooldown_bars=0,
        mc_method="block_bootstrap",
        n_paths=10,
        computed_at=dt.datetime(2026, 1, 6, tzinfo=dt.timezone.utc),
        data_as_of=dt.date(2026, 1, 6),
    )
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 1, 6))
    client = TestClient(_app(_FakeDB({SignalBacktestRun: [row], MarketDataStore: [market_row]})))

    response = client.get("/strategy/backtest-mc?symbol=AAA&horizon=weekly&variant=expanded_ta_simple")

    assert response.status_code == 200
    ledger = response.json()["results"][0]["trade_ledger"]
    assert [entry["side"] for entry in ledger] == ["VENTE", "ACHAT"]
    assert ledger[0]["position"] == -1.0
    assert ledger[0]["cmp"] == 99.0
    assert ledger[1]["pnl_realise"] == 3.0
    assert ledger[1]["pnl_latent"] == 3.0


def test_signal_backtest_results_selected_direction_filters_chart_and_ledger():
    row = SignalBacktestRun(
        symbol="AAA",
        horizon="weekly",
        variant="expanded_ta_simple",
        source="engine",
        scope="global",
        scope_key="global",
        status="succeeded",
        window_start=dt.date(2026, 1, 1),
        window_end=dt.date(2026, 1, 7),
        n_bars=4,
        n_trades=2,
        dates_json=["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"],
        equity_json=[1.0, 1.0, 0.95, 1.0, 1.02],
        close_series_json=[100.0, 110.0, 105.0, 100.0, 98.0],
        position_series_json=[0.0, 1.0, -1.0, -1.0, 0.0],
        trades_json=[
            {
                "open_date": "2026-01-02",
                "close_date": "2026-01-05",
                "open_price": 110.0,
                "close_price": 105.0,
                "pnl_return": -0.045,
                "direction": 1.0,
            },
            {
                "open_date": "2026-01-05",
                "close_date": "2026-01-07",
                "open_price": 105.0,
                "close_price": 98.0,
                "pnl_return": 0.067,
                "direction": -1.0,
            },
        ],
        total_return=0.02,
        cagr=0.02,
        sharpe=0.7,
        max_drawdown=0.05,
        win_rate=0.5,
        cost_bps=0.0,
        slippage_bps=0.0,
        side_policy="long_short",
        cooldown_bars=0,
        mc_method="block_bootstrap",
        n_paths=10,
        computed_at=dt.datetime(2026, 1, 7, tzinfo=dt.timezone.utc),
        data_as_of=dt.date(2026, 1, 7),
    )
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 1, 7))
    client = TestClient(_app(_FakeDB({SignalBacktestRun: [row], MarketDataStore: [market_row]})))

    response = client.get(
        "/strategy/backtest-mc?symbol=AAA&horizon=weekly&variant=expanded_ta_simple&selected_direction=short"
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["selected_direction"] == "short"
    assert result["position_series"] == [0.0, 0.0, -1.0, -1.0, 0.0]
    assert [entry["side"] for entry in result["trade_ledger"]] == ["VENTE", "ACHAT"]
    assert [entry["position"] for entry in result["trade_ledger"]] == [-1.0, 0.0]
    assert len(result["trades"]) == 1
    assert result["trades"][0]["direction"] == -1.0
    assert result["metrics"]["n_trades"] == 1


def test_trigger_all_signal_engine_enqueues_all_data_backed_symbols_and_horizons(monkeypatch):
    calls: list[tuple[str, str, str, str, str | None, str | None]] = []
    factor_jobs: list[tuple[str, bool]] = []

    def _fake_enqueue(
        symbol: str,
        horizon: str,
        variant: str = "expanded",
        triggered_by: str = "manual",
        batch_id: str | None = None,
        depends_on: str | None = None,
    ):
        calls.append((symbol, horizon, variant, triggered_by, batch_id, depends_on))
        return f"{symbol}-{horizon}-{variant}"

    class _FakeFactorQueue:
        def enqueue(self, _fn, symbol: str, auto_enqueue: bool, **_kwargs):
            factor_jobs.append((symbol, auto_enqueue))
            return types.SimpleNamespace(id=f"factor-{symbol}")

    fake_enqueue_module = types.ModuleType("services.worker.tasks.signal_enqueue")
    fake_enqueue_module.enqueue_signal_engine_for_symbol = _fake_enqueue
    monkeypatch.setitem(sys.modules, "services.worker.tasks.signal_enqueue", fake_enqueue_module)
    monkeypatch.setattr(
        "services.api.app.queue._get_macro_ingest_queue",
        lambda: _FakeFactorQueue(),
    )
    monkeypatch.setattr(
        "services.api.app.services.market_universe.list_signal_universe_symbols",
        lambda _db: ["AAA", "BBB"],
    )

    client = TestClient(_app(_FakeDB({})))

    response = client.post("/strategy/engine/trigger-all", json={})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["batch_id"], str)
    assert payload["batch_id"]
    assert payload["symbols"] == 2
    assert payload["horizons"] == ["weekly", "monthly", "quarterly"]
    assert payload["variants"] == [
        "legacy_ta_simple",
        "expanded_ta_simple",
        "legacy_factor_x_ta_simple",
        "expanded_factor_x_ta_simple",
        "legacy_ta_combo",
        "expanded_ta_combo",
        "legacy_factor_x_ta_combo",
        "expanded_factor_x_ta_combo",
    ]
    assert payload["total_jobs"] == 48
    assert len(calls) == 48
    assert payload["factor_selection_jobs"] == 2
    assert sorted(factor_jobs) == [("AAA", False), ("BBB", False)]
    assert all(triggered_by == "manual_global" for *_rest, triggered_by, _batch, _depends_on in calls)
    assert all(batch == payload["batch_id"] for *_rest, _triggered_by, batch, _depends_on in calls)
    assert all(
        depends_on is not None
        for *_rest, variant, _triggered_by, _batch, depends_on in calls
        if "factor_x_ta" in variant
    )


def test_signal_engine_result_rejects_legacy_horizon_query():
    client = TestClient(_app(_FakeDB({})))
    response = client.get("/strategy/engine/result?symbol=AAA&horizon=short&variant=legacy")
    assert response.status_code == 422


def test_signal_engine_global_batch_status_dedupes_latest_rows_and_counts_partial():
    now = dt.datetime(2026, 4, 22, tzinfo=dt.timezone.utc)
    batch_id = "batch-new"
    rows = [
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="AAA",
            horizon="weekly",
            variant="legacy",
            job_type="signal_engine",
            triggered_by="manual_global",
            batch_id=batch_id,
            status="pending",
            created_at=now - dt.timedelta(minutes=5),
        ),
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="AAA",
            horizon="weekly",
            variant="legacy",
            job_type="signal_engine",
            triggered_by="manual_global",
            batch_id=batch_id,
            status="succeeded",
            created_at=now,
        ),
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="BBB",
            horizon="monthly",
            variant="expanded",
            job_type="signal_engine",
            triggered_by="manual_global",
            batch_id=batch_id,
            status="partial",
            created_at=now - dt.timedelta(minutes=1),
        ),
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="CCC",
            horizon="quarterly",
            variant="expanded",
            job_type="signal_engine",
            triggered_by="manual_global",
            batch_id=batch_id,
            status="running",
            created_at=now - dt.timedelta(minutes=2),
        ),
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="ZZZ",
            horizon="weekly",
            variant="expanded",
            job_type="signal_engine",
            triggered_by="manual_global",
            batch_id="batch-old",
            status="failed",
            created_at=now - dt.timedelta(days=1),
        ),
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="DDD",
            horizon="weekly",
            variant="expanded",
            job_type="signal_backtest",
            triggered_by="manual_global",
            status="failed",
            created_at=now - dt.timedelta(minutes=3),
        ),
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="EEE",
            horizon="weekly",
            variant="expanded",
            job_type="signal_engine",
            triggered_by="manual",
            status="failed",
            created_at=now - dt.timedelta(minutes=3),
        ),
    ]
    client = TestClient(_app(_FakeDB({SignalEngineBatchJob: rows})))

    response = client.get("/strategy/engine/batch-status-global")

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch_id"] == batch_id
    assert payload["total"] == 3
    assert payload["succeeded"] == 1
    assert payload["partial"] == 1
    assert payload["running"] == 1
    assert payload["pending"] == 0
    assert payload["failed"] == 0
    assert payload["legacy_horizon_rows"] == 0
    assert payload["horizon_distribution"] == {"monthly": 1, "quarterly": 1, "weekly": 1}


def test_signal_engine_global_batch_status_filters_by_batch_id():
    now = dt.datetime(2026, 4, 22, tzinfo=dt.timezone.utc)
    rows = [
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="AAA",
            horizon="weekly",
            variant="legacy",
            job_type="signal_engine",
            triggered_by="manual_global",
            batch_id="batch-a",
            status="succeeded",
            created_at=now,
        ),
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="AAA",
            horizon="weekly",
            variant="legacy",
            job_type="signal_engine",
            triggered_by="manual_global",
            batch_id="batch-b",
            status="failed",
            created_at=now,
        ),
    ]
    client = TestClient(_app(_FakeDB({SignalEngineBatchJob: rows})))

    response = client.get("/strategy/engine/batch-status-global?batch_id=batch-a")

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch_id"] == "batch-a"
    assert payload["total"] == 1
    assert payload["succeeded"] == 1
    assert payload["failed"] == 0
    assert payload["legacy_horizon_rows"] == 0
