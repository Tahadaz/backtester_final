"""Tests for the portfolio backtest panel endpoints.

Covers:
  (a) Dedupe: one per_symbol entry per symbol given duplicate SignalBacktestRun window rows.
  (b) Universe endpoint: no duplicate symbols given duplicate window rows.
  (c) Trades ledger returned and date-filtered when start_date/end_date set.
  (d) pnl_mad sums roughly to final_equity - initial_capital for executed trades.
  (e) date_range returned by universe endpoint.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")

from services.api.app.db import get_db
from services.api.app.routers import strategy_signals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(
    open_date: str,
    close_date: str,
    direction: int = 1,
    pnl_return: float = 0.04,
) -> dict:
    return {
        "open_date": open_date,
        "close_date": close_date,
        "open_price": 100.0,
        "close_price": 100.0 * (1 + pnl_return),
        "direction": direction,
        "pnl_return": pnl_return,
        "bars_held": 5,
    }


def _make_row(
    symbol: str,
    trades: list[dict],
    *,
    row_id: int = 1,
    computed_at: datetime | None = None,
) -> SimpleNamespace:
    """Create a fake SignalBacktestRun-like row."""
    return SimpleNamespace(
        id=row_id,
        symbol=symbol,
        trades_json=trades,
        computed_at=computed_at,
        updated_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


# At least 3 long trades so a symbol qualifies for the backtest
_LONG_TRADES = [
    _make_trade("2024-01-10", "2024-01-20", direction=1, pnl_return=0.05),
    _make_trade("2024-02-05", "2024-02-15", direction=1, pnl_return=-0.02),
    _make_trade("2024-03-01", "2024-03-10", direction=1, pnl_return=0.03),
    _make_trade("2024-04-01", "2024-04-10", direction=1, pnl_return=0.04),
]


class _FakeQuery:
    """Minimal SQLAlchemy query stub."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def filter(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def all(self) -> list:
        return list(self._rows)


class _FakeDB:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def query(self, *_args, **_kwargs) -> _FakeQuery:
        return _FakeQuery(self._rows)


def _make_app(rows: list) -> TestClient:
    app = FastAPI()
    app.include_router(strategy_signals.router)

    def override_get_db():
        yield _FakeDB(rows)

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


# ---------------------------------------------------------------------------
# Part A: Dedupe tests
# ---------------------------------------------------------------------------

class TestPortfolioBacktestDedupe:
    """A1 + A2: one per_symbol entry, trades not double-counted."""

    def test_duplicate_rows_produce_single_per_symbol_entry(self) -> None:
        """Given two rows for ADI (different windows), per_symbol must have exactly one ADI."""
        rows = [
            _make_row("ADI", _LONG_TRADES, row_id=1,
                      computed_at=datetime(2024, 6, 1, tzinfo=timezone.utc)),
            _make_row("ADI", _LONG_TRADES, row_id=2,
                      computed_at=datetime(2025, 1, 1, tzinfo=timezone.utc)),  # newer
        ]
        client = _make_app(rows)
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "variant": "expanded", "long_only": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        symbols = [s["symbol"] for s in data["per_symbol"]]
        assert symbols.count("ADI") == 1, f"Expected 1 ADI, got: {symbols}"

    def test_duplicate_rows_trades_not_double_counted(self) -> None:
        """Trades from the deduped (latest) row must not be doubled."""
        rows = [
            _make_row("ADI", _LONG_TRADES, row_id=1,
                      computed_at=datetime(2024, 6, 1, tzinfo=timezone.utc)),
            _make_row("ADI", _LONG_TRADES, row_id=2,
                      computed_at=datetime(2025, 1, 1, tzinfo=timezone.utc)),
        ]
        client = _make_app(rows)
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "variant": "expanded", "long_only": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        # With single-row dedupe: n_trades should equal len(_LONG_TRADES), not 2× that
        assert data["metrics"]["n_trades"] == len(_LONG_TRADES)

    def test_latest_row_is_kept_on_dedupe(self) -> None:
        """The newer row (higher computed_at) is the one whose trades are used."""
        old_trades = [
            _make_trade("2023-01-10", "2023-01-20", pnl_return=0.10),
            _make_trade("2023-02-05", "2023-02-15", pnl_return=0.10),
            _make_trade("2023-03-01", "2023-03-10", pnl_return=0.10),
        ]
        new_trades = [
            _make_trade("2025-01-10", "2025-01-20", pnl_return=0.05),
            _make_trade("2025-02-05", "2025-02-15", pnl_return=-0.02),
            _make_trade("2025-03-01", "2025-03-10", pnl_return=0.03),
        ]
        rows = [
            _make_row("AAA", old_trades, row_id=1,
                      computed_at=datetime(2024, 1, 1, tzinfo=timezone.utc)),
            _make_row("AAA", new_trades, row_id=2,
                      computed_at=datetime(2025, 6, 1, tzinfo=timezone.utc)),  # newer
        ]
        client = _make_app(rows)
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "variant": "expanded", "long_only": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        trades = data.get("trades", [])
        # All returned trade open_dates should be from the 2025 (new) row
        open_dates = [t["open_date"] for t in trades]
        assert all(d.startswith("2025") for d in open_dates), (
            f"Expected only 2025 trades, got: {open_dates}"
        )


