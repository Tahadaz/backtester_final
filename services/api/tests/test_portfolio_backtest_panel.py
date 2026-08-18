"""Tests for the portfolio backtest panel endpoints.

Both endpoints source trades from ``SignalBestEvidenceSnapshot`` — the same
stitched-OOS-WFO trade reconstruction shown on the signal evidence page for
whichever method the dashboard currently ranks as each symbol's best WFO
signal (see ``_dashboard_best_signal_trades_by_symbol`` in
``strategy_signals/_backtest.py``). There is exactly one snapshot row per
(symbol, horizon, cooldown_bars) — the DB enforces that with a unique
constraint — so there's no cross-window dedupe to test here; the trades for
a symbol all come from that one row's ``evidence_payload_jsonb.stitched_oos_backtest.trades``.

Covers:
  (a) Universe endpoint: eligible symbols, n_long/n_short counts, date_range.
  (b) Trades ledger returned and date-filtered when start_date/end_date set.
  (c) pnl_mad sums roughly to final_equity - initial_capital for executed trades.
  (d) Stitched-trade field mapping (entry_date/exit_date/action_return_net/direction).
  (e) Rows with the wrong horizon/status/cooldown_bars, or missing stitched
      trades, are excluded from the universe.
"""
from __future__ import annotations

import datetime as dt
from datetime import datetime, timezone

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.db import get_db
from services.api.app.routers import strategy_signals


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover
    return "JSON"


def _create_sqlite_table(engine, model) -> None:
    """Create *model*'s table on sqlite, dropping its postgres-only ``::jsonb``
    server_default (upstream_rev) which sqlite can't parse. Uses a scratch
    Table/MetaData so the shared model metadata is never mutated."""
    src = model.__table__
    cols = []
    for c in src.columns:
        c2 = c.copy()
        if c.server_default is not None and "jsonb" in str(c.server_default.arg).lower():
            c2.server_default = None
        cols.append(c2)
    Table(src.name, MetaData(), *cols).create(engine)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stitched_trade(
    entry_date: str,
    exit_date: str,
    direction: str = "long",
    action_return_net: float = 0.04,
    entry_price: float = 100.0,
    exit_price: float = 104.0,
    holding_period_bars: int = 5,
) -> dict:
    """One trade in the shape produced by ``_evidence_stitched_backtest``."""
    return {
        "trade_id": f"wfo-0-{entry_date}-0",
        "direction": direction,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "holding_period_bars": holding_period_bars,
        "stock_return": action_return_net,
        "action_return_gross": action_return_net,
        "action_return_net": action_return_net,
        "is_hit": action_return_net > 0,
    }


# At least 3 long trades so a symbol qualifies for the backtest
_LONG_TRADES = [
    _stitched_trade("2024-01-10", "2024-01-20", action_return_net=0.05),
    _stitched_trade("2024-02-05", "2024-02-15", action_return_net=-0.02),
    _stitched_trade("2024-03-01", "2024-03-10", action_return_net=0.03),
    _stitched_trade("2024-04-01", "2024-04-10", action_return_net=0.04),
]


