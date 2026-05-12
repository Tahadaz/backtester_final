from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.db import get_db
from services.api.app.routers import dashboard_data
from services.api.app.schemas.dashboard_portfolio import DashboardDailyBlotterRequest, DashboardPortfolioTicketRequest
from services.api.app.services import dashboard_portfolio as svc


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self._rows)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(dashboard_data.router)

    def override_get_db():
        yield object()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _bars() -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=80, freq="B")
    close = pd.Series([100 + i * 0.2 for i in range(len(idx))], index=idx)
    return pd.DataFrame({
        "Open": close,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": 10_000,
    }, index=idx)


def _edge(symbol: str, direction: str = "long", proven: bool = True, *, p_win: float = 0.60):
    expectancy = SimpleNamespace(p_win=p_win, avg_win=0.04, avg_loss=-0.02)
    return SimpleNamespace(
        symbol=symbol,
        direction=direction,
        bucket="buy" if direction == "long" else "strong_sell",
        proven_edge_net=proven,
        action_expected_return_net=0.03,
        stock_expected_return=0.03 if direction == "long" else -0.03,
        expectancy_net=expectancy,
    )


def test_dashboard_portfolio_ticket_sizes_manual_basket(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "build_dashboard_payload",
        lambda *_args, **_kwargs: {
            "stocks": [
                {"symbol": "AAA", "display_name": "Alpha", "sector": "Banks", "adv": 10_000, "scores": {"signal_engine": {"expanded_aggregate_score_pct": 75}}},
                {"symbol": "BBB", "display_name": "Beta", "sector": "Mines", "adv": 10_000, "scores": {"signal_engine": {"expanded_aggregate_score_pct": -80}}},
            ]
        },
    )
    monkeypatch.setattr(svc, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: _bars())
    monkeypatch.setattr(svc, "compute_hrp_weights", lambda *_args, **_kwargs: {"AAA": 0.6, "BBB": 0.4})
    monkeypatch.setattr(
        svc,
        "_edge_for_symbol",
        lambda _db, *, symbol, **_kwargs: _edge(symbol, direction="short" if symbol == "BBB" else "long"),
    )
    monkeypatch.setattr(
        svc,
        "compute_execution_plan",
        lambda **kwargs: {
            "direction": "short" if kwargs["consensus"] < 0 else "long",
            "status": "entry_zone",
            "entry_price": 100.0,
            "entry_zone_low": 99.0,
            "entry_zone_high": 101.0,
            "stop_loss": 95.0 if kwargs["consensus"] > 0 else 105.0,
            "target_1": 110.0 if kwargs["consensus"] > 0 else 90.0,
            "target_2": None,
            "rr_ratio": 2.0,
            "atr_14": 2.0,
            "explain": "ok",
        },
    )

    db = _FakeDB([
        SimpleNamespace(symbol="AAA", display_name="Alpha", sector="Banks"),
        SimpleNamespace(symbol="BBB", display_name="Beta", sector="Mines"),
    ])
    response = svc.build_dashboard_portfolio_ticket(
        db,
        DashboardPortfolioTicketRequest(
            symbols=["AAA", "BBB"],
            horizon="monthly",
            total_capital_mad=1_000_000,
            cash_buffer_pct=10,
            max_position_pct=20,
            side_policy="long_short",
            require_proven_edge=True,
        ),
        cost_bps=33.0,
    )

    assert response.summary.selected_count == 2
    assert response.summary.tradable_count == 2
    assert response.summary.deployable_capital_mad == 900_000
    rows = {row.symbol: row for row in response.rows}
    assert rows["AAA"].action == "buy"
    assert rows["BBB"].action == "sell_short"
    assert rows["AAA"].size_mad > 0
    assert rows["BBB"].size_mad > 0
    assert rows["BBB"].stock_expected_return == -0.03
    assert rows["BBB"].action_expected_return_net == 0.03


