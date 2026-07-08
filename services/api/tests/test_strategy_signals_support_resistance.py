from __future__ import annotations

import os

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")

from services.api.app.db import get_db
from services.api.app.routers import strategy_signals

from core.quant_core.signal_engine.domain import EnsemblePipelineDetail, FamilyCombinedSignal, VariantRobustnessSummary


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(strategy_signals.router)

    def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    return app


def _ohlcv() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=160, freq="D")
    close = np.linspace(90.0, 110.0, len(dates))
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 2.0,
            "Low": close - 2.0,
            "Close": close,
            "Volume": np.linspace(100_000.0, 120_000.0, len(dates)),
        },
        index=dates,
    )


def _detail(family: str, score: float, representatives: list[dict] | None = None) -> EnsemblePipelineDetail:
    return EnsemblePipelineDetail(
        signal=FamilyCombinedSignal(
            family=family,
            symbol="AAA",
            horizon="medium",
            timeframe="1D",
            family_score_pct=score,
            family_signal_label="Haussier",
            tested_count=1,
            viable_count=1,
            competitive_count=1,
            representative_count=len(representatives or []),
            representatives=representatives or [],
            fallback_variants=[],
            score_explanation="ok",
            as_of="2024-06-08",
            latest_close=110.0,
        ),
        all_summaries=[],
        oos_windows={},
        survivor_ids=set(),
        representative_ids=set(),
    )


def _install_common_mocks(monkeypatch) -> None:
    monkeypatch.setattr(strategy_signals, "load_ohlcv_for_symbol", lambda *args, **kwargs: _ohlcv())

    def fake_get_or_compute(_db, family, *_args, **_kwargs):
        if family == "sma":
            return _detail(
                family,
                30.0,
                [
                    {
                        "variant_id": "sma_20",
                        "signal": 1.0,
                        "signal_label": "HAUSSIER",
                        "reliability_weight": 0.8,
                        "normalized_weight": 0.8,
                        "contribution": 0.8,
                        "current_close": 110.0,
                        "indicator_value": 98.0,
                        "explanation": "Close > SMA",
                        "params": {"window": 20},
                        "archetype": "price_vs_sma",
                        "selection_status": "selected",
                    }
                ],
            )
        if family == "ema":
            return _detail(family, 20.0, [])
        if family in {"ema_cross", "ichimoku", "psar"}:
            return _detail(family, 10.0, [])
        return _detail(family, 0.0, [])

    monkeypatch.setattr(strategy_signals, "_get_or_compute", fake_get_or_compute)
    monkeypatch.setattr(
        strategy_signals,
        "detect_swing_levels",
        lambda *args, **kwargs: {
            "nearest_support": 97.0,
            "nearest_resistance": 109.0,
            "supports": [{"price": 97.0, "bar_index": 10, "strength": 2}],
            "resistances": [{"price": 109.0, "bar_index": 12, "strength": 3}],
        },
    )
    monkeypatch.setattr(
        strategy_signals,
        "compute_pivot_points",
        lambda **kwargs: {"pp": 100.0, "s1": 103.0, "s2": 94.0, "r1": 101.0, "r2": 112.0},
    )
    monkeypatch.setattr(
        strategy_signals,
        "compute_levels_support_resistance",
        lambda *_args, **_kwargs: {
            "support": 99.0,
            "resistance": 105.0,
            "inputs": {"support_q20": 97.0, "resistance_q80": 104.0, "atr_ratio_20": 0.02},
            "explain": "quantile ok",
        },
    )