def _snapshot_row(
    symbol: str,
    trades: list[dict],
    *,
    row_id: int,
    horizon: str = "weekly",
    source: str = "wfo",
    status: str = "succeeded",
    cooldown_bars: int = 0,
    variant: str = "expanded_ta_simple",
    edge_score: float = 75.0,
) -> models.SignalBestEvidenceSnapshot:
    return models.SignalBestEvidenceSnapshot(
        id=row_id,
        symbol=symbol,
        horizon=horizon,
        source=source,
        status=status,
        cooldown_bars=cooldown_bars,
        variant=variant,
        scope="global",
        scope_key="global",
        side_policy="long_short",
        evidence_payload_jsonb={
            "edge": {"edge_score": edge_score, "n": 60, "action_expected_return_net": 0.01},
            "stitched_oos_backtest": {"trades": trades},
        } if trades is not None else None,
        upstream_rev={},
        computed_at=dt.datetime(2025, 1, 1, tzinfo=timezone.utc),
        updated_at=dt.datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _make_app(rows: list[models.SignalBestEvidenceSnapshot]) -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    _create_sqlite_table(engine, models.SignalBestEvidenceSnapshot)
    db = SessionLocal()
    for row in rows:
        db.add(row)
    db.commit()

    app = FastAPI()
    app.include_router(strategy_signals.router)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


# ---------------------------------------------------------------------------
# Part A: Universe endpoint
# ---------------------------------------------------------------------------

class TestPortfolioBacktestUniverse:
    def test_universe_lists_eligible_symbols(self) -> None:
        client = _make_app([
            _snapshot_row("ADI", _LONG_TRADES, row_id=1),
            _snapshot_row("BBI", _LONG_TRADES, row_id=2),
        ])
        resp = client.get(
            "/strategy/signal/portfolio-backtest/universe",
            params={"horizon": "weekly", "long_only": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        syms = sorted(s["symbol"] for s in data["symbols"])
        assert syms == ["ADI", "BBI"]

    def test_universe_reports_long_short_counts(self) -> None:
        mixed = _LONG_TRADES + [_stitched_trade("2024-05-01", "2024-05-10", direction="short")]
        client = _make_app([_snapshot_row("ADI", mixed, row_id=1)])
        resp = client.get(
            "/strategy/signal/portfolio-backtest/universe",
            params={"horizon": "weekly", "long_only": True},
        )
        assert resp.status_code == 200
        row = resp.json()["symbols"][0]
        assert row["n_long"] == 4
        assert row["n_short"] == 1

    def test_universe_returns_date_range(self) -> None:
        client = _make_app([_snapshot_row("ADI", _LONG_TRADES, row_id=1)])
        resp = client.get(
            "/strategy/signal/portfolio-backtest/universe",
            params={"horizon": "weekly", "long_only": True},
        )
        assert resp.status_code == 200
        dr = resp.json().get("date_range", {})
        assert dr.get("min") is not None
        assert dr.get("max") is not None
        assert dr["min"] <= dr["max"]

    def test_universe_excludes_wrong_horizon(self) -> None:
        client = _make_app([_snapshot_row("ADI", _LONG_TRADES, row_id=1, horizon="monthly")])
        resp = client.get(
            "/strategy/signal/portfolio-backtest/universe",
            params={"horizon": "weekly", "long_only": True},
        )
        assert resp.status_code == 200
        assert resp.json()["symbols"] == []

    def test_universe_excludes_failed_snapshot(self) -> None:
        client = _make_app([_snapshot_row("ADI", _LONG_TRADES, row_id=1, status="failed")])
        resp = client.get(
            "/strategy/signal/portfolio-backtest/universe",
            params={"horizon": "weekly", "long_only": True},
        )
        assert resp.status_code == 200
        assert resp.json()["symbols"] == []

    def test_universe_excludes_missing_stitched_trades(self) -> None:
        client = _make_app([_snapshot_row("ADI", None, row_id=1)])
        resp = client.get(
            "/strategy/signal/portfolio-backtest/universe",
            params={"horizon": "weekly", "long_only": True},
        )
        assert resp.status_code == 200
        assert resp.json()["symbols"] == []

    def test_universe_excludes_symbol_below_kelly_minimum(self) -> None:
        client = _make_app([
            _snapshot_row("AAA", [_stitched_trade("2024-01-10", "2024-01-20")], row_id=1)
        ])
        resp = client.get(
            "/strategy/signal/portfolio-backtest/universe",
            params={"horizon": "weekly", "long_only": True},
        )
        assert resp.status_code == 200
        assert resp.json()["symbols"] == []

    def test_universe_enforces_configured_edge_floor(self) -> None:
        client = _make_app([
            _snapshot_row("LOW", _LONG_TRADES, row_id=1, edge_score=49.99),
            _snapshot_row("PASS", _LONG_TRADES, row_id=2, edge_score=50.0),
            _snapshot_row("HIGH", _LONG_TRADES, row_id=3, edge_score=75.0),
        ])

        default_response = client.get(
            "/strategy/signal/portfolio-backtest/universe",
            params={"horizon": "weekly", "long_only": True},
        )
        assert sorted(row["symbol"] for row in default_response.json()["symbols"]) == ["HIGH", "PASS"]

        stricter_response = client.get(
            "/strategy/signal/portfolio-backtest/universe",
            params={"horizon": "weekly", "long_only": True, "min_edge_score": 80},
        )
        assert stricter_response.json()["symbols"] == []

        relaxed_response = client.get(
            "/strategy/signal/portfolio-backtest/universe",
            params=[
                ("horizon", "weekly"), ("long_only", "true"),
                ("min_edge_score", "0"), ("required_edge_conditions", "sample_size"),
            ],
        )
        assert sorted(row["symbol"] for row in relaxed_response.json()["symbols"]) == ["HIGH", "LOW", "PASS"]

        no_gate_response = client.get(
            "/strategy/signal/portfolio-backtest/universe",
            params=[("horizon", "weekly"), ("min_edge_score", "0"), ("required_edge_conditions", "none")],
        )
        assert sorted(row["symbol"] for row in no_gate_response.json()["symbols"]) == ["HIGH", "LOW", "PASS"]


# ---------------------------------------------------------------------------
# Part B: Trades ledger + period
# ---------------------------------------------------------------------------

class TestPortfolioBacktestTrades:
    def test_daily_mtm_curve_is_continuous_and_conserves_wealth(self, monkeypatch) -> None:
        from services.api.app.routers.strategy_signals import _backtest as bt

        dates = pd.date_range("2024-01-01", "2024-01-10", freq="D")
        closes = [100.0 + i for i in range(10)]
        daily = pd.DataFrame(
            {
                "Open": closes,
                "High": closes,
                "Low": closes,
                "Close": closes,
                "Volume": [1_000.0] * len(closes),
            },
            index=dates,
        )

        def fake_prices(_db, symbol, _timeframe):
            return daily if symbol == "AAA" else pd.DataFrame()

        monkeypatch.setattr(bt, "load_ohlcv_for_symbol", fake_prices)
        trade = _stitched_trade(
            "2024-01-01",
            "2024-01-10",
            action_return_net=0.09,
            entry_price=100.0,
            exit_price=109.0,
            holding_period_bars=9,
        )
        client = _make_app([_snapshot_row("AAA", [trade], row_id=1)])
        response = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "initial_capital": 100_000.0},
        )

        assert response.status_code == 200
        data = response.json()
        curve = data["equity_curve"]
        assert [point["date"] for point in curve] == [date.strftime("%Y-%m-%d") for date in dates]
        assert all(
            curve[index]["date"] < curve[index + 1]["date"]
            for index in range(len(curve) - 1)
        )

        executed = data["trades"][0]
        quantity = executed["position_size"] / executed["open_price"]
        expected_daily_change = quantity * 1.0
        changes = [curve[index]["equity"] - curve[index - 1]["equity"] for index in range(1, len(curve))]
        assert all(abs(change - expected_daily_change) < 1e-6 for change in changes)
        assert changes[-1] < executed["pnl_mad"] / 2.0
        assert curve[1]["equity"] > curve[0]["equity"]

        realized = sum(row["pnl_mad"] for row in data["trades"] if row["executed"])
        assert abs(curve[-1]["equity"] - (100_000.0 + realized)) < 1e-6
        assert data["metrics"]["max_exposure_pct"] <= 100.0
        assert all(row["exposition_pct"] <= 100.0 for row in data["ledger"])

    def test_same_day_close_is_not_used_for_kelly_sizing(self) -> None:
        trades = [
            _stitched_trade("2024-01-01", "2024-01-02", action_return_net=0.10, exit_price=110.0),
            _stitched_trade("2024-01-03", "2024-01-04", action_return_net=0.10, exit_price=110.0),
            _stitched_trade("2024-01-05", "2024-01-06", action_return_net=0.10, exit_price=110.0),
            _stitched_trade("2024-01-06", "2024-01-10", action_return_net=0.10, exit_price=110.0),
        ]
        client = _make_app([_snapshot_row("AAA", trades, row_id=1)])
        response = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "initial_capital": 100_000.0},
        )

        assert response.status_code == 200
        executed = sorted(response.json()["trades"], key=lambda row: (row["open_date"], row["close_date"]))
        same_day_open = next(
            row for row in executed
            if row["open_date"] == "2024-01-06" and row["close_date"] == "2024-01-10"
        )
        equity_before_open = 100_000.0 + sum(row["pnl_mad"] for row in executed[:3])
        assert same_day_open["position_size"] == round(0.025 * equity_before_open)
        # Including the third (same-day) winning close would produce 50% Kelly.
        assert same_day_open["position_size"] < 0.05 * equity_before_open

    def test_missing_symbol_prices_carry_lot_at_cost_with_warning(self, monkeypatch) -> None:
        from services.api.app.routers.strategy_signals import _backtest as bt

        monkeypatch.setattr(bt, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: pd.DataFrame())
        client = _make_app([
            _snapshot_row(
                "AAA",
                [_stitched_trade("2024-01-01", "2024-01-10", action_return_net=0.09)],
                row_id=1,
            )
        ])
        response = client.post("/strategy/signal/portfolio-backtest", json={"horizon": "weekly"})

        assert response.status_code == 200
        data = response.json()
        assert len(data["equity_curve"]) == 2
        assert any(
            "AAA: prix indisponibles" in warning and "au coût" in warning
            for warning in data["warnings"]
        )

    def test_trades_present_in_response(self) -> None:
        client = _make_app([_snapshot_row("ADI", _LONG_TRADES, row_id=1)])
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "trades" in data
        assert len(data["trades"]) > 0

    def test_trades_have_required_fields(self) -> None:
        client = _make_app([_snapshot_row("ADI", _LONG_TRADES, row_id=1)])
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": True},
        )
        assert resp.status_code == 200
        trade = resp.json()["trades"][0]
        for field in ("symbol", "direction", "open_date", "close_date", "open_price",
                      "close_price", "pnl_return", "effective_return", "tp_applied",
                      "position_size", "pnl_mad", "executed"):
            assert field in trade, f"Trade missing field: {field}"

    def test_stitched_trade_fields_map_onto_engine_trade(self) -> None:
        """entry_date/exit_date/entry_price/exit_price/action_return_net/direction
        map onto open_date/close_date/open_price/close_price/pnl_return/direction."""
        client = _make_app([_snapshot_row("ADI", _LONG_TRADES, row_id=1)])
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": True},
        )
        assert resp.status_code == 200
        trades = sorted(resp.json()["trades"], key=lambda t: t["open_date"])
        first = trades[0]
        assert first["open_date"] == "2024-01-10"
        assert first["close_date"] == "2024-01-20"
        assert first["open_price"] == 100.0
        assert first["close_price"] == 104.0
        assert first["pnl_return"] == 0.05
        assert first["direction"] == 1

    def test_short_direction_maps_to_negative_one(self) -> None:
        client = _make_app([
            _snapshot_row(
                "ADI",
                [_stitched_trade(f"2024-0{i}-10", f"2024-0{i}-20", direction="short") for i in range(1, 4)],
                row_id=1,
            )
        ])
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["n_symbols_qualified"] == 1
        assert all(t["direction"] == -1 for t in data["trades"])

    def test_date_filter_start_date(self) -> None:
        client = _make_app([_snapshot_row("ADI", _LONG_TRADES, row_id=1)])
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": True, "start_date": "2024-03-01"},
        )
        assert resp.status_code == 200
        trades = resp.json()["trades"]
        bad = [t for t in trades if t["open_date"] < "2024-03-01"]
        assert bad == [], f"Trades before start_date returned: {bad}"

    def test_date_filter_end_date(self) -> None:
        client = _make_app([_snapshot_row("ADI", _LONG_TRADES, row_id=1)])
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": True, "end_date": "2024-02-28"},
        )
        assert resp.status_code == 200
        trades = resp.json()["trades"]
        bad = [t for t in trades if t["open_date"] > "2024-02-28"]
        assert bad == [], f"Trades after end_date returned: {bad}"

    def test_period_returned_in_response(self) -> None:
        client = _make_app([_snapshot_row("ADI", _LONG_TRADES, row_id=1)])
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={
                "horizon": "weekly",
                "long_only": True,
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            },
        )
        assert resp.status_code == 200
        period = resp.json().get("period", {})
        assert period.get("start") is not None
        assert period.get("end") is not None
        assert period.get("requested_start") == "2024-01-01"
        assert period.get("requested_end") == "2024-12-31"

    def test_pnl_mad_sums_to_equity_delta(self) -> None:
        client = _make_app([_snapshot_row("ADI", _LONG_TRADES, row_id=1)])
        initial_capital = 100_000.0
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": True, "initial_capital": initial_capital},
        )
        assert resp.status_code == 200
        data = resp.json()
        trades = data.get("trades", [])
        executed_pnl_sum = sum(t["pnl_mad"] for t in trades if t["executed"])
        final_equity = data["metrics"].get("final_equity", 0.0)
        equity_delta = final_equity - initial_capital
        assert abs(executed_pnl_sum - equity_delta) < 1.0, (
            f"pnl_mad sum {executed_pnl_sum:.2f} != equity delta {equity_delta:.2f}"
        )

    def test_same_day_trade_executes_and_closes(self) -> None:
        """A trade whose entry_date == exit_date (same-day open/close, seen in
        stitched data e.g. 2022-12-13/2022-12-13) must still open then close
        within the replay. Before the fix, the CLOSE event sorted before the
        symbol's own OPEN event on that date, so the close was a no-op (record
        not yet executed), the later open deducted cash into open_positions,
        and the position was never closed — final_equity (cash only) lost the
        position's cost permanently even though nothing went wrong price-wise.
        """
        trades = [
            _stitched_trade("2022-11-01", "2022-11-10", action_return_net=0.02),
            _stitched_trade("2022-11-15", "2022-11-25", action_return_net=0.03),
            # Same-day trade: entry_date == exit_date.
            _stitched_trade("2022-12-13", "2022-12-13", action_return_net=0.06),
            _stitched_trade("2023-01-05", "2023-01-15", action_return_net=-0.01),
        ]
        client = _make_app([_snapshot_row("ADI", trades, row_id=1)])
        initial_capital = 100_000.0
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": True, "initial_capital": initial_capital},
        )
        assert resp.status_code == 200
        data = resp.json()

        same_day = [t for t in data["trades"] if t["open_date"] == "2022-12-13" and t["close_date"] == "2022-12-13"]
        assert len(same_day) == 1
        assert same_day[0]["executed"] is True, "same-day trade must execute, not be silently skipped"
        assert same_day[0]["pnl_mad"] != 0.0, "same-day trade's pnl must be booked into the ledger"

        warnings = data.get("warnings", [])
        assert not any("never closed" in w for w in warnings), warnings

        equity_curve = data["equity_curve"]
        assert equity_curve, "equity curve should not be empty"
        assert abs(equity_curve[-1]["equity"] - data["metrics"]["final_equity"]) < 1e-6

        # total_return should be consistent with the equity curve, not a huge
        # negative number caused by cash being stranded in open_positions.
        expected_total_return = (
            (data["metrics"]["final_equity"] - initial_capital) / initial_capital * 100.0
        )
        assert abs(data["metrics"]["total_return"] - expected_total_return) < 1e-2

    def test_no_executed_trades_when_kelly_multiplier_zero(self) -> None:
        """kelly_multiplier=0 zeroes both the starter fraction and the walk-forward
        Kelly fraction, so every trade should be skipped for every symbol."""
        client = _make_app([
            _snapshot_row("AAA", _LONG_TRADES, row_id=1)
        ])
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": True, "kelly_multiplier": 0.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["n_symbols_qualified"] == 0
        assert len(data["warnings"]) > 0
        assert all(not t["executed"] for t in data["trades"])
        assert all(t["skip_reason"] == "kelly <= 0" for t in data["trades"])

    def test_single_trade_symbol_executes_via_starter_fraction(self) -> None:
        """A brand-new symbol with only one trade (no prior closed history) is no
        longer dropped up front for insufficient Kelly history — it executes using
        the starter fraction (no survivorship bias / no upfront symbol filtering)."""
        client = _make_app([
            _snapshot_row("AAA", [_stitched_trade("2024-01-10", "2024-01-20")], row_id=1)
        ])
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["n_symbols_qualified"] == 1
        trade = data["trades"][0]
        assert trade["executed"] is True
        assert trade["skip_reason"] is None
        # starter fraction = 0.05 * kelly_multiplier(default 0.5) = 2.5% of equity
        assert trade["position_size"] == round(0.025 * 100_000.0)

    def test_benchmark_null_with_warning_when_masi_unavailable(self) -> None:
        """The sqlite fixture has no MASI market data, so the benchmark must be
        null and the response must carry the French unavailability warning
        instead of failing the whole request."""
        client = _make_app([_snapshot_row("ADI", _LONG_TRADES, row_id=1)])
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "benchmark" in data
        assert data["benchmark"] is None
        assert data["metrics"]["alpha_total_return"] is None
        assert any("Indice MASI indisponible" in w for w in data["warnings"])

    def test_alpha_uses_common_window_not_full_period(self, monkeypatch) -> None:
        """MASI history may start after the strategy's first trade. Alpha must
        compare the strategy return measured over the benchmark's own window
        against the benchmark return — never full-period vs partial-period."""
        from services.api.app.routers.strategy_signals import _backtest as bt

        bench_curve = [
            {"date": "2024-02-01", "equity": 100_000.0},
            {"date": "2024-03-10", "equity": 110_000.0},
        ]

        def fake_benchmark(db, *, start_date, end_date, initial_capital):
            return {
                "curve": bench_curve,
                "metrics": {"total_return": 10.0, "cagr": None, "max_drawdown": 0.0},
            }, None

        monkeypatch.setattr(bt, "_portfolio_benchmark", fake_benchmark)

        client = _make_app([_snapshot_row("ADI", _LONG_TRADES, row_id=1)])
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": True, "initial_capital": 100_000.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        bench = data["benchmark"]
        assert bench is not None

        # Strategy equity at the benchmark window edges (last curve point <= date).
        def equity_at(as_of: str) -> float:
            value = 100_000.0
            for p in data["equity_curve"]:
                if p["date"] <= as_of:
                    value = p["equity"]
            return value

        eq_start = equity_at("2024-02-01")
        eq_end = equity_at("2024-03-10")
        expected_window_return = (eq_end / eq_start - 1.0) * 100.0
        expected_alpha = expected_window_return - 10.0

        window = bench["window"]
        assert window["start"] == "2024-02-01"
        assert window["end"] == "2024-03-10"
        assert abs(window["strategy_total_return"] - expected_window_return) < 1e-3
        assert abs(data["metrics"]["alpha_total_return"] - expected_alpha) < 1e-3

        # And it must differ from the naive full-period alpha: the first trade
        # (+5%, closed 2024-01-20) and the last (+4%, closed 2024-04-10) lie
        # outside the benchmark window, so full-period != window return here.
        full_alpha = data["metrics"]["total_return"] - 10.0
        assert abs(data["metrics"]["alpha_total_return"] - full_alpha) > 1e-6

    def test_ledger_two_rows_per_executed_trade_in_date_order(self) -> None:
        client = _make_app([
            _snapshot_row("ADI", _LONG_TRADES, row_id=1),
            _snapshot_row("BBI", _LONG_TRADES, row_id=2),
        ])
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        ledger = data["ledger"]
        assert data["ledger_truncated"] is False

        executed = [t for t in data["trades"] if t["executed"]]
        assert len(ledger) == 2 * len(executed)

        # Chronological order.
        dates = [row["date"] for row in ledger]
        assert dates == sorted(dates)

        # Each executed trade contributes exactly one open row and one close
        # row, in date order (open first).
        for t in executed:
            sym_rows = [
                r for r in ledger
                if r["symbol"] == t["symbol"] and r["date"] in (t["open_date"], t["close_date"])
            ]
            open_rows = [r for r in sym_rows if r["date"] == t["open_date"] and r["pnl_realise"] is None]
            close_rows = [r for r in sym_rows if r["date"] == t["close_date"] and r["pnl_realise"] is not None]
            assert len(open_rows) == 1, f"expected 1 open row for {t}"
            assert len(close_rows) == 1, f"expected 1 close row for {t}"
            assert ledger.index(open_rows[0]) < ledger.index(close_rows[0])

        # Non-executed trades never appear in the ledger.
        skipped = [t for t in data["trades"] if not t["executed"]]
        for t in skipped:
            assert not any(
                r["symbol"] == t["symbol"] and r["date"] == t["open_date"] and r["pnl_realise"] is None
                and r["montant"] == t["position_size"]
                for r in ledger
            ) or t["position_size"] == 0

    def test_ledger_cumulative_realized_pnl_ties_out(self) -> None:
        client = _make_app([_snapshot_row("ADI", _LONG_TRADES, row_id=1)])
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        ledger = data["ledger"]
        assert ledger, "ledger should not be empty when trades execute"
        executed_pnl_sum = sum(t["pnl_mad"] for t in data["trades"] if t["executed"])
        assert abs(ledger[-1]["pnl_realise_cumule"] - executed_pnl_sum) < 0.02

        # Ledger row shape sanity: open rows carry cmp == prix_execution, close
        # rows carry cmp == open price of the lot and a realized PnL.
        for row in ledger:
            for field in ("date", "symbol", "side", "quantity", "prix_execution",
                          "cmp", "montant", "pnl_realise_cumule", "capital", "exposition_pct"):
                assert field in row, f"ledger row missing {field}"
            if row["pnl_realise"] is None:
                assert row["cmp"] == row["prix_execution"]

    def test_symbols_filter_restricts_to_selection(self) -> None:
        client = _make_app([
            _snapshot_row("ADI", _LONG_TRADES, row_id=1),
            _snapshot_row("BBI", _LONG_TRADES, row_id=2),
        ])
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "long_only": True, "symbols": ["ADI"]},
        )
        assert resp.status_code == 200
        symbols = [s["symbol"] for s in resp.json()["per_symbol"]]
        assert symbols == ["ADI"]