def test_dashboard_portfolio_ticket_blocks_unproven_edges(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "build_dashboard_payload",
        lambda *_args, **_kwargs: {
            "stocks": [
                {"symbol": "AAA", "display_name": "Alpha", "sector": "Banks", "adv": 10_000, "scores": {"signal_engine": {"expanded_aggregate_score_pct": 75}}},
            ]
        },
    )
    monkeypatch.setattr(svc, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: _bars())
    monkeypatch.setattr(svc, "compute_hrp_weights", lambda *_args, **_kwargs: {"AAA": 1.0})
    monkeypatch.setattr(svc, "_edge_for_symbol", lambda *_args, **_kwargs: _edge("AAA", proven=False))
    monkeypatch.setattr(
        svc,
        "compute_execution_plan",
        lambda **_kwargs: {
            "direction": "long",
            "status": "entry_zone",
            "entry_price": 100.0,
            "entry_zone_low": 99.0,
            "entry_zone_high": 101.0,
            "stop_loss": 95.0,
            "target_1": 110.0,
            "target_2": None,
            "rr_ratio": 2.0,
            "atr_14": 2.0,
            "explain": "ok",
        },
    )

    response = svc.build_dashboard_portfolio_ticket(
        _FakeDB([SimpleNamespace(symbol="AAA", display_name="Alpha", sector="Banks")]),
        DashboardPortfolioTicketRequest(symbols=["AAA"], require_proven_edge=True),
        cost_bps=33.0,
    )

    assert response.summary.tradable_count == 0
    assert response.summary.allocated_count == 0
    assert response.rows[0].shares == 0
    assert "edge_not_proven" in response.rows[0].warnings
    assert response.rows[0].allocation_reason == "strict_edge_gate"


def test_dashboard_portfolio_ticket_allocates_unproven_edge_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "build_dashboard_payload",
        lambda *_args, **_kwargs: {
            "stocks": [
                {"symbol": "AAA", "display_name": "Alpha", "sector": "Banks", "adv": 10_000, "scores": {"signal_engine": {"expanded_aggregate_score_pct": 75}}},
            ]
        },
    )
    monkeypatch.setattr(svc, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: _bars())
    monkeypatch.setattr(svc, "compute_hrp_weights", lambda *_args, **_kwargs: {"AAA": 1.0})
    monkeypatch.setattr(svc, "_edge_for_symbol", lambda *_args, **_kwargs: _edge("AAA", proven=False))
    monkeypatch.setattr(
        svc,
        "compute_execution_plan",
        lambda **_kwargs: {
            "direction": "long",
            "status": "entry_zone",
            "entry_price": 100.0,
            "entry_zone_low": 99.0,
            "entry_zone_high": 101.0,
            "stop_loss": 95.0,
            "target_1": 110.0,
            "target_2": None,
            "rr_ratio": 2.0,
            "atr_14": 2.0,
            "explain": "ok",
        },
    )

    response = svc.build_dashboard_portfolio_ticket(
        _FakeDB([SimpleNamespace(symbol="AAA", display_name="Alpha", sector="Banks")]),
        DashboardPortfolioTicketRequest(symbols=["AAA"]),
        cost_bps=33.0,
    )

    assert response.summary.allocated_count == 1
    assert response.summary.tradable_count == 1
    assert response.rows[0].shares > 0
    assert response.rows[0].allocation_eligible is True
    assert response.rows[0].allocation_reason == "entry_zone"
    assert "edge_not_proven" in response.rows[0].warnings


def test_dashboard_portfolio_ticket_plans_weight_when_waiting_for_entry(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "build_dashboard_payload",
        lambda *_args, **_kwargs: {
            "stocks": [
                {"symbol": "AAA", "display_name": "Alpha", "sector": "Banks", "adv": 10_000, "scores": {"signal_engine": {"expanded_aggregate_score_pct": 75}}},
            ]
        },
    )
    monkeypatch.setattr(svc, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: _bars())
    monkeypatch.setattr(svc, "compute_hrp_weights", lambda *_args, **_kwargs: {"AAA": 1.0})
    monkeypatch.setattr(svc, "_edge_for_symbol", lambda *_args, **_kwargs: _edge("AAA", proven=True))
    monkeypatch.setattr(
        svc,
        "compute_execution_plan",
        lambda **_kwargs: {
            "direction": "long",
            "status": "watching",
            "entry_price": 99.0,
            "entry_zone_low": 98.0,
            "entry_zone_high": 100.0,
            "stop_loss": 95.0,
            "target_1": 108.0,
            "target_2": None,
            "rr_ratio": 2.25,
            "atr_14": 2.0,
            "explain": "waiting",
        },
    )

    response = svc.build_dashboard_portfolio_ticket(
        _FakeDB([SimpleNamespace(symbol="AAA", display_name="Alpha", sector="Banks")]),
        DashboardPortfolioTicketRequest(symbols=["AAA"]),
        cost_bps=33.0,
    )

    assert response.summary.allocated_count == 1
    assert response.summary.tradable_count == 0
    assert response.rows[0].shares > 0
    assert response.rows[0].allocation_reason == "waiting_for_entry_zone"
    assert "execution_watching" in response.rows[0].warnings


