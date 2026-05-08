from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from services.worker.tasks import score_history_batch as score_mod


def test_fold_scoped_wfo_series_overrides_each_oos_fold_with_own_winner(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=8, freq="D")
    base = pd.Series(np.zeros(len(idx)), index=idx, name="tendance")
    row = SimpleNamespace(
        category="tendance",
        horizon="weekly",
        variant="expanded",
        folds_json=[
            {"index": 0, "oos_start": 2, "oos_end": 4, "winner_variant_id": "v_pos"},
            {"index": 1, "oos_start": 5, "oos_end": 7, "winner_variant_id": "v_neg"},
        ],
    )
    variants = [
        SimpleNamespace(variant_id="v_pos"),
        SimpleNamespace(variant_id="v_neg"),
    ]

    monkeypatch.setattr(score_mod, "_candidate_pool_for", lambda _row: variants)

    def fake_signal(_close, variant, **_kwargs):
        return np.ones(len(idx)) if variant.variant_id == "v_pos" else -np.ones(len(idx))

    monkeypatch.setattr(score_mod, "compute_variant_signal_array", fake_signal)

    out = score_mod._fold_scoped_wfo_series(
        row=row,
        base_series=base,
        close=np.arange(len(idx), dtype=float) + 100.0,
        volume=None,
        high=None,
        low=None,
        index=idx,
    )

    assert out.loc[idx[2]] == 100.0
    assert out.loc[idx[3]] == 100.0
    assert out.loc[idx[5]] == -100.0
    assert out.loc[idx[6]] == -100.0
    assert out.loc[idx[0]] == 0.0
