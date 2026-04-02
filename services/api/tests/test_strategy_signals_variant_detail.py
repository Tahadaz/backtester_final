from __future__ import annotations

import os

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")

from services.api.app.db import get_db
from services.api.app.routers import strategy_signals

from core.quant_core.signal_engine.domain import (
    EnsemblePipelineDetail,
    FamilyCombinedSignal,
    VariantDef,
    VariantRobustnessSummary,
)


def _summary(variant_id: str, reliability_score: float) -> VariantRobustnessSummary:
    return VariantRobustnessSummary(
        variant=VariantDef(
            variant_id=variant_id,
            family="rsi",
            archetype="rsi_level",
            params={"period": 14, "oversold": 30, "overbought": 70},
            description=f"Variant {variant_id}",
        ),
        n_oos_windows=0,
        n_valid_windows=0,
        mean_sharpe=0.0,
        std_sharpe=0.0,
        median_sharpe=0.0,
        fraction_positive_windows=0.0,
        mean_max_drawdown=0.0,
        reliability_score=reliability_score,
        is_viable=True,
    )


def test_variant_detail_uses_rsi_alternation_for_header_and_table(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(strategy_signals.router)

    def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db

    summaries = [
        _summary("rsi_repeat_sell", 0.8),
        _summary("rsi_repeat_buy", 0.5),
    ]
    detail = EnsemblePipelineDetail(
        signal=FamilyCombinedSignal(
            family="rsi",
            symbol="AAA",
            horizon="medium",
            timeframe="1D",
            family_score_pct=-25.0,
            family_signal_label="Surachete",
            tested_count=2,
            viable_count=2,
            competitive_count=2,
            representative_count=1,
            representatives=[
                {
                    "variant_id": "rsi_repeat_sell",
                    "signal": -1.0,
                    "signal_label": "SURACHETE",
                    "selection_status": "selected",
                }
            ],
        ),
        all_summaries=summaries,
        oos_windows={summary.variant.variant_id: [] for summary in summaries},
        survivor_ids={"rsi_repeat_sell"},
        representative_ids={"rsi_repeat_sell"},
        current_signal_labels={
            "rsi_repeat_sell": "SURACHETE",
            "rsi_repeat_buy": "SURVENDU",
        },
    )

    bars = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0, 103.0],
            "High": [100.0, 101.0, 102.0, 103.0],
            "Low": [100.0, 101.0, 102.0, 103.0],
            "Close": [100.0, 101.0, 102.0, 103.0],
            "Volume": [10.0, 10.0, 10.0, 10.0],
        },
        index=pd.date_range("2024-01-01", periods=4, freq="D"),
    )

    def fake_latest_rsi_variant_signal(close, variant, *, cooldown_bars=0):
        mapping = {
            "rsi_repeat_sell": (0.0, "NORMAL"),
            "rsi_repeat_buy": (0.0, "NORMAL"),
        }
        return mapping[variant.variant_id]

    monkeypatch.setattr(strategy_signals, "_family_for_variant", lambda *args, **kwargs: "rsi")
    monkeypatch.setattr(strategy_signals, "_get_or_compute", lambda *args, **kwargs: detail)
    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: bars)
    monkeypatch.setattr(strategy_signals, "latest_rsi_variant_signal", fake_latest_rsi_variant_signal)

    with TestClient(app) as client:
        response = client.post(
            "/strategy/signal/variant-detail",
            json={
                "symbol": "AAA",
                "horizon": "medium",
                "variant_id": "rsi_repeat_sell",
                "cost_bps": 10.0,
                "cooldown_bars": 0,
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()

    assert payload["signal"] == 0.0
    assert payload["signal_label"] == "NORMAL"
    assert payload["selection_status"] == "selected"

    variants = {row["variant_id"]: row for row in payload["all_variants"]}
    assert variants["rsi_repeat_sell"]["signal_value"] == 0.0
    assert variants["rsi_repeat_sell"]["signal_label"] == "NORMAL"
    assert "total_pnl_realise_1u" in variants["rsi_repeat_sell"]
    assert variants["rsi_repeat_buy"]["signal_value"] == 0.0
    assert variants["rsi_repeat_buy"]["signal_label"] == "NORMAL"
    assert "total_pnl_realise_1u" in variants["rsi_repeat_buy"]
    assert payload["robustness"]["total_pnl_realise_1u"] == 0.0


def test_variant_backtest_returns_cumulative_return_audit_field(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(strategy_signals.router)

    def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db

    summary = _summary("rsi_audit", 0.8)
    detail = EnsemblePipelineDetail(
        signal=FamilyCombinedSignal(
            family="rsi",
            symbol="AAA",
            horizon="medium",
            timeframe="1D",
            family_score_pct=12.5,
            family_signal_label="Survendu",
            tested_count=1,
            viable_count=1,
            competitive_count=1,
            representative_count=1,
            representatives=[
                {
                    "variant_id": "rsi_audit",
                    "signal": 1.0,
                    "signal_label": "SURVENDU",
                    "selection_status": "selected",
                }
            ],
        ),
        all_summaries=[summary],
        oos_windows={"rsi_audit": []},
        survivor_ids={"rsi_audit"},
        representative_ids={"rsi_audit"},
        current_signal_labels={"rsi_audit": "SURVENDU"},
    )

    bars = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0, 103.0],
            "High": [100.0, 101.0, 102.0, 103.0],
            "Low": [100.0, 101.0, 102.0, 103.0],
            "Close": [100.0, 101.0, 102.0, 103.0],
            "Volume": [10.0, 10.0, 10.0, 10.0],
        },
        index=pd.date_range("2024-01-01", periods=4, freq="D"),
    )

    monkeypatch.setattr(strategy_signals, "_family_for_variant", lambda *args, **kwargs: "rsi")
    monkeypatch.setattr(strategy_signals, "_get_or_compute", lambda *args, **kwargs: detail)
    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: bars)
    monkeypatch.setattr(
        strategy_signals,
        "compute_variant_detail",
        lambda *args, **kwargs: {
            "metrics": {"total_pnl": 1250.0},
            "trade_performance": [],
            "trade_ledger": [
                {
                    "date": "2024-01-02",
                    "side": "ACHAT",
                    "open_t_plus_1": 101.0,
                    "cmp": 101.0,
                    "position": 1.0,
                    "return_cumule": 0.0125,
                    "pnl_realise_cumule": 0.0,
                }
            ],
            "plots": {},
            "per_window": [
                {
                    "window_index": 0,
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-04",
                    "sharpe": 1.0,
                    "pnl": 1250.0,
                    "pnl_100k": 1250.0,
                    "n_trades": 1,
                    "is_valid": True,
                    "plot": {"data": [], "layout": {}},
                    "equity_plot": {"data": [], "layout": {}},
                    "drawdown_plot": {"data": [], "layout": {}},
                    "trades": [
                        {
                            "date": "2024-01-02",
                            "side": "ACHAT",
                            "open_t_plus_1": 101.0,
                            "cmp": 101.0,
                            "position": 1.0,
                            "return_cumule": 0.0125,
                            "pnl_realise_cumule": 0.0,
                        }
                    ],
                }
            ],
        },
    )

    with TestClient(app) as client:
        response = client.post(
            "/strategy/signal/variant-backtest",
            json={
                "symbol": "AAA",
                "horizon": "medium",
                "variant_id": "rsi_audit",
                "cost_bps": 10.0,
                "cooldown_bars": 0,
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["trade_ledger"][0]["return_cumule"] == 0.0125
    assert payload["trade_ledger"][0]["pnl_realise_cumule"] == 0.0
    assert payload["per_window"][0]["trades"][0]["return_cumule"] == 0.0125
    assert payload["per_window"][0]["trades"][0]["pnl_realise_cumule"] == 0.0