def test_dashboard_portfolio_ticket_defaults_to_long_only_for_bearish_edges(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "build_dashboard_payload",
        lambda *_args, **_kwargs: {
            "stocks": [
                {"symbol": "BBB", "display_name": "Beta", "sector": "Mines", "adv": 10_000, "scores": {"signal_engine": {"expanded_aggregate_score_pct": -80}}},
            ]
        },
    )
    monkeypatch.setattr(svc, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: _bars())
    monkeypatch.setattr(svc, "compute_hrp_weights", lambda *_args, **_kwargs: {"BBB": 1.0})
    monkeypatch.setattr(svc, "_edge_for_symbol", lambda *_args, **_kwargs: _edge("BBB", direction="short", proven=True))
    monkeypatch.setattr(
        svc,
        "compute_execution_plan",
        lambda **_kwargs: {
            "direction": None,
            "status": "no_setup",
            "entry_price": None,
            "entry_zone_low": None,
            "entry_zone_high": None,
            "stop_loss": None,
            "target_1": None,
            "target_2": None,
            "rr_ratio": None,
            "atr_14": 2.0,
            "explain": "blocked",
        },
    )

    response = svc.build_dashboard_portfolio_ticket(
        _FakeDB([SimpleNamespace(symbol="BBB", display_name="Beta", sector="Mines")]),
        DashboardPortfolioTicketRequest(symbols=["BBB"]),
        cost_bps=33.0,
    )

    assert response.summary.side_policy == "long_only"
    assert response.summary.tradable_count == 0
    assert response.rows[0].action == "avoid_or_exit"
    assert "short_blocked_by_long_only" in response.rows[0].warnings


def test_dashboard_daily_blotter_exits_existing_long_on_bearish_long_only(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "build_dashboard_payload",
        lambda *_args, **_kwargs: {
            "stocks": [
                {"symbol": "BBB", "display_name": "Beta", "sector": "Mines", "adv": 10_000, "scores": {"signal_engine": {"expanded_aggregate_score_pct": -80}}},
            ]
        },
    )
    monkeypatch.setattr(svc, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: _bars())
    monkeypatch.setattr(svc, "compute_hrp_weights", lambda *_args, **_kwargs: {"BBB": 1.0})
    monkeypatch.setattr(svc, "_edge_for_symbol", lambda *_args, **_kwargs: _edge("BBB", direction="short", proven=True))
    monkeypatch.setattr(
        svc,
        "compute_execution_plan",
        lambda **_kwargs: {
            "direction": None,
            "status": "no_setup",
            "entry_price": 100.0,
            "entry_zone_low": 99.0,
            "entry_zone_high": 101.0,
            "stop_loss": None,
            "target_1": None,
            "target_2": None,
            "rr_ratio": None,
            "atr_14": 2.0,
            "explain": "blocked",
        },
    )

    response = svc.build_dashboard_daily_blotter(
        _FakeDB([SimpleNamespace(symbol="BBB", display_name="Beta", sector="Mines")]),
        DashboardDailyBlotterRequest(
            symbols=["BBB"],
            positions=[{"symbol": "BBB", "quantity": 120, "average_price_mad": 95.0}],
        ),
        cost_bps=33.0,
    )

    row = response.rows[0]
    assert row.blotter_action == "EXIT"
    assert row.current_quantity == 120
    assert row.target_quantity == 0
    assert row.delta_quantity == -120
    assert response.summary.exit_count == 1


def test_dashboard_portfolio_ticket_zero_kelly_gets_zero_size(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "build_dashboard_payload",
        lambda *_args, **_kwargs: {
            "stocks": [
                {"symbol": "AAA", "display_name": "Alpha", "sector": "Banks", "adv": 10_000, "scores": {"signal_engine": {"expanded_aggregate_score_pct": 75}}},
            ]
        },
    )
    monkeypatch.setattr(svc, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: _bars())
    monkeypatch.setattr(svc, "compute_hrp_weights", lambda *_args, **_kwargs: {"AAA": 1.0})
    monkeypatch.setattr(svc, "_edge_for_symbol", lambda *_args, **_kwargs: _edge("AAA", proven=True, p_win=0.20))
    monkeypatch.setattr(
        svc,
        "compute_execution_plan",
        lambda **_kwargs: {
            "direction": "long",
            "status": "entry_zone",
            "entry_price": 100.0,
            "entry_zone_low": 99.0,
            "entry_zone_high": 101.0,
            "stop_loss": 95.0,
            "target_1": 110.0,
            "target_2": None,
            "rr_ratio": 2.0,
            "atr_14": 2.0,
            "explain": "ok",
        },
    )

    response = svc.build_dashboard_portfolio_ticket(
        _FakeDB([SimpleNamespace(symbol="AAA", display_name="Alpha", sector="Banks")]),
        DashboardPortfolioTicketRequest(symbols=["AAA"], require_proven_edge=True),
        cost_bps=33.0,
    )

    assert response.summary.tradable_count == 0
    assert response.rows[0].shares == 0
    assert response.rows[0].size_mad == 0.0


