from __future__ import annotations

import os
import uuid

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects.postgresql import JSONB

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")

from services.api.app import models
from services.api.app.db import get_db
from services.api.app.routers import strategy as strategy_router
from services.api.app.strategy_v2 import (
    build_legacy_backtest_config_from_v2,
    build_strategy_review,
    migrate_strategy_config_v2,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover - test harness glue
    return "JSON"


@pytest.fixture()
def client_and_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    models.SavedStrategy.__table__.create(engine)

    app = FastAPI()
    app.include_router(strategy_router.router)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client, SessionLocal

    app.dependency_overrides.clear()
    engine.dispose()


def test_migrate_legacy_strategy_into_v2_stock_configs() -> None:
    migrated = migrate_strategy_config_v2(
        {
            "capital": {"total_capital_mad": 250_000},
            "universe": {"basket": ["IAM", "BCP"], "sort_by": "signal_score"},
            "allocation": {"hrp_lookback_bars": 60, "manual_overrides_by_symbol": {"IAM": 10_000}},
            "signal": {"enabled_families": ["sma", "macd"]},
            "risk": {
                "max_holding_bars": 45,
                "stop_atr_multiplier": 2.0,
                "take_profit_rr": 2.5,
                "time_stop_enabled": False,
            },
        },
        horizon="medium",
    )

    assert migrated["schema_version"] == 3
    assert migrated["app_domain"] == "four_pages"
    assert migrated["portfolio"]["universe"]["basket"] == ["IAM", "BCP"]
    assert migrated["stocks"]["IAM"]["signal_construction"]["families"]["sma"]["enabled"] is True
    assert migrated["stocks"]["IAM"]["signal_construction"]["families"]["rsi"]["enabled"] is False
    assert migrated["stocks"]["IAM"]["risk"]["stop_loss"]["atr_multiplier"]["value"] == 2.0
    assert migrated["stocks"]["IAM"]["risk"]["time_stop"]["enabled"] is False


def test_migrate_schema_v3_recovers_basket_from_stock_keys_when_missing() -> None:
    migrated = migrate_strategy_config_v2(
        {
            "schema_version": 3,
            "app_domain": "four_pages",
            "portfolio": {
                "total_capital_mad": 250_000,
                "universe": {},
                "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            },
            "stocks": {
                "IAM": {"strategy_type": "trend_following"},
                "BCP": {"strategy_type": "trend_following"},
            },
        },
        horizon="medium",
    )

    assert migrated["portfolio"]["universe"]["basket"] == ["IAM", "BCP"]
    assert set(migrated["stocks"].keys()) == {"IAM", "BCP"}


def test_strategy_review_counts_leaf_wfo_params_and_allows_fixed_rule_wfo_sizing() -> None:
    review = build_strategy_review(
        {
            "schema_version": 3,
            "app_domain": "four_pages",
            "portfolio": {
                "total_capital_mad": 100_000,
                "universe": {"basket": ["IAM"]},
                "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            },
            "stocks": {
                "IAM": {
                    "strategy_type": "trend_following",
                    "signal_construction": {
                        "families": {
                            "sma": {
                                "enabled": True,
                                "indicator_type": "price_vs_sma",
                                "params": {"window": {"mode": "wfo", "value": 20, "scan_min": 10, "scan_max": 40, "scan_step": 5}},
                            },
                            "rsi": {"enabled": False, "indicator_type": "rsi_wilder", "params": {"period": {"mode": "manual", "value": 14}}},
                            "macd": {"enabled": False, "indicator_type": "macd_histogram", "params": {}},
                            "obv": {"enabled": False, "indicator_type": "obv_deviation", "params": {}},
                        }
                    },
                    "entry_rules": [
                        {
                            "id": "e1",
                            "label": "Entree 1",
                            "config_option": "E",
                            "conditions": [
                                {"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 1.0}}
                            ],
                            "sizing": {
                                "mode": "wfo",
                                "manual_pct": 25,
                                "size_pct": {"mode": "wfo", "value": 25, "scan_min": 25, "scan_max": 75, "scan_step": 25},
                            },
                        }
                    ],
                    "exit_rules": [],
                    "risk": {
                        "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
                        "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
                        "cooldown_bars": {"mode": "manual", "value": 0},
                        "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
                        "trailing_stop_enabled": False,
                        "max_position_pct": 20,
                        "max_sector_pct": 40,
                    },
                }
            },
        },
        horizon="medium",
    )

    assert review["total_wfo_param_count"] == 2
    assert review["ready"] is True
    assert not any("Option E" in item for item in review["stocks"][0]["blocking_issues"])
    assert not any("entry_rules[0].sizing" in item for item in review["stocks"][0]["blocking_issues"])


def test_strategy_review_normalizes_legacy_entry_wfo_sizing_into_size_pct() -> None:
    review = build_strategy_review(
        {
            "schema_version": 3,
            "app_domain": "four_pages",
            "portfolio": {
                "total_capital_mad": 100_000,
                "universe": {"basket": ["IAM"]},
                "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            },
            "stocks": {
                "IAM": {
                    "strategy_type": "trend_following",
                    "signal_construction": {
                        "families": {
                            "sma": {"enabled": True, "indicator_type": "price_vs_sma", "params": {"window": {"mode": "manual", "value": 20}}},
                            "rsi": {"enabled": False, "indicator_type": "rsi_wilder", "params": {"period": {"mode": "manual", "value": 14}}},
                            "macd": {"enabled": False, "indicator_type": "macd_histogram", "params": {}},
                            "obv": {"enabled": False, "indicator_type": "obv_deviation", "params": {}},
                        }
                    },
                    "entry_rules": [
                        {
                            "id": "e1",
                            "label": "Entree 1",
                            "config_option": "A",
                            "conditions": [
                                {"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 1.0}}
                            ],
                            "sizing": {
                                "mode": "wfo",
                                "manual_pct": 25,
                                "kelly_modifier": {"mode": "wfo", "value": 50, "scan_min": 25, "scan_max": 100, "scan_step": 25},
                            },
                        }
                    ],
                    "exit_rules": [],
                    "risk": {
                        "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
                        "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
                        "cooldown_bars": {"mode": "manual", "value": 0},
                        "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
                        "trailing_stop_enabled": False,
                        "max_position_pct": 20,
                        "max_sector_pct": 40,
                    },
                }
            },
        },
        horizon="medium",
    )

    entry_sizing = review["canonical_config"]["stocks"]["IAM"]["entry_rules"][0]["sizing"]
    assert review["ready"] is True
    assert entry_sizing["mode"] == "wfo"
    assert entry_sizing["size_pct"]["value"] == 50
    assert entry_sizing["size_pct"]["scan_step"] == 25


def test_strategy_review_accepts_exit_kelly_wfo_mode() -> None:
    review = build_strategy_review(
        {
            "schema_version": 3,
            "app_domain": "four_pages",
            "portfolio": {
                "total_capital_mad": 100_000,
                "universe": {"basket": ["IAM"]},
                "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            },
            "stocks": {
                "IAM": {
                    "strategy_type": "trend_following",
                    "signal_construction": {
                        "families": {
                            "sma": {"enabled": True, "indicator_type": "price_vs_sma", "params": {"window": {"mode": "manual", "value": 20}}},
                            "rsi": {"enabled": False, "indicator_type": "rsi_wilder", "params": {"period": {"mode": "manual", "value": 14}}},
                            "macd": {"enabled": False, "indicator_type": "macd_histogram", "params": {}},
                            "obv": {"enabled": False, "indicator_type": "obv_deviation", "params": {}},
                        }
                    },
                    "entry_rules": [
                        {
                            "id": "e1",
                            "label": "Entree 1",
                            "config_option": "A",
                            "conditions": [
                                {"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 1.0}}
                            ],
                            "sizing": {"mode": "manual", "manual_pct": 25},
                        }
                    ],
                    "exit_rules": [
                        {
                            "id": "x1",
                            "label": "Sortie 1",
                            "config_option": "B",
                            "conditions": [
                                {"variable": "consensus_score", "operator": "<=", "threshold": {"mode": "manual", "value": -1.0}}
                            ],
                            "sizing": {
                                "mode": "kelly_wfo",
                                "manual_pct": 100,
                                "kelly_modifier": {"mode": "wfo", "value": 0.5, "scan_min": 0.25, "scan_max": 1.0, "scan_step": 0.25},
                            },
                        }
                    ],
                    "risk": {
                        "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
                        "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
                        "cooldown_bars": {"mode": "manual", "value": 0},
                        "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
                        "trailing_stop_enabled": False,
                        "max_position_pct": 20,
                        "max_sector_pct": 40,
                    },
                }
            },
        },
        horizon="medium",
    )

    exit_sizing = review["canonical_config"]["stocks"]["IAM"]["exit_rules"][0]["sizing"]
    assert review["ready"] is True
    assert review["total_wfo_param_count"] == 1
    assert exit_sizing["mode"] == "kelly_wfo"
    assert exit_sizing["kelly_modifier"]["mode"] == "wfo"


def test_strategy_review_does_not_raise_container_scan_step_error_for_rule_sizing() -> None:
    review = build_strategy_review(
        {
            "schema_version": 3,
            "app_domain": "four_pages",
            "portfolio": {
                "total_capital_mad": 100_000,
                "universe": {"basket": ["IAM"]},
                "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            },
            "stocks": {
                "IAM": {
                    "strategy_type": "trend_following",
                    "signal_construction": {
                        "families": {
                            "sma": {"enabled": True, "indicator_type": "price_vs_sma", "params": {"window": {"mode": "manual", "value": 20}}},
                            "rsi": {"enabled": False, "indicator_type": "rsi_wilder", "params": {"period": {"mode": "manual", "value": 14}}},
                            "macd": {"enabled": False, "indicator_type": "macd_histogram", "params": {}},
                            "obv": {"enabled": False, "indicator_type": "obv_deviation", "params": {}},
                        }
                    },
                    "entry_rules": [
                        {
                            "id": "e1",
                            "label": "Entree 1",
                            "config_option": "A",
                            "conditions": [
                                {"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 1.0}}
                            ],
                            "sizing": {"mode": "wfo", "manual_pct": 25},
                        }
                    ],
                    "exit_rules": [],
                    "risk": {
                        "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
                        "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
                        "cooldown_bars": {"mode": "manual", "value": 0},
                        "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
                        "trailing_stop_enabled": False,
                        "max_position_pct": 20,
                        "max_sector_pct": 40,
                    },
                }
            },
        },
        horizon="medium",
    )

    assert review["ready"] is True
    assert not any("entry_rules[0].sizing: scan_step must be positive" in item for item in review["stocks"][0]["blocking_issues"])


def test_strategy_review_blocks_malformed_integer_wfo_range() -> None:
    review = build_strategy_review(
        {
            "schema_version": 3,
            "app_domain": "four_pages",
            "portfolio": {
                "total_capital_mad": 100_000,
                "universe": {"basket": ["IAM"]},
                "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            },
            "stocks": {
                "IAM": {
                    "strategy_type": "trend_following",
                    "signal_construction": {
                        "families": {
                            "sma": {
                                "enabled": True,
                                "indicator_type": "price_vs_sma",
                                "params": {"window": {"mode": "wfo", "value": 20, "scan_min": 10.5, "scan_max": 40, "scan_step": 5}},
                            },
                            "rsi": {"enabled": False, "indicator_type": "rsi_wilder", "params": {"period": {"mode": "manual", "value": 14}}},
                            "macd": {"enabled": False, "indicator_type": "macd_histogram", "params": {}},
                            "obv": {"enabled": False, "indicator_type": "obv_deviation", "params": {}},
                        }
                    },
                    "entry_rules": [{"id": "e1", "label": "Entree 1", "config_option": "A", "conditions": [{"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 1.0}}], "sizing": {"mode": "manual", "manual_pct": 25}}],
                    "exit_rules": [{"id": "x1", "label": "Sortie 1", "config_option": "A", "conditions": [{"variable": "consensus_score", "operator": "<=", "threshold": {"mode": "manual", "value": -1.0}}], "sizing": {"mode": "manual", "manual_pct": 100}}],
                    "risk": {
                        "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
                        "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
                        "cooldown_bars": {"mode": "manual", "value": 0},
                        "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
                        "trailing_stop_enabled": False,
                        "max_position_pct": 20,
                        "max_sector_pct": 40,
                    },
                }
            },
        },
        horizon="medium",
    )

    assert review["ready"] is False
    assert any("integer-compatible" in item for item in review["stocks"][0]["blocking_issues"])
def test_handoff_endpoint_returns_manifest_for_saved_strategy(client_and_session) -> None:
    client, SessionLocal = client_and_session
    strategy_id = uuid.uuid4()

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json={
                    "capital": {"total_capital_mad": 500_000},
                    "universe": {"basket": ["IAM"]},
                    "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
                    "signal": {"enabled_families": ["sma", "rsi"]},
                    "risk": {
                        "max_holding_bars": 30,
                        "stop_atr_multiplier": 1.8,
                        "take_profit_rr": 1.7,
                        "time_stop_enabled": True,
                    },
                },
            )
        )
        db.commit()

    response = client.post(f"/strategy/plan/strategies/{strategy_id}/handoff")

    assert response.status_code == 200
    payload = response.json()
    assert payload["strategy_id"] == str(strategy_id)
    assert payload["schema_version"] == 3
    assert payload["app_domain"] == "four_pages"
    assert payload["portfolio"]["universe"]["basket"] == ["IAM"]
    assert "IAM" in payload["stocks"]
    assert payload["wfo_params"]["params"] == []


def test_build_chart_payload_emits_wfo_boundary_indicators_for_row_source() -> None:
    ohlcv = pd.DataFrame(
        {
            "Open": [100, 101, 102, 103, 104, 105],
            "High": [101, 102, 103, 104, 105, 106],
            "Low": [99, 100, 101, 102, 103, 104],
            "Close": [100.5, 101.5, 102.5, 103.5, 104.5, 105.5],
            "Volume": [100_000, 101_000, 102_000, 103_000, 104_000, 105_000],
        },
        index=pd.date_range("2024-01-01", periods=6, freq="D"),
    )
    frame = pd.DataFrame({"trend_score": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}, index=ohlcv.index)

    chart = strategy_router._build_chart_payload(
        None,
        stock_config={
            "signal_construction": {
                "families": {
                    "sma": {
                        "enabled": True,
                        "source_mode": "indicator_rows",
                        "rows": [
                            {
                                "id": "sma_row_1",
                                "enabled": True,
                                "score_key": "trend_score",
                                "label": "Trend Score",
                                "params": {"window": {"mode": "wfo", "value": 3, "scan_min": 2, "scan_max": 4, "scan_step": 1}},
                            }
                        ],
                    },
                    "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                    "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                    "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                }
            }
        },
        symbol="IAM",
        horizon="medium",
        timeframe="1D",
        cost_bps=0.0,
        cooldown_bars=0,
        ohlcv=ohlcv,
        frame=frame,
    )

    source = chart["sources"][0]
    assert source["source_mode_label"] == "WFO range"
    assert source["wfo_range_active"] is True
    assert source["wfo_param_names"] == ["window"]
    assert source["indicator"]["name"] == "SMA-3"
    assert source["wfo_start_indicator"]["name"] == "SMA-2"
    assert source["wfo_end_indicator"]["name"] == "SMA-4"


def test_build_chart_payload_changes_manual_indicator_when_row_param_changes() -> None:
    ohlcv = pd.DataFrame(
        {
            "Open": [100, 101, 102, 103, 104, 105],
            "High": [101, 102, 103, 104, 105, 106],
            "Low": [99, 100, 101, 102, 103, 104],
            "Close": [100.5, 101.5, 102.5, 103.5, 104.5, 105.5],
            "Volume": [100_000, 101_000, 102_000, 103_000, 104_000, 105_000],
        },
        index=pd.date_range("2024-01-01", periods=6, freq="D"),
    )
    frame = pd.DataFrame({"trend_score": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}, index=ohlcv.index)

    def build_source(window: int) -> dict:
        chart = strategy_router._build_chart_payload(
            None,
            stock_config={
                "signal_construction": {
                    "families": {
                        "sma": {
                            "enabled": True,
                            "source_mode": "indicator_rows",
                            "rows": [
                                {
                                    "id": "sma_row_1",
                                    "enabled": True,
                                    "score_key": "trend_score",
                                    "label": "Trend Score",
                                    "params": {"window": {"mode": "manual", "value": window}},
                                }
                            ],
                        },
                        "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                        "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                        "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                    }
                }
            },
            symbol="IAM",
            horizon="medium",
            timeframe="1D",
            cost_bps=0.0,
            cooldown_bars=0,
            ohlcv=ohlcv,
            frame=frame,
        )
        return chart["sources"][0]

    source_fast = build_source(3)
    source_slow = build_source(5)

    assert source_fast["source_mode_label"] == "Specific setup"
    assert source_slow["source_mode_label"] == "Specific setup"
    assert source_fast["indicator"]["name"] == "SMA-3"
    assert source_slow["indicator"]["name"] == "SMA-5"
    assert source_fast["indicator"]["plot_values"] != source_slow["indicator"]["plot_values"]


def test_build_chart_payload_emits_family_representatives_for_active_horizon(monkeypatch) -> None:
    ohlcv = pd.DataFrame(
        {
            "Open": [100, 101, 102, 103, 104, 105],
            "High": [101, 102, 103, 104, 105, 106],
            "Low": [99, 100, 101, 102, 103, 104],
            "Close": [100.5, 101.5, 102.5, 103.5, 104.5, 105.5],
            "Volume": [100_000, 101_000, 102_000, 103_000, 104_000, 105_000],
        },
        index=pd.date_range("2024-01-01", periods=6, freq="D"),
    )
    frame = pd.DataFrame({"trend_score": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}, index=ohlcv.index)
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        strategy_router,
        "_get_or_compute",
        lambda db, family, symbol, horizon, timeframe, cost_bps, cooldown_bars: seen.update({
            "family": family,
            "symbol": symbol,
            "horizon": horizon,
            "timeframe": timeframe,
        }) or object(),
    )
    monkeypatch.setattr(
        strategy_router,
        "_get_all_representative_indicators",
        lambda detail, close, volume: [
            {
                "label": "SMA 20",
                "weight": 0.72,
                "indicator": {"type": "overlay", "name": "SMA-20", "values": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]},
            },
            {
                "label": "SMA 50",
                "weight": 0.51,
                "indicator": {"type": "overlay", "name": "SMA-50", "values": [99.0, 100.0, 101.0, 102.0, 103.0, 104.0]},
            },
        ],
    )
    monkeypatch.setattr(
        strategy_router,
        "_get_top_representative_indicator",
        lambda detail, close, volume: {"type": "overlay", "name": "SMA-20", "values": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]},
    )

    chart = strategy_router._build_chart_payload(
        None,
        stock_config={
            "signal_construction": {
                "families": {
                    "sma": {"enabled": True, "source_mode": "family_ensemble", "rows": []},
                    "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                    "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                    "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                }
            }
        },
        symbol="IAM",
        horizon="short",
        timeframe="1D",
        cost_bps=0.0,
        cooldown_bars=0,
        ohlcv=ohlcv,
        frame=frame,
    )

    source = chart["sources"][0]
    assert seen == {"family": "sma", "symbol": "IAM", "horizon": "short", "timeframe": "1D"}
    assert source["source_kind"] == "family_ensemble"
    assert source["source_mode_label"] == "Family score"
    assert source["wfo_range_active"] is False
    assert source["wfo_start_indicator"] is None
    assert source["wfo_end_indicator"] is None
    assert [rep["label"] for rep in source["representatives"]] == ["SMA 20", "SMA 50"]
    assert source["indicator"]["name"] == "SMA-20"
    assert source["representatives"][0]["indicator"]["plot_kind"] == "line"
    assert source["representatives"][0]["indicator"]["plot_axis"] == "price"


@pytest.mark.parametrize(
    ("family", "score_key", "raw_indicator", "expected_plot_kind", "expected_plot_axis", "expected_zero_line"),
    [
        ("rsi", "oscillation_score", {"type": "secondary_yaxis", "name": "RSI-14", "values": [30.0, 40.0, 55.0], "thresholds": [30, 70]}, "line", "indicator", 50.0),
        ("macd", "momentum_score", {"type": "secondary_yaxis", "name": "MACD 12/26/9", "macd_line": [0.1, 0.2, 0.3], "signal_line": [0.05, 0.1, 0.15], "histogram": [0.05, 0.1, 0.15]}, "histogram", "indicator", 0.0),
        ("obv", "volume_score", {"type": "secondary_yaxis", "name": "OBV-21", "obv": [100.0, 105.0, 103.0], "ema_values": [99.0, 100.0, 101.0]}, "line", "indicator", 0.0),
    ],
)
def test_build_chart_payload_normalizes_family_representative_indicator_payloads(
    monkeypatch,
    family: str,
    score_key: str,
    raw_indicator: dict,
    expected_plot_kind: str,
    expected_plot_axis: str,
    expected_zero_line: float,
) -> None:
    ohlcv = pd.DataFrame(
        {
            "Open": [100, 101, 102],
            "High": [101, 102, 103],
            "Low": [99, 100, 101],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [100_000, 101_000, 102_000],
        },
        index=pd.date_range("2024-01-01", periods=3, freq="D"),
    )
    frame = pd.DataFrame({score_key: [1.0, 2.0, 3.0]}, index=ohlcv.index)

    monkeypatch.setattr(strategy_router, "_get_or_compute", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        strategy_router,
        "_get_all_representative_indicators",
        lambda detail, close, volume: [{"label": "Representative", "weight": 0.8, "indicator": raw_indicator}],
    )
    monkeypatch.setattr(strategy_router, "_get_top_representative_indicator", lambda detail, close, volume: raw_indicator)

    chart = strategy_router._build_chart_payload(
        None,
        stock_config={
            "signal_construction": {
                "families": {
                    "sma": {"enabled": family == "sma", "source_mode": "family_ensemble", "rows": []},
                    "rsi": {"enabled": family == "rsi", "source_mode": "family_ensemble", "rows": []},
                    "macd": {"enabled": family == "macd", "source_mode": "family_ensemble", "rows": []},
                    "obv": {"enabled": family == "obv", "source_mode": "family_ensemble", "rows": []},
                }
            }
        },
        symbol="IAM",
        horizon="medium",
        timeframe="1D",
        cost_bps=0.0,
        cooldown_bars=0,
        ohlcv=ohlcv,
        frame=frame,
    )

    indicator = chart["sources"][0]["representatives"][0]["indicator"]
    assert indicator["plot_kind"] == expected_plot_kind
    assert indicator["plot_axis"] == expected_plot_axis
    assert indicator["zero_line"] == expected_zero_line


def test_signal_construction_preview_endpoint_resolves_preview_stock_key(client_and_session, monkeypatch) -> None:
    client, _SessionLocal = client_and_session
    seen_modes: list[str] = []
    ohlcv = pd.DataFrame(
        {
            "Open": [100 + i for i in range(40)],
            "High": [101 + i for i in range(40)],
            "Low": [99 + i for i in range(40)],
            "Close": [100.5 + i for i in range(40)],
            "Volume": [100_000 + i * 1_000 for i in range(40)],
        },
        index=pd.date_range("2024-01-01", periods=40, freq="D"),
    )

    monkeypatch.setattr(strategy_router, "load_ohlcv_for_symbol", lambda db, symbol, timeframe: ohlcv)
    monkeypatch.setattr(strategy_router, "_truncate_for_horizon", lambda frame, horizon: frame)
    monkeypatch.setattr(strategy_router, "_clean_ohlcv", lambda frame: frame)
    monkeypatch.setattr(
        strategy_router,
        "compute_strategy_score_frame",
        lambda **kwargs: (
            seen_modes.append(str(kwargs.get("family_history_mode") or "static_current_reps")) or pd.DataFrame(
                {
                    "trend_score": np.linspace(10.0, 30.0, len(ohlcv)),
                    "consensus_score": np.linspace(10.0, 30.0, len(ohlcv)),
                },
                index=ohlcv.index,
                dtype="float64",
            )
        ),
    )
    monkeypatch.setattr(
        strategy_router,
        "_get_or_compute",
        lambda db, family, symbol, horizon, timeframe, cost_bps, cooldown_bars: type(
            "Detail",
            (),
            {"signal": type("Signal", (), {"family_score_pct": 12.3, "family_signal_label": "Haussier"})(), "all_summaries": [], "representative_ids": [], "fallback_variant_ids": []},
        )(),
    )
    monkeypatch.setattr(strategy_router, "_get_all_representative_indicators", lambda detail, close, volume: [])
    monkeypatch.setattr(strategy_router, "_get_top_representative_indicator", lambda detail, close, volume: None)

    response = client.post(
        "/strategy/plan/signal-construction/preview",
        json={
            "symbol": "IAM",
            "horizon": "short",
            "family_history_mode": "dynamic_point_in_time",
            "stock_config": {
                "strategy_type": "trend_following",
                "signal_construction": {
                    "families": {
                        "sma": {
                            "enabled": True,
                            "source_mode": "family_ensemble",
                            "rows": [
                                {
                                    "id": "sma_row_1",
                                    "enabled": True,
                                    "score_key": "trend_score",
                                    "label": "Trend Score",
                                    "params": {"window": {"mode": "manual", "value": 20}},
                                }
                            ],
                        },
                        "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                        "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                        "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                    }
                },
                "entry_rules": [],
                "exit_rules": [],
                "risk": {
                    "stop_loss": {"mode": "atr_based", "manual_pct": 0.02, "atr_multiplier": {"mode": "manual", "value": 1.5}},
                    "take_profit": {"mode": "rr_target", "manual_pct": 0.03, "rr_ratio": {"mode": "manual", "value": 1.5}},
                    "cooldown_bars": {"mode": "manual", "value": 0},
                    "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 10}},
                    "trailing_stop_enabled": False,
                    "max_position_pct": 20,
                    "max_sector_pct": 40,
                },
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["zone_chart"]["symbol"] == "IAM"
    assert payload["zone_chart"]["sources"][0]["score_key"] == "trend_score"
    assert seen_modes == ["dynamic_point_in_time"]


def test_build_legacy_backtest_config_keeps_manual_per_stock_overrides() -> None:
    config = build_legacy_backtest_config_from_v2(
        {
            "schema_version": 3,
            "app_domain": "four_pages",
            "portfolio": {
                "total_capital_mad": 100_000,
                "universe": {"basket": ["IAM", "BCP"]},
                "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            },
            "stocks": {
                "IAM": {
                    "strategy_type": "trend_following",
                    "signal_construction": {
                        "families": {
                            "sma": {"enabled": True, "indicator_type": "price_vs_sma", "params": {"window": {"mode": "manual", "value": 20}}},
                            "rsi": {"enabled": False, "indicator_type": "rsi_wilder", "params": {"period": {"mode": "manual", "value": 14}}},
                            "macd": {"enabled": False, "indicator_type": "macd_histogram", "params": {"fast": {"mode": "manual", "value": 12}, "slow": {"mode": "manual", "value": 26}, "signal": {"mode": "manual", "value": 9}}},
                            "obv": {"enabled": False, "indicator_type": "obv_deviation", "params": {"ema_period": {"mode": "manual", "value": 21}}},
                        }
                    },
                    "entry_rules": [],
                    "exit_rules": [],
                    "risk": {
                        "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
                        "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
                        "cooldown_bars": {"mode": "manual", "value": 0},
                        "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
                        "trailing_stop_enabled": False,
                        "max_position_pct": 20,
                        "max_sector_pct": 40,
                    },
                },
                "BCP": {
                    "strategy_type": "trend_following",
                    "signal_construction": {
                        "families": {
                            "sma": {"enabled": False, "indicator_type": "price_vs_sma", "params": {"window": {"mode": "manual", "value": 20}}},
                            "rsi": {"enabled": True, "indicator_type": "rsi_wilder", "params": {"period": {"mode": "manual", "value": 14}}},
                            "macd": {"enabled": False, "indicator_type": "macd_histogram", "params": {"fast": {"mode": "manual", "value": 12}, "slow": {"mode": "manual", "value": 26}, "signal": {"mode": "manual", "value": 9}}},
                            "obv": {"enabled": False, "indicator_type": "obv_deviation", "params": {"ema_period": {"mode": "manual", "value": 21}}},
                        }
                    },
                    "entry_rules": [],
                    "exit_rules": [],
                    "risk": {
                        "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 2.0}},
                        "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 2.1}},
                        "cooldown_bars": {"mode": "manual", "value": 0},
                        "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 45}},
                        "trailing_stop_enabled": False,
                        "max_position_pct": 20,
                        "max_sector_pct": 40,
                    },
                },
            },
        },
        horizon="medium",
    )

    assert config["signal"]["enabled_families"] == ["sma"]
    assert config["per_stock"]["IAM"]["signal"]["enabled_families"] == ["sma"]
    assert config["per_stock"]["BCP"]["signal"]["enabled_families"] == ["rsi"]
    assert config["per_stock"]["BCP"]["risk"]["take_profit_rr"] == 2.1


def test_strategy_review_resolves_horizon_specific_wfo_search_spaces() -> None:
    raw = {
        "schema_version": 3,
        "app_domain": "four_pages",
        "portfolio": {
            "total_capital_mad": 100_000,
            "universe": {"basket": ["IAM"]},
            "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
        },
        "stocks": {
            "IAM": {
                "strategy_type": "trend_following",
                "signal_construction": {
                    "families": {
                        "sma": {
                            "enabled": True,
                            "indicator_type": "price_vs_sma",
                            "params": {
                                "window": {
                                    "mode": "wfo",
                                    "value": 20,
                                    "scan_min": 10,
                                    "scan_max": 60,
                                    "scan_step": 5,
                                    "search_spaces_by_horizon": {
                                        "short": {"scan_min": 5, "scan_max": 20, "scan_step": 1},
                                        "medium": {"scan_min": 20, "scan_max": 60, "scan_step": 5},
                                        "long": {"scan_min": 50, "scan_max": 200, "scan_step": 10},
                                    },
                                }
                            },
                        },
                        "rsi": {"enabled": False, "indicator_type": "rsi_wilder", "params": {"period": {"mode": "manual", "value": 14}}},
                        "macd": {"enabled": False, "indicator_type": "macd_histogram", "params": {}},
                        "obv": {"enabled": False, "indicator_type": "obv_deviation", "params": {}},
                    }
                },
                "entry_rules": [{"id": "e1", "label": "Entree 1", "config_option": "A", "conditions": [{"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 1.0}}], "sizing": {"mode": "manual", "manual_pct": 25}}],
                "exit_rules": [{"id": "x1", "label": "Sortie 1", "config_option": "A", "conditions": [{"variable": "consensus_score", "operator": "<=", "threshold": {"mode": "manual", "value": -1.0}}], "sizing": {"mode": "manual", "manual_pct": 100}}],
                "risk": {
                    "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
                    "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
                    "cooldown_bars": {"mode": "manual", "value": 0},
                    "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
                    "trailing_stop_enabled": False,
                    "max_position_pct": 20,
                    "max_sector_pct": 40,
                },
            }
        },
    }

    short_review = build_strategy_review(raw, horizon="short")
    short_window = short_review["canonical_config"]["stocks"]["IAM"]["signal_construction"]["families"]["sma"]["rows"][0]["params"]["window"]
    assert short_window["scan_min"] == 5
    assert short_window["scan_max"] == 20
    assert short_window["scan_step"] == 1
    assert short_window["search_spaces_by_horizon"]["long"]["scan_step"] == 10

    long_review = build_strategy_review(raw, horizon="long")
    long_window = long_review["canonical_config"]["stocks"]["IAM"]["signal_construction"]["families"]["sma"]["rows"][0]["params"]["window"]
    assert long_window["scan_min"] == 50
    assert long_window["scan_max"] == 200
    assert long_window["scan_step"] == 10


def test_strategy_review_validates_only_selected_horizon_search_space() -> None:
    raw = {
        "schema_version": 3,
        "app_domain": "four_pages",
        "portfolio": {
            "total_capital_mad": 100_000,
            "universe": {"basket": ["IAM"]},
            "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
        },
        "stocks": {
            "IAM": {
                "strategy_type": "trend_following",
                "signal_construction": {
                    "families": {
                        "sma": {
                            "enabled": True,
                            "indicator_type": "price_vs_sma",
                            "params": {
                                "window": {
                                    "mode": "wfo",
                                    "value": 20,
                                    "scan_min": 10,
                                    "scan_max": 60,
                                    "scan_step": 5,
                                    "search_spaces_by_horizon": {
                                        "short": {"scan_min": 5, "scan_max": 20, "scan_step": 0},
                                        "medium": {"scan_min": 20, "scan_max": 60, "scan_step": 5},
                                        "long": {"scan_min": 50, "scan_max": 120, "scan_step": 10},
                                    },
                                }
                            },
                        },
                        "rsi": {"enabled": False, "indicator_type": "rsi_wilder", "params": {"period": {"mode": "manual", "value": 14}}},
                        "macd": {"enabled": False, "indicator_type": "macd_histogram", "params": {}},
                        "obv": {"enabled": False, "indicator_type": "obv_deviation", "params": {}},
                    }
                },
                "entry_rules": [{"id": "e1", "label": "Entree 1", "config_option": "A", "conditions": [{"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 1.0}}], "sizing": {"mode": "manual", "manual_pct": 25}}],
                "exit_rules": [{"id": "x1", "label": "Sortie 1", "config_option": "A", "conditions": [{"variable": "consensus_score", "operator": "<=", "threshold": {"mode": "manual", "value": -1.0}}], "sizing": {"mode": "manual", "manual_pct": 100}}],
                "risk": {
                    "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
                    "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
                    "cooldown_bars": {"mode": "manual", "value": 0},
                    "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
                    "trailing_stop_enabled": False,
                    "max_position_pct": 20,
                    "max_sector_pct": 40,
                },
            }
        },
    }

    short_review = build_strategy_review(raw, horizon="short")
    assert short_review["ready"] is False
    assert any("scan_step must be positive" in item for item in short_review["stocks"][0]["blocking_issues"])

    medium_review = build_strategy_review(raw, horizon="medium")
    assert medium_review["ready"] is True
    medium_window = medium_review["canonical_config"]["stocks"]["IAM"]["signal_construction"]["families"]["sma"]["rows"][0]["params"]["window"]
    assert medium_window["scan_min"] == 20
    assert medium_window["scan_max"] == 60
    assert medium_window["scan_step"] == 5


def test_strategy_review_blocks_rules_that_reference_removed_score_rows() -> None:
    review = build_strategy_review(
        {
            "schema_version": 3,
            "app_domain": "four_pages",
            "portfolio": {
                "total_capital_mad": 100_000,
                "universe": {"basket": ["IAM"]},
                "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            },
            "stocks": {
                "IAM": {
                    "strategy_type": "trend_following",
                    "signal_construction": {
                        "families": {
                            "sma": {
                                "enabled": True,
                                "source_mode": "indicator_rows",
                                "rows": [
                                    {
                                        "id": "sma_row_1",
                                        "enabled": True,
                                        "score_key": "trend_score",
                                        "label": "Trend Score",
                                        "params": {"window": {"mode": "manual", "value": 20}},
                                    }
                                ],
                            },
                            "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                            "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                            "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                        }
                    },
                    "entry_rules": [
                        {
                            "id": "e1",
                            "label": "Entree 1",
                            "config_option": "A",
                            "conditions": [
                                {
                                    "variable": "trend_score_2",
                                    "operator": ">=",
                                    "threshold": {"mode": "manual", "value": 1.0},
                                }
                            ],
                            "sizing": {"mode": "manual", "manual_pct": 25},
                        }
                    ],
                    "exit_rules": [],
                    "risk": {
                        "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
                        "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
                        "cooldown_bars": {"mode": "manual", "value": 0},
                        "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
                        "trailing_stop_enabled": False,
                        "max_position_pct": 20,
                        "max_sector_pct": 40,
                    },
                }
            },
        },
        horizon="medium",
    )

    assert review["ready"] is False
    assert any("trend_score_2" in item for item in review["stocks"][0]["blocking_issues"])


def test_strategy_review_allows_family_ensemble_in_wfo_mode() -> None:
    review = build_strategy_review(
        {
            "schema_version": 3,
            "app_domain": "four_pages",
            "portfolio": {
                "total_capital_mad": 100_000,
                "universe": {"basket": ["IAM"]},
                "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            },
            "stocks": {
                "IAM": {
                    "strategy_type": "trend_following",
                    "signal_construction": {
                        "families": {
                            "sma": {"enabled": True, "source_mode": "family_ensemble", "rows": []},
                            "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                            "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                            "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                        }
                    },
                    "entry_rules": [
                        {
                            "id": "e1",
                            "label": "Entree 1",
                            "config_option": "A",
                            "conditions": [
                                {"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 1.0}}
                            ],
                            "sizing": {"mode": "manual", "manual_pct": 25},
                        }
                    ],
                    "exit_rules": [],
                    "risk": {
                        "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
                        "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
                        "cooldown_bars": {"mode": "manual", "value": 0},
                        "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
                        "trailing_stop_enabled": False,
                        "max_position_pct": 20,
                        "max_sector_pct": 40,
                    },
                }
            },
        },
        horizon="medium",
        for_wfo=True,
    )

    assert review["ready"] is True
    assert not any("family_ensemble" in item for item in review["stocks"][0]["blocking_issues"])
