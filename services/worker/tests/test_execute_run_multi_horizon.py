from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import services.worker.tasks.execute_run as execute_run_mod  # noqa: E402


class _FakeMappingsResult:
    def mappings(self) -> "_FakeMappingsResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return []


class _FakeDB:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeMappingsResult:
        self.calls.append((str(statement), params))
        return _FakeMappingsResult()


class _DummyPage:
    def __init__(self, explain: dict[str, Any]) -> None:
        self._explain = explain

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return {
            "status": "watch",
            "explain": dict(self._explain),
        }


def _bars_records() -> list[dict[str, Any]]:
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    out: list[dict[str, Any]] = []
    for i, ts in enumerate(idx):
        px = 100.0 + float(i)
        out.append(
            {
                "timestamp": ts.isoformat(),
                "Open": px - 0.2,
                "High": px + 0.5,
                "Low": px - 0.5,
                "Close": px,
                "Volume": 100000.0 + float(i),
            }
        )
    return out


def test_simple_multi_horizon_decisions_only_top3_per_horizon(monkeypatch) -> None:
    monkeypatch.setattr(execute_run_mod, "_has_table", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        execute_run_mod,
        "compute_levels_support_resistance",
        lambda _bars, direction=0: {"entry": 100.0, "stop": 95.0 if direction >= 0 else 105.0, "target": 110.0 if direction >= 0 else 90.0},
    )
    monkeypatch.setattr(execute_run_mod, "compute_rr_and_invalidation", lambda **_kwargs: {"rr": 2.0, "explain": "ok"})
    monkeypatch.setattr(execute_run_mod, "compute_opportunity_score", lambda **_kwargs: {"total": 72.0, "layers": {}})
    monkeypatch.setattr(execute_run_mod, "compute_confidence_score", lambda **_kwargs: {"total": 66.0, "layers": {}})
    monkeypatch.setattr(
        execute_run_mod,
        "build_decision_page",
        lambda **kwargs: _DummyPage(kwargs.get("extra_explain") or {}),
    )

    leaderboard: list[dict[str, Any]] = []
    horizons = ["short", "medium", "long"]
    for h_idx, horizon in enumerate(horizons):
        for local_rank in range(1, 6):
            storage_rank = h_idx * 1000 + local_rank
            leaderboard.append(
                {
                    "symbol": "AAA",
                    "strategy_kind": "sma_price",
                    "rank": storage_rank,
                    "pnl": 1000.0 - float(local_rank),
                    "cagr": 0.10 - (local_rank * 0.001),
                    "efficiency": 0.2,
                    "n_fills": 10 + local_rank,
                    "signal_today": 1.0,
                    "signal_label": "BUY",
                    "best_params_json": {
                        "simple_wfo.horizon": horizon,
                        "simple_wfo.rank": local_rank,
                        "strategy.window": 20 + local_rank + (h_idx * 10),
                        "last_test_start": "2024-01-03",
                        "last_test_end": "2024-01-06",
                        "_summary": {
                            "objective_mean": 0.12,
                            "objective_median": 0.11,
                            "objective_std": 0.02,
                            "positive_ratio": 1.0,
                            "n_folds": 4,
                        },
                    },
                }
            )

    out = {
        "leaderboard": leaderboard,
        "strategy_results": {},
        "simple_wfo_multi_horizon": {"enabled": True, "horizons": horizons},
        "decision_support": {
            "inputs_by_kind": {
                "sma_price": {
                    "decision_inputs": {
                        "symbols": {
                            "AAA": {
                                "bars": _bars_records(),
                                "signals": [{"timestamp": "2024-01-10T00:00:00+00:00", "signal": 1.0}],
                                "returns": [{"timestamp": "2024-01-10T00:00:00+00:00", "return": 0.01}],
                            }
                        }
                    },
                    "trade_ledger": [],
                    "symbols": ["AAA"],
                }
            }
        },
    }

    db = _FakeDB()
    execute_run_mod._persist_decisions(
        db=db,
        rid=UUID("00000000-0000-0000-0000-000000000001"),
        out=out,
        default_symbol="AAA",
    )

    insert_calls = [c for c in db.calls if "insert into strategy_decision" in c[0].lower()]
    assert len(insert_calls) == 9
    for _, params in insert_calls:
        _, local_rank = execute_run_mod._decode_storage_rank((params or {}).get("rank"))
        assert local_rank is not None and local_rank <= 3