def test_dashboard_portfolio_ticket_liquidity_cap_uses_adv_value_mad(monkeypatch) -> None:
    monkeypatch.setattr(
        svc,
        "build_dashboard_payload",
        lambda *_args, **_kwargs: {
            "stocks": [
                {"symbol": "AAA", "display_name": "Alpha", "sector": "Banks", "adv": 1_000_000, "scores": {"signal_engine": {"expanded_aggregate_score_pct": 75}}},
            ]
        },
    )
    monkeypatch.setattr(svc, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: _bars())
    monkeypatch.setattr(svc, "compute_hrp_weights", lambda *_args, **_kwargs: {"AAA": 1.0})
    monkeypatch.setattr(svc, "_edge_for_symbol", lambda *_args, **_kwargs: _edge("AAA", proven=True))
    monkeypatch.setattr(
        svc,
        "compute_execution_plan",
        lambda **_kwargs: {
            "direction": "long",
            "status": "entry_zone",
            "entry_price": 100.0,
            "entry_zone_low": 99.0,
            "entry_zone_high": 101.0,
            "stop_loss": 95.0,
            "target_1": 110.0,
            "target_2": None,
            "rr_ratio": 2.0,
            "atr_14": 2.0,
            "explain": "ok",
        },
    )

    response = svc.build_dashboard_portfolio_ticket(
        _FakeDB([SimpleNamespace(symbol="AAA", display_name="Alpha", sector="Banks")]),
        DashboardPortfolioTicketRequest(
            symbols=["AAA"],
            total_capital_mad=1_000_000,
            cash_buffer_pct=0,
            max_position_pct=100,
            adv_participation_pct=5,
            require_proven_edge=True,
        ),
        cost_bps=33.0,
    )

    assert response.rows[0].adv20 == 1_000_000
    assert response.rows[0].max_liquidity_size_mad == 50_000
    assert response.rows[0].size_mad == 50_000


def test_dashboard_portfolio_ticket_normalizes_score_to_edge_direction(monkeypatch) -> None:
    seen: dict[str, float] = {}
    monkeypatch.setattr(
        svc,
        "build_dashboard_payload",
        lambda *_args, **_kwargs: {
            "stocks": [
                {"symbol": "AAA", "display_name": "Alpha", "sector": "Banks", "adv": 10_000, "scores": {"signal_engine": {"expanded_aggregate_score_pct": -75}}},
            ]
        },
    )
    monkeypatch.setattr(svc, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: _bars())
    monkeypatch.setattr(svc, "compute_hrp_weights", lambda *_args, **_kwargs: {"AAA": 1.0})
    monkeypatch.setattr(svc, "_edge_for_symbol", lambda *_args, **_kwargs: _edge("AAA", direction="long", proven=True))

    def fake_execution_plan(**kwargs):
        seen["consensus"] = kwargs["consensus"]
        return {
            "direction": "long" if kwargs["consensus"] > 0 else "short",
            "status": "entry_zone",
            "entry_price": 100.0,
            "entry_zone_low": 99.0,
            "entry_zone_high": 101.0,
            "stop_loss": 95.0,
            "target_1": 110.0,
            "target_2": None,
            "rr_ratio": 2.0,
            "atr_14": 2.0,
            "explain": "ok",
        }

    monkeypatch.setattr(svc, "compute_execution_plan", fake_execution_plan)
    response = svc.build_dashboard_portfolio_ticket(
        _FakeDB([SimpleNamespace(symbol="AAA", display_name="Alpha", sector="Banks")]),
        DashboardPortfolioTicketRequest(symbols=["AAA"], require_proven_edge=True),
        cost_bps=33.0,
    )

    assert seen["consensus"] > 0
    assert response.rows[0].direction == "long"
    assert response.rows[0].stop_loss is not None and response.rows[0].stop_loss < response.rows[0].entry_reference_price
    assert response.rows[0].target_1 is not None and response.rows[0].target_1 > response.rows[0].entry_reference_price
    assert "score_edge_direction_mismatch" in response.rows[0].warnings


