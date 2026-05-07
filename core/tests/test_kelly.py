from __future__ import annotations

from core.quant_core.wfo.sizing import compute_kelly_fraction, compute_trade_stats


def test_compute_trade_stats_and_kelly_fraction_positive_edge() -> None:
    stats = compute_trade_stats([200, 180, 150, -100, -120, 220, 160, -90] * 5)
    result = compute_kelly_fraction(stats)
    assert stats.n_trades == 40
    assert result.fraction > 0
    assert result.half_kelly == result.fraction / 2
    assert result.warning is None


def test_compute_kelly_fraction_warns_for_small_samples() -> None:
    stats = compute_trade_stats([120, -90, 110, -80, 100])
    result = compute_kelly_fraction(stats)
    assert result.fraction > 0
    assert result.warning is not None


def test_compute_kelly_fraction_returns_zero_for_negative_edge() -> None:
    stats = compute_trade_stats([50, -100, 40, -120, 35, -90])
    result = compute_kelly_fraction(stats)
    assert result.fraction == 0.0
    assert result.reason is not None

