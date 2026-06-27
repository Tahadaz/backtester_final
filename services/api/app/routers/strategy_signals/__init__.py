"""strategy_signals router package.

Replaces the monolithic strategy_signals.py with a package of the same import
surface.  External callers use the same symbol paths:

  from .strategy_signals import router
  from .strategy_signals import _get_or_compute, _safe_float, _score_to_label
  from .strategy_signals import _get_all_representative_indicators
  from .strategy_signals import _get_top_representative_indicator
  from .strategy_signals import _sr_get_or_compute_variants
"""
from ._shared import router

# Import submodules so their @router.* decorators register on the shared router.
from . import _ensemble
from . import _support_resistance
from . import _variants
from . import _engine
from . import _evidence
from . import _backtest

# Re-export symbols consumed by other modules so their import paths are unchanged.
from ._shared import _get_or_compute, _safe_float
from ._shared import _score_to_label
from ._engine import _get_all_representative_indicators, _get_top_representative_indicator
from ._support_resistance import _sr_get_or_compute_variants

# Re-export all names that tests monkeypatch on this module.
# Each name must exist here so getattr(strategy_signals, name) succeeds before the patch;
# _PatchPropagator.__setattr__ then propagates the patch to the submodule that actually uses it.
from ._shared import (
    load_ohlcv_for_symbol,
    compute_score_inversion_levels,
    compute_variant_detail,
    detect_swing_levels,
    compute_pivot_points,
    compute_levels_support_resistance,
    latest_rsi_variant_signal,
    monte_carlo_equity_paths,
)
from ._support_resistance import _sr_direct_objective_summary, _sr_simulate_signal_overlay
from ._variants import _family_for_variant
from ._evidence import (
    _select_signal_evidence_edge,
    _edge_payload_for_evidence,
    _current_evidence_signal,
    _signal_evidence_contributors,
    _signal_evidence_oos_periods,
    _evidence_trade_ledger,
    _evidence_stitched_backtest,
    _build_signal_evidence_payload,
    _read_best_evidence_snapshot,
)
from ._backtest import build_stored_best_backtest_chart_payload

# Cache objects accessed directly by tests (e.g. strategy_signals._SR_VARIANTS_CACHE.clear())
from ._shared import _BACKTEST_CACHE, _SR_INVERSION_CACHE, _SR_VARIANTS_CACHE, _SR_VARIANT_BACKTEST_CACHE

__all__ = [
    "router",
    "_get_or_compute",
    "_safe_float",
    "_score_to_label",
    "_get_all_representative_indicators",
    "_get_top_representative_indicator",
    "_sr_get_or_compute_variants",
    "load_ohlcv_for_symbol",
    "compute_score_inversion_levels",
    "compute_variant_detail",
    "detect_swing_levels",
    "compute_pivot_points",
    "compute_levels_support_resistance",
    "latest_rsi_variant_signal",
    "monte_carlo_equity_paths",
    "_sr_direct_objective_summary",
    "_sr_simulate_signal_overlay",
    "_family_for_variant",
    "_BACKTEST_CACHE",
    "_SR_INVERSION_CACHE",
    "_SR_VARIANTS_CACHE",
    "_SR_VARIANT_BACKTEST_CACHE",
]

# ---------------------------------------------------------------------------
# Monkeypatch propagation (test compatibility)
# ---------------------------------------------------------------------------
# In a flat module, LOAD_GLOBAL looks up names in one shared __dict__; pytest
# monkeypatch.setattr(strategy_signals, "X", fake) works because every
# function in the module sees the same dict.  In a package each submodule
# has its own global dict.  We fix this by replacing the module's __class__
# with a subclass whose __setattr__ propagates patches to each submodule
# that holds the same name — zero test changes, zero endpoint changes.
import sys as _sys
import types as _types

_PKG = __name__

class _PatchPropagator(_types.ModuleType):
    _SUBS = (
        "_shared", "_ensemble", "_support_resistance",
        "_variants", "_engine", "_evidence", "_backtest",
    )

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for sub in self._SUBS:
            submod = _sys.modules.get(f"{_PKG}.{sub}")
            if submod is not None and name in vars(submod):
                vars(submod)[name] = value

_sys.modules[__name__].__class__ = _PatchPropagator