def test_slice_bars_to_last_oos_window_uses_bounds_and_fallback() -> None:
    idx = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC")
    bars = pd.DataFrame({"Close": [100.0 + float(i) for i in range(10)]}, index=idx)

    sliced, source, warnings = execute_run_mod._slice_bars_to_last_oos_window(
        bars,
        last_test_start="2024-01-03",
        last_test_end="2024-01-05",
    )
    assert source == "last_oos_window"
    assert not warnings
    assert len(sliced) == 3
    assert sliced.index[0].date().isoformat() == "2024-01-03"
    assert sliced.index[-1].date().isoformat() == "2024-01-05"

    fallback, fallback_source, fallback_warnings = execute_run_mod._slice_bars_to_last_oos_window(
        bars,
        last_test_start="2030-01-01",
        last_test_end="2030-01-03",
    )
    assert fallback_source == "full_bars_fallback_empty_slice"
    assert fallback.equals(bars)
    assert fallback_warnings


def test_simple_multi_horizon_fold_persistence_writes_run_fold_and_artifacts(monkeypatch) -> None:
    monkeypatch.setattr(execute_run_mod, "_has_table", lambda _db, table: table == "run_fold")

    uploaded_keys: list[str] = []
    inserted_artifacts: list[dict[str, Any]] = []

    def _fake_upload_json(object_key: str, payload: Any, db: Any | None = None) -> tuple[int, str, str]:
        uploaded_keys.append(object_key)
        return (1, "sha", object_key)

    def _fake_insert_artifact_row(**kwargs: Any) -> None:
        inserted_artifacts.append(dict(kwargs))

    monkeypatch.setattr(execute_run_mod, "_upload_json", _fake_upload_json)
    monkeypatch.setattr(execute_run_mod, "_insert_artifact_row", _fake_insert_artifact_row)

    out = {
        "artifacts": {
            "simple_wfo_multi_horizon": {
                "enabled": True,
                "horizons": ["short", "medium"],
                "fold_rows_by_horizon": {
                    "short": [
                        {
                            "fold_index": 0,
                            "trial_rank": 1,
                            "strategy_kind": "sma_price",
                            "test_start": "2024-01-01",
                            "test_end": "2024-01-05",
                            "objective_value": 1.2,
                        }
                    ],
                    "medium": [
                        {
                            "fold_index": 0,
                            "trial_rank": 2,
                            "strategy_kind": "sma_price",
                            "test_start": "2024-01-06",
                            "test_end": "2024-01-10",
                            "objective_value": 0.8,
                        }
                    ],
                },
            }
        }
    }

    db = _FakeDB()
    rid = UUID("00000000-0000-0000-0000-000000000002")
    execute_run_mod._persist_walk_forward_folds(
        db=db,
        rid=rid,
        out=out,
        default_symbol="AAA",
    )

    run_fold_calls = [c for c in db.calls if "insert into run_fold" in c[0].lower()]
    assert run_fold_calls
    for _, params in run_fold_calls:
        fold_artifacts = json.loads(str((params or {}).get("fold_artifacts") or "{}"))
        assert fold_artifacts.get("horizon") in {"short", "medium"}

    assert f"runs/{rid}/wfo/AAA/short/folds.json" in uploaded_keys
    assert f"runs/{rid}/wfo/AAA/medium/folds.json" in uploaded_keys
    folds_artifacts = [a for a in inserted_artifacts if a.get("name") == "walk_forward.folds"]
    assert len(folds_artifacts) == 2