class TestPortfolioBacktestUniverseDedupe:
    """A1: Universe endpoint must not return duplicate symbols."""

    def test_universe_no_duplicate_symbols(self) -> None:
        rows = [
            _make_row("ADI", _LONG_TRADES, row_id=1,
                      computed_at=datetime(2024, 6, 1, tzinfo=timezone.utc)),
            _make_row("ADI", _LONG_TRADES, row_id=2,
                      computed_at=datetime(2025, 1, 1, tzinfo=timezone.utc)),
            _make_row("BBI", _LONG_TRADES, row_id=3,
                      computed_at=datetime(2025, 1, 1, tzinfo=timezone.utc)),
        ]
        client = _make_app(rows)
        resp = client.get(
            "/strategy/signal/portfolio-backtest/universe",
            params={"horizon": "weekly", "variant": "expanded", "long_only": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        syms = [s["symbol"] for s in data["symbols"]]
        assert syms.count("ADI") == 1, f"Duplicate ADI in universe: {syms}"
        assert "BBI" in syms

    def test_universe_returns_date_range(self) -> None:
        """B1.5: date_range should reflect min open_date / max close_date across universe."""
        rows = [
            _make_row("ADI", _LONG_TRADES, row_id=1,
                      computed_at=datetime(2025, 1, 1, tzinfo=timezone.utc)),
        ]
        client = _make_app(rows)
        resp = client.get(
            "/strategy/signal/portfolio-backtest/universe",
            params={"horizon": "weekly", "variant": "expanded", "long_only": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        dr = data.get("date_range", {})
        assert dr.get("min") is not None
        assert dr.get("max") is not None
        assert dr["min"] <= dr["max"]


# ---------------------------------------------------------------------------
# Part B: Trades ledger + period
# ---------------------------------------------------------------------------

class TestPortfolioBacktestTrades:
    """B1: trades returned, date-filtered, pnl_mad, period."""

    def test_trades_present_in_response(self) -> None:
        rows = [_make_row("ADI", _LONG_TRADES, row_id=1,
                          computed_at=datetime(2025, 1, 1, tzinfo=timezone.utc))]
        client = _make_app(rows)
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "variant": "expanded", "long_only": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "trades" in data, "Response missing 'trades' key"
        assert len(data["trades"]) > 0

    def test_trades_have_required_fields(self) -> None:
        rows = [_make_row("ADI", _LONG_TRADES, row_id=1,
                          computed_at=datetime(2025, 1, 1, tzinfo=timezone.utc))]
        client = _make_app(rows)
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "variant": "expanded", "long_only": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        trade = data["trades"][0]
        for field in ("symbol", "direction", "open_date", "close_date", "open_price",
                      "close_price", "pnl_return", "effective_return", "tp_applied",
                      "position_size", "pnl_mad", "executed"):
            assert field in trade, f"Trade missing field: {field}"

    def test_date_filter_start_date(self) -> None:
        """Trades before start_date must be excluded."""
        rows = [_make_row("ADI", _LONG_TRADES, row_id=1,
                          computed_at=datetime(2025, 1, 1, tzinfo=timezone.utc))]
        client = _make_app(rows)
        # Only trades from March 2024 onward
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={
                "horizon": "weekly",
                "variant": "expanded",
                "long_only": True,
                "start_date": "2024-03-01",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        trades = data["trades"]
        # January and February trades should be excluded
        bad = [t for t in trades if t["open_date"] < "2024-03-01"]
        assert bad == [], f"Trades before start_date returned: {bad}"

    def test_date_filter_end_date(self) -> None:
        """Trades after end_date must be excluded."""
        rows = [_make_row("ADI", _LONG_TRADES, row_id=1,
                          computed_at=datetime(2025, 1, 1, tzinfo=timezone.utc))]
        client = _make_app(rows)
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={
                "horizon": "weekly",
                "variant": "expanded",
                "long_only": True,
                "end_date": "2024-02-28",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        trades = data["trades"]
        bad = [t for t in trades if t["open_date"] > "2024-02-28"]
        assert bad == [], f"Trades after end_date returned: {bad}"

    def test_period_returned_in_response(self) -> None:
        rows = [_make_row("ADI", _LONG_TRADES, row_id=1,
                          computed_at=datetime(2025, 1, 1, tzinfo=timezone.utc))]
        client = _make_app(rows)
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={
                "horizon": "weekly",
                "variant": "expanded",
                "long_only": True,
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        period = data.get("period", {})
        assert period.get("start") is not None
        assert period.get("end") is not None
        assert period.get("requested_start") == "2024-01-01"
        assert period.get("requested_end") == "2024-12-31"

    def test_pnl_mad_sums_to_equity_delta(self) -> None:
        """Sum of pnl_mad for executed trades ≈ final_equity - initial_capital."""
        rows = [_make_row("ADI", _LONG_TRADES, row_id=1,
                          computed_at=datetime(2025, 1, 1, tzinfo=timezone.utc))]
        client = _make_app(rows)
        initial_capital = 100_000.0
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={
                "horizon": "weekly",
                "variant": "expanded",
                "long_only": True,
                "initial_capital": initial_capital,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        trades = data.get("trades", [])
        executed_pnl_sum = sum(t["pnl_mad"] for t in trades if t["executed"])
        final_equity = data["metrics"].get("final_equity", 0.0)
        equity_delta = final_equity - initial_capital
        # Allow 1 MAD tolerance for floating-point rounding across the simulation
        assert abs(executed_pnl_sum - equity_delta) < 1.0, (
            f"pnl_mad sum {executed_pnl_sum:.2f} != equity delta {equity_delta:.2f}"
        )

    def test_no_executed_trades_when_kelly_zero(self) -> None:
        """A single trade (kelly requires ≥3) → no_trades warning path."""
        single_trade_rows = [
            _make_row("AAA", [_make_trade("2024-01-10", "2024-01-20")], row_id=1,
                      computed_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
        ]
        client = _make_app(single_trade_rows)
        resp = client.post(
            "/strategy/signal/portfolio-backtest",
            json={"horizon": "weekly", "variant": "expanded", "long_only": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["n_symbols_qualified"] == 0
        assert len(data["warnings"]) > 0