def test_dashboard_portfolio_ticket_auto_uses_best_signal_source_variant(monkeypatch) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        svc,
        "build_dashboard_payload",
        lambda *_args, **_kwargs: {
            "stocks": [
                {"symbol": "AAA", "display_name": "Alpha", "sector": "Banks", "adv": 10_000, "scores": {"signal_engine": {"expanded_aggregate_score_pct": -75}}},
            ]
        },
    )
    monkeypatch.setattr(
        svc,
        "_build_best_signal_payload",
        lambda *_args, **_kwargs: {"source": "wfo", "variant": "expanded_factor_x_ta_simple"},
    )
    monkeypatch.setattr(svc, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: _bars())
    monkeypatch.setattr(svc, "compute_hrp_weights", lambda *_args, **_kwargs: {"AAA": 1.0})

    def fake_edge(_db, *, symbol, source, variant=None, **_kwargs):
        seen["source"] = source
        seen["variant"] = variant
        return _edge(symbol, direction="long", proven=True)

    def fake_execution_plan(**kwargs):
        seen["consensus"] = kwargs["consensus"]
        return {
            "direction": "long",
            "status": "entry_zone",
            "entry_price": 100.0,
            "entry_zone_low": 99.0,
            "entry_zone_high": 101.0,
            "stop_loss": 95.0,
            "target_1": 110.0,
            "target_2": None,
            "rr_ratio": 2.0,
            "atr_14": 2.0,
            "explain": "ok",
        }

    monkeypatch.setattr(svc, "_edge_for_symbol", fake_edge)
    monkeypatch.setattr(svc, "compute_execution_plan", fake_execution_plan)

    response = svc.build_dashboard_portfolio_ticket(
        _FakeDB([SimpleNamespace(symbol="AAA", display_name="Alpha", sector="Banks")]),
        DashboardPortfolioTicketRequest(symbols=["AAA"], source="auto", require_proven_edge=True),
        cost_bps=33.0,
    )

    assert seen["source"] == "wfo"
    assert seen["variant"] == "expanded_factor_x_ta_simple"
    assert seen["consensus"] == 35.0
    assert response.summary.source == "auto"
    assert "source=wfo" in response.rows[0].proof_url
    assert "variant=expanded_factor_x_ta_simple" in response.rows[0].proof_url


def test_dashboard_portfolio_ticket_api_contract(monkeypatch) -> None:
    def fake_build(_db, body, *, cost_bps):
        assert body.symbols == ["AAA"]
        assert cost_bps >= 0
        return {
            "summary": {
                "horizon": "monthly",
                "source": "signal_engine",
                "side_policy": "long_short",
                "entry_timing": "next_open",
                "total_capital_mad": 1_000_000,
                "deployable_capital_mad": 900_000,
                "allocated_capital_mad": 100_000,
                "cash_buffer_mad": 900_000,
                "expected_action_return_mad": 3_000,
                "expected_action_return_pct": 0.003,
                "selected_count": 1,
                "tradable_count": 1,
            },
            "rows": [
                {
                    "symbol": "AAA",
                    "action": "buy",
                    "status": "entry_zone",
                    "proven_edge": True,
                    "base_hrp_weight_pct": 20,
                    "final_weight_pct": 10,
                    "size_mad": 100_000,
                    "shares": 1_000,
                    "entry_timing": "next_open",
                    "entry_reference_price_type": "last_close_proxy",
                    "execution_condition": "execute_next_open_only_if_open_remains_in_entry_zone",
                    "proof_url": "/signals?symbol=AAA&horizon=monthly&view=expanded&source=signal_engine&side=long_short&tab=evidence",
                }
            ],
        }

    monkeypatch.setattr(dashboard_data, "build_dashboard_portfolio_ticket", fake_build)
    res = _client().post(
        "/dashboard/portfolio-ticket",
        json={"symbols": ["AAA"], "horizon": "monthly", "side_policy": "long_short"},
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["summary"]["entry_timing"] == "next_open"
    assert payload["rows"][0]["entry_reference_price_type"] == "last_close_proxy"
