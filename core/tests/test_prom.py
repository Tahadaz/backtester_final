from __future__ import annotations

from math import isinf

from core.quant_core.wfo.prom import compute_prom


def test_compute_prom_returns_negative_infinity_for_no_trades() -> None:
    assert isinf(compute_prom([], 100_000))
    assert compute_prom([], 100_000) < 0


def test_compute_prom_single_winning_trade_is_zero() -> None:
    assert compute_prom([100.0], 100_000) == 0.0


def test_compute_prom_single_losing_trade_is_doubly_penalized() -> None:
    assert compute_prom([-100.0], 100_000) == -0.002


def test_compute_prom_mixed_trade_sequence_matches_formula() -> None:
    trades = [100.0, 50.0, -40.0, -20.0]
    result = compute_prom(trades, 10_000)
    assert round(result, 6) == round(-0.005849242404917499, 6)
