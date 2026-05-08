"""Tests for `monte_carlo_label_shuffle_test` (§A.1.c-NEW)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.quant_core.significance import monte_carlo_label_shuffle_test


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="B")


def test_label_shuffle_pvalue_close_to_one_when_no_signal():
    rng = np.random.default_rng(7)
    n = 400
    idx = _idx(n)
    score = pd.Series(rng.uniform(-100, 100, size=n), index=idx)
    fwd = pd.Series(rng.normal(0.0, 0.01, size=n), index=idx)
    res = monte_carlo_label_shuffle_test(
        score, fwd, bucket="strong_buy", n_iter=2000, seed=42,
    )
    assert res["method"] == "bucket_label_shuffle"
    assert res["pvalue"] is not None
    assert res["pvalue"] > 0.05  # uninformative null → not significant


def test_label_shuffle_pvalue_low_when_strong_signal():
    n = 400
    idx = _idx(n)
    rng = np.random.default_rng(11)
    score_vals = rng.uniform(-100, 100, size=n)
    score = pd.Series(score_vals, index=idx)
    fwd_vals = np.where(score_vals > 50, 0.05, 0.0) + rng.normal(0.0, 0.001, size=n)
    fwd = pd.Series(fwd_vals, index=idx)
    res = monte_carlo_label_shuffle_test(
        score, fwd, bucket="strong_buy", n_iter=2000, seed=42,
    )
    assert res["pvalue"] is not None
    assert res["pvalue"] < 0.01


def test_label_shuffle_seed_determinism():
    n = 200
    idx = _idx(n)
    rng = np.random.default_rng(3)
    score = pd.Series(rng.uniform(-100, 100, size=n), index=idx)
    fwd = pd.Series(rng.normal(0.0, 0.01, size=n), index=idx)
    a = monte_carlo_label_shuffle_test(score, fwd, bucket="buy", n_iter=500, seed=42)
    b = monte_carlo_label_shuffle_test(score, fwd, bucket="buy", n_iter=500, seed=42)
    assert a["pvalue"] == b["pvalue"]
    assert a["null_quantiles"] == b["null_quantiles"]


def test_label_shuffle_supports_block_shuffle():
    n = 120
    idx = _idx(n)
    rng = np.random.default_rng(13)
    score = pd.Series(rng.uniform(-100, 100, size=n), index=idx)
    fwd = pd.Series(rng.normal(0.0, 0.01, size=n), index=idx)

    res = monte_carlo_label_shuffle_test(
        score,
        fwd,
        bucket="strong_buy",
        n_iter=100,
        seed=42,
        block_mean=5,
    )

    assert res["method"] == "bucket_label_block_shuffle"
    assert res["block_mean"] == 5