def test_summary_endpoint_does_not_compute_score_inversion(monkeypatch) -> None:
    app = _app()
    _install_common_mocks(monkeypatch)
    strategy_signals._SR_VARIANTS_CACHE.clear()
    called = {"count": 0}
    variants_called = {"count": 0}

    def fake_score_inversion(*_args, **_kwargs):
        called["count"] += 1
        return {}

    monkeypatch.setattr(strategy_signals, "compute_score_inversion_levels", fake_score_inversion)
    monkeypatch.setattr(
        strategy_signals,
        "_sr_get_or_compute_variants",
        lambda *args, **kwargs: variants_called.__setitem__("count", variants_called["count"] + 1),
    )

    client = TestClient(app)
    response = client.post(
        "/strategy/signal/support-resistance",
        json={"symbol": "AAA", "horizon": "medium", "timeframe": "1D"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "AAA"
    assert called["count"] == 0
    assert variants_called["count"] == 0
    assert payload["optimal_status"] == "pending"
    assert payload["final_support"] is None
    assert payload["preview_support"] is not None
    by_id = {row["id"]: row for row in payload["methods"]}
    assert by_id["score_inversion"]["status"] == "ignored"
    assert by_id["score_inversion"]["support"] is None
    assert by_id["score_inversion"]["resistance"] is None


def test_method_detail_invokes_score_inversion_only_for_score_method(monkeypatch) -> None:
    app = _app()
    _install_common_mocks(monkeypatch)
    strategy_signals._SR_INVERSION_CACHE.clear()
    called = {"count": 0}

    def fake_score_inversion(*_args, **_kwargs):
        called["count"] += 1
        return {
            "close_used": 110.0,
            "support_buy_trigger": 96.0,
            "resistance_sell_trigger": 111.0,
            "support_reference": 98.0,
            "thresholds": {"buy": 15.0, "sell": -15.0},
            "method": "rep_inversion_v2",
            "inputs": {"budget_exceeded": False, "eval_count": 88},
        }

    monkeypatch.setattr(strategy_signals, "compute_score_inversion_levels", fake_score_inversion)
    client = TestClient(app)

    response_score = client.post(
        "/strategy/signal/support-resistance/method-detail",
        json={"symbol": "AAA", "horizon": "medium", "timeframe": "1D", "method_id": "score_inversion"},
    )
    assert response_score.status_code == 200
    payload = response_score.json()
    assert payload["method_id"] == "score_inversion"
    assert payload["method"]["status"] == "available"
    assert payload["method"]["support"] == 96.0
    assert called["count"] == 1

    response_pivot = client.post(
        "/strategy/signal/support-resistance/method-detail",
        json={"symbol": "AAA", "horizon": "medium", "timeframe": "1D", "method_id": "pivot_points"},
    )
    assert response_pivot.status_code == 200
    assert response_pivot.json()["method_id"] == "pivot_points"
    assert called["count"] == 1


def test_score_inversion_method_detail_uses_cache(monkeypatch) -> None:
    app = _app()
    _install_common_mocks(monkeypatch)
    strategy_signals._SR_INVERSION_CACHE.clear()
    called = {"count": 0}

    def fake_score_inversion(*_args, **_kwargs):
        called["count"] += 1
        return {
            "close_used": 110.0,
            "support_buy_trigger": 96.0,
            "resistance_sell_trigger": 111.0,
            "support_reference": 98.0,
            "thresholds": {"buy": 15.0, "sell": -15.0},
            "method": "rep_inversion_v2",
            "inputs": {"budget_exceeded": False, "eval_count": 77},
        }

    monkeypatch.setattr(strategy_signals, "compute_score_inversion_levels", fake_score_inversion)
    client = TestClient(app)

    payload = {"symbol": "AAA", "horizon": "medium", "timeframe": "1D", "method_id": "score_inversion"}
    first = client.post("/strategy/signal/support-resistance/method-detail", json=payload)
    second = client.post("/strategy/signal/support-resistance/method-detail", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert called["count"] == 1
    assert second.json()["method"]["inputs"]["cached"] is True


def test_sr_variants_endpoint_returns_funnel_and_variant_grid(monkeypatch) -> None:
    app = _app()
    _install_common_mocks(monkeypatch)
    strategy_signals._SR_VARIANTS_CACHE.clear()

    client = TestClient(app)
    response = client.post(
        "/strategy/signal/support-resistance/variants",
        json={"symbol": "AAA", "horizon": "medium", "timeframe": "1D"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "AAA"
    assert payload["funnel"]["tested"] >= 1
    assert payload["funnel"]["representative"] == payload["funnel"]["competitive"]
    assert isinstance(payload["all_variants"], list)
    assert payload["all_variants"]
    first = payload["all_variants"][0]
    assert str(first["variant_id"]).startswith("sr:")
    assert "__" in str(first["variant_id"])
    assert "score_inversion" not in str(first["variant_id"])


def test_sr_variants_best_pair_defines_final_levels_and_summary_cache(monkeypatch) -> None:
    app = _app()
    _install_common_mocks(monkeypatch)
    strategy_signals._SR_VARIANTS_CACHE.clear()

    def fake_direct_summary(variant, **_kwargs):
        params = variant.params
        score = (
            0.95
            if params.get("support_method_id") == "quantile_extrema_atr"
            and params.get("support_line_id") == "S1"
            and params.get("resistance_method_id") == "pivot_points"
            and params.get("resistance_line_id") == "R1"
            else 0.5
        )
        summary = VariantRobustnessSummary(
            variant=variant,
            n_oos_windows=1,
            n_valid_windows=1,
            mean_sharpe=1.0,
            std_sharpe=0.0,
            median_sharpe=1.0,
            fraction_positive_windows=1.0,
            mean_max_drawdown=0.05,
            reliability_score=score,
            is_viable=True,
            sharpe_score=1.0,
            stability_score=1.0,
            consistency_score=1.0,
            drawdown_score=1.0,
            cagr=0.12,
            total_pnl=1200.0,
        )
        return summary, {
            "sr_objective_score": score,
            "net_return_score": score,
            "consistency_score": 1.0,
            "drawdown_score": 1.0,
            "trade_activity_score": 1.0,
            "n_trades": 3.0,
            "total_return": 0.12,
            "cagr": 0.12,
            "max_drawdown": 0.05,
            "win_rate": 1.0,
            "total_pnl_realise_1u": 12.0,
        }

    monkeypatch.setattr(strategy_signals, "_sr_direct_objective_summary", fake_direct_summary)
    client = TestClient(app)

    variants_response = client.post(
        "/strategy/signal/support-resistance/variants",
        json={"symbol": "AAA", "horizon": "medium", "timeframe": "1D"},
    )
    assert variants_response.status_code == 200
    variants_payload = variants_response.json()
    assert variants_payload["best_variant_id"] == "sr:quantile_extrema_atr:S1__pivot_points:R1"
    assert variants_payload["final_support"] == 99.0
    assert variants_payload["final_resistance"] > variants_payload["final_support"]
    assert variants_payload["selected_support_method_id"] == "quantile_extrema_atr"
    assert variants_payload["selected_resistance_method_id"] == "pivot_points"
    assert variants_payload["selected_support_line_id"] == "S1"
    assert variants_payload["selected_resistance_line_id"] == "R1"

    summary_response = client.post(
        "/strategy/signal/support-resistance",
        json={"symbol": "AAA", "horizon": "medium", "timeframe": "1D"},
    )
    assert summary_response.status_code == 200
    summary_payload = summary_response.json()
    assert summary_payload["optimal_status"] == "ready"
    assert summary_payload["optimal_variant_id"] == "sr:quantile_extrema_atr:S1__pivot_points:R1"
    assert summary_payload["final_support"] == 99.0
    assert summary_payload["preview_support"] is not None


def test_sr_variant_detail_and_backtest_endpoints_return_stable_payload(monkeypatch) -> None:
    app = _app()
    _install_common_mocks(monkeypatch)
    strategy_signals._SR_VARIANTS_CACHE.clear()
    strategy_signals._SR_VARIANT_BACKTEST_CACHE.clear()

    client = TestClient(app)
    variants_response = client.post(
        "/strategy/signal/support-resistance/variants",
        json={"symbol": "AAA", "horizon": "medium", "timeframe": "1D"},
    )
    assert variants_response.status_code == 200
    variants_payload = variants_response.json()
    assert variants_payload["all_variants"]
    variant_id = str(variants_payload["all_variants"][0]["variant_id"])

    detail_response = client.post(
        "/strategy/signal/support-resistance/variant-detail",
        json={"symbol": "AAA", "horizon": "medium", "timeframe": "1D", "variant_id": variant_id},
    )
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["variant_id"] == variant_id
    assert "funnel" in detail_payload
    assert "all_variants" in detail_payload
    assert "robustness" in detail_payload

    backtest_response = client.post(
        "/strategy/signal/support-resistance/variant-backtest",
        json={"symbol": "AAA", "horizon": "medium", "timeframe": "1D", "variant_id": variant_id},
    )
    assert backtest_response.status_code == 200
    backtest_payload = backtest_response.json()
    assert backtest_payload["variant_id"] == variant_id
    assert "metrics" in backtest_payload
    assert "plots" in backtest_payload
    assert "price_indicator_signal" in backtest_payload["plots"]


def test_sr_wfo_endpoint_returns_insufficient_history_for_short_fixture(monkeypatch) -> None:
    app = _app()
    _install_common_mocks(monkeypatch)
    strategy_signals._SR_WFO_CACHE.clear()

    client = TestClient(app)
    response = client.post(
        "/strategy/signal/support-resistance/wfo",
        json={"symbol": "AAA", "horizon": "medium", "timeframe": "1D"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "AAA"
    assert payload["family"] == "support_resistance_wfo"
    # the 160-bar fixture is shorter than the monthly train+test requirement,
    # so the WFO procedure must degrade gracefully rather than error out.
    assert payload["wfo"]["status"] == "insufficient_history"
    assert payload["wfo"]["windows"] == []
    assert payload["wfo"]["decision"] == "no_edge"
    assert "line_touch_stats" in payload


def test_sr_overlay_enters_on_support_and_exits_on_resistance() -> None:
    close = np.array([100.0, 101.0, 104.0, 103.0], dtype=float)
    high = np.array([101.0, 102.0, 106.0, 104.0], dtype=float)
    low = np.array([99.0, 98.0, 102.0, 101.0], dtype=float)
    baseline_position = np.array([0.0, 1.0, 1.0, 0.0], dtype=float)
    support = np.array([np.nan, 99.0, 100.0, np.nan], dtype=float)
    resistance = np.array([np.nan, 105.0, 105.0, np.nan], dtype=float)

    result = strategy_signals._sr_simulate_signal_overlay(
        close=close,
        high=high,
        low=low,
        dates=["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
        baseline_position=baseline_position,
        support_series=support,
        resistance_series=resistance,
        cost_bps=0.0,
        slippage_bps=0.0,
        cooldown_bars=0,
        allow_short=False,
    )

    assert result["metrics"]["n_trades"] == 1
    assert result["trades"][0]["open_price"] == 99.0
    assert result["trades"][0]["close_price"] == 105.0
    assert result["trades"][0]["exit_reason"] == "resistance"
    assert result["metrics"]["total_return"] > 0.06


def test_sr_overlay_mirrors_short_when_allowed() -> None:
    close = np.array([100.0, 99.0, 95.0, 96.0], dtype=float)
    high = np.array([101.0, 103.0, 97.0, 97.0], dtype=float)
    low = np.array([99.0, 98.0, 94.0, 95.0], dtype=float)
    baseline_position = np.array([0.0, -1.0, -1.0, 0.0], dtype=float)
    support = np.array([np.nan, 96.0, 96.0, np.nan], dtype=float)
    resistance = np.array([np.nan, 102.0, 101.0, np.nan], dtype=float)

    result = strategy_signals._sr_simulate_signal_overlay(
        close=close,
        high=high,
        low=low,
        dates=["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
        baseline_position=baseline_position,
        support_series=support,
        resistance_series=resistance,
        cost_bps=0.0,
        slippage_bps=0.0,
        cooldown_bars=0,
        allow_short=True,
    )

    assert result["metrics"]["n_trades"] == 1
    assert result["trades"][0]["direction"] == -1.0
    assert result["trades"][0]["open_price"] == 102.0
    assert result["trades"][0]["close_price"] == 96.0
    assert result["trades"][0]["exit_reason"] == "support"
    assert result["metrics"]["total_return"] > 0.06
