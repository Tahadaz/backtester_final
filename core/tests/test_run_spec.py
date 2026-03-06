from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_core.run_spec import build_run_spec  # noqa: E402


def _base_kwargs() -> dict:
    return {
        "source_key": "synthetic",
        "symbols": ["AAA"],
        "start": "2020-01-01",
        "end": "2020-12-31",
        "include_windows": [],
        "exclude_windows": [],
        "interval": "1d",
        "yf_period": "max",
        "yf_interval": "1d",
        "yf_auto_adjust": False,
        "rank_metric": "pnl",
        "lb_opt_kinds": ["sma_price"],
        "opt_method": "random",
        "n_trials": 25,
        "allow_short": False,
        "initial_cash": 100000.0,
        "cooldown_bars": 0,
        "min_return_before_sell": 0.0,
        "cost_model": {},
        "volume_gate": {},
        "participation_cap": {},
        "domains_by_kind": {},
    }


def test_build_run_spec_defaults_topk_and_topn_artifacts() -> None:
    spec = build_run_spec(**_base_kwargs())
    optimization = dict(spec.get("optimization") or {})
    assert optimization.get("top_k") == 20
    assert optimization.get("top_n_artifacts") == 3


def test_build_run_spec_explicit_values_override_defaults() -> None:
    spec = build_run_spec(**_base_kwargs(), top_k=7, top_n_artifacts=2)
    optimization = dict(spec.get("optimization") or {})
    assert optimization.get("top_k") == 7
    assert optimization.get("top_n_artifacts") == 2
